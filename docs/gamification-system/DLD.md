# Detailed Low-Level Design — Gamification System

**Feature slug:** `gamification-system`
**Date:** 2026-04-13
**Author:** Solution Architect

---

## 1. Component Breakdown

### Backend Components

#### `backend/src/gamification/` (new package)

| Module | Single Responsibility | I/O |
|--------|-----------------------|-----|
| `xp_engine.py` | Pure XP formula calculation; DB write of `xp_events` row; atomic `students.xp` increment | Input: difficulty, hints, wrong_attempts, daily_streak. Output: `XpResult(base_xp, multiplier, final_xp)` |
| `streak_engine.py` | Read `students.last_active_date`; compare to today (UTC); update `daily_streak`, `daily_streak_best`, `last_active_date`; return current multiplier | Input: student DB row. Output: `StreakResult(daily_streak, multiplier, streak_broke)` |
| `badge_engine.py` | Evaluate all 13 badge conditions against current student state; insert newly earned badges; return list of newly awarded badge keys | Input: student state dict, db session. Output: `list[str]` new badge keys |
| `badge_definitions.py` | Registry of 13 `BadgeDefinition` dataclass instances; provides `get_badge(key)` and `all_badges()` | No I/O — static data |
| `schemas.py` | Pydantic models for gamification responses (`XpResult`, `BadgeSummary`, `LeaderboardEntry`, `ProgressReportResponse`) | No I/O |

#### Modified Backend Files

| File | Change |
|------|--------|
| `backend/src/api/teaching_router.py` | `record_card_interaction` endpoint: call gamification pipeline; return `{saved, xp_awarded, new_badges}` |
| `backend/src/api/teaching_schemas.py` | Add `RecordInteractionResponse` schema; add `difficulty: int | None` to `RecordInteractionRequest` |
| `backend/src/db/models.py` | Add ORM models for `XpEvent`, `StudentBadge`; add columns to `Student` and `CardInteraction` |
| `backend/src/config.py` | Add all gamification constants |
| `backend/src/api/admin_router.py` | Add `GET /admin/students/{id}/progress-report` endpoint |
| `backend/src/adaptive/prompt_builder.py` | Pass card `difficulty` in generated card dict so `record-interaction` can persist it |

#### New Backend Endpoint Files

| File | Purpose |
|------|---------|
| `backend/src/api/gamification_router.py` | New router: `GET /leaderboard`, `GET /students/{id}/badges`, `GET /features` |

### Frontend Components

#### New Components

| Component | File | Purpose |
|-----------|------|---------|
| `BadgeCelebration` | `components/game/BadgeCelebration.jsx` | Full-screen overlay with Framer Motion celebration for badge award |
| `BadgeGrid` | `components/game/BadgeGrid.jsx` | Grid display of all 13 badges; locked/unlocked state |
| `BadgeIcon` | `components/game/BadgeIcon.jsx` | Single badge icon with tooltip — Lucide icon + label |
| `StreakMultiplierBadge` | `components/game/StreakMultiplierBadge.jsx` | Compact inline badge showing current streak multiplier tier |
| `LeaderboardMini` | `components/game/LeaderboardMini.jsx` | Top-5 sidebar widget (used on ConceptMapPage) |
| `LeaderboardPage` | `pages/LeaderboardPage.jsx` | Full leaderboard table with pagination |
| `AdminStudentProgressReport` | `pages/AdminStudentProgressReport.jsx` | Admin view: XP trend chart, accuracy timeline, badge list |

#### Modified Frontend Files

| File | Change |
|------|--------|
| `store/adaptiveStore.js` | Add `dailyStreak`, `dailyStreakBest`, `streakMultiplier`, `newBadges`, `setStreakData()`, `addBadges()` actions |
| `components/learning/CardLearningView.jsx` | Replace hardcoded `awardXP(10)` with `awardXP(response.xp_awarded)`; handle `new_badges` from response |
| `api/sessions.js` | Update `recordInteraction()` to pass `difficulty` and consume `{xp_awarded, new_badges}` response |
| `api/students.js` | Add `fetchBadges(studentId)` |
| `api/leaderboard.js` | New file: `fetchLeaderboard(limit, offset)` |
| `App.jsx` | Add route `/leaderboard` → `LeaderboardPage` |
| `locales/*.json` | Add i18n keys for all new UI strings (13 files) |

---

## 2. Data Design

### New ORM Models (additions to `db/models.py`)

