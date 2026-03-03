# High-Level Design — AI-Native Learning OS

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-01 | Solution Architect | Initial authoring. Covers all 10 features: Game Design System, Zustand Adaptive Store, Game Components, AppShell HUD, WelcomePage World, ConceptMapPage Neural Map, AssistantPanel Sticky Fix, CardLearningView Adaptive Modules, AssistantPanel Companion Upgrades, StudentHistoryPage Enhancement. Confirmed framer-motion 12.x and zustand 5.x already present in frontend/package.json. |

---

**Feature slug:** `ai-native-learning-os`
**Author:** Solution Architect
**Date:** 2026-03-01
**Status:** Approved for implementation

---

## 1. Executive Summary

### Feature Name
AI-Native Adaptive Learning OS — Visual & Emotional Redesign

### Purpose
Transform ADA from a functional educational UI into a game-world learning environment that children experience as a living, breathing operating system rather than a website. The goal is to remove every visual cue that this is a traditional school tool and replace it with the emotional vocabulary of games: XP, streaks, levels, adaptive environments, animated companions, and a persistent sense of progress.

### Business Problem Being Solved
ADA has strong pedagogical mechanics (Socratic loop, adaptive card delivery, mastery tracking) but presents them inside a generic SaaS UI. Children aged 8-14 disengage from standard educational interfaces within minutes. The adaptive engine detects struggle, speed, and boredom signals but has no visual manifestation — the UI looks identical whether the student is excelling or failing. This wastes the adaptive data ADA already collects.

Additionally, the AssistantPanel has a critical regression: after the first answer is submitted and the panel slides in, it does not maintain a sticky position when the user scrolls the card column. This causes the AI companion to disappear from view precisely when the student needs help.

### Key Stakeholders
- Product: ADA product team
- Users: Students aged 8-14 (primary), parents/guardians (secondary)
- Engineering: Frontend Developer (implementation), Solution Architect (design)

### Scope

**Included:**
- CSS design system extension (game tokens, keyframes, utility classes)
- Zustand adaptive state store (`adaptiveStore.js`)
- Four new game UI components (`GameBackground`, `XPBurst`, `StreakMeter`, `LevelBadge`, `AdaptiveModeIndicator`)
- AppShell game HUD (nav height, XP bar, glassmorphism)
- WelcomePage game world (particle canvas, floating islands, fog of war)
- ConceptMapPage living neural map (particle canvas, node state CSS)
- AssistantPanel sticky positioning fix (critical bug)
- CardLearningView adaptive overlays and XP integration
- AssistantPanel AI companion visual upgrades
- StudentHistoryPage achievement layer

**Excluded:**
- Backend changes (all state is frontend-only Zustand; XP/levels do not persist to PostgreSQL in this phase)
- New API endpoints
- New i18n translation keys beyond those already referenced in existing components
- Mobile-specific layout changes (responsive behavior preserved but not redesigned)
- Accessibility audit (handled in a future hardening phase)

---

## 2. Functional Requirements

### Core Capabilities
The system must deliver a cohesive game-world UI layer that:
- Expresses student performance state visually in real time
- Rewards correct answers with visible XP gain and streak tracking
- Adapts the visual environment (colors, animations, layout cues) to the current adaptive mode
- Fixes the AssistantPanel scroll-stickiness regression
- Adds particle background atmosphere to WelcomePage and ConceptMapPage
- Annotates concept map nodes with mastery/lock/weakness visual states
- Surfaces learning history as achievement badges and heatmaps

### User Stories (Priority Order)

| ID | Story | Priority |
|----|-------|----------|
| US-01 | As a student, I want to see my XP increase with a burst animation after every correct answer, so I feel immediate reward. | P0 |
| US-02 | As a student, I want the AI helper panel to stay visible on screen when I scroll down through a long card, so I can ask for help without losing my place. | P0 (bug fix) |
| US-03 | As a student, I want to see my streak count in the nav bar, so I feel motivated to keep answering correctly. | P1 |
| US-04 | As a student, I want the card background to subtly change when I am excelling or struggling, so the environment feels alive and aware. | P1 |
| US-05 | As a student, I want to see animated floating subject cards on the home screen, so launching a lesson feels like entering a game world. | P2 |
| US-06 | As a student, I want mastered concept nodes on the map to glow gold and locked nodes to appear greyed out, so I can see my progress at a glance. | P2 |
| US-07 | As a student, I want to see my level badge and XP progress bar in the navigation, so I always know how close I am to leveling up. | P1 |
| US-08 | As a student, I want animated thinking dots on the AI companion when it is loading, so I know it is working rather than frozen. | P2 |

---

## 3. Non-Functional Requirements

