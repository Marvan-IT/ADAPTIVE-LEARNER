# Full Adaptive Upgrade — Detailed Low-Level Design

**Feature slug:** `full-adaptive-upgrade`
**Date:** 2026-03-02
**Status:** Approved for implementation

---

## 1. Component Breakdown

| Component | File | Single Responsibility | Changes |
|-----------|------|-----------------------|---------|
| **TeachingService** | `backend/src/api/teaching_service.py` | Orchestrate LLM session lifecycle | Add adaptive context loading to `generate_cards()` and `begin_socratic_check()` |
| **PromptBuilder (teaching)** | `backend/src/api/prompts.py` | Assemble system/user prompts for presentation, cards, and Socratic phases | Add `learning_profile`, `history`, `wrong_option_pattern`, and `session_card_stats` parameters; inject mode-specific blocks |
| **PromptBuilder (adaptive)** | `backend/src/adaptive/prompt_builder.py` | Assemble system/user prompts for adaptive lesson (v3) | Fix FAST/STRONG wording (~line 213) only |
| **TeachingRouter** | `backend/src/api/teaching_router.py` | Route HTTP requests to service; handle XP award | Add XP award call after mastery in `respond_to_check`; populate `xp_awarded` on response |
| **TeachingSchemas** | `backend/src/api/teaching_schemas.py` | Pydantic request/response models | Add `xp_awarded: int | None = None` to `SocraticResponse` |
| **Config** | `backend/src/config.py` | All constants | Add `XP_MASTERY`, `XP_MASTERY_BONUS`, `XP_MASTERY_BONUS_THRESHOLD`, `XP_CONSOLATION`, `XP_CARD_ADVANCE` |
| **SessionContext** | `frontend/src/context/SessionContext.jsx` | Client-side session state machine | Wire `updateMode` + `awardXP` after `ADAPTIVE_CARD_LOADED`; wire `awardXP` + streak after mastery |
| **AppShell** | `frontend/src/components/layout/AppShell.jsx` | Navigation shell and game HUD | Mount `XPBurst` component (others already mounted) |
| **CardLearningView** | `frontend/src/components/learning/CardLearningView.jsx` | Card display, question answering, signal tracking | Verify `recordAnswer(false)` is called on wrong MCQ; verify `awardXP(5)` for TF correct |
| **LearningPage** | `frontend/src/pages/LearningPage.jsx` | Route-level lesson page | Add optional "Customize this lesson" collapsible panel |
| **StudentForm** | `frontend/src/components/` (locate exact path) | Student profile creation form | Change interests field label to subtle hint text |

**Unchanged / Reused without modification:**
- `backend/src/adaptive/adaptive_engine.py` — `load_student_history()`, `load_wrong_option_pattern()`: called as-is
- `backend/src/adaptive/profile_builder.py` — `build_learning_profile()`, `build_generation_profile()`: called as-is
- `backend/src/adaptive/schemas.py` — `AnalyticsSummary`, `LearningProfile`: used as-is
- `frontend/src/store/adaptiveStore.js` — `awardXP()`, `recordAnswer()`, `updateMode()`, `init()`: used as-is
- All five game components in `frontend/src/components/game/`: used as-is
- `PATCH /api/v2/students/{id}/progress` endpoint: used as-is

---

## 2. Data Design

### No Schema Changes
No new tables, columns, or migrations are required. All required data is already present:

- `card_interactions.student_id`, `card_interactions.concept_id`, `card_interactions.time_on_card_sec`, `card_interactions.wrong_attempts`, `card_interactions.hints_used` — source for `load_student_history()` and `load_wrong_option_pattern()`
- `card_interactions.session_id` — source for session-level stats in `begin_socratic_check()`
- `students.xp`, `students.streak` — target for atomic XP/streak update

### New Config Constants (`backend/src/config.py`)

```python
# ── XP Award Values ────────────────────────────────────────────────────────────
XP_MASTERY: int = 50                  # Base XP awarded on concept mastery
XP_MASTERY_BONUS: int = 25            # Bonus XP when check_score >= XP_MASTERY_BONUS_THRESHOLD
XP_MASTERY_BONUS_THRESHOLD: int = 90  # Score (0–100) qualifying for mastery bonus
XP_CONSOLATION: int = 10              # Consolation XP when session completes without mastery
XP_CARD_ADVANCE: int = 5              # XP awarded in the frontend per card advance (informational)
```

### Internal Data Flows

#### Flow A: generate_cards() adaptive enrichment