```python
class XpEvent(Base):
    __tablename__ = "xp_events"

    id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    student_id: Mapped[UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("teaching_sessions.id", ondelete="SET NULL"), nullable=True
    )
    interaction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("card_interactions.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Event types: CARD_CORRECT, CARD_MASTERY, CARD_CONSOLATION
    base_xp: Mapped[int] = mapped_column(Integer, nullable=False)
    multiplier: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0")
    final_xp: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata: Mapped[dict | None] = mapped_column(postgresql.JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class StudentBadge(Base):
    __tablename__ = "student_badges"
    __table_args__ = (
        UniqueConstraint("student_id", "badge_key", name="uq_student_badges_student_badge"),
    )

    id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    student_id: Mapped[UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    badge_key: Mapped[str] = mapped_column(String(50), nullable=False)
    awarded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    metadata: Mapped[dict | None] = mapped_column(postgresql.JSONB, nullable=True)
```

### Additions to Existing ORM Models

```python
# Student — new columns (added by migration 015)
daily_streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
daily_streak_best: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
last_active_date: Mapped[date | None] = mapped_column(Date, nullable=True)

# CardInteraction — new column (added by migration 015)
difficulty: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
```

### Badge Definitions Registry

```python
# backend/src/gamification/badge_definitions.py
from dataclasses import dataclass

@dataclass(frozen=True)
class BadgeDefinition:
    key: str          # unique slug — matches student_badges.badge_key
    label_i18n: str   # i18n key for display label
    description_i18n: str  # i18n key for description
    icon: str         # Lucide icon name

BADGE_REGISTRY: dict[str, BadgeDefinition] = {
    "first_correct":   BadgeDefinition("first_correct",   "badge.first_correct.label",   "badge.first_correct.desc",   "CheckCircle"),
    "first_mastery":   BadgeDefinition("first_mastery",   "badge.first_mastery.label",   "badge.first_mastery.desc",   "Star"),
    "mastery_5":       BadgeDefinition("mastery_5",       "badge.mastery_5.label",       "badge.mastery_5.desc",       "BookOpen"),
    "mastery_10":      BadgeDefinition("mastery_10",      "badge.mastery_10.label",      "badge.mastery_10.desc",      "BookMarked"),
    "mastery_25":      BadgeDefinition("mastery_25",      "badge.mastery_25.label",      "badge.mastery_25.desc",      "Trophy"),
    "streak_3":        BadgeDefinition("streak_3",        "badge.streak_3.label",        "badge.streak_3.desc",        "Flame"),
    "streak_7":        BadgeDefinition("streak_7",        "badge.streak_7.label",        "badge.streak_7.desc",        "Zap"),
    "streak_14":       BadgeDefinition("streak_14",       "badge.streak_14.label",       "badge.streak_14.desc",       "Calendar"),
    "streak_30":       BadgeDefinition("streak_30",       "badge.streak_30.label",       "badge.streak_30.desc",       "Crown"),
    "correct_10":      BadgeDefinition("correct_10",      "badge.correct_10.label",      "badge.correct_10.desc",      "Target"),
    "correct_25":      BadgeDefinition("correct_25",      "badge.correct_25.label",      "badge.correct_25.desc",      "Award"),
    "perfect_chunk":   BadgeDefinition("perfect_chunk",   "badge.perfect_chunk.label",   "badge.perfect_chunk.desc",   "Medal"),
    "speed_demon":     BadgeDefinition("speed_demon",     "badge.speed_demon.label",     "badge.speed_demon.desc",     "Timer"),
}
```

### Data Flow Diagram

```
[Student answers card]
        │
        ▼
POST /sessions/{id}/record-interaction
        │
        ├─ 1. Save CardInteraction row (with difficulty)
        │
        ├─ 2. streak_engine.update_streak(student, today)
        │       └─ Returns: StreakResult(daily_streak, multiplier, streak_broke)
        │       └─ DB: UPDATE students SET daily_streak, daily_streak_best, last_active_date
        │
        ├─ 3. xp_engine.calculate_xp(difficulty, hints, wrong, multiplier)
        │       └─ Returns: XpResult(base_xp, multiplier, final_xp)
        │       └─ DB: INSERT INTO xp_events
        │       └─ DB: UPDATE students SET xp = xp + final_xp
        │
        ├─ 4. badge_engine.evaluate_badges(student_id, context, db)
        │       └─ Queries: student mastery count, streak, card correct count, etc.
        │       └─ DB: INSERT INTO student_badges ON CONFLICT DO NOTHING
        │       └─ Returns: list[str] new badge keys
        │
        └─ 5. Return {saved: true, xp_awarded: N, new_badges: [...]}
```

### Caching Strategy

- Feature flags (`GAMIFICATION_ENABLED`, etc.) cached in-process Python dict with 60-second TTL
- No Redis required — single-process server; TTL invalidated on admin flag toggle via `GET /features` internal refresh
- Leaderboard results are NOT cached — query is fast enough via `students.xp` indexed scan; caching adds stale-data risk

