# Workflow: swipe-scan

**Objective:** Find the highest-performing content by other creators across Meta Ads, X, Reddit, and LinkedIn, score it by a per-platform proxy, and hand the winners to the `/content` skill to rebuild as Alex's own scripts + posts.

**Inputs:** a niche / keyword / competitor (e.g. "AI automation agency"), optional country + min-days
**Outputs:** `data/swipe_intel.json` (scored winners) → consumed by `/content`
**Data files:** `data/swipe_intel.json`
**Tools:** `tools/swipe_scan.py`, `tools/log_entry.py`

> There is no real ROI data for ads. "Winning" is a proxy: Meta Ads = days-running + variant count; X = likes+reposts+replies; Reddit = upvotes+comments; LinkedIn = reactions+comments. Always present it as a proxy.

---

## Step 0 — Credentials (one-time)

- **Apify (meta_ads / x / linkedin):** apify.com → Settings → Integrations → API token → add `APIFY_TOKEN=...` to `.env`. Free tier gives ~$5/mo credit.
- **Reddit (free path):** reddit.com/prefs/apps → create app (type "script") → add `REDDIT_CLIENT_ID=...` and `REDDIT_CLIENT_SECRET=...` to `.env`. Without these, Reddit falls back to Apify.
- Actor slugs in `swipe_scan.py` are starting guesses. Confirm in the Apify Store; override via `APIFY_ACTOR_META_ADS` / `_X` / `_LINKEDIN` / `_REDDIT` in `.env` if different.

## Step 1 — Confirm cost (paid sources only)

`meta_ads`, `x`, `linkedin` spend Apify credit. Tell Alex the source(s) + item cap (`--limit`), get a yes, then run. Reddit via a Reddit app is free.

## Step 2 — Run the scan

```bash
python3 tools/swipe_scan.py --source meta_ads --query "AI automation agency" --country US --min-days 30 --limit 15
python3 tools/swipe_scan.py --source reddit  --query "replace your VA"
python3 tools/swipe_scan.py --source all     --query "automation agency" --limit 12
```

**First real Apify run for a source:** add `--raw` to dump the actor's raw schema. Map any unmatched fields into that source's parser in `swipe_scan.py`, then re-run without `--raw`.

## Step 3 — Hand off to /content

The tool only gathers + scores. Invoke `/content` with seed path (d): it reads `data/swipe_intel.json`, extracts the hook/angle/offer pattern from each winner, and rebuilds it in Alex's voice as the swipe-to-script bundle (hook ×2, angle, primary text, CTA, LinkedIn/X/Reddit posts, reel script). Draft-only. Pattern, never plagiarism.

## Step 4 — Log

```bash
python3 tools/log_entry.py --skill content --action swipe-scan --note "SUMMARY (query, sources, # winners)"
```

---

## Learnings

- **Reddit's unauthenticated `.json` endpoints 403** as of 2024+. Must use a Reddit app (OAuth) or Apify. Confirmed 31 May 2026.
- Apify runs the browser in their cloud — nothing heavy installs locally (matters on a near-full disk).
- Keep `--limit` low (10-15) to bound Apify cost; raise only when a query proves useful.
