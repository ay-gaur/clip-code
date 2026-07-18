#!/usr/bin/env python3
"""
swipe_scan.py — Cross-platform "winning content" radar for the /content skill.

Finds the highest-performing content by OTHER creators, scores it by a
per-platform performance proxy, normalizes it, and saves a swipe file that
the /content skill turns into Alex's own scripts + posts.

IMPORTANT — there is no real ROI/engagement-truth for ads. Meta does not
publish spend/CTR/ROAS for commercial ads. So we approximate "winning":

  meta_ads : days the ad has been running + active variant count.
             Long-running, multi-variant ads are almost always profitable —
             nobody keeps paying to run a loser. This is the media-buyer proxy.
  x        : likes + reposts + replies
  reddit   : upvotes + comments
  linkedin : reactions + comments   (EXPERIMENTAL — see notes below)

Backends:
  reddit   : FREE via a Reddit app (REDDIT_CLIENT_ID/SECRET, OAuth) — Reddit now
             403s unauthenticated JSON. Falls back to Apify if no Reddit creds.
  meta_ads : Apify actor. Needs APIFY_TOKEN. Paid (cheap, cloud-run).
  x        : Apify actor. Needs APIFY_TOKEN. Paid.
  linkedin : Apify actor. Needs APIFY_TOKEN. Paid. EXPERIMENTAL / ToS-risky —
             LinkedIn actively blocks scraping and can flag accounts. Off unless
             you pass --source linkedin explicitly.

Actor slugs below are STARTING GUESSES. Confirm the exact slug in the Apify
Store and override via env (APIFY_ACTOR_META_ADS / _X / _LINKEDIN) if different.
Run once with --raw to dump an item's raw keys, then we map fields precisely.

Usage:
  python3 tools/swipe_scan.py --source reddit  --query "AI automation agency" --limit 15
  python3 tools/swipe_scan.py --source meta_ads --query "replace your VA" --country US --min-days 30
  python3 tools/swipe_scan.py --source x       --query "AI automation" --limit 20
  python3 tools/swipe_scan.py --source all     --query "automation agency" --dry-run
  python3 tools/swipe_scan.py --source meta_ads --query "AI agency" --raw   # inspect raw schema

Output: data/swipe_intel.json   (consumed by the /content skill)

Requires: APIFY_TOKEN in .env for meta_ads / x / linkedin. Reddit needs nothing.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
sys.path.insert(0, str(BASE))

# Polite, identifiable UA — Reddit 429s generic/empty user agents.
UA = "clip-swipe-scan/1.0 (content research; contact user@example.com)"

# Apify actor slugs — VERIFY in the Apify Store; override in .env if different.
DEFAULT_ACTORS = {
    "meta_ads": "apify/facebook-ads-scraper",
    "x": "apidojo/tweet-scraper",
    "linkedin": "curious_coder/linkedin-post-search-scraper",
    "reddit": "trudax/reddit-scraper",  # only used if no REDDIT_CLIENT_ID/SECRET
}

PAID_SOURCES = {"meta_ads", "x", "linkedin"}


def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


# ----------------------------- HTTP helpers ------------------------------- #

def http_get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def http_post_json(url, payload, headers=None, timeout=300):
    data = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json", "User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def days_running(start):
    """Best-effort age in days from an epoch int, ISO string, or YYYY-MM-DD."""
    if not start:
        return None
    try:
        if isinstance(start, (int, float)) or (isinstance(start, str) and str(start).isdigit()):
            dt = datetime.fromtimestamp(int(start), tz=timezone.utc)
        else:
            s = str(start).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s[:19] if "T" in s else s[:10])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return None


def first(d, *keys, default=""):
    """Return the first present, non-empty value among keys (supports a.b paths)."""
    for k in keys:
        cur = d
        ok = True
        for part in k.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur not in (None, "", [], {}):
            return cur
    return default


def normalize(platform, url, author, hook, text, engagement,
              longevity_days=None, variant_count=None, extra=None):
    return {
        "platform": platform,
        "url": url,
        "author": author,
        "hook": (hook or "").strip()[:300],
        "text": (text or "").strip()[:2000],
        "engagement": int(engagement or 0),
        "longevity_days": longevity_days,
        "variant_count": variant_count,
        "extra": extra or {},
    }


# ----------------------------- Apify runner ------------------------------- #

def apify_run(source, token, run_input, max_items, raw=False):
    """Run an Apify actor synchronously and return its dataset items."""
    actor = os.environ.get(f"APIFY_ACTOR_{source.upper()}", DEFAULT_ACTORS[source])
    actor_path = actor.replace("/", "~")  # Apify run-sync URLs use ~ not /
    url = f"https://api.apify.com/v2/acts/{actor_path}/run-sync-get-dataset-items?" + \
        urllib.parse.urlencode({"token": token, "limit": max_items})
    print(f"[swipe_scan] [paid] Apify actor '{actor}' (source={source}, up to {max_items} items)...",
          file=sys.stderr)
    try:
        raw_text = http_post_json(url, run_input, timeout=300)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        print(f"[swipe_scan] Apify HTTP {e.code}: {body}", file=sys.stderr)
        print("[swipe_scan] If 404: actor slug is wrong — set "
              f"APIFY_ACTOR_{source.upper()} in .env. If 401: bad APIFY_TOKEN.", file=sys.stderr)
        return []
    rows = json.loads(raw_text)
    if not isinstance(rows, list):
        rows = rows.get("items", []) if isinstance(rows, dict) else []
    if raw and rows:
        print("\n[swipe_scan] --raw: keys of first item (map these into the parser):", file=sys.stderr)
        print(json.dumps(rows[0], indent=2)[:2500], file=sys.stderr)
    return rows


# --------------------------- Source scanners ------------------------------ #

def reddit_oauth_token():
    """App-only OAuth token from a free Reddit app. None if creds absent/invalid."""
    cid = os.environ.get("REDDIT_CLIENT_ID", "")
    csec = os.environ.get("REDDIT_CLIENT_SECRET", "")
    if not (cid and csec):
        return None
    import base64
    basic = base64.b64encode(f"{cid}:{csec}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token", data=data,
        headers={"Authorization": f"Basic {basic}", "User-Agent": UA}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()).get("access_token")
    except urllib.error.HTTPError as e:
        print(f"[swipe_scan] Reddit OAuth HTTP {e.code} — check REDDIT_CLIENT_ID/SECRET", file=sys.stderr)
        return None


def scan_reddit(query, limit=15, timeframe="month", apify_token=None):
    """Top posts by upvotes+comments. Free via Reddit OAuth, else Apify, else skip."""
    tok = reddit_oauth_token()
    if tok:
        url = "https://oauth.reddit.com/search?" + urllib.parse.urlencode(
            {"q": query, "sort": "top", "t": timeframe, "limit": limit, "type": "link"})
        data = json.loads(http_get(url, headers={"Authorization": f"bearer {tok}", "User-Agent": UA}))
        items = []
        for c in data.get("data", {}).get("children", []):
            d = c.get("data", {})
            up, ncom = d.get("score", 0), d.get("num_comments", 0)
            items.append(normalize(
                platform="reddit",
                url="https://www.reddit.com" + d.get("permalink", ""),
                author="u/" + d.get("author", "?"),
                hook=d.get("title", ""), text=d.get("selftext", "") or "",
                engagement=up + ncom * 3,
                extra={"upvotes": up, "comments": ncom, "subreddit": "r/" + d.get("subreddit", "")}))
        return items
    if apify_token:
        run_input = {"searches": [query], "searchType": "posts", "sort": "top",
                     "maxItems": limit, "maxPostCount": limit}
        rows = apify_run("reddit", apify_token, run_input, limit)
        items = []
        for r in rows:
            up = int(first(r, "upVotes", "score", "ups", default=0) or 0)
            ncom = int(first(r, "numberOfComments", "numComments", "comments", default=0) or 0)
            items.append(normalize(
                platform="reddit",
                url=first(r, "url", "link", default=""),
                author="u/" + str(first(r, "author", "username", default="?")),
                hook=first(r, "title", "text", default=""),
                text=first(r, "body", "text", "selftext", default=""),
                engagement=up + ncom * 3,
                extra={"upvotes": up, "comments": ncom,
                       "subreddit": first(r, "subreddit", "community", default="")}))
        return items
    print("[swipe_scan] Reddit needs REDDIT_CLIENT_ID/SECRET (free app) or APIFY_TOKEN — skipping.\n"
          "  Free app: reddit.com/prefs/apps -> create app (type 'script').", file=sys.stderr)
    return []


def scan_meta_ads(query, token, country="US", min_days=0, limit=20, raw=False):
    """Apify. Active ads matching query, scored by longevity + variants."""
    run_input = {
        "searchTerms": [query], "search": query,        # actor-dependent keys
        "countryCode": country, "country": country,
        "adActiveStatus": "active", "activeStatus": "active",
        "count": limit, "maxItems": limit, "resultsLimit": limit,
    }
    rows = apify_run("meta_ads", token, run_input, limit, raw=raw)
    items = []
    for r in rows:
        start = first(r, "startDate", "ad_delivery_start_time", "startDateFormatted",
                      "snapshot.creation_time", default=None)
        days = days_running(start)
        if min_days and days is not None and days < min_days:
            continue
        variants = first(r, "collationCount", "totalActiveTime", "variantCount", default=1)
        try:
            variants = int(variants)
        except (TypeError, ValueError):
            variants = 1
        body = first(r, "adText", "body", "snapshot.body.text", "text", "linkDescription")
        cta = first(r, "ctaText", "snapshot.cta_text", "callToActionType", default="")
        page = first(r, "pageName", "page_name", "snapshot.page_name", default="?")
        items.append(normalize(
            platform="meta_ads",
            url=first(r, "url", "adUrl", "snapshotUrl", default=""),
            author=page,
            hook=first(r, "title", "snapshot.title", "linkTitle", default=body[:80]),
            text=body,
            engagement=(days or 0) + variants * 7,   # longevity + variant proxy
            longevity_days=days,
            variant_count=variants,
            extra={"cta": cta, "country": country},
        ))
    return items


def scan_x(query, token, limit=20, raw=False):
    """Apify. Top tweets matching query, scored by likes+reposts+replies."""
    run_input = {
        "searchTerms": [query], "searchQueries": [query], "query": query,
        "maxItems": limit, "maxTweets": limit, "tweetLanguage": "en",
        "sort": "Top",
    }
    rows = apify_run("x", token, run_input, limit, raw=raw)
    items = []
    for r in rows:
        likes = int(first(r, "likeCount", "favorite_count", "likes", default=0) or 0)
        rts = int(first(r, "retweetCount", "retweet_count", "reposts", default=0) or 0)
        reps = int(first(r, "replyCount", "reply_count", "replies", default=0) or 0)
        txt = first(r, "text", "full_text", "fullText", "content")
        author = first(r, "author.userName", "username", "author.screen_name", "user.screen_name", default="?")
        items.append(normalize(
            platform="x",
            url=first(r, "url", "twitterUrl", "tweetUrl", default=""),
            author="@" + str(author).lstrip("@"),
            hook=txt[:120],
            text=txt,
            engagement=likes + rts * 2 + reps * 2,
            extra={"likes": likes, "reposts": rts, "replies": reps},
        ))
    return items


def scan_linkedin(query, token, limit=20, raw=False):
    """Apify. EXPERIMENTAL — top posts matching query, scored by reactions+comments."""
    run_input = {
        "searchQuery": query, "query": query, "keywords": query,
        "maxItems": limit, "maxResults": limit, "limit": limit,
    }
    rows = apify_run("linkedin", token, run_input, limit, raw=raw)
    items = []
    for r in rows:
        reacts = int(first(r, "numLikes", "reactionsCount", "likes", "totalReactionCount", default=0) or 0)
        comments = int(first(r, "numComments", "commentsCount", "comments", default=0) or 0)
        txt = first(r, "text", "content", "postText", "commentary")
        author = first(r, "authorName", "author.name", "actor.name", default="?")
        items.append(normalize(
            platform="linkedin",
            url=first(r, "url", "postUrl", "link", default=""),
            author=author,
            hook=txt[:120],
            text=txt,
            engagement=reacts + comments * 3,
            extra={"reactions": reacts, "comments": comments},
        ))
    return items


# -------------------------------- Main ------------------------------------ #

SCANNERS = {"meta_ads": scan_meta_ads, "x": scan_x, "reddit": scan_reddit, "linkedin": scan_linkedin}


def run_source(source, args, token):
    if source == "reddit":
        return scan_reddit(args.query, limit=args.limit, timeframe=args.timeframe, apify_token=token)
    if source in PAID_SOURCES and not token:
        print(f"[swipe_scan] Skipping '{source}' — no APIFY_TOKEN in .env.", file=sys.stderr)
        return []
    if source == "meta_ads":
        return scan_meta_ads(args.query, token, country=args.country,
                             min_days=args.min_days, limit=args.limit, raw=args.raw)
    if source == "x":
        return scan_x(args.query, token, limit=args.limit, raw=args.raw)
    if source == "linkedin":
        return scan_linkedin(args.query, token, limit=args.limit, raw=args.raw)
    return []


def main():
    load_env()
    p = argparse.ArgumentParser(description="Cross-platform winning-content radar for /content")
    p.add_argument("--source", default="reddit",
                   choices=["reddit", "meta_ads", "x", "linkedin", "all", "free"],
                   help="'all' = every source; 'free' = reddit only")
    p.add_argument("--query", required=True, help="niche / keyword / competitor (e.g. 'AI automation agency')")
    p.add_argument("--country", default="US", help="meta_ads country code")
    p.add_argument("--min-days", type=int, default=0, help="meta_ads: drop ads younger than N days")
    p.add_argument("--limit", type=int, default=15, help="max items per source (caps Apify cost)")
    p.add_argument("--timeframe", default="month", help="reddit window: day|week|month|year|all")
    p.add_argument("--top", type=int, default=10, help="how many winners to keep in the output")
    p.add_argument("--raw", action="store_true", help="dump first raw Apify item, then map fields")
    p.add_argument("--dry-run", action="store_true", help="print results, don't save")
    args = p.parse_args()

    token = os.environ.get("APIFY_TOKEN", "")
    if args.source == "all":
        sources = ["reddit", "meta_ads", "x", "linkedin"]
    elif args.source == "free":
        sources = ["reddit"]
    else:
        sources = [args.source]

    paid = [s for s in sources if s in PAID_SOURCES]
    if paid and not token:
        print(f"[swipe_scan] Note: {', '.join(paid)} need APIFY_TOKEN — running free sources only.\n"
              "  Get one at apify.com → Settings → Integrations → API token, add APIFY_TOKEN=... to .env",
              file=sys.stderr)

    all_items, ran = [], []
    for s in sources:
        got = run_source(s, args, token)
        if got:
            ran.append(s)
            all_items.extend(got)
        print(f"[swipe_scan] {s}: {len(got)} items", file=sys.stderr)

    all_items.sort(key=lambda x: x["engagement"], reverse=True)
    winners = all_items[: args.top]

    output = {
        "query": args.query,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources_run": ran,
        "scoring": {
            "meta_ads": "longevity_days + variant_count*7 (ROI proxy)",
            "x": "likes + reposts*2 + replies*2",
            "reddit": "upvotes + comments*3",
            "linkedin": "reactions + comments*3",
        },
        "count": len(winners),
        "items": winners,
    }

    if args.dry_run or args.raw:
        print(json.dumps(output, indent=2))
        return
    DATA.mkdir(exist_ok=True)
    (DATA / "swipe_intel.json").write_text(json.dumps(output, indent=2))
    print(f"[swipe_scan] Saved {len(winners)} winners to data/swipe_intel.json "
          f"(sources: {', '.join(ran) or 'none'})")
    for i, it in enumerate(winners[:5], 1):
        print(f"  {i}. [{it['platform']}] {it['hook'][:70]}  (score {it['engagement']})")


if __name__ == "__main__":
    main()
