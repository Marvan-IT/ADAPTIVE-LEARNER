# Execution Plan — Gamification System

**Feature slug:** `gamification-system`
**Date:** 2026-04-13
**Author:** Solution Architect

---

## 1. Work Breakdown Structure (WBS)

All tasks follow the project's Stage 0 → Stage 4 workflow. Effort is expressed in engineer-days (1 day = 6 productive hours).

### Stage 0 — Infrastructure (devops-engineer)

| ID | Title | Description | Effort | Depends On | Component |
|----|-------|-------------|--------|-----------|-----------|
| G0-01 | Apply migration 015 | Run `alembic upgrade head` to apply `015_gamification_system.py`; verify new tables and columns in staging DB | 0.5d | — | Alembic / PostgreSQL |
| G0-02 | Add ORM models to `db/models.py` | Add `XpEvent`, `StudentBadge` ORM classes; add new column mappings to `Student` and `CardInteraction` | 0.5d | G0-01 | `db/models.py` |
| G0-03 | Add gamification constants to `config.py` | Add all 14 new constants (`XP_PER_DIFFICULTY_POINT`, streak tiers, badge threshold, feature flag TTL, leaderboard limits) | 0.5d | — | `config.py` |
| G0-04 | Create `gamification/` package skeleton | Create `backend/src/gamification/__init__.py`, `xp_engine.py`, `streak_engine.py`, `badge_engine.py`, `badge_definitions.py`, `schemas.py`, `feature_flags.py` as empty module stubs with docstrings | 0.5d | G0-03 | `backend/src/gamification/` |

**Stage 0 total: 2 dev-days, 1 calendar day (parallelisable)**

---

### Stage 1 — Design (solution-architect)

Design complete. This document is the Stage 1 output.

| ID | Title | Description | Effort | Depends On | Component |
|----|-------|-------------|--------|-----------|-----------|
| G1-01 | HLD, DLD, execution-plan | Written and delivered | DONE | — | `docs/gamification-system/` |

---

### Stage 2 — Backend (backend-developer)

#### Sub-stage 2A: Core Gamification Module

| ID | Title | Description | Effort | Depends On | Component |
|----|-------|-------------|--------|-----------|-----------|
| G2-01 | Implement `xp_engine.py` | `calculate_xp()` pure function; `award_xp()` async function that inserts `xp_events` row and atomically increments `students.xp`; return `XpResult` | 1.0d | G0-04 | `gamification/xp_engine.py` |
| G2-02 | Implement `streak_engine.py` | `update_streak()` async function; calendar-day comparison logic; five-tier multiplier lookup via constants from `config.py`; return `StreakResult` | 1.0d | G0-04 | `gamification/streak_engine.py` |
| G2-03 | Implement `badge_definitions.py` | `BADGE_REGISTRY` dict with all 13 `BadgeDefinition` entries; `get_badge(key)` and `all_badges()` helper functions | 0.5d | G0-04 | `gamification/badge_definitions.py` |
| G2-04 | Implement `badge_engine.py` | `BadgeContext` dataclass; single aggregate DB query builder; `BADGE_PREDICATES` dict; `evaluate_badges()` async function with ON CONFLICT DO NOTHING inserts | 1.5d | G2-02, G2-03 | `gamification/badge_engine.py` |
| G2-05 | Implement `feature_flags.py` | In-memory cache with 60-second TTL; `get_flag(key, db)` async function; `_refresh()` with `AdminConfig` query; defaults dict | 0.5d | G0-03 | `gamification/feature_flags.py` |
| G2-06 | Implement Pydantic schemas | `XpResult`, `StreakResult`, `BadgeSummary`, `LeaderboardEntry`, `ProgressReportResponse`, `RecordInteractionResponse` in `gamification/schemas.py`; update `RecordInteractionRequest` in `teaching_schemas.py` to add `difficulty: int | None` | 0.5d | G0-03 | `gamification/schemas.py`, `teaching_schemas.py` |

#### Sub-stage 2B: Endpoint Wiring

