#!/usr/bin/env python3
"""
research_url.py — Fetch and summarize any URL (YouTube, articles, webpages).

Usage:
  python3 tools/research_url.py --url "https://..." [--context "why"]

Output:
  Prints a clean brief to stdout (title, key points, verdict, next actions)
  Auto-saves to acmestudio Drive: CLIP Research/YouTube/ or Articles/
  Auto-appends row to CLIP OS Google Sheet > Research Notes tab
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dotenv import load_dotenv
load_dotenv(BASE / ".env")


# ── YouTube ────────────────────────────────────────────────────────────────────

def extract_video_id(url: str) -> str | None:
    patterns = [
        r"(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})",
        r"shorts/([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def fetch_youtube_transcript(url: str) -> tuple[str, str]:
    """Returns (title, transcript_text). title may be empty if unavailable."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
    except ImportError:
        return "", "(youtube-transcript-api not installed)"

    video_id = extract_video_id(url)
    if not video_id:
        return "", "(could not extract video ID from URL)"

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        # prefer manual, fall back to auto
        try:
            transcript = transcript_list.find_manually_created_transcript(["en"])
        except Exception:
            transcript = transcript_list.find_generated_transcript(["en"])

        entries = transcript.fetch()
        text = " ".join(e["text"] for e in entries)
        # Truncate to ~8000 chars
        if len(text) > 8000:
            text = text[:8000] + "... [truncated]"
        return f"YouTube video {video_id}", text
    except (NoTranscriptFound, TranscriptsDisabled):
        return f"YouTube video {video_id}", "(no English transcript available for this video)"
    except Exception as e:
        return f"YouTube video {video_id}", f"(transcript fetch failed: {e})"


# ── Webpage ────────────────────────────────────────────────────────────────────

def fetch_webpage(url: str) -> tuple[str, str]:
    """Returns (title, main_text)."""
    try:
        import requests
        from bs4 import BeautifulSoup

        headers = {"User-Agent": "Mozilla/5.0 (compatible; CLIPBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Get title
        title = ""
        if soup.title:
            title = soup.title.string or ""
        title = title.strip()

        # Remove boilerplate
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        # Extract main content
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if main:
            text = main.get_text(separator=" ", strip=True)
        else:
            text = soup.get_text(separator=" ", strip=True)

        # Collapse whitespace and truncate
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 6000:
            text = text[:6000] + "... [truncated]"

        return title, text
    except Exception as e:
        return "", f"(webpage fetch failed: {e})"


# ── Summarize ──────────────────────────────────────────────────────────────────

def summarize(url: str, title: str, content: str, source_type: str, context: str = "") -> dict:
    """Call Claude Haiku to summarize. Returns dict with title, points, verdict, suggestions."""
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"title": title, "points": ["(ANTHROPIC_API_KEY not set)"], "verdict": "", "suggestions": []}

    context_line = f"\nAlex's context for sharing this: {context}" if context else ""
    prompt = f"""You are CLIP, Alex's executive assistant. He just shared a {source_type} link.
URL: {url}
Title: {title}{context_line}

Content:
{content}

Write a sharp research brief:
1. **Title** — clean title (use the actual content title, not the URL)
2. **Key Points** — 3-7 bullet points, each one actionable or insight-worthy. Be specific.
3. **Verdict** — 1 sentence: what's the bottom line / why does this matter for Alex?
4. **Next** — exactly 2 concrete next actions Alex could take (e.g. "Draft a LinkedIn post about X", "Email this insight to [type of contact]", "Add X to your pitch notes")

Format as JSON:
{{
  "title": "...",
  "points": ["...", "..."],
  "verdict": "...",
  "suggestions": ["action 1", "action 2"]
}}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            from tools.credits import track_usage
        except ImportError:
            from credits import track_usage
        track_usage("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens)

        raw = resp.content[0].text.strip()
        # Extract JSON even if wrapped in markdown
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            return json.loads(json_match.group())
        return {"title": title, "points": [raw], "verdict": "", "suggestions": []}
    except Exception as e:
        return {"title": title, "points": [f"(summarization failed: {e})"], "verdict": "", "suggestions": []}


# ── Drive save ─────────────────────────────────────────────────────────────────

def save_to_drive(summary: dict, url: str, source_type: str) -> str | None:
    """Save summary as a markdown doc to CLIP Research/ in Drive. Returns file link or None."""
    try:
        import base64
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaInMemoryUpload

        token_b64 = os.environ.get("GWORKSPACE_TOKEN") or os.environ.get("GOOGLE_TOKEN_B64")
        local_token = Path.home() / ".google-mcp" / "tokens" / "acmestudio.json"

        if token_b64:
            import json as _json
            creds = Credentials.from_authorized_user_info(_json.loads(base64.b64decode(token_b64).decode()))
        elif local_token.exists():
            creds = Credentials.from_authorized_user_file(str(local_token))
        else:
            return None

        service = build("drive", "v3", credentials=creds)

        def get_or_create_folder(name: str, parent_id: str | None = None) -> str:
            q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            if parent_id:
                q += f" and '{parent_id}' in parents"
            results = service.files().list(q=q, fields="files(id)").execute()
            files = results.get("files", [])
            if files:
                return files[0]["id"]
            meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
            if parent_id:
                meta["parents"] = [parent_id]
            folder = service.files().create(body=meta, fields="id").execute()
            return folder["id"]

        research_id = get_or_create_folder("CLIP Research")
        subfolder = "YouTube" if source_type == "youtube" else "Articles"
        subfolder_id = get_or_create_folder(subfolder, research_id)

        # Build markdown content
        today = datetime.now().strftime("%b %d, %Y")
        points_md = "\n".join(f"- {p}" for p in summary.get("points", []))
        suggestions_md = "\n".join(f"- {s}" for s in summary.get("suggestions", []))
        content_md = f"""# {summary.get('title', 'Research')}
