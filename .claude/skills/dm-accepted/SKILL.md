---
name: dm-accepted
description: Alex's follow-up DM sender for accepted LinkedIn connections. Use this skill when Alex wants to send follow-up DMs to recently-accepted LinkedIn connections, asks "send DMs to accepted invites", "follow up with my new connections", "dm accepted connections", "send resumes to my new linkedin contacts", or wants to run Phase 7c. Trigger on /dm-accepted or any request about following up with accepted LinkedIn invites / sending DMs to new connections.
---

# dm-accepted

You send the follow-up DM (with the tailored resume PDF attached) to each LinkedIn connection that accepted Alex's request. Per-DM approval. Cap: 20 DMs/day.

## Setup gates

1. Claude in Chrome MCP available.
2. Alex logged into LinkedIn.
3. Queue non-empty: `python3 tools/job_outreach_linkedin.py list-accepted-dms`. Surface count.

If queue empty → "No accepted connections waiting on a DM. Check `/clean-inbox` to detect new acceptances."

## The loop (per DM)

### Step 1: Get next DM
```
python3 tools/job_outreach_linkedin.py get-next-dm
```
Returns `{next: {connection_id, manager_name, manager_linkedin_url, follow_up_dm, tailored_pdf, ...}}`.

### Step 2: Navigate to messaging with that person
The fastest path is:
```
mcp__Claude_in_Chrome__navigate({url: <manager_linkedin_url>})
```
Then click "Message" on their profile.

OR use direct messaging URL:
```
mcp__Claude_in_Chrome__navigate({url: "https://www.linkedin.com/messaging/thread/new/"})
```
Search for the manager by name.

### Step 3: Paste DM text
```
mcp__Claude_in_Chrome__form_input({selector: <message textarea>, value: <follow_up_dm>})
```

### Step 4: Attach tailored resume PDF
```
mcp__Claude_in_Chrome__find({query: "Attach file / paperclip icon"})
mcp__Claude_in_Chrome__left_click(...)
mcp__Claude_in_Chrome__file_upload({path: <tailored_pdf>, selector: ...})
```
Wait for upload completion (usually < 5s; verify by reading page state).

### Step 5: STOP before send
```
mcp__Claude_in_Chrome__screenshot()
```
Show to Alex: "DM ready with resume attached. Approve, edit, or reject?"

### Step 6: Send
```
mcp__Claude_in_Chrome__find({query: "Send message button"})
mcp__Claude_in_Chrome__left_click(...)
```

### Step 7: Record
```
python3 tools/job_outreach_linkedin.py record-dm \
  --connection-id <id> \
  --status sent \
  --dm-text "<actual text sent>"
```

### Step 8: Pace + repeat
Wait 30-90s before next DM. Then back to Step 1.

## Hard stops

- LinkedIn shows "rate limit" / "slow down" warning → halt for the day; tell Alex.
- File upload fails 2× → MCP / LinkedIn UI changed; halt and report.
- Alex rejects 2 DMs in a row → halt + ask if rubric needs tuning.

## End-of-session

```
python3 tools/job_outreach_linkedin.py status
```
Update dashboard + Sheets. Reflexion log.

## Critical voice notes

- The DM template (`follow_up_dm` from Phase 6) is ~150 words. Alex can shorten if recipient prefers brevity (LinkedIn DMs over 200 words rarely get read).
- Always preserve the "{resume_url}" or attached-PDF reference — that's the whole point.
- Sign "Alex" first-name-only.
