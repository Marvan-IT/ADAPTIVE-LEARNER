# Per-Card Adaptive Generation — High-Level Design

**Feature slug:** `per-card-adaptive-generation`
**Author:** Solution Architect Agent
**Date:** 2026-03-24
**Status:** Ready for implementation

---

## 1. Executive Summary

### Feature Name
Per-Card Adaptive Generation

### Business Problem
ADA currently generates lesson cards in section-sized batches. Cards are generated before the student interacts with them, so presentation mode (STRUGGLING / NORMAL / FAST) is fixed at batch-generation time. A student who struggles on card 4 or accelerates past expectations on card 2 receives no adjusted content for the remaining pre-generated cards.

A secondary structural bug means `section_count` — the field that controls blending weights in `build_blended_analytics()` — is never incremented during a session. The system permanently operates in cold-start mode (80 / 20 current-vs-history weighting), ignoring all accumulated session signal.

### Solution
Replace rolling batch generation with a per-card on-demand loop:

1. Session start: generate 3 cards covering content pieces P1, P2, P3
2. After each card completion: `POST /sessions/{id}/next-card` generates exactly one card for the next content piece, using the student's current blended performance score
3. Content pieces are always covered in textbook order — nothing is skipped, all students receive the same number of cards
4. What adapts: HOW each piece is presented (STRUGGLING gets step-by-step; FAST gets MCQ-dense technical prose)
5. `has_more_concepts=false` when all pieces are exhausted — triggers Socratic phase unchanged

The feature also fixes eight confirmed bugs listed in the Known Bugs section.

### Key Stakeholders
- Product: Adaptive learning team
- Engineering: Backend developer, Frontend developer
- QA: Comprehensive tester

### Scope

**Included:**
- New `POST /api/v2/sessions/{id}/next-card` endpoint
- New `generate_per_card()` method on `TeachingService`
- `section_count` increment fix in the per-card service path
- Image injection into per-card prompts via `build_next_card_prompt()`
- New `NextCardRequest` and `NextCardResponse` Pydantic schemas
- `NEXT_CARD_MAX_TOKENS` constant in `config.py`
- Frontend `nextCardInFlight` guard (Bug 1 fix)
- Frontend `NEXT_CARD` reducer boundary fix (Bug 2 fix)
- New `fetchNextAdaptiveCard()` Axios wrapper in `sessions.js`

**Excluded:**
- Socratic phase — unchanged; begins when `has_more_concepts=false`
- Mastery logic — unchanged
- `POST /sessions/{id}/complete-card` — unchanged (continues handling recovery cards)
- `POST /sessions/{id}/next-section-cards` — kept for backward compatibility; deprecated but not removed
- Any database schema changes
- Pre-fetch optimisation (generating the next card while student is on current one) — deferred to v2

---

## 2. Functional Requirements

| ID | Priority | Requirement |
|----|----------|-------------|
| FR-1 | Critical | Session start generates exactly 3 cards (P1, P2, P3); remaining pieces are queued |
| FR-2 | Critical | `POST /next-card` pops the next content piece from queue and generates one card |
| FR-3 | Critical | Content pieces are covered in original textbook order — nothing is skipped |
| FR-4 | Critical | Every content piece yields exactly one card (one-to-one mapping) |
| FR-5 | Critical | Presentation mode is derived from `build_blended_analytics()` result at generation time |
| FR-6 | Critical | `has_more_concepts=false` in response when queue is empty; frontend begins Socratic |
| FR-7 | High | `section_count` is incremented once per successful per-card call so blend weights graduate |
| FR-8 | High | Images from the concept image pool are injected into per-card prompts |
| FR-9 | High | Frontend does not fire concurrent `next-card` requests (race condition guard) |
| FR-10 | High | Frontend `currentCardIndex` can advance past `cards.length - 1` to receive appended cards |
| FR-11 | Medium | Section with fewer than 3 pieces: initial batch covers all pieces, queue is empty |
| FR-12 | Medium | `POST /next-card` failure is graceful — student is not stuck; Socratic can still begin |

---

## 3. Non-Functional Requirements

