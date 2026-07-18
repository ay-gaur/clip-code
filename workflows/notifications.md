# Notifications — Workflow
*Created: 2026-03-25*

## Purpose

Monitor and manage CLIP's Telegram push channel — view push history, test connectivity, trigger manual pushes.

## WAT Chain

**Skill** → `.claude/skills/notifications/SKILL.md`
**Workflow** → `workflows/notifications.md` (this file)
**Tool** → `tools/notify.py`
**Data** → `data/push-log.json`

## Push signals and their cadences

| Signal | Script | Cadence | Cooldown |
|--------|--------|---------|---------|
| Email alert | `heartbeat_email.py` | every 30min | 4h per thread |
| Meeting prep | `calendar_watch.py` | every 30min | once per event/day |
| Heartbeat digest | `heartbeat.py` | every 6h | 6h |
| Pipeline alert | `heartbeat.py` | every 6h | 12h per contact |

## Steps

### 1. Status check
```bash
python3 tools/notify.py --status
```
Reads `data/push-log.json` and shows last 20 entries sorted by time.

### 2. Test connectivity
```bash
python3 tools/notify.py --test
```
Fires a live Telegram message. Confirms bot is alive.

### 3. Force heartbeat push
```bash
python3 tools/heartbeat.py --force-llm
```
Runs full heartbeat and pushes to Telegram, bypassing the 6h cooldown.

### 4. View raw push log
`data/push-log.json` — array of `{signal, key, sent_at}`.
Entries expire from cooldown logic; file grows unbounded (trim manually if needed).

## Edge cases

- If Telegram bot is down (cron @reboot died): `ps aux | grep telegram_bot` to check
- If pushes stopped: check `/tmp/clip_email_watch.log` and `/tmp/clip_cal_watch.log`
- To restart bot manually: `nohup python3 bot/telegram_bot_server.py &`
