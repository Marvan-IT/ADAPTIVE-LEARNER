# High-Level Design — Adaptive Real Tutor
**Feature slug:** `adaptive-real-tutor`
**Version:** 1.0
**Date:** 2026-02-27
**Author:** Solution Architect Agent

---
## 1. Executive Summary

### Feature Name and Purpose
The **Adaptive Real Tutor** transforms ADA's card-based learning loop from a static, pre-generated batch into a live, per-card adaptive experience. Every card a student sees is generated (or selected) on the fly, informed by what happened on the card they just completed — measured with sub-second precision through behavioral signals such as time on card, wrong attempts, hints used, and idle triggers.

### Business Problem Being Solved
Currently, the entire lesson (7–12 cards) is generated in a single LLM call at session start. The cards are identical for every student regardless of how they actually perform mid-session. A student who is confused on card 3 still receives the same card 4 that a confident student receives. There is no cross-session memory: the system never knows that this student historically takes twice as long on fraction problems. Mastered concepts are never surfaced for spaced review.

The result is a learning experience that is only as adaptive as its initial profile — it never course-corrects during the lesson, and it forgets everything between sessions.

### Key Stakeholders
| Stakeholder | Role |
|---|---|
| Students | Primary users of the adaptive card flow |
| Backend Developer Agent | Implements engine and endpoints |
| Frontend Developer Agent | Implements signal collection and dynamic card replacement |
| Comprehensive Tester Agent | Validates blending algorithm and API contracts |
| DevOps Engineer Agent | Migration already applied; monitors new endpoint performance |

### Scope

**Included:**
- Per-card behavioral signal collection in the frontend
- Cross-session personal baseline computation from `card_interactions` table
- Deviation-aware blending algorithm (current vs. historical signals)
- Real-time `generate_next_card()` function — one LLM call per card transition
- Motivational micro-feedback sentence (one per card, included in the LLM response)
- Adaptive Socratic check — question complexity matched to the blended LearningProfile
- Spaced repetition scheduling (Ebbinghaus +1/+3/+7/+14/+30 day intervals)
- `POST /api/v2/sessions/{session_id}/complete-card` endpoint
- `GET /api/v2/students/{student_id}/review-due` endpoint
- ConceptMap review-due badges in the frontend
- Feature flag `ADAPTIVE_CARDS_ENABLED` in `config.py`
- i18n strings for motivational feedback and review prompts (13 languages)

**Explicitly excluded:**
- Changing the existing `POST /api/v3/adaptive/lesson` endpoint (first card generation is unchanged)
- Alembic migration (already applied — migration `e3c02cf4c22e` is live)
- SM-2 ease-factor tracking (v2 milestone — Ebbinghaus fixed intervals are sufficient for v1)
- Multi-book spaced review cross-referencing
- Push notifications for due reviews
- Any change to the Socratic chat (CHECKING phase) conversation history format

---

## 2. Functional Requirements

### Core Capabilities

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | After a student completes a card, record the behavioral signals (time, wrong attempts, wrong option, hints, idle triggers) to `card_interactions` | P0 |
| FR-02 | Compute a per-student personal baseline (average `time_on_card_sec`, `wrong_attempts`, `hints_used`) from all historical `card_interactions` | P0 |
| FR-03 | Blend current-card signals with historical baseline using the deviation-aware algorithm | P0 |
| FR-04 | Classify a new LearningProfile from the blended signals | P0 |
| FR-05 | Generate the next card in a single LLM call using the updated LearningProfile and GenerationProfile | P0 |
| FR-06 | Include one motivational micro-feedback sentence in every generated card | P0 |
| FR-07 | Return 409 with `{"ceiling": true}` when `card_index >= 8` (no more cards to generate) | P0 |
| FR-08 | Return 502 (with silent frontend fallback to existing card) when LLM fails | P0 |
| FR-09 | Schedule a spaced-review entry in `spaced_reviews` when a concept is mastered | P1 |
| FR-10 | Expose due spaced reviews for a student via `GET /api/v2/students/{student_id}/review-due` | P1 |
| FR-11 | Display review-due badge on ConceptMap nodes that have pending reviews | P1 |
| FR-12 | Adaptive Socratic check: derive question complexity from the blended LearningProfile at the time `finishCards()` is called | P1 |
| FR-13 | Surface "known weak concept" state when a student has failed a concept 2+ times without mastering | P2 |
| FR-14 | Feature flag `ADAPTIVE_CARDS_ENABLED` in `config.py` — when `False`, `complete-card` returns the next pre-generated card without LLM call | P0 |

### User Stories

**US-01 (P0):** As a student who is struggling on card 3, I want the next card to be simpler and more patient, so that I can build confidence before tackling harder material.

