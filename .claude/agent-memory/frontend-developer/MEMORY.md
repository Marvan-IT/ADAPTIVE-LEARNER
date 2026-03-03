# Frontend Developer Memory — ADA Project

## Project Stack
- React 19 + Vite 7, React Router DOM 7
- Tailwind CSS 4 + PostCSS (utility classes only, no inline styles where possible)
- i18next 25 — 13 languages: en, ar, de, es, fr, hi, ja, ko, ml, pt, si, ta, zh
- KaTeX via react-markdown + remark-math + rehype-katex
- Lucide React for icons
- PostHog via `src/utils/analytics.js` (`trackEvent`)

## Key File Paths
- `frontend/src/context/SessionContext.jsx` — useReducer-based session state; exports `useSession()`
- `frontend/src/context/StudentContext.jsx` — exports `useStudent()` with `{ student, masteredConcepts, refreshMastery, ... }`
- `frontend/src/api/sessions.js` — all session API calls (Axios wrappers)
- `frontend/src/api/students.js` — student API calls
- `frontend/src/locales/*.json` — flat key format (e.g. `"learning.cardProgress"`, NOT nested objects)
- `frontend/src/pages/ConceptMapPage.jsx` — Sigma graph + concept sidebar + node detail panel
- `frontend/src/components/learning/CardLearningView.jsx` — card-by-card teaching UI with MCQ/TF questions

## Patterns & Conventions
- All API wrappers in `src/api/` use the `api` Axios instance from `./client`
- Context state spreads via `...state` into Provider value — new state fields added to `initialState` are auto-exposed
- Locale files use flat dot-notation keys; new keys appended at end of file before closing `}`
- `useSession()` is the hook name for SessionContext (NOT `useSessionContext`)
- The reducer `NEXT_CARD` case was updated to reset `idleTriggerCount`, `motivationalNote`, `performanceVsBaseline`
- `sendAssistMessage(message, trigger)` dispatches `IDLE_TRIGGERED` when `trigger === "idle"`

## Adaptive Card Feature (implemented)
- `completeCardAndGetNext` in sessions.js — POST to `/api/v2/sessions/:id/complete-card`; body includes `difficulty_bias`
- `getReviewDue` in students.js — GET `/api/v2/students/:id/review-due`
- `getCardHistory` in students.js — GET `/api/v2/students/:id/card-history?limit=50`
- New state: `idleTriggerCount`, `adaptiveCardLoading`, `motivationalNote`, `performanceVsBaseline`, `learningProfileSummary`, `adaptationApplied`, `difficultyBias`
- New reducer cases: `IDLE_TRIGGERED`, `ADAPTIVE_CARD_LOADING`, `ADAPTIVE_CARD_LOADED`, `ADAPTIVE_CARD_ERROR`, `SET_DIFFICULTY_BIAS`
- `goToNextCard(signals)` — async, calls backend; falls back to simple `NEXT_CARD` if no session/signals or card ceiling (8) reached
- Signal tracking refs in CardLearningView: `cardStartTimeRef`, `wrongAttemptsRef`, `selectedWrongOptionRef`, `hintsUsedRef`
- Hints tracked via `assistLoading` false→true transitions
- `isLastCard` includes ceiling: `currentCardIndex === cards.length - 1 || cards.length >= MAX_ADAPTIVE_CARDS`
- `setDifficultyBias(bias)` exposed from SessionContext (dispatches SET_DIFFICULTY_BIAS); reset after goToNextCard call

## UI Components (as of premium redesign)
- `frontend/src/components/ui/Card.jsx` — basic card wrapper with elevated prop
- `frontend/src/components/ui/index.js` — barrel export for Badge, Button, Card, ProgressRing, Skeleton
- `frontend/src/components/learning/AdaptiveSignalTracker.jsx` — live timer, wrong/hints/idle counts, post-card profile badges
- `frontend/src/pages/StudentHistoryPage.jsx` — card history table with Sparkline SVG; route `/history` inside AppShell

## Game Layer (implemented)
- `frontend/src/store/adaptiveStore.js` — Zustand store; exports `useAdaptiveStore()`; fields: mode, xp, level, streak, streakBest, lastXpGain, burnoutScore; actions: awardXP, recordAnswer, setMode, updateMode, resetLastXpGain
- `frontend/src/components/game/GameBackground.jsx` — canvas particle animation; `style` prop forwarded
- `frontend/src/components/game/XPBurst.jsx` — fixed-position framer-motion XP toast; uses `lastXpGain` from store
- `frontend/src/components/game/StreakMeter.jsx` — streak pill; `compact` prop; fires on streak >= 1; "on fire" at >= 3
- `frontend/src/components/game/LevelBadge.jsx` — SVG ring progress badge; `size` prop (default 36)
- `frontend/src/components/game/AdaptiveModeIndicator.jsx` — mode pill; `compact` prop; returns null for NORMAL mode
- `framer-motion` and `zustand` are already installed in frontend/package.json
- AssistantPanel header gradient now reflects adaptive mode via `modeColors` map; dots-bounce loading indicator replaces spinner
- CardLearningView: awardXP(10) + recordAnswer(true/false) on every MCQ/TF answer; updateMode called on learningProfileSummary change
- AppShell nav: 64px height, glassmorphism bg, XP progress bar in center, StreakMeter + dropdown on right, Map pill in left section
- AssistantPanel wrapper in CardLearningView has `position: sticky, top: 70px, alignSelf: flex-start` for scroll-persistence
- AssistantPanel height: `calc(100vh - 86px)` (accounts for 64px nav + 2px glow line + padding)

## CSS Design Tokens (index.css :root, post-redesign)
- `--shadow-*` use premium rgba values
- `--radius-md` is `12px`; `--radius-sm` is `6px`; `--radius-lg` is `16px`; `--radius-xl` is `24px`
- `--motion-fast` is `120ms ease`; `--motion-normal` is `200ms ease`; `--motion-slow` is `350ms cubic-bezier(0.34,1.56,0.64,1)`
- Keyframes: shimmer, shake, confetti-fall, fade-up, pulse-glow, spin, slide-in-right, fadeIn, slideInRight, slideInUp, pulse, node-pulse, node-flicker, xp-burst, fog-reveal, streak-fire, float, combo-flash, dots-bounce
- Game tokens: `--node-locked/available/mastered/weak`, `--glow-xs/sm/md/lg`, `--xp-gold`, `--xp-glow`, `--adapt-slow/excelling/struggling/bored`, `--spring-bounce`, `--spring-soft`
- Game utility classes: `.node-mastered`, `.node-locked`, `.node-available`, `.node-weak`, `.glass-panel`, `.float-card`, `.adaptive-slow`, `.adaptive-excelling`, `.adaptive-struggling`

## Routing
- `/history` is inside `<AppShell />` wrapper — requires student auth
- AppShell dropdown has: Learning History (Link), language, theme, switch student; uses `Link` from react-router-dom

## ConceptMapPage Patterns
- `useStudent()` exposes `student.id` — use `student?.id` for safe access
- Review-due badges placed in: (1) mastered node detail panel (right side), (2) sidebar ConceptListItem
- Sigma renders on canvas — badges must be in DOM panels, not on canvas
- `reviewDueConcepts` is a `Set` of concept_id strings; fetch silently on mount when student is known