| ID | Title | Description | Effort | Depends On | Component |
|----|-------|-------------|--------|-----------|-----------|
| G2-07 | Modify `record_card_interaction` | Call `streak_engine`, `xp_engine`, `badge_engine` after interaction save; wrap in try/except with WARNING log on failure; change return type to `RecordInteractionResponse`; persist `difficulty` on `CardInteraction` | 1.5d | G2-01, G2-02, G2-04, G2-05, G2-06 | `teaching_router.py` |
| G2-08 | Create `gamification_router.py` | Implement `GET /leaderboard`, `GET /students/{id}/badges`, `GET /features` endpoints; register router in `main.py` under `/api/v2` prefix | 1.0d | G2-05, G2-06 | `gamification_router.py`, `main.py` |
| G2-09 | Implement admin progress report | `GET /admin/students/{id}/progress-report` in `admin_router.py`; XP-by-day aggregation from `xp_events`; accuracy-by-day from `card_interactions`; badge timeline from `student_badges`; `require_role("admin")` guard | 1.5d | G2-01, G2-03 | `admin_router.py` |
| G2-10 | Wire `difficulty` from adaptive engine | Ensure `difficulty` field from LLM-generated card dict is returned in `next-card` and initial card generation endpoints; confirm it flows to `record-interaction` request | 0.5d | G2-07 | `teaching_service.py`, `adaptive_engine.py` |

**Stage 2 total: 9.5 dev-days**

---

### Stage 3 — Testing (comprehensive-tester)

| ID | Title | Description | Effort | Depends On | Component |
|----|-------|-------------|--------|-----------|-----------|
| G3-01 | Unit tests: XP engine | Test all difficulty levels, hint/wrong combos, streak tiers, minimum floor, zero-difficulty fallback | 1.0d | G2-01 | `tests/test_gamification.py` |
| G3-02 | Unit tests: streak engine | Test first activity, consecutive days, missed days, same-day idempotency, all five multiplier tiers | 1.0d | G2-02 | `tests/test_gamification.py` |
| G3-03 | Unit tests: badge engine | Test all 13 badge predicates (pass + fail); test already-awarded idempotency; test `perfect_chunk` and `speed_demon` edge cases | 1.5d | G2-04 | `tests/test_gamification.py` |
| G3-04 | Unit tests: feature flags | Test TTL refresh, default values on empty DB, per-flag enable/disable path | 0.5d | G2-05 | `tests/test_gamification.py` |
| G3-05 | Integration tests: `record-interaction` | Full pipeline: gamification enabled; gamification disabled; XP failure non-fatal; difficulty NULL fallback; badge awarded in response | 1.5d | G2-07 | `tests/test_gamification_integration.py` |
| G3-06 | Integration tests: endpoints | `GET /leaderboard` enabled/disabled; `GET /badges` ownership check; `GET /features` values; admin progress report 403/200 | 1.0d | G2-08, G2-09 | `tests/test_gamification_integration.py` |
| G3-07 | Concurrency test: badge deduplication | Concurrent `record-interaction` calls for same student; assert exactly one badge row per key | 0.5d | G2-07 | `tests/test_gamification_integration.py` |

**Stage 3 total: 7.0 dev-days**

---

### Stage 4 — Frontend (frontend-developer)

#### Sub-stage 4A: Store and API Layer

| ID | Title | Description | Effort | Depends On | Component |
|----|-------|-------------|--------|-----------|-----------|
| G4-01 | Extend `adaptiveStore.js` | Add `dailyStreak`, `dailyStreakBest`, `streakMultiplier`, `pendingBadges` state; add `setStreakData()`, `addPendingBadges()`, `clearPendingBadges()` actions; hydrate daily streak from `GET /students/{id}` on app start | 0.5d | G2-08 | `store/adaptiveStore.js` |
| G4-02 | Update `sessions.js` API wrapper | Pass `difficulty` in `recordInteraction()` payload; consume and return `{xp_awarded, new_badges}` from response | 0.5d | G2-07 | `api/sessions.js` |
| G4-03 | Add `fetchBadges()` to `students.js` | `GET /api/v2/students/{id}/badges` wrapper; standard error handling | 0.5d | G2-08 | `api/students.js` |
| G4-04 | Create `api/leaderboard.js` | `fetchLeaderboard(limit, offset)` Axios wrapper; handle `enabled: false` response | 0.5d | G2-08 | `api/leaderboard.js` |

