#!/usr/bin/env python3
"""
gap_discover.py — Phase 1: discover early-stage Indian D2C / coach candidates.

Uses the existing Tavily wrapper (search_tavily) over gap-focused query templates,
then an LLM extractor turns messy search results into structured candidates
{company, domain, contact_name, contact_linkedin, source_url}. Discover-until-target
loop with dedupe against data/leads.json (by domain + company).

All sources are $0: Tavily free tier + public web (Shark Tank India, d2c.fyi, Inc42
free articles, VC portfolios). LinkedIn is never scraped — only Tavily-surfaced
public URLs are read.

Usage:
  python3 tools/gap_discover.py --count 15 --persona d2c
"""

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
import time

from tools.find_leads import search_tavily, load_leads
from tools.utils.llm_rest import call_llm_list, load_env
from tools.utils.gap_models import normalize_domain

# Persona-targeted query templates aimed at EARLY-STAGE India + missing-infra signals.
QUERIES = {
    "d2c": [
        'new Indian D2C brand 2025 2026 Shopify skincare OR beauty OR coffee OR snacks founder',
        'site:linkedin.com "founder" D2C India "just launched" OR "early days" 2025 2026',
        'Shark Tank India season 5 D2C brand founder website',
        'bootstrapped Indian D2C brand 2025 instagram shopify founder small team',
        'site:inc42.com OR site:yourstory.com new D2C brand India seed 2025 2026',
        '"D2C" India founder skincare OR wellness OR food brand "we started" 2025',
    ],
    "coach": [
        'India online coach cohort OR "1:1 coaching" topmate OR calendly 2025 2026',
        'site:linkedin.com India "business coach" OR "career coach" solo "DM me" 2025',
        'Indian fitness OR mindset coach launched program instagram early',
    ],
    "consultant": [
        'India fractional CMO OR growth consultant advisory 2025 2026',
        'site:linkedin.com India "fractional" OR "consultant" D2C growth advisor',
    ],
}

_EXCLUDE_DOMAINS = ("linkedin.com", "instagram.com", "facebook.com", "twitter.com",
                    "x.com", "youtube.com", "amazon.in", "amazon.com", "nykaa.com",
                    "flipkart.com", "inc42.com", "yourstory.com", "d2c.fyi",
                    "wikipedia.org", "crunchbase.com", "tracxn.com", "medium.com",
                    # Indian marketplaces — a listing there is not the brand's own site
                    "ajio.com", "myntra.com", "tatacliq.com", "meesho.com",
                    "tirabeauty.com", "purplle.com", "1mg.com", "pharmeasy.in",
                    "blinkit.com", "zepto.com", "swiggy.com", "qikink.com",
                    "shopify.com", "wordpress.com", "wixsite.com",
                    "reddit.com", "quora.com", "pinterest.com", "tiktok.com",
                    "google.com", "play.google.com", "apps.apple.com")


def extract_candidates(results: list[dict], persona: str) -> list[dict]:
    """LLM-extract structured brand candidates from raw Tavily results."""
    if not results:
        return []
    blob = "\n\n".join(
        f"RESULT {i+1}:\nTitle: {r.get('title','')}\nURL: {r.get('url','')}\n"
        f"Content: {r.get('content','')[:400]}"
        for i, r in enumerate(results)
    )
    persona_desc = {
        "d2c": "early-stage Indian Direct-to-Consumer product BRANDS (skincare, food, beverage, wellness, etc.)",
        "coach": "individual Indian online COACHES (business/career/fitness/mindset) selling programs",
        "consultant": "Indian fractional executives / CONSULTANTS / advisors",
    }.get(persona, "early-stage Indian D2C brands")

    prompt = f"""Extract real {persona_desc} from these web search results.
INCLUDE only genuine early-stage businesses/people. EXCLUDE: news outlets, big/funded
household brands, agencies, marketplaces, listicles, and aggregators.

For each, return an object with:
- company: brand or person/business name
- domain: their OWN website domain (e.g. brand.in) — NOT linkedin/instagram/amazon/nykaa/news. "" if unknown.
- contact_name: founder/owner name if visible, else ""
- contact_linkedin: LinkedIn profile URL if present, else ""
- source_url: the result URL you found them in

Search results:
{blob}

Return ONLY JSON shaped as {{"leads": [ ... ]}} (a "leads" key holding the array).
If nothing valid, return {{"leads": []}}."""
    # Extraction is token-heavy + few calls -> Gemini (higher throughput, public-data
    # input so training risk is low). The small, numerous classify/draft calls use Groq.
    out = call_llm_list(prompt, prefer="gemini", max_tokens=1600, temperature=0.2, scrub=False)
    return out if isinstance(out, list) else []


def _clean_domain(d: str) -> str:
    dom = normalize_domain(d)
    if not dom or any(dom == x or dom.endswith("." + x) for x in _EXCLUDE_DOMAINS):
        return ""
    return dom


def resolve_domain(company: str) -> str:
    """Follow-up search to find a brand's OWN website when extraction missed it.

    A lead with no domain can't be audited (the core of this skill), so this is
    worth the extra Tavily call. Returns "" if nothing clean is found.
    """
    if not company:
        return ""
    for r in search_tavily(f'{company} official website india shop', max_results=4):
        dom = _clean_domain(r.get("url", ""))
        if dom:
            return dom
    return ""


def discover(target: int, persona: str = "d2c", existing: dict | None = None,
             per_query: int = 8, verbose: bool = True, resolve: bool = True) -> list[dict]:
    """Return up to `target` new, deduped candidate dicts."""
    load_env()
    existing = existing or {}
    seen_dom = set(existing.get("domains", set()))
    seen_co = set(existing.get("companies", set()))

    queries = QUERIES.get(persona, QUERIES["d2c"])
    found: list[dict] = []

    for i, q in enumerate(queries):
        if len(found) >= target:
            break
        if verbose:
            print(f"[gap_discover] query {i+1}/{len(queries)}: {q[:70]}...")
        if i:
            time.sleep(3.0)  # space extraction calls under Gemini's ~10 RPM free limit
        results = search_tavily(q, max_results=per_query)
        if verbose:
            print(f"[gap_discover]   {len(results)} results")
        for cand in extract_candidates(results, persona):
            if len(found) >= target:
                break
            company = (cand.get("company") or "").strip()
            if not company:
                continue
            co_key = company.lower()
            if co_key in seen_co:
                continue
            dom = _clean_domain(cand.get("domain", ""))
            if not dom and resolve:
                dom = resolve_domain(company)  # follow-up search for their own site
            if dom and dom in seen_dom:
                continue
            cand["company"] = company
            cand["domain"] = dom
            found.append(cand)
            seen_co.add(co_key)
            if dom:
                seen_dom.add(dom)
            if verbose:
                print(f"  + {company} ({dom or 'no-domain'})")

    return found


def existing_index() -> dict:
    """Build dedupe sets from the current leads.json."""
    leads = load_leads()
    return {
        "domains": {normalize_domain(l.get("domain", "")) for l in leads if l.get("domain")},
        "companies": {l.get("company", "").lower() for l in leads if l.get("company")},
    }


def main():
    ap = argparse.ArgumentParser(description="Discover early-stage gap-fit candidates")
    ap.add_argument("--count", type=int, default=15)
    ap.add_argument("--persona", default="d2c", choices=list(QUERIES.keys()))
    args = ap.parse_args()

    cands = discover(args.count, persona=args.persona, existing=existing_index())
    print(f"\n[gap_discover] {len(cands)} new candidates:")
    print(json.dumps(cands, indent=2))


if __name__ == "__main__":
    main()
