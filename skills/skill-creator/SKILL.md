---
name: skill-creator
description: Create new SKILL.md files in the correct format for Kore and ClawHub compatibility
metadata: '{"kore":{"emoji":"🛠️","always":false,"requires":{"tools":["write_file"]}}}'
---

# Skill Creator Skill

## SKILL.md format

Every skill is a directory containing a `SKILL.md` file:

```
skills/<skill-name>/SKILL.md
```

The file starts with YAML frontmatter:

```yaml
---
name: skill-name                      # kebab-case, matches directory name
description: One-line summary         # shown to the agent in Level 1 summary
metadata: '{"kore":{"emoji":"🔧","always":false,"requires":{"tools":["tool_name"]}}}'
---
```

Metadata fields:
- `emoji` — shown in UI
- `always` — if `true`, full body loaded every turn (use sparingly)
- `requires.tools` — list of tool names this skill needs
- `requires.bins` — list of system binaries required (e.g. `["git"]`)
- `requires.env` — list of environment variables required

## Writing the body

- Use Markdown headings to organise sections.
- Write in imperative tone: "Search for...", "When X, do Y".
- Be specific — vague instructions produce vague behaviour.
- Include examples where format or output structure matters.
- Keep the body under 1,000 tokens for non-always-on skills.

## Process

1. Clarify the skill's name, purpose, required tools, and whether it should be always-on.
2. Draft the frontmatter.
3. Write the body using the structure above.
4. Use `write_file` to save to `data/skills/<skill-name>/SKILL.md`.
5. Confirm with the user.