### Data Retention

- `xp_events` — no automatic deletion; append-only. Admin can query historical data indefinitely.
- `student_badges` — permanent; badges are never auto-revoked.
- If a student account is deleted (`CASCADE`), all `xp_events` and `student_badges` rows are deleted automatically.

---

## 3. API Design

### Versioning
All new student-facing endpoints use the `/api/v2` prefix (consistent with existing v2 student resource pattern). The admin progress report uses `/api/admin` (consistent with existing admin router).

---

### Modified: `POST /api/v2/sessions/{session_id}/record-interaction`

**Change:** Response body extended; `difficulty` added to request.

**Request:**
```json
{
  "card_index": 2,
  "time_on_card_sec": 45.2,
  "wrong_attempts": 1,
  "hints_used": 0,
  "idle_triggers": 0,
  "difficulty": 3,
  "selected_wrong_option": "B",
  "adaptation_applied": null,
  "engagement_signal": null,
  "strategy_applied": null
}
```

**Response (was `{"saved": true}`, now):**
```json
{
  "saved": true,
  "xp_awarded": 18,
  "new_badges": ["first_correct"]
}
```

**Status codes:**
- `200 OK` — interaction saved; XP and badges computed (or gamification disabled)
- `404 Not Found` — session not found
- `403 Forbidden` — student ownership check failed
- `429 Too Many Requests` — rate limit (30/minute, existing)

**Auth:** Bearer JWT required (`get_current_user`)

**Gamification disabled fallback:** If `GAMIFICATION_ENABLED` is false, the endpoint saves the interaction and returns `{"saved": true, "xp_awarded": 0, "new_badges": []}`.

---

### New: `GET /api/v2/students/{student_id}/badges`

**Purpose:** Return all badges earned by a student.

**Auth:** Bearer JWT; `_validate_student_ownership` enforced.

**Response:**
```json
{
  "badges": [
    {
      "key": "first_correct",
      "label": "First Correct",
      "description": "Answered your first card correctly",
      "icon": "CheckCircle",
      "awarded_at": "2026-04-13T10:22:00Z"
    }
  ]
}
```

**Status codes:**
- `200 OK`
- `404 Not Found` — student not found
- `403 Forbidden` — ownership check failed

---

### New: `GET /api/v2/leaderboard`

**Purpose:** Return ranked list of students by XP.

**Auth:** Bearer JWT required.

**Query parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Max rows returned (max 200) |
| `offset` | int | 0 | Pagination offset |

**Response:**
```json
{
  "enabled": true,
  "entries": [
    {
      "rank": 1,
      "display_name": "Alice",
      "xp": 1240,
      "level": 13,
      "daily_streak": 7
    }
  ],
  "total": 312
}
```

**Status codes:**
- `200 OK` — always returned when endpoint is called; `enabled: false` if `LEADERBOARD_ENABLED` is false with empty `entries` array
- `401 Unauthorized` — no valid JWT

**Privacy:** UUIDs are never exposed in the leaderboard. `display_name` only.

---

### New: `GET /api/admin/students/{student_id}/progress-report`

**Purpose:** Admin view of a student's XP trend, accuracy, and badge history.

**Auth:** Bearer JWT + `require_role("admin")` dependency.

**Query parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `days` | int | 30 | Rolling window for XP trend (max 365) |

**Response:**
```json
{
  "student_id": "uuid",
  "display_name": "Alice",
  "total_xp": 1240,
  "current_level": 13,
  "daily_streak": 7,
  "daily_streak_best": 14,
  "xp_by_day": [
    {"date": "2026-04-12", "xp_earned": 45},
    {"date": "2026-04-13", "xp_earned": 72}
  ],
  "accuracy_by_day": [
    {"date": "2026-04-12", "correct": 8, "total": 10}
  ],
  "badges": [
    {"key": "first_correct", "awarded_at": "2026-04-01T09:00:00Z"}
  ],
  "total_cards_attempted": 152,
  "total_correct": 134
}
```

**Status codes:**
- `200 OK`
- `403 Forbidden` — non-admin caller
- `404 Not Found` — student not found

---

### New: `GET /api/v2/features`

**Purpose:** Return current state of all gamification feature flags for frontend conditional rendering.

**Auth:** Bearer JWT required.

**Response:**
```json
{
  "GAMIFICATION_ENABLED": true,
  "LEADERBOARD_ENABLED": false,
  "BADGES_ENABLED": true,
  "STREAK_MULTIPLIER_ENABLED": true,
  "DIFFICULTY_WEIGHTED_XP_ENABLED": true
}
```

**Status codes:**
- `200 OK` always

---

