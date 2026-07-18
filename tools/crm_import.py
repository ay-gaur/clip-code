#!/usr/bin/env python3
"""
crm_import.py — one-time seed: read the 3 lead tabs from the CLIP OS Google Sheet
and upsert them into the Supabase `leads` table (the CRM's source of truth).

Reuses sheets_log auth (token at ~/.google-mcp/tokens/acmestudio.json or
GOOGLE_TOKEN_B64). Writes to Supabase via its REST API (PostgREST) using the
service-role key. Idempotent: upserts on (source, source_row), so re-running is safe.

Env (add to claude_automations/.env):
  SUPABASE_URL                e.g. https://abcd.supabase.co
  SUPABASE_SERVICE_ROLE_KEY   service_role secret (server-only)

Usage:
  python3 tools/crm_import.py --dry-run     # map + print, no writes
  python3 tools/crm_import.py               # live upsert
  python3 tools/crm_import.py --only-new    # skip rows whose (source,source_row) already exists
"""
import argparse
import os
import re
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
import requests
from tools.utils.llm_rest import load_env
from tools.sheets_log import _get_services

SHEET_ID = "16NoNcWixfeYyfKV3Cz2APO4cSsp-odp1aO79FRHBEEE"
# 3 projects only. `source` column == project. The D2C book is retired (deleted).
TABS = {
    "interior": "NCR Interior Designers — Jun12",
    "acme": "Service Leads — Jun12",
}

# Status text (from the sheets) -> canonical stage
STAGE_MAP = [
    (("won", "client", "closed won", "signed"), "won"),
    (("lost", "dead", "no ", "not interested", "rejected"), "lost"),
    (("not now", "later", "archived", "nurture", "parked", "do not contact"), "not_now"),
    (("proposal", "quote", "scoped"), "proposal"),
    (("call", "booked", "meeting", "demo"), "call_booked"),
    (("replied", "responded", "reply"), "replied"),
    (("contacted", "sent", "reached", "outreach", "dm sent"), "contacted"),
]


def to_stage(status: str, default: str = "new") -> str:
    s = (status or "").strip().lower()
    if not s:
        return default
    for keys, stage in STAGE_MAP:
        if any(k in s for k in keys):
            return stage
    return default


def _int(v):
    if v is None:
        return None
    m = re.search(r"\d[\d,]*", str(v))
    return int(m.group(0).replace(",", "")) if m else None


def _float(v):
    if v is None:
        return None
    m = re.search(r"\d+(\.\d+)?", str(v))
    return float(m.group(0)) if m else None


def _clean(v):
    v = (v or "").strip()
    return v or None


def read_tab(sheets, tab) -> list[dict]:
    res = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"'{tab}'!A1:Z").execute()
    rows = res.get("values", [])
    if not rows:
        return []
    headers = [h.strip() for h in rows[0]]
    out = []
    for r in rows[1:]:
        r = r + [""] * (len(headers) - len(r))  # pad short rows
        out.append({headers[i]: r[i] for i in range(len(headers))})
    return out


# ── per-source mappers (return a unified `leads` dict) ──────────────────────────

def map_interior(row, idx):
    addr = _clean(row.get("Address"))
    why = _clean(row.get("Why we chose them"))
    return {
        "source": "interior", "source_row": _int(row.get("#")) or idx,
        "business_name": _clean(row.get("Business name")) or "(unnamed)",
        "phone": _clean(row.get("Phone")),
        "category": _clean(row.get("Category")),
        "city": _clean(row.get("City")), "region": "NCR",
        "reason_gap": why,
        "evidence": _clean(row.get("Fact-check evidence")),
        "rating": _float(row.get("Rating")), "reviews": _int(row.get("Reviews")),
        "maps_url": _clean(row.get("Google Maps")),
        "notes": f"Address: {addr}" if addr else None,
        "stage": "new",
    }


def map_service(row, idx):
    return {
        "source": "acme", "source_row": idx,
        "business_name": _clean(row.get("Company")) or "(unnamed)",
        "contact_name": _clean(row.get("Founder")),
        "category": _clean(row.get("Type")),
        "what_they_do": _clean(row.get("What they do")),
        "linkedin": _clean(row.get("LinkedIn")), "instagram": _clean(row.get("Instagram")),
        "domain": _clean(row.get("Domain")), "region": _clean(row.get("Region")),
        "reason_gap": _clean(row.get("The gap (client acquisition)")),
        "cold_email_subject": _clean(row.get("Cold email subject")),
        "cold_email_body": _clean(row.get("Cold email")),
        "linkedin_note": _clean(row.get("LinkedIn note")), "dm": _clean(row.get("DM")),
        "stage": to_stage(row.get("Status")),
    }


