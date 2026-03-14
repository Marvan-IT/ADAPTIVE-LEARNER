# High-Level Design — Enhanced Adaptive Flashcard System

**Feature slug:** `adaptive-flashcard-system`
**Date:** 2026-03-10
**Author:** solution-architect agent
**Status:** Approved for implementation

---

## 1. Executive Summary

### Feature Name and Purpose
The Enhanced Adaptive Flashcard System is an upgrade to ADA's existing adaptive card-generation pipeline. It replaces the current discrete-label classification model with a continuous numeric blending system, adds cold-start calibration for new students, enforces full section coverage regardless of learner profile, and introduces text-based boredom detection with four engagement-recovery strategies.

### Business Problem Being Solved
The current system has four compounding weaknesses that degrade learning outcomes:

1. **Binary profile snapping.** A student who scores STRUGGLING on their first ever card immediately receives a STRUGGLING-profile lesson. There is no warm-up period, no prior history to temper the reading, and no numeric gradient between NORMAL and STRUGGLING. A student one point below the STRUGGLING threshold gets NORMAL delivery; a student one point above gets high-scaffolding STRUGGLING delivery. This cliff edge produces erratic card-sequence quality.

2. **No cold-start calibration.** `load_student_history()` returns `None`-baseline values for new students. `build_blended_analytics()` handles this with `cw=1.0, hw=0.0`, but the *classification thresholds* are fixed regardless of whether a student has 0 or 200 cards of history. A student who solves their very first card in 30 seconds is labelled FAST without any context.

3. **Content coverage gaps.** The FAST/STRONG profile produces 7 cards with `explanation_depth=LOW`. When the LLM is told to be brief and the concept source text has many sub-sections, it silently skips sub-sections. Students in FAST mode miss whole topic branches with no indication that content was omitted.

4. **No boredom engagement recovery.** The current system detects BORED engagement (time < 35% of expected, no wrong answers) but only adds `fun_level += 0.3` to the GenerationProfile. There is no detection of *stated* boredom in Socratic chat messages, no strategy selection based on what has worked before, and no tracking of engagement strategy effectiveness.

### Key Stakeholders
- Students (end users): improved lesson quality, fairer profiling
- Backend developers: new DB columns, new functions, new endpoint
- Frontend developers: boredom signal capture, section-complete reporting
- Comprehensive tester: expanded test coverage for all new functions

### Scope

**In scope:**
- Numeric state score computation replacing discrete STRUGGLING/NORMAL/FAST labels for blending purposes
- Cold-start weighting (80/20 for new students, graduating to 60/40 after 3+ sections)
- Full section coverage enforcement — all students receive all content; delivery style alone varies
- Concept-level tracking in LLM prompts (concept_index, concepts_remaining, images_used_this_section)
- Text-based boredom detection module (`boredom_detector.py`) scanning Socratic chat messages
- Four engagement strategies: GAMIFY, CHALLENGE, STORY, BREAK_SUGGESTION
- Strategy effectiveness tracking in `card_interactions` and `students` tables
- `POST /api/v2/sessions/{session_id}/section-complete` endpoint to persist section results
- DB schema additions (11 columns on `students`, 3 columns on `card_interactions`) via Alembic migration `005_add_adaptive_history_columns`

**Explicitly out of scope:**
- Changes to the spaced-repetition (SpacedReview) model
- Changes to the Socratic check scoring logic
- ChromaDB schema changes
- Frontend redesign of the card-learning view (visual layout unchanged)
- Multi-worker translation cache (deferred per CLAUDE.md)

---

## 2. Functional Requirements

### Core Capabilities

| ID | Priority | Requirement |
|----|----------|-------------|
| FR-01 | Must | Compute a numeric state score (0.0–4.0 scale) from speed and comprehension labels |
| FR-02 | Must | Blend the current session state score with the student's historical average using a configurable weight ratio |
| FR-03 | Must | Apply 80/20 current/history weighting for students with fewer than 3 completed sections; apply 60/40 after |
| FR-04 | Must | Ensure the LLM prompt receives all concept sub-sections regardless of profile; depth/pacing may vary |
| FR-05 | Must | Pass concept_index, concepts_remaining, and images_used_this_section in the LLM user prompt COVERAGE CONTEXT block |
| FR-06 | Must | Detect boredom signals in Socratic chat text (exact phrases and sentiment patterns) |
| FR-07 | Must | Select engagement strategy from [GAMIFY, CHALLENGE, STORY, BREAK_SUGGESTION] avoiding previously ineffective strategies |
| FR-08 | Must | Persist per-card engagement_signal, strategy_applied, strategy_effective in card_interactions |
| FR-09 | Must | Persist per-student effective_engagement, ineffective_engagement, avg_state_score in students table via section-complete endpoint |
| FR-10 | Must | Expose `POST /api/v2/sessions/{session_id}/section-complete` endpoint to record section-level outcomes |
| FR-11 | Should | Detect autopilot patterns (repeated identical short answers in Socratic chat) as a secondary boredom signal |
| FR-12 | Should | All 93 existing adaptive engine tests must remain green after this feature is merged |

