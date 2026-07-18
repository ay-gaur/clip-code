#!/usr/bin/env python3
"""
subscription_tracker.py — Business subscription + expense tracker for CLIP.

Reads/writes data/subscriptions.json.

Usage:
  python3 tools/subscription_tracker.py               # view all subs + monthly total
  python3 tools/subscription_tracker.py --upcoming    # show next 30d billing events
  python3 tools/subscription_tracker.py --add         # interactive add (or use flags)
  python3 tools/subscription_tracker.py --remove ID   # remove by id
  python3 tools/subscription_tracker.py --usd-rate 84 # override INR→USD rate (default: 84)
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
DATA_PATH = BASE / "data" / "subscriptions.json"

DEFAULT_USD_TO_INR = 84.0  # rough exchange rate


# ── I/O ──────────────────────────────────────────────────────────────────────

def load() -> list:
    if not DATA_PATH.exists():
        return []
    try:
        return json.loads(DATA_PATH.read_text())
    except json.JSONDecodeError:
        return []


def save(subs: list) -> None:
    DATA_PATH.write_text(json.dumps(subs, indent=2))


# ── Helpers ───────────────────────────────────────────────────────────────────

def to_monthly_usd(sub: dict, usd_rate: float) -> float:
    """Normalise any subscription to a monthly USD cost."""
    amount = sub.get("amount")
    amount_inr = sub.get("amount_inr")
    cycle = sub.get("billing_cycle", "monthly")

    if cycle == "pay-as-you-go":
        return 0.0  # variable — excluded from fixed monthly total

    if amount is not None:
        monthly = amount / 12 if cycle == "annual" else amount
    elif amount_inr is not None:
        monthly_inr = amount_inr / 12 if cycle == "annual" else amount_inr
        monthly = monthly_inr / usd_rate
    else:
        monthly = 0.0

    return round(monthly, 2)


def format_cost(sub: dict) -> str:
    """Human-readable cost string."""
    cycle = sub.get("billing_cycle", "monthly")
    if cycle == "pay-as-you-go":
        return "pay-as-you-go"
    if sub.get("amount_inr") is not None:
        amt = sub["amount_inr"]
        label = f"₹{amt:.2f}"
    elif sub.get("amount") is not None:
        amt = sub["amount"]
        label = f"${amt:.2f}"
    else:
        return "unknown"
    suffix = "/yr" if cycle == "annual" else "/mo"
    return label + suffix


def days_until(date_str: str) -> int | None:
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (d - date.today()).days
    except ValueError:
        return None


# ── Views ─────────────────────────────────────────────────────────────────────

def view_all(subs: list, usd_rate: float) -> None:
    active = [s for s in subs if s.get("status") == "active"]
    inactive = [s for s in subs if s.get("status") != "active"]

    categories = {}
    for s in active:
        cat = s.get("category", "other")
        categories.setdefault(cat, []).append(s)

    total_monthly_usd = sum(to_monthly_usd(s, usd_rate) for s in active)
    total_annual_usd = total_monthly_usd * 12

    print("=" * 52)
    print("  CLIP — Subscription Tracker")
    print(f"  As of {date.today().strftime('%B %d, %Y')}")
    print("=" * 52)

    for cat, items in sorted(categories.items()):
        print(f"\n── {cat.upper()} {'─' * (38 - len(cat))}")
        for s in items:
            cost = format_cost(s)
            next_b = s.get("next_billing")
            d = days_until(next_b)
            if d is not None:
                if d <= 7:
                    billing_str = f"  ⚠️  next billing in {d}d ({next_b})"
                elif d <= 30:
                    billing_str = f"  → next billing in {d}d ({next_b})"
                else:
                    billing_str = f"  → renews {next_b}"
            elif s.get("billing_cycle") == "pay-as-you-go":
                billing_str = "  → usage-based"
            else:
                billing_str = ""

            print(f"  {s['name']}")
            print(f"     {cost}{billing_str}")
            if s.get("notes"):
                print(f"     note: {s['notes']}")

    print(f"\n{'─' * 52}")
    print(f"  Fixed monthly total:  ~${total_monthly_usd:.2f}/mo USD")
    print(f"  Fixed annual total:   ~${total_annual_usd:.2f}/yr USD")
    print(f"  (excl. pay-as-you-go; INR converted at ₹{usd_rate:.0f}=$1)")

    if inactive:
        print(f"\n── INACTIVE ───────────────────────────────────")
        for s in inactive:
            print(f"  {s['name']} [{s.get('status')}]")

    print()


def view_upcoming(subs: list, days: int = 30) -> None:
    print(f"\nUpcoming billing in next {days} days:\n")
    events = []
    for s in subs:
        if s.get("status") != "active":
            continue
        nb = s.get("next_billing")
        d = days_until(nb)
        if d is not None and 0 <= d <= days:
            events.append((d, s, nb))

    if not events:
        print(f"  Nothing due in the next {days} days.")
        return

    for d, s, nb in sorted(events):
        cost = format_cost(s)
        flag = "⚠️ " if d <= 7 else "→ "
        print(f"  {flag}{nb} ({d}d)  {s['name']}  [{cost}]")
    print()


# ── Mutators ──────────────────────────────────────────────────────────────────

def add_sub(subs: list) -> list:
    print("\nAdd a new subscription (press Enter to skip optional fields):\n")
    name = input("  Name: ").strip()
    vendor = input("  Vendor: ").strip()
    category = input("  Category (ai-tools / productivity / infrastructure / other): ").strip() or "other"
    cycle = input("  Billing cycle (monthly / annual / pay-as-you-go): ").strip() or "monthly"
    currency = input("  Currency (USD / INR): ").strip().upper() or "USD"
    amount_str = input(f"  Amount ({currency}): ").strip()
    amount = float(amount_str) if amount_str else None
    next_billing = input("  Next billing date (YYYY-MM-DD): ").strip() or None
    notes = input("  Notes (optional): ").strip() or None

    slug = name.lower().replace(" ", "-").replace(".", "")
    new_id = f"{vendor.lower()}-{slug}"[:32]

    entry = {
        "id": new_id,
        "name": name,
        "vendor": vendor,
        "category": category,
        "billing_cycle": cycle,
        "amount": amount if currency == "USD" else None,
        "currency": currency,
        "amount_inr": amount if currency == "INR" else None,
        "status": "active",
        "start_date": date.today().isoformat(),
        "next_billing": next_billing,
        "notes": notes,
    }

    subs.append(entry)
    print(f"\n  ✅ Added: {name}")
    return subs


def remove_sub(subs: list, sub_id: str) -> list:
    before = len(subs)
    subs = [s for s in subs if s.get("id") != sub_id]
    if len(subs) < before:
        print(f"  Removed: {sub_id}")
    else:
        # Try fuzzy match on name
        matches = [s for s in subs if sub_id.lower() in s.get("name", "").lower()]
        if matches:
            print(f"  No exact ID match. Did you mean one of these?")
            for m in matches:
                print(f"    id: {m['id']}  name: {m['name']}")
        else:
            print(f"  No subscription found with id: {sub_id}")
    return subs


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CLIP Subscription Tracker")
    parser.add_argument("--upcoming", action="store_true", help="Show next 30d billing events")
    parser.add_argument("--add", action="store_true", help="Add a new subscription interactively")
    parser.add_argument("--remove", metavar="ID", help="Remove subscription by ID")
    parser.add_argument("--usd-rate", type=float, default=DEFAULT_USD_TO_INR,
                        help=f"INR per USD for conversion (default: {DEFAULT_USD_TO_INR})")
    args = parser.parse_args()

    subs = load()

    if args.remove:
        subs = remove_sub(subs, args.remove)
        save(subs)
        return

    if args.add:
        subs = add_sub(subs)
        save(subs)

    if args.upcoming:
        view_upcoming(subs)
    else:
        view_all(subs, args.usd_rate)


if __name__ == "__main__":
    main()