### Error Handling Conventions

All endpoints follow the existing project convention:
- `HTTPException(status_code, detail=str)` for client errors
- Structured `logger.exception()` for unexpected errors (never bare `except`)
- Gamification pipeline failures are non-fatal: interaction saves and returns `xp_awarded: 0, new_badges: []` with a WARNING log

---

## 4. Sequence Diagrams

### 4.1 Happy Path — Card Answered Correctly (Full Gamification)

```
Frontend (CardLearningView)
    │
    │  POST /sessions/{id}/record-interaction {difficulty:3, hints:0, wrong:0, ...}
    │────────────────────────────────────────────────────────────────────────────▶
    │                                                                   teaching_router
    │                                                                        │
    │                                                              Save CardInteraction (with difficulty=3)
    │                                                                        │
    │                                                              streak_engine.update_streak()
    │                                                                        │
    │                                                              ┌─ last_active_date == today?
    │                                                              │  YES: no change to streak
    │                                                              │  NO, yesterday: streak += 1
    │                                                              │  NO, older: streak = 1
    │                                                              └──▶ UPDATE students (streak, last_active_date)
    │                                                                        │
    │                                                              xp_engine.calculate_xp(3, 0, 0, 1.5×)
    │                                                                        │
    │                                                              base_xp = 3 * 4 = 12
    │                                                              first_attempt_bonus = 1.5
    │                                                              final_xp = round(12 * 1.0 * 1.0 * 1.5 * 1.5) = 27
    │                                                                        │
    │                                                              INSERT INTO xp_events (student_id, final_xp=27, ...)
    │                                                              UPDATE students SET xp = xp + 27
    │                                                                        │
    │                                                              badge_engine.evaluate_badges()
    │                                                                        │
    │                                                              ┌─ first_correct: no prior xp_events? YES
    │                                                              └── INSERT student_badges (first_correct) ON CONFLICT DO NOTHING
    │                                                                        │
    │  ◀──────────────────────────────────────────────────────── {saved:true, xp_awarded:27, new_badges:["first_correct"]}
    │
    ├─ awardXP(27)  [Zustand]  → XPBurst animation
    ├─ addBadges(["first_correct"])  [Zustand]
    └─ render BadgeCelebration for "first_correct"
```

### 4.2 Error Path — Gamification Pipeline Fails

```
Frontend
    │  POST /sessions/{id}/record-interaction
    │────────────────────────────────────────▶ teaching_router
    │                                              │
    │                                    Save CardInteraction  ← succeeds
    │                                              │
    │                                    streak_engine.update_streak()  ← raises DB error
    │                                              │
    │                                    logger.warning("[gamification-failed] ...")
    │                                              │
    │  ◀──────────────────────────────── {saved:true, xp_awarded:0, new_badges:[]}
    │
    └─ No XP animation shown; interaction recorded correctly
```

### 4.3 Leaderboard Fetch

```
Frontend (LeaderboardPage)
    │  GET /api/v2/leaderboard?limit=50&offset=0
    │────────────────────────────────────────────────────────────▶ gamification_router
    │                                                                    │
    │                                                          Check feature flag cache
    │                                                          LEADERBOARD_ENABLED == false?
    │                                                                    │
    │  ◀──────────────────────────────── {enabled:false, entries:[], total:0}
    │
    └─ Render "Leaderboard is currently disabled" message
```

### 4.4 Badge Award — Streak Milestone (streak_7)

```
[Student answers card on day 7 of consecutive daily activity]
    │
    │  POST /sessions/{id}/record-interaction
    │────────────────────────────────────▶ teaching_router
    │                                         │
    │                               streak_engine.update_streak()
    │                               last_active_date == yesterday  → streak = 7
    │                                         │
    │                               badge_engine.evaluate_badges()
    │                               ┌─ streak_7: daily_streak >= 7? YES
    │                               └── INSERT student_badges (streak_7) ON CONFLICT DO NOTHING → new row
    │
    │  ◀─────────── {saved:true, xp_awarded:22, new_badges:["streak_7"]}
    │
    └─ BadgeCelebration("streak_7") rendered
```

---

## 5. Integration Design

### 5.1 Gamification Module ↔ Teaching Router

The `record_card_interaction` handler in `teaching_router.py` calls into the gamification module synchronously after saving the `CardInteraction` row. The module receives the `AsyncSession` passed from the handler's FastAPI dependency injection — all operations share the same session and implicit transaction.

