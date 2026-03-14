# High-Level Design — Real-Time Adaptive Cards

**Feature slug:** `real-time-adaptive-cards`
**Date:** 2026-03-10
**Author:** Solution Architect

---

## 1. Executive Summary

### Feature Name and Purpose
Real-Time Adaptive Cards is a session-level architecture that replaces the static "generate all cards up front" model with a rolling adaptive loop. Each card the student completes triggers a background LLM call that customises the *next* card to that student's live performance signals, while the student continues reading the current card without interruption.

### Business Problem Being Solved
Before this feature the following defects existed:

1. **Bypassed adaptive engine.** All cards were generated in a single batch at session start using only historical data. The `complete-card` adaptive endpoint existed but was only called after the student had consumed all pre-generated cards — at which point the session was already over in practice.
2. **Token budget overrun.** A concept with many sub-sections could produce 57 micro-sections. Generating cards for all of them in one LLM call exceeded the output token budget, causing truncated JSON and blank screens.
3. **Curriculum position errors.** Gap-fill cards (re-generated for sections that produced no card on the first pass) were appended to the end of the list instead of being inserted at their original curriculum position.
4. **VISUAL cards had no images.** The LLM assigns images via `image_indices` in its JSON output. When the LLM omitted `image_indices` for a VISUAL-typed card (~30% of the time), the card displayed with no illustration despite one being conceptually required.
5. **Cache poisoning.** Stale sessions cached under `cache_version < 3` returned cards built with old prompt logic, so prompt improvements had no visible effect without a manual DB wipe.

### Key Stakeholders
- Students: experience responsive, personalised card progression
- Backend engineers: own `teaching_service.py`, `adaptive_router.py`, `config.py`
- Frontend engineers: own `SessionContext.jsx`

### Scope

**Included:**
- Starter-pack generation limiting initial batch to `STARTER_PACK_MAX_SECTIONS = 2` sections
- Per-section parallel LLM calls with text-driven token budget
- Rolling `REPLACE_UPCOMING_CARD` reducer in `SessionContext.jsx`
- Concurrency guard (`adaptiveCallInFlight` flag)
- Envelope preservation in `adaptive_router.py`
- Gap-fill sort restoring curriculum order
- VISUAL card keyword-scoring image fallback
- Cache version bump to `_CARDS_CACHE_VERSION = 3`

**Excluded (out of scope):**
- Changing the Socratic check or mastery scoring logic
- Persisting adaptive card content to a separate DB table
- Per-student image personalisation
- Any frontend component changes outside `SessionContext.jsx`

---

## 2. Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Session start must return a small starter pack (cards from the first 2 sections only) within the existing latency budget | P0 |
| FR-2 | After each card answer the backend must generate a personalised next card using the student's live signals | P0 |
| FR-3 | The student must never wait for the adaptive LLM call to see the next card; advance is immediate | P0 |
| FR-4 | Concurrent `complete-card` calls from the same session must be deduplicated on the frontend | P1 |
| FR-5 | Page reload after adaptive cards have been generated must not retrigger full card generation | P1 |
| FR-6 | Gap-fill cards must appear at their correct curriculum position, not the end | P1 |
| FR-7 | VISUAL-typed cards must always include an image, even when the LLM omits `image_indices` | P1 |
| FR-8 | Stale cached cards must be automatically detected and discarded | P2 |

---

## 3. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Latency — starter pack | Under 8 s for 2-section concepts on `gpt-4o-mini` |
| Latency — adaptive card | Under 5 s per card (background; student never waits) |
| Throughput — complete-card | 60 requests/minute per IP (rate limiter in place) |
| Throughput — generate_lesson | 10 requests/minute per IP |
| Ceiling | Maximum 20 adaptive cards per session (`_ADAPTIVE_CARD_CEILING`) |
| Reliability | LLM failures fall back gracefully: frontend shows existing card, error is logged |
| Cache correctness | `cache_version = 3` ensures sessions generated under prior prompt logic are automatically discarded and regenerated |
| Observability | Every starter-pack limit event, token budget decision, gap-fill event, and image-fallback event is logged at INFO level with structured fields |

