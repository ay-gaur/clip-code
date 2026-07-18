#!/usr/bin/env python3
"""
content_draft.py — LinkedIn post drafter from Reddit intel.

Reads data/content_intel.json (written by reddit_intel.py) and generates
3 ready-to-post LinkedIn posts in Alex's voice. Saves to data/content_drafts.json
and pushes a Telegram notification.

Runs Monday 8:30am IST via APScheduler (30min after reddit_intel.py).

Usage:
  python3 tools/content_draft.py           # full run + save
  python3 tools/content_draft.py --dry-run # print, don't save

Requires: ANTHROPIC_API_KEY in .env
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
CONTEXT = BASE / "context"
sys.path.insert(0, str(BASE))


def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


USER_VOICE = """
Alex's LinkedIn voice:
- Direct and casual, like texting a smart friend
- No corporate fluff, no "I'm excited to share"
- Short paragraphs, lots of line breaks (LinkedIn formatting)
- Specific and concrete — real numbers, real situations, not vague
- First-person stories work best
- Ends with a question or clear takeaway
- Occasionally swears or uses casual Indian English (no forced Indianisms)
- Never uses: "delighted", "thrilled", "synergy", "ecosystem", "leverage"
- Max 250 words per post
"""


def draft_posts(intel: dict) -> list[dict]:
    """Generate 3 LinkedIn post drafts from Reddit intel."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[content_draft] ANTHROPIC_API_KEY not set", file=sys.stderr)
        return []

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    # Load me.md for context
    me_context = ""
    me_path = CONTEXT / "me.md"
    if me_path.exists():
        me_context = me_path.read_text().strip()[:600]

    pitch_context = ""
    pitch_path = CONTEXT / "pitch.md"
    if pitch_path.exists():
        pitch_context = pitch_path.read_text().strip()[:600]

    pain_points = intel.get("pain_points", [])
    what_works = intel.get("what_works", [])
    post_angles = intel.get("post_angles", [])

    intel_summary = ""
    if pain_points:
        intel_summary += "TOP PAIN POINTS THIS WEEK:\n"
        for p in pain_points[:3]:
            intel_summary += f"- {p.get('pain', '')}: \"{p.get('quote', '')}\"\n"
    if what_works:
        intel_summary += "\nWHAT'S WORKING:\n"
        for w in what_works[:2]:
            intel_summary += f"- {w.get('insight', '')}\n"
    if post_angles:
        intel_summary += "\nSUGGESTED ANGLES:\n"
        for a in post_angles:
            intel_summary += f"- [{a.get('format','')}] Hook: {a.get('hook','')} | About: {a.get('angle','')}\n"

    prompt = f"""You are writing LinkedIn posts for Alex Doe, an AI automation builder in India.

## Who Alex is:
{me_context}

## What he sells:
{pitch_context}

## Voice guidelines:
{USER_VOICE}

## Reddit intel this week (real pain points from founders):
{intel_summary}

## Task:
Write 3 LinkedIn posts. Each post should:
1. Connect to a real pain point from this week's intel
2. Be in Alex's voice (direct, casual, specific)
3. Reference CLIP or his own experience as proof
4. End with a question or CTA

Post formats:
1. STORY: "Here's what happened when I [did X]..." — personal experience with CLIP or client work
2. PAIN→SOLUTION: Start with the pain, give the specific fix, show proof
3. CONTRARIAN: Challenge a common belief about AI/automation/ops

Return ONLY valid JSON:
[
  {{
    "format": "story",
    "hook": "first line (the scroll-stopper)",
    "body": "full post text (250 words max, use \\n for line breaks)",
    "cta": "closing question or call to action"
  }},
  {{
    "format": "pain_solution",
    "hook": "...",
    "body": "...",
    "cta": "..."
  }},
  {{
    "format": "contrarian",
    "hook": "...",
    "body": "...",
    "cta": "..."
  }}
]"""

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        from tools.credits import track_usage
        track_usage("claude-sonnet-4-6", resp.usage.input_tokens, resp.usage.output_tokens)

        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        posts = json.loads(text.strip())
        return posts if isinstance(posts, list) else []
    except Exception as e:
        print(f"[content_draft] Draft error: {e}", file=sys.stderr)
        return []


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Generate LinkedIn post drafts from Reddit intel")
    parser.add_argument("--dry-run", action="store_true", help="Print drafts, don't save")
    args = parser.parse_args()

    print(f"[content_draft] Running — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    intel_path = DATA / "content_intel.json"
    if not intel_path.exists():
        print("[content_draft] No content_intel.json found — run reddit_intel.py first")
        sys.exit(1)

    try:
        intel = json.loads(intel_path.read_text())
    except Exception as e:
        print(f"[content_draft] Failed to read intel: {e}", file=sys.stderr)
        sys.exit(1)

    week = intel.get("week", "?")
    print(f"[content_draft] Intel from week of {week} — drafting posts...")

    posts = draft_posts(intel)
    if not posts:
        print("[content_draft] No posts generated.")
        sys.exit(1)

    output = {
        "week": week,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "posts": posts,
    }

    if args.dry_run:
        print("\n--- CONTENT DRAFTS (dry run) ---")
        for i, p in enumerate(posts, 1):
            print(f"\n{'='*50}")
            print(f"POST {i} [{p.get('format','?').upper()}]")
            print(f"HOOK: {p.get('hook','')}")
            print(f"\n{p.get('body','')}")
            print(f"\nCTA: {p.get('cta','')}")
        return

    DATA.mkdir(exist_ok=True)
    (DATA / "content_drafts.json").write_text(json.dumps(output, indent=2))
    print(f"[content_draft] {len(posts)} posts saved to data/content_drafts.json")

    # Push Telegram notification
    try:
        from tools.notify import send_telegram
        hooks = "\n".join(f"• {p.get('hook','')[:80]}" for p in posts)
        send_telegram(
            f"✍️ *3 LinkedIn drafts ready*\n\n{hooks}\n\n_Type /drafts to review_"
        )
        print("[content_draft] Telegram notification sent")
    except Exception as e:
        print(f"[content_draft] Telegram push failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
