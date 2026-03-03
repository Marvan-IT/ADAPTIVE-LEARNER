# Detailed Low-Level Design: Risk Hardening Redesign

**Feature slug:** `risk-hardening-redesign`
**Date:** 2026-02-28
**Author:** Solution Architect

---

## 1. Component Breakdown

### Stream A — Mastery Threshold

| Component | File | Responsibility |
|-----------|------|---------------|
| `config.py` | `backend/src/config.py` | Define `MASTERY_THRESHOLD = 60` as the single source of truth |
| `teaching_service.py` | `backend/src/api/teaching_service.py` | Import `MASTERY_THRESHOLD` from `config`; remove local definition |

### Stream B — Risk Hardening

| Component | File | Responsibility |
|-----------|------|---------------|
| `config.py` | `backend/src/config.py` | Define all 11 adaptive constants (see §2) |
| `adaptive_engine.py` | `backend/src/adaptive/adaptive_engine.py` | Remove inline constants; import from config; fix model in `generate_next_card()`; add `.limit(200)` to history query |
| `db/models.py` | `backend/src/db/models.py` | Add `UniqueConstraint` to `SpacedReview.__table_args__` |
| `teaching_service.py` | `backend/src/api/teaching_service.py` | Replace bare `db.add(SpacedReview(...))` with `pg_insert().on_conflict_do_nothing()` |
| `CardLearningView.jsx` | `frontend/src/components/learning/CardLearningView.jsx` | Replace `Date.now()` (3 occurrences) with `performance.now()` |

### Stream C — Frontend Redesign

| Component | File | Responsibility |
|-----------|------|---------------|
| Design tokens | `frontend/src/index.css` or theme file | Add `--shadow-*`, `--radius-*`, `--motion-*`, `--shimmer-*` CSS custom properties |
| `Button` | `frontend/src/components/ui/Button.jsx` | Polymorphic button primitive with variants (primary, secondary, ghost, danger) and sizes |
| `Card` | `frontend/src/components/ui/Card.jsx` | Surface container with optional header slot and elevation shadow |
| `Badge` | `frontend/src/components/ui/Badge.jsx` | Inline status chip with semantic colour variants |
| `Skeleton` | `frontend/src/components/ui/Skeleton.jsx` | Shimmer loading placeholder that accepts `width`, `height`, and `rounded` props |
| `ProgressRing` | `frontend/src/components/ui/ProgressRing.jsx` | SVG ring that animates `stroke-dashoffset` from 0 to target on mount |
| `Toast` | `frontend/src/components/ui/Toast.jsx` | Transient notification shown from top-right; self-dismisses after 3 s |
| `WelcomePage.jsx` | `frontend/src/pages/WelcomePage.jsx` | Hero layout redesign |
| `ConceptMapPage.jsx` | `frontend/src/pages/ConceptMapPage.jsx` | Replace absolute tooltip with slide-in `ConceptPanel` |
| `ConceptPanel.jsx` | `frontend/src/components/conceptmap/ConceptPanel.jsx` | New component: slide-in right panel for node details |
| `ConceptTooltip.jsx` | `frontend/src/components/conceptmap/ConceptTooltip.jsx` | Deprecated; retained for one cycle, then removed |
| `CardLearningView.jsx` | `frontend/src/components/learning/CardLearningView.jsx` | Focus-mode, pill MCQ buttons, shake-on-wrong, segmented ProgressDots |
| `SocraticChat.jsx` | `frontend/src/components/learning/SocraticChat.jsx` | Fixed input bar, typing indicator, guaranteed auto-scroll, Enter key handling |
| `CompletionView.jsx` | `frontend/src/components/learning/CompletionView.jsx` | SVG ProgressRing, CSS confetti, updated score bands |
| `AppShell.jsx` | `frontend/src/components/layout/AppShell.jsx` | Student name as dropdown popover |

---

## 2. Data Design

### 2.1 Config Constants Added (Streams A + B)

The following constants are added to `backend/src/config.py` in a new section `── Adaptive Real Tutor ──`:

