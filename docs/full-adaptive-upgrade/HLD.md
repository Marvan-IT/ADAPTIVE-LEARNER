# Full Adaptive Upgrade — High-Level Design

**Feature slug:** `full-adaptive-upgrade`
**Date:** 2026-03-02
**Status:** Approved for implementation

---

## 1. Executive Summary

### Feature / System Name
Full Adaptive Learning Upgrade — closing the loop between stored student history and every live LLM call.

### Business Problem Being Solved
ADA currently behaves like a smart textbook: it generates contextually accurate explanations and cards but generates them the same way for every student. A student who has failed this concept three times receives the same narrative as a student who excels. A student who consistently selects the same wrong answer option gets no targeted misconception correction. The Socratic check is fixed regardless of whether the student breezed through cards or struggled on every one.

In its current state the platform cannot deliver on its core promise — to teach better than a textbook or classroom — because it ignores the large corpus of behavioral data it already collects.

This upgrade wires every stored behavioral signal into every LLM call and closes four critical loops:

| Gap | Current State | After Upgrade |
|-----|--------------|---------------|
| Initial card generation | Identical for all students | Personalised via `LearningProfile` built from `load_student_history()` |
| Card prompt vocabulary / depth | One-size-fits-all | Mode-specific instructions (STRUGGLING, FAST/STRONG, BORED, WORSENING, WEAK CONCEPT) |
| Misconception correction | None | `load_wrong_option_pattern()` injected as `MISCONCEPTION ALERT` block |
| Socratic check difficulty | Fixed 3-question minimum, no awareness of card performance | Queries `CardInteraction` records for the session; adjusts minimum questions and question depth dynamically |
| Mastery XP award | None in teaching loop | 50 XP on mastery, 25 bonus if score >= 90, 10 consolation; synced to DB atomically |
| Frontend game HUD | Components built but not mounted in AppShell | `XPBurst`, `StreakMeter`, `LevelBadge`, `AdaptiveModeIndicator` actively driven by store events |
| Frontend mode feedback | `adaptiveStore.updateMode()` called only after `ADAPTIVE_CARD_LOADED` | Also called when cards are first loaded from initial generation |
| Lesson interest customisation | Available via URL params only | Collapsible in-lesson panel on `LearningPage` |
| Student interests UI | Prominent mandatory-feeling field | Visually optional with hint text in `StudentForm` |

### Key Stakeholders
- Product: ADA adaptive learning team
- Engineering: backend-developer, frontend-developer, comprehensive-tester
- Design: UX — no new pages; touches `LearningPage`, `StudentForm`, `AppShell`

### Scope

**Included:**
- `backend/src/api/teaching_service.py` — `generate_cards()` and `begin_socratic_check()` adaptive wiring
- `backend/src/api/prompts.py` — `build_cards_system_prompt()`, `build_cards_user_prompt()`, `build_socratic_system_prompt()` new parameters and profile injection blocks
- `backend/src/adaptive/prompt_builder.py` — FAST/STRONG mode wording fix (line ~213)
- `backend/src/api/teaching_router.py` — XP award after mastery in `respond_to_check`
- `backend/src/api/teaching_schemas.py` — `xp_awarded: int | None` field on `SocraticResponse`
- `frontend/src/components/layout/AppShell.jsx` — `XPBurst` mount (the other three components are already mounted)
- `frontend/src/context/SessionContext.jsx` — `updateMode` and `awardXP` wiring after `ADAPTIVE_CARD_LOADED` and mastery
- `frontend/src/components/learning/CardLearningView.jsx` — `awardXP(10)` on correct MCQ (already present; verify `recordAnswer` path for wrong MCQ)
- `frontend/src/pages/LearningPage.jsx` — optional "Customize this lesson" collapsible panel
- `frontend/src/components/` `StudentForm.jsx` — make interests field visually optional

