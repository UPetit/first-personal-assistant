# Mobile Responsive Design Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Kore dashboard work on mobile and tablet screens via a bottom tab bar nav and collapsing grid layouts.

**Architecture:** Add a `<nav className="bottom-nav">` element to `App.jsx` (visible only on mobile via CSS), wrap the job card meta children in a grouping div in `Jobs.jsx`, then add two `@media` blocks to `index.css` covering `max-width: 767px` (tablet) and `max-width: 479px` (phone). The desktop layout is untouched.

**Tech Stack:** React, Vite, plain CSS (no Tailwind), react-router-dom `NavLink`

---

## File Map

| File | Change |
|------|--------|
| `ui/src/App.jsx` | Add `<nav className="bottom-nav">` with all 6 nav items merged from `MAIN_NAV` + `SYSTEM_NAV` |
| `ui/src/pages/Jobs.jsx` | Wrap `.job-cron-tag`, `.job-next`, `.job-actions` in `<div className="job-card-meta">` |
| `ui/src/index.css` | Add `.bottom-nav` + `.bottom-nav-item` base styles; add two media query blocks |
| `ui/index.html` | No change needed — viewport meta tag already present |
| `src/kore/ui/static/` | Rebuilt by `npm run build` in final task |

---

## Task 1: Add job-card-meta wrapper in Jobs.jsx

**Files:**
- Modify: `ui/src/pages/Jobs.jsx:108-113`

The three trailing children of each `.job-card` (`job-cron-tag`, `job-next`, `job-actions`) need to be wrapped so CSS can push them to a second row on mobile.

- [ ] **Step 1: Wrap the three children**

In `ui/src/pages/Jobs.jsx`, replace the three sibling elements inside the `job-card` div:

```jsx
// Before (lines 108-113):
<span className="job-cron-tag">{job.schedule || '—'}</span>
<div className="job-next">{fmtNextRun(job.next_run)}</div>
<div className="job-actions">
  <span className="btn-run" onClick={() => run(job.id)}>▶ Run</span>
  <span className="btn-del" onClick={() => remove(job.id)}>✕</span>
</div>

// After:
<div className="job-card-meta">
  <span className="job-cron-tag">{job.schedule || '—'}</span>
  <div className="job-next">{fmtNextRun(job.next_run)}</div>
  <div className="job-actions">
    <span className="btn-run" onClick={() => run(job.id)}>▶ Run</span>
    <span className="btn-del" onClick={() => remove(job.id)}>✕</span>
  </div>
</div>
```

- [ ] **Step 2: Verify the desktop layout is unchanged**

Run the dev server and visit `/jobs`:
```bash
cd ui && npm run dev
```
Open `http://localhost:5173/jobs`. Job cards should look identical to before — the wrapper div has no styles yet so it has no visual effect. Confirm each card still shows icon, name/desc, cron tag, next time, and action buttons all on one row.

- [ ] **Step 3: Commit**

```bash
git add ui/src/pages/Jobs.jsx
git commit -m "refactor: wrap job-card meta children for responsive layout"
```

---

## Task 2: Add bottom nav to App.jsx

**Files:**
- Modify: `ui/src/App.jsx`

Add a `<nav className="bottom-nav">` that renders all 6 nav items as a flat list. It will be hidden on desktop via CSS (added in Task 3).

- [ ] **Step 1: Merge nav arrays and add the bottom nav element**

In `ui/src/App.jsx`, add a combined nav array and the bottom nav element:

```jsx
// Add after SYSTEM_NAV (line 19):
const ALL_NAV = [
  { to: '/',         label: 'Overview', icon: '⬡', end: true },
  { to: '/logs',     label: 'Logs',     icon: '≡' },
  { to: '/jobs',     label: 'Jobs',     icon: '⏱' },
  { to: '/agents',   label: 'Agents',   icon: '◈' },
  { to: '/memory',   label: 'Memory',   icon: '🧠' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
]
```

Then inside the `<BrowserRouter>` return, after the closing `</div>` of `.main` and before `</BrowserRouter>`, add:

```jsx
<nav className="bottom-nav">
  {ALL_NAV.map(({ to, label, icon, end }) => (
    <NavLink
      key={to}
      to={to}
      end={end}
      className={({ isActive }) => 'bottom-nav-item' + (isActive ? ' active' : '')}
    >
      <span className="bottom-nav-icon">{icon}</span>
      <span className="bottom-nav-label">{label}</span>
    </NavLink>
  ))}
</nav>
```

The full App return should look like:
```jsx
return (
  <ToastProvider>
    <BrowserRouter>
      <div className="sb"> ... </div>
      <div className="main"> ... </div>
      <nav className="bottom-nav">
        {ALL_NAV.map(...)}
      </nav>
    </BrowserRouter>
  </ToastProvider>
)
```

- [ ] **Step 2: Verify the bottom nav renders (unstyled)**

With the dev server running, open any page. You should see a row of 6 unstyled nav links appear below the main content area. They won't look right yet — that's expected. Confirm all 6 labels appear: Overview, Logs, Jobs, Agents, Memory, Settings.

- [ ] **Step 3: Commit**

```bash
git add ui/src/App.jsx
git commit -m "feat: add bottom nav element for mobile"
```

---

## Task 3: Add bottom nav styles and hide it on desktop

**Files:**
- Modify: `ui/src/index.css`

Style the bottom nav and hide it by default (desktop-first). The media queries in Task 4 will show it on mobile.

