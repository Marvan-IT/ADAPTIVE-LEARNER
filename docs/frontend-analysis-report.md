# ADA Frontend Analysis Report

## Tech Stack

| Concern | Technology |
|---|---|
| Framework | React 19.2 + Vite 7.3 (SPA, client-side rendering) |
| CSS | Tailwind CSS 4 + CSS custom properties (vars) + **95% inline `style={{}}` objects** |
| Component Library | None (all custom-built). 5 generic UI primitives in `components/ui/` |
| State Management | React Context (4 providers) + Zustand 5.0.11 (1 store) |
| Routing | React Router DOM 7.13 (flat route config in App.jsx) |
| Auth | Custom JWT (email/password + OTP verification, refresh tokens, role-based guards) |
| Data Fetching | Axios 1.7 via `src/api/` wrappers + `useEffect` (no SWR/React Query) |
| Animations | Framer Motion 12.34 |
| i18n | i18next 25 (13 languages, browser detection, RTL for Arabic) |
| Icons | Lucide React |
| Math Rendering | KaTeX 0.16 + react-markdown 10 + remark-math + rehype-katex |
| Graph Viz | @react-sigma/core 5.0.6 + graphology + force-atlas2 |
| Analytics | PostHog JS |
| Fonts | **Outfit** (headings, 400-900) + **DM Sans** (body, 400-700) via Google Fonts |

---

## Pages (Student Console)

| # | Route | File Path | Purpose | Role | Status |
|---|-------|-----------|---------|------|--------|
| 1 | `/map` | `src/pages/ConceptMapPage.jsx` | Concept dependency graph + book/subject selector | Student | Fully built |
| 2 | `/learn/:conceptId` | `src/pages/LearningPage.jsx` | Main lesson: chunk selection -> cards -> exam -> completion | Student | Fully built |
| 3 | `/history` | `src/pages/StudentHistoryPage.jsx` | Past sessions, card interactions, sparklines, stats | Student | Fully built |
| 4 | `/leaderboard` | `src/pages/LeaderboardPage.jsx` | Top-20 XP rankings with feature-flag gate | Student | Fully built |

## Pages (Admin Console)

| # | Route | File Path | Purpose | Role | Status |
|---|-------|-----------|---------|------|--------|
| 1 | `/admin` | `src/pages/AdminPage.jsx` | Dashboard: stats cards, subject list, create subject | Admin | Fully built |
| 2 | `/admin/subjects/:subjectSlug` | `src/pages/AdminSubjectPage.jsx` | Upload PDFs, book status tracking, retrigger | Admin | Fully built |
| 3 | `/admin/books/:slug/track` | `src/pages/AdminTrackPage.jsx` | 7-stage pipeline progress visualization | Admin | Fully built |
| 4 | `/admin/books/:slug/review` | `src/pages/AdminReviewPage.jsx` | 3-panel content editor: section tree + chunk editor + graph editor | Admin | Fully built |
| 5 | `/admin/books/:slug/content` | `src/pages/AdminBookContentPage.jsx` | Post-publish content editing | Admin | Fully built |
| 6 | `/admin/analytics` | `src/pages/AdminAnalyticsPage.jsx` | Mode distribution, difficulty ranking, mastery rates | Admin | Fully built |
| 7 | `/admin/settings` | `src/pages/AdminSettingsPage.jsx` | Runtime config: exam rates, XP values, AI models, feature toggles | Admin | Fully built |
| 8 | `/admin/students` | `src/pages/AdminStudentsPage.jsx` | Student table with sort, search, filter, pagination | Admin | Fully built |
| 9 | `/admin/students/:id` | `src/pages/AdminStudentDetailPage.jsx` | Student profile editor, mastery grant/revoke, badges, sessions | Admin | Fully built |
| 10 | `/admin/students/:id/progress` | `src/pages/AdminStudentProgressReport.jsx` | Per-period progress: XP trends, breakdown, badges | Admin | Fully built |
| 11 | `/admin/sessions` | `src/pages/AdminSessionsPage.jsx` | All sessions with phase filter, book filter, pagination | Admin | Fully built |

## Pages (Auth)