```
generate_cards(db, session, student)
    |
    ├── asyncio.gather(
    │       load_student_history(student_id, concept_id, db),
    │       load_wrong_option_pattern(student_id, concept_id, db)
    │   )
    │   → (history: dict, wrong_option_pattern: int | None)
    |
    ├── if history["total_cards_completed"] >= 3:
    │       AnalyticsSummary(
    │           student_id=..., concept_id=...,
    │           time_spent_sec=history["avg_time_per_card"] or 120.0,
    │           expected_time_sec=120.0,
    │           attempts=max(1, round((history["avg_wrong_attempts"] or 0) + 1)),
    │           wrong_attempts=round(history["avg_wrong_attempts"] or 0),
    │           hints_used=round(history["avg_hints_per_card"] or 0),
    │           revisits=0, recent_dropoffs=0, skip_rate=0.0,
    │           quiz_score=1.0 - (history["avg_wrong_attempts"] or 0) * 0.15,  # proxy
    │           last_7d_sessions=history["sessions_last_7d"],
    │       )
    │       → build_learning_profile(analytics, has_unmet_prereq=False)
    │       → learning_profile: LearningProfile
    │   else:
    │       learning_profile = None
    |
    ├── build_cards_system_prompt(
    │       style, interests, language,
    │       learning_profile=learning_profile,   # NEW
    │       history=history,                      # NEW
    │   )
    │
    └── build_cards_user_prompt(
            concept_title, sub_sections, latex, images,
            wrong_option_pattern=wrong_option_pattern,  # NEW
        )
```

Note on `quiz_score` proxy: Since `load_student_history()` returns `avg_wrong_attempts` but not a direct quiz score, the proxy formula `1.0 - min(avg_wrong_attempts * 0.15, 0.9)` gives a plausible score in [0.1, 1.0]. This is bounded to prevent a value below 0.1 (which would over-classify as STRUGGLING). The proxy is only used to build the initial profile for card generation; the Socratic check uses the same formula already present in the service for `begin_socratic_check()`.

#### Flow B: begin_socratic_check() session stats

```
begin_socratic_check(db, session, student)
    |
    ├── SELECT count(*), sum(wrong_attempts), sum(hints_used)
    │   FROM card_interactions
    │   WHERE session_id = session.id
    │   → session_card_stats: dict | None
    │     {
    │       "total_cards":  int,
    │       "total_wrong":  int,
    │       "total_hints":  int,
    │       "error_rate":   float  (total_wrong / max(total_cards, 1))
    │     }
    |
    └── build_socratic_system_prompt(
            ...,
            socratic_profile=socratic_profile,   # existing
            history=history,                      # existing
            session_card_stats=session_card_stats,  # NEW
        )
```

#### Flow C: XP award after mastery

```
respond_to_check handler in teaching_router.py
    |
    └── result = await teaching_svc.handle_student_response(db, session, req.message)
         |
         └── if result["check_complete"]:
               if result["mastered"]:
                   xp_delta = XP_MASTERY + (XP_MASTERY_BONUS if result["score"] >= XP_MASTERY_BONUS_THRESHOLD else 0)
                   new_streak = student.streak + 1
               else:
                   xp_delta = XP_CONSOLATION
                   new_streak = student.streak  # streak unchanged on non-mastery
               |
               ├── asyncio.create_task(
               │       _award_xp(student_id, xp_delta, new_streak, db)
               │   )   ← fire-and-forget; does not block response
               |
               └── return SocraticResponse(..., xp_awarded=xp_delta)
```

The `_award_xp` helper executes `update(Student).values(xp=Student.xp + xp_delta, streak=new_streak)` and commits. It is a private async function in the router module.

---

## 3. API Design

### Modified Endpoint: POST /api/v2/sessions/{session_id}/respond

**Existing endpoint** — response schema change only.

**Response schema change in `teaching_schemas.py`:**

```python
class SocraticResponse(BaseModel):
    session_id: UUID
    response: str
    phase: str
    check_complete: bool
    score: int | None = None
    mastered: bool | None = None
    exchange_count: int
    xp_awarded: int | None = None   # NEW — populated only when check_complete=True
```

**Behaviour change:** When `check_complete=True`, `xp_awarded` is set to the XP actually awarded (50, 75, or 10). When `check_complete=False`, `xp_awarded` remains `None`. This is backward-compatible: clients that do not consume `xp_awarded` ignore the new field.

**All other endpoints:** No changes. No new endpoints.

### Error Handling Conventions (additions)

- History load failure in `generate_cards()`: log `WARNING` with structured fields; continue with `learning_profile=None`, `wrong_option_pattern=None`
- Session stats query failure in `begin_socratic_check()`: log `WARNING`; continue with `session_card_stats=None`
- XP award failure (DB error in `_award_xp`): log `WARNING`; swallow exception (client already has local XP from Zustand store; hydration on next load corrects any discrepancy)

---

