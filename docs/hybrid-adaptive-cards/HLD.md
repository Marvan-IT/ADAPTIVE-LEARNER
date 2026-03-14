# High-Level Design — Hybrid Rolling Adaptive Card Generation

**Feature slug:** `hybrid-adaptive-cards`
**Author:** Solution Architect
**Date:** 2026-03-14
**Status:** Approved for implementation

---

## 1. Executive Summary

### Feature Name and Purpose
Hybrid Rolling Adaptive Card Generation replaces the current single-batch card generation approach with a rolling, sub-section-by-sub-section pipeline that interleaves real-time adaptive signals into content delivery.

### Business Problem Being Solved
The current architecture generates ALL lesson cards in one bulk LLM call at session start. This produces five confirmed bugs:

| Bug ID | Description | Root Cause |
|--------|-------------|------------|
| B1 | Only 2-3 cards per sub-section | Token budget formula applied to N sections in one call causes per-section starvation |
| B2 | Cards appear in wrong order | Fuzzy RC4 sort applied after bulk generation loses sub-section ordering signal |
| B3 | Same MCQ reappears after wrong answer | No pre-generated `question2` backup; live regeneration call on wrong answer adds 2-3s latency |
| B4 | No real-time mode adaptation | Adaptive signals collected during the session never influence already-generated cards |
| B5 | "Finish Cards" and Socratic chat appear before all content is covered | Frontend only checks card index, not whether all sub-sections have been delivered |

### Key Stakeholders
- Product: Needs confirmed resolution of all five bugs before wider rollout
- Backend developer: Owns `teaching_service.py`, `teaching_router.py`, `prompts.py`
- Frontend developer: Owns `SessionContext.jsx`, `CardLearningView.jsx`
- Students: Reduced latency at session start, better content coverage, zero wrong-MCQ repetition

### Scope

**Included:**
- Rolling sub-section generation (starter pack + rolling pre-fetch)
- `question2` field on every LLM-generated card (pre-generated backup MCQ)
- `has_more_concepts` flag controlling gate to Socratic chat and "Finish Cards" button
- `concepts_queue` stored in `presentation_text` JSON blob (zero DB schema changes)
- New `POST /api/v2/sessions/{id}/next-section-cards` endpoint
- `_section_index` stamping on every card for deterministic frontend sorting
- Token budget fix: per-section floors raised to 6000 / 4500 / 3000 tokens
- Cache version bump to 11 to force all stale cached sessions to regenerate
- Removal of `_ADAPTIVE_CARD_CEILING = 20` from `adaptive_router.py`

