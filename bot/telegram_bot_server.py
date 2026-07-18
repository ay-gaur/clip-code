#!/usr/bin/env python3
"""
telegram_bot_server.py — CLIP bidirectional Telegram bot with voice support.

Pure requests-based long-polling server. No async, no external bot library.
Processes commands and natural language (text or voice) via CLIP tools.

Commands:
  /brief     — latest heartbeat insight (data/ai-updates.md)
  /tasks     — current task list
  /done <task> — mark a task complete
  /snooze <contact> — reset last_contact to today
  /pipeline  — full pipeline view
  /ok        — approve oldest pending action
  /skip      — reject oldest pending action
  /help      — show commands

Voice:
  Send a voice message → CLIP transcribes (faster-whisper) → routes as command
  or sends to Claude → replies with text + audio (gTTS).

Run via crontab @reboot (auto-restarts on crash):
  @reboot cd /path/to/clip && while true; do python3 bot/telegram_bot_server.py; sleep 5; done &

Or manually:
  python3 bot/telegram_bot_server.py

Requires in .env:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID  (only messages from this chat_id are processed)
  ANTHROPIC_API_KEY (for voice → Claude responses)
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
sys.path.insert(0, str(BASE))

PYTHON = sys.executable
API_BASE = "https://api.telegram.org/bot{token}"

# Whisper model size: "tiny" (fast, ~75MB) or "base" (better, ~145MB)
WHISPER_MODEL = "base"


def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def send_message(token: str, chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
    try:
        resp = requests.post(
            api_url(token, "sendMessage"),
            json={"chat_id": chat_id, "text": text[:4000], "parse_mode": parse_mode},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[bot] send error: {e}", file=sys.stderr)
        return False


def send_audio_file(token: str, chat_id: str, audio_path: str, caption: str = "") -> bool:
    """Send an MP3 as a Telegram audio message (appears as voice reply)."""
    try:
        with open(audio_path, "rb") as f:
            resp = requests.post(
                api_url(token, "sendAudio"),
                data={"chat_id": chat_id, "caption": caption[:200] if caption else ""},
                files={"audio": ("clip_reply.mp3", f, "audio/mpeg")},
                timeout=30,
            )
        return resp.status_code == 200
    except Exception as e:
        print(f"[bot] send audio error: {e}", file=sys.stderr)
        return False


def get_updates(token: str, offset: int) -> list:
    try:
        resp = requests.get(
            api_url(token, "getUpdates"),
            params={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
            timeout=40,
        )
        if resp.status_code == 200:
            return resp.json().get("result", [])
    except requests.exceptions.Timeout:
        pass
    except Exception as e:
        print(f"[bot] poll error: {e}", file=sys.stderr)
        time.sleep(5)
    return []


def run_tool(args: list, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            [PYTHON] + args,
            cwd=str(BASE),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(BASE)},
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        if result.returncode != 0 and err:
            return f"Error: {err[:1500]}"
        return out[:3500] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Timed out."
    except Exception as e:
        return f"Error: {e}"


def read_ai_updates() -> str:
    path = DATA / "ai-updates.md"
    if not path.exists():
        return "No heartbeat insights yet."
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    return "\n".join(lines[:30])


def get_pending_actions() -> list:
    path = DATA / "pending-actions.json"
    if not path.exists():
        return []
    try:
        actions = json.loads(path.read_text())
        now = datetime.now(timezone.utc)
        active = []
        for a in actions:
            if a.get("status") != "pending":
                continue
            exp = a.get("expires_at")
            if exp:
                try:
                    exp_dt = datetime.fromisoformat(exp)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    if exp_dt < now:
                        continue
                except Exception:
                    pass
            active.append(a)
        return active
    except Exception:
        return []


def update_pending_action(action_id: str, status: str):
    path = DATA / "pending-actions.json"
    if not path.exists():
        print(f"[bot] WARNING: pending-actions.json missing when updating {action_id}", file=sys.stderr)
        return
    try:
        actions = json.loads(path.read_text())
        found = False
        for a in actions:
            if a.get("id") == action_id:
                a["status"] = status
                a["resolved_at"] = datetime.now(timezone.utc).isoformat()
                found = True
        if not found:
            print(f"[bot] WARNING: action {action_id} not found in pending-actions.json", file=sys.stderr)
        path.write_text(json.dumps(actions, indent=2))
    except Exception as e:
        print(f"[bot] ERROR updating pending action {action_id}: {e}", file=sys.stderr)


# ── Voice pipeline ──────────────────────────────────────────────────────────────

def download_voice(token: str, file_id: str) -> str | None:
    """Download a Telegram voice/audio file to /tmp. Returns local path."""
    try:
        resp = requests.get(api_url(token, "getFile"), params={"file_id": file_id}, timeout=10)
        file_path = resp.json()["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        audio_data = requests.get(file_url, timeout=30).content
        local_path = f"/tmp/clip_voice_{int(time.time())}.ogg"
        with open(local_path, "wb") as f:
            f.write(audio_data)
        return local_path
    except Exception as e:
        print(f"[bot] voice download error: {e}", file=sys.stderr)
        return None


def transcribe_voice(audio_path: str) -> str | None:
    """Transcribe audio using faster-whisper. Returns transcript text."""
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio_path, language="en")
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text if text else None
    except ImportError:
        print("[bot] faster-whisper not installed. Run: pip3 install faster-whisper", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[bot] transcription error: {e}", file=sys.stderr)
        return None


def ask_claude(transcript: str) -> str:
    """Send transcript to Claude Haiku for a concise spoken reply."""
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return "Anthropic API key not configured."
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=(
                "You are CLIP, Alex's AI executive assistant on Telegram. "
                "Reply like a sharp, direct colleague — casual, no fluff. "
                "Use markdown where it helps (bold, bullets). Under 150 words. "
                "For commands like tasks/pipeline/brief, tell him to use /tasks, /pipeline, /brief."
            ),
            messages=[{"role": "user", "content": transcript}],
        )
        from tools.credits import track_usage
        track_usage("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens)
        return resp.content[0].text.strip()
    except Exception as e:
        return f"Claude error: {e}"


def text_to_speech(text: str) -> str | None:
    """Convert reply text to MP3 using gTTS. Returns file path or None."""
    try:
        from gtts import gTTS
        # Strip markdown formatting for clean speech
        clean = text.replace("*", "").replace("_", "").replace("`", "").replace("#", "")
        tts = gTTS(text=clean, lang="en", slow=False)
        path = f"/tmp/clip_reply_{int(time.time())}.mp3"
        tts.save(path)
        return path
    except ImportError:
        print("[bot] gTTS not installed. Run: pip3 install gTTS", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[bot] TTS error: {e}", file=sys.stderr)
        return None


# Natural language → command mapping for voice routing
VOICE_COMMAND_MAP = {
    # Tasks
    "tasks": "/tasks",
    "my tasks": "/tasks",
    "show tasks": "/tasks",
    "what are my tasks": "/tasks",
    "what do i need to do": "/tasks",
    "to do list": "/tasks",
    "todo": "/tasks",
    # Pipeline
    "pipeline": "/pipeline",
    "show pipeline": "/pipeline",
    "my pipeline": "/pipeline",
    "sales pipeline": "/pipeline",
    # Brief
    "brief": "/brief",
    "morning brief": "/brief",
    "what's new": "/brief",
    "whats new": "/brief",
    "latest update": "/brief",
    "heartbeat": "/brief",
    "daily brief": "/brief",
    # Approvals
    "approve": "/ok",
    "ok": "/ok",
    "confirm": "/ok",
    "yes do it": "/ok",
    "looks good": "/ok",
    # Skip
    "skip": "/skip",
    "reject": "/skip",
    "no": "/skip",
    "cancel": "/skip",
    "don't do it": "/skip",
    # Undo
    "undo": "/undo",
    "undo that": "/undo",
    "revert": "/undo",
    "take it back": "/undo",
    # Drafts / Send
    "drafts": "/drafts",
    "linkedin drafts": "/drafts",
    "show drafts": "/drafts",
    "send": "/send",
    "pending emails": "/send",
    "emails to send": "/send",
    # Help
    "help": "/help",
    "what can you do": "/help",
    "commands": "/help",
}


def route_voice_transcript(transcript: str) -> str | None:
    """Try to map transcript to a slash command. Returns command or None."""
    lower = transcript.lower().strip()
    # Direct slash command spoken aloud
    if lower.startswith("/"):
        return lower.split()[0]
    # Phrase matching
    for phrase, cmd in VOICE_COMMAND_MAP.items():
        if phrase in lower:
            return cmd
    return None


def handle_voice_message(token: str, chat_id: str, message: dict) -> None:
    """Full voice pipeline: download → transcribe → route or ask Claude → TTS → reply."""
    voice = message.get("voice") or message.get("audio", {})
    file_id = voice.get("file_id")
    if not file_id:
        return

    send_message(token, chat_id, "_Listening..._")

    # Download
    audio_path = download_voice(token, file_id)
    if not audio_path:
        send_message(token, chat_id, "Couldn't download your voice message. Try again.")
        return

    # Transcribe
    transcript = transcribe_voice(audio_path)
    try:
        os.remove(audio_path)
    except Exception:
        pass

    if not transcript:
        send_message(token, chat_id, "Couldn't make out what you said. Try again or type it.")
        return

    print(f"[bot] Voice: \"{transcript}\"")
    sys.stdout.flush()

    # Route slash commands directly; everything else → CEO agent
    cmd = route_voice_transcript(transcript)
    if cmd:
        reply = dispatch(cmd)
        if not reply:
            reply = f"Unknown command: {cmd}"
    else:
        reply = call_ceo_agent(transcript, chat_id)

    # Send text reply (shows transcript + response)
    send_message(token, chat_id, f"_{transcript}_\n\n{reply}")

    # Send audio reply
    audio_reply = text_to_speech(reply)
    if audio_reply:
        send_audio_file(token, chat_id, audio_reply)
        try:
            os.remove(audio_reply)
        except Exception:
            pass


# ── Command handlers ────────────────────────────────────────────────────────────

def handle_brief(args: str) -> str:
    return read_ai_updates()


GREETINGS = {"hi", "hey", "hello", "yo", "sup", "morning", "hii", "hiii", "heya", "wassup", "what's up", "whats up"}

def handle_greeting() -> str:
    """Instant situational brief — no CEO agent needed."""
    from datetime import date
    today = date.today().strftime("%a, %b %d")
    lines = [f"*CLIP — {today}*\n"]

    # Tasks
    tasks_raw = run_tool(["tools/write_tasks.py", "--action", "list"], timeout=10)
    task_lines = [l for l in tasks_raw.splitlines() if l.strip() and not l.startswith("#")]
    if task_lines:
        lines.append("*Tasks*")
        lines += [f"  {l}" for l in task_lines[:5]]
    else:
        lines.append("*Tasks* — clear")

    lines.append("")

    # Pipeline
    pipeline_raw = run_tool(["tools/pipeline_status.py", "--action", "list"], timeout=10)
    pipeline_lines = [l for l in pipeline_raw.splitlines() if l.strip()]
    if pipeline_lines:
        lines.append("*Pipeline*")
        lines += [f"  {l}" for l in pipeline_lines[:5]]
    else:
        lines.append("*Pipeline* — empty")

    lines.append("")

    # Pending actions
    pending = get_pending_actions()
    if pending:
        lines.append(f"*Pending ({len(pending)})* — type /ok to action")
        for a in pending[:3]:
            badge = _confidence_badge(a.get("confidence", 0.75))
            lines.append(f"  {badge} {a.get('description', a.get('action_type', '?'))[:60]}")
        lines.append("")

    # Latest insight
    insight_path = DATA / "ai-updates.md"
    if insight_path.exists():
        insight_lines = [l for l in insight_path.read_text().splitlines() if l.strip() and not l.startswith("#") and not l.startswith("_") and not l.startswith("**")]
        if insight_lines:
            lines.append(f"*Insight* — _{insight_lines[0][:120]}_")
            lines.append("")

    lines.append("_What do you need?_")
    return "\n".join(lines)


def handle_tasks(args: str) -> str:
    out = run_tool(["tools/write_tasks.py", "--action", "list"])
    return f"*Tasks*\n```\n{out}\n```"


def handle_done(args: str) -> str:
    if not args.strip():
        return "Usage: /done <task text>"
    out = run_tool(["tools/write_tasks.py", "--action", "remove", "--task", args.strip()])
    return f"Done: _{args.strip()}_\n{out}"


def handle_snooze(args: str) -> str:
    if not args.strip():
        return "Usage: /snooze <contact name>"
    today = datetime.now().strftime("%Y-%m-%d")
    out = run_tool([
        "tools/pipeline_status.py", "--action", "update",
        "--name", args.strip(), "--last_contact", today,
    ])
    return f"Snoozed _{args.strip()}_ — last\\_contact = today\n{out}"


def handle_pipeline(args: str) -> str:
    out = run_tool(["tools/pipeline_status.py", "--action", "list"])
    return f"*Pipeline*\n```\n{out}\n```"


def _confidence_badge(confidence) -> str:
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        c = 0.75
    if c >= 0.80:
        return f"🟢 {int(c*100)}%"
    elif c >= 0.60:
        return f"🟡 {int(c*100)}%"
    else:
        return f"🔴 {int(c*100)}%"


def handle_ok(args: str) -> str:
    pending = get_pending_actions()
    if not pending:
        return "No pending actions."
    action = pending[0]
    action_type = action.get("action", "unknown")
    params = action.get("params", {})
    reason = action.get("reason", "")
    confidence = action.get("confidence", 0.75)
    badge = _confidence_badge(confidence)
    result = "Done."

    if action_type == "move_pipeline_stage":
        result = run_tool([
            "tools/pipeline_status.py", "--action", "move",
            "--id", str(params.get("id", "")),
            "--stage", str(params.get("stage", "")),
        ])
    elif action_type == "mark_task_done":
        result = run_tool([
            "tools/write_tasks.py", "--action", "remove",
            "--task", str(params.get("task", "")),
        ])
    elif action_type == "add_task":
        result = run_tool([
            "tools/write_tasks.py", "--action", "add",
            "--task", str(params.get("task", "")),
            "--priority", str(params.get("priority", "this_week")),
        ])
    elif action_type == "log_meeting_notes":
        tool_args = [
            "tools/log_meeting.py",
            "--contact", str(params.get("contact", "")),
            "--summary", str(params.get("summary", "")),
        ]
        if params.get("company"):
            tool_args += ["--company", str(params["company"])]
        if params.get("actions"):
            tool_args += ["--actions", str(params["actions"])]
        if params.get("notes"):
            tool_args += ["--notes", str(params["notes"])]
        result = run_tool(tool_args)
    elif action_type == "add_pipeline_contact":
        tool_args = [
            "tools/pipeline_status.py", "--action", "add",
            "--name", str(params.get("name", "")),
            "--company", str(params.get("company", "")),
            "--stage", str(params.get("stage", "prospect")),
        ]
        if params.get("notes"):
            tool_args += ["--notes", str(params["notes"])]
        result = run_tool(tool_args)
    elif action_type == "send_email":
        tool_args = [
            "tools/send_email.py",
            "--to", str(params.get("to", "")),
            "--subject", str(params.get("subject", "")),
            "--body", str(params.get("body", "")),
        ]
        if params.get("thread_id"):
            tool_args += ["--thread-id", str(params["thread_id"])]
        result = run_tool(tool_args)
    elif action_type == "draft_email":
        result = run_tool([
            "tools/create_gmail_draft.py",
            "--to", str(params.get("to", "")),
            "--subject", str(params.get("subject", "")),
            "--body", str(params.get("body", "")),
        ])
    elif action_type == "create_calendar_event":
        tool_args = [
            "tools/create_calendar_event.py",
            "--title", str(params.get("title", "")),
            "--date", str(params.get("date", "")),
            "--time", str(params.get("time", "")),
            "--duration", str(params.get("duration", 60)),
        ]
        if params.get("description"):
            tool_args += ["--description", str(params["description"])]
        result = run_tool(tool_args)
    elif action_type == "write_memory":
        try:
            import json as _json
            from datetime import datetime as _dt, timezone as _tz
            memory_file = DATA / "memory.jsonl"
            DATA.mkdir(exist_ok=True)
            entry = {
                "timestamp": _dt.now(_tz.utc).isoformat(),
                "content": str(params.get("content", "")),
                "type": str(params.get("type", "insight")),
                "tags": str(params.get("tags", "")),
            }
            with memory_file.open("a") as f:
                f.write(_json.dumps(entry) + "\n")
            result = f"Memory saved: {entry['content'][:80]}"
        except Exception as e:
            result = f"Memory write error: {e}"

    elif action_type == "log_project_decision":
        result = run_tool([
            "tools/project_manager.py",
            "--action", "log-decision",
            "--project", str(params.get("project", "")),
            "--decision", str(params.get("decision", "")),
            "--context", str(params.get("context", "")),
        ])

    update_pending_action(action["id"], "approved")

    # Log to audit trail
    try:
        DATA.mkdir(exist_ok=True)
        sys.path.insert(0, str(BASE))
        from tools.actions_log import log_action
        log_action(action_type, params, result, source="bot-ok", note=reason)
    except Exception as e:
        result += f"\n⚠️ Audit log failed: {e}"

    return f"{badge} Approved: *{action_type}*\n_{reason}_\n\n{result}"


def handle_skip(args: str) -> str:
    pending = get_pending_actions()
    if not pending:
        return "No pending actions."
    action = pending[0]
    update_pending_action(action["id"], "rejected")
    return f"Skipped: _{action.get('action', '?')}_"


def handle_send(args: str) -> str:
    """Show pending send_email actions. /ok sends the first one."""
    pending = get_pending_actions()
    email_actions = [a for a in pending if a.get("action") == "send_email"]
    if not email_actions:
        return "No pending emails to send."
    lines = ["*Pending emails:*\n"]
    for i, a in enumerate(email_actions[:5], 1):
        p = a.get("params", {})
        badge = _confidence_badge(a.get("confidence", 0.75))
        lines.append(f"{i}. {badge} *To:* {p.get('to','?')}\n   *Subject:* {p.get('subject','?')}\n   _{a.get('reason','')}_")
    lines.append("\nType /ok to send the first one · /skip to dismiss it")
    return "\n".join(lines)


def handle_undo(args: str) -> str:
    """Reverse the last completed action if possible."""
    log_path = DATA / "actions-taken.json"
    if not log_path.exists():
        return "No action log found."
    try:
        log = json.loads(log_path.read_text())
        if not log:
            return "No actions to undo."
        last = log[-1]
        action_type = last.get("action", "?")
        # Only certain actions are reversible
        reversible = {"send_email", "add_task", "move_pipeline_stage", "add_pipeline_contact"}
        if action_type not in reversible:
            return f"Last action ({action_type}) can't be undone automatically. Check manually."
        last["status"] = "undone"
        log[-1] = last
        log_path.write_text(json.dumps(log, indent=2))
        return f"Marked last action as undone: *{action_type}*\n_{last.get('note','')}_\n\nNote: for sent emails, go to Gmail Sent to recall manually."
    except Exception as e:
        return f"Undo error: {e}"


def handle_drafts(args: str) -> str:
    """Show this week's LinkedIn post drafts."""
    path = DATA / "content_drafts.json"
    if not path.exists():
        return "No drafts yet. Content machine runs Monday 8:30am IST."
    try:
        data = json.loads(path.read_text())
        posts = data.get("posts", [])
        week = data.get("week", "?")
        if not posts:
            return "No posts in drafts file."
        lines = [f"*LinkedIn Drafts — week of {week}*\n"]
        for i, p in enumerate(posts, 1):
            fmt = p.get("format", "?").upper()
            hook = p.get("hook", "")
            body = p.get("body", "")[:300]
            cta = p.get("cta", "")
            lines.append(f"*{i}. [{fmt}]*\n_{hook}_\n\n{body}{'...' if len(p.get('body','')) > 300 else ''}\n\n→ _{cta}_\n")
        lines.append("_Copy, paste, post manually on LinkedIn._")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading drafts: {e}"


