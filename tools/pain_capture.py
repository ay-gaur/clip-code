#!/usr/bin/env python3.13
"""pain_capture.py — Painfinder Stage 1: multi-source pain capture.

Reads a run's source_map.json and scrapes complaint signal across sources into
normalized raw items under raw/<source>/. Sources (v1): reddit, trustpilot,
upwork. G2 is opt-in (--with-g2) because it needs product slugs. LinkedIn/X are
a flagged follow-up.

Each raw item is normalized to:
  {id, source_type, source_url, tool, title, text, meta{...}, created}

Usage (python3.13):
  python3.13 tools/pain_capture.py --slice agencies --test            # tiny pull, dumps samples
  python3.13 tools/pain_capture.py --slice agencies                   # full pull
  python3.13 tools/pain_capture.py --run-id run_001 --sources reddit,upwork
  python3.13 tools/pain_capture.py --run-id run_001 --with-g2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import pain_common as pc
from tools.utils.apify import run_apify_actor, get_token

REDDIT_ACTOR = "harshmaur/reddit-scraper"
REDDIT_FALLBACK_ACTOR = "trudax/reddit-scraper-lite"
TRUSTPILOT_ACTOR = "memo23/trustpilot-scraper-ppe"
UPWORK_ACTOR = "blackfalcondata/upwork-scraper"
G2_ACTOR = "automation-lab/g2-scraper"

PAIN_PHRASES = ["alternative to", "frustrating", "hate", "workaround", "switching from", "overpriced"]


def _first(d: dict, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _mk_id(source_type: str, url: str, text: str) -> str:
    raw = f"{source_type}|{url}|{pc.norm(text)[:120]}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


# ---- per-source query builders --------------------------------------------

def reddit_queries(sm: dict, test: bool) -> list:
    # platform-scoped queries only — keeps recall on-topic (generic slice phrases
    # pulled unrelated subreddits in testing).
    platforms = sm.get("platforms", [])[: (2 if test else 10)]
    phrases = PAIN_PHRASES[:2] if test else PAIN_PHRASES[:3]
    qs = [f"{p} {ph}" for p in platforms for ph in phrases]
    seen, out = set(), []
    for q in qs:
        if q.lower() not in seen:
            seen.add(q.lower()); out.append(q)
    return out[: (2 if test else 20)]


# ---- per-source scrapers ---------------------------------------------------

def _norm_reddit(items):
    out = []
    for it in items:
        title = _first(it, "title")
        body = _first(it, "body", "text", "selftext", "content")
        text = (title + "\n" + body).strip()
        if not text or not pc.has_pain_term(text):
            continue
        url = _first(it, "postUrl", "url", "link")
        out.append({
            "id": _mk_id("reddit", url, text), "source_type": "reddit",
            "source_url": url, "tool": "", "title": title, "text": text[:4000],
            "meta": {"community": _first(it, "communityName", "subreddit", "community"),
                     "score": _first(it, "score", "upVotes", default=0),
                     "comments": _first(it, "commentsCount", "numberOfComments", default=0)},
            "created": _first(it, "createdAt", "created"),
        })
    return out


def _reddit_via_tavily(sm, tracker, test):
    """Free Reddit signal via Tavily site:reddit.com search — bypasses Apify entirely
    (used when Apify is capped). Snippets, not full posts, but enough for pain extraction."""
    from tools.find_leads import search_tavily
    plats = sm.get("platforms", [])[: (2 if test else 12)]
    out, seen = [], set()
    raw = 0
    for p in plats:
        q = f"{p} frustrating OR alternative OR problem OR overpriced site:reddit.com"
        try:
            hits = search_tavily(q, max_results=3 if test else 5)
        except Exception as e:
            print(f"[capture] tavily '{p}' failed: {e}", file=sys.stderr)
            continue
        if tracker:
            tracker.track("tavily", calls=1)
        for h in hits:
            raw += 1
            url = h.get("url", "")
            text = ((h.get("title", "") or "") + "\n" + (h.get("content", "") or "")).strip()
            if not url or url in seen or not text or not pc.has_pain_term(text):
                continue
            seen.add(url)
            out.append({
                "id": _mk_id("reddit", url, text), "source_type": "reddit",
                "source_url": url, "tool": p, "title": h.get("title", "")[:200], "text": text[:4000],
                "meta": {"via": "tavily", "platform": p}, "created": "",
            })
    return out, raw


def scrape_reddit(sm, token, tracker, test):
    qs = reddit_queries(sm, test)
    # Try Apify primary, then fallback actor, then free Tavily site:reddit.com search.
    inp = {"searchTerms": qs, "searchPosts": True, "searchComments": False,
           "searchSort": "relevance", "searchTime": "year", "maxPostsCount": 15 if test else 150}
    try:
        items = run_apify_actor(REDDIT_ACTOR, inp, token, tracker=tracker, label="reddit")
        return _norm_reddit(items), len(items)
    except Exception as e:
        print(f"[capture] reddit primary failed ({e}); trying fallback actor", file=sys.stderr)
    try:
        fb_inp = {"searches": qs, "searchPosts": True, "searchComments": False, "searchCommunities": False,
                  "sort": "relevance", "time": "year", "maxItems": 15 if test else 150, "maxPostCount": 15 if test else 150}
        items = run_apify_actor(REDDIT_FALLBACK_ACTOR, fb_inp, token, tracker=tracker, label="reddit-fallback")
        return _norm_reddit(items), len(items)
    except Exception as e:
        print(f"[capture] reddit fallback actor failed ({e}); using free Tavily site:reddit.com", file=sys.stderr)
    return _reddit_via_tavily(sm, tracker, test)


def scrape_trustpilot(sm, token, tracker, test):
    targets = sm.get("review_targets", [])[: (3 if test else 10)]
    inp = {
        "searchTerms": targets, "filterStars": ["1", "2", "3"],
        "reviewInsights": True, "painPointAnalysis": True,
        "strictNameMatch": True, "expandRegionalDomains": False,
        "filterDateRange": "last12months", "flattenCompanyData": True,
        "maxItems": 8 if test else 60,
    }
    items = run_apify_actor(TRUSTPILOT_ACTOR, inp, token, timeout=1200, tracker=tracker, label="trustpilot")
    out = []
    for it in items:
        company = _first(it, "companyName", "company", "brand", "displayName")
        if isinstance(company, dict):
            company = _first(company, "displayName", "name", default="")
        # AI pain-point / insights rows: keep whole, they are pre-clustered gold
        if it.get("painPointAnalysis") or it.get("review_insights"):
            out.append({
                "id": _mk_id("trustpilot_insight", str(company), json.dumps(it)[:120]),
                "source_type": "trustpilot_insight", "source_url": _first(it, "companyUrl", "url"),
                "tool": company, "title": f"pain-point analysis: {company}",
                "text": json.dumps(it.get("painPointAnalysis") or it.get("review_insights"))[:4000],
                "meta": {"kind": "insight"}, "created": "",
            })
            continue
        text = _first(it, "text", "reviewText", "body", "review", "content")
        if not text:
            continue
        url = _first(it, "reviewUrl", "url", "companyUrl")
        out.append({
            "id": _mk_id("trustpilot", url, text), "source_type": "trustpilot",
            "source_url": url, "tool": company,
            "title": _first(it, "title", "reviewTitle"), "text": text[:4000],
            "meta": {"stars": _first(it, "stars", "rating", "companyStars", default=None)},
            "created": _first(it, "date", "createdAt", "publishedDate"),
        })
    return out, len(items)


def scrape_upwork(sm, token, tracker, test):
    terms = sm.get("job_terms", [])[: (2 if test else 8)]
    out, raw_total = [], 0
    for term in terms:
        inp = {
            "query": term, "sort": "relevance", "compact": True,
            "verifiedPaymentOnly": True, "maxResults": 6 if test else 25,
        }
        try:
            items = run_apify_actor(UPWORK_ACTOR, inp, token, timeout=600, tracker=tracker, label=f"upwork:{term[:20]}")
        except Exception as e:
            print(f"[capture] upwork '{term}' failed: {e}", file=sys.stderr)
            continue
        raw_total += len(items)
        for it in items:
            title = _first(it, "title")
            desc = _first(it, "description", "descriptionText", "snippet")
            if isinstance(desc, dict):
                desc = _first(desc, "text", "markdown", default="")
            text = (title + "\n" + str(desc)).strip()
            if not text:
                continue
            url = _first(it, "url", "link", "jobUrl", "ciphertext")
            out.append({
                "id": _mk_id("upwork", url, text), "source_type": "upwork",
                "source_url": url, "tool": "", "title": title, "text": text[:4000],
                "meta": {"query": term,
                         "budget": _first(it, "budget", "amount", default=None),
                         "hourly": _first(it, "hourlyRate", "hourlyBudget", "rate", default=None),
                         "client_spent": _first(it, "totalSpent", "clientTotalSpent", "totalCharge", default=None),
                         "applicants": _first(it, "applicants", "totalApplicants", "proposals", default=None),
                         "country": _first(it, "clientCountry", "country", default="")},
                "created": _first(it, "publishedDate", "createdAt", "postedOn"),
            })
    return out, raw_total


def scrape_g2(sm, token, tracker, test):
    slugs = [pc.norm(t).replace(" ", "-").replace(".", "-") for t in sm.get("review_targets", [])[: (3 if test else 8)]]
    inp = {"mode": "product_reviews", "productUrls": slugs,
           "sortReviews": "rating_low", "maxReviews": 8 if test else 40}
    items = run_apify_actor(G2_ACTOR, inp, token, timeout=1200, tracker=tracker, label="g2")
    out = []
    for it in items:
        text = _first(it, "text", "review", "body", "content", "reviewBody")
        if not text:
            continue
        url = _first(it, "reviewUrl", "url")
        out.append({
            "id": _mk_id("g2", url, text), "source_type": "g2",
            "source_url": url, "tool": _first(it, "productName", "product", "companyName"),
            "title": _first(it, "title", "reviewTitle"), "text": text[:4000],
            "meta": {"rating": _first(it, "rating", "nps", "score", default=None)},
            "created": _first(it, "date", "publishedAt", default=""),
        })
    return out, len(items)


SCRAPERS = {"reddit": scrape_reddit, "trustpilot": scrape_trustpilot, "upwork": scrape_upwork, "g2": scrape_g2}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slice", choices=pc.SLICES, default=None)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--sources", default="reddit,trustpilot,upwork", help="csv subset")
    ap.add_argument("--with-g2", action="store_true", help="include G2 (slug-fragile, opt-in)")
    ap.add_argument("--test", action="store_true", help="tiny pull + dump sample raw items")
    args = ap.parse_args()

    run_id = args.run_id or pc.latest_run_id()
    if not run_id:
        sys.exit("[capture] no run found — run pain_sources.py first")
    run_dir = pc.get_run_dir(run_id)
    sm = pc.read_json(run_dir / "source_map.json")
    if not sm:
        sys.exit(f"[capture] no source_map.json in {run_dir} — run pain_sources.py first")

    token = get_token()
    if not token:
        sys.exit("[capture] APIFY_API_TOKEN missing")
    tracker = pc.make_tracker(run_dir)

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if args.with_g2 and "g2" not in sources:
        sources.append("g2")

    summary = {}
    all_items = []
    for src in sources:
        fn = SCRAPERS.get(src)
        if not fn:
            print(f"[capture] unknown source '{src}', skipping", file=sys.stderr)
            continue
        try:
            items, raw_n = fn(sm, token, tracker, args.test)
            pc.write_json(run_dir / "raw" / src / "items.json", items)
            summary[src] = {"raw": raw_n, "kept": len(items)}
            all_items.extend(items)
            if args.test and items:
                print(f"\n[SAMPLE {src}] {json.dumps(items[0], ensure_ascii=False)[:600]}\n", file=sys.stderr)
        except Exception as e:
            (run_dir / "errors").mkdir(parents=True, exist_ok=True)
            (run_dir / "errors" / f"capture_{src}.txt").write_text(traceback.format_exc())
            summary[src] = {"error": str(e)}
            print(f"[capture] {src} ERROR: {e}", file=sys.stderr)

    pc.write_json(run_dir / "raw" / "all_items.json", all_items)
    tracker.save()

    est = tracker.summary().get("apify", {})
    print(json.dumps({
        "run": run_id, "slice": sm.get("slice"), "sources": summary,
        "total_kept": len(all_items),
        "apify_calls": est.get("calls"), "est_cost_usd": est.get("est_cost_usd"),
        "note": "est_cost uses the LinkedIn-jobs per-call rate; true cost varies by actor (see plan).",
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
