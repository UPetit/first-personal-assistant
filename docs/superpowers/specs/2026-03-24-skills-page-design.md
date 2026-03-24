# Skills Page Design

**Date:** 2026-03-24
**Status:** Approved

## Overview

Add a Skills page to the Kore dashboard UI that displays built-in and workspace skills as a card grid, with dependency warnings for skills whose requirements are not met. Includes a Reload button to re-scan skill directories without restarting.

## Backend

### New endpoint: `GET /api/skills`

Added to `src/kore/gateway/routes_api.py`.

**Response shape:**
```json
{
  "builtin": [SkillInfo],
  "user": [SkillInfo]
}
```

**SkillInfo fields:**
```json
{
  "name": "web-research",
  "description": "Search the web effectively and synthesize findings",
  "emoji": "🔍",
  "always_on": false,
  "required_tools": ["web_search", "scrape_url"],
  "required_bins": [],
  "required_env": [],
  "active": true,
  "missing": []
}
```

- `active`: `true` when all bin and env var dependencies are satisfied. Tool deps are informational only — tools are always available at runtime.
- `missing`: list of unsatisfied bin/env deps (empty when `active: true`).
- Skills are split by source: built-in (`skills/`) vs user/workspace (`~/.kore/workspace/skills/`).

**Wiring:**
- `skill_registry` stored in `app.state` in `server.py` and passed from `main.py`.
- The endpoint reads `registry.all_skills()`, splits by whether each skill's path is under the builtin dir, and runs `registry.check_dependencies()` per skill to compute `active` and `missing`.

## Frontend

### Navigation

`Skills` added to `SYSTEM_NAV` in `App.jsx`:
- Icon: `✦`
- Route: `/skills`
- Position: between Agents and Memory

### `Skills.jsx`

- Fetches `GET /api/skills` on mount.
- Reload button in page header re-fetches the same endpoint (no separate server-side reload needed — registry re-scans on each call).
- Two sections rendered in order: **Built-in** then **Workspace**.
- Each section uses a grid layout matching the Agents page (`.agents-grid`).
- Empty workspace section renders a hint: `Drop a SKILL.md into ~/.kore/workspace/skills/ to add your own`.

### Skill card

Each skill is rendered as a card (`SkillCard` component) with:
- **Header:** emoji + name
- **Description:** one-line text
- **Tags row:** `always-on` badge (cyan), tool requirement tags (indigo), bin/env requirement tags (indigo)
- **Warning row** (only when `active: false`): amber `⚠ missing: <dep>, <dep>` tag; card gets an amber border tint (`.skill-card-warn`)

### CSS

New styles added to `index.css`:
- `.skill-section-header` — section label (reuses `.card-title` style)
- `.skill-card-warn` — amber border variant of `.card`
- `.skill-empty` — muted hint text for empty workspace section
- `.always-tag` — cyan badge for always-on skills

Reuses: `.card`, `.tool-tag`, `.agents-grid`, `.page-header`, `.page-title`, `.page-sub`, `.loading`.

## Constraints

- No install/delete actions in this version — read-only view.
- Dependency check for tools is skipped (tools are always available); only bins and env vars affect `active`.
- The endpoint does not trigger a registry reload — it reads current state. The frontend Reload button simply re-fetches.
