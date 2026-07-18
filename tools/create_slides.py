#!/usr/bin/env python3
"""
create_slides.py — Generate a Google Slides presentation from a topic or outline.

Primarily for client proposals and pitch decks.

Usage:
  python3 tools/create_slides.py --title "Acme Studio Automation Proposal" --outline "..."
  python3 tools/create_slides.py --title "..." --outline "..." --type proposal

Returns:
  Shareable Drive link to the created presentation (printed to stdout)
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dotenv import load_dotenv
load_dotenv(BASE / ".env")

DECK_PROMPTS = {
    "proposal": """You are creating a client proposal deck for Acme Studio, an AI automation agency.
The deck should be professional and persuasive. Structure it as:
1. Title slide
2. The Problem (client's current pain)
3. Our Solution (what we're proposing)
4. How It Works (3-4 key steps or components)
5. What You Get (deliverables + outcomes)
6. Why Acme Studio (brief credibility)
7. Investment & Timeline
8. Next Steps

For each slide, provide:
- title: slide title (short, punchy)
- bullets: 3-5 bullet points (concise, value-focused)""",

    "pitch": """You are creating a sales pitch deck for Acme Studio.
Structure it as:
1. Hook / Opening
2. The Problem
3. The Opportunity
4. Our Approach
5. Proof / Results
6. Call to Action

For each slide:
- title: slide title
- bullets: 3-5 bullet points""",

    "summary": """You are creating a research summary presentation.
Structure it to clearly communicate findings and recommended actions.
5-7 slides covering: Overview, Key Findings (2-3 slides), Implications, Recommendations, Next Steps.

For each slide:
- title: slide title
- bullets: 3-5 bullet points""",
}


def generate_slide_content(title: str, outline: str, deck_type: str = "proposal") -> list[dict]:
    """Use Claude to generate structured slide content. Returns list of {title, bullets}."""
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return [{"title": title, "bullets": ["(ANTHROPIC_API_KEY not set)"]}]

    system = DECK_PROMPTS.get(deck_type, DECK_PROMPTS["proposal"])
    prompt = f"""Deck title: {title}

Outline / context:
{outline}

Generate the slide content as a JSON array:
[
  {{"title": "Slide Title", "bullets": ["bullet 1", "bullet 2", "bullet 3"]}},
  ...
]

Be specific, professional, and value-focused. Use the outline to customize content."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            from tools.credits import track_usage
        except ImportError:
            from credits import track_usage
        track_usage("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens)

        import re
        raw = resp.content[0].text.strip()
        json_match = re.search(r"\[[\s\S]*\]", raw)
        if json_match:
            return json.loads(json_match.group())
        return [{"title": title, "bullets": [raw]}]
    except Exception as e:
        return [{"title": title, "bullets": [f"(generation failed: {e})"]}]


def create_presentation(title: str, slides: list[dict]) -> str | None:
    """Create Google Slides presentation. Returns shareable link or None."""
    try:
        token_b64 = os.environ.get("GWORKSPACE_TOKEN") or os.environ.get("GOOGLE_TOKEN_B64")
        local_token = Path.home() / ".google-mcp" / "tokens" / "acmestudio.json"

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if token_b64:
            creds = Credentials.from_authorized_user_info(json.loads(base64.b64decode(token_b64).decode()))
        elif local_token.exists():
            creds = Credentials.from_authorized_user_file(str(local_token))
        else:
            print("[create_slides] No acmestudio token found", file=sys.stderr)
            return None

        slides_service = build("slides", "v1", credentials=creds)
        drive_service = build("drive", "v3", credentials=creds)

        # Create blank presentation
        presentation = slides_service.presentations().create(
            body={"title": title}
        ).execute()
        presentation_id = presentation["presentationId"]

        # Get existing slide ID (first blank slide)
        existing_slide_id = presentation["slides"][0]["objectId"]

        requests = []

        # Delete the default blank slide after we add content
        # Add slides and their content
        slide_ids = []
        for i, slide in enumerate(slides):
            slide_id = f"slide_{i}"
            title_id = f"title_{i}"
            body_id = f"body_{i}"
            slide_ids.append(slide_id)

            requests.append({
                "createSlide": {
                    "objectId": slide_id,
                    "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
                    "placeholderIdMappings": [
                        {"layoutPlaceholder": {"type": "TITLE", "index": 0}, "objectId": title_id},
                        {"layoutPlaceholder": {"type": "BODY", "index": 0}, "objectId": body_id},
                    ],
                }
            })
            requests.append({
                "insertText": {
                    "objectId": title_id,
                    "text": slide.get("title", f"Slide {i+1}"),
                }
            })
            bullets_text = "\n".join(f"• {b}" for b in slide.get("bullets", []))
            requests.append({
                "insertText": {
                    "objectId": body_id,
                    "text": bullets_text,
                }
            })

        # Delete the initial blank slide
        requests.append({"deleteObject": {"objectId": existing_slide_id}})

        slides_service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": requests},
        ).execute()

        # Get shareable link
        drive_service.permissions().create(
            fileId=presentation_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        file = drive_service.files().get(fileId=presentation_id, fields="webViewLink").execute()
        link = file.get("webViewLink", f"https://docs.google.com/presentation/d/{presentation_id}")
        return link

    except Exception as e:
        print(f"[create_slides] Failed: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--outline", required=True)
    parser.add_argument("--type", default="proposal", choices=["proposal", "pitch", "summary"])
    args = parser.parse_args()

    print(f"[create_slides] Generating {args.type} deck: {args.title}")
    slides = generate_slide_content(args.title, args.outline, args.type)
    print(f"[create_slides] {len(slides)} slides generated, creating presentation...")

    link = create_presentation(args.title, slides)
    if link:
        print(f"**{args.title}**\n\n{len(slides)}-slide {args.type} deck created.\n\n[Open in Google Slides]({link})")
    else:
        print("[create_slides] Failed to create presentation — check Drive credentials")
        sys.exit(1)


if __name__ == "__main__":
    main()
