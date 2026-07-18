# CLIP OS — Roadmap
*Last updated: 2026-03-25*

> **History lives in git.** `git log --oneline --decorate` shows every phase milestone.
> This document is forward-looking only — what's next, what's blocked, and why.

---

## Where We Are

```
phase-1-complete  →  db7fa03  CLIP OS v1.0 — 11 skills, 18 tools, full system
phase-2-complete  →  4415220  lead scan upgrade, subscription tracker, roadmap
phase-3-complete  →  (tagged) heartbeat + email briefs + Google Workspace + Calendar
phase-4-complete  →  (current) Telegram Jarvis mode — push + voice + bidirectional bot
```

---

## Phase 3 — COMPLETE ✅

- [x] `tools/heartbeat.py` — background intelligence every 6h
- [x] Wire heartbeat into CEO session-open (`ai-updates.md` → session brief)
- [x] `skill-creator` skill — SKILL.md + `tools/skill_eval.py` + `workflows/skill-creator.md`
- [x] `tools/send_morning_brief.py` — automated daily email brief (9am IST)
- [x] `tools/send_weekly_brief.py` — automated weekly email brief (Monday 9am IST)
- [x] macOS cron jobs — heartbeat (6h), morning brief (daily), weekly brief (Mon)
- [x] Google Workspace MCP connected to user@example.com exclusively
- [x] DKIM verified for acmestudio.com
- [x] Gmail App Password + SMTP delivery live
- [x] Google Calendar API live in morning brief (`tools/fetch_calendar.py`)

---

## Phase 4 — Jarvis Mode: Telegram + Voice — COMPLETE ✅

### Phase 4a: Infrastructure fixes
- [x] `tavily-python`, `google-api-python-client`, `google-auth-*` added to requirements.txt
- [x] `proposals/` directory created
- [x] All cron jobs fixed (python path: `/opt/homebrew/bin/python3`)
- [x] Data sync cron: `*/30 * * * *` → `git push data/` — live

### Phase 4b: Telegram push channel
- [x] `tools/notify.py` — Telegram push primitive with dedup (`data/push-log.json`)
- [x] `tools/heartbeat.py` — wired to push Telegram digest after LLM synthesis
- [x] `python3 tools/notify.py --test` — connectivity check live
- [x] `python3 tools/notify.py --status` — push log viewer

### Phase 5a: Multi-cadence heartbeat
- [x] `tools/heartbeat_email.py` — unanswered email watcher (30min cron)
- [x] `tools/calendar_watch.py` — meeting prep watcher (30min cron, fires at 25-35min window)
- [x] Crontab updated: email watch + calendar watch + data sync

### Phase 5b: Bidirectional Telegram bot
- [x] `bot/telegram_bot_server.py` — pure requests long-polling, no async library
- [x] Commands: `/brief`, `/tasks`, `/done`, `/snooze`, `/pipeline`, `/ok`, `/skip`, `/help`
- [x] Plain text → routed to Claude Haiku for intelligent response
- [x] `@reboot` crontab entry with auto-restart loop
- [x] Security: only responds to `TELEGRAM_CHAT_ID`

### Phase 5c: Voice support
- [x] Voice messages → `faster-whisper` STT (local, no API key)
- [x] Transcript → slash command routing OR Claude Haiku response
- [x] Response → `gTTS` TTS → audio sent back as Telegram audio message
- [x] `faster-whisper` + `gTTS` added to requirements.txt

### Phase 5d: Skill health system
- [x] `tools/skill_creator.py` — WAT scaffold generator (SKILL.md + workflow + tool stub + registry)
- [x] `tools/skill_audit.py` — weekly WAT compliance + skill health report
- [x] `notifications` skill — surfaces push log, test, force-heartbeat via CLIP session
- [x] CEO skill updated — heartbeat freshness check on session open
- [x] Weekly skill audit cron: Mondays 9:30am IST → Telegram push if issues

---

## Autonomous Schedule — LIVE ✅

| Time | Job | Log |
|------|-----|-----|
| Daily 9:00 AM IST | Morning Brief → email | `/tmp/clip_morning.log` |
| Monday 9:00 AM IST | Weekly Full Brief → email | `/tmp/clip_weekly.log` |
| Monday 9:30 AM IST | Skill Audit → Telegram if issues | `/tmp/clip_skill_audit.log` |
| Every 6h | Heartbeat → ai-updates.md + Telegram | `/tmp/clip_heartbeat.log` |
| Every 30min | Email watch → Telegram if unanswered | `/tmp/clip_email_watch.log` |
| Every 30min | Calendar watch → Telegram at 30min | `/tmp/clip_cal_watch.log` |
| Every 30min | Data sync → git push data/ | `/tmp/clip_datasync.log` |
| @reboot | Telegram bot (auto-restart) | `/tmp/clip_telegram_bot.log` |

---

## Phase 5 — Obsidian + NotebookLM *(Q3 2026)*

- Read/write Obsidian vault → sync CLIP memory to notes
- NotebookLM deep research pipeline for opportunity scanning
- Unified knowledge base across CLIP + Obsidian
- *When to start: when data/ has 50+ contacts, 6+ months of meeting logs*

## Phase 6 — WhatsApp Team Integration *(last)*

- Analyse team chat → CLIP sends proactive nudges
- Trust ladder: confirm-required actions before autonomy
- Intentionally last — highest blast radius

## Phase 7 — Full Jarvis Mode *(vision)*

- CLIP watches everything 24/7, proactive surfacing without prompts
- Revenue tracking + invoicing automation
- Heartbeat evolves into full feedback loop with outcome learning
- Apollo.io key → full contact enrichment in outreach pipeline
- DeepSeek API → cost-optimized background LLM calls

---

## Integration Status

| Integration | Purpose | Status |
|-------------|---------|--------|
| Tavily API | Lead + opportunity web search | ✅ LIVE |
| Anthropic API | Claude reasoning + heartbeat synthesis + voice | ✅ LIVE |
| Gmail SMTP | Automated email delivery | ✅ LIVE |
| Google Calendar API | Live schedule in morning brief + meeting watch | ✅ LIVE |
| Google Workspace MCP | Gmail, Calendar (session-time) | ✅ LIVE |
| Gmail API (direct) | Heartbeat email signal reading | ✅ LIVE |
| Telegram Bot | Bidirectional commands + voice + push notifications | ✅ LIVE |
| faster-whisper | Local STT for Telegram voice messages | ✅ LIVE |
| gTTS | TTS audio replies for Telegram voice | ✅ LIVE |
| Apollo.io | Contact enrichment for outreach | 🔑 NEEDS KEY |
| DeepSeek API | Cost-optimized background LLM | 📅 PLANNED |
| Railway | Cloud 24/7 fallback (Mac-off resilience) | 📅 PLANNED |
| Obsidian | PKM — notes + knowledge graph | 📅 PHASE 5 |
| WhatsApp (team) | Proactive nudges | 📅 PHASE 6 |
