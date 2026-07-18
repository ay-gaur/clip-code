---
name: find-gap-leads
description: Alex's prospect-finder for Acme. Finds high-ticket SERVICE businesses (agency owners, coaches/consultants, B2B done-for-you founders) that lack a predictable client-acquisition system - referral-dependent, or running ads into a weak offer/funnel - the gap Acme's 60-Day Client Acquisition System fills. Scores 0-100 on ICP fit + ability-to-pay + gap, outputs ranked leads with ready outreach. Use when Alex says "find gap leads", "find leads", "who can we sell to", "find clients for Acme", "prospect agencies/coaches", or runs /find-gap-leads. ICP + offer locked in ICP-AND-OFFER.md (read it first). $0 cost (Tavily + Gemini/Groq + Meta Ad Library free tiers).
---

# find-gap-leads

**ICP + offer LOCKED 2026-06-12 — read `ICP-AND-OFFER.md` before sourcing anything.**

Finds high-ticket SERVICE businesses that genuinely NEED Acme's 60-Day Client Acquisition
System: agency owners, coaches/consultants, and B2B done-for-you founders who are great at delivery
but referral-dependent (or running ads into a weak offer/funnel with no sales process). Not
spray-and-pray — a qualification engine. The OLD D2C-product-brand ICP is RETIRED.

Follow `workflows/find-gap-leads.md` exactly.

## What it does (6 phases, $0)

1. **discover** — **Meta Ad Library via Apify** (primary): keyword-search India ads → unknown/early brands surface by language not fame, keyed off the ad's DESTINATION DOMAIN (defeats agency/proxy pages + fixes domain resolution). Brands running ads = ability-to-pay built in. Falls back to Tavily web search if no Apify token.
2. **detect** — fetch their site, signature-match the tech stack (BSP/email/subscription/loyalty/pixels)
3. **score** — hard gates (incl. a **funding/maturity gate**: funded/acquired/Shark-Tank/enterprise brands auto-drop to too_late) + weighted 0-100 rubric; LLM only for fuzzy persona/stage/retention
4. **(checkpoint)** — show Alex the ranked table BEFORE any enrichment or writes
5. **enrich + draft** — Apollo contact (surfaced bands only) + a ready ≤300-char LinkedIn note
6. **publish** — Gap Leads / Partners / Audience tabs + upsert leads.json + Telegram

**Recommended before outreach:** run the adversarial-verification workflow on the surfaced
leads (one skeptical agent per lead: confirms correct domain, true funding/stage, and that the
gap is real — not hidden behind a tag manager). This is the reliable pre-outreach gate; the
scanner's own funding gate is a cheap first filter, the agent pass is the authoritative one.
Proven necessary: in the first real run it correctly killed all 10 raw candidates (every one was
funded/established or a wrong-domain false positive).

## How to run

**Step A — discover + score (no writes yet):**
```
python3 tools/find_gap_leads.py --count 20 --persona d2c
```
Show Alex the printed table. Confirm before proceeding (enrichment touches Apollo).

**Step B — after Alex says go:**
```
python3 tools/find_gap_leads.py --proceed
```
Enriches surfaced leads, drafts LinkedIn notes, writes the Gap Leads sheet + leads.json.

Other flags: `--persona {d2c,coach,consultant}`, `--count N`, `--dry-run` (full run, no writes),
`--new-run` (fresh run), `--no-llm` (deterministic only).

### Detection modes (accuracy vs cost)

The default detector reads RAW HTML with substring matching (~70-80% accurate; blind to
stacks injected by Google Tag Manager / server-side). Two optional upgrades:

- `--render` — **FREE, recommended.** Renders each site with a headless browser (Playwright)
  before substring matching, so JS-/tag-manager-injected widgets (Klaviyo, WhatsApp BSPs,
  loyalty) become visible. No LLM, deterministic, ~$0. Catches false-negatives the raw read
  misses (proven: a brand that looked gap-positive actually ran Omnisend + Smile loyalty).
  Setup: `pip install playwright && playwright install chromium` (Playwright already present;
  the chromium binary is the only download).
