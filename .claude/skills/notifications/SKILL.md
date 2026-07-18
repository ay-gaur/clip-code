---
name: notifications
description: Manage CLIP's Telegram push notifications — view push log, test connectivity, check what was sent and when, silence or re-enable alerts. Use this skill when user says "test notification", "did you send me anything", "show push log", "check notifications", "test telegram", "what alerts fired", "notification status". Trigger on /notifications.
---

# Notifications

Manages and monitors CLIP's Telegram push channel. View what was pushed, when, and test connectivity.

## How to run this skill

Follow `workflows/notifications.md` exactly.

## Steps

### View push log
```bash
python3 tools/notify.py --status
```
Shows last 20 pushes from `data/push-log.json` — signal type, key, when sent.

### Test Telegram connectivity
```bash
python3 tools/notify.py --test
```
Sends "CLIP online. Push working." to Telegram. Confirms bot + token are alive.

### Check what's monitoring (cron status)
Show current cron schedule for autonomous monitoring:
- Every 30min: `heartbeat_email.py` (unanswered emails)
- Every 30min: `calendar_watch.py` (meeting prep at 30min window)
- Every 6h: `heartbeat.py` (full pipeline + tasks + LLM synthesis)
- @reboot: `telegram_bot_server.py` (bidirectional commands)

### Force a heartbeat push
```bash
python3 tools/heartbeat.py --force-llm
```
Runs full heartbeat immediately, pushes synthesis to Telegram regardless of cooldown.

### Mute / Unmute
Currently not automated — Alex controls this by replying to the bot or ignoring pushes.
Future: add `CLIP_NOTIFY_MUTED=true` to `.env` to suppress all pushes.

## Output style

- Show timestamps in IST
- Flag signals that fired recently (last 4h)
- Group by signal type: email_alert, heartbeat, meeting_prep, pipeline_alert

## Reflexion log

```bash
python3 tools/log_entry.py --skill notifications --action [status|test|force] --note "SUMMARY"
```
