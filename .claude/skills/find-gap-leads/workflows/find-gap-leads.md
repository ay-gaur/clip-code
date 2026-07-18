# Workflow: find-gap-leads

SOP for finding early-stage Indian businesses that lack Acme's response+retention
layer, scoring them, and surfacing the best with ready outreach. You (the agent) orchestrate;
`tools/find_gap_leads.py` executes. $0 cost.

## Objective
Hand Alex a ranked, deduped list of prospects who genuinely NEED the product (early +
missing infra + can pay + likely to retain), each with a ready LinkedIn note — plus
separate Partner (consultant) and Audience (too-early) lists.

## Inputs
- `count` (default 20): how many new leads to find this run.
- `persona` (default `d2c`): one of `d2c`, `coach`, `consultant`.

## Steps

### 1. Pre-flight
- Confirm `TAVILY_API_KEY` + at least one of `GROQ_API_KEY`/`GEMINI_API_KEY` are set.
- If `GROQ_API_KEY` is missing, tell Alex once: "Add a free Groq key for better scoring +
  privacy; running on Gemini fallback for now." Don't block.
- If `APOLLO_API_KEY` is invalid, note enrichment will be skipped (LinkedIn-primary anyway).

### 2. Step A — discover + score (NO writes)
Run:
```
python3 tools/find_gap_leads.py --count <count> --persona <persona>
```
This discovers → detects stacks → scores → prints a ranked table → STOPS.

**Add `--render` for any real batch** (free accuracy win): renders each site with Playwright
before detection so JS-/tag-manager-injected stacks (Klaviyo, WhatsApp BSPs, loyalty) are seen —
the raw-HTML matcher misses these and reports false gaps. Add `--deep-detect` to also run the
ScrapeGraphAI+Groq LLM read (stack + founder name + products in one pass). Both are $0; see
SKILL.md "Detection modes" for setup. If `scrapegraphai` isn't installed, `--deep-detect`
falls back silently to (rendered) substring detect — never errors the run.

### 3. Checkpoint (human-in-the-loop) — REQUIRED
- Show Alex the printed table: company, score, band, persona, missing infra.
- Call out the priority + shortlist names and what each is missing.
- Ask: "Enrich the surfaced leads (Apollo), draft LinkedIn notes, and write the Gap Leads sheet?"
- Do NOT proceed to Step B without a yes. (Enrichment touches Apollo quota + writes the sheet.)

### 4. Step B — enrich + draft + publish (after yes)
Run:
```
python3 tools/find_gap_leads.py --proceed
```
This enriches priority/shortlist via Apollo, drafts a ≤300-char LinkedIn note per client lead,
writes a markdown dossier for priority leads, then writes the Gap Leads / Partners / Audience
sheet tabs + upserts data/leads.json + sends a Telegram summary.

### 5. Surface results to Alex
- Read the priority dossiers from `data/gap_runs/<run>/drafts/*.md` and show them inline.
- For each priority/shortlist lead, show the drafted LinkedIn note (already voice-linted + hedged).
- Remind Alex: leads flagged `reply_speed_test_pending` should get a manual reply-speed test
  (DM them, time the response) before outreach. The skill never sends — Alex sends.

### 6. Log
```
python3 tools/log_entry.py --skill find-gap-leads --action proceed --note "<N> clients, <P> priority; <A> audience; <Pr> partners"
```

## Edge cases & lessons
- **No domain for a candidate** → it can't be stack-audited; it scores low on missing-infra and
  is usually a watchlist/drop. The discoverer already does a follow-up search to resolve domains.
- **Mature/funded brand that still lacks the layer** (e.g. it has money but no BSP) → legitimately
  scores shortlist. That's correct ("can pay + needs help"), not a bug. Alex decides.
- **Detection false-negative** (tool loaded via GTM/server-side) → the ~70-80% accuracy caveat of
  the default raw-HTML matcher. **Mitigate with `--render`** (free Playwright render makes injected
  stacks visible) or `--deep-detect` (rendered LLM read). Still confirm the gap before any hard
  claim — notes are auto-hedged for this reason.
- **Re-running** is safe + resumable: per-lead state is cached under `data/gap_runs/<run>/`;
  leads.json is an upsert (no duplicates). Use `--new-run` to force a fresh batch.
- **Dry run** (`--dry-run`) runs the whole pipeline with zero Sheet/JSON writes — use it to sanity
  check before a live batch.

## Anti-goals
- Do not auto-send connection requests or DMs from this skill.
- Do not pitch consultants as clients — they go to the Partners list.
- Do not make public "you don't have X" claims off a single automated scan.