## 4. Sequence Diagrams

### 4.1 generate_cards() — Full Adaptive Path

```
Client                  TeachingRouter           TeachingService           DB                    OpenAI
  |                           |                        |                    |                       |
  |--POST /sessions/{id}/cards|                        |                    |                       |
  |                           |--generate_cards(db, session, student)       |                       |
  |                           |                        |--gather(           |                       |
  |                           |                        |   load_student_history(sid, cid, db)       |
  |                           |                        |   load_wrong_option_pattern(sid, cid, db)  |
  |                           |                        |)-->                |                       |
  |                           |                        |             SELECT card_interactions        |
  |                           |                        |<--(history, wrong_option_pattern)           |
  |                           |                        |                    |                       |
  |                           |                        | [if total_cards >= 3]                      |
  |                           |                        |--build_learning_profile(analytics)          |
  |                           |                        |<--learning_profile                         |
  |                           |                        |                    |                       |
  |                           |                        |--build_cards_system_prompt(..., profile, history)
  |                           |                        |--build_cards_user_prompt(..., wrong_option)
  |                           |                        |                    |                       |
  |                           |                        |--chat(system, user, max_tokens=8000)------->|
  |                           |                        |<--(cards JSON)----------------------------  |
  |                           |                        |                    |                       |
  |                           |                        |--post_process(raw_cards)                   |
  |                           |                        |--session.presentation_text = json.dumps()  |
  |                           |                        |--db.flush()------> |                       |
  |                           |<--CardsResponse        |                    |                       |
  |<--200 CardsResponse       |                        |                    |                       |
```

### 4.2 begin_socratic_check() — Session Stats Path

```
Client                  TeachingRouter           TeachingService           DB
  |                           |                        |                    |
  |--POST /sessions/{id}/check|                        |                    |
  |                           |--begin_socratic_check(db, session, student) |
  |                           |                        |                    |
  |                           |                        |--SELECT count/sum FROM card_interactions
  |                           |                        |   WHERE session_id=session.id----------->  |
  |                           |                        |<--session_card_stats (or None on error)    |
  |                           |                        |                    |                       |
  |                           |                        |--load_student_history(...)---------------->|
  |                           |                        |<--history                                  |
  |                           |                        | [if total_cards >= 5]                      |
  |                           |                        |--build_learning_profile(analytics)          |
  |                           |                        |                    |                       |
  |                           |                        |--build_socratic_system_prompt(
  |                           |                        |     ..., session_card_stats=session_card_stats)
  |                           |                        |--chat(messages, max_tokens=500, model=mini) (OpenAI)
  |                           |                        |--db.flush()                               |
  |                           |<--first_question                            |                       |
  |<--200 SocraticResponse    |                        |                    |                       |
```

### 4.3 respond_to_check() — XP Award Path

```
Client                  TeachingRouter           TeachingService           DB
  |                           |                        |                    |
  |--POST /sessions/{id}/respond                       |                    |
  |                           |--handle_student_response(db, session, msg) |
  |                           |<--result {check_complete=True, mastered=True, score=85}
  |                           |                        |                    |
  |                           | [check_complete=True]  |                    |
  |                           |--xp_delta = XP_MASTERY (50)                |
  |                           | [score=85 < 90: no bonus]                  |
  |                           |--new_streak = student.streak + 1           |
  |                           |--create_task(_award_xp(sid, 50, streak+1, db))
  |                           |              (background, non-blocking)     |
  |                           |              UPDATE students SET xp=xp+50, streak=N-->|
  |                           |                        |                    |
  |<--200 SocraticResponse(xp_awarded=50)              |                    |
```

### 4.4 Frontend — SessionContext mastery XP wiring

```
SocraticChat.jsx        SessionContext.jsx       adaptiveStore.js     API (students)
     |                        |                       |                    |
     |--sendAnswer(message)--> |                       |                    |
     |                        |--sendResponse(session_id, msg)------------>|
     |                        |<--{check_complete: true, mastered: true, score: 85, xp_awarded: 50}
     |                        |                       |                    |
     |                        |--dispatch CHECK_RESPONDED                  |
     |                        | [check_complete=true] |                    |
     |                        |--[mastered=true]      |                    |
     |                        |--awardXP(xp_awarded)  |                    |
     |                        |  (useAdaptiveStore.getState().awardXP(50)) |
     |                        |                       |--set xp+=50, level |
     |                        |--set state.streak+1   |                    |
     |                        |--refreshMastery()----------------------------->|
     |                        |                       |                    |
```

---

## 5. Integration Design

### 5.1 `load_student_history()` and `load_wrong_option_pattern()` Integration

