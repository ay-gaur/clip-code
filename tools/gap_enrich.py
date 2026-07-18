#!/usr/bin/env python3
"""
gap_enrich.py — Phase 4 signals + enrichment.

Two distinct jobs, sequenced differently by the orchestrator:

  check_meta_ads(company)  — FREE Meta Ad Library lookup ("are they actively
      running ads in India?"). Cheap, run for ALL leads BEFORE scoring so the
      ability-to-pay component can use it. Returns True/False/None (None = no token).

  enrich_lead(lead)        — Apollo contact enrichment (quota-limited). Run only
      for surfaced bands (priority/shortlist) AFTER scoring. Email is best-effort;
      ~50% of early Indian founders sit on Gmail/info@ so LinkedIn stays primary.

Usage:
  python3 tools/gap_enrich.py --company "Acme" --domain acme.in --name "Jane Doe"
"""

import argparse
import json
import sys
from pathlib import Path

import requests

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
from tools.enrich_contact import enrich_contact
from tools.utils.llm_rest import load_env
from tools.utils.retry import with_retry

ADS_ARCHIVE_URL = "https://graph.facebook.com/v23.0/ads_archive"


def check_meta_ads(company: str, country: str = "IN") -> bool | None:
    """DEPRECATED — always returns None.

    The official Meta /ads_archive API only returns political/social-issue ads, never
    commercial D2C, so it can't tell us if a brand runs ads. The working signal now
    comes from DISCOVERY: leads sourced via gap_discover_ads.py (the Meta Ad Library
    Apify scrape) carry meta_ads_active=True because they were literally found in the
    ad library. Kept as a no-op so existing imports don't break.
    """
    return None


def enrich_lead(lead: dict) -> dict:
    """Opportunistic Apollo enrichment. Mutates + returns the lead. Never raises."""
    company = lead.get("company", "")
    domain = lead.get("domain", "")
    name = lead.get("contact_name", "")
    try:
        res = enrich_contact(company, domain, name)
    except Exception as e:  # noqa: BLE001
        print(f"[gap_enrich] enrich error for {company}: {e}", file=sys.stderr)
        res = None

    if res:
        if res.get("email") and not lead.get("contact_email"):
            lead["contact_email"] = res["email"]
        if res.get("linkedin_url") and not lead.get("contact_linkedin"):
            lead["contact_linkedin"] = res["linkedin_url"]
        if res.get("name") and not lead.get("contact_name"):
            lead["contact_name"] = res["name"]
        if res.get("title"):
            lead["contact_title"] = res["title"]
    lead["enriched"] = True
    return lead


def main():
    ap = argparse.ArgumentParser(description="Enrich + check ads for one lead (debug)")
    ap.add_argument("--company", required=True)
    ap.add_argument("--domain", default="")
    ap.add_argument("--name", default="")
    args = ap.parse_args()

    lead = {"company": args.company, "domain": args.domain, "contact_name": args.name}
    print("meta ads active:", check_meta_ads(args.company))
    print("enriched lead:", json.dumps(enrich_lead(lead), indent=2))


if __name__ == "__main__":
    main()
