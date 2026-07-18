# data/ — the persistent state layer

CLIP's tools read and write JSON/Markdown state here. **The real data is private and
is not part of this shared snapshot** (`data/*` is gitignored). This file documents the
expected shape so the code makes sense; create these files locally to run the tools.

Tools never mutate `data/` directly — they go through `tools/*.py` (the "WAT" rule).

| File | Shape | Written by |
|------|-------|------------|
| `tasks.md` | Markdown with `## urgent / ## this week / ## backlog` sections, `- [ ]` items | `write_tasks.py` |
| `task-log.json` | append-only list of `{ts, skill, action, note}` | `log_entry.py` |
| `pipeline.json` | list of deals `{name, stage, lane, next, ...}` | `pipeline_status.py` |
| `contacts.json` | map of `{contact_id: {name, company, email, history[]}}` | `enrich_contact.py`, `log_meeting.py` |
| `leads.json` | list of scored leads `{company, url, score, signals[]}` | `find_leads.py`, `gap_score.py` |
| `outreach_drafts.json` | list of `{contact, subject, body, status}` | `outreach_draft.py` |
| `content_drafts.json` | list of `{platform, hook, body, status}` | `content_draft.py` |
| `credits.json` | per-service API budget counters | `credits.py` |
| `birdseye.html` / `birdseye_live.json` | generated dashboard + signal cache | `birdseye.py` |

Sub-directories (`sessions/`, `research/`, `gap_runs/`, …) hold per-run working files.
All are safe to delete; the tools recreate them.
