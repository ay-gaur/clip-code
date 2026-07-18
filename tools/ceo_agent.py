#!/usr/bin/env python3
"""
ceo_agent.py — CLIP CEO Agent bridge for Telegram.

Receives a free-form message (text, voice transcript, or file content) and runs
a full Claude Sonnet tool_use loop with complete CLIP context. All write actions
create pending items in data/pending-actions.json — confirmed via /ok in Telegram.
Read actions (list tasks, pipeline, etc.) execute immediately.

Usage:
  python3 tools/ceo_agent.py --message "your message" --chat-id 123456789
  python3 tools/ceo_agent.py --message "see this doc" --chat-id 123456789 --file /tmp/doc.pdf

Outputs final response text to stdout. Bot sends it back to Telegram.
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
DATA = BASE / "data"
CONTEXT = BASE / "context"
SKILLS = BASE / ".claude" / "skills"
PYTHON = sys.executable

from tools.credits import track_usage

SESSION_TTL_HOURS = 8
SESSION_MAX_TURNS = 10  # each turn = 1 user + 1 assistant message

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"

# Tools that execute immediately (read-only, no confirmation needed)
READ_TOOLS = {"list_tasks", "list_pipeline", "morning_brief", "search_memory", "read_contacts", "project_status",
              "research_url", "append_to_sheet", "create_slides", "search_research_drive"}

# Tool definitions exposed to Claude
TOOLS = [
    {
        "name": "list_tasks",
        "description": "List Alex's current tasks by priority (urgent, this week, backlog).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_pipeline",
        "description": "Show the full sales pipeline — all contacts and their deal stages.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "morning_brief",
        "description": "Generate a morning brief with tasks, pipeline status, and schedule.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_memory",
        "description": "Search CLIP's memory for past learnings and context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look up in memory"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_contacts",
        "description": "Read contact history. Optionally filter by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Contact name to look up (optional)"},
            },
            "required": [],
        },
    },
    {
        "name": "search_web",
        "description": "Search the web for information using Tavily.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "add_task",
        "description": "Queue adding a new task to Alex's task list (requires /ok confirmation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Task description"},
                "priority": {
                    "type": "string",
                    "enum": ["urgent", "this_week", "backlog"],
                    "description": "Task priority level",
                },
            },
            "required": ["task", "priority"],
        },
    },
    {
        "name": "log_meeting_notes",
        "description": "Queue logging meeting notes and action items for a contact (requires /ok confirmation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "Contact's full name"},
                "company": {"type": "string", "description": "Contact's company (optional)"},
                "summary": {"type": "string", "description": "Summary of what was discussed"},
                "actions": {"type": "string", "description": "Comma-separated action items (optional)"},
                "notes": {"type": "string", "description": "Additional notes (optional)"},
            },
            "required": ["contact", "summary"],
        },
    },
    {
        "name": "move_pipeline_stage",
        "description": "Queue moving a pipeline contact to a different stage (requires /ok confirmation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "Contact name or company"},
                "stage": {
                    "type": "string",
                    "enum": ["prospect", "contacted", "qualified", "proposal", "negotiation", "client", "closed_lost"],
                },
            },
            "required": ["contact", "stage"],
        },
    },
    {
        "name": "add_pipeline_contact",
        "description": "Queue adding a new contact to the sales pipeline (requires /ok confirmation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "company": {"type": "string"},
                "stage": {
                    "type": "string",
                    "enum": ["prospect", "contacted", "qualified", "proposal", "negotiation", "client"],
                },
                "notes": {"type": "string", "description": "Optional notes"},
            },
            "required": ["name", "company", "stage"],
        },
    },
    {
        "name": "draft_email",
        "description": "Queue creating a Gmail draft (requires /ok confirmation). Draft will appear in Gmail — Alex reviews before sending.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "Plain text email body"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "create_calendar_event",
        "description": "Queue creating a Google Calendar event (requires /ok confirmation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                "time": {"type": "string", "description": "Start time in HH:MM format (IST)"},
                "duration": {"type": "integer", "description": "Duration in minutes"},
                "description": {"type": "string", "description": "Event description (optional)"},
            },
            "required": ["title", "date", "time", "duration"],
        },
    },
    {
        "name": "write_memory",
        "description": "Queue writing a durable insight to CLIP's long-term memory (requires /ok confirmation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The insight or fact to remember"},
                "type": {
                    "type": "string",
                    "enum": ["insight", "preference", "context", "client"],
                },
                "tags": {"type": "string", "description": "Comma-separated tags"},
            },
            "required": ["content", "type"],
        },
    },
    {
        "name": "project_status",
        "description": "Get the current status of a client project — phase, open milestones, recent decisions. Use when Alex asks about a client project or active build.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project slug (e.g. 'my-client'). Required."},
            },
            "required": [],
        },
    },
    {
        "name": "log_project_decision",
        "description": "Queue logging a decision made in a client project — architecture choice, agreed scope, etc. (requires /ok confirmation). Use when Alex says 'we decided', 'client confirmed', 'we agreed', 'going with', 'locked in'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project slug (e.g. 'my-client')"},
                "decision": {"type": "string", "description": "What was decided"},
                "context": {"type": "string", "description": "Why — who confirmed, what context led to this decision"},
            },
            "required": ["project", "decision", "context"],
        },
    },
    {
        "name": "research_url",
        "description": "Fetch and summarize a URL — YouTube video, article, webpage, LinkedIn post. Auto-saves to Drive (CLIP Research/) and logs to Research Notes sheet. After calling this, always suggest 2 concrete next actions based on the content (draft a post, email a contact, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to research"},
                "context": {"type": "string", "description": "Optional: why Alex is sharing this (e.g. 'for client pitch', 'content idea')"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "append_to_sheet",
        "description": "Append a row to the CLIP OS Google Sheet. Use for logging leads, content ideas, outreach records, or research. Auto-chains after research_url for Research Notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tab": {
                    "type": "string",
                    "enum": ["Leads", "Content Ideas", "Outreach Log", "Research Notes"],
                    "description": "Which tab to append to",
                },
                "data": {
                    "type": "object",
                    "description": "Key-value pairs matching the tab's columns. Date is added automatically.",
                },
            },
            "required": ["tab", "data"],
        },
    },
    {
        "name": "create_slides",
        "description": "Generate a Google Slides presentation — client proposal, pitch deck, or research summary. Returns the shareable Drive link immediately (no /ok needed). Use for proposal decks, pitch decks, or summarizing research into slides.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Presentation title"},
                "outline": {"type": "string", "description": "Topic, outline, or context for the deck content"},
                "deck_type": {
                    "type": "string",
                    "enum": ["proposal", "pitch", "summary"],
                    "description": "Type of deck (default: proposal)",
                },
            },
            "required": ["title", "outline"],
        },
    },
    {
        "name": "search_research_drive",
        "description": "Search past research saved in CLIP Research/ folder on Drive. Use when Alex asks about something he researched before, references a past URL, or asks 'what did I read about X'. Falls back to this when search_memory returns nothing relevant.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic or keywords to search for"},
                "limit": {"type": "integer", "description": "Max results to return (default: 3)"},
            },
            "required": ["query"],
        },
    },
]


# ── Env ─────────────────────────────────────────────────────────────────────


def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


# ── System prompt ────────────────────────────────────────────────────────────


def build_system_prompt() -> str:
    parts = []

    # CEO skill instructions (strip YAML frontmatter)
    ceo_skill = SKILLS / "ceo" / "SKILL.md"
    if ceo_skill.exists():
        text = ceo_skill.read_text()
        if text.startswith("---"):
            end = text.find("---", 3)
            text = text[end + 3:].strip() if end > 0 else text
        parts.append(f"# CLIP CEO Instructions\n{text}")

    # Context files
    for fname in ("me.md", "work.md", "priorities.md", "team.md"):
        path = CONTEXT / fname
        if path.exists():
            parts.append(f"# {fname}\n{path.read_text().strip()}")

    # Learned routing patterns (SONA-lite — written weekly by ceo_pattern_summary.py)
    patterns = DATA / "ceo-patterns.md"
    if patterns.exists():
        parts.append(f"# Routing Patterns (learned from usage)\n{patterns.read_text().strip()}")

    # Current date + time
    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    parts.append(f"# Current Date & Time\n{now_ist.strftime('%A, %B %d, %Y — %I:%M %p IST')}")

    # Telegram-specific instructions
    parts.append(
        "# Telegram Input Layer Rules\n"
        "You are receiving messages via Telegram. Alex may send text, voice transcripts, "
        "documents, or links. Identify intent and act:\n"
        "- Read requests → execute tool immediately and return the result\n"
        "- Write/action requests → use the appropriate tool (creates a pending /ok confirmation)\n"
        "- Unstructured input (notes, thoughts, links) → identify what it is and act on it\n"
        "- Keep responses concise — this is a mobile chat interface\n"
        "- After creating a pending action, summarize it in one line and tell Alex to type /ok to confirm or /skip to cancel\n"
        "- Multiple pending actions in one message: list them all, one per bullet\n"
        "- For every write/action tool call, include a 'confidence' field (0.0–1.0) in the tool input "
        "indicating how certain you are the action is correct and wanted. "
        "0.9+ = routine/clear request, 0.7–0.89 = likely correct, <0.7 = uncertain/ambiguous.\n\n"
        "# Research & Workspace Tools\n"
        "When you call research_url:\n"
        "- Always immediately also call append_to_sheet(tab='Research Notes', data={...}) to log it — no confirmation needed\n"
        "- Scan the summary for: pipeline contacts mentioned, pain points matching leads, content angles\n"
        "- End EVERY research response with exactly 2 concrete next actions:\n"
        "  **Next:** [action 1] · [action 2]\n"
        "  Examples: 'Draft a LinkedIn post about this' · 'Email this insight to FCM Travel'\n\n"
        "When you find a signal in research (e.g. pain point matching a pipeline contact):\n"
        "- Surface it clearly: 'This matches what [contact] is dealing with'\n"
        "- Offer to act: 'Want me to draft a hook email?' → queue as pending action only if confirmed\n\n"
        "create_slides returns the link directly — no /ok needed.\n"
        "If search_memory returns no useful results, call search_research_drive as a fallback."
    )

    return "\n\n---\n\n".join(parts)


# ── Session memory ────────────────────────────────────────────────────────────


def session_path(chat_id: str) -> Path:
    sessions_dir = BASE / "data" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir / f"{chat_id}.json"


def load_session(chat_id: str) -> list:
    path = session_path(chat_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        last = data.get("last_active", "")
        if last:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - last_dt > timedelta(hours=SESSION_TTL_HOURS):
                return []
        # Return last N turns (each turn = user + assistant pair = 2 messages)
        msgs = data.get("messages", [])
        return msgs[-(SESSION_MAX_TURNS * 2):]
    except Exception:
        return []


def save_session(chat_id: str, messages: list):
    path = session_path(chat_id)
    path.write_text(json.dumps({
        "last_active": datetime.now(timezone.utc).isoformat(),
        "messages": messages[-(SESSION_MAX_TURNS * 2):],
    }))


# ── Tool execution ────────────────────────────────────────────────────────────


def run_tool(args: list, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            [PYTHON] + args,
            cwd=str(BASE),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        if result.returncode != 0 and err:
            return f"Error: {err[:300]}"
        return out[:3000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Timed out."
    except Exception as e:
        return f"Error: {e}"


def create_pending(action: str, params: dict, reason: str, confidence: float = 0.75) -> tuple[str, str]:
    """Write a pending action. Returns (action_id, human-readable description)."""
    path = DATA / "pending-actions.json"
    try:
        existing = json.loads(path.read_text()) if path.exists() else []
    except Exception:
        existing = []

    action_id = str(uuid.uuid4())[:8]
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

    existing.append({
        "id": action_id,
        "action": action,
        "params": params,
        "reason": reason,
        "confidence": round(confidence, 2),
        "status": "pending",
        "expires_at": expires_at,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    DATA.mkdir(exist_ok=True)
    path.write_text(json.dumps(existing, indent=2))
    return action_id, reason


def execute_tool(name: str, inputs: dict) -> str:
    # ── Read tools (execute immediately) ──────────────────────────────────────

    if name == "list_tasks":
        return run_tool(["tools/write_tasks.py", "--action", "list"])

    if name == "list_pipeline":
        return run_tool(["tools/pipeline_status.py", "--action", "list"])

    if name == "morning_brief":
        return run_tool(["tools/morning_brief.py"])

    if name == "search_memory":
        memory_file = DATA / "memory.jsonl"
        if not memory_file.exists():
            return "No memory entries yet."
        try:
            query = inputs.get("query", "").lower()
            entries = [json.loads(l) for l in memory_file.read_text().splitlines() if l.strip()]
            if query:
                entries = [e for e in entries if query in e.get("content", "").lower()]
            entries = entries[-10:]
            if not entries:
                return "No matching memory entries found."
            return "\n".join(f"[{e.get('timestamp','?')[:10]}] {e.get('content','')}" for e in entries)
        except Exception as e:
            return f"Memory read error: {e}"

    if name == "read_contacts":
        path = DATA / "contacts.json"
        if not path.exists():
            return "No contacts on file."
        try:
            contacts = json.loads(path.read_text())
            name_filter = inputs.get("name", "").lower().strip()
            if name_filter:
                contacts = [c for c in contacts if name_filter in c.get("name", "").lower()]
            if not contacts:
                return "No matching contacts found."
            lines = []
            for c in contacts[:5]:
                lines.append(f"{c.get('name','?')} ({c.get('company','?')}) — {c.get('email','?')}")
                history = c.get("history", [])
                if history:
                    last = history[-1]
                    lines.append(f"  Last note ({last.get('date','?')}): {last.get('summary', last.get('notes',''))[:120]}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    if name == "search_web":
        query = inputs.get("query", "")
        try:
            from tavily import TavilyClient
            api_key = os.environ.get("TAVILY_API_KEY", "")
            if not api_key:
                return "TAVILY_API_KEY not set."
            client = TavilyClient(api_key=api_key)
            resp = client.search(query, max_results=5)
            results = resp.get("results", [])
            if not results:
                return "No results found."
            lines = []
            for r in results:
                lines.append(f"**{r.get('title','?')}** — {r.get('url','')}")
                lines.append(r.get("content", "")[:200])
                lines.append("")
            return "\n".join(lines)[:2000]
        except ImportError:
            return "tavily-python not installed."
        except Exception as e:
            return f"Web search error: {e}"

    # ── Write tools (create pending actions) ──────────────────────────────────

    if name == "add_task":
        task = inputs.get("task", "")
        priority = inputs.get("priority", "this_week")
        confidence = float(inputs.get("confidence", 0.85))
        aid, reason = create_pending("add_task", {"task": task, "priority": priority}, f"Add task: {task} [{priority}]", confidence)
        return f"PENDING:{aid}:{reason}"

    if name == "log_meeting_notes":
        contact = inputs.get("contact", "")
        company = inputs.get("company", "")
        summary = inputs.get("summary", "")
        actions = inputs.get("actions", "")
        notes = inputs.get("notes", "")
        params = {"contact": contact, "company": company, "summary": summary, "actions": actions, "notes": notes}
        confidence = float(inputs.get("confidence", 0.85))
        aid, reason = create_pending("log_meeting_notes", params, f"Log meeting notes for {contact}", confidence)
        return f"PENDING:{aid}:{reason}"

    if name == "move_pipeline_stage":
        contact = inputs.get("contact", "")
        stage = inputs.get("stage", "")
        # Try to find contact ID from pipeline
        contact_id = ""
        try:
            pipeline = json.loads((DATA / "pipeline.json").read_text())
            for p in pipeline:
                if contact.lower() in p.get("name", "").lower() or contact.lower() in p.get("company", "").lower():
                    contact_id = p.get("id", "")
                    break
        except Exception:
            pass
        params = {"name": contact, "id": contact_id, "stage": stage}
        confidence = float(inputs.get("confidence", 0.80))
        aid, reason = create_pending("move_pipeline_stage", params, f"Move {contact} → {stage}", confidence)
        return f"PENDING:{aid}:{reason}"

    if name == "add_pipeline_contact":
        params = {
            "name": inputs.get("name", ""),
            "company": inputs.get("company", ""),
            "stage": inputs.get("stage", "prospect"),
            "notes": inputs.get("notes", ""),
        }
        confidence = float(inputs.get("confidence", 0.80))
        aid, reason = create_pending("add_pipeline_contact", params, f"Add {params['name']} ({params['company']}) → pipeline at {params['stage']}", confidence)
        return f"PENDING:{aid}:{reason}"

    if name == "draft_email":
        params = {
            "to": inputs.get("to", ""),
            "subject": inputs.get("subject", ""),
            "body": inputs.get("body", ""),
        }
        confidence = float(inputs.get("confidence", 0.85))
        aid, reason = create_pending("draft_email", params, f"Create Gmail draft — '{params['subject']}' to {params['to']}", confidence)
        return f"PENDING:{aid}:{reason}"

    if name == "create_calendar_event":
        params = {
            "title": inputs.get("title", ""),
            "date": inputs.get("date", ""),
            "time": inputs.get("time", ""),
            "duration": inputs.get("duration", 60),
            "description": inputs.get("description", ""),
        }
        confidence = float(inputs.get("confidence", 0.85))
        aid, reason = create_pending("create_calendar_event", params, f"Create event — '{params['title']}' on {params['date']} at {params['time']} ({params['duration']}min)", confidence)
        return f"PENDING:{aid}:{reason}"

    if name == "write_memory":
        memory_file = DATA / "memory.jsonl"
        try:
            DATA.mkdir(exist_ok=True)
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": inputs.get("content", ""),
                "type": inputs.get("type", "insight"),
                "tags": inputs.get("tags", ""),
            }
            with memory_file.open("a") as f:
                f.write(json.dumps(entry) + "\n")
            return f"Memory saved: {entry['content'][:80]}"
        except Exception as e:
            return f"Memory write error: {e}"

    if name == "project_status":
        project = inputs.get("project", "")
        if not project:
            return "Error: project slug required"
        return run_tool(["tools/project_manager.py", "--action", "status", "--project", project])

    if name == "log_project_decision":
        project = inputs.get("project", "")
        decision = inputs.get("decision", "")
        context = inputs.get("context", "")
        params = {"project": project, "decision": decision, "context": context}
        confidence = float(inputs.get("confidence", 0.85))
        aid, reason = create_pending("log_project_decision", params, f"Log decision for {project}: {decision[:80]}", confidence)
        return f"PENDING:{aid}:{reason}"

    if name == "research_url":
        url = inputs.get("url", "")
        ctx = inputs.get("context", "")
        cmd = ["tools/research_url.py", "--url", url]
        if ctx:
            cmd += ["--context", ctx]
        return run_tool(cmd, timeout=90)

    if name == "append_to_sheet":
        tab = inputs.get("tab", "Research Notes")
        data = inputs.get("data", {})
        return run_tool(["tools/sheets_log.py", "--tab", tab, "--data", json.dumps(data)], timeout=30)

    if name == "create_slides":
        title = inputs.get("title", "Presentation")
        outline = inputs.get("outline", "")
        deck_type = inputs.get("deck_type", "proposal")
        return run_tool(["tools/create_slides.py", "--title", title, "--outline", outline, "--type", deck_type], timeout=60)

    if name == "search_research_drive":
        query = inputs.get("query", "")
        limit = inputs.get("limit", 3)
        return run_tool(["tools/search_research_drive.py", "--query", query, "--limit", str(limit)], timeout=30)

    return f"Unknown tool: {name}"


# ── File reading ──────────────────────────────────────────────────────────────


def read_file_content(file_path: str) -> str:
    path = Path(file_path)
    if not path.exists():
        return ""
    suffix = path.suffix.lower()

    if suffix in (".txt", ".md", ".csv", ".json", ".py", ".js", ".html"):
        try:
            return path.read_text(errors="replace")[:6000]
        except Exception:
            return ""

    if suffix == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            text = "\n".join(p.extract_text() or "" for p in reader.pages[:15])
            return text[:6000]
        except ImportError:
            pass
        # Fallback: raw bytes as text
        try:
            return path.read_bytes().decode("utf-8", errors="ignore")[:3000]
        except Exception:
            return f"(PDF: {path.name} — install pypdf to extract text)"

    # Any other file: try as text
    try:
        return path.read_text(errors="replace")[:3000]
    except Exception:
        return f"(Binary file: {path.name}, {path.stat().st_size} bytes)"


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    load_env()

    parser = argparse.ArgumentParser(description="CLIP CEO Agent")
    parser.add_argument("--message", default="", help="User's message text")
    parser.add_argument("--chat-id", default="default", help="Telegram chat_id for session memory")
    parser.add_argument("--file", default="", help="Optional local file path to include")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("[ceo_agent] ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    try:
        import anthropic
    except ImportError:
        print("[ceo_agent] anthropic package not installed.", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    system = build_system_prompt()
    history = load_session(args.chat_id)

    # Build user message content
    user_content: list = []

    if args.file:
        file_text = read_file_content(args.file)
        if file_text:
            fname = Path(args.file).name
            user_content.append({"type": "text", "text": f"[Attached file: {fname}]\n\n{file_text}"})

    msg_text = args.message.strip()
    if msg_text:
        user_content.append({"type": "text", "text": msg_text})
    elif not user_content:
        user_content.append({"type": "text", "text": "(empty message)"})

    messages = history + [{"role": "user", "content": user_content}]

    # Tool-use loop
    final_text = ""
    pending_descriptions: list[str] = []
    max_iterations = 15

    for _ in range(max_iterations):
        resp = client.messages.create(
            model=SONNET,
            max_tokens=1024,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        # Collect text blocks and tool calls
        text_parts = []
        tool_calls = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(block)

        messages.append({"role": "assistant", "content": resp.content})
        track_usage(SONNET, resp.usage.input_tokens, resp.usage.output_tokens)

        if resp.stop_reason == "end_turn" or not tool_calls:
            final_text = "\n".join(text_parts).strip()
            break

        # Execute tool calls and collect results
        tool_results = []
        for tc in tool_calls:
            result = execute_tool(tc.name, tc.input)
            # Collect pending action descriptions
            if result.startswith("PENDING:"):
                parts = result.split(":", 2)
                desc = parts[2] if len(parts) > 2 else result
                pending_descriptions.append(desc)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    # Save session (strip non-serializable blocks by converting to dicts)
    serializable = []
    for m in messages:
        if isinstance(m.get("content"), list):
            content = []
            for block in m["content"]:
                if hasattr(block, "model_dump"):
                    content.append(block.model_dump())
                elif isinstance(block, dict):
                    content.append(block)
                else:
                    content.append({"type": "text", "text": str(block)})
            serializable.append({"role": m["role"], "content": content})
        else:
            serializable.append(m)
    save_session(args.chat_id, serializable)

    # Log reflexion (best-effort, don't fail if log_entry errors)
    try:
        note = (msg_text or f"[file: {Path(args.file).name}]" if args.file else "(empty)")[:100]
        subprocess.run(
            [PYTHON, "tools/log_entry.py", "--skill", "ceo", "--action", "telegram-input", "--note", note],
            cwd=str(BASE), capture_output=True, timeout=10,
        )
    except Exception:
        pass

    print(final_text or "(no response)")


if __name__ == "__main__":
    main()
