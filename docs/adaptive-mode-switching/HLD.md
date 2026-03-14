# High-Level Design: Adaptive Mode Switching

## Revision History
| Date | Author | Change |
|------|--------|--------|
| 2026-03-14 | solution-architect | Initial HLD |

---

## 1. Executive Summary

**Feature name:** Adaptive Mode Switching (RC-1 through RC-6 + image distribution + per-section interests)

**Purpose:** Eight targeted quality fixes to the adaptive card generation pipeline. The current system has a critical prompt bug where all three delivery-mode instruction blocks (STRUGGLING / NORMAL / FAST) are appended unconditionally to every system prompt, causing the LLM to produce inconsistent, averaged-out delivery style regardless of the student's actual profile. Additional fixes address TRY_IT section fragmentation, new-student mode conservatism, wrong-answer recovery injection, image clustering, and interest/style customization accessibility.

**Business problem:** Students receive cards that ignore their learning profile because mode-selection is broken at the prompt level. New students receive inappropriately advanced FAST-mode content. Students who fail twice get no re-explanation before advancing. Images cluster on early cards, leaving visual gaps later.

**Scope — included:**
- RC-1 / RC-1b: Fix 3-way mode block bug in `prompt_builder.py` and `prompts.py`
- RC-2: Pre-merge consecutive TRY_IT sections in `teaching_service.py`
- RC-3: Add visual method hints (dot arrays, number lines) to TRY_IT hint blocks in `prompts.py`
- RC-4: Pass signals on 2nd wrong answer in `CardLearningView.jsx` and `sessions.js`
- RC-5: Conservative mode cap for students with < 5 interactions in `adaptive_engine.py`
- RC-6: Recovery card injection after double-wrong in `adaptive_engine.py` + `adaptive_router.py` + `SessionContext.jsx`
- RC-7: Max 1 image per card with redistribution in `teaching_service.py`
- RC-8: Per-section interests/style panel in CARDS phase; remove from `StudentForm.jsx`

**Scope — excluded:**
- New DB table or column migrations (existing `session.lesson_interests` and `session.style` columns used)
- Changes to the Socratic chat loop
- Changes to spaced-review or mastery threshold logic

---

## 2. Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | LLM prompt contains only the single delivery-mode block matching `generate_as` (STRUGGLING / NORMAL / FAST) | P0 |
| FR-2 | Consecutive TRY_IT sections within the same concept are merged into one combined section before LLM prompt construction | P1 |
| FR-3 | TRY_IT hint blocks include at least one visual method hint (dot arrays or number line ASCII art) | P1 |
| FR-4 | On a student's second wrong MCQ attempt for the same card, `re_explain_card_title` and `wrong_attempts=2` are included in the `/complete-card` request | P0 |
| FR-5 | Students with fewer than 5 total card interactions receive NORMAL delivery mode, never FAST | P1 |
| FR-6 | A double-wrong event triggers parallel generation of both a recovery card (re-explain failed topic) and the next adaptive card; recovery card is inserted at `currentCardIndex+1` | P1 |
| FR-7 | Post-processing enforces max 1 image per card; surplus images redistribute to the next image-less card | P2 |
| FR-8 | "Customize this section" panel (interests + style) is available inside the CARDS phase; interests/style fields are removed from the student creation form | P2 |

---

## 3. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Latency — RC-6 recovery path | Recovery + adaptive cards generated in parallel (`asyncio.gather`); end-to-end added latency ≤ 800ms |
| Prompt token reduction — RC-1 | Removing 2 of 3 mode blocks saves ~350 tokens per adaptive call |
| Mode correctness — RC-5 | 100% of cold-start students (< 5 interactions) receive NORMAL; zero FAST misassignments |
| Error resilience — RC-6 | Recovery card LLM failure is graceful: returns only the adaptive card, no 5xx to client |
| Backward compatibility | All existing `NextCardRequest`/`NextCardResponse` fields remain; new fields are optional with defaults |
| No DB migration required | `session.lesson_interests` and `session.style` columns already exist in `TeachingSession` |
| Observability | Structured log lines emitted for each RC path |

