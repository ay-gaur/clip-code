#!/usr/bin/env python3
"""
outreach_draft.py — Generate a cold outreach email draft for a lead.

Reads the lead from data/leads.json by company name (fuzzy match).
Calls Claude API to write a personalized cold email.
Saves draft to data/outreach_drafts.json.
Optionally tries to enrich with Apollo.io contact info.

Requires in .env:
  ANTHROPIC_API_KEY=sk-ant-...
  APOLLO_API_KEY=...              (optional, for contact enrichment)
  GMAIL_FROM                     (used as sender identity in the draft)

Usage:
  python3 tools/outreach_draft.py --company "TechCorp India"
  python3 tools/outreach_draft.py --company "TechCorp" --contact "Rahul Sharma"
  python3 tools/outreach_draft.py --list              # show all leads to pick from
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
LEADS_PATH = BASE / "data" / "leads.json"
DRAFTS_PATH = BASE / "data" / "outreach_drafts.json"
CONTEXT_WORK = BASE / "context" / "work.md"
CONTEXT_ME = BASE / "context" / "me.md"


def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

load_env()


def load_leads() -> list:
    if not LEADS_PATH.exists():
        return []
    try:
        return json.loads(LEADS_PATH.read_text())
    except json.JSONDecodeError:
        return []


def load_drafts() -> list:
    if not DRAFTS_PATH.exists() or DRAFTS_PATH.read_text().strip() in ("", "[]"):
        return []
    try:
        return json.loads(DRAFTS_PATH.read_text())
    except json.JSONDecodeError:
        return []


def save_drafts(drafts: list) -> None:
    DRAFTS_PATH.write_text(json.dumps(drafts, indent=2))


def find_lead(leads: list, company: str) -> dict | None:
    """Fuzzy match: find lead by company name (case-insensitive substring)."""
    company_lower = company.lower()
    # Exact match first
    for lead in leads:
        if lead.get("company", "").lower() == company_lower:
            return lead
    # Substring match
    for lead in leads:
        if company_lower in lead.get("company", "").lower():
            return lead
    return None


def enrich_with_apollo(company: str, domain: str = None) -> dict | None:
    """
    Try to get a contact from Apollo.io for the given company.
    Returns {name, email, title} or None.
    """
    api_key = os.environ.get("APOLLO_API_KEY", "")
    if not api_key:
        return None

    try:
        import urllib.request
        import urllib.error

        payload = json.dumps({
            "api_key": api_key,
            "q_organization_name": company,
            "person_titles": ["CEO", "Founder", "Operations Manager", "CTO", "Director"],
            "per_page": 1,
        }).encode()

        req = urllib.request.Request(
            "https://api.apollo.io/v1/mixed_people/search",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            people = data.get("people", [])
            if people:
                p = people[0]
                return {
                    "name": p.get("name"),
                    "email": p.get("email"),
                    "title": p.get("title"),
                }
    except Exception as e:
        print(f"[outreach_draft] Apollo enrichment failed: {e}", file=sys.stderr)

    return None


def build_context() -> str:
    """Read work.md and me.md to give Claude business context."""
    parts = []
    for path in [CONTEXT_WORK, CONTEXT_ME]:
        if path.exists():
            parts.append(path.read_text().strip())
    return "\n\n---\n\n".join(parts)


def generate_draft(lead: dict, contact: dict | None, linkedin: bool = False) -> tuple[str, str]:
    """
    Call Claude API to generate a cold email or LinkedIn DM.
    Returns (subject_or_note, body).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[outreach_draft] ERROR: ANTHROPIC_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    try:
        import anthropic
    except ImportError:
        print("[outreach_draft] ERROR: anthropic not installed. Run: pip3 install anthropic", file=sys.stderr)
        sys.exit(1)

    business_context = build_context()
    contact_name = (contact or {}).get("name") or lead.get("contact_name") or "there"

    icp_path = BASE / "context" / "icp.md"
    pitch_path = BASE / "context" / "pitch.md"
    icp_context = icp_path.read_text().strip()[:800] if icp_path.exists() else ""
    pitch_context = pitch_path.read_text().strip()[:800] if pitch_path.exists() else ""

    if linkedin:
        prompt = f"""You are writing a LinkedIn connection request + first message on behalf of Alex Doe, an AI automation builder in India.

## About Alex
{business_context[:600]}

## What he sells
{pitch_context[:400]}

## Target person
Name: {contact_name}
Company: {lead.get('company') or 'their company'}
Pain signal: {lead.get('pain_signal') or 'operations pain'}

## Instructions
Write a LinkedIn DM (sent AFTER they accept the connection request). Rules:
- MAX 5 lines total. LinkedIn DMs that are too long get ignored.
- Open by referencing something specific they said or did (the pain signal)
- One sentence on what Alex does and why it's relevant
- One concrete thing CLIP does (specific, not generic)
- Soft CTA — "would it make sense to chat?" or "happy to share more if useful"
- NO "I came across your profile", NO "I hope this message finds you well"
- Casual, direct, peer-to-peer. Like a text, not an email.
- First name only, no "Dear"

Also write a SHORT connection note (max 2 lines, shown before they accept).

Output format — exactly this, no extra text:
NOTE: <2-line connection request note>
---
<DM message after they accept>"""
    else:
        prompt = f"""You are writing a cold outreach email on behalf of Alex Doe, an AI automation builder in India.

## About Alex + his business
{business_context}

## What he sells
{pitch_context}

## ICP (who this is for)
{icp_context}

## Target Lead
Company: {lead.get('company') or 'Unknown'}
Contact: {contact_name}
Pain signal: {lead.get('pain_signal') or 'operations pain'}

## Instructions
Write a short, direct cold outreach email. Rules:
- Subject line: specific, references their actual pain signal
- Body: max 4 short paragraphs, no fluff
  1. What you noticed about them (reference the pain signal specifically)
  2. What you do and why it's directly relevant (1-2 lines)
  3. One concrete proof point — what CLIP does for Alex's own business
  4. Simple CTA: 15-min call, no pressure
- Tone: direct, peer-to-peer, not salesy. Like one founder to another.
- Indian context is fine. Don't be overly formal.
- Sign off as Alex Doe
- Do NOT use placeholders like [Company Name] — use actual names

Output format — exactly this, no extra text:
SUBJECT: <subject line>
---
<email body>"""

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    from tools.credits import track_usage
    track_usage("claude-sonnet-4-6", response.usage.input_tokens, response.usage.output_tokens)

    text = response.content[0].text.strip()

    if linkedin:
        if "NOTE:" in text and "---" in text:
            subject_line = text.split("NOTE:")[1].split("---")[0].strip()
            body = text.split("---", 1)[1].strip()
        else:
            subject_line = "LinkedIn connection note"
            body = text
        return subject_line, body

    # Parse email subject and body
    if "SUBJECT:" in text and "---" in text:
        subject_line = text.split("SUBJECT:")[1].split("---")[0].strip()
        body = text.split("---", 1)[1].strip()
    else:
        subject_line = f"Automation for {lead.get('company', 'your team')}"
        body = text

    return subject_line, body


