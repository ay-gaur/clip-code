# Workflow: birdseye — regenerate + open the bird's-eye dashboard

**Trigger:** every "hi clip" session-open pulse (automatic), or on demand ("birdseye", "dashboard", "big picture").
**Tool:** `tools/birdseye.py` · **Output:** `data/birdseye.html` (auto-opened) · **Skins:** `tools/birdseye_skins/`

## Steps (CEO runs these)

1. **Gather live signals (MCP, session-only — python can't do this).**
   Budget ~20-30s total; on ANY failure skip to step 3 (the tool falls back to cached signals).
   - Gmail (google-workspace MCP, acmestudio account): search last 7 days for lane contacts —
     known addresses from `data/contacts.json` (e.g. sam@example.com) plus name/company
     terms: `Jordan OR Northwind OR Riley OR BoxCo OR GrowthCo newer_than:7d`, and
     `is:unread is:important in:inbox newer_than:3d` for anything else that matters.
     Keep only genuinely relevant rows, max ~8.
   - Calendar: events today + tomorrow.

2. **Write `.tmp/live.json`** in this shape (all fields optional; keep it small):
   ```json
   {
     "inbox":    [ { "from": "Jordan", "subject": "Re: plan", "age": "2h", "lane": "alpha", "unread": true } ],
     "calendar": [ { "when": "Tue 15:00", "what": "Call — Jordan" } ]
   }
   ```
   `age` and `when` are display strings — humanize them at write time.

3. **Generate + open:**
   ```bash
   python3 tools/birdseye.py --live-file .tmp/live.json --open   # with fresh signals
   python3 tools/birdseye.py --open                              # fallback: cached signals
   ```

4. **Log it:** covered by the normal session log entry; no separate log line needed unless run on demand.

## Keeping it truthful

- The tool derives the hero from `data/tasks.md` (first Urgent item) and activity from
  `data/task-log.json`. Keep those current through their tools and the page stays honest.
- Lanes / gates / systems / money / commands live in the `CONFIG` block at the top of
  `tools/birdseye.py`. **When reality changes (lane status, a gate passes, revenue lands),
  edit CONFIG in the same session** — that's part of the sync, not optional.
- Date math (countdowns, drought, warmup day) runs in the page's JS at view time, so an
  un-regenerated page shows correct dates but stale facts — the header stamps how old it is
  (amber >24h, red >72h).

## Skins / design

**Picked (D51, 2026-07-08): `f1`** — the pit-wall board: three clickable views (Pit Wall
timing tower with expandable lane drawers · Mission Control telemetry · Command Deck) plus a
persistent "P0 — THE ONE THING" hero. `DEFAULT_SKIN = "f1"` in the tool.
Rejected alternates (`console`, `terminal`, `paper`, `dossier`) remain in `tools/birdseye_skins/`
(same DATA contract — safe to delete once the repo is committed). To preview one:
`python3 tools/birdseye.py --skin console --out .tmp/preview.html --open`

The f1 skin renders lane detail drawers from `CONFIG lanes[].detail`, race control from
`gates` + `notices`, the paddock from `people`, the revenue chart from `revenue`, and the
Command Deck from `deck` — keep those CONFIG blocks current along with lane status.

## Failure modes

- Missing/corrupt live.json → WARN to stderr, cached signals used, page still builds.
- Missing tasks.md sections → hero falls back to rank-1 lane's next move.
- Missing skin/marker → hard error with the available-skins list (fix the template).