**US-02 (P0):** As a student who answered every card quickly and correctly, I want the next card to be more challenging, so that I am not bored by material I already understand.

**US-03 (P0):** As a student who is normally fast but today is unusually slow, I want the system to detect this deviation from my personal norm (not a generic norm) and adapt accordingly.

**US-04 (P1):** As a student who mastered "Fractions" last week, I want to be reminded to review it today, so that I retain it through spaced repetition.

**US-05 (P1):** As a student entering the Concept Map, I want to see a badge on concepts that are due for review, so that I know where to focus.

**US-06 (P0):** As a student completing each card, I want a short warm message of encouragement, so that the learning experience feels supportive.

---

## 3. Non-Functional Requirements

### Performance
- `POST /api/v2/sessions/{session_id}/complete-card` p95 latency: **< 2500 ms** (single LLM call + DB read/write)
- DB history aggregation query: **< 50 ms** (indexed on `student_id`, `concept_id`)
- `GET /api/v2/students/{student_id}/review-due` p95 latency: **< 100 ms** (pure DB query, no LLM)
- LLM token budget per card: `max_tokens = 1200` (single card, not full lesson)

### Scalability
- Current load: estimated 50–200 concurrent active learning sessions
- The blending and profile classification functions are pure (no I/O) and add zero latency
- DB queries are bounded: history aggregation reads at most N rows per student (capped by card_interactions growth over time); an index on `(student_id)` ensures sub-millisecond scans at current scale

### Availability and Reliability
- LLM failure must never crash the session. The endpoint returns HTTP 502; the frontend silently falls back to the last-known card or a pre-generated card from the initial batch
- `ADAPTIVE_CARDS_ENABLED = False` provides a full degradation path that requires no LLM
- Spaced review scheduling failures are logged but must not fail the mastery completion flow

### Security
- Session ownership is validated: the `session_id` in the URL must belong to the authenticated student (checked via DB join)
- No student data crosses the LLM boundary — only the concept content, the GenerationProfile parameters, and the motivational note request are sent to OpenAI
- All DB writes use parameterised queries via SQLAlchemy ORM (no raw SQL)

### Maintainability and Observability
- Every card generation emits a structured log line including `student_id`, `session_id`, `card_index`, `adaptation_applied`, `blended_speed`, `blended_comprehension`, `duration_ms`
- The `adaptation_applied` field is persisted to `card_interactions.adaptation_applied` for offline analysis
- A PostHog event `adaptive_card_generated` is fired by the frontend with `card_index`, `adaptation_applied`, and `performance_vs_baseline`

---

## 4. System Context Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Browser (Student)                             │
│                                                                      │
│  CardLearningView.jsx                                                │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Timer (useRef) tracks time_on_card_sec                      │    │
│  │ Wrong attempt counter, hint counter, idle trigger counter   │    │
│  │ On "Next Card" click → POST /api/v2/sessions/{id}/          │    │
│  │                             complete-card                   │    │
│  │ On response → replace current card with new card            │    │
│  │ On 409 ceiling → call finishCards() (Socratic check)        │    │
│  │ On 502 → silent fallback (keep existing card or advance)    │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ConceptMapPage.jsx — displays review-due badge from                 │
│  GET /api/v2/students/{id}/review-due                                │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ HTTPS/JSON
                            │
┌───────────────────────────▼──────────────────────────────────────────┐
│                    FastAPI Backend (Port 8000)                        │
│                                                                       │
│  /api/v2 Router (teaching_router.py + new complete-card route)        │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  complete_card_endpoint()                                       │ │
│  │    1. Validate session ownership (DB)                           │ │
│  │    2. Write CardInteraction row                                 │ │
│  │    3. aggregate_student_baseline() ──→ card_interactions table  │ │
│  │    4. blend_signals()  [pure function]                          │ │
│  │    5. build_learning_profile() [pure, reused from adaptive/]    │ │
│  │    6. build_generation_profile() [pure, reused from adaptive/]  │ │
│  │    7. generate_next_card() ──→ OpenAI API                       │ │
│  │    8. schedule_spaced_review() if ceiling reached               │ │
│  │    9. Return NextCardResponse                                   │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  /api/v2/students/{id}/review-due  ──→ spaced_reviews table          │
│                                                                       │
│  Existing (unchanged):                                                │
│    /api/v3/adaptive/lesson  (first card batch, not modified)          │
│    /api/v2/sessions/{id}/begin-check  (Socratic check, not modified)  │
└─────────────────────┬────────────────────────────────────────────────┘
                      │
         ┌────────────┴──────────────┐
         │                           │
