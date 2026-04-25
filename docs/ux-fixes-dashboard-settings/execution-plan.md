# Execution Plan — UX Fixes: Dashboard & Settings

**Slug:** `ux-fixes-dashboard-settings`
**Date:** 2026-04-23

---

## 1. Work Breakdown Structure (WBS)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| P0-01 | Design docs | This document. | 0.5d | — | Docs |
| P1-01 | Backend: add `age` to GET dict | In `teaching_router.py:287–299`, add `"age": student.age,` to the return dict | 0.25d | P0-01 | Backend |
| P2-01 | Test: `age` round-trip assertion | In `backend/tests/test_api_integration.py`, add `test_get_student_includes_age_field` — PATCH age=22 then GET and assert `age == 22`; PATCH null then GET and assert `age is None` | 0.5d | P1-01 | Backend/Tests |
| P2-02 | Test: Playwright spec skeleton | Create `frontend/tests/e2e/ux-fixes.spec.js` with XP skeleton block (mock `GET /api/v2/students/{id}` with 300ms delay, assert `—` then real values) | 0.75d | P3-01 | Frontend/Tests |
| P2-03 | Test: Playwright spec logout confirm | In `frontend/tests/e2e/ux-fixes.spec.js`, add logout confirm block (cancel path + confirm path) | 0.5d | P3-04 | Frontend/Tests |
| P3-01 | Frontend: `isHydrated` on StudentContext | Add `isHydrated` state to `StudentContext.jsx`; reset in early-return branch; set true after `initAdaptive()` in effect, `refreshStudent()`, and `selectStudent()`; expose in Provider value | 0.5d | P0-01 | Frontend |
| P3-02 | Frontend: skeleton in StudentSidebar | In `StudentSidebar.jsx`, destructure `isHydrated`; gate level badge number, level label, XP progress text, and progress bar width on `isHydrated` | 0.25d | P3-01 | Frontend |
| P3-03 | Frontend: skeleton in DashboardPage | In `DashboardPage.jsx`, destructure `isHydrated`; gate XP stat card `label` and `value` on `isHydrated` | 0.25d | P3-01 | Frontend |
| P3-04 | Frontend: logout confirm in AppShell | Import `useDialog`; call `dialog.confirm({ variant: "danger", ... })` in logout handler; guard `if (!confirmed) return` | 0.5d | P0-01 | Frontend |
| P3-05 | Frontend: autofill attrs on SettingsPage | Add `type="text"`, `name="custom-interest"`, `autoComplete="off"`, `data-lpignore="true"` to custom-interest `<input>` at line 296 | 0.25d | P0-01 | Frontend |
| P3-06 | i18n: audit all 13 locale files | Run audit script (see §4 below) to confirm `confirm.logoutTitle`, `confirm.logoutMessage`, `nav.logout`, and nested `confirm.cancel` exist in all 13 files; backfill any missing | 0.25d | P0-01 | Frontend |

**Total estimated effort: 4.5 dev-days**

---

## 2. Phased Delivery Plan

### Phase 1 — Foundation (no blockers)

Run in parallel. Each change is independent of the others.

| Task | File | Change |
|------|------|--------|
| P1-01 | `backend/src/api/teaching_router.py` | Add `"age": student.age,` |
| P3-05 | `frontend/src/pages/SettingsPage.jsx` | Add autofill attrs |
| P3-06 | `frontend/src/locales/*.json` (13 files) | Audit + backfill i18n |

Completion gate: `pytest backend/tests/test_api_integration.py -k test_get_student` passes; `npm run lint` passes.

### Phase 2 — Core Functionality

Depends on Phase 1 being merged or in-branch.

| Task | File | Depends on |
|------|------|-----------|
| P3-01 | `frontend/src/context/StudentContext.jsx` | P3-06 (locale audit done) |
| P3-04 | `frontend/src/components/layout/AppShell.jsx` | P3-06 (locale audit done) |

Run P3-01 and P3-04 in parallel — they touch independent files.

Completion gate: manual dev-server check: login → sidebar shows `—` briefly, then real values; logout → modal appears → cancel works → confirm works.

### Phase 3 — Dependent Frontend

Depends on P3-01 completing.

| Task | File | Depends on |
|------|------|-----------|
| P3-02 | `frontend/src/components/layout/StudentSidebar.jsx` | P3-01 |
| P3-03 | `frontend/src/pages/DashboardPage.jsx` | P3-01 |

Completion gate: `npm run lint` passes; manual check confirms no flicker on login.

### Phase 4 — Tests

Depends on Phase 2 + Phase 3 completing.

| Task | File | Depends on |
|------|------|-----------|
| P2-01 | `backend/tests/test_api_integration.py` | P1-01 |
| P2-02 | `frontend/tests/e2e/ux-fixes.spec.js` (new) | P3-01, P3-02, P3-03 |
| P2-03 | `frontend/tests/e2e/ux-fixes.spec.js` (append) | P3-04 |

Note: Before writing P2-02 / P2-03, confirm `playwright.config.js` exists or create it. The project has no `frontend/tests/e2e/` directory yet — the frontend-developer must initialise it and ensure `npm run test:e2e` resolves the new spec.

Completion gate: `pytest backend/tests/test_api_integration.py -k age` passes; `npm run test:e2e` passes (or at minimum the two new test blocks pass).

### Phase 5 — Release

| Step | Action |
|------|--------|
| 5.1 | Final `npm run lint` from `frontend/` — zero errors |
| 5.2 | Final `pytest backend/tests/test_api_integration.py` from `backend/` (venv active) |
| 5.3 | Manual regression: login → verify XP/level populates without flicker; visit Settings → verify age pre-populated; focus custom-interest field → verify no email autofill; click logout → verify modal; cancel logout → verify no navigation; confirm logout → verify /login |
| 5.4 | Deploy backend (patch to `teaching_router.py` — zero-downtime, no migration) |
| 5.5 | Deploy frontend (Vite build + static deploy) |