Both functions live in `backend/src/adaptive/adaptive_engine.py`. They are already used in `begin_socratic_check()` and the adaptive card endpoint. The `generate_cards()` integration follows the exact same import pattern:

```python
# At top of teaching_service.py method (lazy import, same pattern as begin_socratic_check)
from adaptive.adaptive_engine import load_student_history, load_wrong_option_pattern
from adaptive.profile_builder import build_learning_profile
from adaptive.schemas import AnalyticsSummary
```

Both functions accept `(student_id: str, concept_id: str, db: AsyncSession)`. They return their respective types with graceful None/fallback behaviour on error.

### 5.2 XP Award Integration

The XP award uses the existing `update_student_progress` endpoint internally via a direct DB `UPDATE` (not an HTTP call to self). The router has direct DB access via `AsyncSession`, so it uses SQLAlchemy directly:

```python
# In teaching_router.py
from sqlalchemy import update
from db.models import Student
from config import XP_MASTERY, XP_MASTERY_BONUS, XP_MASTERY_BONUS_THRESHOLD, XP_CONSOLATION

async def _award_xp(student_id: UUID, xp_delta: int, new_streak: int, db: AsyncSession):
    try:
        await db.execute(
            update(Student)
            .where(Student.id == student_id)
            .values(xp=Student.xp + xp_delta, streak=new_streak)
        )
        await db.commit()
        logger.info("[xp-awarded] student_id=%s xp=%d new_streak=%d", student_id, xp_delta, new_streak)
    except Exception as exc:
        logger.warning("[xp-award-failed] student_id=%s error=%s", student_id, exc)
```

**Note:** Because this runs as `asyncio.create_task()` the `db` session must already be in a committed/flushed state from the primary transaction. The task acquires a fresh connection from the pool. Alternatively, the implementation may call `await db.execute(...)` inline (not as a background task) and commit after the mastery record flush — this is simpler and acceptable given the latency budget. The developer should choose the inline approach for simplicity unless benchmarks show it is problematic.

**Recommendation: Use inline (not background task)** — the latency of a single indexed UPDATE + commit is under 5 ms. Inline is simpler, transactionally safer, and avoids session lifecycle concerns with background tasks.

### 5.3 Frontend `SessionContext.jsx` Integration Points

Two new calls added to existing callbacks:

```javascript
// After ADAPTIVE_CARD_LOADED dispatch (in goToNextCard callback)
dispatch({ type: "ADAPTIVE_CARD_LOADED", payload: res.data });
useAdaptiveStore.getState().updateMode(res.data.learning_profile_summary);  // NEW
useAdaptiveStore.getState().awardXP(XP_CARD_ADVANCE);                        // NEW (XP_CARD_ADVANCE = 5, defined in frontend/src/utils/constants.js)

// After CHECK_RESPONDED dispatch with check_complete=true (in sendAnswer callback)
if (res.data.check_complete) {
  // Existing mastery track + refreshMastery() ...
  if (res.data.xp_awarded) {                                     // NEW
    useAdaptiveStore.getState().awardXP(res.data.xp_awarded);    // NEW
  }
  if (res.data.mastered) {
    // Increment streak in store (server already updated DB streak)
    const { streak } = useAdaptiveStore.getState();
    useAdaptiveStore.getState().recordAnswer(true);               // NEW — drives streak display
  }
}
```

**`XP_CARD_ADVANCE` in frontend:** Add to `frontend/src/utils/constants.js`:
```javascript
export const XP_CARD_ADVANCE = 5;
```
This mirrors the backend constant. The frontend value drives only the local Zustand store; the server-authoritative value is used for the mastery XP award which is synced back to the DB.

---

## 6. Security Design

### Authentication and Authorization
No changes. The `APIKeyMiddleware` and `slowapi` rate limiting already protect all endpoints. The new DB queries and prompt enrichment are internal operations on the existing session's data.

### Data Exposure
- `learning_profile` and `wrong_option_pattern` are injected into the LLM system prompt only. They are not included in any API response body.
- `session_card_stats` is injected into the Socratic system prompt only. Not in response.
- `xp_awarded` is new in `SocraticResponse` but contains only a non-sensitive integer.

### Input Validation
- All new parameters in prompt functions are typed (`LearningProfile | None`, `int | None`, `dict | None`). Python's type system and Pydantic's model validation prevent injection.
- `wrong_option_pattern` is an integer (0–3). The prompt block wraps it in a string literal: `f"Option index {wrong_option_pattern} (0-based)"` — no string interpolation of user-supplied values.

---

## 7. Observability Design

### Logging

All logging uses the existing Python `logging` module with structured fields. No `print()` statements.

#### New log lines:

**`teaching_service.py` — `generate_cards()`:**
```python
logger.info(
    "[cards-adaptive] student_id=%s concept_id=%s history_cards=%d "
    "profile=%s/%s/%s wrong_option_pattern=%s",
    str(session.student_id), session.concept_id,
    history["total_cards_completed"],
    learning_profile.speed if learning_profile else "NONE",
    learning_profile.comprehension if learning_profile else "NONE",
    learning_profile.engagement if learning_profile else "NONE",
    wrong_option_pattern,
)
```

**`teaching_service.py` — `begin_socratic_check()`:**
```python
if session_card_stats:
    logger.info(
        "[socratic-adaptive] session_id=%s session_cards=%d session_wrong=%d "
        "session_hints=%d error_rate=%.2f",
        str(session.id),
        session_card_stats["total_cards"],
        session_card_stats["total_wrong"],
        session_card_stats["total_hints"],
        session_card_stats["error_rate"],
    )
```

**`teaching_router.py` — `_award_xp()`:**
```python
logger.info(
    "[xp-awarded] student_id=%s xp_delta=%d new_streak=%d mastered=%s score=%s",
    student_id, xp_delta, new_streak, mastered, score,
)
```

### Metrics / Dashboards (no new dashboards — add to existing)
- Track `learning_profile` distribution in card generation logs (STRUGGLING/OK/STRONG ratios)
- Track `wrong_option_pattern` injection rate (% of sessions where pattern != None)
- Track XP award events per day

### Alerting
No new alerts. Existing rate-limit and error-rate alerts cover the modified endpoints.

---

## 8. Error Handling and Resilience

### 8.1 `generate_cards()` — History Load Failure

```python
try:
    history, wrong_option_pattern = await asyncio.gather(
        load_student_history(str(session.student_id), session.concept_id, db),
        load_wrong_option_pattern(str(session.student_id), session.concept_id, db),
    )
except Exception as exc:
    logger.warning("[cards-adaptive] history_load_failed: error=%s — using defaults", exc)
    history = {
        "total_cards_completed": 0,
        "avg_time_per_card": None,
        "avg_wrong_attempts": None,
        "avg_hints_per_card": None,
        "sessions_last_7d": 0,
        "is_known_weak_concept": False,
        "failed_concept_attempts": 0,
        "trend_direction": "STABLE",
        "trend_wrong_list": [],
    }
    wrong_option_pattern = None
```

Note: `load_wrong_option_pattern()` already has its own internal `try/except` that returns `None` on failure. The outer `asyncio.gather` `try/except` handles the case where `load_student_history()` raises.

### 8.2 `begin_socratic_check()` — Session Stats Query Failure

```python
try:
    stats_result = await db.execute(
        select(
            func.count(CardInteraction.id).label("total_cards"),
            func.coalesce(func.sum(CardInteraction.wrong_attempts), 0).label("total_wrong"),
            func.coalesce(func.sum(CardInteraction.hints_used), 0).label("total_hints"),
        )
        .where(CardInteraction.session_id == session.id)
    )
    row = stats_result.one()
    total_cards = row.total_cards or 0
    session_card_stats = {
        "total_cards": total_cards,
        "total_wrong": row.total_wrong,
        "total_hints": row.total_hints,
        "error_rate": row.total_wrong / max(total_cards, 1),
    }
except Exception as exc:
    logger.warning("[socratic-adaptive] session_stats_failed: session_id=%s error=%s", session.id, exc)
    session_card_stats = None
```

### 8.3 `build_cards_system_prompt()` — Profile None Guard

Every profile-conditional block is guarded:
```python
if learning_profile is not None:
    # inject STUDENT PROFILE SUMMARY block
```
If `learning_profile` is `None`, the function returns the existing prompt unchanged — no regression.

### 8.4 `build_cards_user_prompt()` — Wrong Option None Guard

```python
if wrong_option_pattern is not None:
    # inject MISCONCEPTION ALERT block
```

### 8.5 `build_socratic_system_prompt()` — Session Stats None Guard

```python
if session_card_stats is not None:
    # inject WHAT YOU KNOW ABOUT THIS STUDENT block
```

---

## 9. Detailed Prompt Specification

This section provides the exact text of new prompt blocks to eliminate implementation ambiguity.

### 9.1 `build_cards_system_prompt()` — STUDENT PROFILE SUMMARY block

This block is appended after the existing `interests_text` and `style_text` sections.