#### Sub-stage 4B: Core UI Components

| ID | Title | Description | Effort | Depends On | Component |
|----|-------|-------------|--------|-----------|-----------|
| G4-05 | `BadgeIcon.jsx` | Single badge component; Lucide icon + label + Tailwind tooltip; locked/unlocked visual state | 0.5d | G4-01 | `components/game/BadgeIcon.jsx` |
| G4-06 | `BadgeGrid.jsx` | 4-column grid of all 13 badges; pass `earnedKeys` prop; grayscale for unearned | 0.5d | G4-05 | `components/game/BadgeGrid.jsx` |
| G4-07 | `BadgeCelebration.jsx` | Full-screen Framer Motion overlay; `AnimatePresence`; sequential multi-badge display; auto-dismiss; `onDismiss` callback; i18n strings | 1.5d | G4-05 | `components/game/BadgeCelebration.jsx` |
| G4-08 | `StreakMultiplierBadge.jsx` | Tier-coloured pill showing streak count and multiplier; uses constants matching backend tiers | 0.5d | G4-01 | `components/game/StreakMultiplierBadge.jsx` |
| G4-09 | `LeaderboardMini.jsx` | Top-5 widget for sidebar; handles disabled state; links to `/leaderboard` | 0.5d | G4-04 | `components/game/LeaderboardMini.jsx` |
| G4-10 | `LeaderboardPage.jsx` | Full ranked table; pagination; current-student row highlight; handles `enabled:false`; add route to `App.jsx`; i18n | 1.5d | G4-04 | `pages/LeaderboardPage.jsx`, `App.jsx` |

#### Sub-stage 4C: Integration into Existing Views

| ID | Title | Description | Effort | Depends On | Component |
|----|-------|-------------|--------|-----------|-----------|
| G4-11 | Wire XP response into `CardLearningView` | Replace hardcoded `awardXP(10)` with `awardXP(response.xp_awarded)`; call `addPendingBadges(response.new_badges)`; render `BadgeCelebration` when `pendingBadges.length > 0` | 1.0d | G4-02, G4-07 | `components/learning/CardLearningView.jsx` |
| G4-12 | Add `StreakMultiplierBadge` to card header | Display badge in the card learning view header area; read from `adaptiveStore.streakMultiplier` | 0.5d | G4-08, G4-01 | `components/learning/CardLearningView.jsx` |
| G4-13 | `AdminStudentProgressReport.jsx` | Fetch and render admin progress report; XP-by-day bar chart (CSS or simple SVG); accuracy line; badge list; add link from `AdminStudentDetailPage` | 2.0d | G4-03 | `pages/AdminStudentProgressReport.jsx` |

#### Sub-stage 4D: i18n

| ID | Title | Description | Effort | Depends On | Component |
|----|-------|-------------|--------|-----------|-----------|
| G4-14 | Add i18n keys to all 13 locale files | Badge labels, badge descriptions, leaderboard column headers, celebration messages, disabled-leaderboard message, streak tier labels | 1.0d | G4-05 through G4-10 | `locales/*.json` (13 files) |

**Stage 4 total: 11.5 dev-days**

---

## 2. Phased Delivery Plan

### Phase 1 — Foundation (Stage 0 + Stage 2A)
**Goal:** Database ready, gamification module implemented and unit-tested in isolation. No endpoint changes yet.

**Tasks:** G0-01, G0-02, G0-03, G0-04, G2-01, G2-02, G2-03, G2-04, G2-05, G2-06

**Deliverables:**
- Migration 015 applied to staging DB
- `gamification/` package fully implemented with typed interfaces
- All config constants added to `config.py`
- ORM models updated

**Calendar duration:** 3 days (G0 parallelisable with G2-01/G2-02/G2-03)

---

### Phase 2 — Core Functionality (Stage 2B)
**Goal:** Backend endpoints wired. `record-interaction` returns XP and badges. Leaderboard, badges, features, and progress report endpoints live.

**Tasks:** G2-07, G2-08, G2-09, G2-10