| Category | Requirement | Measurable Target |
|----------|-------------|-------------------|
| Performance | GameBackground canvas must not drop frame rate below 60fps on a mid-range device | 60fps sustained at 120 particles, measured in Chrome DevTools |
| Performance | Framer Motion animations must not cause layout thrash | Zero layout recalculations during animation (use `transform` and `opacity` only) |
| Performance | Zustand store actions must complete synchronously | No async operations in `awardXP`, `recordAnswer` |
| Bundle Size | framer-motion + zustand combined addition to bundle | Less than 60KB gzipped added to current bundle |
| Accessibility | Reduced motion preference must disable all CSS keyframe animations | `@media (prefers-reduced-motion: reduce)` already present in `index.css`; all new keyframes must be inside or guarded by this block |
| Reliability | AssistantPanel sticky fix must work across all four themes | Verified by visual inspection in default, pirate, astronaut, gamer themes |
| Maintainability | All new CSS tokens must follow existing naming convention (`--color-*`, `--shadow-*`, `--motion-*`) | Code review gate |
| Maintainability | Zustand store must be the single source of truth for XP/level/streak; no local state duplication | Code review gate |
| Scalability | XP and level state is session-scoped (in-memory only); no persistence to backend required in this phase | Documented assumption |

---

## 4. System Context Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Browser (React 19 SPA)                       │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  AppShell (Game HUD Nav — 64px)                               │   │
│  │  ┌──────────┐  ┌─────────────────────────┐  ┌─────────────┐ │   │
│  │  │  Logo    │  │  XP Strip + LevelBadge  │  │ Streak +    │ │   │
│  │  │  (Brain) │  │  (Zustand: xp, level)   │  │ Dropdown    │ │   │
│  │  └──────────┘  └─────────────────────────┘  └─────────────┘ │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌────────────────────────┐   ┌──────────────────────────────────┐  │
│  │   WelcomePage          │   │   ConceptMapPage                  │  │
│  │  ┌──────────────────┐  │   │  ┌──────────────────────────┐   │  │
│  │  │ GameBackground   │  │   │  │ GameBackground (canvas)  │   │  │
│  │  │ (canvas, stars)  │  │   │  │ + Sigma graph overlay    │   │  │
│  │  └──────────────────┘  │   │  │   - gold ring: mastered  │   │  │
│  │  Floating Island Cards │   │  │   - grey+blur: locked    │   │  │
│  │  Player Profile Strip  │   │  │   - flicker: weak        │   │  │
│  └────────────────────────┘   │  └──────────────────────────┘   │  │
│                                └──────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │   CardLearningView                                              │  │
│  │  ┌───────────────────────────┐  ┌────────────────────────────┐│  │
│  │  │  Card Column              │  │  AssistantPanel (FIXED)    ││  │
│  │  │  - Adaptive mode overlay  │  │  position: sticky          ││  │
│  │  │  - StreakMeter in header  │  │  top: 70px                 ││  │
│  │  │  - XPBurst on correct ans │  │  alignSelf: flex-start     ││  │
│  │  │  - Framer Motion entry    │  │  height: calc(100vh-86px)  ││  │
│  │  └───────────────────────────┘  └────────────────────────────┘│  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Zustand adaptiveStore (in-memory, session-scoped)              │  │
│  │  { mode, xp, level, streak, streakBest, lastXpGain,            │  │
│  │    burnoutScore }                                               │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Existing Contexts (unchanged)                                  │  │
│  │  StudentContext | SessionContext | ThemeContext                  │  │
│  └────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP / Axios (unchanged)
                              ▼
                    ┌─────────────────┐
                    │  FastAPI Backend  │
                    │  (no changes)    │
                    └─────────────────┘