| Concern | Target |
|---------|--------|
| Per-card latency | p50 < 4 s, p99 < 10 s (gpt-4o-mini, NEXT_CARD_MAX_TOKENS=1200) |
| Throughput | No new infrastructure — inherits FastAPI/Uvicorn concurrency |
| Availability | No new external dependencies introduced |
| Backward compatibility | All existing endpoints continue to function unchanged |
| Security | Inherits `APIKeyMiddleware` and `slowapi` rate limiting from existing middleware |
| Observability | Structured log per call: student_id, concept_id, section_count, generate_as, duration_ms |
| Test coverage | Unit: service method, reducer fix, in-flight guard; Integration: round-trip via API |

---

## 4. System Context Diagram

```
BROWSER (React 19)
─────────────────────────────────────────────────────────────────────────
SessionContext.startLesson()
  │
  ├─► POST /api/v2/sessions                     [create session]
  └─► POST /api/v2/sessions/{id}/cards          [initial 3-card batch]
        Response: cards=[P1,P2,P3], concepts_queue=[P4,P5,...], has_more_concepts=true

Student views card P1, P2, P3 ...
                          │
                          │ [on Next tap at last pre-generated card]
                          ▼
SessionContext.goToNextCard()
  └─► fetchNextAdaptiveCard()
        │
        ├─► POST /api/v2/sessions/{id}/next-card   [per-card request]
        │     Body: { card_index, time_on_card_sec, wrong_attempts, hints_used, idle_triggers }
        │     Response: { card: LessonCard, has_more_concepts: bool, current_mode: str }
        │
        └─► dispatch APPEND_NEXT_CARD → currentCardIndex auto-advances

                          │ [all pieces exhausted: has_more_concepts=false]
                          ▼
SessionContext.finishCards() → POST /sessions/{id}/complete-cards → begin Socratic

─────────────────────────────────────────────────────────────────────────
FASTAPI BACKEND (port 8889)
─────────────────────────────────────────────────────────────────────────
teaching_router.py
  POST /next-card
    ├── Auth check (APIKeyMiddleware)
    ├── Rate limit: 30/minute
    ├── Load session (404 if missing)
    ├── Assert phase == "CARDS" (409 otherwise)
    └── teaching_svc.generate_per_card(db, session, student, req)

teaching_service.py — generate_per_card()
  ├── Parse concepts_queue from session.presentation_text
  ├── Return empty card + has_more_concepts=false if queue empty
  ├── Pop next_piece = concepts_queue[0]
  ├── load_student_history() [DB query]
  ├── Increment history["section_count"] by 1
  ├── build_blended_analytics(current_signals, history, ...) → (blended, score, mode)
  ├── Resolve available images (exclude assigned_image_indices)
  ├── build_next_card_prompt(next_piece text, images, learning_profile, ...)
  ├── _call_llm(gpt-4o-mini, NEXT_CARD_MAX_TOKENS)
  ├── Validate + normalise card dict
  ├── Write updated cache (pop consumed piece, update assigned_image_indices)
  └── Return { card, has_more_concepts, current_mode }

adaptive_engine.py — build_blended_analytics()
  └── Selects blend weights from section_count via ADAPTIVE_COLD/WARM/PARTIAL/STATE constants

prompt_builder.py — build_next_card_prompt()
  └── Extended to accept content_piece_text + content_piece_images parameters

PostgreSQL 15
  └── TeachingSession.presentation_text (JSON cache — queue + metadata)
```

---

## 5. Architectural Style and Patterns

### Selected Style: Refinement of the existing rolling-generation pattern

The existing system already implements rolling card generation (`generate_next_section_cards`). This feature refines the granularity from *section batch* to *individual content piece*. All established patterns are reused:

- **Session JSON cache pattern:** `session.presentation_text` stores `concepts_queue`. Per-card pops from the same list; the updated cache is written back after each call.
- **LLM retry pattern:** `TeachingService._chat()` — 3 attempts, exponential back-off, established in `teaching_service.py`.
- **Blended analytics pattern:** `build_blended_analytics()` from `adaptive_engine.py` — already used by `generate_cards()` and `generate_next_section_cards()`. Per-card path reuses it without modification.
- **Module-level service injection:** No new service instances — the existing `teaching_svc` reference in `teaching_router.py` is used.

### Rationale
No new architecture is warranted. The per-card loop is logically equivalent to existing rolling generation at a finer granularity. Introducing a dedicated queue service or a new DB table would add infrastructure and migration work with no benefit at current scale. The JSON cache is sufficient for queues up to ~50 items (the existing `STARTER_PACK_MAX_SECTIONS` cap).