| # | Route | File Path | Purpose | Role | Status |
|---|-------|-----------|---------|------|--------|
| 1 | `/login` | `src/pages/LoginPage.jsx` | Email/password login, role-based redirect | Public | Fully built |
| 2 | `/register` | `src/pages/RegisterPage.jsx` | Registration with password strength, language, interests, style | Public | Fully built |
| 3 | `/verify-otp` | `src/pages/OtpVerifyPage.jsx` | 6-digit OTP with auto-advance, paste, resend cooldown | Public | Fully built |
| 4 | `/forgot-password` | `src/pages/ForgotPasswordPage.jsx` | Password reset email request | Public | Fully built |
| 5 | `/reset-password` | `src/pages/ResetPasswordPage.jsx` | New password entry with strength validation | Public | Fully built |
| 6 | `/` | `src/pages/WelcomePage.jsx` | Student profile picker / onboarding (legacy, pre-auth) | Public | Fully built |

**Total: 22 pages (4 student + 11 admin + 6 auth + 1 catch-all 404)**

---

## Shared Components

### Layout (`src/components/layout/`)

| Component | File Path | Purpose | Used In |
|-----------|-----------|---------|---------|
| AppShell | `layout/AppShell.jsx` (427 lines) | Main authenticated shell: collapsible sidebar + gamification HUD + nav + theme controls | All student routes |
| StyleSwitcher | `layout/StyleSwitcher.jsx` | 4 teaching style buttons (Default/Pirate/Astronaut/Gamer) | AppShell sidebar |

### Learning (`src/components/learning/`)

| Component | File Path | Purpose | Used In |
|-----------|-----------|---------|---------|
| CardLearningView | `learning/CardLearningView.jsx` (~44KB) | Card lesson UI: MCQ, hints, flags, adaptive signals, XP burst | LearningPage |
| AssistantPanel | `learning/AssistantPanel.jsx` (~10KB) | AI tutor chat panel with 90s idle auto-trigger | LearningPage |
| CompletionView | `learning/CompletionView.jsx` (~9KB) | Post-lesson summary: confetti, score ring, next concept | LearningPage |
| AdaptiveSignalTracker | `learning/AdaptiveSignalTracker.jsx` | Wrong attempts & hints display per card | CardLearningView |
| ProgressBar | `learning/ProgressBar.jsx` | Horizontal pill-dot progress for card sequence | CardLearningView |
| VerticalProgressRail | `learning/VerticalProgressRail.jsx` | Left-side vertical per-card state indicator | LearningPage |
| ConceptImage | `learning/ConceptImage.jsx` | Concept illustration display (skipHtml XSS protection) | CardLearningView |
| ChatBubble | `learning/ChatBubble.jsx` | Chat message bubble with markdown rendering | AssistantPanel |

### Gamification (`src/components/game/`)

| Component | File Path | Purpose | Used In |
|-----------|-----------|---------|---------|
| LevelBadge | `game/LevelBadge.jsx` | Level number display (XP / 100 + 1) | AppShell |
| StreakMeter | `game/StreakMeter.jsx` | Daily streak counter with flame icon | AppShell |
| StreakMultiplierBadge | `game/StreakMultiplierBadge.jsx` | Streak XP multiplier (tier 1-4) | AppShell |
| XPBurst | `game/XPBurst.jsx` | Animated XP gain notification | CardLearningView |
| AdaptiveModeIndicator | `game/AdaptiveModeIndicator.jsx` | Current mode badge (NORMAL/FAST/SLOW/STRUGGLING/BORED) | AppShell, CardLearningView |
| BadgeCelebration | `game/BadgeCelebration.jsx` | Badge earned animation/modal | CardLearningView |
| BadgeGrid | `game/BadgeGrid.jsx` | Grid of earned badges | AdminStudentDetailPage |
| BadgeIcon | `game/BadgeIcon.jsx` | Individual badge icon renderer | BadgeGrid, BadgeCelebration |
| LeaderboardMini | `game/LeaderboardMini.jsx` | Compact top-3 sidebar widget | AppShell |

### Concept Map (`src/components/conceptmap/`)

| Component | File Path | Purpose | Used In |
|-----------|-----------|---------|---------|
| ConceptGraph | `conceptmap/ConceptGraph.jsx` | Force-directed graph (Sigma + graphology) | ConceptMapPage |
| MapLegend | `conceptmap/MapLegend.jsx` | Node type legend overlay | ConceptMapPage |

### Welcome/Onboarding (`src/components/welcome/`)