- [ ] **Step 1: Add bottom nav base styles to index.css**

Append the following after the existing `.sb-footer` block (around line 82):

```css
/* ── Bottom nav (mobile only — shown via media query) ── */
.bottom-nav {
  display: none;
  position: fixed;
  bottom: 0; left: 0; right: 0;
  height: 60px;
  background: rgba(5, 5, 16, 0.95);
  border-top: 1px solid rgba(255,255,255,0.07);
  z-index: 100;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}
.bottom-nav-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  color: rgba(255,255,255,0.32);
  text-decoration: none;
  font-size: 10px;
  transition: color 0.12s;
  user-select: none;
}
.bottom-nav-item:hover { color: rgba(255,255,255,0.6); }
.bottom-nav-item.active {
  background: rgba(129,140,248,0.13);
  color: #c7d2fe;
}
.bottom-nav-icon { font-size: 16px; line-height: 1; }
.bottom-nav-label { font-size: 9px; letter-spacing: 0.02em; }
```

- [ ] **Step 2: Verify bottom nav is still hidden on desktop**

With the dev server running, confirm the bottom nav is not visible at a normal desktop window width (≥ 768px). The page should look identical to before this task.

- [ ] **Step 3: Commit**

```bash
git add ui/src/index.css
git commit -m "style: add bottom nav base styles (hidden on desktop)"
```

---

## Task 4: Add responsive media queries

**Files:**
- Modify: `ui/src/index.css`

Add the two media query blocks that wire everything together. The `max-width: 767px` block handles tablet and phone; `max-width: 479px` overrides specific things for narrow phones.

- [ ] **Step 1: Add the tablet media query block**

Append to the end of `ui/src/index.css`:

```css
/* ══════════════════════════════════
   Responsive — tablet (≤ 767px)
   Covers both tablet and phone.
   Phone block below overrides where needed.
   ══════════════════════════════════ */
@media (max-width: 767px) {
  /* Layout */
  body { overflow: auto; }
  #root {
    flex-direction: column;
    height: auto;
    overflow: visible;
    min-height: 100vh;
  }

  /* Sidebar hidden, bottom nav shown */
  .sb { display: none; }
  .bottom-nav { display: flex; }

  /* Main content */
  .main {
    padding: 16px;
    padding-bottom: 72px; /* clear the fixed bottom nav */
    overflow-y: visible;
  }

  /* Stats: 4-col → 2-col */
  .stats-grid { grid-template-columns: repeat(2, 1fr); }

  /* Overview two-col → single col */
  .two-col { grid-template-columns: 1fr; }

  /* Job card meta wraps to second row */
  .job-card-meta {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
}
```

- [ ] **Step 2: Add the phone media query block**

Append immediately after (still in `index.css`):

```css
/* ══════════════════════════════════
   Responsive — phone (≤ 479px)
   Overrides the tablet block above.
   ══════════════════════════════════ */
@media (max-width: 479px) {
  /* Stats: 2-col → 1-col */
  .stats-grid { grid-template-columns: 1fr; }

  /* Agents: 2-col → 1-col */
  .agents-grid { grid-template-columns: 1fr; }

  /* Settings: 2-col → 1-col */
  .settings-grid { grid-template-columns: 1fr; }
}
```

- [ ] **Step 3: Manually test on mobile viewport**

In the browser with the dev server running, open DevTools and toggle device emulation (e.g. iPhone 12, 390px wide). Check each page:

| Page | What to verify |
|------|---------------|
| All pages | Sidebar gone, bottom tab bar visible, active tab highlighted |
| Overview | Stats show 2×2 grid (tablet) or stacked (phone); live logs + jobs stack vertically |
| Logs | Toolbar wraps cleanly; log entries readable |
| Jobs | Job cards wrap cron/next/actions to a second line on narrow screens |
| Agents | Cards stack to 1 col on phone |
| Memory | Memory items readable, form inputs full-width |
| Settings | Setting rows stack to 1 col on phone |

Navigate between tabs using the bottom nav — confirm routing works.

- [ ] **Step 4: Test at desktop width**

Resize back to ≥ 768px. Confirm:
- Sidebar is back
- Bottom nav is gone
- All grids are back to their original column counts
- No visual regressions

- [ ] **Step 5: Commit**

```bash
git add ui/src/index.css
git commit -m "feat: add responsive media queries for mobile and tablet"
```

---

## Task 5: Build and update static assets

**Files:**
- Modify: `src/kore/ui/static/` (generated by build)

- [ ] **Step 1: Build the production bundle**

```bash
cd ui && npm run build
```

Expected output: Vite builds successfully with no errors. New files appear in `src/kore/ui/static/assets/`.

- [ ] **Step 2: Verify the built files changed**

```bash
git diff --stat src/kore/ui/static/
```

You should see the JS and CSS assets have changed (new hashed filenames or modified content).

- [ ] **Step 3: Commit the built assets**

```bash
git add src/kore/ui/static/
git commit -m "build: rebuild static assets for mobile responsive UI"
```

---

## Verification Checklist

Before calling this done, manually verify:

- [ ] Bottom tab bar visible and functional on a 390px-wide viewport
- [ ] Active page highlighted in the bottom nav
- [ ] Desktop layout (≥ 768px) completely unchanged — sidebar, grids, all columns intact
- [ ] No horizontal scroll on any page at 390px width
- [ ] Job cards wrap cleanly on narrow screens
- [ ] Pages scroll vertically on mobile (not cut off)