```python
# ── Mastery ─────────────────────────────────────────────────────────────────
MASTERY_THRESHOLD: int = 60                  # Score >= 60 marks concept as mastered
                                             # (Stream A: was 70, defined locally in teaching_service.py)

# ── Adaptive Real Tutor ──────────────────────────────────────────────────────
ADAPTIVE_CARD_MODEL: str = OPENAI_MODEL_MINI # Model for per-card generation (gpt-4o-mini)
ADAPTIVE_CARD_CEILING: int = 8               # Max adaptive cards per session before 409

# Blending: minimum history threshold
ADAPTIVE_MIN_HISTORY_CARDS: int = 5         # Cards needed before history weighting activates

# Blending: acute deviation thresholds
ADAPTIVE_ACUTE_HIGH_TIME_RATIO: float = 2.0  # time_on_card / baseline > this → acute
ADAPTIVE_ACUTE_LOW_TIME_RATIO: float = 0.4   # time_on_card / baseline < this → acute
ADAPTIVE_ACUTE_WRONG_RATIO: float = 3.0      # (wrong+1) / (baseline_wrong+1) > this → acute

# Blending: weights for acute vs normal scenarios
ADAPTIVE_ACUTE_CURRENT_WEIGHT: float = 0.9
ADAPTIVE_ACUTE_HISTORY_WEIGHT: float = 0.1
ADAPTIVE_NORMAL_CURRENT_WEIGHT: float = 0.6
ADAPTIVE_NORMAL_HISTORY_WEIGHT: float = 0.4
```

### 2.2 SpacedReview Model Change (Stream B)

Current `SpacedReview` in `backend/src/db/models.py`:
```python
class SpacedReview(Base):
    __tablename__ = "spaced_reviews"
    # ... columns ...
```

After change:
```python
class SpacedReview(Base):
    __tablename__ = "spaced_reviews"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "concept_id", "review_number",
            name="uq_spaced_review",
        ),
    )
    # ... columns unchanged ...
```

This change requires an Alembic migration that:
1. Checks for duplicate `(student_id, concept_id, review_number)` rows and removes duplicates (keep earliest `id`)
2. Adds `CREATE UNIQUE INDEX uq_spaced_review ON spaced_reviews(student_id, concept_id, review_number)`

The migration is delegated to the devops-engineer agent. The ORM change is applied independently.

### 2.3 CSS Design Tokens Added (Stream C)

New tokens appended to the `:root` and theme selectors in `frontend/src/index.css` (or wherever theme tokens are currently defined):

```css
:root {
  /* Elevation shadows */
  --shadow-xs:  0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-sm:  0 2px 8px rgba(0, 0, 0, 0.07);
  --shadow-md:  0 4px 16px rgba(0, 0, 0, 0.10);
  --shadow-lg:  0 8px 32px rgba(0, 0, 0, 0.12);
  --shadow-xl:  0 16px 48px rgba(0, 0, 0, 0.15);

  /* Border radii */
  --radius-sm:  6px;
  --radius-md:  12px;
  --radius-lg:  16px;
  --radius-xl:  24px;
  --radius-full: 9999px;

  /* Motion */
  --motion-fast:   150ms ease;
  --motion-normal: 250ms ease;
  --motion-slow:   400ms ease;

  /* Skeleton shimmer (light mode) */
  --shimmer-from: #f0f0f0;
  --shimmer-via:  #e0e0e0;
  --shimmer-to:   #f0f0f0;
}

[data-theme="dark"],
.dark {
  --shimmer-from: #2a2a2a;
  --shimmer-via:  #3a3a3a;
  --shimmer-to:   #2a2a2a;
  /* shadows: use slightly higher opacity in dark mode */
  --shadow-md:  0 4px 16px rgba(0, 0, 0, 0.30);
  --shadow-lg:  0 8px 32px rgba(0, 0, 0, 0.40);
}
```

Skeleton shimmer keyframe (global):
```css
@keyframes skeleton-shimmer {
  0%   { background-position: -200% 0; }
  100% { background-position:  200% 0; }
}
```

