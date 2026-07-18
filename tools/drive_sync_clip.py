"""
drive_sync_clip.py — Google Drive sync for CLIP data files
-----------------------------------------------------------
Pushes/pulls data/*.json and data/*.md files to acmestudio
Google Drive under the CLIP/ folder.

Usage:
  python3 tools/drive_sync_clip.py push          # push all data/ files
  python3 tools/drive_sync_clip.py pull           # pull all files (restore)
  python3 tools/drive_sync_clip.py push tasks.md  # push single file
  python3 tools/drive_sync_clip.py pull tasks.md  # pull single file

Can also be imported:
  from tools.drive_sync_clip import push_file, pull_file, push_all
"""

import os, sys, json, base64
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

BASE       = Path(__file__).parent.parent
DATA_DIR   = BASE / "data"
FOLDER_NAME = "CLIP"
LOCAL_TOKEN = Path.home() / ".google-mcp" / "tokens" / "acmestudio.json"

load_dotenv(BASE / ".env")

# Files to sync (relative to data/)
SYNC_FILES = [
    "tasks.md", "pipeline.json", "contacts.json",
    "leads.json", "opportunities.json", "opportunities.md",
    "ai-updates.md", "market-intel.md", "schedule.md",
    "skill-registry.json", "subscriptions.json",
    "task-log.json", "credits.json", "memory.jsonl",
    "outreach_drafts.json", "heartbeat.json",
]


def _get_credentials() -> Credentials:
    token_b64 = os.getenv("GWORKSPACE_TOKEN")
    if token_b64:
        token_data = json.loads(base64.b64decode(token_b64).decode())
        return Credentials.from_authorized_user_info(token_data)
    if LOCAL_TOKEN.exists():
        return Credentials.from_authorized_user_file(str(LOCAL_TOKEN))
    raise RuntimeError("No acmestudio token found.")


def _get_service():
    return build("drive", "v3", credentials=_get_credentials())


def _get_or_create_folder(service, name: str) -> str:
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=q, fields="files(id)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def _find_file(service, folder_id: str, filename: str) -> Optional[str]:
    q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=q, fields="files(id)").execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None


def push_file(filename: str) -> bool:
    """Push data/{filename} to Drive CLIP/ folder."""
    path = DATA_DIR / filename
    if not path.exists():
        print(f"  skip {filename} (not found locally)")
        return False
    try:
        service   = _get_service()
        folder_id = _get_or_create_folder(service, FOLDER_NAME)
        content   = path.read_bytes()
        mime      = "text/plain" if filename.endswith((".md", ".jsonl")) else "application/json"
        media     = MediaInMemoryUpload(content, mimetype=mime)
        file_id   = _find_file(service, folder_id, filename)
        if file_id:
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            meta = {"name": filename, "parents": [folder_id]}
            service.files().create(body=meta, media_body=media, fields="id").execute()
        return True
    except Exception as e:
        print(f"  ✗ push {filename}: {e}")
        return False


def pull_file(filename: str) -> bool:
    """Pull data/{filename} from Drive CLIP/ folder."""
    try:
        service   = _get_service()
        folder_id = _get_or_create_folder(service, FOLDER_NAME)
        file_id   = _find_file(service, folder_id, filename)
        if not file_id:
            print(f"  skip {filename} (not in Drive)")
            return False
        content = service.files().get_media(fileId=file_id).execute()
        path = DATA_DIR / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        return True
    except Exception as e:
        print(f"  ✗ pull {filename}: {e}")
        return False


def push_all():
    print(f"Pushing {len(SYNC_FILES)} CLIP files to Drive...")
    ok = sum(1 for f in SYNC_FILES if push_file(f))
    print(f"Done — {ok}/{len(SYNC_FILES)} pushed")


def pull_all():
    print(f"Pulling CLIP files from Drive...")
    ok = sum(1 for f in SYNC_FILES if pull_file(f))
    print(f"Done — {ok} pulled")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: python3 tools/drive_sync_clip.py push|pull [filename]")
        sys.exit(1)
    cmd = args[0]
    filename = args[1] if len(args) > 1 else None
    if cmd == "push":
        if filename:
            push_file(filename)
        else:
            push_all()
    elif cmd == "pull":
        if filename:
            pull_file(filename)
        else:
            pull_all()
    else:
        print(f"Unknown command: {cmd}")
