# Skills Page Design

**Date:** 2026-03-24
**Status:** Approved

## Overview

Add a Skills page to the Kore dashboard UI that displays built-in and workspace skills as a card grid, with dependency warnings for skills whose requirements are not met. Includes a Reload button to re-scan skill directories without restarting.

## Backend

### Wiring changes required

Two files need changes:

1. `server.py` — `create_app()` gains a `skill_registry=None` parameter and stores it as `app.state.skill_registry`.
2. `main.py` — the existing `create_app(...)` call gains `skill_registry=skill_registry` to pass the already-instantiated registry.

### New endpoint: `GET /api/skills`

Added to `src/kore/gateway/routes_api.py`.

**Response shape:**
```json
{
  "builtin": [SkillInfo],
  "user": [SkillInfo]
}
```

If `app.state.skill_registry` is `None`, return `{"builtin": [], "user": []}`.

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

- `active`: `true` when all bin and env var dependencies are satisfied.
  - Computed by calling `registry.check_dependencies(skill, available_tools=[])`. Passing an empty tools list means tool deps never block `active`; they are informational only.
- `missing`: list of specific unsatisfied bin/env dep names (empty when `active: true`).
  - `SkillRegistry.check_dependencies()` returns only a boolean; the missing list must be computed inline in the endpoint by iterating `skill.required_bins` (checking `shutil.which`) and `skill.required_env` (checking `os.environ.get`).

**Builtin vs user split:**
Skills are split using `skill.path.is_relative_to(registry.user_dir)` (note: `skill.path` is the full path to the `SKILL.md` file). Skills under `user_dir` are `user`; all others are `builtin`. The actual user dir defaults to `~/.kore/data/skills/`.

**Emoji fallback:**
If a skill's metadata has no `emoji` field, use `"✦"` as the default.

**Reload behaviour:**
The endpoint calls `registry.reload()` on every request so the client's Reload button (which simply re-fetches) always sees current skill directory state. This is intentional: Kore runs single-worker asyncio, so there is no concurrency concern with mutating registry state on a read endpoint.

## Frontend

### `App.jsx` changes

- Import `Skills` from `./pages/Skills.jsx`.
- Add to `SYSTEM_NAV`: `{ to: '/skills', label: 'Skills', icon: '✦' }` — between Agents and Memory.
- Add `<Route path="/skills" element={<Skills />} />` to the `<Routes>` block.
- `ALL_NAV` (used by the bottom nav) is derived from `[...MAIN_NAV, ...SYSTEM_NAV]` so Skills appears there automatically.

### `Skills.jsx`

- Fetches `GET /api/skills` on mount.
- Reload button in page header re-fetches the same endpoint.
- Two sections rendered in order: **Built-in** then **Workspace**.
- Each section uses a grid layout matching the Agents page (`.agents-grid`).
- Empty workspace section renders a hint: `Drop a SKILL.md into ~/.kore/data/skills/ to add your own`.

### Skill card (`SkillCard` component)

Each skill is rendered as a card with:
- **Header:** emoji + name
- **Description:** one-line text
- **Tags row:** `always-on` badge (cyan), tool requirement tags (indigo), bin/env requirement tags (indigo)
- **Warning row** (only when `active: false`): amber `⚠ missing: <dep>, <dep>` tag; card gets a subtle amber border tint (`.skill-card-warn`)

### CSS

New styles added to `index.css`:
- `.skill-card-warn` — amber border variant of `.card`
- `.skill-empty` — muted hint text for empty workspace section
- `.always-tag` — cyan badge for always-on skills

Reuses: `.card`, `.tool-tag`, `.agents-grid`, `.page-header`, `.page-title`, `.page-sub`, `.loading`.

## Tests

Per project convention, tests are mandatory alongside implementation. The following must be covered:

- `GET /api/skills` returns correct `builtin`/`user` split
- `active: false` and `missing` list computed correctly for a skill with an unsatisfied bin dep
- `active: true` when all deps are met
- Tool deps do not affect `active`
- Returns `{"builtin": [], "user": []}` when `skill_registry` is `None`
- `Skills.jsx`: renders loading state, skill cards, empty workspace hint, and warn card for inactive skill

## Constraints

- No install/delete actions in this version — read-only view.
- Dependency check for tools is informational only; only bins and env vars affect `active`.
