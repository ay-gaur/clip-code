---
name: morning-brief
description: Alex's daily morning briefing for CLIP. Use this skill whenever the user types /morning-brief or asks for their morning brief, daily briefing, "what's on today", "brief me", "what do I need to know this morning". Pulls tasks, pipeline, and schedule into one tight briefing.
---

# morning-brief

You are generating Alex's morning briefing. No preamble. Run the tool, show the output.

## How to run this skill

Follow `workflows/morning-brief.md` exactly.

In short:
1. Run `python3 tools/morning_brief.py`
2. Print the output as-is
3. **If job-search is active** (i.e., `data/apply_log.json` or `data/connection_log.json` exist), append a "## Job Search" section below the regular brief by running:
   ```
   python3 tools/job_status_report.py --window-days 1
   ```
   Concatenate that output as the last section of the brief. Skip silently if no job activity yet.
4. Log the interaction with `python3 tools/log_entry.py`

## Output style

- Show the tool output directly — don't add headers, don't summarize, don't wrap it
- After printing the brief, you may offer one short follow-up: "Want to update anything?" — but only if it feels natural
- No filler. No "Here's your morning brief:". Just the brief.

## Reflexion log

After every run, call:
```
python3 tools/log_entry.py --skill morning-brief --action view --note "SUMMARY"
```

SUMMARY = one line covering what surfaced (e.g. "2 urgent tasks, Meera 3d stale, no meetings").

This is mandatory — it's how CLIP learns over time.
