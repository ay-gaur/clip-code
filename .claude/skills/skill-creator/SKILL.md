---
name: skill-creator
description: Create new skills, modify and improve existing skills, and measure skill performance. Use when users want to create a skill from scratch, update or optimize an existing skill, run evals to test a skill, benchmark skill performance with variance analysis, or optimize a skill's description for better triggering accuracy.
---

# Skill Creator

You build, improve, and measure CLIP skills. You are the tool CLIP uses to grow itself.

---

## Modes

### 1. Create a new skill

When Alex asks to build a new skill:

1. Read `CLAUDE.md` and `tools/ceo_router.py` to understand the skill registry
2. Check `tools/` for any existing tool that could be reused
3. Draft the skill following this structure:
   - `SKILL.md` → `.claude/skills/<name>/SKILL.md`
   - Tool script (if needed) → `tools/<name>.py`
   - Workflow → `workflows/<name>.md`
4. Follow the WAT framework (Skill → Workflow → Tool)
5. Write at least 3 eval cases: smoke test, happy path, edge case
6. Update `data/skill-registry.json` with the new skill entry

**Skill template:**
```markdown
---
name: <kebab-case>
description: <one sentence — used for routing. Include trigger phrases.>
---

# <Skill Name>

[What this skill does in 1-2 sentences.]

## How to run this skill

Follow `workflows/<name>.md` exactly.

## Output style

[How responses should look]

## Reflexion log

python3 tools/log_entry.py --skill <name> --action <action> --note "SUMMARY"
```

---

### 2. Modify an existing skill

When Alex asks to update a skill:

1. Read the current `SKILL.md` for that skill
2. Read the current workflow and tool (if any)
3. Make the change surgically — don't rewrite what isn't broken
4. Update the reflexion log note to reflect the change
5. If the change is significant, add a new eval case covering the new behavior

---

### 3. Run evals

When Alex asks to test or benchmark a skill:

```bash
python3 tools/skill_eval.py --list <skill-name>    # see what cases exist
python3 tools/skill_eval.py --report <skill-name>  # show structured report
python3 tools/skill_eval.py --add <skill-name>     # add a new case
```

Then manually test each case by triggering the skill behavior and comparing against expected behavior.

**Variance analysis:** For any case that's borderline or edge-case, run it 3x. If outputs differ meaningfully across runs, flag it — the skill description or workflow likely needs tightening.

**Pass rate target:** ≥90% before shipping a new or modified skill.

---

### 4. Optimize skill description (trigger accuracy)

The skill `description` field in SKILL.md frontmatter is what Claude Code uses to match user intent to a skill. If a skill isn't triggering reliably:

1. Look at what phrases aren't matching
2. Add those phrases explicitly to the description
3. Remove vague terms that could cause false positives
4. Test by saying those phrases in a new session

**Good description structure:**
```
Use this skill when [user types/asks] X, Y, Z. Trigger on /skill-name or [list of natural language variants].
```

---

## Eval data location

All eval cases live in `data/skill-evals/<skill-name>.json`.

---

## Skill registry

After creating or modifying a skill, update `data/skill-registry.json`:
```bash
python3 tools/ceo_router.py   # verify the skill appears in registry
```

If the skill isn't in the registry, add it manually to `data/skill-registry.json`.

---

## Reflexion log

```
python3 tools/log_entry.py --skill skill-creator --action [create|modify|eval|optimize] --note "SUMMARY"
```

SUMMARY = skill name + what changed + eval result (e.g. "Created lead-scan v2, 8/9 evals passing").