| Component | File Path | Purpose | Used In |
|-----------|-----------|---------|---------|
| StudentPicker | `welcome/StudentPicker.jsx` | Select existing student profile | WelcomePage |
| StudentCard | `welcome/StudentCard.jsx` | Student profile card (avatar, name, mastery) | StudentPicker |
| StudentForm | `welcome/StudentForm.jsx` | Create new student form | WelcomePage |

### UI Primitives (`src/components/ui/`)

| Component | File Path | Purpose | Used In |
|-----------|-----------|---------|---------|
| Badge | `ui/Badge.jsx` | Generic status/label badge | Multiple pages |
| Card | `ui/Card.jsx` | Container with border/padding | Multiple pages |
| ProgressRing | `ui/ProgressRing.jsx` | SVG circular progress | CompletionView |
| Skeleton | `ui/Skeleton.jsx` | Loading placeholder (+ CardSkeleton) | CardLearningView, LearningPage |
| Button | `ui/index.js` (exported) | **MISSING FILE** - exported in index.js but `Button.jsx` does not exist | Broken import |

### Other

| Component | File Path | Purpose | Used In |
|-----------|-----------|---------|---------|
| ProtectedRoute | `components/ProtectedRoute.jsx` | Auth + role guard (redirects unauthorized) | App.jsx |
| LanguageSelector | `components/LanguageSelector.jsx` | 13-language dropdown with RTL support | AppShell, WelcomePage |

**Total: 30 components (2 layout + 8 learning + 9 game + 2 map + 3 welcome + 5 UI + 2 other)**

---

## Layouts

| Layout | File Path | Contains | Used By |
|--------|-----------|----------|---------|
| AppShell | `components/layout/AppShell.jsx` | Collapsible sidebar (240px / 64px) with: logo, nav links (Map/History/Leaderboard), gamification HUD (level/XP/streak/multiplier/mode), style switcher, language selector, theme toggle, profile + logout | All student routes (`/map`, `/learn/*`, `/history`, `/leaderboard`) |
| *None* (bare) | -- | Admin pages render without a shared shell | All admin routes (`/admin/*`) |
| *None* (bare) | -- | Auth pages render standalone (centered card on gradient bg) | `/login`, `/register`, `/verify-otp`, `/forgot-password`, `/reset-password` |

**Note: Admin pages have NO shared layout** - each admin page manages its own header/nav independently. This means duplicated back-button patterns, inconsistent headers, and no shared admin sidebar.

---

## Design System

### Fonts
- **Headings**: Outfit (Google Fonts, weights 400-900)
- **Body**: DM Sans (Google Fonts, weights 400-700, includes italic)

### Color Palette (5 themes via CSS variables)

| Variable | Light | Dark (default) | Pirate | Astronaut | Gamer |
|----------|-------|---------|--------|-----------|-------|
| `--color-primary` | `#6366f1` (indigo) | `#6366f1` | `#d97706` (amber) | `#7c3aed` (violet) | `#22c55e` (green) |
| `--color-bg` | `#f5f5fb` | `#0e0e1a` | `#fffbeb` | `#0f0a2e` | `#0a0a0a` |
| `--color-surface` | `#ffffff` | `#1c1c2e` | `#fefce8` | `#1a1145` | `#161616` |
| `--color-text` | `#0f0f1a` | `#eeeeff` | `#78350f` | `#e2e8f0` | `#f0f0f0` |
| `--color-accent` | `#8b5cf6` | `#a78bfa` | `#b45309` | `#06b6d4` | `#ec4899` |

### Tokens File
- **Primary**: `src/index.css` - all CSS variables (colors, spacing, shadows, radii, motion, game vars)
- **Teaching styles**: `src/theme/themes.js` - style definitions (default, pirate, astronaut, gamer)

### Dark Mode
- **Supported**: Yes, via `data-theme` attribute on `<html>`
- **Default**: Dark theme
- **Toggle**: ThemeContext, persisted in localStorage (`ada_theme`)
- **Implementation**: CSS variable swap (no Tailwind dark: prefix)

### CSS Variables Defined

**Colors**: `--color-primary`, `--color-primary-light`, `--color-primary-dark`, `--color-primary-rgb`, `--color-bg`, `--color-surface`, `--color-surface-2`, `--color-text`, `--color-text-muted`, `--color-accent`, `--color-success`, `--color-warning`, `--color-danger`, `--color-border`, `--color-border-strong`

**Sidebar** (always dark): `--sidebar-bg`, `--sidebar-border`, `--sidebar-text`, `--sidebar-text-muted`, `--sidebar-accent`

