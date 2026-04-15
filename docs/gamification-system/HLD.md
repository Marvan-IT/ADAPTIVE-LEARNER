# High-Level Design — Gamification System

**Feature slug:** `gamification-system`
**Date:** 2026-04-13
**Author:** Solution Architect

---

## 1. Executive Summary

### Feature Name and Purpose
The Gamification System upgrades ADA's existing cosmetic XP mechanic into a meaningful, data-driven progression layer. Students receive XP that reflects the real difficulty of their work, maintain daily activity streaks with compounding multipliers, earn achievement badges at key milestones, and can optionally view their standing on a leaderboard. Administrators gain progress-report visibility into XP trends, accuracy, and badge acquisition over time.

### Business Problem Being Solved
The existing XP system awards a flat 10 XP per correct card answer regardless of difficulty, never persists streak data reliably to the database, has no badge system, and has no reporting surface. Students have no signal that sustained effort is rewarded above casual effort, and administrators cannot measure engagement over time. This reduces retention and limits the platform's ability to motivate consistent daily learning.

### Key Stakeholders
- **Students** — primary recipients of XP, streaks, badges, leaderboard ranking
- **Platform administrators** — consumers of progress reports, leaderboard toggle, feature flags
- **Backend developers** — implement new `gamification/` module and modified `record-interaction` endpoint
- **Frontend developers** — implement badge celebration UX, leaderboard page, and store migration

### Scope

**Included:**
1. Difficulty-weighted XP formula applied at card-interaction record time
2. Calendar-day daily streaks tracked server-side with five multiplier tiers
3. 13 achievement badges with idempotent award logic and celebration animation
4. Opt-in XP leaderboard (admin-toggleable)
5. Admin progress reports: XP trend, accuracy, badge timeline per student
6. Five feature flags via `AdminConfig` (GAMIFICATION_ENABLED, LEADERBOARD_ENABLED, BADGES_ENABLED, STREAK_MULTIPLIER_ENABLED, DIFFICULTY_WEIGHTED_XP_ENABLED)
7. Full i18n coverage across all 13 supported languages

**Excluded:**
- Social features (friend lists, challenges, direct messaging)
- Team/classroom leaderboards
- Paid or consumable rewards
- Push/email notifications for streak recovery
- Badge NFT or exportable certificates
- Real-time leaderboard websocket updates (polling only)

---

## 2. Functional Requirements

### Core Capabilities

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-01 | XP awarded per card interaction must be proportional to card difficulty (1–5 scale) | Must |
| FR-02 | Hint usage and wrong attempts must reduce XP earned for that card | Must |
| FR-03 | First-attempt correct answers (no hints, no wrong attempts) must earn a 1.5× bonus | Must |
| FR-04 | A calendar-day activity streak must be tracked server-side and reset on missed days | Must |
| FR-05 | Streak multiplier must escalate through five tiers (1.0× → 2.5×) | Must |
| FR-06 | 13 defined badges must be awarded idempotently at milestone events | Must |
| FR-07 | Badge award must trigger a celebration animation on the student UI | Must |
| FR-08 | An XP leaderboard must be available when the admin enables it | Should |
| FR-09 | The leaderboard must be hidden (HTTP 403) when LEADERBOARD_ENABLED is false | Must |
| FR-10 | Admins must be able to view a per-student progress report | Should |
| FR-11 | All five gamification features must be individually togglable at runtime via AdminConfig | Must |
| FR-12 | All user-facing strings must be translated across all 13 supported languages | Must |
| FR-13 | Card difficulty assigned at generation time must be persisted to `card_interactions.difficulty` | Must |
| FR-14 | Every XP award must be recorded in `xp_events` for audit and reporting | Must |

### User Stories

1. **As a student**, I want the XP I earn to reflect how hard the card was so that difficult work feels more rewarding than easy work.
2. **As a student**, I want to see my daily streak grow each day I study, with a higher multiplier as a visible reward for consistency.
3. **As a student**, I want to receive a badge and celebration animation when I reach a milestone so that progress feels meaningful.
4. **As a student**, I want to see where I stand relative to peers (when enabled) to motivate continued learning.
5. **As an administrator**, I want to toggle the leaderboard off for younger students or privacy-sensitive cohorts.
6. **As an administrator**, I want a per-student progress report showing XP trends, accuracy over time, and badge history.
7. **As an administrator**, I want to enable or disable individual gamification features at runtime without redeployment.

---

## 3. Non-Functional Requirements