```python
def _build_card_profile_block(learning_profile, history: dict) -> str:
    """
    Build the STUDENT PROFILE SUMMARY block for build_cards_system_prompt().
    Returns an empty string if learning_profile is None.
    """
    if learning_profile is None:
        return ""

    parts = ["\n\n---\nSTUDENT PROFILE SUMMARY — read this carefully before generating cards:"]
    parts.append(
        f"Speed: {learning_profile.speed} | "
        f"Comprehension: {learning_profile.comprehension} | "
        f"Engagement: {learning_profile.engagement} | "
        f"Confidence: {learning_profile.confidence_score:.0%}"
    )

    # Mode-specific generation instructions
    if learning_profile.comprehension == "STRUGGLING" or learning_profile.speed == "SLOW":
        parts.append(
            "\nMODE: SUPPORT\n"
            "- Use vocabulary a child aged 8-10 would understand. No jargon without a plain-English definition first.\n"
            "- Open every card explanation with a concrete real-world example BEFORE introducing any formula or rule.\n"
            "- Use analogies that connect to everyday life (cooking, sports, money, building blocks).\n"
            "- Make every MCQ option plausible in plain language — avoid obviously silly distractors.\n"
            "- Tone: warm, patient, never rushed. Short sentences. No more than 4 sentences before a bullet point."
        )

    elif learning_profile.speed == "FAST" and learning_profile.comprehension == "STRONG":
        parts.append(
            "\nMODE: ACCELERATE\n"
            "- ALL content, definitions, and formulas MUST appear — never skip substance because the student is fast.\n"
            "- Replace beginner analogies with real-world applications: show WHERE this concept is used in engineering, finance, coding, or science.\n"
            "- Add 'why it works' reasoning: after each rule or formula, explain the mathematical intuition behind it.\n"
            "- Include at least one challenging application example per card (edge case, non-obvious use, or extension).\n"
            "- Questions may use academic vocabulary. Distractors should represent common mathematical misconceptions, not guesses."
        )

    if learning_profile.engagement == "BORED":
        parts.append(
            "\nENGAGEMENT BOOST:\n"
            "- Open each card with an attention-grabbing hook: a surprising fact, an unsolved puzzle, or a real-world mystery that the concept solves.\n"
            "- Frame quiz questions as challenges or puzzles, not assessments. E.g., 'Can you catch the mistake?' or 'Which of these would a NASA engineer choose?'\n"
            "- Every card must have a non-null fun_element (a game mechanic, creative scenario, or competitive hook)."
        )

    if history.get("trend_direction") == "WORSENING":
        parts.append(
            "\nCONFIDENCE BUILDING:\n"
            "- The student's recent performance is declining. Prioritise encouragement over difficulty.\n"
            "- Do NOT increase difficulty across cards beyond what the content requires.\n"
            "- Open the first card with a strong positive hook that connects to something the student already knows.\n"
            "- MCQ options should give the student a fair chance to succeed — one clearly correct answer, no trick questions."
        )

    if history.get("is_known_weak_concept"):
        n = history.get("failed_concept_attempts", 0)
        parts.append(
            f"\nWEAK CONCEPT (failed {n} time(s)):\n"
            "- This student has attempted this concept before and not yet mastered it.\n"
            "- Use a completely different narrative frame than a standard textbook would use.\n"
            "- Lead with a story, metaphor, or real-world scenario that makes the core idea intuitive before any formal definition.\n"
            "- Scaffold carefully: never assume any prior understanding of this concept."
        )

    parts.append("---")
    return "\n".join(parts)
```

### 9.2 `build_cards_user_prompt()` — MISCONCEPTION ALERT block

Appended at the end of the user prompt, before "Respond with valid JSON only."

```python
def _build_misconception_block(wrong_option_pattern: int | None) -> str:
    if wrong_option_pattern is None:
        return ""
    return (
        f"\n\nMISCONCEPTION ALERT — this student has repeatedly selected option index "
        f"{wrong_option_pattern} (0-based) when answering questions on this concept. "
        "This suggests a persistent misunderstanding. In at least one question per card, "
        "include an MCQ where option index {wrong_option_pattern} is a plausible but INCORRECT "
        "answer that addresses exactly this misconception. The explanation for that distractor "
        "must clearly explain WHY it is wrong."
    ).format(wrong_option_pattern=wrong_option_pattern)
```

### 9.3 `build_socratic_system_prompt()` — WHAT YOU KNOW ABOUT THIS STUDENT block

Appended at the end of the prompt (after existing history and profile blocks), before the language instruction.