def make_draft_id(company: str) -> str:
    ts = date.today().isoformat()
    return hashlib.md5(f"{company}|{ts}".encode()).hexdigest()[:10]


def main():
    parser = argparse.ArgumentParser(description="CLIP Outreach Draft Generator")
    parser.add_argument("--company", help="Company name to draft for")
    parser.add_argument("--contact", help="Contact person name (optional)")
    parser.add_argument("--linkedin", action="store_true", help="Generate LinkedIn DM instead of email")
    parser.add_argument("--list", action="store_true", help="List all leads")
    args = parser.parse_args()

    leads = load_leads()

    if args.list or not args.company:
        if not leads:
            print("No leads found in data/leads.json. Run lead_scan.py first.")
            sys.exit(0)
        print(f"Leads in data/leads.json ({len(leads)} total):\n")
        new = [l for l in leads if l.get("status") == "new"]
        for i, l in enumerate(new, 1):
            pain = l.get('pain_signal', l.get('role_posted', 'no signal'))[:80]
            print(f"  {i}. {l.get('company') or l.get('contact_name', '?')} — {pain} (found {l['discovered']})")
        print(f"\nUsage: python3 tools/outreach_draft.py --company \"Company Name\"")
        sys.exit(0)

    lead = find_lead(leads, args.company)
    if not lead:
        # Also try matching by contact name
        for l in leads:
            if args.company.lower() in l.get("contact_name", "").lower():
                lead = l
                break
    if not lead:
        print(f"[outreach_draft] Lead not found for '{args.company}'.")
        print("Run: python3 tools/outreach_draft.py --list")
        sys.exit(1)

    print(f"[outreach_draft] Generating draft for: {lead['company']}")

    # Try Apollo enrichment (skipped if key not set)
    contact = None
    if not args.contact and os.environ.get("APOLLO_API_KEY"):
        contact = enrich_with_apollo(lead["company"])
        if contact:
            print(f"[outreach_draft] Apollo found: {contact['name']} ({contact.get('title', '')})")
    else:
        contact = {"name": args.contact, "email": None, "title": None}

    mode = "LinkedIn DM" if args.linkedin else "email"
    print(f"[outreach_draft] Calling Claude API ({mode})...")
    subject, body = generate_draft(lead, contact, linkedin=args.linkedin)

    draft = {
        "id": make_draft_id(lead["company"] + mode),
        "created": date.today().isoformat(),
        "lead_id": lead.get("id"),
        "lead_company": lead.get("company") or lead.get("contact_name"),
        "lead_contact_name": (contact.get("name") if contact else None) or lead.get("contact_name"),
        "lead_contact_email": contact.get("email") if contact else None,
        "lead_contact_linkedin": lead.get("contact_linkedin", ""),
        "type": "linkedin_dm" if args.linkedin else "email",
        "subject": subject,
        "body": body,
        "status": "draft",  # draft | approved | sent
    }

    # Save
    drafts = load_drafts()
    drafts.append(draft)
    save_drafts(drafts)

    # Update lead status
    for l in leads:
        if l.get("id") == lead.get("id"):
            l["status"] = "outreach_drafted"
    LEADS_PATH.write_text(json.dumps(leads, indent=2))

    print(f"\n{'='*50}")
    if args.linkedin:
        print(f"CONNECTION NOTE: {subject}")
        print(f"{'='*50}")
        print(body)
        linkedin_url = lead.get("contact_linkedin", "")
        if linkedin_url:
            print(f"\nLinkedIn profile: {linkedin_url}")
    else:
        print(f"SUBJECT: {subject}")
        print(f"{'='*50}")
        print(body)
    print(f"{'='*50}")
    print(f"\nSaved to data/outreach_drafts.json (id: {draft['id']})")


if __name__ == "__main__":
    main()