---

## 3. API Design

No new API endpoints are introduced in this release. No existing endpoint contracts change.

### 3.1 Behaviour Changes to Existing Endpoints

| Endpoint | Change | Impact |
|----------|--------|--------|
| `POST /api/v2/sessions/{id}/answer` (handle_student_response) | Mastery evaluated at score >= 60 instead of >= 70 | Students scoring 60-69 will now receive `"mastered": true` |
| `POST /api/v2/sessions/{id}/complete-card` | SpacedReview inserts are now idempotent (ON CONFLICT DO NOTHING) | Duplicate calls no longer create duplicate review rows |
| `POST /api/v3/adaptive-lesson` (generate_adaptive_lesson) | No change — model parameter default unchanged at OPENAI_MODEL |
| `POST /api/v2/sessions/{id}/complete-card` (generate_next_card) | Uses ADAPTIVE_CARD_MODEL (gpt-4o-mini) consistently | No external contract change; cost reduction |

### 3.2 Response Schema Changes

`POST /api/v2/sessions/{id}/answer` response when check completes:

```json
{
  "response": "string",
  "phase": "COMPLETED",
  "check_complete": true,
  "score": 63,
  "mastered": true
}
```

No schema field changes. `mastered` is now `true` at score 60 instead of 70.

---

## 4. Sequence Diagrams

### 4.1 Stream A: Mastery Evaluation at Score 60

```
Client                teaching_service.py         config.py
  │                          │                        │
  │ POST /sessions/{id}/answer                         │
  │─────────────────────────>│                        │
  │                          │ _parse_assessment()     │
  │                          │ returns score=63        │
  │                          │                        │
  │                          │ mastered = 63 >= MASTERY_THRESHOLD
  │                          │ (imports MASTERY_THRESHOLD from config)
  │                          │────────────────────────>│
  │                          │<── 60 ─────────────────│
  │                          │ mastered = True         │
  │                          │ write StudentMastery    │
  │                          │ schedule SpacedReview   │
  │<─ {mastered: true} ─────│                        │
```

### 4.2 Stream B: Idempotent SpacedReview Insert

```
teaching_service.py                    PostgreSQL
  │                                        │
  │ session complete, score >= 60          │
  │ for i, days in REVIEW_INTERVALS_DAYS:  │
  │   stmt = pg_insert(SpacedReview)       │
  │          .values(student_id, ...)      │
  │          .on_conflict_do_nothing()     │
  │───────────── INSERT ... ON CONFLICT DO NOTHING ──>│
  │                                        │
  │ [first call: row inserted]             │
  │<──────────── 1 row affected ──────────│
  │                                        │
  │ [duplicate call: constraint fires]     │
  │───────────── INSERT ... ON CONFLICT DO NOTHING ──>│
  │<──────────── 0 rows affected ─────────│
  │ (no exception, session continues)      │
```

### 4.3 Stream B: load_student_history with 200-row cap

```
adaptive_engine.py                     PostgreSQL
  │                                        │
  │ load_student_history(student_id, ...)  │
  │                                        │
  │ SELECT avg(time), avg(wrong), ...      │
  │   FROM card_interactions               │
  │   WHERE student_id = $1               │
  │   LIMIT 200   ◄── new cap ──────────── │
  │───────────────────────────────────────>│
  │<── aggregate of ≤200 rows ────────────│
  │                                        │
  │ [trend query — limit 5, unchanged]     │
  │───────────────────────────────────────>│
  │<── 5 rows ────────────────────────────│
```

Note: The `LIMIT 200` on an aggregate query requires a subquery wrapping. The correct SQLAlchemy pattern is:

```python
# Wrap in subquery to apply row cap before aggregation
recent_interactions = (
    select(CardInteraction)
    .where(CardInteraction.student_id == sid)
    .order_by(CardInteraction.completed_at.desc())
    .limit(200)
    .subquery()
)
agg_result = await db.execute(
    select(
        func.avg(recent_interactions.c.time_on_card_sec).label("avg_time"),
        func.avg(recent_interactions.c.wrong_attempts).label("avg_wrong"),
        func.avg(recent_interactions.c.hints_used).label("avg_hints"),
        func.count(recent_interactions.c.id).label("total_cards"),
    )
)
```

