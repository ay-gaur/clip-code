---
name: outreach-draft
description: Alex's cold email drafter for CLIP. Use this skill when the user wants to draft, write, or send a cold outreach email to a lead, or asks things like "draft an email for [Company]", "write outreach for [Name]", "send cold email to X", "draft pitch for this lead", "compose outreach". Trigger on /outreach-draft or any request to write a cold email or pitch message for a lead.
---

# outreach-draft

You generate personalized cold outreach emails for leads in `data/leads.json`.

## How to run this skill

Follow `workflows/outreach-draft.md` exactly.

**Step 1 — Identify the target company**

Extract company name from Alex's message. If unclear, run:
```
python3 tools/outreach_draft.py --list
```
Show the list and ask which one.

**Step 2 — Generate the draft**

```
python3 tools/outreach_draft.py --company "Company Name"
```

This calls the Claude API and generates the email. Show the full draft inline:
- Subject line
- Full email body

**Step 3 — Review and iterate**

Ask: "Want me to change the tone, angle, or CTA?"

If Alex wants changes, regenerate:
```
python3 tools/outreach_draft.py --company "Company Name"
```
Or edit the draft manually if it's a small tweak.

**Step 4 — Approve and send**

When Alex says "send it" or "looks good":
1. Read the contact email from `data/outreach_drafts.json`
2. If email is known → use Gmail MCP to draft/send
3. If email is unknown → tell Alex: "No email found for this contact. Find it on LinkedIn or Apollo and I'll send it."

Update the draft status to `"approved"` or `"sent"` in `data/outreach_drafts.json`.

## For a lead not in the system

If Alex says "draft outreach for [Company] I saw on LinkedIn":
1. Ask for the role they posted and what they're doing manually
2. Create a minimal lead entry in `data/leads.json` via `data/leads.json` directly
3. Then run the draft tool

## Reflexion log

```
python3 tools/log_entry.py --skill outreach-draft --action [draft|send|revise] --note "SUMMARY"
```
SUMMARY = "Drafted cold email for [Company] — angle: [automation type]"
