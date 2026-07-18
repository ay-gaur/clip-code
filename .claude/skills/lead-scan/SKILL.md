---
name: lead-scan
description: Alex's lead scanner for CLIP. Use this skill when the user wants to see their leads, find new leads, review who to reach out to, or asks things like "show me my leads", "any new leads this week?", "who should I reach out to?", "run the lead scan", "find me clients". Trigger on /lead-scan or any natural-language request about leads, finding clients, or who to pitch.
---

# lead-scan

You help Alex find and review leads — companies paying humans for work that can be automated.

## How to run this skill

Follow `workflows/lead-scan.md` exactly.

**Step 1 — Check if fresh leads exist**

Run:
```
python3 tools/outreach_draft.py --list
```
This shows all leads in `data/leads.json` with their status.

**Step 2 — If no leads exist (or Alex wants a fresh scan)**

Run:
```
python3 tools/lead_scan.py --no-email
```
This runs the scan and prints results. Tell Alex how many new leads were found.

**Step 3 — Show leads and surface the best ones**

Read `data/leads.json`. Filter for `"status": "new"`. Show the top 5:
- Company name
- Role they posted
- Automation angle (the pitch hook)

Ask: "Want me to draft outreach for any of these?"

## Routing to outreach-draft

If Alex picks a company, say: "I'll draft the email now."
Then run:
```
python3 tools/outreach_draft.py --company "Company Name"
```
Show the draft inline. Ask if he wants changes before saving.

## Reflexion log

```
python3 tools/log_entry.py --skill lead-scan --action [view|scan|draft] --note "SUMMARY"
```
SUMMARY = "Showed X new leads" or "Scanned, found X leads, drafted for Y"