This approach aggregates over only the 200 most recent rows, which is the intended semantics (recency-weighted baseline).

### 4.4 Stream B: generate_next_card() model fix

```
adaptive_engine.py                      config.py           OpenAI API
  │                                        │                    │
  │ generate_next_card(...)                │                    │
  │                                        │                    │
  │ BEFORE (bug): hardcoded OPENAI_MODEL_MINI inline import     │
  │ AFTER: model = ADAPTIVE_CARD_MODEL ────>│                   │
  │              (= "gpt-4o-mini")         │                    │
  │                                        │                    │
  │ _call_llm(llm_client, ADAPTIVE_CARD_MODEL, messages, ...)   │
  │─────────────────────────────────────────────────────────────>│
  │<── card JSON ────────────────────────────────────────────────│
```

The `generate_next_card()` function signature currently accepts a `model: str` parameter but then ignores it at line 469 by doing a local `from config import OPENAI_MODEL_MINI`. The fix removes the local import and uses `ADAPTIVE_CARD_MODEL` from config directly at the call site.

### 4.5 Stream C: performance.now() replacement

```
Browser                         CardLearningView.jsx
  │                                    │
  │ Card renders (currentCardIndex changes)
  │────────────────────────────────────>│
  │                                    │ useEffect([currentCardIndex])
  │                                    │ cardStartTimeRef.current = performance.now()
  │                                    │                    ↑
  │                                    │           was: Date.now()
  │                                    │
  │ Student proceeds to next card      │
  │────────────────────────────────────>│
  │                                    │ handleNextCard()
  │                                    │ timeOnCardSec = (performance.now() - cardStartTimeRef.current) / 1000
  │                                    │                       ↑ divide ms → seconds
  │                                    │ goToNextCard({ timeOnCardSec, ... })
```

---

## 5. Integration Design

### 5.1 Backend: config.py import pattern

All existing modules that need `MASTERY_THRESHOLD` or the adaptive constants import them at the top level:

```python
# teaching_service.py — replace local definition
from config import (
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_MODEL_MINI,
    MASTERY_THRESHOLD,  # ← added; remove local MASTERY_THRESHOLD = 70
)

# adaptive_engine.py — replace inline definitions in build_blended_analytics()
from config import (
    OPENAI_MODEL,
    ADAPTIVE_CARD_MODEL,
    ADAPTIVE_MIN_HISTORY_CARDS,
    ADAPTIVE_ACUTE_HIGH_TIME_RATIO,
    ADAPTIVE_ACUTE_LOW_TIME_RATIO,
    ADAPTIVE_ACUTE_WRONG_RATIO,
    ADAPTIVE_ACUTE_CURRENT_WEIGHT,
    ADAPTIVE_ACUTE_HISTORY_WEIGHT,
    ADAPTIVE_NORMAL_CURRENT_WEIGHT,
    ADAPTIVE_NORMAL_HISTORY_WEIGHT,
)
```

The `build_blended_analytics()` function currently defines `MIN_HISTORY_CARDS = 5` as a local variable (line 394) and uses hardcoded `2.0`, `0.4`, `3.0`, `0.9`, `0.1`, `0.6`, `0.4` literals throughout. All of these are replaced with the config imports above.

### 5.2 Backend: PostgreSQL dialect import for ON CONFLICT

```python
# teaching_service.py — add import
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Replace:
db.add(SpacedReview(
    student_id=session.student_id,
    concept_id=session.concept_id,
    review_number=i,
    due_at=now_utc + timedelta(days=days),
))

# With:
stmt = pg_insert(SpacedReview).values(
    student_id=session.student_id,
    concept_id=session.concept_id,
    review_number=i,
    due_at=now_utc + timedelta(days=days),
).on_conflict_do_nothing(
    index_elements=["student_id", "concept_id", "review_number"]
)
await db.execute(stmt)
```