```python
# Pseudocode in record_card_interaction():
interaction = CardInteraction(...)
db.add(interaction)
await db.flush()  # get interaction.id without full commit

xp_result = None
new_badge_keys: list[str] = []
if await feature_flags.get("GAMIFICATION_ENABLED"):
    try:
        streak_result = await streak_engine.update_streak(session.student_id, db)
        xp_result = await xp_engine.award_xp(
            student_id=session.student_id,
            session_id=session.id,
            interaction_id=interaction.id,
            difficulty=req.difficulty or 3,
            hints_used=req.hints_used,
            wrong_attempts=req.wrong_attempts,
            multiplier=streak_result.multiplier,
            db=db,
        )
        new_badge_keys = await badge_engine.evaluate_badges(
            student_id=session.student_id,
            daily_streak=streak_result.daily_streak,
            db=db,
        )
    except Exception:
        logger.warning("[gamification-failed] student=%s", session.student_id, exc_info=True)

await db.commit()
return RecordInteractionResponse(
    saved=True,
    xp_awarded=xp_result.final_xp if xp_result else 0,
    new_badges=new_badge_keys,
)
```

### 5.2 Adaptive Engine ↔ Card Difficulty

The adaptive engine's `generate_per_card()` and `_generate_cards_single()` functions currently return a card dict. The `difficulty` field is already generated by the LLM prompt (`parsed.get("difficulty", 3)`). The backend developer must ensure `difficulty` is forwarded in the `RecordInteractionRequest` that the frontend sends.

**Change required in `prompt_builder.py`:** No change — `difficulty` is already in the LLM output.

**Change required in `CardLearningView.jsx`:** Include `difficulty: card.difficulty` in the `recordInteraction()` call payload.

**Change required in `sessions.js`:** `recordInteraction()` function must forward `difficulty` field.

### 5.3 Feature Flag Cache

```python
# backend/src/gamification/feature_flags.py
import asyncio
import time
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import AdminConfig

_CACHE: dict[str, bool] = {}
_LAST_REFRESH: float = 0.0
_TTL_SECONDS = 60

FLAG_KEYS = [
    "GAMIFICATION_ENABLED",
    "LEADERBOARD_ENABLED",
    "BADGES_ENABLED",
    "STREAK_MULTIPLIER_ENABLED",
    "DIFFICULTY_WEIGHTED_XP_ENABLED",
]
FLAG_DEFAULTS = {k: True for k in FLAG_KEYS}
FLAG_DEFAULTS["LEADERBOARD_ENABLED"] = False  # opt-in

async def get_flag(key: str, db: AsyncSession) -> bool:
    global _LAST_REFRESH
    if time.monotonic() - _LAST_REFRESH > _TTL_SECONDS:
        await _refresh(db)
    return _CACHE.get(key, FLAG_DEFAULTS[key])

async def _refresh(db: AsyncSession) -> None:
    global _LAST_REFRESH
    rows = await db.execute(select(AdminConfig).where(AdminConfig.key.in_(FLAG_KEYS)))
    for row in rows.scalars():
        _CACHE[row.key] = row.value.lower() in ("true", "1", "yes")
    _LAST_REFRESH = time.monotonic()
```

---

## 6. Security Design

### Authentication and Authorization

| Endpoint | Auth | Authorization |
|----------|------|---------------|
| `POST /sessions/{id}/record-interaction` | Bearer JWT | `_validate_student_ownership` |
| `GET /students/{id}/badges` | Bearer JWT | `_validate_student_ownership` |
| `GET /leaderboard` | Bearer JWT | Any authenticated user |
| `GET /admin/students/{id}/progress-report` | Bearer JWT | `require_role("admin")` |
| `GET /features` | Bearer JWT | Any authenticated user |

### Data Exposure
- Leaderboard: returns `display_name`, `xp`, `level`, `daily_streak` only. No UUIDs, emails, or internal state.
- Badge endpoint: scoped to the requesting student's own data only.
- Progress report: admin-only; full data exposed only to admins.

### Input Validation
- `difficulty` field: `SmallInteger`, validated as `1 ≤ difficulty ≤ 5` in `RecordInteractionRequest` (Pydantic `Field(ge=1, le=5, default=None)` — nullable for legacy cards)
- `hints_used`, `wrong_attempts`: `ge=0` constraints already exist; reused
- `leaderboard` limit: `Field(ge=1, le=200, default=50)` — prevents runaway queries
- `progress-report` days: `Field(ge=1, le=365, default=30)`

### Secrets Management
No new secrets. All existing `API_SECRET_KEY` and JWT mechanisms apply unchanged.

---

## 7. Observability Design

### Structured Log Events

