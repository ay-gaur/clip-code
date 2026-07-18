# Workflow: morning-brief

**Objective:** Generate Alex's daily morning briefing — tight, prioritized, actionable. Not a data dump.

**Inputs:** None (reads live data files)
**Outputs:** Formatted brief printed to terminal
**Data files:** `data/tasks.md`, `data/pipeline.json`, `data/schedule.md`
**Tool:** `tools/morning_brief.py`

---

## Step 1 — Run the brief tool

```bash
python3 tools/morning_brief.py
```

Capture stdout. This is the brief.

---

## Step 1b — Fetch today's calendar (if Google Workspace MCP is connected)

After running the brief tool, check today's calendar events:

```
listCalendarEvents: calendarId="primary", timeMin=<today 00:00 IST>, timeMax=<today 23:59 IST>
```

If events are returned, append a **Today's Schedule** section to the brief:
```
📅 Today's Schedule
- [HH:MM] Event name (duration)
- [HH:MM] Event name
```

If no events: skip the section (don't say "no events").
If MCP not connected: skip silently.

---

## Step 2 — Present the output

Print the brief tool output first, then append the calendar section (if any). Do not otherwise reformat the tool output.

---

## Step 3 — Log the interaction (reflexion)

After presenting the brief, always log to `data/task-log.json`:

```bash
python3 tools/log_entry.py --skill morning-brief --action view --note "SUMMARY"
```

Where SUMMARY is a 1-line note on what surfaced: e.g. "3 urgent tasks, Meera proposal 3d stale, no meetings today".

---

## Edge cases

- **tasks.md missing or empty:** Tool handles gracefully — shows "Nothing urgent or due this week."
- **pipeline.json missing:** Tool handles gracefully — shows "Pipeline looks healthy."
- **schedule.md missing:** Tool handles gracefully — shows no meetings.
- **All data missing:** Still runs, returns a minimal brief. Never crash.

---

## What good looks like

- Brief should feel like a smart assistant briefing you at 8am — what's urgent, what's hot, what needs follow-up
- Top action at the bottom gives Alex one clear "start here" signal
- The whole thing should read in under 30 seconds

---

## Learning notes

*(Updated as edge cases are discovered)*

- Stale threshold is 3 days — adjust STALE_DAYS in morning_brief.py if too noisy
- schedule.md uses `_none scheduled_` as placeholder; parser ignores these
- Pipeline stages: prospect, contacted, qualified, proposal, negotiation, client — "client" is never flagged as stale