**Spacing (8pt grid)**: `--sp-1` (4px) through `--sp-16` (64px)

**Shadows**: `--shadow-sm`, `--shadow-md`, `--shadow-lg`, `--shadow-xl`, `--shadow-inner`

**Radii**: `--radius-sm` (6px), `--radius-md` (12px), `--radius-lg` (16px), `--radius-xl` (24px), `--radius-full` (9999px)

**Motion**: `--motion-instant` (100ms), `--motion-fast` (120ms), `--motion-normal` (200ms), `--motion-standard` (300ms), `--motion-slow` (350ms), `--spring-bounce`, `--spring-soft`

**Game/Adaptive**: `--node-locked`, `--node-available`, `--node-mastered`, `--node-weak`, `--glow-xs/sm/md/lg`, `--xp-gold`, `--xp-glow`, `--adapt-slow`, `--adapt-excelling`, `--adapt-struggling`, `--adapt-bored`

**Keyframe Animations**: `shimmer`, `fade-up`, `pulse-glow`, `spin`, `pulse`, `dots-bounce`, `node-pulse`

---

## API Layer (`src/api/`)

### Auth (`auth.js`) -> `POST /api/v1/auth/*`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/auth/register` | POST | Register new user |
| `/api/v1/auth/login` | POST | Email/password login -> JWT tokens |
| `/api/v1/auth/verify-otp` | POST | Email OTP verification |
| `/api/v1/auth/refresh` | POST | Refresh access token |
| `/api/v1/auth/me` | GET | Get current user profile |
| `/api/v1/auth/forgot-password` | POST | Request password reset OTP |
| `/api/v1/auth/reset-password` | POST | Reset password with OTP |
| `/api/v1/auth/resend-otp` | POST | Resend OTP email |
| `/api/v1/auth/logout` | POST | Invalidate refresh token |

### Sessions (`sessions.js`) -> `/api/v2/sessions/*`

| Endpoint | Method | Purpose | Timeout |
|----------|--------|---------|---------|
| `/api/v2/sessions` | POST | Start new learning session | default |
| `/api/v2/sessions/{id}` | GET | Get session state | default |
| `/api/v2/sessions/{id}/style` | PUT | Switch teaching style | default |
| `/api/v2/sessions/{id}/assist` | POST | AI assistant message | 180s |
| `/api/v2/sessions/{id}/record-interaction` | POST | Record card telemetry | default |
| `/api/v2/sessions/{id}/complete-cards` | POST | Finish cards phase | default |
| `/api/v2/sessions/{id}/complete-card` | POST | Complete single card + get next | 30s |
| `/api/v2/sessions/{id}/interests` | PUT | Update session interests | default |
| `/api/v2/sessions/{id}/chunks` | GET | Get chunk list for concept | default |
| `/api/v2/sessions/{id}/chunk-cards` | POST | Generate cards for a chunk | 300s |
| `/api/v2/sessions/{id}/chunk-recovery-card` | POST | Generate recovery card | 180s |
| `/api/v2/sessions/{id}/complete-chunk` | POST | Mark chunk complete | default |
| `/api/v2/sessions/{id}/chunks/{id}/complete` | POST | Complete chunk item | default |
| `/api/v2/sessions/{id}/chunks/{id}/evaluate` | POST | Evaluate chunk answers | 60s |

### Concepts (`concepts.js`) -> `/api/v1/*` and `/api/v2/*`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/graph/full` | GET | Full concept graph (nodes + edges) |
| `/api/v1/concepts/next` | POST | Get next available concepts |
| `/api/v1/books` | GET | List available books |
| `/api/v2/concepts/translate-titles` | POST | Translate concept titles (180s timeout) |
| `/api/v2/concepts/{id}/readiness` | GET | Check prerequisite readiness |

### Students (`students.js`) -> `/api/v2/*`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v2/students` | POST | Create student |
| `/api/v2/students` | GET | List all students |
| `/api/v2/students/{id}` | GET | Get student profile |
| `/api/v2/students/{id}/mastery` | GET | Get mastered concepts |
| `/api/v2/students/{id}/language` | PATCH | Update language preference |
| `/api/v2/students/{id}/review-due` | GET | Get spaced review due items |
| `/api/v2/students/{id}/card-history` | GET | Card interaction history |
| `/api/v2/students/{id}/progress` | PATCH | Update XP + streak |
| `/api/v2/students/{id}/sessions` | GET | Student's sessions |
| `/api/v2/students/{id}/badges` | GET | Earned badges |
| `/api/v2/sessions/{id}/card-interactions` | GET | Session card telemetry |
| `/api/v2/leaderboard` | GET | Top students ranking |
| `/api/v2/features` | GET | Feature flags |

