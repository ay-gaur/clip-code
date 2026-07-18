---
name: draft-proposal
description: Generate a structured automation proposal for a client. Use this skill when Alex wants to draft, write, or create a proposal, pitch, or scope document for a client or prospect. Triggers on /draft-proposal or requests like "draft a proposal for X", "write up a pitch for Y", "create an automation proposal for Z", "scope a deal for [Company]".
---

# draft-proposal

You generate structured automation proposals for Alex's clients and prospects. Output a clean, professional proposal saved to `proposals/` and show it inline.

## How to run this skill

Follow `workflows/draft-proposal.md` exactly.

In short:
1. Extract client name, company, services, value, and any context from the user's message
2. Read `context/work.md` and `context/priorities.md` for relevant background
3. Run `python3 tools/draft_proposal.py` with the extracted args
4. Show the saved path + proposal inline
5. Log with `python3 tools/log_entry.py`

## Parsing the request

Extract from user input:
- `--client`: Contact's name (e.g. "John Smith")
- `--company`: Company name (e.g. "Acme Corp")
- `--services`: Comma-separated services to propose (e.g. "claims automation, lead gen, outreach")
- `--value`: Estimated project value in USD (integer, no $ sign) — ask if missing and it matters
- `--context`: Any extra context to embed in the proposal (recent convo notes, constraints, etc.)

If company or client isn't clear, check `context/work.md` and `data/pipeline.json` for a match. Ask only if truly ambiguous.

## Output format

After the tool runs:
1. Print the file path: "Saved → proposals/[filename]"
2. Print the full proposal as-is (it's already formatted markdown)
3. Offer a next step: "Want me to adjust the scope, pricing, or framing?"

No preamble. No "Here's your proposal:". Just the path + doc.

## Mutations and edits

If Alex asks to tweak pricing, scope, or framing after generation:
- Re-run the tool with updated args — don't edit the file directly
- Or if it's a small text edit, use the Edit tool on the saved proposals/ file

## Reflexion log

After every run:
```
python3 tools/log_entry.py --skill draft-proposal --action generate --note "SUMMARY"
```
SUMMARY = "Drafted proposal for [Company] — services: X, value: $Y"
