#!/usr/bin/env python3
"""
enrich_contact.py — Apollo.io People Search enrichment.

Given a company name, finds the founder/CEO/ops lead and returns their
name, email, title, and LinkedIn URL.

Usage:
  python3 tools/enrich_contact.py --company "Acme Corp"
  python3 tools/enrich_contact.py --company "Acme Corp" --domain "acme.com"

Requires: APOLLO_API_KEY in .env
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))


def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def enrich_contact(company: str, domain: str = "", name: str = "") -> dict | None:
    """
    Enrich a contact via Apollo people/match (free tier) or mixed_people/search (paid).
    Returns {name, email, title, linkedin_url} or None.
    """
    api_key = os.environ.get("APOLLO_API_KEY", "")
    if not api_key:
        print("[enrich] APOLLO_API_KEY not set", file=sys.stderr)
        return None

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "CLIP/1.0",
    }

    # people/match works on free tier — requires name or email
    if name:
        match_payload = {"name": name, "organization_name": company}
        if domain:
            match_payload["domain"] = domain
        try:
            req = urllib.request.Request(
                "https://api.apollo.io/v1/people/match",
                data=json.dumps(match_payload).encode(),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                p = data.get("person") or {}
                if p:
                    email = p.get("email") or ""
                    return {
                        "name": p.get("name", name),
                        "email": email if email and "*" not in email else "",
                        "title": p.get("title", ""),
                        "linkedin_url": p.get("linkedin_url", ""),
                        "company": company,
                    }
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")[:300]
            print(f"[enrich] people/match HTTP {e.code}: {body}", file=sys.stderr)
        except Exception as e:
            print(f"[enrich] people/match error: {e}", file=sys.stderr)

    # mixed_people/search — requires paid plan, but try anyway
    search_payload = {
        "q_organization_name": company,
        "person_titles": ["CEO", "Founder", "Co-Founder", "COO", "Director of Operations",
                          "Head of Operations", "Managing Director", "Owner"],
        "per_page": 1,
    }
    if domain:
        search_payload["q_organization_domains"] = [domain]

    try:
        req = urllib.request.Request(
            "https://api.apollo.io/v1/mixed_people/search",
            data=json.dumps(search_payload).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            people = data.get("people", [])
            if people:
                p = people[0]
                email = p.get("email") or ""
                return {
                    "name": p.get("name", ""),
                    "email": email if email and "*" not in email else "",
                    "title": p.get("title", ""),
                    "linkedin_url": p.get("linkedin_url", ""),
                    "company": company,
                    "note": "" if email and "*" not in email else "email redacted (upgrade Apollo plan)",
                }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:300]
        if "API_INACCESSIBLE" in body:
            print("[enrich] mixed_people/search requires paid Apollo plan — use people/match with --name", file=sys.stderr)
        else:
            print(f"[enrich] mixed_people/search HTTP {e.code}: {body}", file=sys.stderr)
    except Exception as e:
        print(f"[enrich] mixed_people/search error: {e}", file=sys.stderr)

    return None


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Enrich a company contact via Apollo")
    parser.add_argument("--company", default="", help="Company name to search")
    parser.add_argument("--name", default="", help="Contact name for people/match (free tier)")
    parser.add_argument("--domain", default="", help="Optional company domain (e.g. acme.com)")
    args = parser.parse_args()

    if not args.company and not args.name:
        parser.error("Provide at least --company or --name")

    print(f"[enrich] Searching Apollo for: {args.name or args.company}")
    result = enrich_contact(args.company, args.domain, args.name)

    if result:
        print(f"\nFound:")
        print(f"  Name:     {result.get('name', '?')}")
        print(f"  Title:    {result.get('title', '?')}")
        print(f"  Email:    {result.get('email') or '(not available)'}")
        print(f"  LinkedIn: {result.get('linkedin_url') or '(not available)'}")
        if result.get("note"):
            print(f"  Note:     {result['note']}")
    else:
        print("No contact found.")
        sys.exit(1)


if __name__ == "__main__":
    main()
