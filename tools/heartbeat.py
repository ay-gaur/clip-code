#!/usr/bin/env python3
"""
heartbeat.py — CLIP background intelligence engine.

Runs rule-based analyzers across pipeline, leads, tasks, and subscriptions.
If ≥2 signals are detected, fires an LLM call to synthesize an insight.
Writes output to data/ai-updates.md and logs run metadata to data/heartbeat.json.

No email. No noise. Surfaces at CEO session open only.

Usage:
  python3 tools/heartbeat.py              # full run
  python3 tools/heartbeat.py --dry-run   # analyze + print, no writes
  python3 tools/heartbeat.py --force-llm # run LLM even if <2 signals

Requires in .env:
  ANTHROPIC_API_KEY
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
DATA = BASE / "data"

try:
    from tools.credits import track_usage
except ImportError:
    from credits import track_usage

STALE_PIPELINE_DAYS = 5      # pipeline contact considered stale after 5 days
LEAD_UNREVIEWED_DAYS = 3     # lead considered stale if not reviewed in 3 days
SUBSCRIPTION_ALERT_DAYS = 7  # subscription alert window
LLM_SIGNAL_THRESHOLD = 1     # fire LLM if this many signals detected


# ── Env loading ───────────────────────────────────────────────────────────────

def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


# ── Analyzers ─────────────────────────────────────────────────────────────────

def analyze_pipeline() -> dict | None:
    """Flag stale active contacts and hot deals with no recent contact."""
    path = DATA / "pipeline.json"
    if not path.exists():
        return None

    try:
        contacts = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None

    today = date.today()
    stale = []
    hot_no_contact = []

    for c in contacts:
        stage = c.get("stage", "")
        last = c.get("last_contact")
        name = c.get("name", "?")
        company = c.get("company", "")

        if stage in ("client", "closed_lost"):
            continue

        days_since = None
        if last:
            days_since = (today - date.fromisoformat(last)).days

        if stage in ("proposal", "negotiation"):
            if days_since is None or days_since >= STALE_PIPELINE_DAYS:
                hot_no_contact.append(f"{name} ({company}) — {stage}, {days_since or 'never'}d")
        elif days_since is not None and days_since >= STALE_PIPELINE_DAYS:
            stale.append(f"{name} ({company}) — {stage}, {days_since}d")

    if not stale and not hot_no_contact:
        return None

    parts = []
    if hot_no_contact:
        parts.append(f"{len(hot_no_contact)} hot deal(s) need follow-up: {', '.join(hot_no_contact)}")
    if stale:
        parts.append(f"{len(stale)} contact(s) going stale: {', '.join(stale)}")

    return {
        "signal": "pipeline",
        "label": "Pipeline",
        "summary": "; ".join(parts),
        "count": len(stale) + len(hot_no_contact),
    }


def analyze_leads() -> dict | None:
    """Flag unreviewed or stale leads."""
    path = DATA / "leads.json"
    if not path.exists():
        return None

    try:
        leads = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None

    today = date.today()
    unreviewed = []

    for lead in leads:
        status = lead.get("status", "new")
        if status in ("contacted", "closed", "rejected"):
            continue

        reviewed = lead.get("last_reviewed")
        company = lead.get("company") or lead.get("name") or "Unknown"

        if reviewed is None:
            unreviewed.append(company)
        else:
            days = (today - date.fromisoformat(reviewed)).days
            if days >= LEAD_UNREVIEWED_DAYS:
                unreviewed.append(f"{company} ({days}d)")

    if not unreviewed:
        return None

    return {
        "signal": "leads",
        "label": "Leads",
        "summary": f"{len(unreviewed)} unreviewed lead(s): {', '.join(unreviewed[:5])}{'...' if len(unreviewed) > 5 else ''}",
        "count": len(unreviewed),
    }


def analyze_tasks() -> dict | None:
    """Flag urgent tasks."""
    path = DATA / "tasks.md"
    if not path.exists():
        return None

    text = path.read_text()
    urgent = []
    in_urgent = False

    for line in text.splitlines():
        lower = line.lower().strip()
        if lower.startswith("## urgent"):
            in_urgent = True
        elif lower.startswith("## "):
            in_urgent = False
        elif in_urgent and line.strip().startswith("- "):
            urgent.append(line.strip()[2:].strip())

    if not urgent:
        return None

    return {
        "signal": "tasks_urgent",
        "label": "Tasks",
        "summary": f"{len(urgent)} urgent task(s): {', '.join(urgent[:3])}{'...' if len(urgent) > 3 else ''}",
        "count": len(urgent),
    }


def analyze_gmail() -> dict | None:
    """Flag unanswered client emails older than 24h."""
    try:
        from tools.fetch_gmail import fetch_unanswered_client_threads
        contacts_path = DATA / "contacts.json"
        unanswered = fetch_unanswered_client_threads(contacts_path=contacts_path, days=3)
    except Exception:
        return None

    if not unanswered:
        return None

    parts = []
    for t in unanswered[:3]:
        parts.append(f"{t['contact_name']} ({t['hours_since']}h): \"{t['subject']}\"")

    return {
        "signal": "gmail_unanswered",
        "label": "Email",
        "summary": f"{len(unanswered)} unanswered thread(s): {'; '.join(parts)}{'...' if len(unanswered) > 3 else ''}",
        "count": len(unanswered),
    }


def analyze_subscriptions() -> dict | None:
    """Flag subscriptions billing within SUBSCRIPTION_ALERT_DAYS."""
    path = DATA / "subscriptions.json"
    if not path.exists():
        return None

    try:
        subs = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None

    today = date.today()
    due_soon = []

    for s in subs:
        if s.get("status") != "active":
            continue
        nb = s.get("next_billing")
        if not nb:
            continue
        try:
            billing_date = date.fromisoformat(nb)
            days = (billing_date - today).days
            if 0 <= days <= SUBSCRIPTION_ALERT_DAYS:
                name = s.get("name", "?")
                cost = s.get("amount") or s.get("amount_inr") or "?"
                currency = "$" if s.get("amount") else "₹"
                due_soon.append(f"{name} ({currency}{cost}, {days}d)")
        except ValueError:
            continue

    if not due_soon:
        return None

    return {
        "signal": "subscriptions",
        "label": "Subscriptions",
        "summary": f"{len(due_soon)} renewal(s) due soon: {', '.join(due_soon)}",
        "count": len(due_soon),
    }


# ── LLM Synthesis ─────────────────────────────────────────────────────────────

def call_llm_insight(signals: list[dict]) -> str:
    """Call Anthropic to synthesize a short, actionable insight from signals."""
    try:
        import anthropic
    except ImportError:
        return "(anthropic SDK not installed — run: pip3 install anthropic)"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "(ANTHROPIC_API_KEY not set — skipping LLM synthesis)"

    signal_text = "\n".join(f"- {s['label']}: {s['summary']}" for s in signals)
    today_str = date.today().strftime("%A, %B %d")

    prompt = f"""You are CLIP, Alex's executive assistant AI. Today is {today_str}.

