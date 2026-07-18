# Workflow: pipeline-status

**Objective:** Read or update `data/pipeline.json` and present Alex's sales pipeline in a clear, actionable format.

**Inputs:** User command (view, add, move, remove, update)
**Outputs:** Formatted pipeline in terminal, or confirmation of change
**Data file:** `data/pipeline.json`
**Tool:** `tools/pipeline_status.py`

---

## Pipeline stages (in order)

| Stage | Meaning |
|---|---|
| `prospect` | Researched, not yet contacted |
| `contacted` | Outreach sent, no reply yet |
| `qualified` | Responded, had initial conversation |
| `proposal` | Proposal sent or in progress |
| `negotiation` | Discussing terms / scope |
| `client` | Active paying client |
| `closed_lost` | Passed, ghosted, or rejected |

---

## Step 1 — Detect intent

| Input pattern | Mode |
|---|---|
| `/pipeline-status` with nothing else | View all |
| "show pipeline", "what's in my pipeline" | View all |
| "show prospects", "who's in negotiation" | View (stage filter) |
| "add: Name at Company [stage]" | Add |
| "move X to qualified", "X responded" | Move |
| "remove X", "drop X from pipeline" | Remove |
| "update X notes/value/last_contact" | Update |

If unclear, default to View all.

---

## Step 2 (View mode) — Read and display

1. Run the tool:
   ```
   python3 tools/pipeline_status.py --action list
   ```
   Or with a stage filter:
   ```
   python3 tools/pipeline_status.py --action list --stage qualified
   ```
2. Display the raw output directly — it's already formatted
3. Add a brief follow-up observation if warranted:
   - Contacts sitting in `contacted` for >7 days without a reply → suggest follow-up
   - High-value contacts in `negotiation` → flag if last_contact was >3 days ago
   - `proposal` with no update in >5 days → ask if Alex wants to follow up

---

## Step 2 (Add mode) — Parse and write

Parse from user input:
- `--name`: Contact's name
- `--company`: Company name
- `--stage`: Stage (default to `prospect` if not specified)
- `--type`: `dtc` / `manufacturer` / `b2b` / `other` (default `other`)
- `--value`: Monthly value estimate in USD (integer, no $ sign)
- `--notes`: Brief context

Run:
```
python3 tools/pipeline_status.py --action add --name "Name" --company "Company" --stage prospect --type dtc --value 5000 --notes "context"
```

Confirm: "Added: [Name] at [Company] → [stage]"

---

## Step 2 (Move mode) — Advance or change stage

1. Extract: contact id or name, target stage
2. If only a name is given (not an id), first run `--action list` to find the id
3. Run:
   ```
   python3 tools/pipeline_status.py --action move --id p001 --stage qualified
   ```
4. Confirm: "Moved: [Name] → [new stage]"
5. Optionally suggest next action for the new stage (e.g., "In proposal — want me to draft an outline?")

---

## Step 2 (Remove mode) — Drop a contact

1. Run `--action list` first to find the id if not provided
2. Run:
   ```
   python3 tools/pipeline_status.py --action remove --id p001
   ```
3. Confirm: "Removed: [Name] from pipeline"

---

## Step 2 (Update mode) — Edit notes, value, or last_contact

```
python3 tools/pipeline_status.py --action update --id p001 --notes "new context" --last_contact 2026-03-09
```

---

## Edge cases

- **Name not found:** Show the full list and ask Alex to confirm the id
- **Stage not recognized:** List valid stages and ask for clarification
- **Value not given on add:** Default to 0, don't fail
- **Duplicate name+company:** Tool will catch and print DUPLICATE — surface it cleanly

---

## Step 3 — Log the interaction (reflexion)

After every skill execution, call:

```bash
python3 tools/log_entry.py --skill pipeline-status --action ACTION --note "SUMMARY"
```

- `ACTION`: the mode used — `view`, `add`, `move`, `remove`, or `update`
- `SUMMARY`: 1 line — what happened (e.g. "Moved Anil Sharma → proposal", "Viewed full pipeline: 6 contacts")

This is mandatory — it feeds CLIP's learning flywheel.

---

## What NOT to do

- Do not edit `data/pipeline.json` directly with file tools. Always use `tools/pipeline_status.py`.
- Do not show all contacts when a stage filter is requested.
- Do not add filler like "Here's your pipeline:" — just show the output.

---

## Learning notes

*(Updated as edge cases are discovered)*

- Tool outputs are already formatted for display — pass through directly
- Stage order matters: prospect → contacted → qualified → proposal → negotiation → client
- `closed_lost` is intentionally last and often hidden unless explicitly requested