**Explicitly Excluded:**
- New database tables or columns (none required — all data exists in `CardInteraction`, `Student`)
- New Alembic migrations (none required)
- New API endpoints (none required — `PATCH /api/v2/students/{id}/progress` already exists)
- Changes to the adaptive engine's per-card next-card loop (`complete-card` endpoint) — that path already calls `load_student_history()`; this upgrade targets the initial `generate_cards()` path and the Socratic check
- Changes to the v3 adaptive lesson batch endpoint
- i18n string additions for the interests panel (English only for now; i18n keys added as placeholders)

---

## 2. Functional Requirements

### Core Capabilities

**FR-1 (P1):** `generate_cards()` must load the student's global interaction history via `load_student_history()` and, when `total_cards_completed >= 3`, build a `LearningProfile` and pass it as `learning_profile` to `build_cards_system_prompt()`.

**FR-2 (P1):** `generate_cards()` must call `load_wrong_option_pattern()` and pass the result as `wrong_option_pattern` to `build_cards_user_prompt()`.

**FR-3 (P1):** `build_cards_system_prompt()` must accept `learning_profile=None` and `history=None` parameters and inject a `STUDENT PROFILE SUMMARY` block with mode-specific generation instructions when a profile is present.

**FR-4 (P1):** `build_cards_user_prompt()` must accept `wrong_option_pattern=None` and inject a `MISCONCEPTION ALERT` block when the pattern is not `None`.

**FR-5 (P1):** `build_socratic_system_prompt()` must accept `session_card_stats=None` and inject a `WHAT YOU KNOW ABOUT THIS STUDENT` block with combined global + session interpretation and dynamic minimum-questions logic.

**FR-6 (P1):** `begin_socratic_check()` must query `CardInteraction` records for `session.id` (total cards, total wrong attempts, total hints used) and pass the resulting dict as `session_card_stats`.

**FR-7 (P1):** `build_cards_system_prompt()` mode-specific blocks must implement the following semantics:
- **STRUGGLING or SLOW:** age-8 vocabulary, worked examples first, analogies before formulas
- **FAST + STRONG:** retain ALL definitions and formulas, replace beginner analogies with real-world applications ("why it works" reasoning), add challenging applications — never skip substance
- **BORED:** puzzle/game hook on every card, fun_element non-null, quiz questions as game-style challenges
- **WORSENING trend:** confidence building tone, extra encouragement, no difficulty increase
- **Known weak concept:** completely different narrative frame, patient scaffolding

**FR-8 (P1):** `adaptive/prompt_builder.py` FAST/STRONG mode block (~line 213) must be changed from "Skip introductory analogies" to "ALL content, definitions, and formulas MUST appear — never skip substance. Replace beginner analogies with real-world applications."

**FR-9 (P1):** When `handle_student_response()` returns `check_complete=True` with `mastered=True`, the router must call `PATCH /api/v2/students/{id}/progress` with `xp_delta=50` (or 75 if `score >= 90`) and increment streak. If `mastered=False`, call with `xp_delta=10`.

**FR-10 (P1):** `SocraticResponse` schema must include `xp_awarded: int | None = None` field, populated by the router on completion.

**FR-11 (P2):** `SessionContext.jsx` after `ADAPTIVE_CARD_LOADED` must call `useAdaptiveStore.getState().updateMode(res.data.learning_profile_summary)`.

**FR-12 (P2):** `SessionContext.jsx` after `ADAPTIVE_CARD_LOADED` must call `useAdaptiveStore.getState().awardXP(5)` (engagement XP per card advance).

**FR-13 (P2):** `SessionContext.jsx` after receiving `check_complete=True` with `mastered=True` must call `useAdaptiveStore.getState().awardXP(xp_awarded)` and update the streak counter.

**FR-14 (P2):** `AppShell.jsx` must mount `XPBurst` component (the other three components — `LevelBadge`, `StreakMeter`, `AdaptiveModeIndicator` — are already mounted and wired).