```python
def _build_session_stats_block(
    session_card_stats: dict | None,
    socratic_profile,
    history: dict | None,
) -> str:
    """Build the WHAT YOU KNOW ABOUT THIS STUDENT block for the Socratic prompt."""
    if session_card_stats is None and socratic_profile is None:
        return ""

    parts = ["\n\n---\nWHAT YOU KNOW ABOUT THIS STUDENT (use this to calibrate your questioning):"]

    if session_card_stats is not None:
        total_cards = session_card_stats["total_cards"]
        total_wrong = session_card_stats["total_wrong"]
        total_hints = session_card_stats["total_hints"]
        error_rate = session_card_stats["error_rate"]

        if total_cards == 0:
            parts.append("The student skipped the card phase — no card performance data available.")
        else:
            parts.append(
                f"Card phase performance: {total_cards} card(s) completed, "
                f"{total_wrong} wrong answer(s), {total_hints} hint(s) used. "
                f"Error rate: {error_rate:.0%}."
            )

            if error_rate >= 0.4:
                parts.append(
                    "INTERPRETATION: The student struggled significantly with the cards. "
                    "Ask at least 5 questions. Start very simply — test basic recognition before application. "
                    "Offer a gentle nudge if they get two consecutive questions wrong."
                )
            elif error_rate <= 0.1 and total_hints == 0:
                parts.append(
                    "INTERPRETATION: The student sailed through the cards with no errors and no hints. "
                    "You may use 3 questions minimum. Push to deeper understanding: ask WHY, not just WHAT. "
                    "Include at least one question that requires applying the concept to a novel scenario."
                )
            else:
                parts.append(
                    "INTERPRETATION: The student showed partial understanding. "
                    "Use 4 questions. Mix basic and application questions. "
                    "Pay attention to which questions reveal gaps and follow up on those."
                )

    if history and history.get("trend_direction") == "IMPROVING":
        parts.append(
            "TREND: This student is improving across recent sessions. "
            "Challenge them gently — they can handle slightly harder questions than their average suggests."
        )
    elif history and history.get("trend_direction") == "WORSENING":
        parts.append(
            "TREND: This student's performance has been declining recently. "
            "Build confidence first. Do not jump to hard questions. "
            "Acknowledge correct answers warmly before asking the next question."
        )

    parts.append("---")
    return "\n".join(parts)
```

**Integration into `build_socratic_system_prompt()`:** Replace the existing conditional profile blocks at the end of the function with a call to `_build_session_stats_block(session_card_stats, socratic_profile, history)`. Preserve the existing `is_known_weak_concept` block separately (it should remain).

The function signature becomes:
```python
def build_socratic_system_prompt(
    concept_title: str,
    concept_text: str,
    style: str = "default",
    interests: list[str] | None = None,
    images: list[dict] | None = None,
    language: str = "en",
    socratic_profile=None,        # LearningProfile | None — EXISTING
    history: dict | None = None,  # EXISTING
    session_card_stats: dict | None = None,  # NEW
) -> str:
```

### 9.4 `adaptive/prompt_builder.py` — FAST/STRONG mode fix

**Current text (lines ~208–215):**
```python
    if learning_profile.speed == "FAST" and learning_profile.comprehension == "STRONG":
        parts.append(
            "\n\nFAST/STRONG LEARNER MODE — additional requirements:\n"
            "- Include at least 2 'practice' cards with difficulty >= 4.\n"
            "- Each of those challenge cards must have a non-null fun_element "
            "(e.g., a real-world puzzle, competitive challenge, or creative twist).\n"
            "- Skip introductory analogies; assume the student grasps concepts quickly.\n"  # ← WRONG
            "- Introduce edge cases and extensions where appropriate."
        )
```

**Replace with:**
```python
    if learning_profile.speed == "FAST" and learning_profile.comprehension == "STRONG":
        parts.append(
            "\n\nFAST/STRONG LEARNER MODE — additional requirements:\n"
            "- Include at least 2 'practice' cards with difficulty >= 4.\n"
            "- Each of those challenge cards must have a non-null fun_element "
            "(e.g., a real-world puzzle, competitive challenge, or creative twist).\n"
            "- ALL content, definitions, and formulas MUST appear — never skip substance. "
            "Replace beginner analogies with real-world applications and 'why it works' reasoning.\n"
            "- Introduce edge cases and extensions where appropriate."
        )
```

---

## 10. Testing Strategy

### Unit Tests (pytest, `backend/tests/`)