### Performance
- `record-interaction` endpoint (now XP-augmented) must complete in ≤ 300 ms p99 under normal load (≤ 50 concurrent students)
- Leaderboard endpoint must complete in ≤ 500 ms for up to 10,000 students (uses indexed aggregate query — no per-request full scan)
- Badge evaluation must complete in ≤ 100 ms; executed in the same DB transaction as the interaction save

### Scalability
- `xp_events` is append-only; indexed on `(student_id, created_at)` and `(student_id, event_type)` — supports time-range sum queries without full-table scans
- `student_badges` UNIQUE constraint on `(student_id, badge_key)` makes award logic safe to call concurrently (INSERT … ON CONFLICT DO NOTHING)
- Feature flags are read from `AdminConfig` at startup and cached in-memory with a 60-second TTL to avoid per-request DB lookups

### Availability and Reliability
- XP award failure must be non-fatal; interaction is saved with `{"saved": true}` even if XP calculation throws; failure logged at WARNING level
- Badge evaluation failure is non-fatal; interaction proceeds; failure logged separately
- Streak update uses an atomic `UPDATE students SET daily_streak = ..., last_active_date = :today WHERE id = :id` — no separate read-update race condition

### Security and Compliance
- Leaderboard returns only `display_name` and `xp` — no email, no student UUID exposed
- Student can only read their own badges (`_validate_student_ownership` enforced)
- Admin progress report behind `require_role("admin")` dependency
- Feature flag reads go through the existing `AdminConfig` table — no separate env-var surface for attackers to enumerate

### Maintainability and Observability
- `xp_events` table provides full audit trail; every XP change is traceable to an interaction and event type
- Structured log fields: `[xp-awarded]`, `[badge-awarded]`, `[streak-updated]` — consistent prefix for log aggregation
- Badge definitions in a single registry file (`badge_definitions.py`) — adding a new badge requires editing one file only
- All new config constants in `config.py` — no magic numbers in business logic

---

## 4. System Context Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                        ADA Platform                                 │
│                                                                     │
│  ┌─────────────────────────┐     ┌──────────────────────────────┐  │
│  │   React Frontend        │     │   FastAPI Backend             │  │
│  │                         │     │                              │  │
│  │  CardLearningView       │────▶│  POST /sessions/{id}/        │  │
│  │  (records interaction)  │     │  record-interaction          │  │
│  │                         │◀────│  ← {saved, xp_awarded,       │  │
│  │  XPBurst animation      │     │      new_badges}             │  │
│  │  BadgeCelebration       │     │         │                    │  │
│  │  StreakMultiplierBadge   │     │         ▼                    │  │
│  │                         │     │  gamification/               │  │
│  │  GET /leaderboard       │────▶│    xp_engine.py              │  │
│  │  LeaderboardPage        │◀────│    streak_engine.py          │  │
│  │                         │     │    badge_engine.py           │  │
│  │  GET /badges            │────▶│    badge_definitions.py      │  │
│  │  BadgeGrid (profile)    │◀────│         │                    │  │
│  │                         │     │         ▼                    │  │
│  │  Admin: progress report │────▶│  GET /admin/students/{id}/   │  │
│  │  AdminStudentProgressReport◀──│  progress-report             │  │
│  │                         │     │         │                    │  │
│  │  GET /features          │────▶│  GET /api/v2/features        │  │
│  └─────────────────────────┘     └──────────────────────────────┘  │
│                                           │                         │
│                                           ▼                         │
│                                  ┌────────────────┐                 │
│                                  │  PostgreSQL 15  │                 │
│                                  │                │                 │
│                                  │  students      │                 │
│                                  │  xp_events     │                 │
│                                  │  student_badges│                 │
│                                  │  card_interact.│                 │
│                                  │  admin_config  │                 │
│                                  └────────────────┘                 │
└────────────────────────────────────────────────────────────────────┘

External actors:
  [Student browser] ──▶ React SPA ──▶ FastAPI ──▶ PostgreSQL
  [Admin browser]   ──▶ React SPA ──▶ FastAPI ──▶ PostgreSQL
