# Workflow: draft-proposal

**Objective:** Generate a structured automation proposal for a client, save it to `proposals/`, and display it inline.

**Inputs:** Client name, company, services to propose, optional value estimate and context
**Outputs:** Saved markdown file in `proposals/`, printed to terminal
**Data written:** `proposals/<company-slug>_<date>.md`
**Tool:** `tools/draft_proposal.py`

---

## Step 1 — Parse intent and extract args

From the user's message, extract:

| Arg | Source | Required? |
|-----|--------|-----------|
| `--client` | Name of the contact | Yes |
| `--company` | Company name | Yes |
| `--services` | Comma-separated list of services | Yes |
| `--value` | Estimated USD value (integer) | Recommended |
| `--context` | Any notes, constraints, or recent convo context | Optional |

**If client/company isn't obvious:** Check `context/work.md` for active clients and `data/pipeline.json` for contacts in the pipeline. Default to whoever is most contextually relevant.

**If services aren't specified:** Ask Alex which services to include before running.

---

## Step 2 — Run the tool

```bash
python3 tools/draft_proposal.py \
  --client "John Smith" \
  --company "Acme Corp" \
  --services "claims automation, lead generation, outreach automation" \
  --value 8000 \
  --context "In talks since Jan, 3-month engagement"
```

The tool:
1. Builds a structured markdown proposal
2. Saves it to `proposals/<slug>_<date>.md`
3. Prints the saved path + full proposal to stdout

---

## Step 3 — Display output

Print directly from the tool output:
```
Saved → proposals/client-name_2026-04-04.md

# Automation Proposal — Client Name
...
```

After the proposal, offer one follow-up:
- "Want me to adjust scope, pricing, or framing?"
- "Want to send this to the client? I can draft an email."

---

## Step 4 — Log the interaction

```bash
python3 tools/log_entry.py \
  --skill draft-proposal \
  --action generate \
  --note "Drafted proposal for [Company] — [services]. ~$[value]"
```

---

## Edge cases

- **Company already has a proposal file:** That's fine — the new run creates a new dated file. Don't overwrite.
- **Value not given:** Default to 0, don't fail. Alex can fill it in.
- **Services are vague (e.g. "automation stuff"):** Ask to clarify before running — the services list is the heart of the proposal.
- **Alex wants to edit after generation:** For small edits, use Edit tool on the saved file. For rewrites, re-run the tool with updated args.

---

## What NOT to do

- Don't edit `proposals/` files directly to generate the initial draft — always go through the tool
- Don't add marketing fluff — keep the proposal tight and honest
- Don't invent pricing — use what Alex provides or leave it blank with a TBD note

---

## Learning notes

*(Updated as edge cases are discovered)*

- Tool outputs path + full proposal — display both
- `proposals/` dir is auto-created on first run
- Filename format: `<company-slug>_<YYYY-MM-DD>.md`