Note: `index_elements` must match the column names in the `UniqueConstraint` defined in the model.

### 5.3 Frontend: components/ui/ index barrel

A barrel file at `frontend/src/components/ui/index.js` exports all primitives:

```javascript
export { default as Button }      from "./Button.jsx";
export { default as Card }        from "./Card.jsx";
export { default as Badge }       from "./Badge.jsx";
export { default as Skeleton }    from "./Skeleton.jsx";
export { default as ProgressRing } from "./ProgressRing.jsx";
export { default as Toast }       from "./Toast.jsx";
```

Pages import from the barrel: `import { Button, Card, Badge } from "../components/ui";`

---

## 6. Security Design

### Authentication and Authorisation
No change. All endpoints retain existing session-cookie / student-context authentication.

### Data Encryption
No change. At-rest and in-transit encryption is unchanged.

### Input Validation
No new inputs are introduced. The mastery threshold is a server-side constant, not a client-supplied value.

### Secrets Management
`ADAPTIVE_CARD_MODEL` and other new config constants are not secrets. They are code-level defaults. If env-var override is needed in future, the pattern `os.getenv("ADAPTIVE_CARD_MODEL", "gpt-4o-mini")` is used.

---

## 7. Observability Design

### Logging

**Stream B — model fix:** Add a log statement in `generate_next_card()` to confirm the model in use:

```python
logger.info(
    "generate_next_card: model=%s card_index=%d student_id=%s",
    ADAPTIVE_CARD_MODEL,
    card_index,
    student_id,
)
```

**Stream B — ON CONFLICT:** The `pg_insert().on_conflict_do_nothing()` call silently swallows conflicts. Add a row-count check:

```python
result = await db.execute(stmt)
if result.rowcount == 0:
    logger.debug(
        "spaced_review_conflict_ignored: student_id=%s concept_id=%s review_number=%d",
        session.student_id,
        session.concept_id,
        i,
    )
```

### Metrics
No new metrics dashboards required. Existing `adaptive_lesson_generated` and `card_interaction` log lines provide sufficient signal.

### Alerting
No new alerting thresholds. The existing P95 latency alert on `/api/v2/sessions/{id}/answer` will reflect the mastery threshold change through a possible slight increase in completion rate.

---

## 8. Error Handling and Resilience

### Stream A
`MASTERY_THRESHOLD` is a module-level integer constant. No error handling required. If `config.py` fails to import (syntax error), the application will not start — this is the correct fail-fast behaviour.

### Stream B — ON CONFLICT DO NOTHING
SQLAlchemy `execute()` with `on_conflict_do_nothing()` does not raise on conflict. The `rowcount` may be 0. This is safe; the loop continues to the next review interval.

If `pg_insert` is used but the UniqueConstraint does not yet exist in the DB (migration not yet applied), the conflict will not be caught and duplicate rows will still be inserted. This is safe behaviour — the `on_conflict_do_nothing` simply has no effect until the constraint exists.

### Stream B — History cap
If the subquery returns 0 rows (new student), all aggregate values are `None`. The existing `or None` / `or 0.0` fallbacks in `load_student_history()` handle this correctly. No new error handling needed.

### Stream C — ProgressRing
If `score` is `null` or `undefined` at mount time, `stroke-dashoffset` is computed as `circumference` (0% fill). This is the correct visual state — an empty ring. No JS error.

### Stream C — CSS confetti
The confetti is a purely visual `@keyframes` animation applied to a `div`. If the animation is not supported (very old browsers), the confetti simply does not appear. No error handling needed.

### Retry Policies
No change to existing 3-attempt / exponential back-off retry policy in `_call_llm`.

---

## 9. Testing Strategy

### Unit Tests

