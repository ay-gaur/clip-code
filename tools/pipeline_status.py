#!/usr/bin/env python3
"""
pipeline_status.py — Deterministic tool for reading/writing data/pipeline.json

Usage:
  python3 tools/pipeline_status.py --action list
  python3 tools/pipeline_status.py --action list --stage prospect
  python3 tools/pipeline_status.py --action add --name "Contact Name" --company "Company" --stage prospect --type dtc --value 5000 --notes "context"
  python3 tools/pipeline_status.py --action move --id p001 --stage qualified
  python3 tools/pipeline_status.py --action remove --id p001
  python3 tools/pipeline_status.py --action update --id p001 --notes "new notes" --last_contact 2026-03-09

Part of the CLIP WAT framework. AI agents call this; never edit pipeline.json directly.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
PIPELINE_FILE = ROOT / "data" / "pipeline.json"

STAGES = ["prospect", "contacted", "qualified", "proposal", "negotiation", "client", "closed_lost"]

STAGE_LABELS = {
    "prospect":    "🔍 Prospects",
    "contacted":   "📧 Contacted",
    "qualified":   "💬 Qualified",
    "proposal":    "📋 Proposal Sent",
    "negotiation": "🤝 Negotiation",
    "client":      "✅ Active Clients",
    "closed_lost": "❌ Closed/Lost",
}

TYPES = ["dtc", "manufacturer", "b2b", "other"]


def read_pipeline():
    if not PIPELINE_FILE.exists():
        return []
    return json.loads(PIPELINE_FILE.read_text())


def write_pipeline(records):
    PIPELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PIPELINE_FILE.write_text(json.dumps(records, indent=2) + "\n")


def generate_id(records):
    existing = {r["id"] for r in records}
    n = len(records) + 1
    while f"p{n:03d}" in existing:
        n += 1
    return f"p{n:03d}"


def action_list(stage_filter=None):
    records = read_pipeline()

    if stage_filter:
        if stage_filter not in STAGES:
            print(f"ERROR: Unknown stage '{stage_filter}'. Valid: {', '.join(STAGES)}")
            sys.exit(1)
        by_stage = {stage_filter: [r for r in records if r["stage"] == stage_filter]}
    else:
        by_stage = {s: [] for s in STAGES}
        for r in records:
            stage = r.get("stage", "prospect")
            if stage in by_stage:
                by_stage[stage].append(r)

    # Print summary
    total_value = sum(r.get("value") or 0 for r in records if r["stage"] != "closed_lost")
    active_stages = [s for s in STAGES if s != "closed_lost" and by_stage.get(s)]

    if not any(by_stage.get(s) for s in STAGES):
        print("Pipeline is empty. Add your first contact with --action add.")
        return

    for stage in STAGES:
        contacts = by_stage.get(stage, [])
        label = STAGE_LABELS[stage]
        count = len(contacts)
        if not contacts:
            continue
        print(f"\n{label} ({count})")
        for c in contacts:
            value_str = f"~${c['value']:,}/mo" if c.get("value") else ""
            type_str = c.get("type", "").upper()
            last = f"  [last: {c['last_contact']}]" if c.get("last_contact") else ""
            parts = [f"- [{c['id']}] {c['name']}"]
            if c.get("company"):
                parts.append(f"— {c['company']}")
            if type_str:
                parts.append(f"({type_str})")
            if value_str:
                parts.append(value_str)
            if last:
                parts.append(last)
            print(" ".join(parts))
            if c.get("notes"):
                print(f"  ↳ {c['notes']}")

    print(f"\nTotal pipeline value (excl. closed): ~${total_value:,}")
    print(f"Total contacts: {len(records)}")


def action_add(name, company, stage, contact_type, value, notes):
    if stage not in STAGES:
        print(f"ERROR: Unknown stage '{stage}'. Valid: {', '.join(STAGES)}")
        sys.exit(1)
    if contact_type not in TYPES:
        print(f"ERROR: Unknown type '{contact_type}'. Valid: {', '.join(TYPES)}")
        sys.exit(1)

    records = read_pipeline()

    # Check for duplicate name+company
    for r in records:
        if r["name"].lower() == name.lower() and r.get("company", "").lower() == (company or "").lower():
            print(f"DUPLICATE: '{name}' at '{company}' already exists (id: {r['id']}).")
            sys.exit(1)

    new_id = generate_id(records)
    record = {
        "id": new_id,
        "name": name,
        "company": company or "",
        "stage": stage,
        "type": contact_type,
        "value": int(value) if value else 0,
        "notes": notes or "",
        "last_contact": None,
        "added": str(date.today()),
    }
    records.append(record)
    write_pipeline(records)
    print(f"ADDED: [{new_id}] {name} ({company}) → {stage}")


def action_move(record_id, new_stage):
    if new_stage not in STAGES:
        print(f"ERROR: Unknown stage '{new_stage}'. Valid: {', '.join(STAGES)}")
        sys.exit(1)

    records = read_pipeline()
    for r in records:
        if r["id"] == record_id:
            old_stage = r["stage"]
            r["stage"] = new_stage
            r["last_contact"] = str(date.today())
            write_pipeline(records)
            print(f"MOVED: [{record_id}] {r['name']} — {old_stage} → {new_stage}")
            return

    print(f"NOT_FOUND: No record with id '{record_id}'.")
    sys.exit(1)


def action_remove(record_id):
    records = read_pipeline()
    for i, r in enumerate(records):
        if r["id"] == record_id:
            removed = records.pop(i)
            write_pipeline(records)
            print(f"REMOVED: [{record_id}] {removed['name']} ({removed.get('company', '')})")
            return

    print(f"NOT_FOUND: No record with id '{record_id}'.")
    sys.exit(1)


def action_update(record_id, notes=None, last_contact=None, value=None):
    records = read_pipeline()
    for r in records:
        if r["id"] == record_id:
            if notes is not None:
                r["notes"] = notes
            if last_contact is not None:
                r["last_contact"] = last_contact
            if value is not None:
                r["value"] = int(value)
            write_pipeline(records)
            print(f"UPDATED: [{record_id}] {r['name']}")
            return

    print(f"NOT_FOUND: No record with id '{record_id}'.")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Manage data/pipeline.json")
    parser.add_argument("--action", choices=["list", "add", "move", "remove", "update"], required=True)

    # list
    parser.add_argument("--stage", type=str, help="Filter by stage (for list), or target stage (for move/add)")

    # add
    parser.add_argument("--name", type=str)
    parser.add_argument("--company", type=str, default="")
    parser.add_argument("--type", dest="contact_type", type=str, default="other")
    parser.add_argument("--value", type=int, default=0)
    parser.add_argument("--notes", type=str, default="")

    # move / remove / update
    parser.add_argument("--id", type=str)
    parser.add_argument("--last_contact", type=str)

    args = parser.parse_args()

    if args.action == "list":
        action_list(stage_filter=args.stage)

    elif args.action == "add":
        if not args.name:
            print("ERROR: --name is required for add")
            sys.exit(1)
        if not args.stage:
            print("ERROR: --stage is required for add")
            sys.exit(1)
        action_add(args.name, args.company, args.stage, args.contact_type, args.value, args.notes)

    elif args.action == "move":
        if not args.id or not args.stage:
            print("ERROR: --id and --stage are required for move")
            sys.exit(1)
        action_move(args.id, args.stage)

    elif args.action == "remove":
        if not args.id:
            print("ERROR: --id is required for remove")
            sys.exit(1)
        action_remove(args.id)

    elif args.action == "update":
        if not args.id:
            print("ERROR: --id is required for update")
            sys.exit(1)
        action_update(args.id, notes=args.notes or None, last_contact=args.last_contact, value=args.value or None)


if __name__ == "__main__":
    main()
