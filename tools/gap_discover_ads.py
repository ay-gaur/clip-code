#!/usr/bin/env python3
"""
gap_discover_ads.py — discovery via Meta Ad Library (the early-biased source).

Replaces the failed Tavily-over-listicles discovery. Keyword-searches the Meta Ad
Library in India for category terms ("face serum", "gut health", ...) and returns
EVERY advertiser using that language — unknown/early brands surface by language, not
fame (the bias that broke web search). Each lead is keyed off the ad's DESTINATION
DOMAIN (snapshot.linkUrl), NOT the Facebook page name — this defeats the agency/proxy-
page problem AND yields the brand's own store URL directly (fixing domain resolution).

Bonus: a brand running ads = ability-to-pay built in. Leads carry meta_ads_active=True.

Extraction: Apify Meta Ad Library scraper (the OFFICIAL Meta /ads_archive API returns
only political/issue ads — useless for commercial D2C). Needs a free APIFY_API_TOKEN
(~$5/mo free credits, no card). Without it, callers fall back to Tavily discovery.

Usage:
  python3 tools/gap_discover_ads.py --count 20
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
from tools.utils.llm_rest import load_env
from tools.utils.gap_models import normalize_domain
from tools.find_leads import load_leads

APIFY_ACTOR = "curious_coder~facebook-ads-library-scraper"
APIFY_URL = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"

# MID-SPECIFICITY trending-category terms = the goldilocks middle. Head terms
# ("face serum") are dominated by funded giants (gated out); ultra-niche ("handmade
# soap") surfaces ₹-tiny micro-makers. These hot D2C categories have a LONG TAIL of
# growing-but-bootstrapped brands (₹5-50L/mo) competing alongside the giants — the
# funding gate drops the giants, leaving the real early-but-fundable brands.
DEFAULT_KEYWORDS = [
    "hair growth serum india", "biotin hair gummies", "shilajit resin india",
    "collagen powder india", "under eye cream india", "body butter india",
    "beard growth kit india", "intimate wash india", "sleep gummies india",
    "electrolyte hydration india", "protein bar india", "gut health probiotic india",
    "magnesium oil spray india", "retinol serum india", "scalp serum india",
    "cold pressed juice india", "vegan protein india", "period pain relief india",
    "pre workout india", "hair fall control oil india",
]

# Domains that are not a brand's own store (marketplaces, socials, infra).
_EXCLUDE = (
    "facebook.com", "instagram.com", "fb.com", "fb.me", "linktr.ee", "bit.ly",
    "amazon.in", "amazon.com", "nykaa.com", "flipkart.com", "myntra.com",
    "ajio.com", "meesho.com", "tatacliq.com", "tirabeauty.com", "purplle.com",
    "blinkit.com", "zepto.com", "swiggy.com", "wa.me", "api.whatsapp.com",
    "youtube.com", "google.com", "shopify.com", "apps.apple.com", "play.google.com",
    # marketplace + URL-shortener destinations (not the brand's own store)
    "amzn.in", "amzn.to", "amazon.com", "fkrt.cc", "fkrt.it", "dl.flipkart.com",
    "bit.ly", "cutt.ly", "rb.gy", "tinyurl.com", "spti.fi", "linktr.ee",
    "wears.shop", "taplink.cc", "beacons.ai",
    # foreign / other marketplaces (not an Indian brand's own store)
    "shopee.co.id", "shopee.com", "lazada.com", "etsy.com", "aliexpress.com",
    "wa.link", "wati.io",
)


def _apify_token() -> str:
    load_env()
    return (os.environ.get("APIFY_API_TOKEN") or os.environ.get("APIFY_TOKEN") or "").strip()


def has_token() -> bool:
    return bool(_apify_token())


def _search_url(keyword: str, country: str) -> str:
    return ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
            f"&country={country}&q={quote(keyword)}&search_type=keyword_unordered&media_type=all")


def run_apify_ads(keyword: str, country: str = "IN", count: int = 50,
                  period: str = "last30d") -> list[dict]:
    """Run the Apify Meta Ad Library scraper for one keyword. Returns raw ad records."""
    token = _apify_token()
    if not token:
        return []
    body = {
        # actor requires urls as objects and count >= 10 ("Maximum charged results")
        "urls": [{"url": _search_url(keyword, country)}],
        "count": max(10, count),
        "scrapePageAds.activeStatus": "active",
        "scrapePageAds.countryCode": country,
        "scrapePageAds.period": period,
        "scrapePageAds.sortBy": "most_recent",  # fresher/smaller advertisers, not top spenders
    }
    try:
        resp = requests.post(f"{APIFY_URL}?token={token}", json=body, timeout=300)
        if resp.status_code >= 400:
            print(f"[gap_discover_ads] Apify {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
            return []
        data = resp.json()
        return data if isinstance(data, list) else []
    except requests.RequestException as e:
        print(f"[gap_discover_ads] Apify error: {e}", file=sys.stderr)
        return []


def _dest_domain(item: dict) -> str:
    """Pull the ad's CTA destination domain (the brand's own store), excluding non-brand hosts."""
    snap = item.get("snapshot") or {}
    candidates = [
        snap.get("linkUrl"), snap.get("link_url"), snap.get("caption"),
        item.get("linkUrl"), item.get("link_url"), snap.get("displayUrl"),
    ]
    for c in candidates:
        if not c:
            continue
        dom = normalize_domain(c)
        if dom and not any(dom == x or dom.endswith("." + x) for x in _EXCLUDE):
            return dom
    return ""


def _company(item: dict, domain: str) -> str:
    snap = item.get("snapshot") or {}
    name = (item.get("pageName") or item.get("page_name") or snap.get("page_name")
            or snap.get("pageName") or "").strip()
    if name:
        return name
    # fall back to the domain root, title-cased
    return domain.split(".")[0].replace("-", " ").title() if domain else ""


def discover_via_ads(target: int, keywords: list[str] | None = None, country: str = "IN",
                     existing: dict | None = None, verbose: bool = True) -> list[dict]:
    """Return up to `target` deduped early-brand candidates from the Meta Ad Library."""
    if not has_token():
        if verbose:
            print("[gap_discover_ads] no APIFY_API_TOKEN — skipping ads discovery")
        return []
    existing = existing or {}
    seen_dom = set(existing.get("domains", set()))
    seen_co = set(existing.get("companies", set()))
    keywords = keywords or DEFAULT_KEYWORDS
    found: list[dict] = []

    for i, kw in enumerate(keywords):
        if len(found) >= target:
            break
        if verbose:
            print(f"[gap_discover_ads] keyword {i+1}/{len(keywords)}: {kw}")
        if i:
            time.sleep(1.0)
        items = run_apify_ads(kw, country=country, count=max(40, target * 3))
        if verbose:
            print(f"[gap_discover_ads]   {len(items)} ad records")
        for item in items:
            if len(found) >= target:
                break
            dom = _dest_domain(item)
            if not dom or dom in seen_dom:
                continue
            company = _company(item, dom)
            co_key = company.lower()
            if not company or co_key in seen_co:
                continue
            found.append({
                "company": company,
                "domain": dom,
                "contact_name": "",
                "contact_linkedin": "",
                "source_url": item.get("url") or _search_url(kw, country),
                "meta_ads_active": True,  # discovered FROM the ad library
                "ad_keyword": kw,
            })
            seen_dom.add(dom)
            seen_co.add(co_key)
            if verbose:
                print(f"  + {company} ({dom})")
    return found


def existing_index() -> dict:
    leads = load_leads()
    return {
        "domains": {normalize_domain(l.get("domain", "")) for l in leads if l.get("domain")},
        "companies": {l.get("company", "").lower() for l in leads if l.get("company")},
    }


def main():
    ap = argparse.ArgumentParser(description="Discover early D2C brands via Meta Ad Library (Apify)")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--country", default="IN")
    args = ap.parse_args()
    if not has_token():
        print("Set APIFY_API_TOKEN in .env (free at apify.com). Falling back is the caller's job.")
        sys.exit(1)
    cands = discover_via_ads(args.count, country=args.country, existing=existing_index())
    print(f"\n[gap_discover_ads] {len(cands)} candidates:")
    print(json.dumps(cands, indent=2))


if __name__ == "__main__":
    main()