| Test | File | What to Verify |
|------|------|---------------|
| `test_mastery_threshold_is_60` | `tests/test_teaching_service.py` | `MASTERY_THRESHOLD == 60`; score 60 → `mastered=True`; score 59 → `mastered=False` |
| `test_mastery_threshold_from_config` | `tests/test_config.py` | `from config import MASTERY_THRESHOLD; assert MASTERY_THRESHOLD == 60` |
| `test_adaptive_constants_in_config` | `tests/test_config.py` | All 11 constants importable from `config`; values match spec |
| `test_build_blended_analytics_uses_config` | `tests/test_adaptive_engine.py` | Constants from config match behaviour (pass mock history with values triggering acute/normal paths) |
| `test_generate_next_card_uses_adaptive_card_model` | `tests/test_adaptive_engine.py` | `_call_llm` is called with `ADAPTIVE_CARD_MODEL` not `OPENAI_MODEL` |
| `test_spaced_review_unique_constraint` | `tests/test_models.py` | Attempting to insert duplicate `(student_id, concept_id, review_number)` raises `IntegrityError` |

### Integration Tests

| Test | File | What to Verify |
|------|------|---------------|
| `test_session_mastered_at_score_60` | `tests/integration/test_teaching_flow.py` | Full session ending with score 60 → `student_mastery` row inserted |
| `test_session_not_mastered_at_score_59` | `tests/integration/test_teaching_flow.py` | Score 59 → no `student_mastery` row |
| `test_spaced_review_on_conflict_do_nothing` | `tests/integration/test_teaching_flow.py` | Completing same session twice does not create duplicate `spaced_reviews` rows |
| `test_load_student_history_capped_at_200` | `tests/integration/test_adaptive_engine.py` | Seed 300 `CardInteraction` rows; `total_cards_completed` returns 200 |

### Frontend Tests
Stream C changes are visual. Testing approach:
- Manual visual review in all 4 themes (default, pirate, astronaut, gamer) on Chrome, Firefox, Safari
- Manual review at 375px (mobile), 768px (tablet), 1440px (desktop) viewports
- Performance.now() change: verify `time_on_card_sec` is a plausible float > 0 in the `goToNextCard` call via React Testing Library if a test suite exists

### End-to-End Tests
No dedicated E2E test change required. The existing session lifecycle E2E test (if present) should be updated to assert `mastered: true` at score 60.

---

## Component Specifications: Stream C

### 9.1 New CSS @keyframes

```css
/* Shake on wrong answer */
@keyframes ada-shake {
  0%, 100% { transform: translateX(0); }
  15%      { transform: translateX(-6px); }
  30%      { transform: translateX(6px); }
  45%      { transform: translateX(-4px); }
  60%      { transform: translateX(4px); }
  75%      { transform: translateX(-2px); }
}

/* Confetti pieces (applied to individual spans) */
@keyframes ada-confetti-fall {
  0%   { transform: translateY(-20px) rotate(0deg); opacity: 1; }
  100% { transform: translateY(120px) rotate(720deg); opacity: 0; }
}

/* Skeleton shimmer */
@keyframes ada-skeleton-shimmer {
  0%   { background-position: -400px 0; }
  100% { background-position:  400px 0; }
}

/* Fade-slide in for panels */
@keyframes ada-slide-in-right {
  from { transform: translateX(24px); opacity: 0; }
  to   { transform: translateX(0);    opacity: 1; }
}

/* ProgressRing fill — triggers via CSS class added on mount */
@keyframes ada-ring-fill {
  from { stroke-dashoffset: var(--ring-circumference); }
  to   { stroke-dashoffset: var(--ring-offset); }
}
```

### 9.2 Skeleton Component Spec

```jsx
// frontend/src/components/ui/Skeleton.jsx
// Props: width (string|number), height (string|number), rounded (bool), className (string)
// Renders a div with the shimmer animation.
// Uses CSS custom property --shimmer-* tokens.
```

Inline style pattern (no Tailwind class needed):
```css
.ada-skeleton {
  background: linear-gradient(
    90deg,
    var(--shimmer-from) 25%,
    var(--shimmer-via)  50%,
    var(--shimmer-to)   75%
  );
  background-size: 400px 100%;
  animation: ada-skeleton-shimmer 1.4s ease infinite;
}
```

