#!/usr/bin/env python3
"""
gap_publish.py — Phase 6: route scored leads to Sheets + leads.json + notify.

Routing (every lead lands somewhere useful):
  partner_flag           -> "Partners" tab        (referral track)
  audience_flag          -> "Audience" tab         (too-early nurture / edu audience)
  scored client (>=50)   -> "Gap Leads" tab        (priority/shortlist/watchlist)
  scored drop (<50)      -> leads.json only         (kept, not surfaced)

leads.json is an UPSERT keyed by id (sha1 domain), so re-runs update in place
instead of duplicating. Sheets/JSON writes are skipped in dry_run.

Usage: called by the orchestrator. Operates on a list of GapLead dicts.
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
sys.path.insert(0, str(BASE))
from tools.sheets_log import append_row
from tools.notify import send_telegram
from tools.log_entry import append_entry


def _client_row(l: dict) -> dict:
    return {
        "Company": l.get("company", ""),
        "Founder": l.get("contact_name", ""),
        "LinkedIn": l.get("contact_linkedin", ""),
        "Domain": l.get("domain", ""),
        "Gap Score": l.get("gap_score", 0),
        "Band": l.get("band", ""),
        "Persona": l.get("persona", ""),
        "Missing Infra": l.get("pain_signal", ""),
        "Meta Ads": l.get("meta_ads_active"),
        "LinkedIn Note": l.get("linkedin_note", ""),
        "Source": l.get("source_url", ""),
    }


def _partner_row(l: dict) -> dict:
    return {
        "Name": l.get("contact_name", ""),
        "Company": l.get("company", ""),
        "LinkedIn": l.get("contact_linkedin", ""),
        "Domain": l.get("domain", ""),
        "Why Partner": l.get("reasoning", "consultant -> referral partner"),
        "Source": l.get("source_url", ""),
    }


def _audience_row(l: dict) -> dict:
    return {
        "Company": l.get("company", ""),
        "Founder": l.get("contact_name", ""),
        "Domain": l.get("domain", ""),
        "Stage": l.get("hard_gate", "too_early"),
        "Note": l.get("reasoning", "") or l.get("pain_signal", ""),
        "Source": l.get("source_url", ""),
    }


def _load_leads() -> list:
    path = DATA / "leads.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def _upsert_leads(gap_leads: list[dict]) -> tuple[int, int]:
    """Merge gap leads into data/leads.json by id. Returns (updated, added)."""
    existing = _load_leads()
    by_id = {l.get("id"): i for i, l in enumerate(existing) if l.get("id")}
    updated = added = 0
    for gl in gap_leads:
        gid = gl.get("id")
        if gid and gid in by_id:
            existing[by_id[gid]] = gl
            updated += 1
        else:
            existing.append(gl)
            if gid:
                by_id[gid] = len(existing) - 1
            added += 1
    DATA.mkdir(exist_ok=True)
    (DATA / "leads.json").write_text(json.dumps(existing, indent=2))
    return updated, added


def publish(gap_leads: list[dict], *, dry_run: bool = False, do_notify: bool = True) -> dict:
    """Route + persist scored leads. Returns a summary dict."""
    clients = [l for l in gap_leads if not l.get("partner_flag") and not l.get("audience_flag")
               and l.get("gap_score", 0) >= 50]
    partners = [l for l in gap_leads if l.get("partner_flag")]
    audience = [l for l in gap_leads if l.get("audience_flag")]
    drops = [l for l in gap_leads if not l.get("partner_flag") and not l.get("audience_flag")
             and l.get("gap_score", 0) < 50]

    priority = [l for l in clients if l.get("band") == "priority"]
    shortlist = [l for l in clients if l.get("band") == "shortlist"]

    summary = {
        "clients": len(clients), "priority": len(priority), "shortlist": len(shortlist),
        "watchlist": len(clients) - len(priority) - len(shortlist),
        "partners": len(partners), "audience": len(audience), "drops": len(drops),
    }

    if dry_run:
        print(f"[gap_publish] DRY RUN — would write: {summary}")
        return summary

    for l in clients:
        append_row("Gap Leads", _client_row(l))
    for l in partners:
        append_row("Partners", _partner_row(l))
    for l in audience:
        append_row("Audience", _audience_row(l))

    upd, add = _upsert_leads(gap_leads)
    summary["leads_json_updated"], summary["leads_json_added"] = upd, add

    append_entry("find-gap-leads", "publish",
                 f"{summary['clients']} clients ({summary['priority']}P/{summary['shortlist']}S), "
                 f"{summary['partners']} partners, {summary['audience']} audience")

    if do_notify and (clients or partners or audience):
        send_telegram(
            f"*find-gap-leads*\n"
            f"{summary['clients']} clients ({summary['priority']} priority, {summary['shortlist']} shortlist)\n"
            f"{summary['partners']} partners | {summary['audience']} audience\n"
            f"_Gap Leads sheet updated_",
            urgency="silent",
        )
    return summary


if __name__ == "__main__":
    print("[gap_publish] module — called by the find_gap_leads orchestrator")