**Explicitly Excluded:**
- DB schema changes (no new columns or tables)
- Changes to the Socratic check phase logic
- Changes to remediation card generation
- Spaced review or XP award logic
- New Alembic migration (no schema change needed)
- Multilingual prompt changes (LLM generates in student's language already)

---

## 2. Functional Requirements

| ID | Priority | Requirement |
|----|----------|-------------|
| FR-01 | Must | On `POST /sessions/{id}/cards`, return cards only for the first `STARTER_PACK_INITIAL_SECTIONS` (2) sub-sections, plus `has_more_concepts: true` if more sub-sections remain |
| FR-02 | Must | On `POST /sessions/{id}/next-section-cards`, generate and return cards for the next queued sub-section; update the session's `concepts_queue` in `presentation_text` |
| FR-03 | Must | Every LLM-generated card must include a `question2` field (second MCQ) so the frontend can show a fresh question after a wrong answer without a live API call |
| FR-04 | Must | "Finish Cards" button must only be shown when `has_more_concepts === false` AND student is on the last card |
| FR-05 | Must | Socratic chat must only begin after all sub-sections have been delivered (`has_more_concepts === false`) |
| FR-06 | Must | Every generated card must carry a `_section_index` integer so the frontend can sort without fuzzy matching |
| FR-07 | Must | Token budget per sub-section generation must use raised floors: 6000 (SLOW), 4500 (NORMAL), 3000 (FAST) |
| FR-08 | Must | Cache version must be bumped to 11 in `presentation_text` JSON so stale bulk-generated sessions regenerate |
| FR-09 | Should | Frontend pre-fetches the next sub-section when student is 2 cards from end of current batch |
| FR-10 | Should | A `conceptsProgress` i18n key (`"Section {{current}} of {{total}}"`) must be added to all 13 locale files |
| FR-11 | Should | Recovery cards (Case A: both MCQs wrong) must bypass `has_more_concepts` gating and insert immediately |
| FR-12 | Must | `_ADAPTIVE_CARD_CEILING` constant removed from `adaptive_router.py` — recovery cards are unlimited |

---

## 3. Non-Functional Requirements

| Category | Requirement | Target |
|----------|-------------|--------|
| Latency — starter pack | Time from `POST /cards` response to first card displayed | < 4 s P95 (down from current 8-12 s for full batch) |
| Latency — rolling fetch | Time from `POST /next-section-cards` trigger to cards appended in UI | < 3 s P95 (student is 2 cards away, fetch is background) |
| Latency — `question2` display | Time to show backup MCQ after wrong answer | 0 ms (already in card payload; no API call) |
| Throughput | Concurrent sessions generating rolling batches | Inherits existing FastAPI / Uvicorn capacity; no new bottleneck |
| Availability | Feature must degrade gracefully if `next-section-cards` call fails | Frontend shows previously loaded cards; error logged; student can still advance |
| Correctness — coverage | Every sub-section must produce at least 1 card | Enforced by per-section generation loop + numbered checklist in prompt |
| Correctness — ordering | Cards within a sub-section batch delivered in section order | `_section_index` integer on every card; frontend sorts by this field |
| Storage | No increase in PostgreSQL row count or schema | `concepts_queue` stored in existing `presentation_text` TEXT column as JSON |
| Backward compatibility | Old sessions with `cache_version < 11` must regenerate cleanly | Cache version check in `_load_cached_cards()` triggers full regeneration |
| Observability | Each rolling fetch logged with section name + card count | `logger.info("rolling_fetch section=%s cards=%d")` |

---

## 4. System Context Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                         STUDENT BROWSER                              │
│                                                                      │
│  CardLearningView.jsx                                                │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │  SessionContext (React)                                   │       │
│  │  State: cards[], currentCardIndex, hasMoreConcepts        │       │
│  │                                                           │       │
│  │  goToNextCard() — 3 Cases:                                │       │
│  │   Case A  ──► POST /complete-card  (recovery, unlimited) │       │
│  │   Case B  ──► POST /next-section-cards  (rolling fetch)  │       │
│  │   Case D  ──► recordCardInteraction + advance index      │       │
│  │                                                           │       │
│  │  "Finish Cards" btn visible only when:                   │       │
│  │    !hasMoreConcepts && isLastCard                         │       │
│  └──────────────────────────────────────────────────────────┘       │
│         │              │                  │                          │
└─────────┼──────────────┼──────────────────┼──────────────────────────┘
          │              │                  │
     POST /cards   POST /next-       POST /complete-card
     (starter)     section-cards    (adaptive recovery)
          │              │                  │
┌─────────▼──────────────▼──────────────────▼──────────────────────────┐
│                       FastAPI Backend (port 8889)                    │
│                                                                      │
│  teaching_router.py (prefix /api/v2)                                 │
│  ┌────────────────────────────────────────────────────────────┐      │
│  │  POST /sessions/{id}/cards                                  │      │
│  │    ► generate_cards_starter_pack()                          │      │
│  │    ► returns first 2 sub-sections + has_more_concepts       │      │
│  │    ► stores concepts_queue in presentation_text JSON        │      │
│  │                                                             │      │
│  │  POST /sessions/{id}/next-section-cards  (NEW)              │      │
│  │    ► generate_next_section_cards()                          │      │
│  │    ► pops one sub-section from concepts_queue               │      │
│  │    ► stores updated queue back to presentation_text         │      │
│  │    ► returns cards + has_more_concepts                      │      │
│  └────────────────────────────────────────────────────────────┘      │
│                              │                                        │
│  teaching_service.py                                                  │
│  ┌────────────────────────────────────────────────────────────┐      │
│  │  generate_cards()          ─► starter pack only             │      │
│  │  generate_next_section_cards()  ─► rolling (one section)   │      │
│  │  _generate_cards_single()  ─► LLM call (unchanged core)    │      │
│  └────────────────────────────────────────────────────────────┘      │
│                              │                                        │
│  ┌────────────────────────────────────────────────────────────┐      │
│  │  PostgreSQL 15                                               │      │
│  │  teaching_sessions.presentation_text (TEXT)                 │      │
│  │  Stores:                                                     │      │
│  │    { "version": 11,                                         │      │
│  │      "presentation": "...",                                  │      │
│  │      "cached_cards": [...],                                  │      │
│  │      "concepts_queue": ["sec_3", "sec_4", ...],             │      │
│  │      "total_sections": 8 }                                   │      │
│  └────────────────────────────────────────────────────────────┘      │
│                              │                                        │
│  ┌────────────────────────────────────────────────────────────┐      │
│  │  ChromaDB + NetworkX (KnowledgeService)                     │      │
│  │  Provides concept blocks per sub-section                    │      │
│  └────────────────────────────────────────────────────────────┘      │
│                              │                                        │
│  ┌────────────────────────────────────────────────────────────┐      │
│  │  OpenAI API (gpt-4o / gpt-4o-mini)                          │      │
│  │  Called once per sub-section during rolling fetch           │      │
│  └────────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 5. Architectural Style and Patterns

### Selected Style: Rolling Window Generation with In-Band State

Rather than a streaming or WebSocket approach, the design uses a **client-driven rolling window** pattern:

- The backend is stateless per request — all rolling state lives in `presentation_text` JSON
- The frontend drives pre-fetching: it fires `POST /next-section-cards` when the student is 2 cards from end
- Each rolling fetch is an independent LLM call scoped to one sub-section (smaller context window, faster, more adaptive)

### Justification

| Alternative | Reason Rejected |
|-------------|-----------------|
| Server-Sent Events / WebSocket push | Adds connection complexity; FastAPI needs separate SSE handling; overkill when client-driven polling is sufficient |
| Full bulk regeneration on each mode change | 8-12s latency is unacceptable; discards already-seen cards |
| Store `concepts_queue` in new DB column | Requires Alembic migration, DevOps involvement, and is unnecessary since `presentation_text` TEXT column already exists |
| Pre-generate all sections but return in chunks | Wastes LLM tokens generating content the student may never reach |

### Patterns Used

- **Starter pack + rolling pre-fetch:** Reduces time-to-first-card from ~10s to ~3s
- **Idempotent section fetch:** Each `next-section-cards` call is safe to retry — it checks whether the section has already been generated before calling the LLM
- **`_section_index` as truth-of-order:** Removes all fuzzy sorting (RC4 bug); integer comparison is O(n log n) deterministic
- **`question2` pre-generation:** Eliminates the live MCQ regeneration API call (B3 fix); the backup question is in every card's payload at zero added latency

---

## 6. Technology Stack

All choices align with the existing ADA tech stack — no new dependencies are introduced.

| Concern | Technology | Rationale |
|---------|-----------|-----------|
| Backend framework | FastAPI 0.128+ async | Existing; new endpoint follows established pattern |
| LLM | OpenAI `gpt-4o` / `gpt-4o-mini` | Existing; model selection by learner profile as before |
| State storage | `presentation_text` TEXT column (PostgreSQL 15) | No migration required; column already holds JSON blob |
| Frontend state | React 19 `useReducer` (SessionContext) | Existing pattern; new `APPEND_CARDS` action follows established reducer convention |
| i18n | i18next 25 | Existing; new `conceptsProgress` key added to all 13 locale files |
| Schema validation | Pydantic v2 | Existing; two new schemas (`NextSectionCardsRequest`, `NextSectionCardsResponse`) |
| HTTP client | Axios 1.13 | Existing; one new wrapper function `getNextSectionCards()` in `sessions.js` |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-01: Store `concepts_queue` in `presentation_text` rather than a new DB column

- **Options considered:** (A) New `concepts_queue` TEXT column via Alembic, (B) In-memory on FastAPI process (lost on restart), (C) Embed in existing `presentation_text` JSON blob
- **Decision:** Option C
- **Rationale:** No migration required; the `presentation_text` column already holds a versioned JSON object; the queue is session-scoped and naturally co-located with the presentation cache; survives process restarts
- **Trade-off:** The `presentation_text` column grows slightly per session (~500 bytes for queue); acceptable given it is already up to 40KB for cached cards

### ADR-02: Pre-generate `question2` in the same LLM call as `question`

- **Options considered:** (A) Keep live MCQ regeneration endpoint, (B) Add `question2` to the card generation prompt and return it in payload, (C) Generate `question2` asynchronously after card delivery
- **Decision:** Option B
- **Rationale:** Zero added latency for the student; no new API round-trip; the LLM already has full section context in the same call; only a small prompt addition is needed
- **Trade-off:** Each card's token cost increases by ~100-150 tokens for `question2`; acceptable given the elimination of a 2-3s live API round-trip

### ADR-03: Frontend drives pre-fetch timing (not backend push)

- **Options considered:** (A) Backend pushes cards via SSE, (B) Frontend fires next-section fetch when 2 cards from end, (C) Frontend fires fetch after last card of section is seen
- **Decision:** Option B (2-card lookahead trigger)
- **Rationale:** 2 cards lookahead gives approximately 30-60 seconds of buffer at average reading pace; server-side push requires persistent connection management; client-driven is simpler to implement and debug
- **Trade-off:** If the student reads cards very fast (< 5s per card), the pre-fetch may not complete before the last card — mitigated by the `adaptiveCardLoading` spinner that already exists in the UI

### ADR-04: `_section_index` as an integer stamped by the service layer

- **Options considered:** (A) Keep RC4 fuzzy sort, (B) Use section title string comparison, (C) Stamp an integer `_section_index` on every card at generation time
- **Decision:** Option C
- **Rationale:** Integer sort is O(n log n) deterministic; eliminates the RC4 fuzzy match bug entirely; the service knows section order at generation time and can stamp it cheaply
- **Trade-off:** Adds one integer field to every card in the payload; negligible

### ADR-05: Cache version bump to 11

- **Decision:** Bump `cache_version` from current value to 11 in `presentation_text` structure
- **Rationale:** Forces all existing cached sessions (which used bulk generation) to regenerate under the new rolling architecture; without this bump, students with existing sessions would receive stale bulk cards
- **Trade-off:** All in-progress sessions regenerate their starter pack on next visit (one-time ~4s cost per student)

---

## 8. Risks and Mitigations

| Risk ID | Risk | Probability | Impact | Mitigation |
|---------|------|-------------|--------|------------|
| R1 | `concepts_queue` JSON grows large for concepts with 20+ sub-sections | Low | Low | Queue stores section IDs only (strings), not content; < 1KB overhead |
| R2 | Rolling fetch arrives after student reaches last card — blank state | Medium | High | `adaptiveCardLoading` spinner already in `CardLearningView.jsx`; 2-card lookahead provides ~30s buffer; graceful error returns existing cards |
| R3 | Concurrent rolling fetches (double-tap) result in duplicate sections | Low | Medium | Backend idempotency check: if section already in `cached_cards`, return without LLM call |
| R4 | `presentation_text` column update (queue mutation) under concurrent requests | Low | Medium | `SELECT ... FOR UPDATE` row lock on session row during queue pop |
| R5 | Old sessions with `cache_version < 11` fail to regenerate cleanly | Low | Medium | Cache miss path already tested; falls back to full starter pack generation |
| R6 | `question2` increases LLM token cost materially | Low | Low | ~150 tokens per card × 6 cards per section = ~900 tokens extra per section; within budget |
| R7 | 13 locale files not fully updated before frontend deploy | Medium | Medium | Execution plan enforces locale files as part of Stage 2 DoD; fallback is `en` key |
| R8 | `_ADAPTIVE_CARD_CEILING` removal breaks adaptive_router tests | Low | Medium | Test suite must be updated in the same stage as the removal |

---

## Key Decisions Requiring Stakeholder Input

1. **Starter pack size:** `STARTER_PACK_INITIAL_SECTIONS = 2` is the proposed default. Should this be configurable per book (e.g., Calculus sections are longer and may need 1)?
2. **Pre-fetch trigger distance:** 2 cards from end is the proposed trigger. Should it be configurable via a config constant (e.g., `ROLLING_PREFETCH_TRIGGER_DISTANCE = 2`)?
3. **Stale session UX:** Students with sessions started before cache version 11 will see their starter pack regenerate silently. Should there be a UI notification ("Your lesson has been updated")?
4. **`question2` requirement on CHECKIN cards:** CHECKIN cards are backend-generated (not LLM). Confirm `question2` is only required on LLM-generated card types (TEACH, EXAMPLE, VISUAL, QUESTION, APPLICATION, EXERCISE, RECAP, FUN).
