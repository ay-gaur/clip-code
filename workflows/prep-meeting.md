# Workflow: prep-meeting

**Objective:** Generate a structured meeting prep brief for a contact before a call or meeting.

**Inputs:** Contact name (or company name)
**Outputs:** Formatted brief printed to terminal — no file saved
**Data read:** `data/contacts.json`, `data/pipeline.json`
**Tool:** `tools/prep_meeting.py`

---

## Step 1 — Extract contact name

From the user's message, extract:
- Contact name (e.g. "John Smith")
- Or company name if that's all they gave (e.g. "Acme Corp")

If ambiguous (e.g. "prep me for my next call"), ask: "Who's the call with?"

---

## Step 2 — Run the tool

```bash
python3 tools/prep_meeting.py --contact "John Smith"
```

If you only have a company name:
```bash
python3 tools/prep_meeting.py --contact "Acme Corp"
```

The tool searches `contacts.json` and cross-references `pipeline.json`.

---

## Step 3 — Handle: contact not found

If the tool returns `NOT_FOUND`:
1. Show the available contacts list (tool does this automatically)
2. Say: "No record for [Name]. Want me to create a contact? You can use `/log-meeting` after the call to add them."

Don't fail silently — always offer a path forward.

---

## Step 4 — Display output

Print the brief directly — it's already formatted markdown. Then optionally add:
- If `open_items` is non-empty: "You've got [N] open items from your last meeting — worth closing those out."
- If `last_meeting` is >30 days ago: "⚠️ Haven't logged a meeting with them in X days."
- If pipeline stage is `proposal` or `negotiation`: "They're in [stage] — this call matters."

---

## Step 5 — Log the interaction

```bash
python3 tools/log_entry.py \
  --skill prep-meeting \
  --action view \
  --note "Prepped for call with [Name] ([Company]) — stage: X, last met: Y"
```

---

## Edge cases

- **Only company name given:** `prep_meeting.py` does partial matching — usually works. If not, show the list.
- **Contact has no meetings logged yet:** Brief will show background/pipeline but no history. That's fine — note it.
- **Multiple contacts with similar names:** Tool returns first match. If wrong, show the list and ask to confirm.

---

## What NOT to do

- Don't make up information that isn't in the contact record
- Don't pull from context files to fill in gaps — only use what's in `contacts.json` and `pipeline.json`
- Don't skip the log step

---

## Learning notes

*(Updated as edge cases are discovered)*

- Tool cross-references `pipeline.json` automatically — no need to run both tools manually
- Brief is most useful when `meetings[]` has at least 1–2 entries
- Encourage Alex to use `/log-meeting` after every call to build up the record
