#!/usr/bin/env python3
"""
find_gap_leads.py — orchestrator for the find-gap-leads skill.

Finds early-stage Indian D2C / coach prospects that LACK the funnel/retention infra
Acme sells, scores them 0-100, and outputs ranked leads + a ready LinkedIn
note. $0 cost (Tavily free + Gemini/Groq free + Apollo free + Meta Ad Library free).

Two-step human checkpoint:
  Step A (default):  discover -> detect -> score -> SHOW TABLE -> stop.
  Step B (--proceed): enrich (surfaced bands) -> draft notes -> publish to Sheets/JSON.
This lets Alex eyeball the scored table before any Apollo/sheet writes happen.

Resumable: per-lead state saved under data/gap_runs/run_NNN/; re-runs skip work.

Usage:
  python3 tools/find_gap_leads.py --count 20 --persona d2c        # Step A
  python3 tools/find_gap_leads.py --proceed                       # Step B (latest run)
  python3 tools/find_gap_leads.py --count 5 --dry-run             # full run, no writes
  python3 tools/find_gap_leads.py --count 20 --new-run            # force a fresh run
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
GAP_RUNS = DATA / "gap_runs"
sys.path.insert(0, str(BASE))

from tools.utils.llm_rest import load_env, provider_status
from tools.utils.models import save_result, load_result, result_exists
from tools.utils.run_config import CreditTracker
from tools.utils.gap_models import GapLead
from tools.utils.tech_signatures import match_signatures
from tools.gap_discover import discover, existing_index
from tools.gap_discover_ads import discover_via_ads, has_token as has_apify
from tools.gap_detect import detect_infra
from tools.gap_enrich import enrich_lead
from tools.gap_score import score_lead
from tools.gap_draft import draft_linkedin_note, draft_dossier
from tools.gap_publish import publish


# ---------- run-dir helpers (standalone; mirror run_config logic on gap_runs) ----------

def _run_ids() -> list[str]:
    if not GAP_RUNS.exists():
        return []
    return sorted(d.name for d in GAP_RUNS.iterdir() if d.is_dir() and d.name.startswith("run_"))


def _next_run_id() -> str:
    ids = _run_ids()
    if not ids:
        return "run_001"
    return f"run_{int(ids[-1].split('_')[1]) + 1:03d}"


def init_run(new: bool) -> Path:
    ids = _run_ids()
    run_id = _next_run_id() if (new or not ids) else ids[-1]
    run_dir = GAP_RUNS / run_id
    for sub in ("discovered", "detected", "html", "scored", "final", "drafts"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    meta = run_dir / "meta.json"
    if not meta.exists():
        meta.write_text(json.dumps(
            {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(),
             "status": "running"}, indent=2))
    return run_dir


# ---------- table ----------

def print_table(leads: list[GapLead]):
    rows = sorted(leads, key=lambda l: (-l.gap_score, l.band))
    print("\n" + "=" * 92)
    print(f"{'COMPANY':<26}{'SCORE':>6}  {'BAND':<10}{'PERSONA':<14}{'MISSING / NOTE'}")
    print("-" * 92)
    for l in rows:
        if l.partner_flag:
            band, note = "PARTNER", "consultant -> referral"
        elif l.audience_flag:
            band, note = "AUDIENCE", "too-early -> nurture"
        else:
            band, note = l.band.upper(), (l.pain_signal or "")[:34]
        print(f"{l.company[:25]:<26}{l.gap_score:>6}  {band:<10}{l.persona[:13]:<14}{note}")
    print("=" * 92)
    clients = [l for l in leads if not l.partner_flag and not l.audience_flag and l.gap_score >= 50]
    pr = sum(1 for l in clients if l.band == "priority")
    sl = sum(1 for l in clients if l.band == "shortlist")
    print(f"{len(clients)} clients ({pr} priority, {sl} shortlist) | "
          f"{sum(1 for l in leads if l.partner_flag)} partners | "
          f"{sum(1 for l in leads if l.audience_flag)} audience | "
          f"{sum(1 for l in leads if not l.partner_flag and not l.audience_flag and l.gap_score < 50)} drop\n")


# ---------- phases ----------

def step_a(run_dir: Path, count: int, persona: str, use_llm: bool, tracker: CreditTracker,
           keywords: list[str] | None = None, render: bool = False, deep: bool = False) -> list[GapLead]:
    """discover -> detect -> score. Returns scored GapLeads (also persisted)."""
    disc_dir = run_dir / "discovered"
    saved = list(disc_dir.glob("*.json"))
    if saved:
        print(f"[find_gap_leads] resuming: {len(saved)} candidates already discovered")
        candidates = [load_result(p.stem, disc_dir) for p in saved]
    else:
        # Primary: Meta Ad Library via Apify (early-biased, domain-keyed, ability-to-pay
        # built in). Fallback: Tavily web search if no Apify token.
        if persona == "d2c" and has_apify():
            print("[find_gap_leads] discovery: Meta Ad Library (Apify)")
            candidates = discover_via_ads(count, keywords=keywords, existing=existing_index())
        else:
            if persona == "d2c":
                print("[find_gap_leads] discovery: Tavily fallback (no APIFY_API_TOKEN — "
                      "add one for the better ads-based source)")
            candidates = discover(count, persona=persona, existing=existing_index())
        for c in candidates:
            gl = GapLead.from_candidate(c)
            save_result(gl, disc_dir, "id")
        tracker.track("tavily", len(candidates))

    leads: list[GapLead] = []
    scored_dir = run_dir / "scored"
    for c in candidates:
        gl = GapLead.from_candidate(c) if "id" not in c else GapLead.from_dict(c)
        if result_exists(gl.id, scored_dir):
            leads.append(GapLead.from_dict(load_result(gl.id, scored_dir)))
            continue

        infra = detect_infra(gl.domain, cache_dir=run_dir / "html", render=render, deep=deep) if gl.domain else match_signatures("")
        save_result(_InfraHolder(gl.id, infra), run_dir / "detected", "id")
        # meta_ads_active comes from discovery (ad-library-sourced leads carry it), not a live check
        sc = score_lead(gl.to_dict(), infra,
                        signals={"meta_ads_active": gl.meta_ads_active}, use_llm=use_llm)
        gl.infra_detected = infra
        gl.persona = sc["persona"]
        gl.gap_score = sc["gap_score"]
        gl.band = sc["band"]
        gl.score_components = sc["score_components"]
        gl.hard_gate = sc["hard_gate"]
        gl.partner_flag = sc["partner_flag"]
        gl.audience_flag = sc["audience_flag"]
        gl.reply_speed_test_pending = sc["reply_speed_test_pending"]
        gl.reasoning = sc["reasoning"]
        gl.meta_ads_active = sc.get("meta_ads_active")
        gl.sync_legacy()
        save_result(gl, scored_dir, "id")
        leads.append(gl)
        print(f"  scored {gl.company[:30]:<32} {gl.gap_score:>3} {gl.band}")
    return leads


def step_b(run_dir: Path, leads: list[GapLead], dry_run: bool, tracker: CreditTracker) -> dict:
    """enrich (surfaced) -> draft notes -> publish."""
    final_dir = run_dir / "final"
    for gl in leads:
        if gl.partner_flag or gl.audience_flag:
            save_result(gl, final_dir, "id")
            continue
        d = gl.to_dict()
        if gl.band in ("priority", "shortlist") and tracker.can_use("apollo"):
            enrich_lead(d)
            tracker.track("apollo")
            gl.contact_email = d.get("contact_email", gl.contact_email)
            gl.contact_linkedin = d.get("contact_linkedin", gl.contact_linkedin)
            gl.contact_name = d.get("contact_name", gl.contact_name)
            gl.enriched = True
        if gl.band in ("priority", "shortlist", "watchlist"):
            gl.linkedin_note = draft_linkedin_note(gl.to_dict(), gl.infra_detected)
        if gl.band == "priority":
            sc = {"persona": gl.persona, "band": gl.band, "gap_score": gl.gap_score}
            (run_dir / "drafts" / f"{gl.id}.md").write_text(draft_dossier(gl.to_dict(), gl.infra_detected, sc))
        save_result(gl, final_dir, "id")

    summary = publish([gl.to_dict() for gl in leads], dry_run=dry_run)
    tracker.save()
    return summary


# minimal holder so save_result can persist the infra dict keyed by id
class _InfraHolder:
    def __init__(self, _id, infra):
        self.id = _id
        self._infra = infra
    def to_dict(self):
        return {"id": self.id, **self._infra}


def main():
    load_env()
    ap = argparse.ArgumentParser(description="Find early-stage gap-fit leads ($0)")
    ap.add_argument("--count", type=int, default=20, help="target new leads (Step A)")
    ap.add_argument("--persona", default="d2c", choices=["d2c", "coach", "consultant"])
    ap.add_argument("--proceed", action="store_true", help="Step B: enrich+draft+publish latest run")
    ap.add_argument("--dry-run", action="store_true", help="full run, no Sheet/JSON writes")
    ap.add_argument("--new-run", action="store_true", help="force a fresh run dir")
    ap.add_argument("--no-llm", action="store_true", help="deterministic only (no LLM)")
    ap.add_argument("--keywords", default=None,
                    help="comma-separated category keywords to override DEFAULT_KEYWORDS (d2c/Apify only)")
    ap.add_argument("--render", action="store_true",
                    help="render sites with Playwright before detection (free, catches JS-injected stacks)")
    ap.add_argument("--deep-detect", action="store_true",
                    help="ScrapeGraphAI+Groq rendered LLM read per site (needs scrapegraphai; falls back if absent)")
    args = ap.parse_args()

    print(f"[find_gap_leads] LLM providers: {provider_status()}")
    if args.deep_detect:
        from tools.gap_deep_detect import deep_detect_available, unavailable_reason
        if deep_detect_available():
            print("[find_gap_leads] deep detect: ON (ScrapeGraphAI + Groq, rendered)")
        else:
            print(f"[find_gap_leads] deep detect requested but unavailable ({unavailable_reason()}); "
                  f"using {'rendered ' if args.render else ''}substring detect")
    run_dir = init_run(new=args.new_run and not args.proceed)
    print(f"[find_gap_leads] run: {run_dir.name}")

    tracker = CreditTracker(run_dir=run_dir, budgets={"apollo": 30})
    # register the free-tier services this skill uses (for the credits summary)
    tracker.usage.setdefault("groq", {"calls": 0, "budget": 1000, "service": "Groq (free)"})
    tracker.usage.setdefault("gemini", {"calls": 0, "budget": 250, "service": "Gemini (free)"})

    kw = [k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else None
    leads = step_a(run_dir, args.count, args.persona, use_llm=not args.no_llm, tracker=tracker,
                   keywords=kw, render=args.render, deep=args.deep_detect)
    print_table(leads)

    if not (args.proceed or args.dry_run):
        print("Review the table above. To enrich the surfaced leads, draft LinkedIn notes,")
        print(f"and publish to the Gap Leads sheet, re-run:\n  python3 tools/find_gap_leads.py --proceed")
        (run_dir / "meta.json").write_text(json.dumps(
            {"run_id": run_dir.name, "status": "scored", "n": len(leads)}, indent=2))
        return

    summary = step_b(run_dir, leads, dry_run=args.dry_run, tracker=tracker)
    print(f"[find_gap_leads] published: {json.dumps(summary)}")
    if not args.dry_run:
        flagged = [l.company for l in leads if l.reply_speed_test_pending]
        if flagged:
            print(f"\n⚠ Manual reply-speed test before outreach: {', '.join(flagged[:8])}")


if __name__ == "__main__":
    main()