### 9.3 ProgressRing Component Spec

```jsx
// frontend/src/components/ui/ProgressRing.jsx
// Props: score (0-100), size (px, default 130), strokeWidth (default 8),
//        animate (bool, default true), label (string)
//
// Implementation:
//   circumference = 2 * Math.PI * radius
//   offset = circumference - (score / 100) * circumference
//   Use CSS var(--ring-circumference) and var(--ring-offset) set via style prop
//   SVG: viewBox="0 0 {size} {size}", circle cx/cy = size/2, r = radius
//   On mount: add class "animated" to trigger ada-ring-fill keyframe
```

Score-to-colour mapping for ProgressRing and CompletionView (aligned with 60-threshold):
```
score >= 90  → var(--color-success)    [green]
score >= 60  → var(--color-primary)    [blue]
score >= 40  → #f59e0b                 [amber]
score <  40  → var(--color-danger)     [red]
```

### 9.4 ConceptPanel Slide-In Spec

`ConceptPanel.jsx` replaces the existing absolute-positioned tooltip div inside `ConceptMapPage.jsx`.

Layout change to `ConceptMapPage`:
```
Before:
  [Sidebar 340px] | [Graph flex:1]
                       └─ absolute div top-right (310px wide)

After:
  [Sidebar 340px] | [Graph flex:1] | [ConceptPanel 320px, slide-in]
                                         └─ only visible when selectedNode != null
```

The ConceptPanel:
- Is a `div` with `position: relative` (not absolute) in a flex row
- Animates in/out using `ada-slide-in-right` when `selectedNode` changes
- Width: 320px, hidden (width 0, overflow hidden) when no node is selected
- Transition: `width var(--motion-normal), opacity var(--motion-normal)`
- Contains: status badge, title, chapter/section, style selector, interest chips, CTA button
- Content is moved verbatim from the existing absolute overlay; only layout wrapper changes

### 9.5 CardLearningView Redesign Spec

**Pill MCQ Buttons:**
- Replace rectangular bordered buttons with pill-shaped buttons (`border-radius: var(--radius-full)`)
- Left label circle: A/B/C/D in 20px circle, filled on selection
- Correct state: solid `var(--color-success)` background, white text
- Wrong state: `ada-shake` animation (300ms), `var(--color-danger)` outline

**Shake-on-Wrong:**
```jsx
// Apply class "shake" to MCQ button on wrong answer
// CSS: .shake { animation: ada-shake 0.35s ease; }
// Remove class after animation ends via onAnimationEnd
```

**Segmented ProgressDots:**
The current `CardProgress` component renders circles. Redesign as a segmented bar:
- Each segment: `height: 4px`, `border-radius: var(--radius-full)`
- Completed: `var(--color-success)`
- Current: `var(--color-primary)` with a 1.5x width pulse
- Pending: `var(--color-border)`
- Segments connected by 4px gap, no connector line

**Focus Mode:**
- The main card panel occupies 100% viewport width on the first card (no AssistantPanel rendered yet)
- AssistantPanel slides in from the right when the first question is answered
- This is a progressive disclosure pattern; the AssistantPanel `width` transitions from 0 → 320px

**Inline Hints:**
- When an LLM hint arrives (AssistantPanel updates), a toast notification appears above the MCQ block: "Hint available — check the panel"
- The Toast component auto-dismisses after 3 seconds

### 9.6 SocraticChat Redesign Spec

**Fixed Input Bar:**
```
┌─────────────────────────────────────────────────┐
│  Chat Header (gradient, fixed height)            │
├─────────────────────────────────────────────────┤
│  Messages area (flex: 1, overflow-y: auto)       │
│  [auto-scroll to bottom on new message]          │
│  [TypingIndicator when loading=true]             │
├─────────────────────────────────────────────────┤
│  Input bar (fixed at bottom, never scrolls)      │
│  [textarea] [Send button]                        │
│  Shift+Enter for newline, Enter sends            │
└─────────────────────────────────────────────────┘
```

