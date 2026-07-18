#!/usr/bin/env python3
"""
find_clinic_leads.py — local-clinic lead pull via Apify Google Maps scraper.

Purpose:
  Build a call sheet of clinics (v1: physiotherapists, Noida + Delhi) that have
  NO real website — prospects for the DFY website + appointment-booking-agent
  pitch (demo asset: archives/local-website-lane/Noida Physiotherapy).

  A clinic counts as "no real website" when its Google Maps website field is
  empty OR points at a directory/social profile (Practo, Justdial, Instagram,
  Facebook, linktr.ee, WhatsApp, business.site) — still website-less in sales
  terms.

How it works:
  1. For each city, run Apify actor compass~crawler-google-places
     (base "scraped place" event only — no paid add-ons)
  2. Post-filter: drop places with a real website; drop places without a phone
  3. Parse doctor name from the listing title where present ("Dr. <Name> ...")
  4. Dedupe by placeId, then by normalized phone
  5. Upsert into data/local_leads.json (keyed by place_id — re-runs are safe)
  6. Regenerate data/call_sheets/physio-noida-delhi-<date>.csv from the full
     file, sorted by review count desc (busiest clinics first)

Usage:
  python3 tools/find_clinic_leads.py --test              # 5 places, Noida only — account/cap check
  python3 tools/find_clinic_leads.py --city noida
  python3 tools/find_clinic_leads.py --city delhi
  python3 tools/find_clinic_leads.py                     # both cities
  python3 tools/find_clinic_leads.py --ingest items.json --city noida   # skip Apify, filter a saved dataset
  python3 tools/find_clinic_leads.py --dry-run           # show actor inputs, no API calls

Requires (.env):
  APIFY_API_TOKEN — https://console.apify.com/account/integrations

Cost: ~$0.003 per scraped place (pay-per-event), no add-ons used.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from tools.utils import api_retry

# NOTE: run/poll helpers duplicated from job_discover_apify.py rather than
# imported — that module's annotations require python 3.10+, this tool must run
# on the system python3 (3.9).

APIFY_BASE = "https://api.apify.com"
ACTOR = "compass~crawler-google-places"
LEADS_PATH = BASE / "data" / "local_leads.json"
CALL_SHEET_DIR = BASE / "data" / "call_sheets"
COST_PER_PLACE_USD = 0.003

CITIES = {
    "noida": "Noida, Uttar Pradesh, India",
    "delhi": "Delhi, India",
}
SEARCHES = ["physiotherapist", "physiotherapy clinic"]

# A "website" on one of these domains is a directory/social profile, not a real
# site — the clinic is still a website prospect.
DIRECTORY_DOMAINS = (
    "practo.com", "justdial.com", "jsdl.in", "lybrate.com",
    "instagram.com", "facebook.com", "fb.com", "linktr.ee",
    "wa.me", "whatsapp.com", "business.site", "g.page", "goo.gl",
)

# Words that end a doctor-name match in a listing title
NAME_STOPWORDS = {
    "physiotherapy", "physiotherapist", "physio", "clinic", "centre", "center",
    "hospital", "care", "rehab", "rehabilitation", "chamber", "wellness", "the",
    "best", "sports", "advanced", "multispeciality", "polyclinic", "at", "in",
}


def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


@api_retry
def apify_post(endpoint: str, body: dict, token: str, timeout: int = 30) -> dict:
    url = "{}{}?token={}".format(APIFY_BASE, endpoint, token)
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


@api_retry
def apify_get(endpoint: str, token: str, timeout: int = 30):
    url = "{}{}?token={}".format(APIFY_BASE, endpoint, token)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def run_apify_actor(actor_id: str, run_input: dict, token: str,
                    poll_interval: float = 6.0, timeout: float = 900.0) -> list:
    """Start an actor run, poll until done, return dataset items."""
    print("[apify] starting actor {}...".format(actor_id), file=sys.stderr)
    start_resp = apify_post("/v2/acts/{}/runs".format(actor_id), run_input, token)
    run = start_resp.get("data", {})
    run_id, dataset_id = run.get("id"), run.get("defaultDatasetId")
    if not run_id or not dataset_id:
        raise RuntimeError("Apify: malformed start response: {}".format(start_resp))
    print("[apify]   run_id={}  dataset_id={}".format(run_id, dataset_id), file=sys.stderr)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        status = apify_get("/v2/actor-runs/{}".format(run_id), token, timeout=15).get("data", {}).get("status")
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError("Apify run {} ended with status={}".format(run_id, status))
        print("[apify]   poll: status={}".format(status), file=sys.stderr)
    else:
        raise TimeoutError("Apify run {} did not finish within {}s".format(run_id, timeout))

    items = apify_get("/v2/datasets/{}/items".format(dataset_id), token, timeout=60)
    if isinstance(items, list):
        return items
    return items.get("items", items.get("data", []))


def domain_of(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^/:?#]+)", url or "", re.I)
    return m.group(1).lower() if m else ""


def is_real_website(url: str) -> bool:
    d = domain_of(url)
    if not d:
        return False
    return not any(d == dd or d.endswith("." + dd) for dd in DIRECTORY_DOMAINS)


def parse_doctor_name(title: str) -> str:
    """Pull 'Dr <Name>' out of a listing title like 'Dr. Anjali Sharma Physiotherapy Clinic'."""
    m = re.search(r"\bDr\.?\s+([A-Z][\w.]*(?:\s+[A-Z][\w.]*){0,3})", title or "")
    if not m:
        return ""
    words = []
    for w in m.group(1).split():
        if w.lower().strip(".") in NAME_STOPWORDS:
            break
        words.append(w)
    return ("Dr. " + " ".join(words)) if words else ""


def normalize_phone(phone: str) -> str:
    """Digits only, last 10 — dedup key. '' if too short."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else ""


