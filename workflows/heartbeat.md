# Heartbeat Workflow

**Purpose:** Background intelligence engine — scans pipeline, leads, tasks, and subscriptions every 6h. Fires LLM synthesis when ≥2 signals detected. No email, no noise — surfaces at CEO session open.

---

## When to Run

- Automatically: every 6h via cron / n8n (once Railway is deployed)
- Manually: `python3 tools/heartbeat.py` at any time
- Dry run to inspect without writing: `python3 tools/heartbeat.py --dry-run`
- Force LLM even if <2 signals: `python3 tools/heartbeat.py --force-llm`

---

## What It Analyzes

| Analyzer | Signal Condition |
|----------|-----------------|
| Pipeline | Hot deals or active contacts with no contact in 5+ days |
| Leads | Unreviewed leads in queue (new or not reviewed in 3+ days) |
| Tasks | Any items in the Urgent section of `data/tasks.md` |
| Subscriptions | Any active subscription billing in the next 7 days |

---

## Signal Threshold

- **0 signals** → writes "no signals detected" to `data/ai-updates.md`, no LLM call
- **1 signal** → writes signal to `data/ai-updates.md`, no LLM call
- **≥2 signals** → writes signals + calls Claude Haiku to synthesize an insight

LLM used: `claude-haiku-4-5-20251001` (fast + cheap for synthesis tasks).
Future: swap to DeepSeek-V3 via OpenAI-compatible API (~10x cheaper).

---

## Outputs

| File | What's Written |
|------|---------------|
| `data/ai-updates.md` | Latest insight: timestamp, signals, LLM synthesis |
| `data/heartbeat.json` | Run history: last 30 runs with signal counts + LLM flag |
| `data/task-log.json` | Reflexion log entry via `log_entry.py` |

---

## How Insights Surface

The CEO skill reads `data/ai-updates.md` at session open. If there's a fresh insight (written since last session), it's surfaced in the opening context.

Alex can also ask: "What's the latest heartbeat?" to get the current `ai-updates.md` contents.

---

## Tuning

Edit thresholds in `tools/heartbeat.py`:

```python
STALE_PIPELINE_DAYS = 5      # pipeline stale threshold
LEAD_UNREVIEWED_DAYS = 3     # lead stale threshold
SUBSCRIPTION_ALERT_DAYS = 7  # subscription alert window
LLM_SIGNAL_THRESHOLD = 2     # fire LLM if this many signals detected
```

---

## Cron Schedule (target — pending Railway)

```
0 */6 * * *   python3 /clip/tools/heartbeat.py
```

Runs at: 00:00, 06:00, 12:00, 18:00 UTC (05:30, 11:30, 17:30, 23:30 IST).
