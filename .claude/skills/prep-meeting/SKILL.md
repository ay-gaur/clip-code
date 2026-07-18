---
name: prep-meeting
description: Generate a meeting prep brief for a contact. Use this skill when Alex is about to have a call or meeting and wants to prep. Triggers on /prep-meeting or requests like "prep me for my call with X", "I have a meeting with Y, prep brief", "what do I know about Z before we talk?", "meeting notes for [Name]".
---

# prep-meeting

You generate a tight meeting prep brief for Alex before a call or meeting. Pull from `data/contacts.json` and `data/pipeline.json`. Output a structured brief — fast and useful.

## How to run this skill

Follow `workflows/prep-meeting.md` exactly.

In short:
1. Extract the contact name from the user's message
2. Run `python3 tools/prep_meeting.py --contact "Name"`
3. Print the output as-is
4. Log with `python3 tools/log_entry.py`

## Parsing the request

- Extract the contact name. If only a company name is given, try that too.
- If ambiguous, run `python3 tools/prep_meeting.py --list` first and ask Alex to confirm.
- If the contact isn't in `contacts.json`, say so and offer to create them via `/log-meeting`.

## Output format

Show the brief directly — it's already formatted. Then optionally offer:
- "Want me to draft talking points or a follow-up message for this meeting?"

No intro. No "Here's your brief:". Just the brief.

## What good looks like

- Fast. Alex wants signal before a call, not a wall of text.
- If there are open action items from the last meeting, surface them prominently.
- If the contact is in a key pipeline stage (proposal, negotiation), highlight it.
- If last_meeting is >30 days ago, flag it: "⚠️ Haven't met in X days — worth a quick catch-up note before the call?"

## Reflexion log

After every run:
```
python3 tools/log_entry.py --skill prep-meeting --action view --note "SUMMARY"
```
SUMMARY = "Prepped for call with [Name] ([Company]) — stage: X, last met: Y"
