# CLIP OS — Team Onboarding

Your personal CLIP instance. Takes ~15 minutes to set up.

---

## What you get

Your own CLIP assistant with:
- Task manager (your tasks, separate from the team)
- Pipeline / CRM view (shared data if you sync via git, local if you don't)
- Daily morning brief
- Gmail inbox triage
- Lead and opportunity intelligence

---

## Step 1: Prerequisites

Install Claude Code if you haven't:
```bash
npm install -g @anthropic-ai/claude-code
```

You need a Claude subscription (Pro or Max) at claude.ai.

---

## Step 2: Clone the repo

```bash
git clone https://github.com/[org]/clip-os.git
cd clip-os
```

---

## Step 3: Install Python dependencies

```bash
pip3 install -r requirements.txt
pip3 install tavily-python anthropic flask
```

---

## Step 4: Set up your .env

```bash
cp .env.example .env
```

Open `.env` and fill in your values. See `SETUP.md` for where to get each key.

At minimum you need:
- `ANTHROPIC_API_KEY` — for outreach email drafting
- `GMAIL_FROM` + `GMAIL_APP_PASSWORD` + `GMAIL_TO` — for email digests

---

## Step 5: Initialize your data files

Your data lives in `data/` (gitignored — stays on your machine only).

```bash
mkdir -p data
echo "# Tasks\n\n## Urgent\n\n## This Week\n\n## Backlog" > data/tasks.md
echo "[]" > data/pipeline.json
echo "[]" > data/contacts.json
echo "[]" > data/leads.json
echo "[]" > data/opportunities.json
echo "[]" > data/outreach_drafts.json
echo "" > data/schedule.md
echo "[]" > data/task-log.json
```

---

## Step 6: Test it works

```bash
python3 tools/morning_brief.py
python3 tools/write_tasks.py --action list
python3 tools/pipeline_status.py --action list
```

All three should run without errors.

---

## Step 7: Open Claude Code

```bash
claude
```

Type anything — CLIP will route it. Try:
- `what's on my plate?`
- `show my pipeline`
- `brief me`

---

## Notes

- **Your data is yours.** `data/` never gets committed to git. Your tasks and pipeline stay on your machine.
- **Skills are shared.** Any skill improvements Alex makes get pulled down with `git pull`.
- **Gmail MCP is optional.** For inbox triage, set up OAuth separately — see `SETUP.md` section 8.
- **Don't edit `data/` files directly.** Always go through CLIP or the Python tools.

---

## Questions?

Ask Alex or check `SETUP.md` for detailed setup steps per integration.