---

## 4. System Context Diagram

```
Student browser
    │
    │  [Wrong answer × 2 on card N]
    ▼
CardLearningView.jsx
    │  goToNextCard({ wrongAttempts: 2,
    │                 reExplainCardTitle: card.title })
    ▼
sessions.js → completeCardAndGetNext(signals)
    │
    ▼
POST /api/v2/sessions/{id}/complete-card
    ├── adaptive_router.py
    │       │
    │       ├── asyncio.gather(
    │       │     generate_next_card(...),       ← RC-1 single mode block
    │       │     generate_recovery_card(...)    ← RC-6 NEW
    │       │   )
    │       │
    │       └── NextCardResponse { card, recovery_card, ... }
    ▼
SessionContext.jsx
    │  dispatch("INSERT_RECOVERY_CARD")          ← RC-6 NEW
    │  inserts recovery_card at index N+1
    │  adaptive card lands at index N+2
    ▼
CardLearningView renders recovery card first, then adaptive card

──────────────────────────────────────────

POST /api/v2/sessions/{id}/cards (batch generation)
    │
    ├── teaching_service._batch_consecutive_try_its()  ← RC-2 NEW
    ├── prompts._MODE_DELIVERY[generate_as]            ← RC-1b single block
    ├── conservative cap (interactions < 5 → NORMAL)  ← RC-5
    └── image post-processing max-1 guard             ← RC-7

──────────────────────────────────────────

LearningPage / CardLearningView (CARDS phase)
    │  "Customize this section" panel
    └── PUT /api/v2/sessions/{id}/interests            ← RC-8 NEW endpoint
```

---

## 5. Architectural Style and Patterns

**Style:** Targeted patch. No new services, no new DB tables.

**Patterns:**
- **Dict-lookup single injection** (RC-1/RC-1b): `_CARD_MODE_DELIVERY: dict[str, str]` — one lookup replaces unconditional triple-block append.
- **Pure pre-processing function** (RC-2): `_batch_consecutive_try_its(sections: list[dict]) -> list[dict]` — stateless, called before prompt construction.
- **Guard clause at profile derivation** (RC-5): Single interaction count check caps `generate_as` before LLM call.
- **Parallel async gather** (RC-6): Recovery and adaptive cards are causally independent; parallel generation minimizes added latency.
- **Post-processing image distributor** (RC-7): Pure function called after JSON parse.

---

## 6. Key Architectural Decisions (ADRs)

### ADR-1: Single-block mode injection (RC-1 / RC-1b)
**Decision:** `_CARD_MODE_DELIVERY` dict with `.get(generate_as, default)` lookup.
**Rationale:** LLMs parse inline conditional instructions poorly when all branches are present. Dict lookup with a default fallback is the minimal, testable change.

### ADR-2: TRY_IT merge as pre-processing (RC-2)
**Decision:** Pre-merge sections before prompt construction.
**Rationale:** LLM receives one coherent section. Card ordering and completeness checks are simpler with merged input.

### ADR-3: Parallel asyncio.gather for RC-6
**Decision:** `asyncio.gather(generate_next_card, generate_recovery_card)`.
**Rationale:** Recovery and next card are fully independent. Parallel generation caps added latency to the slower of the two calls.

### ADR-4: Per-section interests stored in existing session columns
**Decision:** Use existing `TeachingSession.lesson_interests` and `TeachingSession.style` columns (confirmed in `db/models.py:88-89`). No Alembic migration needed.
**Rationale:** Columns already exist. No migration risk.

---

## 7. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| RC-6 recovery card LLM failure | Low | Medium | Graceful: catch exception, log warning, return `recovery_card=null` |
| RC-1 dict key mismatch | Low | High | Default fallback: `.get(generate_as, _CARD_MODE_DELIVERY["NORMAL"])` |
| RC-5 interaction count stale after server restart | Low | Low | Count read from DB `card_interactions` table, not memory |
| RC-8 interests lost on mid-session server restart | Low | Low | Session columns persist in DB — not transient |