- `--deep-detect` — renders **and** runs a ScrapeGraphAI + Groq LLM read per site (one pass
  → stack + founder name + founder social + products). Catches what regex can't and helps fill
  founder gaps. Still $0 (uses the free Groq key + open-source ScrapeGraphAI, NOT the paid
  hosted API). Heavier + slower; falls back silently to substring detect if `scrapegraphai`
  isn't installed.

  **Install (system Python is externally-managed → isolated venv):**
  ```
  python3 -m venv .venv-deepdetect
  .venv-deepdetect/bin/pip install scrapegraphai langchain-groq
  .venv-deepdetect/bin/python -m playwright install chromium
  ```
  Because scrapegraphai lives in that venv, **run the skill through the venv Python** to actually
  use deep detect:
  ```
  .venv-deepdetect/bin/python tools/find_gap_leads.py --count 20 --deep-detect --render
  ```
  Standalone test: `.venv-deepdetect/bin/python tools/gap_deep_detect.py --domain <site>`.
  (Running on system Python with `--deep-detect` is safe — it just prints "unavailable" and uses
  rendered/substring detect.) Caveats: the LLM read is non-deterministic and reads only the
  homepage, so founders on an /about page won't surface; treat it as additive signal, not gospel.

Rule of thumb: use `--render` for every real batch (free accuracy win, runs on system Python);
reach for `--deep-detect` (venv) when you also want founder names auto-extracted or suspect
GTM-hidden stacks on a shortlist.

## The buckets (nothing useful is discarded)

- **client** (scored ≥50) → Gap Leads sheet. Bands: priority ≥80, shortlist 65-79, watchlist 50-64.
- **partner** (consultants) → Partners sheet. They don't need the product; they refer who does.
- **audience** (too-early) → Audience sheet. Future clients + the audience for a low-ticket education layer.
- **drop** (already mature / has the full stack) → leads.json only.

## Setup gates (warn Alex if missing)

- `APIFY_API_TOKEN` — **primary discovery.** Free at apify.com (~$5/mo credits, no card). Powers the Meta Ad Library discovery. Without it, discovery falls back to Tavily web search (which surfaces funded/established brands — the documented failure mode), so this is strongly recommended.
- `GROQ_API_KEY` — present. No-data-training, 1000/day, used for scoring + drafting.
- `GEMINI_API_KEY` — present; used for the token-heavy discovery extraction + prose fallback.
- `TAVILY_API_KEY` — present. Used by the funding/maturity gate (per-lead funding lookup) + the Tavily discovery fallback.
- `APOLLO_API_KEY` — **currently returns 401 (invalid).** Email enrichment is skipped until refreshed. Not fatal: LinkedIn is the primary channel anyway (~50% of early founders are on Gmail/info@ regardless).
- ~~`META_AD_LIBRARY_TOKEN`~~ — **not used.** The official Meta /ads_archive API only returns political/issue ads, never commercial D2C. "Running ads" is known from the Apify discovery source instead.

## Honest limits (state these; don't oversell)

- **Tech detection is ~70-80% accurate by default** (raw-HTML substring match; blind to GTM/server-side-injected tools). `--render` lifts this materially for free; `--deep-detect` further. Either way, "no signature found" is probabilistic — outreach copy is auto-hedged ("from what I could see publicly"), NEVER a flat "you don't have X" claim. Always confirm a gap before any hard claim.
- **The skill never sends anything.** It drafts. Sending stays manual.
- **Shortlist/priority leads are flagged `reply_speed_test_pending`** — DM them and time the reply before outreach (the strongest "they need us" signal, not scriptable safely).
- **Scraping is polite** (real UA, robots best-effort, ≤3 pages, delay). LinkedIn is never scraped.

## Reflexion log
```
python3 tools/log_entry.py --skill find-gap-leads --action [scan|proceed] --note "SUMMARY"
```
