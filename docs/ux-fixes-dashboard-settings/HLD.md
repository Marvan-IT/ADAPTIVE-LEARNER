# HLD — UX Fixes: Dashboard & Settings

**Slug:** `ux-fixes-dashboard-settings`
**Date:** 2026-04-23
**Author:** Solution Architect

---

## 1. Executive Summary

Four independent UX defects degrade the first-run and daily-use experience of the Adaptive Learner student shell. All four are pure frontend or trivial backend changes — no schema migration, no new endpoints, no LLM prompt change.

| # | Problem | Severity |
|---|---------|---------|
| 1 | XP/Level flickers to 0/Lv.1 on every login until hydration completes | High — visible regression on first render |
| 2 | Age field is blank on Settings even after the user saved it | Medium — silent data loss perception |
| 3 | Chrome autofills the custom-interest input with the user's email address | Medium — confusing UX, corrupts interest list |
| 4 | Logout button fires immediately with no confirmation | Low-Medium — destructive action lacks guard |

**Business problem:** Each defect erodes trust in the app's correctness. Problem 1 is the most jarring because it appears on every login. Problems 2–4 surface during onboarding or profile management — a critical retention window.

**Stakeholders:** Student-facing product; no admin or pipeline impact.

**Scope — included:**
- Backend: one-line dict fix for `GET /api/v2/students/{student_id}` (`teaching_router.py`).
- Frontend: `StudentContext.jsx`, `StudentSidebar.jsx`, `DashboardPage.jsx`, `SettingsPage.jsx`, `AppShell.jsx`, all 13 locale files.
- Tests: one new backend assertion in `test_api_integration.py`, one new Playwright e2e spec.

**Scope — excluded:**
- AdminSidebar / admin logout (separate auth flow, separate risk surface).
- `/api/v1/auth/login` response (adding XP/level to the JWT payload or login response is a larger auth refactor; out of scope).
- Alembic migrations (no schema change).
- `cache_version` bump (no card-generation prompt touched).
- Any i18n key that does not exist yet and is not needed for these four fixes.

---

## 2. Functional Requirements

**FR-1 — XP skeleton gate**
The sidebar and dashboard stat cards MUST render placeholder `—` values from the moment the authenticated route mounts until `StudentContext` has completed `getStudent()` → `initAdaptive()`. After hydration the real values appear, with no intermediate flash of `Lv.1 · 0/100 XP`.

**FR-2 — Age round-trip**
`GET /api/v2/students/{student_id}` MUST include `age` in its response dict so that `SettingsPage` can pre-populate the field. No user-facing change beyond the field being populated.

**FR-3 — Autofill suppression**
The custom-interest text input in Settings MUST carry `type="text"`, `name="custom-interest"`, `autoComplete="off"`, and `data-lpignore="true"` so that browser and password-manager autofill does not inject the user's email.

**FR-4 — Logout confirmation**
Clicking the logout button in `AppShell.jsx` MUST open a `useDialog().confirm()` modal (variant `"danger"`) before executing `logout()` + navigation. Pressing Cancel MUST leave the app in its current state.

---

## 3. Non-Functional Requirements

| Attribute | Target |
|-----------|--------|
| Render performance | Skeleton must appear within the same paint as the authenticated shell — no extra network call. |
| Hydration latency | No new API call added; `getStudent()` is already in-flight. |
| Bundle size | No new dependencies. |
| i18n coverage | All 13 locale files must carry the keys used by Problem 4's modal. |
| Regression risk | Changes are isolated to 5 frontend files + 1 backend handler. No shared service layer touched. |

---

## 4. System Context

```
  Browser (student)
       │
       ▼
  React SPA (Vite 7, port 5173)
  ┌──────────────────────────────────────────────────────┐
  │  AuthContext  ──────────►  AuthProvider (JWT store)  │
  │       │                                              │
  │  StudentContext (isHydrated NEW) ──► adaptiveStore   │
  │       │                             (xp, level,      │
  │       │                              dailyStreak)    │
  │       │                                              │
  │  AppShell ──► StudentSidebar (skeleton gate NEW)     │
  │           └► DashboardPage  (skeleton gate NEW)      │
  │           └► SettingsPage   (autofill fix NEW,       │
  │                              age pre-populate via    │
  │                              GET fix)                │
  │  DialogProvider (confirm modal, already mounted)     │
  └──────────────────────────────────────────────────────┘
       │
       ▼ HTTP (port 8889)
  FastAPI backend
  ┌─────────────────────────────────────────────┐
  │  GET /api/v2/students/{id}  ← add "age" key │
  │  (teaching_router.py:287–299)               │
  └─────────────────────────────────────────────┘
       │
  PostgreSQL 15  (students.age INTEGER nullable)
```

