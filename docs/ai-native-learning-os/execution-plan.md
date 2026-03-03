# Execution Plan — AI-Native Learning OS

**Feature slug:** `ai-native-learning-os`
**Author:** Solution Architect
**Date:** 2026-03-01
**Status:** Approved for implementation

---

## 1. Work Breakdown Structure (WBS)

Each task is atomic: it targets a single file or a tightly coupled pair of files. Estimated effort is in engineer-days assuming a senior frontend developer familiar with React 19, Tailwind CSS 4, Framer Motion, and Zustand.

### Phase 0 — Dependency Verification

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P0-1 | Verify framer-motion + zustand installed | Confirm `framer-motion ^12.x` and `zustand ^5.x` appear in `frontend/package.json` dependencies (both already present as of 2026-03-01). Run `npm install` if lock file is out of sync. | 0.25d | None | package.json |
| P0-2 | Create `frontend/src/store/` directory | Confirm the `store/` subdirectory exists under `frontend/src/`. Create it if absent. | 0.1d | P0-1 | filesystem |
| P0-3 | Create `frontend/src/components/game/` directory | Confirm the `game/` subdirectory exists under `frontend/src/components/`. Create it if absent. | 0.1d | P0-1 | filesystem |

### Phase 1 — Foundation: Design System Tokens

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P1-1 | Add game CSS custom properties to `index.css` | Append a new `:root` block after line 103 of `frontend/src/index.css` containing all 18 new game tokens: `--node-locked`, `--node-available`, `--node-mastered`, `--node-weak`, `--glow-xs` through `--glow-lg`, `--xp-gold`, `--xp-glow`, `--adapt-excelling`, `--adapt-struggling`, `--adapt-slow`, `--adapt-bored`, `--spring-bounce`, `--spring-soft`. Full values in DLD Section 4.1.1. | 0.5d | P0-1 | `frontend/src/index.css` |
| P1-2 | Add game keyframes to `index.css` | Append seven new `@keyframes` blocks after the existing `@keyframes slideInUp` block: `node-pulse`, `node-flicker`, `xp-burst`, `fog-reveal`, `streak-fire`, `float`, `combo-flash`. Full definitions in DLD Section 4.1.2. | 0.5d | P1-1 | `frontend/src/index.css` |
| P1-3 | Add utility classes to `index.css` | Append twelve new utility class definitions after the existing `.fade-up` class: `.node-mastered`, `.node-locked`, `.node-available`, `.node-weak`, `.glass-panel`, `.xp-burst`, `.adaptive-excelling`, `.adaptive-struggling`, `.adaptive-slow`, `.adaptive-bored`, `.float-card` (with nth-child delay variants). Full definitions in DLD Section 4.1.3. | 0.5d | P1-2 | `frontend/src/index.css` |
| P1-4 | Visual smoke test of CSS tokens | Open any existing page in the browser. Using DevTools, verify that `getComputedStyle(document.documentElement).getPropertyValue('--xp-gold')` returns `#f59e0b`. Verify no existing visual regression across all four themes (default, pirate, astronaut, gamer). | 0.25d | P1-3 | browser / DevTools |

### Phase 2 — Foundation: Zustand Adaptive Store

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P2-1 | Implement `adaptiveStore.js` | Create `frontend/src/store/adaptiveStore.js` with the full Zustand store as specified in DLD Section 4.2 (Feature 2). State shape: `{ mode, xp, level, streak, streakBest, lastXpGain, burnoutScore }`. Actions: `awardXP`, `recordAnswer`, `detectMode`, `clearLastXpGain`. Module-level `cardTimeSamples` array for rolling card-time average (10-sample window). | 1.0d | P0-2 | `frontend/src/store/adaptiveStore.js` |
| P2-2 | Unit-test store logic in isolation | Open browser console, import the store, call `awardXP(90)` then `awardXP(20)` and verify `level === 2` and `xp === 10`. Call `recordAnswer(false, 5000)` three times and verify `burnoutScore === 60` and `streak === 0`. Call `recordAnswer(true, 3000)` and verify `streak === 1` and `burnoutScore === 50`. | 0.5d | P2-1 | browser console |