**FR-15 (P3):** `LearningPage.jsx` must render a collapsible "Customize this lesson" panel before cards load, with a free-text or tag-based interests input that is passed as `lessonInterests` to `startLesson()`.

**FR-16 (P3):** `StudentForm.jsx` must change the interests field label from a prominent heading to subtle hint text to communicate that it is optional.

---

## 3. Non-Functional Requirements

### Performance
- `generate_cards()` latency increase from adding `load_student_history()` + `load_wrong_option_pattern()` must be under 80 ms (both are single indexed DB queries; `load_student_history()` already runs in `begin_socratic_check()` so we have a measured baseline)
- Both DB calls run concurrently via `asyncio.gather()` — sequential would add ~160 ms; parallel keeps the addition under 60 ms in practice
- No change to LLM call count per session (still one LLM call for the batch card generation)
- Socratic session latency: querying `CardInteraction` for session records adds one lightweight indexed query (<10 ms)

### Scalability
- No new tables; all queries hit existing indices (`ix_card_interactions_student_concept`, `ix_card_interactions_session_id`)
- `load_student_history()` already caps at 200 records

### Availability
- `load_wrong_option_pattern()` already uses a `try/except` that returns `None` on failure — card generation proceeds without pattern injection, never blocking
- History load failure: if `load_student_history()` raises, `generate_cards()` must catch and continue with `learning_profile=None` (graceful degradation — student gets the same generic experience as today, not an error)
- Socratic stats query failure: if the `CardInteraction` query fails, `begin_socratic_check()` continues with `session_card_stats=None` (graceful degradation)
- XP award after mastery: fire-and-forget atomic DB update; failure silently logged, session result still returned

### Security
- No new endpoints, no new auth surface
- `learning_profile` and `wrong_option_pattern` are internal to the backend LLM call; they are not exposed in API responses (except `learning_profile_summary` on the per-card endpoint, which already exists)

### Maintainability
- All new prompt injection blocks are plain Python string sections inside existing prompt builder functions — no new files
- Mode-specific blocks follow the existing pattern already used in `adaptive/prompt_builder.py`
- All new config constants added to `config.py`
- No magic numbers in service or router files

### Observability
- `generate_cards()` must emit a structured log line: `[cards-adaptive] student_id=... concept_id=... history_cards=N profile=SPEED/COMPREHENSION/ENGAGEMENT wrong_option_pattern=N|None`
- `begin_socratic_check()` must emit: `[socratic-adaptive] session_id=... session_cards=N session_wrong=N session_hints=N`
- XP award must emit: `[xp-awarded] student_id=... xp=N mastered=True|False score=N`

---

## 4. System Context Diagram

```
Student (Browser)
    |
    | HTTPS
    v
Frontend SPA (React 19 + Vite 7)
    ├── LearningPage.jsx          ← new: lesson interests collapsible panel
    ├── CardLearningView.jsx      ← existing: XP + recordAnswer calls (verify)
    ├── AppShell.jsx              ← add XPBurst mount
    ├── SessionContext.jsx        ← new: updateMode + awardXP wiring
    └── adaptiveStore.js (Zustand) ← existing: awardXP, recordAnswer, updateMode
         |
         | Axios (VITE_API_BASE_URL)
         v
Backend API (FastAPI + Uvicorn)
    ├── teaching_router.py        ← POST /sessions/{id}/respond: XP award
    └── teaching_service.py
         ├── generate_cards()     ← loads history + profile + wrong_option_pattern
         └── begin_socratic_check() ← loads session CardInteraction stats
              |
              ├── prompts.py      ← build_cards_system_prompt() (profile injection)
              |                      build_cards_user_prompt() (misconception block)
              |                      build_socratic_system_prompt() (session stats block)
              |
              ├── adaptive_engine.py  (load_student_history, load_wrong_option_pattern)
              ├── profile_builder.py  (build_learning_profile) — EXISTING, UNCHANGED
              |
              └── PostgreSQL 15
                   ├── card_interactions   ← source of history + session stats
                   └── students            ← xp, streak columns (atomic UPDATE)

External:
    └── OpenAI API (gpt-4o for batch cards, gpt-4o-mini for Socratic)
```