| Test ID | Component | Scenario |
|---------|-----------|----------|
| `test_build_cards_system_prompt_with_struggling_profile` | `prompts.py` | Profile with STRUGGLING comprehension → SUPPORT MODE block present; "age-8" vocabulary instruction present |
| `test_build_cards_system_prompt_with_fast_strong_profile` | `prompts.py` | FAST+STRONG profile → ACCELERATE block present; "ALL content MUST appear" present; "Skip introductory analogies" absent |
| `test_build_cards_system_prompt_with_bored_profile` | `prompts.py` | BORED engagement → ENGAGEMENT BOOST block present |
| `test_build_cards_system_prompt_with_worsening_trend` | `prompts.py` | `history["trend_direction"] == "WORSENING"` → CONFIDENCE BUILDING block present |
| `test_build_cards_system_prompt_with_weak_concept` | `prompts.py` | `history["is_known_weak_concept"] = True, failed_concept_attempts=3` → WEAK CONCEPT block with "3 time(s)" present |
| `test_build_cards_system_prompt_no_profile` | `prompts.py` | `learning_profile=None` → no profile block; prompt identical to pre-upgrade |
| `test_build_cards_user_prompt_with_wrong_option_pattern` | `prompts.py` | `wrong_option_pattern=2` → MISCONCEPTION ALERT block contains "option index 2" |
| `test_build_cards_user_prompt_no_pattern` | `prompts.py` | `wrong_option_pattern=None` → no MISCONCEPTION ALERT block |
| `test_build_socratic_prompt_with_session_stats_high_error` | `prompts.py` | `error_rate=0.5` → "at least 5 questions" instruction present |
| `test_build_socratic_prompt_with_session_stats_no_errors` | `prompts.py` | `error_rate=0.0, total_hints=0` → "3 questions minimum" + "WHY not WHAT" present |
| `test_build_socratic_prompt_no_stats` | `prompts.py` | `session_card_stats=None` → no WHAT YOU KNOW block |
| `test_adaptive_prompt_builder_fast_strong_wording` | `adaptive/prompt_builder.py` | FAST+STRONG → "ALL content MUST appear" present; "Skip introductory analogies" absent |
| `test_xp_award_on_mastery` | `teaching_router.py` | `check_complete=True, mastered=True, score=85` → `xp_awarded=50` |
| `test_xp_award_bonus_on_mastery_high_score` | `teaching_router.py` | `score=92` → `xp_awarded=75` |
| `test_xp_consolation_on_completion_no_mastery` | `teaching_router.py` | `mastered=False` → `xp_awarded=10` |
| `test_xp_not_awarded_mid_session` | `teaching_router.py` | `check_complete=False` → `xp_awarded=None` |

### Integration Tests (FastAPI TestClient + PostgreSQL test DB)

| Test ID | Scenario |
|---------|----------|
| `test_generate_cards_uses_history_when_available` | Seed `card_interactions` for student; call `POST /sessions/{id}/cards`; verify response cards (check prompt log or mock LLM call validates profile was passed) |
| `test_generate_cards_graceful_on_empty_history` | New student (no interactions); call `POST /sessions/{id}/cards`; verify 200 response with cards |
| `test_socratic_check_includes_session_stats` | Seed `card_interactions` for session; call `POST /sessions/{id}/check`; verify first question returned |
| `test_respond_awards_xp_on_mastery` | Complete Socratic session to mastery; verify `students.xp` incremented in DB and `xp_awarded` in response |
| `test_respond_awards_consolation_on_no_mastery` | Complete session without mastery; verify `xp_awarded=10` and DB `xp` incremented by 10 |

### Frontend Tests (manual / Playwright)

| Test ID | Scenario |
|---------|----------|
| `FE-01` | On card advance, XPBurst animation fires (+5 XP) |
| `FE-02` | On correct MCQ answer, XPBurst fires (+10 XP), streak counter increments |
| `FE-03` | On mastery completion, XPBurst fires with mastery XP amount from response |
| `FE-04` | Lesson interest panel expands/collapses correctly; submitted interests pass through to session |
| `FE-05` | StudentForm interests field shows subtle hint text, not a prominent label |
| `FE-06` | AdaptiveModeIndicator updates after first card advance (mode from learning_profile_summary) |

---

## Key Decisions Requiring Stakeholder Input

1. **`quiz_score` proxy formula for initial card generation profile:** The formula `1.0 - min(avg_wrong_attempts * 0.15, 0.9)` is an approximation. Product/data team should validate this is a reasonable mapping of `avg_wrong_attempts` to quiz score for the initial profile.

2. **Inline vs background-task XP award:** DLD recommends inline for simplicity and transactional safety. Engineering team should confirm there are no latency concerns at expected load.

3. **Minimum dynamic question count (Socratic):** The block proposes 5 questions for `error_rate >= 0.4` and 3 for clean performance. Product should confirm these are educationally appropriate.

4. **XP_CARD_ADVANCE constant:** Frontend proposes 5 XP per card advance. This is not synced to the DB (it would require an endpoint call per card, which is expensive). The DB xp is updated only on mastery/consolation. The frontend Zustand XP will therefore diverge from DB xp within a session and be corrected on hydration. Product should confirm this is acceptable UX.

5. **`StudentForm.jsx` location:** The exact file path for the student creation form must be confirmed before the frontend task begins (it may be at `frontend/src/components/StudentForm.jsx` or similar — the developer should `Glob` for it).
