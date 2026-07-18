#!/usr/bin/env python3
"""birdseye.py — render the one-page bird's-eye dashboard from CLIP's data layer.

Usage:
  python3 tools/birdseye.py                                    # cached signals
  python3 tools/birdseye.py --live-file .tmp/live.json --open  # the "hi clip" path
  python3 tools/birdseye.py --skin terminal --out data/birdseye-terminal.html

Reads : data/tasks.md, data/task-log.json, live-signals JSON (optional)
Writes: data/birdseye.html (default), data/birdseye_live.json (signal cache)

The CONFIG block is the editable state (lanes, gates, systems, money, commands).
Update it when reality changes — everything else derives from the data files.
Date-dependent numbers (countdowns, drought, warmup day) are computed by the
page's own JS at view time, so the page stays honest between regenerations.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SKINS = Path(__file__).resolve().parent / "birdseye_skins"
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_SKIN = "f1"  # the picked design (D51): F1 pit-wall, 3 clickable views

CONFIG = {
    "directive": "SAMPLE DIRECTIVE — replace with your own operating priority",
    "money": {
        "last": "$0 · sample project · —",
        "last_date": "2026-01-01",
        "burn": "$X/mo fixed + API",
    },
    "warmup": {"label": "sample warmup", "start": "2026-01-01", "end": "2026-01-31"},
    "gates": [
        {"date": "2026-02-01", "label": "Sample gate A", "note": "describe a decision point here"},
        {"date": "2026-02-15", "label": "Sample gate B", "note": "another upcoming checkpoint"},
    ],
    "lanes": [
        {"rank": 1, "key": "alpha", "name": "Sample Lane Alpha", "crew": "OWNER · CITY · SOLO CREW",
         "status": "ball in our pit", "tone": "ok", "distance": "ONE STEP AWAY",
         "last": "Most recent update for this lane",
         "next": "The next action to take",
         "blocker": None,
         "keywords": ["alpha", "sample"],
         "detail": [
             {"label": "Context", "text": "Placeholder detail — the real state lives in your data layer."},
             {"label": "Note", "text": "This CONFIG is sample data; edit it to reflect your own pipeline."},
         ]},
        {"rank": 2, "key": "beta", "name": "Sample Lane Beta", "crew": "PROSPECT · CHANNEL · SOLO CREW",
         "status": "formation lap", "tone": "warn", "distance": "GATE AHEAD",
         "last": "A recent signal for this lane",
         "next": "What unblocks it",
         "blocker": "waiting on an external event",
         "keywords": ["beta", "sample"],
         "detail": [
             {"label": "Offer", "text": "Describe the offer for this lane."},
             {"label": "Gate", "text": "Describe the kill / go gate."},
         ]},
    ],
    "dead_lanes": [
        {"name": "Sample retired lane", "tag": "DNS", "ref": "why it was parked"},
    ],
    "notices": [
        {"when": "OPEN", "text": "Sample notice — surface anything that needs attention here."},
    ],
    "people": [
        {"name": "Sample Studio", "state": "on", "label": "SOLO", "note": "team note"},
        {"name": "Prospect · Lane Alpha", "state": "on", "label": "HOT", "note": "status note"},
    ],
    "revenue": {"title": "Revenue received (sample)", "max": 3, "unit": "$", "suffix": "k",
                "months": [["JAN", 0], ["FEB", 0], ["MAR", 0], ["APR", 0], ["MAY", 0], ["JUN", 0], ["JUL", 0]],
                "note": "SAMPLE"},
    "systems": [
        {"name": "CLIP in-session (CEO + skills)", "state": "on", "note": "the daily driver"},
        {"name": "Google Workspace MCP", "state": "on", "note": "Gmail / Calendar"},
        {"name": "Data layer", "state": "on", "note": "pipeline / tasks / contacts"},
        {"name": "Heartbeat / Telegram", "state": "off", "note": "in-session only"},
    ],
    "commands": [
        {"say": "hi clip", "does": "pulse + regenerate this page"},
        {"say": "brief me", "does": "morning brief"},
        {"say": "what's on my plate?", "does": "tasks"},
        {"say": "where's my pipeline at?", "does": "pipeline"},
        {"say": "birdseye", "does": "rebuild + open this page"},
    ],
    "deck": {
        "active": [
            {"name": "hi clip", "does": "Session-open pulse: brief + pipeline + tasks + this dashboard.", "say": "hi clip", "lane": None},
            {"name": "/morning-brief", "does": "Tasks due, pipeline state, schedule — one tight brief.", "say": "brief me", "lane": None},
            {"name": "/task-check", "does": "See, add, or close tasks (urgent / week / backlog).", "say": "what's on my plate?", "lane": None},
            {"name": "/pipeline-status", "does": "Where every deal sits; move stages, add prospects.", "say": "where's my pipeline at?", "lane": "alpha"},
            {"name": "/draft-proposal", "does": "Structured client proposal → proposals/.", "say": "draft a proposal", "lane": "alpha"},
            {"name": "/prep-meeting", "does": "Prep brief from contact history.", "say": "prep me for a call", "lane": "alpha"},
            {"name": "/log-meeting", "does": "Save call notes + action items to contact history.", "say": "just got off a call with…", "lane": None},
            {"name": "/outreach-draft", "does": "Cold email / pitch drafts for a named lead.", "say": "draft outreach for X", "lane": "beta"},
            {"name": "/clean-inbox", "does": "Gmail triage: read, label, archive, find replies.", "say": "any replies?", "lane": None},
            {"name": "/skill-creator", "does": "Build or improve a CLIP skill when a gap shows up 3+ times.", "say": "build me a skill that…", "lane": None},
        ],
        "strategy": [
            {"name": "/audit", "does": "Four-Cs scoreboard of the whole AIOS + top-3 fixes.", "say": "audit my setup"},
            {"name": "/level-up", "does": "Weekly 3Ms ritual: find one automation, scope it, ship it.", "say": "let's level up"},
            {"name": "/deep-research", "does": "Multi-source, fact-checked research report on anything.", "say": "deep research: …"},
        ],
        "parked": [
            {"name": "/notifications", "does": "Telegram push manager — bot parked.", "note": "nothing is pushing"},
        ],
    },
    "hero_why": {
        "alpha": "Closest item on the board — a live prospect waiting on your move.",
        "beta": "Staged and waiting on a gate.",
        "default": "Top of the urgent list under your operating rule.",
    },
}



def read_tasks():
    """Parse data/tasks.md → {section: [task, ...]}."""
    sections, current = {}, None
    path = DATA / "tasks.md"
    if not path.exists():
        return sections
    for line in path.read_text(encoding="utf-8").splitlines():
        h = re.match(r"^##\s+(.*)$", line.strip())
        if h:
            current = h.group(1).strip()
            sections[current] = []
            continue
        t = re.match(r"^-\s+(.*)$", line.strip())
        if t and current:
            sections[current].append(t.group(1).strip())
    return sections


def read_activity(limit=8):
    """Last N task-log entries → [{when, what}]."""
    path = DATA / "task-log.json"
    if not path.exists():
        return []
    try:
        log = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    entries = [e for e in log if (e.get("note") or "").strip() not in ("", "(empty)")]
    out = []
    for e in entries[-limit:][::-1]:
        ts = e.get("timestamp") or e.get("date") or ""
        try:
            when = datetime.fromisoformat(ts).astimezone(IST).strftime("%b %d")
        except ValueError:
            when = ts[:10]
        out.append({"when": when, "what": e["note"].strip()})
    return out


def lane_for(text):
    low = text.lower()
    for lane in CONFIG["lanes"]:
        if any(k in low for k in lane["keywords"]):
            return lane["key"]
    return None


def load_live(live_file):
    """Load fresh live signals if given, else fall back to the cache.
    Returns (signals, fresh: bool)."""
    cache_path = DATA / "birdseye_live.json"
    if live_file:
        try:
            live = json.loads(Path(live_file).read_text(encoding="utf-8"))
            live["fetched_at"] = datetime.now(IST).isoformat()
            cache_path.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
            return live, True
        except (json.JSONDecodeError, OSError) as e:
            print(f"[birdseye] WARN: live file unusable ({e}); using cache", file=sys.stderr)
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8")), False
        except (json.JSONDecodeError, OSError):
            pass
    return {"inbox": [], "calendar": [], "fetched_at": None}, False


def build_data(live):
    tasks = read_tasks()
    urgent = tasks.get("Urgent", [])
    week = tasks.get("This Week", [])
    backlog = tasks.get("Backlog", [])

    if urgent:
        action = re.sub(r"\.?\s*FASTEST CASH IN PLAY\s*$", "", urgent[0]).strip()
    else:
        action = CONFIG["lanes"][0]["next"]
    lane_key = lane_for(action) or CONFIG["lanes"][0]["key"]
    hero = {
        "action": action,
        "why": CONFIG["hero_why"].get(lane_key, CONFIG["hero_why"]["default"]),
        "lane": lane_key,
        "queue": week[:3],
    }

    unread = sum(1 for m in live.get("inbox", []) if m.get("unread"))
    open_tasks = len(urgent) + len(week)
    live_lanes = sum(1 for l in CONFIG["lanes"] if l["tone"] != "bad")
    stats = [
        {"k": "DROUGHT", "kind": "drought", "date": CONFIG["money"]["last_date"], "tone": "bad", "sub": "since last invoice"},
        {"k": "NEXT GATE", "kind": "tminus", "gates": [g["date"] for g in CONFIG["gates"]], "tone": "warn", "sub": "nearest date"},
        {"k": "WARMUP", "kind": "warmup", "start": CONFIG["warmup"]["start"], "end": CONFIG["warmup"]["end"], "tone": "info", "sub": "acmestudio inbox"},
        {"k": "SIGNALS UNREAD", "v": str(unread), "tone": "warn" if unread else "ok", "sub": "from lane contacts"},
        {"k": "OPEN TASKS", "v": str(open_tasks), "tone": "info", "sub": f"+{len(backlog)} backlog"},
        {"k": "LANES LIVE", "v": f"{live_lanes} of {len(CONFIG['lanes'])}", "tone": "info", "sub": "1 frozen"},
    ]

    return {
        "generated_at": datetime.now(IST).isoformat(),
        "live_fetched_at": live.get("fetched_at"),
        "directive": CONFIG["directive"],
        "hero": hero,
        "stats": stats,
        "lanes": CONFIG["lanes"],
        "dead_lanes": CONFIG["dead_lanes"],
        "gates": CONFIG["gates"],
        "notices": CONFIG["notices"],
        "people": CONFIG["people"],
        "revenue": CONFIG["revenue"],
        "warmup": CONFIG["warmup"],
        "signals": {"inbox": live.get("inbox", []), "calendar": live.get("calendar", [])},
        "activity": read_activity(),
        "systems": CONFIG["systems"],
        "money": CONFIG["money"],
        "commands": CONFIG["commands"],
        "deck": CONFIG["deck"],
    }


def render(skin, data, out_path):
    tpl_path = SKINS / f"{skin}.html"
    if not tpl_path.exists():
        available = ", ".join(p.stem for p in SKINS.glob("*.html")) or "none"
        sys.exit(f"[birdseye] ERROR: skin '{skin}' not found (available: {available})")
    tpl = tpl_path.read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    marker = "/*__DATA__*/{}"
    if marker not in tpl:
        sys.exit(f"[birdseye] ERROR: skin '{skin}' is missing the {marker} marker")
    out_path.write_text(tpl.replace(marker, blob), encoding="utf-8")
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Render the bird's-eye dashboard")
    ap.add_argument("--skin", default=DEFAULT_SKIN, help="template name in tools/birdseye_skins/")
    ap.add_argument("--live-file", default=None, help="JSON with fresh inbox/calendar signals")
    ap.add_argument("--out", default=None, help="output path (default data/birdseye.html)")
    ap.add_argument("--open", action="store_true", help="open the result in the default browser")
    args = ap.parse_args()

    live, fresh = load_live(args.live_file)
    data = build_data(live)
    out = Path(args.out) if args.out else DATA / "birdseye.html"
    if not out.is_absolute():
        out = ROOT / out
    render(args.skin, data, out)
    print(f"[birdseye] wrote {out.relative_to(ROOT)} (skin={args.skin}, "
          f"signals={'fresh' if fresh else 'cached'})")
    if args.open:
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