---

## 5. Architectural Style and Patterns

### Selected Style
**Layered (Router → Service → Prompt Builder → LLM)** with **Pure-Function Side Enrichment**.

The architecture remains the established layered pattern of the codebase. The upgrade adds enrichment at the service layer boundary: before the prompt is assembled, the service fetches behavioral context and passes it to pure prompt-builder functions. No new layers are introduced.

### Key Pattern: Graceful Degradation at Every Seam
Every new DB call in the service layer is wrapped in a `try/except` (or uses the existing graceful-fail pattern in `load_wrong_option_pattern()`). If the enrichment data is unavailable, the system falls back to the pre-upgrade behaviour. This keeps the critical path (card generation returning cards) blast-radius-free.

### Justification vs Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| New endpoint that pre-fetches profile and passes it in the request | Adds client complexity; client already has no knowledge of profiles; server side is the right place |
| Cache profile in Redis between sessions | Premature optimisation; profile builds in <5 ms from indexed queries; adds infrastructure dependency |
| Separate adaptive-cards endpoint (v3 style) | Breaks backward compatibility with existing client; the upgrade is a transparent quality improvement to existing endpoints |
| Build profile in a background task | Async DB calls are fast enough (<80 ms total); background tasks add complexity with no latency benefit at current load |

---

## 6. Technology Stack

All components use the existing confirmed stack. No new dependencies required.

| Concern | Technology | Notes |
|---------|-----------|-------|
| Backend framework | FastAPI 0.128+ async | No change |
| LLM client | AsyncOpenAI (gpt-4o / gpt-4o-mini) | No change — same call sites |
| Database | PostgreSQL 15, SQLAlchemy 2.0 async | Queries hit existing `card_interactions` and `students` tables |
| Adaptive utilities | `adaptive_engine.py`, `profile_builder.py` | Reused unchanged |
| Frontend state | Zustand 5.x (`adaptiveStore.js`) | Already installed; `awardXP`, `updateMode` already exist |
| Frontend game components | All 5 in `frontend/src/components/game/` | Already built; `XPBurst` just needs mounting in `AppShell` |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-1: History Load Threshold = 3 Cards (for initial generation)

**Decision:** Build `LearningProfile` for initial card generation when `total_cards_completed >= 3`.

**Options considered:**
- `>= 1`: Too sparse; single-card history is noisy (the student may have just registered)
- `>= 3`: Sufficient signal for meaningful speed/comprehension/engagement classification; low enough that returning students see personalisation quickly
- `>= 5`: Already used in `begin_socratic_check()` (global profile); conservative but delays personalisation

**Chosen:** 3 — lower threshold is acceptable for initial generation because the profile influences tone/vocabulary (low harm if slightly wrong) rather than prerequisite routing (high harm if wrong).

**Rationale:** The existing threshold of 5 in `begin_socratic_check()` remains unchanged — the Socratic check uses a more sensitive classification that deserves a higher confidence bar.

### ADR-2: Run History and Wrong-Option Loads Concurrently

**Decision:** Use `asyncio.gather(load_student_history(...), load_wrong_option_pattern(...))` in `generate_cards()`.

**Rationale:** Both queries are independent. Sequential adds ~80–120 ms (two round trips); parallel adds ~40–60 ms (one round trip). No correctness dependency between the two results.

### ADR-3: Profile Injection as Prompt String Block (Not Structured Object)

**Decision:** Pass `learning_profile` as a Python object to prompt functions; the functions render it as a human-readable block appended to the system prompt string.