┌────────▼────────┐        ┌─────────▼────────┐
│  PostgreSQL 15  │        │  OpenAI API       │
│                 │        │  gpt-4o           │
│ card_interactions        │  (single card     │
│ spaced_reviews  │        │   generation)     │
│ teaching_sessions        └──────────────────┘
│ student_mastery │
└─────────────────┘
```

**Data flow summary:**
1. Frontend sends behavioral signals (6 fields) on each card advance
2. Backend persists signals, reads historical baseline, blends signals, classifies profile
3. Backend calls OpenAI with a single-card prompt derived from the updated profile
4. Backend returns the next card with motivational note and adaptation metadata
5. On mastery completion, backend writes a `spaced_reviews` row
6. ConceptMap polls review-due endpoint on page load; renders badges

---

## 5. Architectural Style and Patterns

### Selected Style: Request-Response with In-Request Analytics Pipeline

Rather than introducing an event bus or async queue, adaptation happens synchronously within the HTTP request. This keeps the system simple and latency predictable. The only asynchronous element is the LLM call, which is already modelled as an `await`.

**Justification:**
- At current student scale (50–200 sessions), a synchronous LLM call per card advance is well within latency budgets
- An event-driven approach (e.g., Kafka + consumer) would add operational complexity that is not justified until tens of thousands of concurrent users
- The blending algorithm is deterministic and pure, which makes it trivially testable and requires no infrastructure

**Alternatives considered:**

| Alternative | Why Rejected |
|---|---|
| Pre-generate all cards upfront in a larger batch (e.g., 20 cards) | Wastes LLM tokens on cards the student never sees; cannot react to within-session behaviour |
| Background task queue (Celery/Redis) to pre-generate next card speculatively | Adds infrastructure complexity; speculative generation may still miss the actual profile at card transition time |
| Full streaming response from LLM to frontend | KaTeX rendering requires complete JSON; streaming partial JSON cannot be validated or rendered |

### Reuse of Existing Patterns
- `_call_llm()` — reused verbatim from `adaptive_engine.py` (3-attempt retry with exponential back-off)
- `build_learning_profile()` — reused verbatim from `adaptive/profile_builder.py` (pure function)
- `build_generation_profile()` — reused verbatim from `adaptive/generation_profile.py` (pure function)
- `_extract_json_block()` + `_salvage_truncated_json()` — reused from `adaptive_engine.py`
- Module-level service injection pattern — identical to `adaptive_router.py` and `teaching_router.py`

---

## 6. Technology Stack

| Concern | Technology | Rationale |
|---|---|---|
| New endpoint module | Python / FastAPI async (extends existing `/api/v2`) | Consistent with all existing v2 endpoints; no new framework |
| History aggregation | SQLAlchemy 2.0 async `select()` with `func.avg()` | Already in use; avoids raw SQL; correct async pattern |
| Blending algorithm | Pure Python functions in `adaptive/blending.py` (new file) | Keeps logic testable without DB mocks; consistent with profile_builder pattern |
| Single-card prompt | New function `build_next_card_prompt()` in `adaptive/prompt_builder.py` | Extends existing prompt_builder; avoids new module |
| LLM call | `_call_llm()` from `adaptive_engine.py` | Reused — no duplication |
| Spaced review scheduling | Pure Python function `compute_next_due()` in `adaptive/spaced_review.py` (new file) | Isolated, pure, testable |
| Frontend signals | `useRef` timer + counter state in `CardLearningView.jsx` | Minimal React overhead; ref-based timer does not trigger re-renders |
| Frontend API call | New function `completeCard()` in `frontend/src/api/sessions.js` | Consistent with all other session API wrappers |
| Feature flag | `ADAPTIVE_CARDS_ENABLED: bool` in `config.py` | Follows established config.py convention |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-001: One LLM Call Per Card Transition (Not Per Session)
**Decision:** Generate each subsequent card with a fresh LLM call triggered by the `complete-card` endpoint, rather than pre-generating all cards at session start.
**Options considered:** (a) batch generation at session start, (b) speculative background generation, (c) per-transition generation (chosen)
**Rationale:** Only per-transition generation can respond to actual in-session behaviour. The latency cost (~1.5 s) is acceptable for a learning context where the student is reviewing their answer before advancing.
**Trade-off:** Higher LLM API cost per session (7–12 calls instead of 1). Mitigated by capping `max_tokens=1200` per card and the `ceiling` at card index 8.

### ADR-002: Blend Current Signal with Historical Baseline (Not Replace)
**Decision:** Use a weighted blend of current-card signal and historical average rather than using either alone.
**Rationale:** Using only current signal makes the system brittle to outlier moments (student was interrupted on one card). Using only historical baseline ignores real in-session distress. Blending (60/40 steady-state, 90/10 for acute deviations) balances responsiveness with stability.
**Trade-off:** The blend ratio constants (`MIN_HISTORY_CARDS = 5`, `0.9/0.1`, `0.6/0.4`) are empirically chosen. They must be tunable constants in `config.py`, not hardcoded, to allow adjustment based on A/B testing.

### ADR-003: Ceiling at Card Index 8
**Decision:** The maximum number of adaptively generated cards per session is 8 (indices 0–7). When `card_index >= 8` is sent, the endpoint returns 409.
**Rationale:** Prevents runaway LLM cost; initial lesson already provides 7–12 cards; an adaptive tail of up to 8 additional cards gives ample material for any student state.
**Trade-off:** A struggling student could theoretically benefit from more. This is a cost/experience trade-off; can be raised in a config constant `ADAPTIVE_CARD_CEILING` without code changes.

### ADR-004: Ebbinghaus Fixed Intervals for Spaced Repetition (v1)
**Decision:** Use fixed intervals [+1, +3, +7, +14, +30 days] rather than the full SM-2 variable ease-factor algorithm.
**Rationale:** SM-2 requires tracking per-concept ease factors and requires a meaningful performance signal from each review attempt. ADA does not yet collect review performance signals. Fixed intervals are a well-understood, pedagogically sound starting point.
**Trade-off:** Suboptimal for students with very different retention rates. Upgrade path: add `ease_factor` column to `spaced_reviews` and implement SM-2 in a future migration.

### ADR-005: Motivational Note Inside LLM Card JSON (Not a Separate Call)
**Decision:** Include `motivational_note` as a field inside the single-card JSON response from the LLM rather than making a second LLM call.
**Rationale:** A second call would add ~800 ms of latency. The note is short (1 sentence) and can be guided by a prompt constraint. Including it in the same JSON ensures the tone is contextually appropriate to the card content.
**Trade-off:** Marginally increases prompt complexity. The schema enforcement constraint (`"motivational_note": "<one warm sentence>"`) keeps it bounded.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM latency exceeds 2500 ms p95 | Medium | Medium | Cap `max_tokens=1200`; use `gpt-4o-mini` for single-card generation (lower latency, sufficient quality for one card); expose model as config constant `ADAPTIVE_CARD_MODEL` |
| LLM returns malformed JSON for single card | Medium | Low | Reuse `_salvage_truncated_json()` + Pydantic validation from adaptive_engine; on failure return 502 and let frontend fall back silently |
| `card_interactions` table grows very large over time | Low | Low | Add composite index `(student_id, completed_at DESC)` in migration; aggregation query uses `LIMIT` to read only the last 100 rows per student |
| Blending constants are wrong for diverse student populations | Medium | Medium | Constants (`MIN_HISTORY_CARDS`, blend ratios, deviation thresholds) are defined in `config.py`, not hardcoded; can be tuned without deployment |
| Frontend timer inaccurate if tab is backgrounded | Low | Low | Use `performance.now()` instead of `Date.now()` — more reliable across tab visibility changes; document as known limitation |
| Spaced review scheduling creates duplicate rows | Low | High | Add unique constraint `(student_id, concept_id, review_number)` to `spaced_reviews` (to be confirmed with devops-engineer — may require Alembic patch migration) |
| Students game the system (answer instantly to get easier cards) | Low | Low | Speed classification requires `attempts <= 1` guard (already in `classify_speed()`); FAST classification without correctness is blocked by comprehension check |

---

## Key Decisions Requiring Stakeholder Input

1. **`ADAPTIVE_CARD_MODEL` value:** Should single-card generation use `gpt-4o` (higher quality, ~1.8 s) or `gpt-4o-mini` (lower cost, ~0.7 s)? The DLD defaults to `gpt-4o-mini` for single-card generation. Confirm before implementation.

2. **`ADAPTIVE_CARD_CEILING` value:** The ceiling is specified as 8 in the feature brief. Confirm this is the correct pedagogical limit. It maps to a `config.py` constant and can be changed at any time.

3. **Unique constraint on `spaced_reviews`:** The current migration `e3c02cf4c22e` adds `spaced_reviews` without a unique constraint on `(student_id, concept_id, review_number)`. A patch migration is needed to prevent duplicate review rows on rapid re-mastery. Confirm scope with devops-engineer.

4. **Review-due badge in ConceptMap:** The feature brief mentions badges on ConceptMap nodes. The ConceptMap currently uses Sigma/Graphology for graph rendering. Confirm the expected badge style and whether it requires a new graph node property or a separate overlay layer in `ConceptMapPage.jsx`.

5. **Weak-concept tracking threshold:** FR-13 specifies "failed 2+ times without mastering." Define "failed" — does it mean `check_score < MASTERY_THRESHOLD` (70), or does it mean the Socratic check was not completed? This affects the DB query used for weak-concept detection.
