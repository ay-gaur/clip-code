# Workflow: task-check

**Objective:** Read or update `data/tasks.md` and present Alex's tasks in a clean, scannable format.

**Inputs:** User command (view, add, or remove)
**Outputs:** Formatted task list in terminal, or confirmation of add/remove
**Data file:** `data/tasks.md`
**Tool:** `tools/write_tasks.py`

---

## Step 1 — Detect intent

Read the user's input and decide which mode:

| Input pattern | Mode |
|---|---|
| `/task-check` with nothing else | View |
| "what do I need to do", "show tasks", "my list" | View |
| "add: X [priority]", "/task-check add X" | Add |
| "remove: X", "done: X", "mark X complete" | Remove |

If unclear, default to View.

---

## Step 2 (View mode) — Read and display

1. Read `data/tasks.md`
2. Parse the three sections: Urgent, This Week, Backlog
3. Display using the format defined in SKILL.md
4. If a section is empty, skip it entirely
5. If ALL sections empty → "No tasks on the list."

---

## Step 2 (Add mode) — Parse and write

1. Extract task description from input
2. Extract priority:
   - `[urgent]` or "urgent" → priority = urgent
   - `[week]` or "this week" → priority = week
   - `[backlog]` or nothing specified → priority = week (default)
3. Run the tool:
   ```
   python tools/write_tasks.py --action add --task "DESCRIPTION" --priority PRIORITY
   ```
4. Confirm: "Added: [task] → [priority section]"
5. Optionally show the updated task list

---

## Step 2 (Remove mode) — Find and remove

1. Extract the task description (approximate is fine)
2. Run the tool:
   ```
   python tools/write_tasks.py --action remove --task "DESCRIPTION"
   ```
3. The tool handles fuzzy matching
4. Confirm: "Removed: [task]" or "Couldn't find a matching task — try being more specific"

---

## Edge cases

- **Duplicate tasks:** The tool checks for duplicates before adding. If the same task already exists, say: "That task is already on the list."
- **Empty file:** If `data/tasks.md` doesn't exist or has no content, create/initialize it with the standard template before writing.
- **Priority not recognized:** Default to "week", don't fail.

---

## Step 3 — Log the interaction (reflexion)

After every skill execution, call:

```bash
python3 tools/log_entry.py --skill task-check --action ACTION --note "SUMMARY"
```

- `ACTION`: the mode used — `view`, `add`, or `remove`
- `SUMMARY`: 1 line — what happened (e.g. "Viewed tasks: 3 urgent, 2 this week", "Added: call Ravi → urgent")

This is mandatory — it feeds CLIP's learning flywheel.

---

## What NOT to do

- Do not edit `data/tasks.md` directly with file tools. Always use `tools/write_tasks.py`.
- Do not add tasks silently — always confirm what was added.
- Do not show filler text like "Here are your tasks:" — just show the tasks.

---

## Learning notes

*(Updated as edge cases are discovered)*

- tasks.md uses `##` headers for sections and `-` for list items
- The tool uses exact section names: "Urgent", "This Week", "Backlog"