| Logger Call | Fields | When |
|-------------|--------|------|
| `logger.info("[xp-awarded]")` | `student_id`, `xp_delta`, `event_type`, `base_xp`, `multiplier`, `final_xp` | Every successful XP award |
| `logger.info("[streak-updated]")` | `student_id`, `old_streak`, `new_streak`, `streak_broke` | Every streak update |
| `logger.info("[badge-awarded]")` | `student_id`, `badge_key` | Every new badge insert |
| `logger.warning("[gamification-failed]")` | `student_id`, `exc_info=True` | Any exception in the gamification pipeline |
| `logger.info("[leaderboard-fetched]")` | `requester_id`, `limit`, `total` | Leaderboard endpoint called |

### Metrics (application-level counters — can be scraped by Prometheus if added later)
- `gamification.xp_awarded.total` — running total XP awarded
- `gamification.badges_awarded.total` — running total badges awarded
- `gamification.streak_broke.total` — number of streak resets

### Alerting Thresholds (operational guidance)
- Alert if `[gamification-failed]` log rate exceeds 5/minute — indicates DB contention or schema mismatch
- Alert if `record-interaction` p99 exceeds 500 ms — gamification pipeline may need async migration

### Distributed Tracing
No additional tracing instrumentation required beyond the existing OpenTelemetry setup (if/when added). The gamification pipeline is synchronous within the request span.

---

## 8. Algorithms

### 8.1 XP Formula (pure function in `xp_engine.py`)

```python
from config import XP_PER_DIFFICULTY_POINT  # default: 4

def calculate_xp(
    difficulty: int,          # 1–5; use 3 as fallback for NULL
    hints_used: int,
    wrong_attempts: int,
    streak_multiplier: float, # from streak_engine
) -> XpResult:
    base_xp = difficulty * XP_PER_DIFFICULTY_POINT

    hint_factor = max(0.25, 1.0 - 0.25 * hints_used)
    wrong_factor = max(0.25, 1.0 - 0.15 * wrong_attempts)
    first_attempt_bonus = 1.5 if hints_used == 0 and wrong_attempts == 0 else 1.0

    raw = base_xp * hint_factor * wrong_factor * first_attempt_bonus * streak_multiplier
    final_xp = max(1, round(raw))  # always award at least 1 XP for a completed card

    effective_multiplier = round(raw / base_xp, 4) if base_xp > 0 else 1.0
    return XpResult(base_xp=base_xp, multiplier=effective_multiplier, final_xp=final_xp)
```

**Example calculations:**

| Difficulty | Hints | Wrong | Streak | base_xp | final_xp |
|-----------|-------|-------|--------|---------|---------|
| 3 | 0 | 0 | 1.0× | 12 | 18 (×1.5 first-attempt) |
| 3 | 0 | 0 | 2.0× | 12 | 36 |
| 5 | 0 | 0 | 1.0× | 20 | 30 |
| 1 | 2 | 3 | 1.0× | 4 | 1 (floor) |
| 3 | 1 | 0 | 1.25× | 12 | 11 (hint penalty, no first-attempt bonus) |

### 8.2 Streak Update Algorithm (in `streak_engine.py`)

```python
from datetime import date, timedelta

async def update_streak(student_id: UUID, db: AsyncSession) -> StreakResult:
    today = date.today()  # UTC date
    student = await db.get(Student, student_id)

    if student.last_active_date is None:
        # Brand-new student; first activity
        new_streak = 1
        streak_broke = False
    elif student.last_active_date == today:
        # Already active today; no change
        new_streak = student.daily_streak
        streak_broke = False
    elif student.last_active_date == today - timedelta(days=1):
        # Consecutive day; extend streak
        new_streak = student.daily_streak + 1
        streak_broke = False
    else:
        # Gap of 2+ days; reset
        new_streak = 1
        streak_broke = True

    new_best = max(student.daily_streak_best, new_streak)

    await db.execute(
        update(Student)
        .where(Student.id == student_id)
        .values(
            daily_streak=new_streak,
            daily_streak_best=new_best,
            last_active_date=today,
        )
    )

    return StreakResult(
        daily_streak=new_streak,
        multiplier=_tier_multiplier(new_streak),
        streak_broke=streak_broke,
    )

def _tier_multiplier(streak: int) -> float:
    if streak >= 14:  return 2.5
    if streak >= 7:   return 2.0
    if streak >= 5:   return 1.5
    if streak >= 3:   return 1.25
    return 1.0
```

### 8.3 Badge Evaluation Logic (in `badge_engine.py`)

Each badge has a predicate. Badge engine runs all predicates whose badge is not yet awarded for the student.