### Phase 3 — Foundation: Game Components

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P3-1 | Implement `GameBackground.jsx` | Create `frontend/src/components/game/GameBackground.jsx` as specified in DLD Section 4.3.1. Canvas element: `position: absolute; inset: 0; z-index: 0; pointer-events: none`. 120 particles initialized with random positions, radii 0.5–2.5px, slow drift velocities, opacity 0.2–0.8, colors alternating between `--color-primary` and `--color-accent` read via `getComputedStyle`. rAF loop with wrap-at-edges. ResizeObserver for canvas resize. Cleanup: `cancelAnimationFrame` + `ro.disconnect` on unmount. | 1.0d | P0-3, P1-1 | `frontend/src/components/game/GameBackground.jsx` |
| P3-2 | Implement `XPBurst.jsx` | Create `frontend/src/components/game/XPBurst.jsx` as specified in DLD Section 4.3.2. Uses `AnimatePresence` + `motion.div`. Subscribes to `lastXpGain` from store. When non-null: renders `+{lastXpGain} XP` with initial/animate/exit Framer Motion variants. Calls `clearLastXpGain` in `onAnimationComplete`. Key uses `Date.now()` to force re-mount on repeat gains. Positioned `absolute; bottom: 1.5rem; left: 50%; transform: translateX(-50%)`. | 0.5d | P0-3, P2-1 | `frontend/src/components/game/XPBurst.jsx` |
| P3-3 | Implement `StreakMeter.jsx` | Create `frontend/src/components/game/StreakMeter.jsx` as specified in DLD Section 4.3.3. Subscribes to `streak` from store. Renders flame emoji with `streak-fire` keyframe when `streak >= 3`, lightning bolt otherwise. `compact` prop: returns null when `streak === 0`. Color: `--xp-gold` when on fire, `--color-text-muted` otherwise. | 0.5d | P0-3, P2-1, P1-2 | `frontend/src/components/game/StreakMeter.jsx` |
| P3-4 | Implement `LevelBadge.jsx` | Create `frontend/src/components/game/LevelBadge.jsx` as specified in DLD Section 4.3.4. SVG ring: outer track (`--color-border`), progress arc (`--xp-gold`) with `strokeDasharray` calculated from `(xp / 100) * circumference`. SVG rotated -90deg so arc starts at 12 o'clock. Level number overlaid via absolutely-positioned `div`. `size` prop: `'sm'` (32px) or `'md'` (44px). Transition on `stroke-dasharray` via `--spring-soft`. | 0.5d | P0-3, P2-1 | `frontend/src/components/game/LevelBadge.jsx` |
| P3-5 | Implement `AdaptiveModeIndicator.jsx` | Create `frontend/src/components/game/AdaptiveModeIndicator.jsx` as specified in DLD Section 4.3.5. `MODE_CONFIG` lookup: EXCELLING (rocket, gold), STRUGGLING (target, red), SLOW (meditation, blue), BORED (lightning, purple), NORMAL (hidden). Returns null when `mode === 'NORMAL'`. Renders pill with icon + label, border + bg-tint matching mode color. `role="status"` for accessibility. | 0.5d | P0-3, P2-1 | `frontend/src/components/game/AdaptiveModeIndicator.jsx` |
| P3-6 | Smoke test all five game components | Create a temporary test harness page (or use Vite's browser console import). Render each component in isolation. Verify: GameBackground canvas fills parent and particles are visible; XPBurst appears and auto-dismisses when `lastXpGain` is set then cleared; StreakMeter shows fire animation at streak 3; LevelBadge arc advances with XP; AdaptiveModeIndicator shows/hides per mode. | 0.5d | P3-1 through P3-5 | browser |

### Phase 4 — Critical Bug Fix: AssistantPanel Sticky Positioning

**Priority: Highest within Stage 4. This task must be completed and deployed before any other enhancement work ships.**

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P4-1 | Fix AssistantPanel wrapper in `CardLearningView.jsx` | Locate the wrapper `div` that conditionally renders `<AssistantPanel />` in `CardLearningView.jsx`. Change its inline style to add: `position: 'sticky'`, `top: '70px'`, `alignSelf: 'flex-start'`, `height: 'calc(100vh - 86px)'`, `overflowY: 'auto'`. This ensures the panel stays in viewport during scroll. Root cause: `position: sticky` requires `align-self: flex-start` in a flex container; without it, the flex item stretches to the container height and sticky has no room to activate. | 0.5d | Phase 1, 2, 3 must NOT block this — it is independent | `frontend/src/components/learning/CardLearningView.jsx` |
| P4-2 | Fix panel height in `AssistantPanel.jsx` | In `AssistantPanel.jsx`, locate the root container div. Set its `height` to `calc(100vh - 86px)` and `overflowY: 'auto'`. This prevents the panel from growing taller than the viewport, which would defeat sticky behavior. | 0.25d | P4-1 | `frontend/src/components/learning/AssistantPanel.jsx` |
| P4-3 | Cross-theme sticky regression test | Manually verify the sticky fix works in all four themes at three viewport widths: 768px (tablet), 1024px (laptop), 1280px (desktop). Procedure: open a lesson, answer the first question to reveal the panel, then scroll down the card column. The AssistantPanel must remain in the upper portion of the viewport throughout scroll. Verify this in default, pirate, astronaut, and gamer themes. | 0.5d | P4-1, P4-2 | browser / DevTools |

### Phase 5 — AppShell Game HUD

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P5-1 | Upgrade AppShell nav to 64px glassmorphism HUD | In `AppShell.jsx`: change nav `height` from `58px` to `64px`. Apply glassmorphism: `backgroundColor: 'color-mix(in srgb, var(--color-surface) 85%, transparent)'`, `backdropFilter: 'blur(16px)'`, `WebkitBackdropFilter: 'blur(16px)'`. Add bottom adaptive glow line: a 2px bottom border that transitions between `--adapt-excelling`, `--adapt-struggling`, etc. based on current mode from `useAdaptiveStore`. | 0.75d | P2-1, P1-1 | `frontend/src/components/layout/AppShell.jsx` |
| P5-2 | Add XP strip + LevelBadge to AppShell center | Replace the existing center "Concept Map" pill in `AppShell.jsx` with a horizontal strip containing: `<LevelBadge size="sm" />`, a compact XP progress bar (width 120px, height 6px, gold fill, shows current xp/100 progress), and the "Concept Map" pill repositioned to the right of the strip. Subscribe to `xp` from `useAdaptiveStore`. | 0.75d | P5-1, P3-4 | `frontend/src/components/layout/AppShell.jsx` |
| P5-3 | Add StreakMeter to AppShell right section | Add `<StreakMeter compact />` before the student dropdown in the right section of `AppShell.jsx`. The streak meter is hidden when `streak === 0` (handled by `compact` prop logic in the component). | 0.25d | P5-1, P3-3 | `frontend/src/components/layout/AppShell.jsx` |
| P5-4 | Visual QA of AppShell HUD | Verify the HUD across all four themes. Check: glassmorphism is visible against page content when scrolled; LevelBadge arc is correctly sized at 32px; StreakMeter appears/disappears correctly; adaptive glow line changes color when mode changes (manually call `useAdaptiveStore.getState().detectMode(...)` in console to test). | 0.5d | P5-1 through P5-3 | browser |

### Phase 6 — WelcomePage Game World

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P6-1 | Add GameBackground to WelcomePage | In `WelcomePage.jsx`: wrap the page root `div` with `position: relative; overflow: hidden`. Render `<GameBackground />` as the first child inside that div. All existing content must be inside a child div with `position: relative; z-index: 1` to render above the canvas. | 0.5d | P3-1 | `frontend/src/pages/WelcomePage.jsx` |
| P6-2 | Apply `.float-card` animation to subject cards | Identify the subject selection cards or `StudentCard` components on WelcomePage. Apply the `.float-card` CSS class (defined in P1-3) to each card wrapper. The nth-child delay variants in CSS will automatically stagger the animation. | 0.5d | P1-3, P6-1 | `frontend/src/pages/WelcomePage.jsx` |
| P6-3 | Add player profile strip | Below the student picker / login form, add a compact profile strip showing: student avatar initial (first letter of name in a colored circle), student display name, and current `<LevelBadge size="sm" />`. This strip is only rendered when a student is already loaded in `StudentContext`. Wrap it in `position: relative; z-index: 1`. | 0.5d | P3-4, P6-1 | `frontend/src/pages/WelcomePage.jsx` |

### Phase 7 — ConceptMapPage Neural Map

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P7-1 | Add GameBackground to ConceptMapPage | In `ConceptMapPage.jsx`: apply `position: relative; overflow: hidden` to the page root. Render `<GameBackground />` as the first child. Ensure the Sigma graph container sits at `z-index: 1` or higher. | 0.5d | P3-1 | `frontend/src/pages/ConceptMapPage.jsx` |
| P7-2 | Apply node state CSS classes to Sigma graph | Investigate how Sigma renders node elements in the existing `ConceptMapPage.jsx`. Apply CSS class overrides based on mastery status: nodes present in `student_mastery` get `.node-mastered` (gold pulse); nodes whose prerequisites are not all mastered get `.node-locked` (grey blur); nodes below weak threshold get `.node-weak` (flicker). If Sigma does not expose DOM nodes directly, apply the effect to the surrounding legend or info panel elements instead, and document this as a known limitation. | 1.0d | P7-1, P1-3 | `frontend/src/pages/ConceptMapPage.jsx` |

### Phase 8 — CardLearningView Adaptive Modules

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P8-1 | Apply adaptive mode class overlay to card container | In `CardLearningView.jsx`: subscribe to `mode` from `useAdaptiveStore`. Compute a `modeClass` based on the current mode: `EXCELLING → 'adaptive-excelling'`, `STRUGGLING → 'adaptive-struggling'`, `SLOW → 'adaptive-slow'`, `BORED → 'adaptive-bored'`, `NORMAL → ''`. Apply `modeClass` to the card container `div` using the `className` prop (in addition to any existing className). | 0.5d | P4-1, P2-1, P1-3 | `frontend/src/components/learning/CardLearningView.jsx` |
| P8-2 | Integrate XPBurst into card correct-answer flow | In `CardLearningView.jsx`: import `useAdaptiveStore`. In the MCQ correct-answer handler, call `recordAnswer(true, elapsedMs)` then `awardXP(10)`. In the short-answer correct handler, call `recordAnswer(true, elapsedMs)` then `awardXP(5)`. In wrong-answer handlers, call `recordAnswer(false, elapsedMs)`. Render `<XPBurst />` inside the card container div (it is self-positioned and self-dismissing). | 0.75d | P8-1, P3-2, P2-1 | `frontend/src/components/learning/CardLearningView.jsx` |
| P8-3 | Add StreakMeter to card header | In `CardLearningView.jsx`: add `<StreakMeter compact />` to the right side of the card header section (next to the difficulty badge and card counter). The streak meter is hidden at zero streak by the `compact` prop. | 0.25d | P8-1, P3-3 | `frontend/src/components/learning/CardLearningView.jsx` |
| P8-4 | Add Framer Motion card entry animation | In `CardLearningView.jsx`: wrap the card content area in a Framer Motion `<motion.div>` with `key={currentCardIndex}` (forces re-mount on card change). Entry: `initial={{ opacity: 0, x: 40 }}`, `animate={{ opacity: 1, x: 0 }}`, `transition={{ type: 'spring', stiffness: 300, damping: 30 }}`. Import `motion` from `framer-motion`. Do NOT wrap the AssistantPanel wrapper in motion (it is sticky; motion would break sticky). | 0.5d | P8-1 | `frontend/src/components/learning/CardLearningView.jsx` |
| P8-5 | Wire `detectMode` from `AdaptiveSignalTracker` to store | In `CardLearningView.jsx` or the session's `AdaptiveSignalTracker` integration point: when a new learning profile arrives from the backend (via `SessionContext.learningProfileSummary`), extract the signal strings and call `useAdaptiveStore.getState().detectMode({ speed, comprehension, engagement })`. The profile summary string maps to: `'FAST_LEARNER'/'SPEED_LEARNER' → speed: FAST`; `'STRUGGLING'/'NEEDS_SUPPORT' → comprehension: STRUGGLING`; `'ENGAGED' → engagement: ENGAGED`; `'BORED'/'DISENGAGED' → engagement: BORED`. Document the mapping assumptions in a code comment. | 0.5d | P8-1, P2-1 | `frontend/src/components/learning/CardLearningView.jsx` |

### Phase 9 — AssistantPanel AI Companion Upgrades

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P9-1 | Add mode-colored header to AssistantPanel | In `AssistantPanel.jsx`: subscribe to `mode` from `useAdaptiveStore`. The panel header's background color transitions based on mode: `EXCELLING → var(--adapt-excelling)`, `STRUGGLING → var(--adapt-struggling)`, `SLOW → var(--adapt-slow)`, `BORED → var(--adapt-bored)`, `NORMAL → var(--color-primary)`. Apply via inline `backgroundColor` with a CSS `transition: background-color 0.4s ease`. | 0.5d | P4-2, P2-1 | `frontend/src/components/learning/AssistantPanel.jsx` |
| P9-2 | Add AnimatePresence message entry animations | In `AssistantPanel.jsx`: wrap the message list items with `AnimatePresence`. Each message `div` becomes a `<motion.div>` with `key={message.id}` (or array index), `initial={{ opacity: 0, y: 10 }}`, `animate={{ opacity: 1, y: 0 }}`, `exit={{ opacity: 0 }}`, `transition={{ duration: 0.2 }}`. Import `AnimatePresence, motion` from `framer-motion`. | 0.5d | P4-2 | `frontend/src/components/learning/AssistantPanel.jsx` |
| P9-3 | Add animated thinking dots | In `AssistantPanel.jsx`: when `assistLoading` is true, render a thinking indicator: three dots in a row (`<span>` elements), each with a `float` keyframe animation at 0.3s offset increments (already defined in P1-2). This replaces or supplements the existing `<Loader />` spinner. Ensure `aria-live="polite"` is on the container with label "ADA is thinking". | 0.5d | P4-2, P1-2 | `frontend/src/components/learning/AssistantPanel.jsx` |

### Phase 10 — StudentHistoryPage Achievement Layer

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P10-1 | Add mastery heatmap (7-day activity grid) | In `StudentHistoryPage.jsx`: derive a 7-day activity array from the existing `history` data (group card interactions by `created_at` date, count per day). Render a 7-column CSS grid where each cell is a 28x28px rounded square. Color intensity: 0 interactions = `--color-border`; 1-2 = `color-mix(in srgb, var(--color-primary) 30%, transparent)`; 3-5 = `color-mix(in srgb, var(--color-primary) 60%, transparent)`; 6+ = `var(--color-primary)`. Add `title` attribute to each cell showing the date and count. | 0.75d | None (uses existing history data) | `frontend/src/pages/StudentHistoryPage.jsx` |
| P10-2 | Add achievement badges row | In `StudentHistoryPage.jsx`: compute achievement status from history data. Render a horizontal scroll row of badge chips. Required badges: "First Answer" (first card interaction), "On Fire" (streak >= 5 in any session), "Consistent" (activity on 3+ consecutive days), "Mastery" (first concept mastered). Each badge: colored pill with emoji + label, opacity 0.3 if not yet earned (greyed-out locked badge). Derive from existing `history.interactions` array — no new API call required. | 0.75d | P10-1 | `frontend/src/pages/StudentHistoryPage.jsx` |
| P10-3 | Add level progression section | In `StudentHistoryPage.jsx`: add a section showing current XP level from `useAdaptiveStore` (session XP) alongside a "Total Sessions" count derived from history data. Render `<LevelBadge size="md" />` + "Level {level}" heading + a summary sentence: "You have completed {N} sessions and answered {M} questions." | 0.5d | P3-4, P2-1 | `frontend/src/pages/StudentHistoryPage.jsx` |

---

## 2. Phased Delivery Plan

### Phase 0 — Dependency Verification (Pre-flight)
**Goal:** Confirm framer-motion and zustand are installed and directory structure is ready.
**Duration:** 0.5 engineer-days
**Tasks:** P0-1, P0-2, P0-3
**DoD:** `npm install` completes without errors. `node_modules/framer-motion` and `node_modules/zustand` directories exist. `frontend/src/store/` and `frontend/src/components/game/` directories exist.

### Phase 1 — Foundation: Design System
**Goal:** Establish all CSS tokens, keyframes, and utility classes as the visual foundation that every other feature depends on.
**Duration:** 1.75 engineer-days
**Tasks:** P1-1, P1-2, P1-3, P1-4
**Blocks:** All subsequent phases depend on CSS tokens being present.

### Phase 2 — Foundation: Zustand Store
**Goal:** Ship the adaptive game state store so all downstream components have a stable API to consume.
**Duration:** 1.5 engineer-days
**Tasks:** P2-1, P2-2
**Blocks:** All game component integrations (Phases 4–10).

### Phase 3 — Foundation: Game Components
**Goal:** Build and smoke-test all five standalone game UI components.
**Duration:** 3.5 engineer-days
**Tasks:** P3-1 through P3-6
**Blocks:** AppShell HUD (Phase 5), WelcomePage (Phase 6), CardLearningView integrations (Phase 8), History (Phase 10).

### Phase 4 — Critical Bug Fix: AssistantPanel Sticky (HIGHEST PRIORITY)
**Goal:** Fix the AssistantPanel scroll-stickiness regression. This is the only user-facing regression in the current codebase. It ships independently and must not be held behind any game feature.
**Duration:** 1.25 engineer-days
**Tasks:** P4-1, P4-2, P4-3
**Note:** Phase 4 is parallel to Phases 1–3. It has no dependency on CSS tokens or game components. It should be committed and reviewed as a standalone PR before any other changes.

### Phase 5 — AppShell Game HUD
**Goal:** Replace the current nav bar with a 64px game HUD featuring glassmorphism, XP strip, LevelBadge, and StreakMeter.
**Duration:** 2.25 engineer-days
**Tasks:** P5-1, P5-2, P5-3, P5-4
**Depends on:** Phase 1 (CSS), Phase 2 (store), Phase 3 (LevelBadge, StreakMeter)

### Phase 6 — WelcomePage Game World
**Goal:** Add GameBackground particle canvas, floating island animations, and player profile strip to WelcomePage.
**Duration:** 1.5 engineer-days
**Tasks:** P6-1, P6-2, P6-3
**Depends on:** Phase 3 (GameBackground, LevelBadge)

### Phase 7 — ConceptMapPage Neural Map
**Goal:** Add GameBackground canvas behind the Sigma graph and apply node-state CSS classes to mastered/locked/weak nodes.
**Duration:** 1.5 engineer-days
**Tasks:** P7-1, P7-2
**Depends on:** Phase 3 (GameBackground), Phase 1 (node CSS classes)

### Phase 8 — CardLearningView Adaptive Modules
**Goal:** Wire adaptive mode overlays, XP gain, streak meter, card entry animation, and mode detection into the active learning view.
**Duration:** 2.5 engineer-days
**Tasks:** P8-1 through P8-5
**Depends on:** Phase 4 (sticky fix must be done first), Phase 2 (store), Phase 3 (XPBurst, StreakMeter)

### Phase 9 — AssistantPanel AI Companion Upgrades
**Goal:** Add mode-colored header, AnimatePresence message animations, and thinking dots to the AI companion panel.
**Duration:** 1.5 engineer-days
**Tasks:** P9-1, P9-2, P9-3
**Depends on:** Phase 4 (sticky fix), Phase 2 (store)

### Phase 10 — StudentHistoryPage Achievement Layer
**Goal:** Add mastery heatmap, achievement badges, and level progression to the history page.
**Duration:** 2.0 engineer-days
**Tasks:** P10-1, P10-2, P10-3
**Depends on:** Phase 2 (store), Phase 3 (LevelBadge)

---

## 3. Dependencies and Critical Path

### Dependency Map

```
P0-1 ──┬──► P0-2 ──► P2-1 ──► P2-2
        │                │
        │                ├──► P3-2 (XPBurst)
        │                ├──► P3-3 (StreakMeter)
        │                ├──► P3-4 (LevelBadge)
        │                ├──► P3-5 (AdaptiveModeIndicator)
        │                ├──► P5-1 ──► P5-2 ──► P5-3 ──► P5-4
        │                ├──► P8-1 ──► P8-2 ──► P8-3 ──► P8-4 ──► P8-5
        │                ├──► P9-1 ──► P9-2 ──► P9-3
        │                └──► P10-3
        │
        └──► P0-3 ──► P3-1 (GameBackground) ──► P6-1 ──► P6-2 ──► P6-3
                  │                          └──► P7-1 ──► P7-2
                  │
P1-1 ──► P1-2 ──► P1-3 ──► P1-4  (CSS foundation, blocks everything visually)
         │
         └──► P9-3 (thinking dots keyframe)

P4-1 ──► P4-2 ──► P4-3  (INDEPENDENT — no dependency on Phases 1-3)
  │
  └──► (must complete before P8-1, P9-1)
```

### Critical Path

The critical path for the full feature set is:

```
P0-1 → P1-1 → P1-2 → P1-3 → P2-1 → P3-4/P3-3 → P5-1 → P5-2 → P5-3 → P5-4
```

Total critical path duration: approximately **8 engineer-days** sequential.

### Parallelizable Work

The following work streams can proceed concurrently once their blockers clear:

| Stream A | Stream B | Stream C |
|----------|----------|----------|
| Phase 4 (Bug fix) — fully independent, ship first | Phase 1+2+3 (Foundation) | — |
| Phase 8+9 (Learning view) | Phase 6 (Welcome) | Phase 7 (Concept map) |
| Phase 10 (History) | Phase 5 (AppShell) | — |

With two engineers: Phase 4 (one engineer) + Phases 1-3 (one engineer) can run in parallel. Total elapsed time with 2 engineers: approximately **8-10 calendar days**.

### External Blockers

None. This feature has no external team dependencies. All changes are frontend-only. No backend API changes, no database migrations, no devops-engineer involvement required.

---

## 4. Definition of Done (DoD)

### Phase 0 DoD
- [ ] `npm install` completes without warnings or errors in `frontend/`
- [ ] `import { create } from 'zustand'` and `import { motion } from 'framer-motion'` resolve without error in a test file
- [ ] `frontend/src/store/` directory exists
- [ ] `frontend/src/components/game/` directory exists

### Phase 1 DoD (CSS Design System)
- [ ] All 18 new CSS custom properties are present in `index.css` under a `/* Game design tokens */` comment block
- [ ] All 7 keyframe animations (`node-pulse`, `node-flicker`, `xp-burst`, `fog-reveal`, `streak-fire`, `float`, `combo-flash`) are present in `index.css`
- [ ] All 12 utility classes are present in `index.css`
- [ ] No existing CSS declarations have been removed or modified
- [ ] DevTools confirms `--xp-gold` = `#f59e0b` across all four themes
- [ ] No visual regression on WelcomePage, ConceptMapPage, or LearningPage in any theme (manual check)

### Phase 2 DoD (Zustand Store)
- [ ] `frontend/src/store/adaptiveStore.js` exists and exports `useAdaptiveStore` as default
- [ ] Store initializes with `{ mode: 'NORMAL', xp: 0, level: 1, streak: 0, streakBest: 0, lastXpGain: null, burnoutScore: 0 }`
- [ ] `awardXP(90)` followed by `awardXP(20)` produces `{ level: 2, xp: 10 }` (verified in console)
- [ ] `recordAnswer(false, 5000)` x3 produces `{ burnoutScore: 60, streak: 0 }` (verified in console)
- [ ] `detectMode({ speed: 'FAST', comprehension: 'STRONG', engagement: 'ENGAGED' })` sets `mode === 'EXCELLING'`
- [ ] `clearLastXpGain()` sets `lastXpGain` to `null`

### Phase 3 DoD (Game Components)
- [ ] `GameBackground.jsx` renders a canvas with visible moving particles in all four themes; canvas resizes correctly on window resize; no memory leak (animRef cleared on unmount)
- [ ] `XPBurst.jsx` appears on screen when `lastXpGain` is set to a number, auto-dismisses after ~1.2s, and calls `clearLastXpGain` on complete; renders "+10 XP" correctly
- [ ] `StreakMeter.jsx` shows lightning at streak 0-2, fire emoji with animation at streak 3+, returns null when `compact && streak === 0`
- [ ] `LevelBadge.jsx` arc occupies the correct fraction of the ring for any XP value 0–99 (e.g., `xp=50` fills exactly half the arc); level number is centered and readable
- [ ] `AdaptiveModeIndicator.jsx` renders nothing at `NORMAL` mode; renders correct icon + label + color for each of the 4 active modes

### Phase 4 DoD (Sticky Fix — Critical)
- [ ] AssistantPanel is visible and remains in viewport top half after scrolling down 400px+ in the card column — verified in Chrome and Firefox
- [ ] Sticky behavior works at 768px, 1024px, and 1280px viewport widths
- [ ] Sticky behavior works in all four themes
- [ ] AssistantPanel still collapses (zero width) when `showAssistant === false` (existing behavior preserved)
- [ ] No layout regression in the two-column LearningPage layout (card column + assistant column)
- [ ] This fix is merged and deployed independently of all other changes

### Phase 5 DoD (AppShell HUD)
- [ ] Nav height is 64px (was 58px) — verified in DevTools
- [ ] Glassmorphism is visible when page content scrolls underneath nav: nav has `backdrop-filter: blur(16px)` applied
- [ ] `<LevelBadge size="sm" />` renders correctly in nav center at 32px diameter
- [ ] XP progress bar updates when `awardXP()` is called from console (live reactivity visible)
- [ ] `<StreakMeter compact />` is hidden at streak 0 and appears at streak 1
- [ ] Adaptive glow bottom line changes color when `detectMode` is called from console
- [ ] Student dropdown still works correctly (opens on click, closes on outside click, logout works)
- [ ] `StyleSwitcher` and `LanguageSelector` remain accessible in dropdown

### Phase 6 DoD (WelcomePage)
- [ ] GameBackground canvas visible behind page content (stars animating)
- [ ] Subject cards apply `.float-card` animation with visible vertical float motion
- [ ] nth-child stagger creates a clearly visible wave effect (cards do not all move in sync)
- [ ] Player profile strip renders correctly when a student is loaded (shows avatar initial, name, LevelBadge)
- [ ] Player profile strip is absent when no student is loaded
- [ ] All existing WelcomePage functionality works (student form, student picker, navigation to map)

### Phase 7 DoD (ConceptMapPage)
- [ ] GameBackground canvas visible behind Sigma graph; Sigma graph interaction is unaffected (pan, zoom, node click)
- [ ] Mastered concept nodes show a visual gold/amber distinction from unmastered nodes (via CSS class or Sigma styling)
- [ ] Locked nodes appear greyed/blurred or otherwise visually de-emphasized
- [ ] If Sigma node DOM access is not feasible, the limitation is documented in a code comment and the alternative approach (legend or info panel) is implemented
- [ ] All existing ConceptMapPage functionality works (graph renders, nodes are clickable, navigates to lesson)

### Phase 8 DoD (CardLearningView Adaptive Modules)
- [ ] Card container applies `.adaptive-excelling` class when `mode === 'EXCELLING'`; border color matches `--adapt-excelling`
- [ ] `awardXP(10)` is called on correct MCQ answer; `awardXP(5)` on correct short answer; `recordAnswer(false, ...)` on wrong answer
- [ ] XPBurst appears visibly after a correct answer and auto-dismisses
- [ ] StreakMeter in card header updates in real-time (no page reload required)
- [ ] Card entry animation fires on every card advance (slide-in from right)
- [ ] Animation does not fire on initial render of the same card (only on `currentCardIndex` change)
- [ ] `detectMode` is called with the correct signals when `learningProfileSummary` updates in SessionContext
- [ ] All existing card functionality works: MCQ selection, short-answer submission, card navigation, adaptive card loading, ceiling detection (409)

### Phase 9 DoD (AssistantPanel Companion)
- [ ] Panel header background color matches `--adapt-excelling` when mode is EXCELLING, etc.
- [ ] Color transition is smooth (0.4s ease), not instant
- [ ] New messages slide up with Framer Motion animation
- [ ] `assistLoading === true` shows animated thinking dots (3 dots with staggered `float` animation)
- [ ] `assistLoading === false` hides thinking dots and shows response
- [ ] `aria-live="polite"` is present on the thinking indicator for screen reader users
- [ ] All existing panel functionality works: message send, idle nudge timer, scroll-to-bottom

### Phase 10 DoD (History Enhancement)
- [ ] 7-day activity heatmap renders correctly with color-coded cells; 0-interaction days are clearly lighter
- [ ] Each cell has a `title` attribute with human-readable date + count (visible in browser tooltip on hover)
- [ ] Achievement badges row renders all 4 badges; unlocked badges are full opacity, locked badges are 30% opacity
- [ ] Level badge and progression summary text render correctly; level number matches current `useAdaptiveStore` level
- [ ] History page renders correctly when `history` is empty (no crashes, graceful empty state)
- [ ] All existing history functionality works (session grouping, sparkline chart, session arc display)

### Global DoD (Feature Complete)
- [ ] All phases above are individually done
- [ ] No `console.log` or `print()` statements in committed code
- [ ] All new React components are functional components (no class components)
- [ ] Framer Motion imports use named imports only (`import { motion, AnimatePresence } from 'framer-motion'`) — no default import
- [ ] Zustand store is consumed via selector (`useAdaptiveStore(s => s.xp)`) in all components — no full-store subscriptions that would trigger unnecessary re-renders
- [ ] `@media (prefers-reduced-motion: reduce)` disables all new CSS keyframe animations (verified in Chrome DevTools: Rendering > Emulate CSS media feature prefers-reduced-motion)
- [ ] Application builds without errors: `npm run build` in `frontend/` exits with code 0
- [ ] ESLint passes: `npm run lint` exits with code 0

---

## 5. Rollout Strategy

### Deployment Approach
This feature is entirely frontend-only with no backend changes. Deployment consists of building the Vite SPA bundle and serving the updated static files.

**Recommended approach: Feature-flag-free incremental merge**

Because XP and streak data are session-scoped (in-memory only, not persisted), there is no risk of data inconsistency during rollout. Each phase can be merged independently as a PR without affecting backend data integrity.

**PR structure recommendation:**
1. PR-1: Phase 4 only (AssistantPanel sticky fix) — highest priority, ship independently
2. PR-2: Phase 1 + 2 + 3 (Foundation: CSS + Store + Game Components) — no visible UI change for users until later phases import the components
3. PR-3: Phase 5 (AppShell HUD) — first visible game-world change for all logged-in users
4. PR-4: Phase 6 + 7 (WelcomePage + ConceptMapPage) — particle background atmosphere
5. PR-5: Phase 8 + 9 (CardLearningView + AssistantPanel) — XP mechanics go live
6. PR-6: Phase 10 (StudentHistoryPage) — history enhancements

### Rollback Plan
Each PR is independently revertable via `git revert` since:
- CSS additions (Phase 1) are purely additive — reverting removes the new tokens and classes without breaking existing styles
- Zustand store (Phase 2) is a new file — reverting is a file deletion; no existing code imports it until Phase 3 components do
- Game components (Phase 3) are new files — reverting is file deletion
- Page/component modifications (Phases 4-10) can be reverted individually via git

**Phase 4 rollback:** If the sticky fix causes unexpected layout issues on narrow viewports, the change is a 3-line inline style modification in `CardLearningView.jsx` and a height change in `AssistantPanel.jsx`. Reverting takes under 5 minutes.

### Post-Launch Monitoring
Monitor the following for 48 hours after each PR merges:

| Signal | Tool | Threshold |
|--------|------|-----------|
| JavaScript error rate | PostHog (already integrated) | Track new error events; any new `TypeError` or `ReferenceError` in game components is a rollback trigger |
| Session completion rate | PostHog `lesson_completed` event | Should remain at baseline (within ±5%); a drop indicates the UI changes are disrupting the learning flow |
| AssistantPanel interaction rate | PostHog `assist_message_sent` event | Should increase after Phase 4 fix; if it drops, the sticky fix regressed |
| Frame rate on GameBackground | Chrome DevTools Performance panel | Manually test on a mid-range Android device; 55fps minimum at 120 particles |

### Post-Launch Validation Steps
1. Verify all four themes render correctly in production (no missing `--xp-gold` variable, no broken glassmorphism)
2. Confirm `prefers-reduced-motion: reduce` disables animations in production build (CSS media query must survive Vite optimization)
3. Open the AssistantPanel on a long card (with a lot of content) and scroll — confirm sticky behavior in production
4. Answer 3 correct MCQ answers in a row — confirm XPBurst appears, streak reaches 3, StreakMeter shows fire, AppShell StreakMeter increments

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| 0 — Dependency Verification | P0-1, P0-2, P0-3 | 0.5d | 1 Frontend Developer |
| 1 — Design System (CSS) | P1-1 through P1-4 | 1.75d | 1 Frontend Developer |
| 2 — Zustand Store | P2-1, P2-2 | 1.5d | 1 Frontend Developer |
| 3 — Game Components | P3-1 through P3-6 | 3.5d | 1 Frontend Developer |
| 4 — Sticky Fix (CRITICAL) | P4-1, P4-2, P4-3 | 1.25d | 1 Frontend Developer |
| 5 — AppShell HUD | P5-1 through P5-4 | 2.25d | 1 Frontend Developer |
| 6 — WelcomePage | P6-1 through P6-3 | 1.5d | 1 Frontend Developer |
| 7 — ConceptMapPage | P7-1, P7-2 | 1.5d | 1 Frontend Developer |
| 8 — CardLearningView | P8-1 through P8-5 | 2.5d | 1 Frontend Developer |
| 9 — AssistantPanel | P9-1 through P9-3 | 1.5d | 1 Frontend Developer |
| 10 — History Enhancement | P10-1 through P10-3 | 2.0d | 1 Frontend Developer |
| **Total** | **31 tasks** | **~19.75 engineer-days** | **1-2 Frontend Developers** |

**With 1 engineer (sequential, with parallelism where possible):** ~15 calendar days
**With 2 engineers (Phase 4 parallel to Phases 1-3; Phase 8+9 parallel to 6+7):** ~10 calendar days

---

## Key Decisions Requiring Stakeholder Input

1. **PR-1 timing:** Phase 4 (AssistantPanel sticky fix) is recommended to ship as a standalone PR before any game feature work. Confirm this priority ordering is acceptable or if it should be bundled with the first game feature PR.

2. **XP amounts:** MCQ correct = 10 XP, short answer correct = 5 XP. Are these values approved, or should they be configurable via `config.js` constants rather than hardcoded in `CardLearningView.jsx`?

3. **Sigma node state CSS:** Phase 7 node state classes require Sigma graph nodes to be targetable via CSS classes or DOM structure. If Sigma renders via WebGL (canvas-only, no DOM nodes), the node state visualization requires a different approach (Sigma custom renderer or node attribute coloring via Sigma's built-in `color` attribute). Confirm whether the current Sigma setup uses SVG/DOM or WebGL before starting P7-2.

4. **`AdaptiveModeIndicator` production visibility:** Should the mode indicator (Challenge Mode, Focus Mode, Calm Mode, Speed Mode) be visible to students in production? If yes, i18n translation keys are required in all 13 locale files. If it is an internal tool, it should be hidden behind a query param flag (e.g., `?debug=1`).

5. **Phase 10 achievement badge criteria:** The 4 badges specified (First Answer, On Fire, Consistent, Mastery) are derived from client-side history data. Confirm that this set is the complete first iteration, or if additional badges (e.g., "Perfectionist" for 100% score on a session) should be included before shipping.

6. **Session XP on HistoryPage:** The history page shows `useAdaptiveStore` level (session-scoped, resets on reload). This will show Level 1 for any student who navigates directly to `/history` without having answered questions in the current session. Should the history page suppress the level section when `xp === 0 && level === 1` (initial state)?
