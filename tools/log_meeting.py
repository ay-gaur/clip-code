#!/usr/bin/env python3
"""
log_meeting.py — Log a meeting summary + action items to data/contacts.json

Usage:
  python3 tools/log_meeting.py \
      --contact "John Smith" \
      --company "Acme Corp" \
      --date 2026-04-04 \
      --summary "Discussed automation scope, aligned on 3-month timeline" \
      --actions "Send proposal by Friday,Schedule follow-up call,Share Loom demo" \
      --notes "Ready to sign if pricing is right"

If contact doesn't exist, creates a new entry.
If contact exists, appends the meeting to their history and updates open_items.

Part of the CLIP WAT framework. Never edit contacts.json directly.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTACTS_FILE = ROOT / "data" / "contacts.json"


def read_contacts() -> list:
    if not CONTACTS_FILE.exists():
        return []
    text = CONTACTS_FILE.read_text().strip()
    if not text or text == "[]":
        return []
    return json.loads(text)


def write_contacts(contacts: list):
    CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTACTS_FILE.write_text(json.dumps(contacts, indent=2) + "\n")


def find_contact(name: str, company: str, contacts: list) -> int | None:
    name_lower = name.lower()
    company_lower = (company or "").lower()
    for i, c in enumerate(contacts):
        if c.get("name", "").lower() == name_lower:
            return i
        if company_lower and c.get("company", "").lower() == company_lower:
            return i
    return None


def main():
    parser = argparse.ArgumentParser(description="Log a meeting to contacts.json")
    parser.add_argument("--contact", required=True, help="Contact name")
    parser.add_argument("--company", default="", help="Company name")
    parser.add_argument("--role", default="", help="Contact's role/title (for new contacts)")
    parser.add_argument("--email", default="", help="Email (for new contacts)")
    parser.add_argument("--date", default=str(date.today()), help="Meeting date (YYYY-MM-DD)")
    parser.add_argument("--summary", required=True, help="One-line meeting summary")
    parser.add_argument("--actions", default="", help="Comma-separated action items")
    parser.add_argument("--notes", default="", help="Additional notes to append to contact")
    args = parser.parse_args()

    contacts = read_contacts()

    action_items = [a.strip() for a in args.actions.split(",") if a.strip()] if args.actions else []

    meeting_entry = {
        "date": args.date,
        "summary": args.summary,
        "action_items": action_items,
    }

    idx = find_contact(args.contact, args.company, contacts)

    if idx is not None:
        # Update existing contact
        c = contacts[idx]
        if "meetings" not in c:
            c["meetings"] = []
        c["meetings"].append(meeting_entry)
        c["last_meeting"] = args.date
        c["last_meeting_summary"] = args.summary

        # Merge open items (add new, don't duplicate)
        existing = set(c.get("open_items", []))
        for item in action_items:
            existing.add(item)
        c["open_items"] = sorted(existing)

        if args.notes:
            old_notes = c.get("notes", "")
            c["notes"] = f"{old_notes}\n[{args.date}] {args.notes}".strip()

        if args.company and not c.get("company"):
            c["company"] = args.company
        if args.role and not c.get("role"):
            c["role"] = args.role
        if args.email and not c.get("email"):
            c["email"] = args.email

        write_contacts(contacts)
        print(f"UPDATED: {c['name']} — meeting logged [{args.date}]")

    else:
        # Create new contact
        new_contact = {
            "name": args.contact,
            "company": args.company,
            "role": args.role,
            "email": args.email,
            "phone": "",
            "background": "",
            "added": str(date.today()),
            "last_meeting": args.date,
            "last_meeting_summary": args.summary,
            "open_items": action_items,
            "notes": f"[{args.date}] {args.notes}".strip() if args.notes else "",
            "meetings": [meeting_entry],
        }
        contacts.append(new_contact)
        write_contacts(contacts)
        print(f"CREATED: {args.contact} ({args.company}) — added to contacts")

    # Print summary
    print()
    print(f"Date:    {args.date}")
    print(f"Summary: {args.summary}")
    if action_items:
        print("Actions:")
        for a in action_items:
            print(f"  - {a}")
    if args.notes:
        print(f"Notes:   {args.notes}")


if __name__ == "__main__":
    main()