def map_d2c(row, idx):
    role = _clean(row.get("Role"))
    sells = _clean(row.get("Sells on"))
    notes = "; ".join(x for x in [f"Role: {role}" if role else None,
                                  f"Sells on: {sells}" if sells else None] if x) or None
    return {
        "source": "d2c", "source_row": idx,
        "business_name": _clean(row.get("Company")) or "(unnamed)",
        "contact_name": _clean(row.get("Founder")),
        "what_they_do": _clean(row.get("What they do")),
        "linkedin": _clean(row.get("LinkedIn")) or _clean(row.get("Founder LinkedIn")),
        "instagram": _clean(row.get("Instagram")), "email": _clean(row.get("Email (business)")),
        "city": _clean(row.get("City")), "category": _clean(row.get("Scale / signal")),
        "reason_gap": _clean(row.get("Gaps (missing)")),
        "value_to_offer": _clean(row.get("Value to offer")),
        "personalization_hook": _clean(row.get("Personalization hook")),
        "gap_score": _int(row.get("Gap score")),
        "cold_email_subject": _clean(row.get("Cold email subject")),
        "cold_email_body": _clean(row.get("Cold email")),
        "linkedin_note": _clean(row.get("LinkedIn note")), "dm": _clean(row.get("DM")),
        "notes": notes,
        # archived old ICP: park unless the sheet already had a further status
        "stage": to_stage(row.get("Status"), default="not_now"),
    }


MAPPERS = {"interior": map_interior, "acme": map_service, "d2c": map_d2c}


def supabase_existing_keys(base, headers):
    """Return set of (source, source_row) already in Supabase."""
    r = requests.get(f"{base}/rest/v1/leads?select=source,source_row", headers=headers, timeout=30)
    r.raise_for_status()
    return {(x["source"], x["source_row"]) for x in r.json()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only-new", action="store_true", help="skip (source,source_row) already in Supabase")
    args = ap.parse_args()

    load_env()
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not args.dry_run and (not base or not key):
        sys.exit("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env (or use --dry-run)")

    _, sheets = _get_services()
    all_rows = []
    for source, tab in TABS.items():
        rows = read_tab(sheets, tab)
        mapped = [MAPPERS[source](r, i + 1) for i, r in enumerate(rows)]
        print(f"[{source}] {tab}: {len(mapped)} rows")
        all_rows.extend(mapped)
    print(f"total mapped: {len(all_rows)}")

    # PostgREST requires every row in a batch to have identical keys.
    # Collect the union of all keys and backfill None for any missing.
    all_keys = set()
    for r in all_rows:
        all_keys.update(r.keys())
    all_rows = [{k: r.get(k) for k in all_keys} for r in all_rows]

    if args.dry_run:
        import json
        print(json.dumps(all_rows[:2] + all_rows[-1:], indent=2, ensure_ascii=False))
        print("(dry run — nothing written)")
        return

    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    if args.only_new:
        existing = supabase_existing_keys(base, headers)
        before = len(all_rows)
        all_rows = [r for r in all_rows if (r["source"], r["source_row"]) not in existing]
        print(f"--only-new: {before - len(all_rows)} already present, {len(all_rows)} to insert")

    # upsert in chunks of 100 on (source, source_row)
    up_headers = {**headers, "Prefer": "resolution=merge-duplicates,return=minimal"}
    url = f"{base}/rest/v1/leads?on_conflict=source,source_row"
    ok = 0
    for i in range(0, len(all_rows), 100):
        chunk = all_rows[i:i + 100]
        resp = requests.post(url, headers=up_headers, json=chunk, timeout=60)
        if resp.status_code >= 300:
            sys.exit(f"Supabase {resp.status_code}: {resp.text[:400]}")
        ok += len(chunk)
        print(f"  upserted {ok}/{len(all_rows)}")
    print(f"done: {ok} leads upserted into Supabase")


if __name__ == "__main__":
    main()