---

## 4. System Context

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ADA Frontend (React 19)                           │
│                                                                             │
│  SessionContext.jsx                                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  state.cards[]        — card array (starter pack + adaptive cards)   │  │
│  │  state.currentCardIndex — index student is viewing                   │  │
│  │  adaptiveCallInFlight  — dedup guard (boolean)                       │  │
│  └───────────────────┬──────────────────────────────────────────────────┘  │
│                      │                                                      │
│       goToNextCard() ├── (1) NEXT_CARD dispatch (immediate)                │
│                      ├── (2) completeCardAndGetNext() ──────────────────►  │
│                      │        POST /api/v2/sessions/{id}/complete-card      │
│                      │                                                      │
│       REPLACE_UPCOMING_CARD ◄── (async response) ────────────────────────  │
└──────────────────────┼──────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────────────────┐
│                      ADA Backend (FastAPI / Python)                         │
│                                                                             │
│  POST /api/v2/sessions/{id}/complete-card   (adaptive_router.py)           │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  1. Save CardInteraction row (persist immediately)                   │  │
│  │  2. Check ceiling (_ADAPTIVE_CARD_CEILING = 20)                      │  │
│  │  3. load_student_history() + load_mastery_store()                    │  │
│  │  4. generate_next_card() — adaptive_engine.py                        │  │
│  │  5. Envelope-preserving cache write                                  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                            │                                               │
│  GET /api/v2/sessions/{id}/cards            (teaching_router.py)           │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  teaching_service.generate_cards()                                   │  │
│  │  ├── parse_sub_sections() → group_by_major_topic()                   │  │
│  │  ├── slice to STARTER_PACK_MAX_SECTIONS = 2                          │  │
│  │  ├── _generate_cards_per_section() — parallel asyncio.gather         │  │
│  │  ├── gap-fill pass → extend + sort by _section_order_key             │  │
│  │  └── VISUAL image fallback (keyword scoring)                         │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                            │                                               │
│              ┌─────────────┴──────────────┐                               │
│              ▼                            ▼                               │
│      ChromaDB (RAG)              PostgreSQL 15                             │
│      (concept text,              (students, teaching_sessions,             │
│       images, latex)              card_interactions, student_mastery)      │
│              │                            │                               │
│              └─────────────┬──────────────┘                               │
│                            ▼                                               │
│                  OpenAI gpt-4o-mini                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Architectural Style and Patterns

### Selected Style: Rolling Adaptive Replace (Event-Driven Prefetch)

The architecture follows a **prefetch-then-replace** pattern:

- Session start produces a **starter pack** — a small, immediately useful set of cards from the first 2 sections only.
- While the student reads card N, the frontend fires a background call to prepare card N+1 adaptively.
- When the student advances to card N+1, the adaptive version is already waiting in the `cards` array. There is zero blocking wait.

### Why Not "All Cards Up Front"
Generating all sections at session start caused two compounding problems: the LLM token budget was exceeded for large concepts, and the adaptive engine had no live signals to work with since no student interaction had occurred yet.

### Why Not "Every Card On Demand"
Blocking the student navigation on a live LLM call introduces 2–5 s latency per card transition, which is pedagogically disruptive. The prefetch model eliminates this entirely.

### Trade-offs

| Decision | Benefit | Cost |
|----------|---------|------|
| Starter pack of 2 sections | Fast session start; adaptive engine has live signals from card 3+ | First 2 sections use historical profile only; less personalised |
| Replace-in-place vs append | Preserves card total; no index drift in the frontend | Requires `currentCardIndex + 1` targeting logic in reducer |
| `adaptiveCallInFlight` guard | Eliminates concurrent LLM calls per session | If two cards are answered very fast, the second interaction is recorded but no adaptive call is made; static card at N+2 may be shown briefly |

---

## 6. Technology Stack