### User Stories

1. **As a new student** completing my first section, I want the system to use my actual performance rather than blend it with a non-existent baseline, so that my first lesson adapts correctly to what I actually demonstrated.

2. **As a fast learner** who finishes cards quickly, I want to receive all topic sub-sections covered in the concept — just presented more concisely — so I do not have silent knowledge gaps.

3. **As a student who types "this is boring" in the Socratic chat**, I want the system to detect that signal and apply an engagement strategy (e.g., GAMIFY or CHALLENGE) in the next card, so the lesson regains my attention.

4. **As a student who has tried GAMIFY strategies before without improvement**, I want the system to avoid repeating those strategies and try a different approach, so the engagement recovery actually works.

5. **As a backend developer**, I want a deterministic `compute_numeric_state_score()` function that maps (speed, comprehension) pairs to floats so I can write simple unit tests without mocking.

---

## 3. Non-Functional Requirements

| Category | Requirement | Measurable Target |
|----------|-------------|-------------------|
| Performance | Section-complete endpoint response time | p95 < 200 ms under normal DB load |
| Performance | Boredom detection scan of a 200-word message | < 5 ms (pure Python, no I/O) |
| Scalability | Numeric blending added to existing card-generation path | Zero additional LLM calls; DB query count unchanged |
| Availability | No new required external services | All new logic is in-process Python |
| Reliability | Boredom detector failure must not block card generation | Must degrade gracefully; detection errors logged, not raised |
| Maintainability | All new constants in `config.py` | No magic numbers in business logic files |
| Observability | All new functions emit structured log lines | `logger.info()` at entry + result for all public functions |
| Security | New endpoint requires same `X-API-Key` auth as all v2 endpoints | Confirmed by existing `verify_api_key` dependency |
| Test coverage | New pure functions: 100% unit test coverage | All branches covered; no integration test required for pure functions |
| Test coverage | DB-touching functions: integration test with test DB | Section-complete endpoint tested with `AsyncSession` fixture |

---

## 4. System Context Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Browser (React 19 SPA)                                                     │
│                                                                             │
│  SocraticChat.jsx ──────── detects boredom text ───────────────────────────┼──┐
│  CardLearningView.jsx ──── card signals (time, wrong, idle) ───────────────┼──┤
│  SessionContext.jsx ─────── section-complete trigger ──────────────────────┼──┤
│  sessions.js (Axios) ────── all HTTP calls ────────────────────────────────┼──┤
└──────────────────────────────────────────────────────────────────────────────┤ │
                                                                              │ │
    ┌─────────────── HTTP (JSON, X-API-Key header) ────────────────────────┐  │ │
    │                                                                      │  │ │
    ▼                                                                      │  ▼ ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  FastAPI (port 8889)                                                                │
│                                                                                     │
│  teaching_router.py                                                                 │
│    POST /sessions/{id}/complete-card   ──► adaptive_engine.generate_next_card()    │
│    POST /sessions/{id}/section-complete ──► TeachingService._persist_section()     │
│    POST /sessions/{id}/chat            ──► TeachingService.socratic_exchange()     │
│                                                                                     │
│  adaptive/                                                                          │
│    adaptive_engine.py                                                               │
│      build_blended_analytics()  ──► ENHANCED: numeric blending + cold-start        │
│      load_student_history()     ──► ENHANCED: reads new history columns             │
│    profile_builder.py           ──► UNCHANGED (still produces labels)               │
│    prompt_builder.py            ──► ENHANCED: STUDENT STATE + COVERAGE CONTEXT     │
│    boredom_detector.py          ──► NEW: text-based signal detection                │
│                                                                                     │
│  api/                                                                               │
│    teaching_service.py          ──► ENHANCED: concept tracking, strategy inject    │
│    teaching_schemas.py          ──► ENHANCED: SectionCompleteRequest/Response      │
│                                                                                     │
└──────────────────────────────┬──────────────────────────────────────────────────────┘
                               │
           ┌───────────────────┼────────────────────┐
           │                   │                    │
           ▼                   ▼                    ▼
  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
  │  PostgreSQL 15  │  │  ChromaDB 0.5  │  │  OpenAI API    │
  │  (students,     │  │  (concept      │  │  (gpt-4o,      │
  │  card_inter-    │  │   embeddings)  │  │  gpt-4o-mini)  │
  │  actions)       │  └────────────────┘  └────────────────┘
  └────────────────┘
