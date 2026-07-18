# Workflow: ceo

**Objective:** Route user intent to the right CLIP skill, or propose a buildable spec when no skill matches. Never a dead end.

**Inputs:** User message (natural language or `/ceo`)
**Outputs:** Route confirmation, skill invocation, or a structured spec proposal
**Data files:** `data/skill-registry.json`
**Tools:** `tools/ceo_router.py`, `tools/log_entry.py`, `tools/write_memory.py`

---

## Step 1 — Load the skill registry

```bash
python3 tools/ceo_router.py
```

This prints all shipped skills with their names and trigger summaries. Use this as the routing table.

---

## Step 2 — Classify the user's intent

Map the message to one of three outcomes:

| Outcome | Condition |
|---------|-----------|
| **Route** | Intent clearly matches a skill |
| **Propose spec** | No skill match |
| **Clarify** | Ambiguous (could match 2+ skills) |

**Known skill triggers (as of shipping):**
- `task-check` — tasks, to-dos, "what needs doing", add/remove tasks
- `pipeline-status` — pipeline, leads, prospects, clients, deal stages
- `morning-brief` — morning brief, daily summary, "what's on today"

---

## Step 3a — Route

Tell the user which skill handles their request and how to invoke it.

Format:
```
That's a [skill-name] request.
→ [exact command or natural language to trigger it]
```

Example:
```
That's a task-check request.
→ /task-check add: draft invoice for PackTech [urgent]
```

---

## Step 3b — Propose a spec (no match)

Use this template exactly — fill in all fields:

```
I don't have a skill for this yet. Here's what I'd build:

**Skill:** `[kebab-case-name]`
**Trigger:** [one sentence — when does this fire?]
**What it does:** [1–2 sentences on behavior]
**Tool needed:** `tools/[name].py` — [what the script does]
**Data:** [what file it reads/writes]

Want me to build this?
```

Be specific. If uncertain about data format or tool approach, say so. Vague specs don't get built.

---

## Step 3c — Clarify (ambiguous)

Ask one question. One. Don't list options, don't hedge — ask the smallest question that resolves the ambiguity.

Example: "Are you asking about your task list or your client pipeline?"

---

## Step 4 — Log (always)

```bash
python3 tools/log_entry.py --skill ceo --action [route|propose|clarify|status] --note "SUMMARY"
```

SUMMARY examples:
- `"routed to morning-brief — user asked for daily update"`
- `"proposed clean-inbox skill — no email skill exists"`
- `"status check — user typed /ceo with no args"`
- `"clarified ambiguous request — was pipeline not tasks"`

---

## Step 5 — Write memory (conditional)

Only if the interaction revealed something durable:

```bash
python3 tools/write_memory.py \
  --content "CONTENT" \
  --type [insight|preference|context|fact] \
  --tags "ceo,RELEVANT" \
  --source ceo
```

Skip this step for routine routing. Trigger it when:
- User reveals a new pattern or preference
- A gap in CLIP becomes clear
- The same request has been routed/missed multiple times (pattern)

---

## Edge cases

- **`/ceo` with no args:** Show the skill status overview (skill names + triggers). Don't run any data tools.
- **User asks to build a skill:** Treat as a spec proposal request — generate the spec, then ask "Want me to build this?"
- **User asks about CLIP itself:** Answer from context — don't route to a skill.
- **ceo_router.py fails or registry missing:** Fall back to the hardcoded skill list in Step 2. Log the error.

---

## What good looks like

- Routing is instant and confident. No "maybe this is task-check?"
- Specs are specific enough to hand off to a builder (human or Claude).
- Every session ends with a log entry. Memory written only when earned.
- Alex feels like he's talking to an intelligent system, not a help menu.

---

## Learning notes

*(Updated as edge cases are discovered)*

- Skill registry is the source of truth for what's shipped — keep it current when new skills ship
- CEO should never try to execute another skill's tool directly — route to the skill, don't impersonate it