```python
BADGE_PREDICATES: dict[str, Callable[[BadgeContext], bool]] = {
    "first_correct":  lambda ctx: ctx.total_correct >= 1,
    "first_mastery":  lambda ctx: ctx.total_mastered >= 1,
    "mastery_5":      lambda ctx: ctx.total_mastered >= 5,
    "mastery_10":     lambda ctx: ctx.total_mastered >= 10,
    "mastery_25":     lambda ctx: ctx.total_mastered >= 25,
    "streak_3":       lambda ctx: ctx.daily_streak >= 3,
    "streak_7":       lambda ctx: ctx.daily_streak >= 7,
    "streak_14":      lambda ctx: ctx.daily_streak >= 14,
    "streak_30":      lambda ctx: ctx.daily_streak >= 30,
    "correct_10":     lambda ctx: ctx.total_correct >= 10,
    "correct_25":     lambda ctx: ctx.total_correct >= 25,
    "perfect_chunk":  lambda ctx: ctx.current_chunk_all_first_attempt,
    "speed_demon":    lambda ctx: ctx.last_card_time_sec <= SPEED_DEMON_THRESHOLD_SEC and ctx.last_card_correct,
}
```

`BadgeContext` is built from a single aggregate query + the current interaction data, not N separate queries:

```python
@dataclass
class BadgeContext:
    daily_streak: int
    total_correct: int          # from COUNT(xp_events WHERE event_type='CARD_CORRECT')
    total_mastered: int         # from COUNT(student_mastery WHERE student_id=...)
    current_chunk_all_first_attempt: bool   # computed from current session card_interactions
    last_card_time_sec: float
    last_card_correct: bool
```

**Evaluation loop:**
1. Query existing badge keys for student: `SELECT badge_key FROM student_badges WHERE student_id = :id`
2. Build `BadgeContext` from aggregate query (single DB call)
3. For each badge key NOT yet awarded, evaluate predicate
4. For each passing badge: `INSERT INTO student_badges (student_id, badge_key) VALUES (...) ON CONFLICT DO NOTHING`
5. Return list of newly inserted badge keys

---

## 9. New Config Constants (`config.py`)

```python
# ── Gamification ──────────────────────────────────────────────────────────────
XP_PER_DIFFICULTY_POINT: int = 4        # base_xp = difficulty * this
XP_FIRST_ATTEMPT_BONUS: float = 1.5     # multiplier when hints==0 and wrong==0
XP_HINT_PENALTY_PER_USE: float = 0.25   # subtracted per hint use (floor 0.25)
XP_WRONG_PENALTY_PER_ATTEMPT: float = 0.15  # subtracted per wrong attempt (floor 0.25)
XP_MINIMUM_AWARD: int = 1               # minimum XP for any completed card

# Streak multiplier tiers
STREAK_TIER_1_DAYS: int = 3             # first tier upgrade threshold
STREAK_TIER_2_DAYS: int = 5
STREAK_TIER_3_DAYS: int = 7
STREAK_TIER_4_DAYS: int = 14
STREAK_MULTIPLIER_TIER_0: float = 1.0   # 1–2 days
STREAK_MULTIPLIER_TIER_1: float = 1.25  # 3–4 days
STREAK_MULTIPLIER_TIER_2: float = 1.5   # 5–6 days
STREAK_MULTIPLIER_TIER_3: float = 2.0   # 7–13 days
STREAK_MULTIPLIER_TIER_4: float = 2.5   # 14+ days

SPEED_DEMON_THRESHOLD_SEC: float = 15.0  # max time_on_card_sec for speed_demon badge

FEATURE_FLAG_TTL_SECONDS: int = 60      # AdminConfig cache TTL

LEADERBOARD_DEFAULT_LIMIT: int = 50
LEADERBOARD_MAX_LIMIT: int = 200
PROGRESS_REPORT_DEFAULT_DAYS: int = 30
PROGRESS_REPORT_MAX_DAYS: int = 365
```

---

## 10. Frontend Component Specifications

### `BadgeCelebration.jsx`

**Props:** `badges: BadgeDefinition[]` (list of newly earned badges), `onDismiss: () => void`

**Behaviour:**
- Full-screen semi-transparent overlay (z-index: 9999)
- Framer Motion `AnimatePresence` with scale + opacity entrance
- If multiple badges awarded simultaneously, show them in sequence with 2-second auto-advance
- Dismissed by click, or auto-dismisses after `badges.length * 3` seconds
- Calls `onDismiss()` when done
- Uses `useTranslation()` for all strings

**State in `CardLearningView`:**
```jsx
const [celebrationBadges, setCelebrationBadges] = useState([]);
// after recordInteraction returns:
if (response.new_badges?.length > 0) {
  setCelebrationBadges(response.new_badges.map(k => BADGE_DEFINITIONS[k]));
}
```

### `BadgeGrid.jsx`

**Props:** `earnedKeys: string[]` (badge keys the student has earned)

**Behaviour:**
- Renders all 13 badges in a 4-column grid
- Unearned badges: grayscale + opacity 40%
- Earned badges: full colour + tooltip with description
- Used on student profile page or as a drawer accessible from the nav