---

## 3. Dependencies and Critical Path

```
P0-01 (docs)
  ├── P1-01 (backend age) ──► P2-01 (test age round-trip)
  ├── P3-05 (autofill attrs)
  ├── P3-06 (i18n audit)
  │     ├── P3-01 (isHydrated) ──► P3-02 (sidebar skeleton)
  │     │                    └──► P3-03 (dashboard skeleton)
  │     │                              └──► P2-02 (playwright skeleton)
  │     └── P3-04 (logout confirm) ──────► P2-03 (playwright confirm)
```

**Critical path:** `P3-01 → P3-02 + P3-03 → P2-02` (2.0d of sequential work after P0-01).

**Blocking external dependencies:** None. All changes are within the frontend and `teaching_router.py`. No other team or service is required.

---

## 4. Definition of Done

### Phase 1 DoD
- [ ] `GET /api/v2/students/{student_id}` response includes `"age"` for a student with age set and for a student with age null.
- [ ] `npm run lint` passes with zero errors on `SettingsPage.jsx`.
- [ ] All 13 locale files contain `confirm.logoutTitle`, `confirm.logoutMessage`, `nav.logout`, and `confirm.cancel` (nested).

### Phase 2 DoD
- [ ] `StudentContext` exports `isHydrated` boolean; value is `false` on mount and before `initAdaptive()` fires; `true` immediately after `initAdaptive()` in the effect, `refreshStudent()`, and `selectStudent()`.
- [ ] `isHydrated` resets to `false` when `user?.student_id` is falsy (logout / user change).
- [ ] `AppShell` logout button opens `dialog.confirm()` modal; Cancel leaves route unchanged; Confirm logs out and navigates to `/login`.

### Phase 3 DoD
- [ ] `StudentSidebar` shows `—` for level badge number, level label, and XP text when `!isHydrated`; shows `"0%"` progress bar width.
- [ ] `DashboardPage` XP stat card shows `—` for label and value when `!isHydrated`.
- [ ] No flash of `Lv.1 · 0 XP` visible on fresh login in a 3G-throttled dev-tools session.

### Phase 4 DoD
- [ ] `pytest backend/tests/test_api_integration.py::TestStudentEndpoints::test_get_student_includes_age_field` passes (or named equivalent).
- [ ] `npm run test:e2e` executes `ux-fixes.spec.js`; XP skeleton test passes; logout confirm test passes (cancel and confirm paths).

### Phase 5 DoD (Release)
- [ ] All above criteria met.
- [ ] `npm run lint` clean.
- [ ] Manual regression checklist in §2 Phase 5 passed.
- [ ] Backend deployed; no 5xx on `GET /api/v2/students/{id}` post-deploy.

---

## 5. Verification Commands

Run from `backend/` with venv active (`source ../.venv/bin/activate`):
```bash
# Run only student-endpoint tests
pytest backend/tests/test_api_integration.py -k "student" -v

# Run age round-trip test specifically (once written)
pytest backend/tests/test_api_integration.py -k "age" -v
```

Run from `frontend/`:
```bash
# Lint check
npm run lint

# e2e tests (Playwright, Chromium, 60s timeout per CLAUDE.md)
npm run test:e2e

# Dev server (manual check)
npm run dev
```

i18n audit (run from `frontend/`):
```bash
for f in src/locales/*.json; do
  echo "=== $(basename $f) ==="
  python3 -c "
import json, sys
d = json.load(open('$f'))
flat_keys = ['confirm.logoutTitle', 'confirm.logoutMessage', 'nav.logout']
nested_cancel = d.get('confirm', {}).get('cancel')
for k in flat_keys:
    print(k, '->', d.get(k, 'MISSING'))
print('confirm.cancel ->', nested_cancel or 'MISSING')
"
done
```

---

## 6. Rollout Strategy

**Deployment approach:** Standard deploy. No feature flags required — all four fixes are either invisible to users until they trigger them (P3 fixes) or are backend data corrections (P1-01). No canary needed given the low risk surface.

**Rollback plan:**
- Backend: revert the one-line dict change in `teaching_router.py` and redeploy. `age` returning null/absent does not break the frontend (SettingsPage already handles null).
- Frontend: revert the Vite build and redeploy static assets. All changes are additive or trivial substitutions; the previous build is a clean rollback.

**Post-deploy validation:**
1. Login as a student with a known XP value → confirm sidebar shows correct value within 2s, no flicker.
2. Login as a student with a saved age → confirm Settings age field pre-populated.
3. Focus the custom-interest input → confirm no email autofill.
4. Click logout → confirm modal appears → click Cancel → confirm no navigation.

---

## 7. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| 1 — Foundation | P1-01 (age dict), P3-05 (autofill), P3-06 (i18n audit) | 0.75d | 1 backend-developer + 1 frontend-developer (parallel) |
| 2 — Core Functionality | P3-01 (isHydrated), P3-04 (logout confirm) | 1.0d | 1 frontend-developer |
| 3 — Dependent Frontend | P3-02 (sidebar skeleton), P3-03 (dashboard skeleton) | 0.5d | 1 frontend-developer |
| 4 — Tests | P2-01 (backend), P2-02 + P2-03 (playwright) | 1.75d | 1 backend-developer + 1 frontend-developer |
| 5 — Release | Lint, pytest, manual regression, deploy | 0.5d | 1 developer |
| **Total** | | **4.5 dev-days** | **2 developers (parallelised to ~2.5 calendar days)** |
