# Workflow: log-meeting

**Objective:** Capture meeting notes and action items from a call and write them to `data/contacts.json`.

**Inputs:** Contact name, meeting date, summary, action items, optional notes
**Outputs:** Updated `data/contacts.json` — new or updated contact record
**Data written:** `data/contacts.json`
**Tool:** `tools/log_meeting.py`

---

## Step 1 — Parse the user's input

From the user's message (which may be raw meeting notes), extract:

| Arg | What it is | Required? |
|-----|-----------|-----------|
| `--contact` | Person's name | Yes |
| `--company` | Their company | Recommended |
| `--date` | Meeting date (YYYY-MM-DD) | Default: today |
| `--summary` | One sentence — what the meeting was about / main outcome | Yes |
| `--actions` | Comma-separated action items (next steps) | Recommended |
| `--notes` | Any other context worth storing | Optional |

**If the user gives raw meeting notes:** Synthesize before running:
- Summary = the core outcome in one sentence
- Actions = concrete next steps (strip vague things like "think about it")
- Notes = anything else — sentiment, context, blockers, quotes

---

## Step 2 — Run the tool

```bash
python3 tools/log_meeting.py \
  --contact "John Smith" \
  --company "Acme Corp" \
  --date 2026-04-04 \
  --summary "Aligned on automation scope: outreach + pipeline, 3-month engagement" \
  --actions "Send proposal draft by Friday,Schedule follow-up call for next week" \
  --notes "Ready to move forward if pricing is right"
```

The tool:
- If contact exists → appends the meeting to `meetings[]`, updates `last_meeting`, merges `open_items`
- If contact doesn't exist → creates a new record with full meeting history

---

## Step 3 — Confirm and display

Show the confirmation output from the tool, then display the action items clearly:

```
Logged: John Smith — 2026-04-04

Action items:
- Send proposal draft by Friday
- Schedule follow-up call for next week
```

If a new contact was created: "Added [Name] to contacts."

---

## Step 4 — Offer follow-through

After logging, optionally offer:
- "Want me to draft the proposal now?" → trigger `/draft-proposal`
- "Want me to add any of these action items to your task list?" → trigger `/task-check`
- "Want me to move them in the pipeline?" → trigger `/pipeline-status`

Don't do these automatically — offer and wait for a yes.

---

## Step 5 — Log the interaction

```bash
python3 tools/log_entry.py \
  --skill log-meeting \
  --action log \
  --note "Logged meeting with [Name] ([Company]) — N action items"
```

---

## Edge cases

- **No action items from the meeting:** Fine — still log summary and notes
- **User gives a wall of raw text:** Synthesize; don't dump raw text into `--summary`
- **Date not given:** Default to today — always use `YYYY-MM-DD` format
- **Duplicate meeting for same day:** Tool appends another entry — that's okay, more context is better
- **Contact name is ambiguous:** Tool does partial match. If it creates a duplicate, user can merge manually later.

---

## What NOT to do

- Don't edit `data/contacts.json` directly — always go through `tools/log_meeting.py`
- Don't invent action items — only log what was actually discussed
- Don't skip the log step

---

## Learning notes

*(Updated as edge cases are discovered)*

- `open_items` accumulates across meetings — it's a running list, not just from the last call
- Meeting history (`meetings[]`) is the source of truth for `/prep-meeting` — the better the log, the better the prep
- Encourage logging after every meaningful call, even short check-ins