**Deliverables:**
- `POST /sessions/{id}/record-interaction` returns `{saved, xp_awarded, new_badges}`
- `GET /api/v2/leaderboard`, `GET /students/{id}/badges`, `GET /features` operational
- `GET /admin/students/{id}/progress-report` operational
- `difficulty` field persisted to `card_interactions`

**Calendar duration:** 3 days (G2-07 and G2-08 partially parallelisable)

**Critical dependency:** G2-07 must not be deployed to production until G4-11 is merged in the same release batch; otherwise the response shape change is a breaking contract for the frontend.

---

### Phase 3 — Testing (Stage 3)
**Goal:** Full unit and integration test coverage for the backend gamification pipeline.

**Tasks:** G3-01 through G3-07

**Deliverables:**
- `tests/test_gamification.py` — pure unit tests (≥ 90% branch coverage of `gamification/`)
- `tests/test_gamification_integration.py` — endpoint and concurrency integration tests
- All tests passing in CI

**Calendar duration:** 3 days (G3-01 through G3-04 fully parallelisable; G3-05 through G3-07 depend on Phase 2 completion)

---

### Phase 4 — Frontend (Stage 4)
**Goal:** Full UX implemented: XP animations driven by server response, badge celebrations, streak multiplier badge, leaderboard page, admin progress report.

**Tasks:** G4-01 through G4-14

**Deliverables:**
- `adaptiveStore.js` extended
- All 7 new components built
- `CardLearningView` wired to server XP
- Leaderboard route live
- Admin progress report accessible from student detail page
- All 13 locale files updated with gamification strings

**Calendar duration:** 5 days (4A and 4B fully parallelisable; 4C depends on 4A + 4B; 4D can run in parallel with 4C)

---

### Phase 5 — Hardening and Release
**Goal:** Edge cases validated, feature flags verified in staging, rollout executed.

**Tasks (not separately numbered — operational):**
- Verify `LEADERBOARD_ENABLED=false` default in staging `admin_config` table
- Run performance benchmark: 100 concurrent `record-interaction` calls with gamification enabled; confirm p99 ≤ 300 ms
- Review `xp_events` growth rate estimate vs. current `card_interactions` volume
- Validate all 13 badge award conditions with manual test scenarios
- Validate i18n renders correctly for all 13 languages (spot-check: Arabic RTL, Japanese, Malayalam)
- Deploy to production with `GAMIFICATION_ENABLED=true`, all other flags as per product decision
- Monitor `[gamification-failed]` log rate for first 24 hours

**Calendar duration:** 2 days

---

## 3. Dependencies and Critical Path

### Dependency Graph

```
G0-01 ──▶ G0-02
G0-03 ──▶ G0-04 ──▶ G2-01 ──▶ G2-07 ──▶ G3-05 ──▶ G4-11 (CRITICAL PATH)
                    G2-02 ──▶ G2-07
                              G2-04 ──┘
           G0-04 ──▶ G2-05 ──▶ G2-07
           G0-04 ──▶ G2-06 ──▶ G2-07
                    G2-03 ──▶ G2-04
                    G2-08 ──▶ G3-06, G4-02, G4-03, G4-04
                    G2-09 ──▶ G3-06, G4-13
G4-02 ──▶ G4-11
G4-07 ──▶ G4-11
G4-05 ──▶ G4-06, G4-07
G4-04 ──▶ G4-09, G4-10
G4-08, G4-01 ──▶ G4-12
G4-05..G4-10 ──▶ G4-14
```

### Critical Path

**G0-03 → G0-04 → G2-01/G2-02/G2-04 → G2-07 → G3-05 → G4-02 + G4-07 → G4-11**

Estimated critical path duration: **11 calendar days** (with 2 developers working in parallel)

### Blocking External Dependencies

| Dependency | Blocks | Action Required |
|-----------|--------|-----------------|
| Migration 015 applied to staging | All of Phase 2 and beyond | devops-engineer must apply before Phase 2 starts |
| `GET /students/{id}` response must include `daily_streak` and `daily_streak_best` | G4-01 (store hydration) | Backend developer adds these fields to `StudentResponse` schema |
| Badge icon design decision (Lucide vs. custom SVGs) | G4-05, G4-07, G4-14 | Product team decision required before G4-05 starts |
| Feature flag defaults confirmed by product | Phase 5 deployment | Confirm `LEADERBOARD_ENABLED` default before deployment |