The following signals were detected during a background scan:

{signal_text}

Write a short (3-5 sentences max), direct, actionable insight for Alex.
- No preamble. No "Here's what I found." Just the insight.
- Be specific about what needs attention and why.
- Prioritize the most urgent signal first.
- Suggest one concrete next action.
- Tone: colleague/friend, casual and direct."""

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        track_usage("claude-haiku-4-5-20251001", response.usage.input_tokens, response.usage.output_tokens)
        return response.content[0].text.strip()
    except Exception as e:
        return f"(LLM synthesis failed: {e})"


# ── Output Writers ─────────────────────────────────────────────────────────────

def write_ai_updates(signals: list[dict], insight: str | None, dry_run: bool) -> None:
    """Write the latest heartbeat insight to data/ai-updates.md."""
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# AI Updates",
        "",
        f"## Latest Insight — {timestamp}",
        f"_Generated by heartbeat · {len(signals)} signal(s) detected_",
        "",
    ]

    for s in signals:
        lines.append(f"**{s['label']}:** {s['summary']}")

    if insight:
        lines += ["", "**Synthesis:**", insight]

    lines += ["", "---", ""]

    content = "\n".join(lines)

    if dry_run:
        print("\n── ai-updates.md (dry run) ──────────────────")
        print(content)
    else:
        (DATA / "ai-updates.md").write_text(content)


def write_heartbeat_log(signals: list[dict], llm_fired: bool, dry_run: bool) -> None:
    """Append run metadata to data/heartbeat.json."""
    log_path = DATA / "heartbeat.json"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "signals": [s["signal"] for s in signals],
        "signal_count": len(signals),
        "llm_fired": llm_fired,
        "insight_written": len(signals) > 0,
    }

    if dry_run:
        print("\n── heartbeat.json entry (dry run) ──────────")
        print(json.dumps(entry, indent=2))
        return

    history = []
    if log_path.exists():
        try:
            history = json.loads(log_path.read_text())
        except json.JSONDecodeError:
            history = []

    history.append(entry)
    # Keep last 30 runs
    history = history[-30:]
    log_path.write_text(json.dumps(history, indent=2))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CLIP Heartbeat — background intelligence engine")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and print, no writes")
    parser.add_argument("--force-llm", action="store_true", help="Run LLM even if <2 signals")
    args = parser.parse_args()

    load_env()

    print(f"[heartbeat] Running — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Run all analyzers
    analyzers = [analyze_pipeline, analyze_leads, analyze_tasks, analyze_subscriptions, analyze_gmail]
    signals = [result for fn in analyzers if (result := fn()) is not None]

    print(f"[heartbeat] {len(signals)} signal(s) detected: {[s['signal'] for s in signals]}")

    if not signals:
        print("[heartbeat] No signals. All clear.")
        if not args.dry_run:
            # Write clean state
            (DATA / "ai-updates.md").write_text(
                f"# AI Updates\n\n_Last checked: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')} — no signals detected._\n"
            )
            write_heartbeat_log([], False, dry_run=False)
        return

    # Print signals
    for s in signals:
        print(f"  → {s['label']}: {s['summary']}")

    # Decide whether to fire LLM
    llm_fired = False
    insight = None
    should_fire_llm = len(signals) >= LLM_SIGNAL_THRESHOLD or args.force_llm

    if should_fire_llm:
        print(f"[heartbeat] {len(signals)} signals ≥ threshold ({LLM_SIGNAL_THRESHOLD}) — calling LLM...")
        insight = call_llm_insight(signals)
        llm_fired = True
        print(f"[heartbeat] Insight generated.")
    else:
        print(f"[heartbeat] Only {len(signals)} signal(s) — below threshold, skipping LLM.")

    # Write outputs
    write_ai_updates(signals, insight, args.dry_run)
    write_heartbeat_log(signals, llm_fired, args.dry_run)

    if not args.dry_run:
        print(f"[heartbeat] Written → data/ai-updates.md + data/heartbeat.json")

    # Push to Telegram if LLM fired
    if llm_fired and insight and not args.dry_run:
        try:
            sys.path.insert(0, str(BASE))
            from tools.notify import send_heartbeat_digest
            send_heartbeat_digest(signals, insight)
        except Exception as e:
            print(f"[heartbeat] Telegram push failed: {e}", file=sys.stderr)

    # Log to task-log
    if not args.dry_run:
        sys.path.insert(0, str(BASE))
        from tools.log_entry import append_entry
        note = f"{len(signals)} signals: {', '.join(s['signal'] for s in signals)}; LLM={'yes' if llm_fired else 'no'}"
        append_entry("heartbeat", "run", note)


if __name__ == "__main__":
    main()