**Rationale:** The LLM interprets natural-language instructions reliably. A structured JSON block in the system prompt would require the LLM to parse its own context, which is less reliable. This matches the pattern already used in `build_socratic_system_prompt()` for `socratic_profile`.

### ADR-4: XP Award in the Router, Not the Service

**Decision:** The `PATCH /students/{id}/progress` call happens in `teaching_router.py`'s `respond_to_check` handler, not inside `handle_student_response()` in the service.

**Rationale:** `handle_student_response()` is a pure service method that returns a result dict; mixing HTTP client calls into the service would couple it to the API layer. The router already has access to `student_id` and the result dict, and the existing `update_student_progress` endpoint is already atomic. The call is fire-and-forget (async background), so it does not block the response.

### ADR-5: XP Award Amounts as Config Constants

**Decision:** Add `XP_MASTERY = 50`, `XP_MASTERY_BONUS = 25` (applied when `score >= 90`), `XP_CONSOLATION = 10`, `XP_CARD_ADVANCE = 5` to `config.py`.

**Rationale:** All threshold values must live in `config.py` per project convention. Hardcoding them in the router or context would violate the coding standard.

### ADR-6: Session Card Stats Passed as a Plain Dict

**Decision:** The session stats computed in `begin_socratic_check()` are passed as `session_card_stats: dict | None` to `build_socratic_system_prompt()`.

**Rationale:** Creating a Pydantic schema for a three-field intermediate object adds unnecessary ceremony. A typed dict with documented keys (`total_cards`, `total_wrong`, `total_hints`, `error_rate`) is readable and consistent with how `history` is already passed through the same function.

---

## 8. Risks and Mitigations

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Prompt injection via aggressive profile blocks inflating token count above `max_tokens=8000` for batch card generation | Medium | Low | Profile block is bounded at ~400 tokens; misconception block at ~80 tokens; total addition is ~480 tokens; current prompt is well under the 8000 token limit |
| `load_student_history()` raising on DB error blocks card generation | High | Low | Wrap in `try/except`; fall back to `learning_profile=None` |
| FAST/STRONG mode skips important content if wording is ambiguous | High | Medium | ADR addresses this directly: wording explicitly states "ALL content MUST appear" — developer must implement exactly as specified |
| XP award fails silently and student sees no XP increment in frontend | Low | Low | Frontend XP is driven by `adaptiveStore.awardXP()` called locally on the client before the DB sync; DB sync failure does not affect client-side display; mismatch is corrected on next `GET /students/{id}` (hydration) |
| Socratic session stats query adds latency to check start | Low | Low | Single indexed query (`CardInteraction` by `session_id`); <10 ms; `begin_socratic_check()` already makes two async calls |
| `LearningPage` interest panel creates confusion if concept-level interests conflict with stored interests | Low | Low | Panel is labelled clearly as "for this lesson only"; `startLesson()` already supports `lessonInterests` override |
| `StudentForm` de-emphasising interests causes students to skip them | Low | Medium | Intentional product decision; interests are optional — the profile-based adaptation covers the main personalisation need |

---

## Key Decisions Requiring Stakeholder Input

1. **XP amounts:** The values 50 (mastery), 25 (score >= 90 bonus), 10 (consolation), 5 (per card advance), and 10 (per correct MCQ in `CardLearningView`) are proposed. Product should confirm or adjust these amounts before implementation.

2. **Mastery bonus score threshold:** Currently proposed at `score >= 90`. Should this match the Socratic check scale (0–100) or be normalised differently?

3. **Minimum history threshold for initial generation:** Proposed at `>= 3` total cards. Product should confirm this is acceptable (new students with 0–2 cards get generic content, which is the current behaviour).

4. **Lesson interest panel placement:** Proposed as a collapsible panel that appears only when the lesson is in `IDLE` state (before cards are loaded). Should it be permanent or dismissed after first interaction?

5. **`StudentForm` interests field:** Confirming that making it visually optional is acceptable and will not reduce data quality for personalisation.