---

## 4. Definition of Done (DoD)

### Phase 1 DoD
- [ ] `alembic upgrade head` succeeds on staging DB without errors
- [ ] `xp_events` and `student_badges` tables exist with correct schema
- [ ] `students.daily_streak`, `students.daily_streak_best`, `students.last_active_date` columns present
- [ ] `card_interactions.difficulty` column present (nullable SmallInteger)
- [ ] All 14 config constants present in `config.py`
- [ ] All four `gamification/` modules importable without errors
- [ ] ORM models load cleanly at application startup

### Phase 2 DoD
- [ ] `POST /record-interaction` with `difficulty=3, hints=0, wrong=0` returns `xp_awarded > 0` and `new_badges` array (may be empty for existing students)
- [ ] `POST /record-interaction` with `GAMIFICATION_ENABLED=false` returns `{saved:true, xp_awarded:0, new_badges:[]}`
- [ ] `GET /leaderboard` with `LEADERBOARD_ENABLED=false` returns `{enabled:false, entries:[], total:0}`
- [ ] `GET /features` returns all five flags as booleans
- [ ] `GET /admin/students/{id}/progress-report` returns 403 for non-admin JWT
- [ ] `card_interactions.difficulty` row is set when a card with `difficulty` in the request is recorded
- [ ] `xp_events` row inserted for every successful XP award
- [ ] `students.xp` atomically incremented
- [ ] No regression in existing `record-interaction` behaviour (existing tests still pass)

### Phase 3 DoD
- [ ] `pytest backend/tests/test_gamification.py` passes with ≥ 90% branch coverage on `gamification/` package
- [ ] `pytest backend/tests/test_gamification_integration.py` passes
- [ ] Concurrency test: 10 simultaneous badge evaluations for the same student produce exactly 1 badge row
- [ ] All existing tests continue to pass (`pytest backend/tests/` with no regressions)
- [ ] CI pipeline green

### Phase 4 DoD
- [ ] `CardLearningView` no longer hardcodes `awardXP(10)`; XP burst reflects server-returned value
- [ ] `BadgeCelebration` renders correctly for a single badge and for multiple simultaneous badges
- [ ] `StreakMultiplierBadge` shows correct tier colour for all five tiers
- [ ] `LeaderboardPage` renders ranked list when enabled; shows disabled message when not
- [ ] `AdminStudentProgressReport` renders XP-by-day and badge list for a test student
- [ ] All 13 locale files have all new i18n keys populated (no missing key fallbacks in console)
- [ ] No console errors in the browser on Chrome and Firefox
- [ ] Mobile layout verified at 375px width for all new components

### Phase 5 DoD
- [ ] `LEADERBOARD_ENABLED=false` confirmed as default in production `admin_config`
- [ ] p99 of `record-interaction` ≤ 300 ms under 100 concurrent requests (load test result documented)
- [ ] All 13 badges manually verified to award correctly in staging
- [ ] Zero `[gamification-failed]` log events in staging smoke test
- [ ] Monitoring dashboard confirms `[xp-awarded]` log events fire on correct card completions
- [ ] Feature deployed and announced; post-launch monitoring active for 24 hours

---

## 5. Rollout Strategy

### Deployment Approach: Feature-Flag Gated Rollout

1. **Deploy backend and frontend together** in a single release (contract change to `record-interaction` response requires both sides live simultaneously)
2. **Set `GAMIFICATION_ENABLED=false` in `admin_config`** before deploying — all new code paths are inactive
3. **Run post-deploy smoke tests** against staging with flag disabled; verify no regression
4. **Enable `GAMIFICATION_ENABLED=true`** via admin console — activates XP calculation and badge awards
5. **Enable `BADGES_ENABLED=true`** — activates badge evaluation (depends on GAMIFICATION_ENABLED)
6. **Enable `STREAK_MULTIPLIER_ENABLED=true`** — activates streak multiplier in XP formula
7. **Enable `DIFFICULTY_WEIGHTED_XP_ENABLED=true`** — activates difficulty weighting (vs. flat difficulty=3 fallback)
8. **Defer `LEADERBOARD_ENABLED`** — enable only after confirming with product team