The entire component uses `display: flex; flex-direction: column; height: 100%` so the input bar sticks to the bottom within the containing layout.

**Typing Indicator:**
```jsx
function TypingIndicator() {
  // Three dots, each with animation-delay 0ms, 150ms, 300ms
  // @keyframes ada-dot-pulse: 0%/100% opacity 0.2, 50% opacity 1
  return (
    <div className="typing-indicator">
      <span /><span /><span />
    </div>
  );
}
```

**Auto-scroll reliability:**
The current `scrollIntoView` call works but may not fire if the DOM hasn't updated yet. The fix is to use `useLayoutEffect` instead of `useEffect` for the scroll, or wrap in `setTimeout(fn, 0)`.

**Enter key handling:**
```jsx
const handleKeyDown = (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSubmit(e);
  }
};
```
Apply `onKeyDown={handleKeyDown}` to the `<textarea>` (change from `<input>` to `<textarea>` for multi-line support with Shift+Enter).

### 9.7 CompletionView Redesign Spec

**Confetti:**
```jsx
// Render 20 <span> elements, each positioned with random left% (0–100)
// Each span: width 8px, height 8px or 6px, random background from palette
// Animation: ada-confetti-fall with random duration (0.8–1.4s) and delay (0–0.5s)
// Only render when mastered=true
// Palette: [--color-primary, --color-success, #f59e0b, #ec4899, #8b5cf6]
```

**SVG ProgressRing:**
Replace the bordered `div` circle with `<ProgressRing score={score} size={130} />` from `components/ui`.

**Score Bands (updated to 60-threshold):**
```javascript
const scoreConfig = score >= 90
  ? { color: "var(--color-success)",  label: "Excellent", icon: Trophy  }
  : score >= 60
  ? { color: "var(--color-primary)",  label: "Mastered",  icon: Star    }
  : score >= 40
  ? { color: "#f59e0b",               label: "Good Try",  icon: Star    }
  : { color: "var(--color-danger)",   label: "Keep Going",icon: RefreshCw };
```

The banner background transitions from the current static green/amber to the `scoreConfig.color` using a gradient.

### 9.8 AppShell Student Dropdown Spec

Replace the centered `<span>` student name with a button that opens a popover:

```
┌────────────────────────────────────────────────────────┐
│ [Brain + ADA]  [Map]          [▼ Student Name]  [Lang] [Style] │
└────────────────────────────────────────────────────────┘
                                      │
                              ┌───────▼──────────┐
                              │  Student Name     │
                              │  Preferred Lang   │
                              │  Preferred Style  │
                              │  ─────────────── │
                              │  [Switch Student] │
                              └───────────────────┘
```

Implementation:
- `useState(false)` for `dropdownOpen`
- Popover: absolute-positioned div below the button, `z-index: 100`, `box-shadow: var(--shadow-lg)`
- Close on outside click via `useEffect` with document `mousedown` listener
- "Switch Student" calls `logout()` and navigates to `/`

---

## Key Decisions Requiring Stakeholder Input

1. **ConceptPanel as permanent flex column vs transient panel:** Should the graph shrink when the panel opens (flex column approach, graph loses 320px) or should the panel overlay the graph (absolute position, graph unchanged)? The slide-in from outside the graph is less visually disruptive but requires the parent flex container to allocate the 320px slot. Confirm which layout is preferred.

2. **SocraticChat input: `<input>` vs `<textarea>`:** The current implementation uses a single-line `<input>`. Switching to `<textarea>` for Shift+Enter multiline support changes the height of the input bar. Confirm whether multiline input is desired.

3. **CompletionView confetti: only on mastered, or on all completions?** The spec says confetti appears on completion. The design above shows it only for mastered. Confirm.

4. **ProgressRing animation duration:** The spec does not specify. The design uses `600ms cubic-bezier(0.34, 1.56, 0.64, 1)` (spring-like overshoot). Confirm or adjust.
