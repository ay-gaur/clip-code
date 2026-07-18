#!/usr/bin/env python3
"""
reddit_intel.py — Weekly Reddit pain point scanner for content ideas.

Scans Reddit via Tavily for automation/ops pain points from founders and
small business owners. Extracts top pain points, what's working, and
3 LinkedIn post angles for Alex's personal brand.

Runs Monday 8:00am IST via APScheduler.

Usage:
  python3 tools/reddit_intel.py           # full run + save
  python3 tools/reddit_intel.py --dry-run # print, don't save

Requires: TAVILY_API_KEY, ANTHROPIC_API_KEY in .env
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
sys.path.insert(0, str(BASE))


def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


REDDIT_QUERIES = [
    "site:reddit.com/r/entrepreneur automation \"manual process\" OR \"overwhelmed\" OR \"no system\"",
    "site:reddit.com/r/smallbusiness AI automation ops founder 2025 OR 2026",
    "site:reddit.com/r/startups \"still doing manually\" OR \"hiring for ops\" automation",
    "site:reddit.com/r/indianstartups automation AI tools founder",
    "site:reddit.com founder \"I spend hours\" OR \"waste time\" email OR CRM OR outreach",
]


def fetch_reddit_signals() -> list[dict]:
    """Run Tavily searches and return raw results."""
    try:
        from tavily import TavilyClient
    except ImportError:
        print("[reddit_intel] tavily-python not installed", file=sys.stderr)
        return []

    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        print("[reddit_intel] TAVILY_API_KEY not set", file=sys.stderr)
        return []

    client = TavilyClient(api_key=api_key)
    all_results = []

    for query in REDDIT_QUERIES:
        try:
            resp = client.search(query, max_results=3, search_depth="basic")
            results = resp.get("results", [])
            all_results.extend(results)
            print(f"[reddit_intel] '{query[:60]}...' → {len(results)} results")
        except Exception as e:
            print(f"[reddit_intel] Search error: {e}", file=sys.stderr)

    return all_results


def synthesize_intel(results: list[dict]) -> dict:
    """Use Claude Haiku to extract pain points and post angles."""
    if not results:
        return {}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[reddit_intel] ANTHROPIC_API_KEY not set", file=sys.stderr)
        return {}

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    results_text = "\n\n".join(
        f"Source: {r.get('url', '')}\n{r.get('content', '')[:500]}"
        for r in results[:15]
    )

    prompt = f"""You are analyzing Reddit posts and discussions to find content ideas for Alex Doe,
an AI automation builder in India who writes about helping founders automate their business ops.

## Reddit content this week:
{results_text}

## Extract:
1. Top 3 pain points founders are complaining about (with a real quote or specific example from the content)
2. Top 2 things that ARE working (tools/approaches people are celebrating)
3. 3 LinkedIn post angles for Alex — specific, concrete, engaging

For the post angles, use these formats (one each):
- Story: "I [did X for my own business]. Here's what happened..." (personal experience)
- Pain→solution: "If you're still doing [specific pain] manually, here's the fix." (direct value)
- Contrarian: "Everyone says [popular belief]. I disagree. Here's why." (engagement hook)

Return ONLY valid JSON:
{{
  "pain_points": [
    {{"pain": "one sentence", "quote": "actual quote or specific example", "frequency": "common/occasional"}}
  ],
  "what_works": [
    {{"insight": "what people are saying works", "source": "reddit community or context"}}
  ],
  "post_angles": [
    {{"format": "story|pain_solution|contrarian", "hook": "first line of the post", "angle": "what the post is about"}}
  ]
}}"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        from tools.credits import track_usage
        track_usage("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens)

        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        return json.loads(text.strip())
    except Exception as e:
        print(f"[reddit_intel] Synthesis error: {e}", file=sys.stderr)
        return {}


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Weekly Reddit pain point scanner")
    parser.add_argument("--dry-run", action="store_true", help="Print output, don't save")
    args = parser.parse_args()

    print(f"[reddit_intel] Running — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    results = fetch_reddit_signals()
    if not results:
        print("[reddit_intel] No results fetched.")
        return

    print(f"[reddit_intel] {len(results)} total results — synthesizing...")
    intel = synthesize_intel(results)

    if not intel:
        print("[reddit_intel] Synthesis failed.")
        return

    intel["week"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    intel["source_count"] = len(results)

    if args.dry_run:
        print("\n--- REDDIT INTEL (dry run) ---")
        print(json.dumps(intel, indent=2))
        return

    DATA.mkdir(exist_ok=True)
    (DATA / "content_intel.json").write_text(json.dumps(intel, indent=2))
    print(f"[reddit_intel] Saved to data/content_intel.json")

    # Print summary
    pains = intel.get("pain_points", [])
    angles = intel.get("post_angles", [])
    print(f"\nTop pain: {pains[0]['pain'] if pains else 'none'}")
    print(f"Post angles ready: {len(angles)}")

    # Push Telegram notification
    if angles:
        try:
            from tools.notify import send_telegram
            lines = ["⚡ *Reddit intel ready — {len(angles)} post angles*\n"]
            for a in angles:
                lines.append(f"• {a.get('hook', '')[:80]}")
            lines.append("\n_Type /drafts to see full posts_")
            send_telegram("\n".join(lines))
        except Exception as e:
            print(f"[reddit_intel] Telegram push failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