### Admin (`admin.js`) -> `/api/v2/admin/*`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v2/admin/dashboard` | GET | Platform stats |
| `/api/v2/admin/subjects` | GET/POST | List/create subjects |
| `/api/v2/admin/books` | GET | List books with status |
| `/api/v2/admin/books/upload` | POST | Upload PDF textbook |
| `/api/v2/admin/books/{slug}/status` | GET | Pipeline status |
| `/api/v2/admin/books/{slug}/sections` | GET | Book section tree |
| `/api/v2/admin/books/{slug}/chunks` | GET | Chunks for section |
| `/api/v2/admin/books/{slug}/graph` | GET | Book dependency graph |
| `/api/v2/admin/books/{slug}/publish` | POST | Publish book |
| `/api/v2/admin/books/{slug}/drop` | DELETE | Drop/wipe book |
| `/api/v2/admin/books/{slug}/retrigger` | POST | Re-run extraction |
| `/api/v2/admin/students` | GET | Student management list |
| `/api/v2/admin/students/{id}` | GET/PUT/DELETE | Student CRUD |
| `/api/v2/admin/students/{id}/toggle-access` | POST | Activate/deactivate |
| `/api/v2/admin/students/{id}/reset-password` | POST | Force password reset |
| `/api/v2/admin/students/{id}/mastery` | POST/DELETE | Grant/revoke mastery |
| `/api/v2/admin/students/{id}/progress-report` | GET | Period-based analytics |
| `/api/v2/admin/sessions` | GET | All sessions (filtered) |
| `/api/v2/admin/analytics` | GET | Platform analytics |
| `/api/v2/admin/config` | GET/PUT | Runtime config CRUD |
| `/api/v2/admin/users` | GET/POST | Admin user management |
| `/api/v2/admin/users/{id}/role` | PUT | Change user role |
| `/api/v2/admin/chunks/{id}` | PUT | Edit chunk content |
| `/api/v2/admin/chunks/{id}/visibility` | PUT | Show/hide chunk |
| `/api/v2/admin/chunks/{id}/exam-gate` | PUT | Toggle exam gate |
| `/api/v2/admin/chunks/merge` | POST | Merge two chunks |
| `/api/v2/admin/chunks/{id}/split` | POST | Split chunk at paragraph |
| `/api/v2/admin/chunks/reorder` | PUT | Reorder chunks |
| `/api/v2/admin/chunks/{id}/embedding` | POST | Regenerate embedding |
| `/api/v2/admin/concepts/{id}/embeddings` | POST | Regenerate concept embeddings |
| `/api/v2/admin/sections/rename` | PUT | Rename section |
| `/api/v2/admin/sections/optional` | PUT | Toggle section optional |
| `/api/v2/admin/sections/exam-gate` | PUT | Toggle section exam gate |
| `/api/v2/admin/graph/edges` | GET | Get graph edges |
| `/api/v2/admin/graph/overrides` | GET | Get edge overrides |
| `/api/v2/admin/graph/edge` | POST | Add/remove graph edge |
| `/api/v2/admin/graph/overrides/{id}` | DELETE | Delete edge override |

---

## State Management Summary

| Store | Type | File | Scope |
|-------|------|------|-------|
| AuthContext | React Context | `context/AuthContext.jsx` | JWT auth, user object, token refresh |
| StudentContext | React Context | `context/StudentContext.jsx` | Student profile, mastered concepts |
| SessionContext | React Context | `context/SessionContext.jsx` (825 lines) | Learning session state machine (phases, cards, chunks, AI assist) |
| ThemeContext | React Context | `context/ThemeContext.jsx` | Dark/light theme + teaching style |
| adaptiveStore | Zustand | `store/adaptiveStore.js` | XP, level, streak, badges, adaptive mode, feature flags |

---

## Custom Hooks

| Hook | File | Purpose |
|------|------|---------|
| useConceptMap | `hooks/useConceptMap.js` | Fetch graph + statuses + translations for a book |

---

## Utilities