All components align with the existing ADA platform stack.

| Component | Technology | Notes |
|-----------|-----------|-------|
| Backend API | FastAPI 0.128+, Python async | No new dependencies |
| Adaptive LLM | `gpt-4o-mini` via `AsyncOpenAI` | Fast, low-cost for per-card generation |
| DB | PostgreSQL 15 / SQLAlchemy 2.0 async | `card_interactions` table already exists |
| Frontend state | React 19 `useReducer` | Pure reducer addition — no new library |
| Rate limiter | `slowapi` (already in place) | Limits set in `adaptive_router.py` |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-1: Starter Pack Limit at 2 Sections

**Decision:** `STARTER_PACK_MAX_SECTIONS = 2` in `config.py`. Remaining sections are covered by the adaptive loop.

**Options considered:**
- All sections: causes token overrun for large concepts; no live signals available.
- 1 section: too few starter cards; student reaches the adaptive boundary on card 2.
- 2 sections: 2–4 starter cards in typical concepts; student has answered 2–3 MCQs before the adaptive loop engages.

**Chosen:** 2 sections. Can be tuned without code changes.

### ADR-2: Text-Driven Token Budget per Section

**Decision:** Each section LLM call uses `max(budget//2, min(budget, text_len//3))` tokens, where `budget` is the profile-adaptive ceiling (`CARDS_MAX_TOKENS_SLOW/NORMAL/FAST`).

**Rationale:** One output token per three characters of section text is a well-calibrated heuristic for structured JSON card generation. The clamp prevents over-allocation on short sections and under-allocation on dense sections.

### ADR-3: Envelope Preservation in Cache Write

**Decision:** `adaptive_router.complete_card()` reads the full `presentation_text` JSON, updates only the `cards` list inside it, and writes the whole envelope back.

**Rationale:** Without this fix, a page reload after adaptive cards had been appended would find no `cache_version` key in `presentation_text` (because the raw list format has no envelope), triggering full card regeneration and discarding the personalised adaptive cards.

### ADR-4: Cache Version 3

**Decision:** `_CARDS_CACHE_VERSION = 3` as a module-level constant in `generate_cards()`. Any cached session with `cache_version < 3` is silently discarded and regenerated.

**Rationale:** Prompt and logic changes made in prior iterations are invisible to students whose sessions were cached under version 1 or 2. The version bump forces one-time regeneration for those sessions.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LLM latency spike makes adaptive card arrive after student reaches that slot | Medium | Student sees loading spinner for 2–4 s | `adaptiveCallInFlight` guard; loading state is shown only when the student has consumed all prepared cards |
| Token budget miscalculation leaves adaptive card truncated | Low | Incomplete card content | `json_repair` + `_salvage_truncated_json` fallback in `_generate_cards_single()`; 3-retry loop |
| Cache version mismatch after rollback | Low | Students see regenerated cards (correct behaviour, slight extra LLM cost) | Acceptable: cost is one extra card generation per affected session |
| Gap-fill sort uses title-substring match which may misclassify a card | Low | Card appears in wrong curriculum order | Only affects gap-fill minority; next session generates correctly |
| Image keyword scoring assigns a topically irrelevant image | Medium | Wrong illustration on VISUAL card | Score is computed on word overlap; pool exhaustion shares an already-assigned image rather than showing nothing |

---

## Key Decisions Requiring Stakeholder Input

1. **Starter pack section count:** `STARTER_PACK_MAX_SECTIONS = 2` is the current value. Product should confirm whether 2 sections provides enough material before the adaptive loop engages, or whether 3 is needed for longer concepts.
2. **Adaptive ceiling:** `_ADAPTIVE_CARD_CEILING = 20` caps the number of adaptive completions per session. Confirm this is appropriate for the expected concept depth.
3. **Cost model:** Per-card adaptive generation adds one `gpt-4o-mini` call per card answered. For a 15-card session this is approximately 15 additional calls. Product should confirm acceptable cost increase vs baseline.