```

**Data flow summary:**
1. Student answers a card → `CardLearningView` calls `POST /sessions/{id}/record-interaction`
2. Backend saves `CardInteraction` row, then calls `xp_engine.calculate()` → `streak_engine.update()` → `badge_engine.evaluate()`
3. `xp_engine` writes to `xp_events` and updates `students.xp`; `streak_engine` updates `students.daily_streak` and related columns; `badge_engine` inserts to `student_badges` (ON CONFLICT DO NOTHING)
4. Response carries `xp_awarded` and `new_badges[]` back to frontend
5. Frontend plays `XPBurst` for XP gain and `BadgeCelebration` for each new badge

---

## 5. Architectural Style and Patterns

### Selected Style: Modular Service Layer within Monolith

The gamification logic is encapsulated in a new `backend/src/gamification/` package with four pure/near-pure modules invoked synchronously from the existing `record-interaction` endpoint. No new microservice is introduced.

**Justification:**
- ADA is a single-server FastAPI monolith; adding a microservice would introduce network latency, deployment complexity, and distributed transaction risk for no scale benefit at current load (< 1,000 concurrent students)
- The gamification computation (XP formula + streak update + badge evaluation) is CPU-light and completes in < 5 ms; running it in the same request path does not affect P99 latency targets
- Shared SQLAlchemy `AsyncSession` allows the interaction save, XP event write, streak update, and badge insert to participate in the same transaction, ensuring atomicity without a saga pattern

**Alternatives considered:**

| Alternative | Rejected because |
|-------------|-----------------|
| Async background task (FastAPI BackgroundTasks) | XP result must be in the response payload (frontend needs it to animate); background task cannot return data to the caller |
| Separate gamification microservice | Distributed transaction complexity, deployment overhead, latency budget consumed — no scale benefit at this size |
| Event-driven (publish event, consume async) | Same problem as background task for synchronous response requirement; adds broker dependency |

### Patterns Used
- **Pure-function calculation core** — `xp_engine.calculate_xp()` and `badge_engine.evaluate_badges()` take only data parameters; no I/O — enables exhaustive unit testing without mocking
- **Repository pattern via SQLAlchemy** — all DB writes go through the passed `AsyncSession`, never direct engine access inside the gamification module
- **Feature flag registry** — `AdminConfig` key/value pairs, cached in-memory with TTL, consulted before each gamification code path
- **Idempotent badge award** — `INSERT INTO student_badges … ON CONFLICT DO NOTHING` at the DB level; application layer may call `award_badge()` multiple times safely
- **Append-only audit log** — `xp_events` is never updated or deleted by application code; provides event sourcing capability for progress reports

---

## 6. Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Backend framework | FastAPI 0.110+ (async) | Existing stack — no change |
| ORM | SQLAlchemy 2.0 async | Existing stack; async session shared with gamification module |
| Database | PostgreSQL 15 | Existing stack; JSONB for metadata, Date type for streak date comparison |
| Migration | Alembic 1.13 | Migration `015_gamification_system.py` already created |
| Frontend framework | React 19 + Vite 7 | Existing stack |
| Frontend state | Zustand 5 (`adaptiveStore.js`) | Already used for XP/level/streak state — extend, not replace |
| Animations | Framer Motion 12 | Already installed; used for XPBurst — reuse for BadgeCelebration |
| i18n | i18next 25 | Existing stack; all new strings must go through `t()` |
| Styling | Tailwind CSS 4 + inline styles | Existing convention |

No new dependencies are required for the backend or frontend.

---

## 7. Key Architectural Decisions (ADRs)

### ADR-01: XP Calculation Happens Synchronously at record-interaction Time

**Decision:** Calculate and persist XP inside the `record-interaction` request handler, not asynchronously.

**Options considered:**
- Option A: Synchronous in the request handler (chosen)
- Option B: FastAPI `BackgroundTask` post-response
- Option C: Scheduled batch recalculation

**Rationale:** The frontend needs `xp_awarded` and `new_badges` in the HTTP response to drive UI animations. Background or batch processing cannot fulfill this. The computation is < 5 ms; it does not affect the latency target.

**Trade-off:** Adds ~5 ms to `record-interaction` response time. Acceptable given the 300 ms p99 budget.

---

### ADR-02: Streak is Tracked Per Calendar Day, Server-Side

**Decision:** Use a `Date`-type `last_active_date` column compared against `datetime.utcnow().date()` at XP-award time; never rely on the frontend to manage the streak boundary.

**Options considered:**
- Option A: Server-side Date comparison (chosen)
- Option B: Frontend manages streak with local storage
- Option C: Streak based on consecutive lesson days (previous behavior of `streak` column)

**Rationale:** Client-side state is unreliable across devices, browser clears, and time zones. The previous `streak` column tracked lesson days loosely; the new `daily_streak` column enforces a calendar-day boundary that is reproducible and auditable. The `xp_events` table provides the ground truth.

**Trade-off:** UTC date is used server-side. Students in UTC+12 to UTC+14 may see a streak day boundary up to 14 hours earlier than their local midnight. This is a known limitation; adding per-student timezone support is deferred.

---

### ADR-03: Badge Definitions Live in a Registry File, Not the Database

**Decision:** Store badge metadata (key, label, description, icon, threshold) in `badge_definitions.py` as a typed registry, not as database rows.

**Options considered:**
- Option A: Python registry file (chosen)
- Option B: `admin_config` JSONB rows per badge
- Option C: Separate `badge_types` table

**Rationale:** Badge definitions change infrequently and only with a code deploy. A Python registry provides type safety, IDE navigation, and is co-located with the evaluation logic. Storing definitions in the DB adds CRUD overhead and migration risk for no operational benefit at this scale.

**Trade-off:** Adding a new badge requires a code deploy. For 13 defined badges this is acceptable. If the product team requires admin-defined custom badges in the future, the registry can be replaced with a DB table.

---

### ADR-04: Leaderboard Returns Aggregated XP from the students Table, Not xp_events

**Decision:** The leaderboard query reads `students.xp` (the running total column) rather than summing `xp_events.final_xp`.

**Options considered:**
- Option A: Read `students.xp` (chosen)
- Option B: `SELECT SUM(final_xp) FROM xp_events GROUP BY student_id ORDER BY SUM DESC`

**Rationale:** `students.xp` is updated atomically on every XP award. Reading it is an O(N) indexed scan on a single column. The `xp_events` aggregate would require a full table scan on a high-churn append-only table, adding seconds of latency as the table grows.

**Trade-off:** If `students.xp` ever diverges from the sum of `xp_events.final_xp` (e.g., manual admin correction), the leaderboard shows the running total, not the audit-verified sum. The admin progress report reconciles these. An hourly reconciliation job can be added in Phase 4.

---

### ADR-05: Feature Flags Cached In-Memory with 60-Second TTL

**Decision:** Feature flag values are loaded from `AdminConfig` at startup and refreshed every 60 seconds, not read per request.

**Rationale:** Reading `AdminConfig` on every `record-interaction` call would add a DB round-trip to the hot path. Feature flags change at most once per admin action. A 60-second staleness window is acceptable for non-critical toggles.

**Trade-off:** After toggling a flag in the admin console, up to 60 seconds may elapse before the new value takes effect on the backend. The admin console must display a note to this effect.

---

## 8. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| `record-interaction` latency increases unacceptably due to badge evaluation DB queries | Low | High | Badge evaluation uses indexed queries only; benchmark during Phase 3; fall back to async background task if p99 > 250 ms |
| XP divergence between `students.xp` running total and `xp_events` sum | Low | Medium | Admin progress report exposes both values; add optional reconciliation endpoint for admins |
| Streak reset due to UTC vs. local-midnight boundary feels unfair to students | Medium | Medium | Communicate clearly in UI that streaks follow UTC; add per-student timezone offset support in a future iteration |
| Badge evaluation called concurrently for the same student (parallel card sessions) | Low | Low | `student_badges` UNIQUE constraint + ON CONFLICT DO NOTHING provides DB-level idempotency; no double-award possible |
| Frontend hardcoded `awardXP(10)` in `CardLearningView.jsx` continues to fire alongside server-side XP | High | Medium | During Phase 2, remove the hardcoded `awardXP(10)` call; replace with `awardXP(response.xp_awarded)` driven by the `record-interaction` response |
| Feature flag cache staleness causes confusion in A/B testing | Low | Low | Document the 60-second TTL; admin console shows "changes take effect within 60 seconds" |
| Leaderboard exposes privacy concerns for minor students | Medium | High | LEADERBOARD_ENABLED defaults to `false`; admin must explicitly opt in; leaderboard shows display_name only, no UUIDs |
| `card_interactions.difficulty` NULL for cards generated before this migration | Certain | Low | XP engine uses `difficulty or 3` as a fallback (median difficulty); NULL rows are never penalised |

---

## Key Decisions Requiring Stakeholder Input

1. **Streak timezone policy** — Should streak boundaries use UTC (current design) or per-student local timezone? Implementing per-student timezone requires a new `timezone` column on `students` and adds complexity.
2. **Leaderboard default state** — Should `LEADERBOARD_ENABLED` default to `true` (opt-out) or `false` (opt-in)? Current design defaults to `false` (opt-in) for privacy. Confirm with product.
3. **XP_PER_DIFFICULTY_POINT value** — Default is 4 (difficulty 3 card = 12 base XP vs. old flat 10). Confirm this feels right relative to legacy XP balances stored in `students.xp`.
4. **Badge icon assets** — Are custom SVG/PNG badge icons being designed by a designer, or will the frontend developer use Lucide React icons as placeholders?
5. **Progress report retention window** — Should `xp_events` be queryable for all time (no retention policy) or limited to a rolling window (e.g., 12 months)? Current design has no retention policy.
6. **Leaderboard scope** — Is the leaderboard global (all students of all books) or per-book? Current design is global. Confirm with product.