def handle_help(args: str) -> str:
    return (
        "*CLIP Commands*\n\n"
        "/brief — latest heartbeat insight\n"
        "/tasks — your task list\n"
        "/done \\<task\\> — mark task complete\n"
        "/snooze \\<contact\\> — reset staleness timer\n"
        "/pipeline — full pipeline view\n"
        "/send — show pending emails to send\n"
        "/drafts — this week's LinkedIn post drafts\n"
        "/ok — approve pending action\n"
        "/skip — reject pending action\n"
        "/undo — reverse last action\n"
        "/help — this message\n\n"
        "*Voice:* Send a voice note — CLIP transcribes and replies with audio."
    )


COMMANDS = {
    "brief":    handle_brief,
    "tasks":    handle_tasks,
    "done":     handle_done,
    "snooze":   handle_snooze,
    "pipeline": handle_pipeline,
    "send":     handle_send,
    "drafts":   handle_drafts,
    "ok":       handle_ok,
    "skip":     handle_skip,
    "undo":     handle_undo,
    "help":     handle_help,
    "start":    handle_help,
}


def dispatch(text: str) -> str | None:
    text = text.strip()
    if not text.startswith("/"):
        return None
    parts = text[1:].split(None, 1)
    if not parts:
        return "Type /help for available commands."
    cmd = parts[0].lower().split("@")[0]  # strip @botname if present
    args = parts[1] if len(parts) > 1 else ""
    handler = COMMANDS.get(cmd)
    if handler:
        return handler(args)
    return f"Unknown command: /{cmd}\nType /help for available commands."


