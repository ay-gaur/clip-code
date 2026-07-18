#!/usr/bin/env python3
"""
find_leads.py — ICP-based company discovery for Acme Studio outbound.

Searches for B2B founders/operators with ops pain signals using Tavily web search,
scores each result for ICP fit using Claude Haiku, and saves to data/leads.json.

Sources searched: LinkedIn posts (pain signals), YourStory, Inc42, IndiaMART,
Crunchbase India — NOT job boards.

Usage:
  python3 tools/find_leads.py                        # run default ICP queries
  python3 tools/find_leads.py --query "custom query" # run custom query
  python3 tools/find_leads.py --count 15             # find more leads
  python3 tools/find_leads.py --dry-run              # print results, don't save

Requires: TAVILY_API_KEY, ANTHROPIC_API_KEY in .env
"""

import argparse
import json
import os
import sys
import uuid
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


# Default ICP search queries — targets founders with visible ops pain
DEFAULT_QUERIES = [
    'site:linkedin.com "founder" OR "CEO" "overwhelmed" OR "hiring ops" OR "manual process" India automation',
    'site:yourstory.com B2B startup "operations" India 2025 OR 2026',
    'site:inc42.com startup India "automation" OR "operations" B2B 2025 OR 2026',
    'site:linkedin.com India founder "still doing manually" OR "no system" OR "ops is a mess"',
    'India B2B company founder "looking for" automation CRM outreach',
]


def search_tavily(query: str, max_results: int = 5) -> list[dict]:
    """Run a Tavily search. Returns list of {title, url, content}."""
    try:
        from tavily import TavilyClient
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            print("[find_leads] TAVILY_API_KEY not set", file=sys.stderr)
            return []
        client = TavilyClient(api_key=api_key)
        resp = client.search(query, max_results=max_results, search_depth="advanced")
        return resp.get("results", [])
    except ImportError:
        print("[find_leads] tavily-python not installed — run: pip install tavily-python", file=sys.stderr)
        return []
    except Exception as e:
        print(f"[find_leads] Tavily error: {e}", file=sys.stderr)
        return []


def score_results(results: list[dict], icp_context: str) -> list[dict]:
    """
    Use Claude Haiku to score each search result for ICP fit.
    Returns list of {company, contact_name, contact_email, contact_linkedin,
                     fit_score, pain_signal, source_url, raw_title}
    """
    if not results:
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[find_leads] ANTHROPIC_API_KEY not set", file=sys.stderr)
        return []

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    results_text = "\n\n".join(
        f"RESULT {i+1}:\nTitle: {r.get('title','')}\nURL: {r.get('url','')}\nContent: {r.get('content','')[:400]}"
        for i, r in enumerate(results)
    )

    prompt = f"""You are a lead qualification agent for Acme Studio, an AI automation agency based in India.

## Ideal Customer Profile
{icp_context}

## Search Results to Evaluate
{results_text}

## Task
For each result, extract any real companies or individuals that match the ICP.
Ignore news articles, job aggregators, generic listicles, or results about companies that clearly don't fit.

For each valid lead found, return:
- company: company name (string)
- contact_name: person's name if identifiable (string or "")
- contact_linkedin: LinkedIn URL if present (string or "")
- fit_score: 0-10, how well they match the ICP (10 = perfect fit)
- pain_signal: one sentence describing the specific pain/buying signal you observed
- source_url: the URL where you found them

Return ONLY a JSON array (no markdown, no explanation):
[
  {{
    "company": "...",
    "contact_name": "...",
    "contact_linkedin": "...",
    "fit_score": 7,
    "pain_signal": "...",
    "source_url": "..."
  }}
]

If no valid leads are found, return: []"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        from tools.credits import track_usage
        track_usage("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens)

        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        leads = json.loads(text.strip())
        return leads if isinstance(leads, list) else []
    except Exception as e:
        print(f"[find_leads] Scoring error: {e}", file=sys.stderr)
        return []


def load_leads() -> list:
    path = DATA / "leads.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def save_leads(leads: list):
    DATA.mkdir(exist_ok=True)
    (DATA / "leads.json").write_text(json.dumps(leads, indent=2))


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Find ICP-matching leads via Tavily + Claude")
    parser.add_argument("--query", default="", help="Custom search query (default: run all ICP queries)")
    parser.add_argument("--count", type=int, default=10, help="Target number of new leads to find")
    parser.add_argument("--dry-run", action="store_true", help="Print results, don't save")
    args = parser.parse_args()

    # Load ICP context
    icp_path = BASE / "context" / "icp.md"
    icp_context = icp_path.read_text().strip() if icp_path.exists() else "B2B founders in India, 10-100 person companies, manual ops pain"

    queries = [args.query] if args.query else DEFAULT_QUERIES
    existing_leads = load_leads()
    existing_urls = {l.get("source_url", "") for l in existing_leads}
    existing_companies = {l.get("company", "").lower() for l in existing_leads}

    new_leads = []
    total_results = 0

    for i, query in enumerate(queries):
        if len(new_leads) >= args.count:
            break
        print(f"[find_leads] Query {i+1}/{len(queries)}: {query[:80]}...")
        results = search_tavily(query, max_results=5)
        total_results += len(results)
        print(f"[find_leads]   → {len(results)} results")

        scored = score_results(results, icp_context)
        for lead in scored:
            company_key = lead.get("company", "").lower()
            url = lead.get("source_url", "")
            # Deduplicate by company + URL
            if company_key in existing_companies or url in existing_urls:
                continue
            if lead.get("fit_score", 0) < 5:
                continue  # Filter out weak fits

            lead["id"] = str(uuid.uuid4())[:10]
            lead["contact_email"] = ""
            lead["discovered"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            lead["status"] = "new"
            lead["enriched"] = False

            new_leads.append(lead)
            existing_companies.add(company_key)
            existing_urls.add(url)
            print(f"  ✓ [{lead['fit_score']}/10] {lead['company']} — {lead['pain_signal'][:60]}")

    print(f"\n[find_leads] Found {len(new_leads)} new leads from {total_results} search results")

    if args.dry_run:
        print("\n--- DRY RUN (not saved) ---")
        print(json.dumps(new_leads, indent=2))
        return

    if new_leads:
        all_leads = existing_leads + new_leads
        save_leads(all_leads)
        print(f"[find_leads] Saved to data/leads.json ({len(all_leads)} total)")
    else:
        print("[find_leads] No new leads found.")


if __name__ == "__main__":
    main()
