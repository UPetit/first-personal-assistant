# Mobile Responsive Design — Kore Dashboard

**Date:** 2026-03-19
**Status:** Approved

## Overview

Make the Kore web dashboard usable on mobile and tablet screens. The current UI has a fixed 200px sidebar and multi-column grids that break on narrow screens. No responsive CSS exists today.

## Decisions

- **Mobile nav pattern:** Bottom tab bar (sidebar hidden on mobile, fixed bottom nav with icons + labels)
- **Layout strategy:** Smart collapse — 2-column on tablet (480–767px), 1-column on phone (<480px)
- **Implementation approach:** CSS-only (media queries in `index.css` + small JSX addition in `App.jsx`)

## Breakpoints

Two `max-width` media query blocks are written. The tablet block (`max-width: 767px`) sets the base mobile rules; the phone block (`max-width: 479px`) overrides specific properties for narrow screens. They overlap intentionally — phone screens receive both blocks, with the phone block winning where they conflict.

| Name    | CSS rule             | Target                          |
|---------|----------------------|---------------------------------|
| desktop | (no query, default)  | Current layout unchanged        |
| tablet  | `max-width: 767px`   | 2-col grids, bottom nav visible |
| phone   | `max-width: 479px`   | 1-col grids                     |

## Navigation (≤ 767px)

- Sidebar (`.sb`) hidden via `display: none`
- New `<nav className="bottom-nav">` added to `App.jsx` — fixed to bottom, full viewport width, 60px tall, `z-index: 100`
- Both `MAIN_NAV` and `SYSTEM_NAV` arrays merged into a single flat list of 6 items; section labels ("Main", "System") dropped — they have no place in a tab bar
- Each tab: icon + label; active tab gets `background: rgba(129,140,248,0.13)` and `color: #c7d2fe`
- The `nav-badge` ("live") on Logs is dropped in the bottom nav — the text pill doesn't fit the 60px bar (accepted trade-off; a dot indicator can be added in a follow-up)
- The sidebar footer status indicator ("Agent online" + status dot) disappears with the sidebar on mobile (accepted regression for v1; can be added to bottom nav in a follow-up)
- `.main` padding-bottom increases to 72px to prevent content hiding behind the tab bar

## Scroll model (≤ 767px)

The current layout locks scrolling to `.main` via `body { overflow: hidden }` and `#root { height: 100vh; overflow: hidden }`. On mobile this must change inside the media query:

- `body { overflow: auto }`
- `#root { height: auto; overflow: visible; min-height: 100vh }` — `min-height: 100vh` keeps the background gradient covering the full viewport
- `.main { overflow-y: visible }` — scroll is now on the document, not the inner container

## Grid Collapses

| Element          | Desktop    | `max-width: 767px` | `max-width: 479px` |
|------------------|------------|--------------------|--------------------|
| `.stats-grid`    | 4 cols     | 2 cols             | 1 col              |
| `.two-col`       | 1.6fr 1fr  | 1 col              | 1 col              |
| `.agents-grid`   | 2 cols     | 2 cols             | 1 col              |
| `.settings-grid` | 2 cols     | 2 cols             | 1 col              |

## Other Adjustments (≤ 767px)

- `.main` padding reduces from `24px 28px` → `16px` to reclaim horizontal space
- `.job-card`: the cron tag, next-run time, and action buttons are wrapped in a new `<div className="job-card-meta">` in `Jobs.jsx`. On mobile this wrapper gets `width: 100%` so it breaks to a second line below the job icon + info group
- `.logs-toolbar` already has `flex-wrap: wrap` — no change needed

## Files Changed

| File | Change |
|------|--------|
| `ui/src/App.jsx` | Add `<nav className="bottom-nav">` with all 6 nav items (merged `MAIN_NAV` + `SYSTEM_NAV`) using `NavLink` |
| `ui/src/pages/Jobs.jsx` | Wrap `.job-cron-tag`, `.job-next`, `.job-actions` in `<div className="job-card-meta">` |
| `ui/src/index.css` | Add `.bottom-nav` / `.bottom-nav-item` styles; add `@media (max-width: 767px)` and `@media (max-width: 479px)` blocks |
| `ui/index.html` | Ensure `<meta name="viewport" content="width=device-width, initial-scale=1">` is present |
| `src/kore/ui/static/` | Rebuild via `npm run build` in `ui/` |

## Out of Scope

- Touch gestures (swipe to open drawer)
- PWA / installable app manifest
- Dark/light mode toggle
- Live badge / status dot in bottom nav (deferred)
- Any backend changes