def format_phone(phone: str) -> str:
    """Tap-to-dial +91 format where the number looks Indian."""
    n = normalize_phone(phone)
    return f"+91{n}" if n else (phone or "")


def map_place(record: dict, city_key: str, now_iso: str):  # -> dict or None
    title = (record.get("title") or "").strip()
    phone = (record.get("phone") or record.get("phoneUnformatted") or "").strip()
    if not title or not normalize_phone(phone):
        return None
    return {
        "place_id": record.get("placeId") or "",
        "practice_name": title,
        "doctor_name": parse_doctor_name(title),
        "phone": format_phone(phone),
        "address": (record.get("address") or "").strip(),
        "locality": (record.get("neighborhood") or record.get("street") or "").strip(),
        "city": city_key,
        "maps_url": record.get("url") or "",
        "website_raw": (record.get("website") or "").strip(),
        "category": record.get("categoryName") or "",
        "rating": record.get("totalScore"),
        "reviews_count": record.get("reviewsCount") or 0,
        "source": "gmaps-apify",
        "discovered": now_iso[:10],
        "status": "new",
    }


def build_actor_input(location_query: str, max_per_search: int) -> dict:
    return {
        "searchStringsArray": SEARCHES,
        "locationQuery": location_query,
        "maxCrawledPlacesPerSearch": max_per_search,
        "language": "en",
        "skipClosedPlaces": True,
        "scrapePlaceDetailPage": False,
        "scrapeContacts": False,
        "maxImages": 0,
        "maxReviews": 0,
    }


def load_leads() -> dict:
    """Existing leads keyed by place_id."""
    if LEADS_PATH.exists():
        try:
            return {l["place_id"]: l for l in json.loads(LEADS_PATH.read_text()) if l.get("place_id")}
        except json.JSONDecodeError:
            print(f"[clinic] WARNING: {LEADS_PATH} unreadable, starting fresh", file=sys.stderr)
    return {}


