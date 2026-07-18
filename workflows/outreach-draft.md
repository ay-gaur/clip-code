# Outreach Draft Workflow

## When this runs
- Triggered by CEO when Alex wants to draft or send a cold email to a lead

## Steps

1. **Identify target company**
   Extract from message. If ambiguous:
   ```
   python3 tools/outreach_draft.py --list
   ```
   Show list, ask which one.

2. **Generate draft**
   ```
   python3 tools/outreach_draft.py --company "Company Name"
   ```
   - Reads lead context from `data/leads.json`
   - Tries Apollo.io enrichment for contact info (optional)
   - Calls Claude API (claude-sonnet-4-6) with business context
   - Saves draft to `data/outreach_drafts.json`

3. **Show draft inline**
   Display subject + full body. Ask: "Want me to change the tone, angle, or CTA?"

4. **Iterate if needed**
   Small changes → edit the draft file directly.
   Major rewrite → re-run the tool.

5. **Approve and send**
   When Alex says "send it":
   - Check `data/outreach_drafts.json` for contact email
   - If email found → use Gmail MCP to send
   - If no email → tell Alex to find it (LinkedIn/Apollo), then send manually or come back
   - Update status: `"draft"` → `"sent"`

6. **Log**
   ```
   python3 tools/log_entry.py --skill outreach-draft --action [draft|send] --note "Drafted/sent email to [Company]"
   ```

## Data
- Reads: `data/leads.json` (lead context)
- Writes: `data/outreach_drafts.json` (saves draft)
- Updates: lead status in `data/leads.json` (`new` → `outreach_drafted`)

## Failure modes
- Lead not found → offer to create manually, then draft
- Apollo enrichment fails → skip silently, draft without contact name
- Claude API fails → print error, suggest retrying
- No email for contact → tell Alex, don't send
