---
name: log-meeting
description: Log meeting notes and action items for a contact. Use this skill when Alex wants to record notes from a call or meeting, add action items, or update what happened with a contact. Triggers on /log-meeting or requests like "log my call with X", "just had a meeting with Y, here's what happened", "add notes from my call with Z", "we met with [Name], action items are...", "save these meeting notes".
---

# log-meeting

You capture meeting notes and action items and write them to `data/contacts.json`. This is how CLIP builds institutional memory about Alex's contacts over time.

## How to run this skill

Follow `workflows/log-meeting.md` exactly.

In short:
1. Extract: contact name, company, date, summary, action items, and any notes from the user's message
2. Run `python3 tools/log_meeting.py` with the extracted args
3. Confirm what was logged
4. Log with `python3 tools/log_entry.py`

## Parsing the request

Extract from user input:
- `--contact`: Person's name (required)
- `--company`: Their company (optional if already in contacts)
- `--date`: Meeting date (default: today — YYYY-MM-DD format)
- `--summary`: One sentence describing what the meeting was about
- `--actions`: Comma-separated list of action items (things to do next)
- `--notes`: Any additional context or observations worth keeping

If the user gives a wall of raw notes, synthesize:
- Summary = one sentence capturing the meeting's main outcome
- Actions = concrete next steps (who does what)
- Notes = anything else worth storing (sentiment, context, blockers)

Don't ask for clarification unless something critical is missing (like who the meeting was with).

## Output format

After the tool runs:
1. Confirm: "Logged: [Name] — [date]"
2. Show the action items clearly:
   ```
   Action items:
   - Send proposal by Friday
   - Schedule follow-up call
   ```
3. Offer: "Want me to draft any of these follow-ups?"

## Edge cases

- **New contact:** Tool will create them automatically. Mention it: "Added [Name] to contacts."
- **No action items:** Fine — still log summary + notes
- **Vague notes:** Synthesize a clean summary, don't dump raw text into the record
- **If `/prep-meeting` was just run for this person:** Offer to cross-check against their open items

## Reflexion log

After every run:
```
python3 tools/log_entry.py --skill log-meeting --action log --note "SUMMARY"
```
SUMMARY = "Logged meeting with [Name] ([Company]) — [N] action items"