| File | Purpose |
|------|---------|
| `utils/analytics.js` | PostHog init, identify, trackEvent, trackPageView, resetUser |
| `utils/constants.js` | API_BASE_URL, MASTERY_THRESHOLD (70), STYLES array, SUGGESTED_INTERESTS |
| `utils/formatConceptTitle.js` | Convert concept_id to readable title ("adding_fractions" -> "Adding Fractions") |

---

## Issues Found

### Critical

1. **Missing Button component**: `components/ui/index.js` exports `Button` but `Button.jsx` does not exist. Any import of `Button` from `ui/` will crash at runtime.

2. **No shared admin layout**: All 11 admin pages manage their own header/nav independently. Duplicated back-button patterns, inconsistent spacing, no shared sidebar or breadcrumbs.

3. **95% inline styles**: Nearly all components use `style={{}}` objects instead of Tailwind classes or CSS modules. This makes the codebase extremely hard to maintain, theme, or redesign. Styles are scattered across 30+ component files with no single source of truth for component-level styling.

### High Priority

4. **SessionContext is 825 lines**: Single reducer file managing 25+ action types. Extremely complex, hard to test, and tightly coupled. Any card/chunk/AI-assist logic change risks regressions across the entire learning flow.

5. **CardLearningView is ~44KB**: Monolithic component handling MCQ, teaching cards, check-in cards, adaptive signals, hints, flags, recovery, and XP animations. Should be decomposed into smaller, focused components.

6. **No admin navigation component**: Each admin page has ad-hoc "Back to X" links. No sidebar, no breadcrumbs, no consistent header. Users navigate by memory or browser back button.

7. **Duplicated table styles across admin pages**: `thStyle`, `tdStyle`, row hover patterns are copy-pasted in AdminStudentsPage, AdminSessionsPage, AdminAnalyticsPage, etc.

8. **No shared form components**: Each page builds its own inputs, selects, toggles with inline styles. No Input, Select, Toggle, or Modal primitives in `ui/`.

9. **Password strength logic duplicated**: Both RegisterPage and ResetPasswordPage implement password validation independently (StrengthBar).

### Medium Priority

10. **No React Query / SWR**: All data fetching is raw `useEffect` + `useState` + manual loading/error tracking. No caching, no automatic revalidation, no optimistic updates. Every admin page re-fetches on mount.

11. **Polling instead of real-time**: AdminSubjectPage polls books every 30s, AdminTrackPage polls every 5s, ConceptMapPage polls every 30s. No WebSocket or SSE for real-time updates.

12. **Only 1 custom hook**: `useConceptMap` is the only extracted hook. Data fetching logic in pages (loading, error, refetch patterns) is duplicated everywhere instead of being abstracted into hooks.

13. **No test framework for frontend**: No vitest/jest configured. Only `adaptiveStore.test.js` exists, and there's no test runner to execute it. Zero component tests.

14. **Tailwind is imported but barely used**: `@import "tailwindcss"` is in index.css but components use inline styles. Tailwind utility classes are rarely applied.

15. **No responsive design**: AppShell sidebar is fixed-width (240/64px). No mobile breakpoints, no hamburger menu, no responsive grid. Admin pages are desktop-only.

16. **No loading skeletons for admin pages**: Student pages have skeletons but admin pages show "Loading..." text.

17. **WelcomePage is orphaned**: The `/` route renders `WelcomePage` (student picker UI) which appears to be a legacy pre-auth flow. With the new JWT auth system, its role is unclear.

### Low Priority

18. **No error boundary per route**: Single top-level ErrorBoundary in App.jsx. A crash in one admin page takes down the entire app.

19. **No breadcrumb navigation**: Deep admin pages (student detail -> progress report) have no breadcrumb trail.

20. **Feature flag check only on Leaderboard**: Feature flags are fetched but only used to gate the leaderboard. Other features (badges, streak multiplier) are always shown.

21. **Locale files are large but not code-split**: All 13 language files are loaded together. Only the active language should be loaded.

22. **No skeleton/placeholder for graph visualization**: ConceptGraph shows nothing while force-atlas2 layout computes.

---

## File Inventory Summary

| Category | Count |
|----------|-------|
| Pages | 22 |
| Components | 30 |
| Context Providers | 4 |
| Zustand Stores | 1 |
| Custom Hooks | 1 |
| API Modules | 5 (+ base client) |
| Utility Files | 3 |
| Locale Files | 13 |
| Config Files | 4 (vite, postcss, eslint, package.json) |
| **Total Source Files** | **~77** |
