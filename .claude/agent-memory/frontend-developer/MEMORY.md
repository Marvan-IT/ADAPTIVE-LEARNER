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
- `completeCardAndGetNext` in sessions.js — POST to `/api/v2/sessions/:id/complete-card`
- `getReviewDue` in students.js — GET `/api/v2/students/:id/review-due`
- New state: `idleTriggerCount`, `adaptiveCardLoading`, `motivationalNote`, `performanceVsBaseline`
- New reducer cases: `IDLE_TRIGGERED`, `ADAPTIVE_CARD_LOADING`, `ADAPTIVE_CARD_LOADED`, `ADAPTIVE_CARD_ERROR`
- `goToNextCard(signals)` — async, calls backend; falls back to simple `NEXT_CARD` if no session/signals or card ceiling (8) reached
- Signal tracking refs in CardLearningView: `cardStartTimeRef`, `wrongAttemptsRef`, `selectedWrongOptionRef`, `hintsUsedRef`
- Hints tracked via `assistLoading` false→true transitions
- `isLastCard` includes ceiling: `currentCardIndex === cards.length - 1 || cards.length >= MAX_ADAPTIVE_CARDS`

## ConceptMapPage Patterns
- `useStudent()` exposes `student.id` — use `student?.id` for safe access
- Review-due badges placed in: (1) mastered node detail panel (right side), (2) sidebar ConceptListItem
- Sigma renders on canvas — badges must be in DOM panels, not on canvas
- `reviewDueConcepts` is a `Set` of concept_id strings; fetch silently on mount when student is known
