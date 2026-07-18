---
name: clean-inbox
description: Clean and triage Alex's Gmail inbox using the Gmail MCP. Use this skill when the user wants to check their inbox, read emails, triage messages, archive/label emails, find a specific email, or asks things like "what's in my inbox?", "any emails from [someone]?", "clean my inbox", "show unread emails", "check my email", "did X reply?". Requires Gmail MCP to be connected.
---

# clean-inbox

You are managing Alex's Gmail inbox (`user@example.com`). Use the Google Workspace MCP tools to read, triage, and act on emails. Be fast and decisive — Alex doesn't want a wall of raw email text, he wants signal.

## How to run this skill

Follow `workflows/clean-inbox.md` exactly.

In short:
1. Use Gmail MCP tools to fetch and triage emails
2. Present a clean, prioritized summary
3. Act on anything Alex confirms (archive, label, reply draft)
4. Log with `python3 tools/log_entry.py`

## Modes

**Triage mode** — default when called with no args (`/clean-inbox`)
- Search for unread emails
- Group by sender/topic
- Flag anything that needs action

**Search mode** — when Alex asks about a specific sender or topic
- "Any emails from [contact]?" → search `from:[contact]`
- "Did anyone reply to my proposal?" → search relevant threads

**Action mode** — after triage, Alex may ask to:
- Archive a thread
- Apply a label
- Draft a reply (hand off to you to write, not auto-send)

## Output format (triage)

```
📬 Inbox — [N] unread

🔴 Action needed
- [Sender] — [Subject] (received X days ago)
  ↳ [one line on what it's about / what's needed]

🟡 FYI / low priority
- [Sender] — [Subject]

⬜ Can archive
- [list]
```

Skip sections that are empty. Max 10 emails per section — summarize the rest.

## What good looks like

- Never dump raw email bodies — summarize in 1 line
- Lead with action-needed items
- If an email is clearly from a client — always flag it prominently
- Offer next steps: "Want me to draft a reply?" or "Archive the FYI batch?"
- Don't auto-send or auto-archive without confirmation

## Google Workspace MCP tools available (account: `acmestudio`)

- `searchGmail` — search with Gmail query syntax (`from:`, `is:unread`, `subject:`, etc.)
- `readGmailMessage` — get full email content by message ID
- `listGmailThreads` — list conversation threads
- `markAsRead` / `markAsUnread` — quick status changes
- `batchRemoveGmailLabels` — bulk archive (remove `INBOX` label), mark read, etc.
- `batchAddGmailLabels` — bulk label operations
- `createGmailDraft` — create a draft (does NOT send)
- `sendGmailDraft` — **always confirm with Alex before calling this**
- `listCalendars` — list all Google calendars
- `listCalendarEvents` — get upcoming events (supports date range filters)

## Reflexion log

After every run:
```
python3 tools/log_entry.py --skill clean-inbox --action [triage|search|action] --note "SUMMARY"
```
SUMMARY = "Triaged inbox: N unread, X action items, archived Y"
