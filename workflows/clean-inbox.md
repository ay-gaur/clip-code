# Workflow: clean-inbox

**Objective:** Triage Alex's Gmail inbox, surface action items, and optionally act on emails.

**Inputs:** Optional — search query or specific sender/topic
**Outputs:** Prioritized inbox summary printed to terminal; optional draft/archive actions
**Data read/written:** Gmail via MCP (no local files)
**Tool:** Gmail MCP (`gmail` server in `~/.claude.json`)

---

## Prerequisites

Google Workspace MCP must be connected (`google-workspace-mcp`). Verify with:
```
~/.google-mcp/credentials.json  ← must exist
~/.google-mcp/accounts/acmestudio/  ← must exist (OAuth token)
```

If missing, run:
```bash
npx google-workspace-mcp setup
npx google-workspace-mcp accounts add acmestudio
```

---

## Step 1 — Detect mode

| Input | Mode |
|-------|------|
| `/clean-inbox` (no args) | Triage — show all unread |
| "any emails from X" | Search — `from:X` |
| "did X reply?" | Search — `from:X is:unread` |
| "find email about Y" | Search — `subject:Y` |
| "archive these" / "mark read" | Action — modify messages |
| "draft a reply to X" | Draft — create draft, don't send |

---

## Step 2 (Triage mode) — Fetch and categorize

1. Search for unread emails:
   ```
   searchGmail: query="is:unread", maxResults=20
   ```

2. For each result, read subject + sender + snippet (avoid full body unless needed)

3. Categorize:
   - **Action needed**: client emails, replies to sent messages, anything with a question or request
   - **FYI**: newsletters, notifications, updates — no response needed
   - **Archive**: receipts, automated emails, old threads

4. Present in the structured format from SKILL.md

---

## Step 2 (Search mode) — Find specific emails

```
searchGmail: query="from:client@example.com"
```

Show matching threads with date + subject + one-line summary. Ask if Alex wants to read the full thread.

---

## Step 3 (Action mode) — Archive / label / mark read

**Archive (single):**
```
batchRemoveGmailLabels: messageIds=[<id>], labelIds=["INBOX"]
```

**Mark as read:**
```
markAsRead: messageId=<message_id>
```

**Bulk archive:**
```
batchRemoveGmailLabels: messageIds=[<id1>, <id2>, ...], labelIds=["INBOX"]
```

**Apply label:**
```
batchAddGmailLabels: messageIds=[<id>], labelIds=["<label_id>"]
```

Always confirm before acting on more than 3 emails at once.

---

## Step 4 (Draft mode) — Write a reply draft

1. Read the original email for context with `readGmailMessage`
2. Draft a reply based on Alex's instructions
3. Call `createGmailDraft` — this creates a draft only, does NOT send
4. Confirm: "Draft saved — you can review and send from Gmail"

**Never call `sendGmailDraft` without explicit confirmation from Alex.**

---

## Step 5 — Log the interaction

```bash
python3 tools/log_entry.py \
  --skill clean-inbox \
  --action triage \
  --note "Triaged inbox: 12 unread, 3 action items (client reply, 2 inquiries), archived 7"
```

---

## Edge cases

- **MCP not connected:** Say "Google Workspace MCP isn't connected. Run `npx google-workspace-mcp accounts add acmestudio` to re-authenticate."
- **Empty inbox:** "Inbox is clear."
- **Large inbox (50+ unread):** Process in batches of 20, ask if Alex wants to continue after each batch
- **Active client email:** Always flag prominently regardless of category

---

## What NOT to do

- Don't dump raw email bodies — always summarize
- Don't auto-send anything
- Don't archive client emails without explicit confirmation
- Don't read emails Alex didn't ask about

---

## Learning notes

*(Updated as edge cases are discovered)*

- Google Workspace MCP credentials stored at `~/.google-mcp/credentials.json`
- Account token stored at `~/.google-mcp/accounts/acmestudio/`
- Token may expire — re-run `npx google-workspace-mcp accounts add acmestudio` if you get 401 errors
- `searchGmail` uses standard Gmail query syntax
- Multi-account: all tools accept an optional `account_name` param (defaults to first account)