# ── CEO Agent bridge ────────────────────────────────────────────────────────────

def download_file(token: str, file_id: str, suffix: str = "") -> str | None:
    """Download any Telegram file to /tmp. Returns local path."""
    try:
        resp = requests.get(api_url(token, "getFile"), params={"file_id": file_id}, timeout=10)
        file_path = resp.json()["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        data = requests.get(file_url, timeout=60).content
        ext = suffix or Path(file_path).suffix or ".bin"
        local_path = f"/tmp/clip_file_{int(time.time())}{ext}"
        with open(local_path, "wb") as f:
            f.write(data)
        return local_path
    except Exception as e:
        print(f"[bot] file download error: {e}", file=sys.stderr)
        return None


def call_ceo_agent(text: str, chat_id: str, file_path: str = "") -> str:
    """Route a message through the CEO agent (tools/ceo_agent.py)."""
    args = [BASE / "tools" / "ceo_agent.py", "--chat-id", chat_id]
    if text:
        args += ["--message", text]
    if file_path:
        args += ["--file", file_path]
    result = run_tool([str(a) for a in args], timeout=90)
    # Clean up temp file
    if file_path:
        try:
            Path(file_path).unlink(missing_ok=True)
        except Exception:
            pass
    return result


# ── Main loop ───────────────────────────────────────────────────────────────────

def main():
    load_env()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token:
        print("[bot] TELEGRAM_BOT_TOKEN not set. Exiting.", file=sys.stderr)
        sys.exit(1)

    print(f"[bot] CLIP Telegram bot starting — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"[bot] Authorized chat_id: {chat_id or 'anyone (no restriction)'}")
    print(f"[bot] Voice support: faster-whisper ({WHISPER_MODEL} model) + gTTS")
    sys.stdout.flush()

    offset = 0
    boot_time = int(datetime.now().timestamp())

    while True:
        updates = get_updates(token, offset)

        for update in updates:
            offset = update["update_id"] + 1
            # Skip messages sent before this process started (stale queue drain)
            msg_date = update.get("message", {}).get("date", 0)
            if msg_date and msg_date < boot_time:
                print(f"[bot] Skipping stale message (age {boot_time - msg_date}s)")
                continue
            try:
                _process_update(token, chat_id, update)
            except Exception as e:
                print(f"[bot] ERROR processing update {update.get('update_id')}: {e}", file=sys.stderr)


def _process_update(token: str, chat_id: str, update: dict) -> None:
    message = update.get("message", {})
    msg_chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "")

    # Security: only respond to authorized chat_id
    if chat_id and msg_chat_id != chat_id:
        print(f"[bot] Rejected from chat_id {msg_chat_id}")
        return

    # Voice message
    if message.get("voice") or message.get("audio"):
        print(f"[bot] Voice message received from {msg_chat_id}")
        sys.stdout.flush()
        handle_voice_message(token, msg_chat_id, message)
        return

    # Document / file attachment → CEO agent
    if message.get("document"):
        doc = message["document"]
        file_id = doc.get("file_id", "")
        file_name = doc.get("file_name", "")
        caption = message.get("caption", "")
        print(f"[bot] Document received: {file_name}")
        sys.stdout.flush()
        if file_id:
            send_message(token, msg_chat_id, "_Reading your file..._")
            ext = Path(file_name).suffix if file_name else ""
            local = download_file(token, file_id, ext)
            if local:
                reply = call_ceo_agent(caption, msg_chat_id, local)
            else:
                reply = "Couldn't download your file. Try again."
            send_message(token, msg_chat_id, reply)
        return

    if not text:
        return

    print(f"[bot] Received: {text[:80]}")
    sys.stdout.flush()

    # URL auto-detection: bare URL (alone or with minimal text) → research
    _url_match = re.search(r"https?://\S+", text)
    if _url_match and not text.strip().startswith("/"):
        _url = _url_match.group()
        _extra = text.replace(_url, "").strip()
        print(f"[bot] URL detected: {_url}")
        send_message(token, msg_chat_id, "_Researching..._")
        _cmd = [sys.executable, "tools/research_url.py", "--url", _url]
        if _extra:
            _cmd += ["--context", _extra]
        reply = run_tool(_cmd, timeout=90)
        send_message(token, msg_chat_id, reply)
        return

    reply = dispatch(text)
    if reply:
        send_message(token, msg_chat_id, reply)
    elif text.strip().lower() in GREETINGS:
        send_message(token, msg_chat_id, handle_greeting())
    else:
        # Plain text → CEO agent (full CLIP context + tool_use)
        send_message(token, msg_chat_id, "_Thinking..._")
        reply = call_ceo_agent(text, msg_chat_id)
        send_message(token, msg_chat_id, reply)


if __name__ == "__main__":
    main()