def write_call_sheet(leads: list) -> Path:
    CALL_SHEET_DIR.mkdir(parents=True, exist_ok=True)
    path = CALL_SHEET_DIR / f"physio-noida-delhi-{date.today().isoformat()}.csv"
    cols = ["practice_name", "doctor_name", "phone", "locality", "city",
            "category", "rating", "reviews_count", "website_raw", "maps_url", "address"]
    ranked = sorted(leads, key=lambda l: (l.get("reviews_count") or 0), reverse=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel/Numbers read ₹/Hindi chars right
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(ranked)
    return path


def process_items(items: list, city_key: str, existing: dict, funnel: dict) -> list:
    """Filter + map + dedupe one city's raw dataset items. Mutates existing/funnel."""
    now_iso = datetime.now(timezone.utc).isoformat()
    seen_phones = {normalize_phone(l["phone"]) for l in existing.values()}
    added = []
    for rec in items:
        funnel["raw"] += 1
        if is_real_website(rec.get("website") or ""):
            funnel["dropped_has_site"] += 1
            continue
        lead = map_place(rec, city_key, now_iso)
        if lead is None:
            funnel["dropped_no_phone"] += 1
            continue
        pid, ph = lead["place_id"], normalize_phone(lead["phone"])
        if pid in existing or ph in seen_phones:
            funnel["dup_skipped"] += 1
            continue
        existing[pid] = lead
        seen_phones.add(ph)
        added.append(lead)
    return added


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--city", choices=[*CITIES, "all"], default="all")
    p.add_argument("--max-per-search", type=int, default=200)
    p.add_argument("--test", action="store_true", help="5 places, Noida only — cap/field check")
    p.add_argument("--ingest", default=None, help="Path to a saved Apify dataset JSON; skips the API")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    load_env()
    token = os.environ.get("APIFY_API_TOKEN", "")

    if args.test:
        cities, max_per_search = ["noida"], 5
    else:
        cities = list(CITIES) if args.city == "all" else [args.city]
        max_per_search = args.max_per_search

    if args.dry_run:
        for c in cities:
            print(f"[dry-run] {c}: {json.dumps(build_actor_input(CITIES[c], max_per_search))}")
        return

    if not args.ingest and not token:
        sys.exit("[clinic] APIFY_API_TOKEN not set in .env")

    existing = load_leads()
    funnel = {"raw": 0, "dropped_has_site": 0, "dropped_no_phone": 0, "dup_skipped": 0}
    all_added = []

    if args.ingest:
        items = json.loads(Path(args.ingest).read_text())
        city_key = cities[0] if len(cities) == 1 else "ncr"
        all_added += process_items(items, city_key, existing, funnel)
    else:
        for c in cities:
            print(f"\n[clinic] city={c} (max {max_per_search}/search × {len(SEARCHES)} searches)", file=sys.stderr)
            items = run_apify_actor(ACTOR, build_actor_input(CITIES[c], max_per_search), token, timeout=900)
            print(f"[clinic]   got {len(items)} raw places", file=sys.stderr)
            all_added += process_items(items, c, existing, funnel)

    LEADS_PATH.parent.mkdir(parents=True, exist_ok=True)
    leads = list(existing.values())
    LEADS_PATH.write_text(json.dumps(leads, indent=2, ensure_ascii=False))
    sheet = write_call_sheet(leads)

    with_doctor = sum(1 for l in all_added if l["doctor_name"])
    cats = {}
    for l in all_added:
        cats[l["category"]] = cats.get(l["category"], 0) + 1

    print(json.dumps({
        "cities": cities,
        "funnel": {**funnel, "new_added": len(all_added), "total_in_file": len(leads)},
        "doctor_name_coverage": f"{with_doctor}/{len(all_added)}",
        "categories": dict(sorted(cats.items(), key=lambda kv: -kv[1])),
        "est_cost_usd": round(funnel["raw"] * COST_PER_PLACE_USD, 2),
        "leads_file": str(LEADS_PATH),
        "call_sheet": str(sheet),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