```

**Data flow narrative:**

1. Frontend sends card behavioral signals to `POST /sessions/{id}/complete-card`.
2. `adaptive_engine.generate_next_card()` calls `load_student_history()` — now reads `avg_state_score`, `section_count`, `effective_engagement`, `ineffective_engagement` from the `students` row.
3. `build_blended_analytics()` computes the numeric blended score and maps it back to a profile label.
4. `prompt_builder.build_next_card_prompt()` injects STUDENT STATE (numeric score, history avg) and COVERAGE CONTEXT (concept_index, concepts_remaining) blocks.
5. LLM generates a card. Card returned to frontend.
6. Separately, `SocraticChat.jsx` monitors user-typed messages. On boredom detection, it adds `engagement_signal` to the next `complete-card` request.
7. When the last card in a section is completed, `SessionContext.jsx` fires `POST /sessions/{id}/section-complete`. Backend updates `students.avg_state_score`, `students.section_count`, `students.effective_engagement`, `students.ineffective_engagement`.

---

## 5. Architectural Style and Patterns

**Selected style: Layered in-process module augmentation with event-driven section boundary signaling**

### Justification

The existing adaptive engine is already a clean layered architecture:
- Input signals (frontend) → Analytics blending → Profile classification → Generation profile → Prompt construction → LLM → Card output

This feature adds processing to several of those layers without changing the layer boundaries. All new behavior is additive:
- Numeric scoring is a new pure function added to the blending layer
- Cold-start weighting changes a constant in `build_blended_analytics()`
- Coverage context is a new block added to the prompt builder
- Boredom detection is a new module that wraps the Socratic chat exchange
- Section-complete is a new endpoint that writes to the existing DB model

### Pattern: Pure function + side-effect isolation

Following the existing codebase convention (visible in `profile_builder.py`, `generation_profile.py`, `prompt_builder.py`), all classification and scoring functions are pure (no I/O, no side effects). Only the DB-touching functions (`load_student_history()`, `_persist_section_complete()`) are async and side-effectful. This keeps unit testing trivial.

### Pattern: Graceful degradation on detection failures

`boredom_detector.py` functions return `None` on any unexpected input. The calling code treats `None` as "no signal detected" and proceeds without modification. This prevents a detection bug from crashing card generation.

### Alternatives considered

| Alternative | Rejected reason |
|-------------|-----------------|
| Separate microservice for boredom detection | Over-engineering — adds network hop for a regex+keyword scan |
| PostgreSQL `UPDATE RETURNING` for section-complete | Already using SQLAlchemy async ORM; direct `UPDATE` via ORM is consistent with existing patterns |
| ML-based engagement classification | Requires training data the platform does not yet have; text-keyword approach is sufficient for MVP |
| Replacing label-based profiling entirely with numeric scoring | Too large a blast radius — 93 existing tests are written against string labels; labels are embedded in LLM prompts |

---

## 6. Technology Stack

All additions work within the existing stack. No new dependencies are required except for confirming `json-repair>=0.30.0` is already in `requirements.txt` (it is, per CLAUDE.md fix log).

| Concern | Technology | Version | Notes |
|---------|------------|---------|-------|
| Backend framework | FastAPI | 0.128+ | Unchanged |
| Database | PostgreSQL 15 + SQLAlchemy 2.0 async | — | New columns added via Alembic |
| Boredom detection | Python stdlib `re` + string ops | — | No new library required |
| Config constants | `backend/src/config.py` | — | 8 new constants added |
| Schema validation | Pydantic v2 | 2.0+ | 2 new schema classes |
| Frontend state | React Context (SessionContext) | React 19 | 1 new action added |
| Frontend HTTP | Axios (sessions.js) | 1.13 | 1 new function added |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-001: Numeric scoring on top of existing labels, not replacement

**Decision:** Add a `compute_numeric_state_score()` function that maps (speed, comprehension) pairs to a float, but keep the string labels as the primary interface for LLM prompts and GenerationProfile lookup.

**Options considered:**
- Replace labels with a single float throughout
- Keep labels, add numeric score as a parallel value used only for blending

**Chosen:** Keep labels, add numeric score for blending.

**Rationale:** The 93 existing tests are written against string labels. The 9-cell GenerationProfile lookup table (`generation_profile.py`) is indexed by `(speed, comprehension)` string tuples. Replacing these would require rewriting all tests and all prompt builder mode blocks. The numeric score is needed only for the blending weight decision and for the STUDENT STATE prompt block — both of which are new additions, not refactors of existing logic.

**Trade-off:** Two parallel representations (label + score) must be kept consistent. This is low risk because `compute_numeric_state_score()` is a pure deterministic function of the two label inputs.

---

### ADR-002: Cold-start threshold at 3 completed sections (not cards)

**Decision:** Measure cold-start maturity by `students.section_count` (sections completed), not by `total_cards_completed` (individual cards).

**Options considered:**
- Use `total_cards_completed >= 5` (already used for history blending in `build_blended_analytics`)
- Use `section_count >= 3` (sections completed)

**Chosen:** `section_count >= 3`.

**Rationale:** A student may complete 5 cards inside a single section and still have only one data point about their cross-section learning pattern. Section boundaries are the natural unit of learning progress in ADA (each section corresponds to one OpenStax textbook section). Three sections gives approximately 27–36 cards of history depending on profile, which is meaningful context. The `section_count` column is already planned in the DB schema (added in migration `005`).

---

### ADR-003: Four fixed engagement strategies with effectiveness memory

**Decision:** Use four named strategies [GAMIFY, CHALLENGE, STORY, BREAK_SUGGESTION] and persist per-student `effective_engagement` / `ineffective_engagement` lists in the `students` table.

**Options considered:**
- Dynamically generate engagement approaches via LLM
- Fixed strategies with random selection
- Fixed strategies with effectiveness memory

**Chosen:** Fixed strategies with effectiveness memory.

**Rationale:** LLM-generated strategies are unpredictable and hard to test. Random selection means the same failed strategy can be repeated. Four named strategies are sufficient for MVP, and the effectiveness memory allows the selection function to learn from the specific student's history without adding a separate ML model. The memory is stored as JSONB arrays in the `students` table, which is already the established pattern for student preference storage.

---

### ADR-004: Section-complete is a dedicated endpoint, not piggybacked on complete-card

**Decision:** Add `POST /sessions/{id}/section-complete` as a separate endpoint rather than triggering section-level persistence inside the last `complete-card` call.

**Options considered:**
- Detect "last card in section" server-side and persist automatically
- Have the frontend explicitly call a section-complete endpoint

**Chosen:** Dedicated frontend-triggered endpoint.

**Rationale:** The server does not reliably know when a section ends because cards can be added dynamically via the adaptive loop. Only the frontend (SessionContext) knows when the student has advanced past the last available card in a section. The explicit call is more reliable and matches the existing pattern of client-driven phase transitions (e.g., `POST /sessions/{id}/start-check`).

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Numeric score introduces regression in profiling quality | Medium | High | Keep labels as primary interface; numeric score only affects blending weight selection, not GenerationProfile lookup |
| Cold-start 80/20 weighting over-amplifies a single bad card performance | Medium | Medium | Cold-start is only for < 3 sections; after 3 sections it graduates to 60/40; the ACUTE deviation check (90/10) is still active |
| Boredom detection false-positive on math problem text | Low | Low | Detector uses explicit phrases ("this is boring", "I already know this") and rate-limits: one strategy per session, not per message |
| Section-complete endpoint called multiple times (duplicate writes) | Medium | Medium | Use `UPDATE ... WHERE section_count = :current_count` optimistic lock; duplicate calls are idempotent because count only increments by 1 |
| LLM ignores COVERAGE CONTEXT block and still skips sections | Medium | High | Add COVERAGE CONTEXT as mandatory numbered checklist in user prompt (same approach as the CARD SEQUENCE ORDER fix in CLAUDE.md) |
| Alembic migration `005` fails on production due to column default mismatch | Low | Critical | devops-engineer to test migration on a clone of production schema before merging; reviewed by solution-architect |
| Strategy effectiveness tracking stores incorrect `strategy_effective` values | Medium | Low | Frontend sends `strategy_effective` based on card completion within 10 minutes of strategy application; server-side validation clamps to boolean |

---

## Key Decisions Requiring Stakeholder Input

1. **Cold-start threshold:** The design uses `section_count >= 3` as the boundary. Should this be `>= 5` to allow more calibration time? Product should validate against pedagogical evidence.

2. **Boredom recovery rate-limiting:** Currently, once a boredom signal is detected in a session, the strategy is applied to the *next generated card* only. Should the strategy persist for the entire remaining section (e.g., all subsequent cards in that session get GAMIFY treatment)?

3. **BREAK_SUGGESTION behavior:** When `select_engagement_strategy()` returns `BREAK_SUGGESTION`, the current design proposes the frontend display a "Take a 5-minute break?" modal. Does the product team want this UX interruption, or should it be a softer in-card suggestion?

4. **avg_state_score scope:** The current design updates `avg_state_score` on every section-complete call using an exponential moving average (alpha = 0.3). Should this also decay over time (e.g., scores older than 30 days weighted less)?