### Trade-offs

| Decision | Trade-off accepted |
|----------|-------------------|
| JSON cache vs. dedicated queue table | Avoids schema change; acceptable for per-session short-lived queue |
| On-demand generation vs. pre-fetch | Simpler; pre-fetch optimisation (fire while student reads current card) deferred |
| gpt-4o-mini vs. gpt-4o | Existing decision per ADAPTIVE_CARD_MODEL; sufficient for single-card generation at 1200 tokens |

---

## 6. Technology Stack

All additions are extensions of the existing stack. No new packages required.

| Layer | Technology | Change |
|-------|-----------|--------|
| Backend | FastAPI 0.128+ async, Python | New endpoint + service method |
| LLM | OpenAI gpt-4o-mini (`ADAPTIVE_CARD_MODEL`) | Existing — new call site |
| Session cache | PostgreSQL 15 TEXT field (JSON) | New read/write in per-card path |
| Frontend | React 19 `useReducer` | New state field, reducer cases, callback logic |
| HTTP client | Axios 1.13 | New wrapper function in `sessions.js` |
| Config | `config.py` | One new constant: `NEXT_CARD_MAX_TOKENS` |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-1: One card per content piece (not per section batch)

**Options:** A) Per content piece (this feature) | B) Batch size reduced to 1 section | C) Adaptive batch size

**Decision:** A.

**Rationale:** Per-piece is the finest granularity for adaptation and matches the stated requirement. Options B and C add complexity without cleaner semantics. Content pieces are already the atomic unit in `_generate_cards_per_section`.

### ADR-2: concepts_queue in session.presentation_text cache (no new table)

**Options:** A) Existing JSON cache | B) New `card_queue` DB table

**Decision:** A.

**Rationale:** The queue is short-lived (one session, up to 50 items, ~500 bytes each = ~25 KB max). A new DB table requires a migration and adds query overhead with no benefit.

### ADR-3: section_count incremented in service layer, not inside adaptive_engine

**Options:** A) Increment in `generate_per_card()` before calling `build_blended_analytics()` | B) Auto-increment inside `build_blended_analytics()`

**Decision:** A.

**Rationale:** `build_blended_analytics()` is a pure function with no I/O. Incrementing inside it would violate this contract and make the function non-deterministic for the same inputs.

### ADR-4: nextCardInFlight as reducer state (not a ref)

**Options:** A) `useRef` (zero re-renders) | B) Reducer state field

**Decision:** B.

**Rationale:** The in-flight state must be visible in the UI to disable the Next button during generation. Refs do not trigger re-renders.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LLM call too slow — student sees spinner | Medium | Medium | `NEXT_CARD_MAX_TOKENS=1200` caps latency; gpt-4o-mini ~2 s average. Pre-fetch optimisation is planned for v2. |
| `concepts_queue` corrupted / empty on JSON parse | Low | High | Return `has_more_concepts=false` + structured log; student advances to Socratic |
| Duplicate concurrent requests from rapid tapping | Medium | Low | `nextCardInFlight` guard prevents second dispatch; rate limiter provides backstop |
| `section_count` briefly stale on concurrent sessions for same student | Low | Low | Blend weight is a soft heuristic; minor inaccuracy has no correctness impact |
| Image pool depletion mid-session | Low | Low | `content_piece_images` is optional in prompt builder; cards render fine without images |
| Frontend stuck at last card if `has_more_concepts` never received | Low | High | Bug 2 fix ensures reducer allows index advance past `cards.length - 1`; `finishCards()` is always callable as fallback |

---

## Key Decisions Requiring Stakeholder Input

1. **Starter pack size:** Current value is `STARTER_PACK_INITIAL_SECTIONS=2`. Changing to `3` would provide one more card before the first on-demand call fires, reducing perceived spinner time. One-line config change — confirm preference before Phase 1 begins.

2. **Pre-fetch strategy:** Currently, `next-card` fires *after* the student taps Next (student sees a spinner while the card generates). An alternative is to fire the request while the student is still on the second-to-last pre-generated card. This eliminates spinner latency but adds complexity to the in-flight guard. Confirm UX preference before Phase 4 (frontend) implementation begins.

3. **Deprecation of `next-section-cards`:** Once per-card generation is live, `POST /sessions/{id}/next-section-cards` is superseded. Confirm whether it should return 410 Gone or continue operating as a legacy path.
