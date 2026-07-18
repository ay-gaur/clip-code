# About this snapshot

This repository is a **sanitized code snapshot** of CLIP — an in-session "AI operating
system" that runs an operator's business admin through a chain of
**skills → workflows → tools** (the "WAT" framework; see `CLAUDE.md`).

It is shared to show the **structure and code**, not the business behind it. To that end:

- **No private data.** The `data/` state layer (pipeline, contacts, leads, tasks) and the
  `context/` files (operator, business, team, priorities) are omitted — only schema
  READMEs remain.
- **No secrets.** `.env` is not included; copy `.env.example` and fill in your own keys.
- **Identities are placeholders.** All real names, clients, emails, links, and figures
  have been replaced with a generic cast (e.g. `Alex Doe`, `Acme`, `user@example.com`).
  Anything that looks like a person or company here is fake.
- **Personal sub-modules removed.** A personal job-search / résumé automation stack that
  was part of the original was dropped entirely.
- **Sample content.** The `birdseye.py` dashboard config and
  `.claude/skills/find-gap-leads/ICP-AND-OFFER.md` contain placeholder sample data, not
  the real pipeline or offer.

## Layout

```
CLAUDE.md          # how the assistant operates (start here)
README.md          # project overview
tools/             # deterministic Python scripts (the "main code")
workflows/         # step-by-step SOPs each skill follows
.claude/skills/    # skill definitions (SKILL.md per skill)
bot/               # Telegram bot server
data/              # state layer — schema only (gitignored)
context/           # grounding files — schema only (gitignored)
```

Start the tools with `python3 tools/<name>.py`; most print a `--help`.