### Rollback Plan

| Scenario | Action |
|---------|--------|
| XP calculation raises exceptions at scale | Set `GAMIFICATION_ENABLED=false` in admin console; effect within 60 seconds (TTL) |
| Badge celebration crashes frontend | Disable via `BADGES_ENABLED=false`; frontend `GET /features` picks up change on next poll |
| `record-interaction` p99 exceeds 500 ms | Set `GAMIFICATION_ENABLED=false`; investigate; consider async background task migration |
| DB contention on `xp_events` insert | Index analysis and VACUUM; short-term: disable GAMIFICATION_ENABLED |
| Migration causes startup failure | `alembic downgrade 014_add_performance_indexes`; redeploy previous backend image |

### Monitoring and Alerting for Launch

**Watch for first 24 hours post-flag-enable:**
- `[gamification-failed]` log count — target: 0
- `[xp-awarded]` log count — target: fires on every correct card answer
- `[badge-awarded]` log count — verify first badges appear within minutes of launch
- `record-interaction` response time p50 and p99 in server logs
- PostgreSQL `xp_events` row count growth rate (confirm it matches card completion rate)

### Post-Launch Validation Steps

1. Manually complete 3 cards as a test student; verify XP increases by the correct computed amount
2. Verify `daily_streak` increments on day 2 of consecutive activity
3. Award `first_correct` badge to a brand-new test student; verify `BadgeCelebration` renders
4. Enable `LEADERBOARD_ENABLED`; verify leaderboard shows the test student
5. Open admin progress report for test student; verify XP-by-day data appears

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|-------------------|
| Phase 1 — Foundation | G0-01 to G0-04 (migration, ORM, config, package skeleton) | 2 dev-days | 1 devops-engineer |
| Phase 2 — Backend Core | G2-01 to G2-10 (gamification module + endpoints) | 9.5 dev-days | 1–2 backend-developer |
| Phase 3 — Testing | G3-01 to G3-07 (unit + integration tests) | 7.0 dev-days | 1 comprehensive-tester |
| Phase 4 — Frontend | G4-01 to G4-14 (store, components, wiring, i18n) | 11.5 dev-days | 1–2 frontend-developer |
| Phase 5 — Hardening/Release | Benchmarks, flag verification, deployment, monitoring | 2.0 dev-days | 1 backend + 1 devops |
| **Total** | **30 tasks** | **32 dev-days** | **3–4 engineers** |

**Estimated calendar duration:**
- With 3 engineers (1 backend, 1 frontend, 1 tester) working in parallel: **~14 calendar days**
- With 4 engineers (2 backend, 1 frontend, 1 tester) working in parallel: **~10 calendar days**

**Critical path duration (minimum achievable):** 11 calendar days with optimal parallelism.

---

## Key Decisions Requiring Stakeholder Input

1. **Release coupling** — Backend and frontend must ship in the same deployment (breaking response contract). Confirm the team can coordinate a joint release, or plan a backward-compatible interim response shape.
2. **Existing XP balances** — Existing `students.xp` values reflect the old flat-10 system. Should they be preserved (additive) or recalculated? A one-time recalculation script would need a separate task outside this WBS.
3. **`LEADERBOARD_ENABLED` default** — Confirm whether this should be `false` (opt-in, privacy-first) or `true` (opt-out). Default is `false` in this design. Product confirmation needed before Phase 5.
4. **Feature flag admin UX** — The five flags must be toggle-able via the admin console. The existing `AdminSettingsPage` uses `admin_config` key/value pairs. Confirm the frontend developer should extend `AdminSettingsPage` with a "Gamification" section, or create a separate settings tab.
5. **`AdminStudentProgressReport` navigation** — Should the progress report be a new page (route `/admin/students/{id}/report`) or a tab within the existing `AdminStudentDetailPage`? Influences G4-13 scope.