```

---

## 5. Architectural Style and Patterns

### Selected Style
**Component-layer augmentation with a shared reactive store.**

The design does not refactor existing components. Instead it:
1. Introduces a Zustand store as a thin global state layer for game mechanics (XP, level, streak, adaptive mode)
2. Extends `index.css` with new design tokens and keyframes — additive, no existing tokens removed
3. Creates isolated game components in `frontend/src/components/game/` that are composed into existing pages
4. Applies targeted fixes to `CardLearningView.jsx` (lines 616-622) and `AssistantPanel.jsx` (line 100)

### Justification
- **Additive over disruptive:** Existing React Context providers (StudentContext, SessionContext, ThemeContext) remain unchanged. The Zustand store is orthogonal to these — it tracks game mechanics, not business domain state. Mixing XP/level into SessionContext would violate single-responsibility and make the session context harder to test.
- **Zustand over React Context for game state:** Game state (XP, streak) changes on every correct answer. React Context triggers a full subtree re-render on each change. Zustand's fine-grained subscription model means only the components that consume `xp` or `streak` re-render.
- **Canvas for GameBackground over CSS backgrounds:** A CSS gradient or SVG cannot produce 120 smoothly animated particles at 60fps without hardware-accelerated canvas. The canvas approach also isolates particle rendering from the React render cycle entirely.
- **Framer Motion for component animations:** The existing `index.css` keyframe system is adequate for CSS-only transitions, but component-mount/unmount animations (XPBurst, message entry, card entry) require JavaScript-driven animation with lifecycle awareness. Framer Motion's `AnimatePresence` provides this without custom animation loop code.

### Alternatives Considered

| Alternative | Reason Rejected |
|-------------|-----------------|
| CSS-only animations for XPBurst | Cannot animate on component unmount (needs AnimatePresence) |
| Redux for game store | Overkill boilerplate; Zustand has equivalent capability with a fraction of the code |
| Three.js for background | 400KB+ bundle impact; overkill for a 2D star field |
| Refactoring SessionContext to include XP | Violates SRP; session context is already complex |

---

## 6. Technology Stack

| Concern | Technology | Version | Rationale |
|---------|-----------|---------|-----------|
| Animation library | framer-motion | ^11.x | AnimatePresence for mount/unmount, spring physics via `transition: { type: "spring" }`, minimal API surface |
| State management (game) | zustand | ^5.x | Zero-boilerplate reactive store, no Provider wrapper needed, fine-grained subscriptions |
| Particle canvas | HTML5 Canvas API | Native (no lib) | No external dependency; 120-particle star field is straightforward with `requestAnimationFrame` |
| Existing React | React 19 + Vite 7 | As-is | No version change |
| Existing styling | Tailwind CSS 4 + CSS custom properties | As-is | New tokens extend `:root`; new keyframes extend existing `@keyframes` block |
| Existing routing | React Router DOM 7 | As-is | No route changes |

### Dependency Addition Declaration
The following packages are added to `frontend/package.json`:

```json
"framer-motion": "^11.0.0",
"zustand": "^5.0.0"
```

No other new dependencies are required.

---

## 7. Key Architectural Decisions (ADRs)

### ADR-001: Zustand Store Is Session-Scoped Only (No Persistence)
- **Decision:** XP, level, and streak are stored in Zustand in-memory only. They reset on page reload.
- **Options considered:** (a) Persist to localStorage; (b) Persist to PostgreSQL via new API; (c) In-memory only
- **Chosen:** (c) In-memory only
- **Rationale:** Adding persistence requires a backend schema change (new table or columns), a migration, and a new API endpoint — all of which are out of scope for a frontend redesign phase. LocalStorage persistence creates a sync problem when the same student logs in on a different device. In-memory keeps this phase clean and reversible.
- **Future note:** When persistence is added, the Zustand store's `awardXP` and `recordAnswer` actions are the correct integration point. Add a backend call inside those actions without changing consumer components.

### ADR-002: GameBackground Uses `position: absolute` with `z-index: 0`
- **Decision:** The canvas element is positioned absolutely behind all page content with `z-index: 0`. Page content sits on `z-index: 1` or higher.
- **Rationale:** This avoids any layout impact. The canvas does not participate in the flex/grid layout of the page. It fills the nearest positioned ancestor (the page wrapper div which receives `position: relative`).

### ADR-003: AssistantPanel Sticky Fix Uses Inline Styles (Not CSS Class)
- **Decision:** The sticky positioning change is applied as inline style on the wrapper div in `CardLearningView.jsx`, consistent with the existing codebase convention of using inline styles for layout.
- **Rationale:** All layout in `CardLearningView.jsx` is done via inline styles (lines 1-632 show zero CSS class usage for layout). Adding a new CSS class would be inconsistent and create a hidden coupling between the JSX and the stylesheet.

### ADR-004: New Game Components Live in `components/game/`, Not Merged into Existing Directories
- **Decision:** All five new game components (`GameBackground`, `XPBurst`, `StreakMeter`, `LevelBadge`, `AdaptiveModeIndicator`) are placed in `frontend/src/components/game/`.
- **Rationale:** This preserves the existing directory conventions (`learning/`, `layout/`, `conceptmap/`, `welcome/`, `ui/`) and makes the game UI layer easy to identify, audit, or remove as a discrete unit.

### ADR-005: Adaptive Mode Token Values Are Defined in CSS, Not Zustand
- **Decision:** The visual expression of each mode (NORMAL, EXCELLING, STRUGGLING, SLOW, BORED) is controlled by CSS custom properties and utility classes in `index.css`. Zustand holds the mode name string. Components apply the appropriate CSS class based on the mode string.
- **Rationale:** CSS tokens can be overridden per-theme without changing JavaScript. If the gamer theme requires different STRUGGLING colors than the default theme, that is a CSS concern, not a Zustand concern.

---

## 8. Feature Summary Table

| # | Feature | Target File(s) | New Dependencies |
|---|---------|----------------|------------------|
| 1 | Game Design System | `frontend/src/index.css` | None |
| 2 | Zustand Adaptive Store | `frontend/src/store/adaptiveStore.js` | zustand |
| 3 | Game Components (5 components) | `frontend/src/components/game/` | framer-motion |
| 4 | AppShell Game HUD | `frontend/src/components/layout/AppShell.jsx` | None (consumes store) |
| 5 | WelcomePage Game World | `frontend/src/pages/WelcomePage.jsx` | None (uses GameBackground) |
| 6 | ConceptMapPage Neural Map | `frontend/src/pages/ConceptMapPage.jsx` | None (CSS classes) |
| 7 | AssistantPanel Sticky Fix | `CardLearningView.jsx` + `AssistantPanel.jsx` | None |
| 8 | CardLearningView Adaptive Modules | `frontend/src/components/learning/CardLearningView.jsx` | None (uses store + new components) |
| 9 | AssistantPanel AI Companion | `frontend/src/components/learning/AssistantPanel.jsx` | framer-motion |
| 10 | StudentHistoryPage Enhancements | `frontend/src/pages/StudentHistoryPage.jsx` | None |

---

## 9. Key Design Principles

### Game-World First
Every visual decision is evaluated against the question: "Does this feel like a game or a school website?" Flat white cards with blue borders fail this test. Glassmorphic panels, particle backgrounds, and glowing gold borders pass it.

### Emotional Engagement at Every State Transition
State transitions (correct answer, level up, streak milestone, mode change) must produce a visible, delightful reaction. Silent state changes are wasted motivational opportunities.

### Adaptive Behavior Is Visible
The adaptive engine already detects student signals. The visual layer must make the system's awareness felt. A student in STRUGGLING mode should see the environment shift to a calmer, more supportive palette. A student in EXCELLING mode should see gold borders and combo badges.

### Visual Premium Without Performance Penalty
All animations use `transform` and `opacity` only (GPU-composited properties). Canvas rendering runs on `requestAnimationFrame`. No animation triggers layout recalculation (`width`, `height`, `top`, `left` are never animated).

### Progressive Enhancement
Every game-world visual is purely additive. If a student's device has `prefers-reduced-motion: reduce`, all keyframe animations collapse to instant transitions (already enforced by the existing media query in `index.css`). The learning experience remains fully functional without any animation.

---

## 10. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| GameBackground canvas causes jank on low-end devices | Medium | High | Cap particle count at 120; use `requestAnimationFrame` cancellation on component unmount; test on Android mid-range device |
| Zustand store XP/streak resets on page reload cause student frustration | High | Medium | Communicate clearly in UI: "Your progress resets each session" (out of scope for this phase; document as known limitation) |
| framer-motion bundle size exceeds tolerance | Low | Medium | Bundle-analyze after install; framer-motion supports tree-shaking — only import `motion`, `AnimatePresence` |
| Adaptive mode CSS classes conflict with existing Tailwind utilities | Low | Low | Use a namespaced prefix (`adaptive-*`) for all new utility classes; run visual regression check on all four themes |
| AssistantPanel sticky fix breaks on narrow viewport | Medium | Medium | Test at 768px, 1024px, 1280px breakpoints; the panel collapses to 0px width when `showAssistant` is false so sticky has no effect until it opens |
| `position: sticky` in a flex container requires `align-self: flex-start` | High (known) | High | The DLD specifies `alignSelf: flex-start` explicitly on the wrapper; this is documented as the root cause of the existing bug |

---

## Key Decisions Requiring Stakeholder Input

1. **XP persistence:** Should XP and level carry over between sessions (requiring backend work) or reset per session as specified? The current design assumes reset.
2. **XP amounts:** The DLD specifies 10 XP for correct MCQ and 5 XP for correct short answer. Are these values confirmed, or should they be configurable constants?
3. **Fog of war on WelcomePage:** The fog-of-war overlay on locked subjects is specified as a hover-reveals interaction. Should locked subjects be hidden entirely or visible but dimmed?
4. **Combo badge threshold:** At what streak count does the EXCELLING combo badge appear? The DLD specifies streak >= 3 for fire animation; a separate threshold for combo badge display needs confirmation.
5. **`AdaptiveModeIndicator` visibility:** Should this pill be visible to students or is it an internal debug tool? If visible, label strings need i18n keys added to all 13 locale files.