*Saved {today} — {source_type.title()}*
*Source: {url}*

## Key Points
{points_md}

## Verdict
{summary.get('verdict', '')}

## Next Actions
{suggestions_md}
"""

        safe_title = re.sub(r"[^\w\s-]", "", summary.get("title", "research"))[:60].strip()
        filename = f"{safe_title} - {datetime.now().strftime('%b %d %Y')}.md"

        media = MediaInMemoryUpload(content_md.encode(), mimetype="text/plain")
        meta = {"name": filename, "parents": [subfolder_id]}
        file = service.files().create(body=meta, media_body=media, fields="id,webViewLink").execute()
        return file.get("webViewLink")
    except Exception as e:
        print(f"[research_url] Drive save failed: {e}", file=sys.stderr)
        return None


# ── Sheet log ──────────────────────────────────────────────────────────────────

def log_to_sheet(summary: dict, url: str, source_type: str):
    """Append a row to CLIP OS > Research Notes tab."""
    try:
        data = {
            "Title": summary.get("title", ""),
            "URL": url,
            "Key Points": " | ".join(summary.get("points", [])),
            "Source Type": source_type,
        }
        import subprocess
        subprocess.run(
            [sys.executable, str(BASE / "tools" / "sheets_log.py"),
             "--tab", "Research Notes",
             "--data", json.dumps(data)],
            cwd=str(BASE), timeout=30,
        )
    except Exception as e:
        print(f"[research_url] Sheet log failed: {e}", file=sys.stderr)


# ── Format output ──────────────────────────────────────────────────────────────

def format_output(summary: dict, drive_link: str | None) -> str:
    title = summary.get("title", "Research")
    points = summary.get("points", [])
    verdict = summary.get("verdict", "")
    suggestions = summary.get("suggestions", [])

    lines = [f"**{title}**\n"]
    for p in points:
        lines.append(f"• {p}")
    if verdict:
        lines.append(f"\n_{verdict}_")
    if drive_link:
        lines.append(f"\n[Saved to Drive]({drive_link})")
    if suggestions:
        lines.append(f"\n**Next:** {suggestions[0]} · {suggestions[1] if len(suggestions) > 1 else ''}")

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--context", default="")
    parser.add_argument("--no-sheet", action="store_true", help="Skip sheet logging")
    args = parser.parse_args()

    url = args.url.strip()
    is_youtube = bool(extract_video_id(url)) or "youtube.com" in url or "youtu.be" in url

    if is_youtube:
        source_type = "youtube"
        title, content = fetch_youtube_transcript(url)
    else:
        source_type = "article"
        title, content = fetch_webpage(url)

    summary = summarize(url, title, content, source_type, args.context)
    drive_link = save_to_drive(summary, url, source_type)

    if not args.no_sheet:
        log_to_sheet(summary, url, source_type)

    print(format_output(summary, drive_link))


if __name__ == "__main__":
    main()
