# context/ — who the assistant works for

CLIP reads these Markdown files to ground personal, strategic, and business responses
(see `CLAUDE.md`). **The real files are private and omitted from this shared snapshot**
(`context/*` is gitignored). Create your own to drive the assistant:

| File | What it holds |
|------|---------------|
| `me.md` | Who the operator is — background, working style, preferences |
| `work.md` | The business and its clients |
| `team.md` | Who's on the team and who owns what |
| `priorities.md` | Current goals, operating directive, and constraints |
| `pitch.md` / `icp.md` | Positioning and ideal-customer definition |

Keep these short and factual — they are loaded into context on every relevant request.