Data flow for Problem 1 (post-fix):
```
login() → navigate("/dashboard")
  └─ StudentProvider mounts → isHydrated = false
       → sidebar/dashboard render "—" placeholders
  └─ getStudent(studentId) resolves
       → initAdaptive({ xp, streak, ... })
       → isHydrated = true
       → sidebar/dashboard replace "—" with real values
```

---

## 5. Architectural Style and Patterns

**Pattern A — Hydration gate via boolean flag on Context**
`isHydrated` is a single boolean exposed from `StudentContext`. Consumers (Sidebar, Dashboard) branch on it to show skeleton text. This is the same pattern used by `AuthContext.loading` for the outer auth gate. Adding a second, narrower flag avoids coupling the XP display to the broader `loading` state (which also covers mastery fetch).

Alternatives considered:
- Expose XP directly from `StudentContext` (would require duplicating Zustand state into Context — violates single source of truth).
- Use `loading` flag already on `StudentContext` (covers the full `getStudent` + `getStudentMastery` chain; `initAdaptive` runs mid-chain, so `loading=false` does not guarantee hydration has occurred before the mastery call resolves — timing is not guaranteed).
- Delay navigation until hydration in `AuthContext.login()` (requires `login()` to fetch student data, coupling auth to the student API — wrong layer).

**Pattern B — Gate destructive actions through `useDialog().confirm()`**
Admin pages already establish this pattern. Applying it to logout in the student shell is a direct reuse of existing infrastructure. No new component or context is needed.

---

## 6. Technology Stack

Unchanged from project baseline. No new packages.

| Layer | Technology |
|-------|-----------|
| Frontend state | React Context + Zustand (`adaptiveStore`) |
| Dialog | `DialogProvider` / `useDialog()` — already installed |
| i18n | i18next via `useTranslation()` |
| Backend | FastAPI + SQLAlchemy 2.0 async |
| DB | PostgreSQL 15 — no migration |

---

## 7. Key Architectural Decisions (ADRs)

**ADR-1: `isHydrated` resets to `false` on user change, not on logout**
Decision: The `useEffect` that drives hydration already depends on `user?.student_id`. When the user logs out, `user` becomes `null`, `studentId` is falsy, the early-return path runs, and `setLoading(false)` is called immediately. `isHydrated` must therefore be reset to `false` at the top of the early-return branch (before `setLoading(false)`), not inside `logout()`, to keep the reset co-located with the hydration trigger.

**ADR-2: Skeleton shows `—` for level badge number and `— / — XP` text; progress bar width = 0**
Decision: A zero-width progress bar is technically accurate (0 XP of 100) but could look like a broken bar. However, showing any non-zero value before hydration is misleading. Width=0 is chosen; developers may optionally use a shimmer/pulse animation on the bar background. The `—` text is unambiguous.

**ADR-3: No change to login response**
Adding XP/level to `/api/v1/auth/login` would eliminate the need for a skeleton gate but requires a coordinated backend auth change and JWT/schema update. The hydration-gate approach achieves the same visible result with zero auth-layer risk.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| `isHydrated` not reset on rapid re-login (same user, token refresh) | Low | Low | Dependency array `[user?.student_id]` re-triggers the effect on any student_id change; flag resets. |
| Chrome ignores `autoComplete="off"` on some versions | Medium | Low | `data-lpignore="true"` (LastPass/1Password bypass) added as second layer. Structural autofill (new form, fieldset split) is a v2 option if needed. |
| Locale keys missing for logout confirm in some languages | None — audit shows all 13 locales have `confirm.logoutTitle` and `confirm.logoutMessage` | — | DLD lists the exact check command to verify. |
| `useDialog` is `null` in AppShell if DialogProvider is not an ancestor | Low | High | DialogProvider is already mounted at root in `App.jsx:140` above the authenticated route shell; AppShell is inside that tree. |

---

## Key Decisions Requiring Stakeholder Input

1. **Skeleton UX styling:** Should the `—` placeholders use a shimmer/pulse animation on the XP bar background, or is a static empty bar acceptable? (No blocking dependency — dev can choose; just confirm before PR.)
2. **Logout confirm button label:** The modal uses `nav.logout` ("Logout") as the confirm label. Stakeholders may prefer a more explicit label such as "Yes, logout". Current `en.json` key `nav.logout = "Logout"` would serve, but a new key `confirm.logoutConfirm` could be added if desired.