### `StreakMultiplierBadge.jsx`

**Props:** `streak: number`, `multiplier: number`

**Behaviour:**
- Small inline pill showing "🔥 {streak}d · {multiplier}×"
- Changes colour based on tier: grey (1×), orange (1.25×), amber (1.5×), red (2×), purple (2.5×)
- Shown in the card learning header area

### `LeaderboardPage.jsx`

**Route:** `/leaderboard` (added to `App.jsx`)

**Behaviour:**
- Fetches `GET /api/v2/leaderboard?limit=50&offset=0` on mount
- Handles `enabled: false` with a localised "Leaderboard is currently disabled" message
- Paginated table: rank, display_name, level, xp, streak
- Highlights the current student's row
- Uses `useTranslation()` for all column headers and messages

### `adaptiveStore.js` Additions

```javascript
// New state fields:
dailyStreak: 0,
dailyStreakBest: 0,
streakMultiplier: 1.0,
pendingBadges: [],   // badges waiting to be celebrated

// New actions:
setStreakData: ({ daily_streak, daily_streak_best, streak_multiplier }) => set({ ... }),
addPendingBadges: (keys) => set(state => ({ pendingBadges: [...state.pendingBadges, ...keys] })),
clearPendingBadges: () => set({ pendingBadges: [] }),
```

`CardLearningView` reads `pendingBadges` from the store and passes them to `BadgeCelebration`; calls `clearPendingBadges()` in `onDismiss`.

---

## 11. Testing Strategy

### Unit Tests (backend) — `backend/tests/test_gamification.py`

| Test Class | Covers |
|------------|--------|
| `TestXpCalculation` | Pure formula: all difficulty levels, hint/wrong combinations, streak tiers, minimum floor |
| `TestStreakUpdate` | First activity, consecutive day, missed day reset, same-day idempotency |
| `TestBadgeEvaluation` | All 13 badge predicates: passing condition, failing condition, already-awarded idempotency |
| `TestFeatureFlagCache` | TTL expiry, default values when DB is empty, flag disabled paths |
| `TestRecordInteractionWithXP` | Integration: full pipeline through `record_card_interaction`; checks `xp_events` insert, `students.xp` increment, response payload |

**Target:** ≥ 90% branch coverage of `gamification/` package. Pure functions tested without DB mocking.

### Integration Tests — `backend/tests/test_gamification_integration.py`

- `POST /sessions/{id}/record-interaction` with gamification enabled/disabled
- `GET /leaderboard` with LEADERBOARD_ENABLED true/false
- Badge deduplication: call `evaluate_badges` twice; assert only one row inserted
- Progress report: verify XP aggregation matches `xp_events` sum

### Frontend Tests

- `BadgeCelebration`: renders for single and multiple badges; auto-dismisses; calls `onDismiss`
- `StreakMultiplierBadge`: correct tier colour for each multiplier level
- `LeaderboardPage`: renders "disabled" message when `enabled: false`; renders ranked list when enabled
- `adaptiveStore.js`: `addPendingBadges` accumulates; `clearPendingBadges` resets

### Performance / Load Test

- Simulate 100 concurrent `record-interaction` requests with gamification enabled
- Assert p99 ≤ 300 ms
- Assert no duplicate badge rows after concurrent badge evaluation for the same student

### Contract Tests

- Verify `record-interaction` response always contains `saved`, `xp_awarded`, `new_badges` fields
- Verify leaderboard response always contains `enabled`, `entries`, `total` fields (even when disabled)

---

## Key Decisions Requiring Stakeholder Input

1. **`perfect_chunk` badge definition** — "All cards in a chunk answered first-attempt correct." Should this be any chunk in the session, or specifically the last chunk? The current design checks whether all `card_interactions` for the current `session_id` have `wrong_attempts=0` and `hints_used=0`. Confirm the intended scope.
2. **`speed_demon` threshold** — 15 seconds is currently proposed as the max `time_on_card_sec` for the badge. This needs calibration against real session telemetry before shipping.
3. **Leaderboard streak visibility** — Should `daily_streak` be shown on the leaderboard, or only `xp` and `level`? Current design shows streak as a motivating signal.
4. **XP retroactive recalculation** — Existing `students.xp` rows were accumulated with the old flat-10 system. Should existing XP be preserved as-is (additive going forward) or recalculated? Current design preserves existing XP as-is.
5. **`BADGES_ENABLED` scope** — When `BADGES_ENABLED` is false, should existing earned badges still be displayed (read-only), or should the badges endpoint return an empty list? Current design: endpoint still returns earned badges; no new badges are awarded.
