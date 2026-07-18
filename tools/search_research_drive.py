#!/usr/bin/env python3
"""
search_research_drive.py — Search CLIP Research/ folder in acmestudio Drive.

Finds past research docs by topic and returns their content.

Usage:
  python3 tools/search_research_drive.py --query "AI in sales"
  python3 tools/search_research_drive.py --query "automation" --limit 3
"""

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dotenv import load_dotenv
load_dotenv(BASE / ".env")

RESEARCH_FOLDER = "CLIP Research"


def _get_credentials():
    from google.oauth2.credentials import Credentials
    token_b64 = os.environ.get("GWORKSPACE_TOKEN") or os.environ.get("GOOGLE_TOKEN_B64")
    local_token = Path.home() / ".google-mcp" / "tokens" / "acmestudio.json"
    if token_b64:
        return Credentials.from_authorized_user_info(json.loads(base64.b64decode(token_b64).decode()))
    if local_token.exists():
        return Credentials.from_authorized_user_file(str(local_token))
    raise RuntimeError("No acmestudio token found.")


def search_research(query: str, limit: int = 3) -> list[dict]:
    """
    Search CLIP Research/ folder by query. Returns list of matching docs with content.
    Each result: {title, date, url_in_doc, key_points, link, snippet}
    """
    try:
        from googleapiclient.discovery import build
        creds = _get_credentials()
        service = build("drive", "v3", credentials=creds)

        # Find CLIP Research folder
        q = f"name='{RESEARCH_FOLDER}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = service.files().list(q=q, fields="files(id)").execute()
        folders = results.get("files", [])
        if not folders:
            return [{"title": "No research found", "snippet": "CLIP Research folder doesn't exist yet. Paste a URL in Telegram to start saving research."}]

        folder_id = folders[0]["id"]

        # Search for files in CLIP Research (including subfolders)
        q = f"'{folder_id}' in parents and trashed=false"
        subfolder_results = service.files().list(q=q, fields="files(id,name,mimeType)").execute()

        all_file_ids = []
        for item in subfolder_results.get("files", []):
            if item["mimeType"] == "application/vnd.google-apps.folder":
                # Search inside subfolder too
                sq = f"'{item['id']}' in parents and trashed=false"
                sub_files = service.files().list(sq=sq, fields="files(id,name,webViewLink,modifiedTime)").execute()
                all_file_ids.extend(sub_files.get("files", []))
            else:
                all_file_ids.append(item)

        if not all_file_ids:
            return [{"title": "No research saved yet", "snippet": "Paste a URL in Telegram to start saving research to Drive."}]

        # Score files by query match against filename
        query_terms = query.lower().split()

        def score_file(f):
            name = f.get("name", "").lower()
            return sum(1 for term in query_terms if term in name)

        scored = sorted(all_file_ids, key=score_file, reverse=True)
        top = scored[:limit]

        results_out = []
        for f in top:
            file_id = f["id"]
            name = f.get("name", "Unknown")
            link = f.get("webViewLink", "")

            # Download content
            content = ""
            try:
                raw = service.files().get_media(fileId=file_id).execute()
                content = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            except Exception:
                pass

            # Parse key points from markdown content
            key_points = []
            url_in_doc = ""
            if content:
                # Extract source URL
                url_match = re.search(r"\*Source: (https?://\S+)\*", content)
                if url_match:
                    url_in_doc = url_match.group(1)
                # Extract key points
                in_points = False
                for line in content.splitlines():
                    if "## Key Points" in line:
                        in_points = True
                        continue
                    if in_points and line.startswith("##"):
                        break
                    if in_points and line.startswith("- "):
                        key_points.append(line[2:].strip())

            # Snippet = first 300 chars of content
            snippet = content[:300].strip() if content else "(no content)"

            results_out.append({
                "title": name.replace(".md", ""),
                "link": link,
                "url": url_in_doc,
                "key_points": key_points,
                "snippet": snippet,
            })

        return results_out

    except Exception as e:
        return [{"title": "Search failed", "snippet": f"Drive search error: {e}"}]


def format_results(results: list[dict]) -> str:
    if not results:
        return "No research found matching that query."

    lines = [f"**Research: found {len(results)} result(s)**\n"]
    for r in results:
        lines.append(f"**{r['title']}**")
        if r.get("url"):
            lines.append(f"Source: {r['url']}")
        if r.get("key_points"):
            for kp in r["key_points"][:3]:
                lines.append(f"• {kp}")
        if r.get("link"):
            lines.append(f"[Open doc]({r['link']})")
        lines.append("")

    return "\n".join(lines).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    results = search_research(args.query, args.limit)
    print(format_results(results))


if __name__ == "__main__":
    main()
