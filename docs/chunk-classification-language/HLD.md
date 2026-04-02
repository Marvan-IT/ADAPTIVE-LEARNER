# High-Level Design — Chunk Classification & Language Feature

**Feature slug:** `chunk-classification-language`
**Date:** 2026-04-01
**Status:** Design — awaiting implementation

---

## 1. Executive Summary

### Feature name and purpose
Five tightly coupled changes that fix the chunk-list classification pipeline, make exercise chunks interactive, propagate language changes correctly, and remove the Socratic chat interface in favour of a direct "Complete" button.

### Business problem
1. `_get_chunk_type()` today produces only three types — `section_review`, `exam_question_source`, and `teaching` — and misclassifies exercise sections as exam-question sources rather than interactive practice items. Students never see interactive practice cards for exercise chunks.
2. The synthetic exam gate is appended unconditionally even when chunks already contain a real gate, risking duplicate gates and an off-by-one completion check.
3. When a student changes their language mid-session, chunk headings remain in the original language, the card cache is not cleared, and exam state is left stale.
4. Exercise chunks (e.g. "Practice Makes Perfect", "Writing Exercises") produce no interactive learning experience today.
5. The Socratic chat (`SocraticChat.jsx`) is unreachable on teaching chunks because the study flow moved to card-based learning; the file is dead UI clutter and should be replaced by an explicit "Complete" button on the last card.

### Stakeholders
- Backend developer: `teaching_router.py`, `teaching_schemas.py`, `adaptive_engine.py`, `prompt_builder.py`
- Frontend developer: `LearningPage.jsx`, `SessionContext.jsx`, `CardLearningView.jsx`, `sessions.js`
- Comprehensive tester: new unit + integration tests for all five changes

### Scope

**In scope:**
- New six-type chunk taxonomy and updated `_get_chunk_type()` / `_is_optional_chunk()` functions
- Exam gate deduplication: exactly one synthetic gate, always last
- Language change propagation: heading translation + cache bust + exam state reset
- Exercise practice mode: 2–3 MCQ cards per exercise chunk from real textbook problems; 2 wrong answers triggers a recovery card with step-by-step walkthrough
- Complete button on last card; `POST /chunks/{id}/complete` API; Socratic chat removal
- Updated `ChunkSummary` schema with `is_optional` field; updated `NextCardRequest` with exercise failure fields

**Explicitly out of scope:**
- Changes to the exam evaluation pipeline (`/exam/start`, `/exam/submit`, `/exam/retry`)
- Alembic migrations (no new DB columns required)
- Translation of card body content (headings only)
- Changes to the ChromaDB-path (legacy) session flow

---

## 2. Functional Requirements

| # | Priority | Requirement |
|---|----------|-------------|
| FR-01 | Must | `_get_chunk_type()` classifies all six types from the taxonomy table below |
| FR-02 | Must | `_is_optional_chunk(heading)` returns `True` only for "Writing Exercises" headings |
| FR-03 | Must | Exactly one `exercise_gate` row appears in `ChunkListResponse`, always at position last |
| FR-04 | Must | No `exercise_gate` is appended when one already exists in the DB chunks |
| FR-05 | Must | `PATCH /students/{id}/language` triggers heading translation for in-flight sessions |
| FR-06 | Must | Language change clears the card generation cache (`presentation_text` JSONB field) |
| FR-07 | Must | Language change resets any in-progress exam state |
| FR-08 | Must | Exercise chunks produce 2–3 MCQ cards drawn from real textbook exercise problems |
| FR-09 | Must | Two wrong answers on an exercise MCQ triggers a recovery card with step-by-step walkthrough |
| FR-10 | Must | `POST /sessions/{id}/chunks/{chunk_id}/complete` marks a chunk complete without requiring a score |
| FR-11 | Must | `CardLearningView` shows a "Complete" button on the last card of each chunk |
| FR-12 | Must | `SocraticChat.jsx` is deleted; all imports referencing it are removed |
| FR-13 | Must | `ChunkSummary` carries an `is_optional` boolean field |
| FR-14 | Must | `NextCardRequest` accepts optional `failed_exercise_question` and `student_wrong_answer` fields |
| FR-15 | Should | Translated headings are obtained via a single batched `gpt-4o-mini` call (not one call per heading) |

---

## 3. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Latency — heading translation | < 3 s for a batch of up to 20 headings (gpt-4o-mini, single call) |
| Latency — exercise card generation | < 15 s (same budget as teaching card generation) |
| Latency — Complete button API call | < 500 ms (DB write only, no LLM) |
| Throughput | No change from existing limits; `_translate_summaries_headings` is called at most once per language-change event |
| Availability | No new external dependencies; all LLM calls use the existing OpenAI client with 30 s timeout + 3-retry back-off |
| Data integrity | Language change must never leave headings and card cache in inconsistent state — translation and cache bust must be atomic within a single request handler |
| Test coverage | All new functions have unit tests; integration tests cover the two-wrong-answer recovery path and the language propagation path |
| Backwards compatibility | `ChunkSummary` schema change is additive (`is_optional` defaults to `False`); `NextCardRequest` change is additive (optional fields) |

---

## 4. System Context Diagram

```
Student browser
      │
      │  PATCH /students/{id}/language
      │  POST  /sessions/{id}/chunks/{chunk_id}/complete
      │  POST  /sessions/{id}/next-card   (extended)
      │  GET   /sessions/{id}/chunks      (updated response)
      ▼
FastAPI (teaching_router.py)
      │
      ├─── PostgreSQL ─── TeachingSession.presentation_text (JSONB cache)
      │                   TeachingSession.chunk_progress (JSONB)
      │                   ConceptChunk rows
      │
      ├─── OpenAI API ─── gpt-4o-mini  (heading translation, exercise card MCQ)
      │                   gpt-4o       (exercise recovery card walkthrough)
      │
      └─── adaptive_engine.py ─── generate_exercise_recovery_card()
           prompt_builder.py  ─── build_exercise_card_prompt()
           prompts.py         ─── build_exercise_card_system_prompt()
                                  build_exercise_recovery_prompt()
```

---

## 5. Architectural Style and Patterns

**Selected style:** Layered monolith with pure-function prompt builders (existing pattern).

All new LLM prompt construction is placed in `prompts.py` (system prompts) and `prompt_builder.py` (user prompts), keeping them pure functions (no I/O). The router orchestrates DB reads, calls pure builders, calls the OpenAI client, then writes results. This matches the established pattern used by the adaptive engine and the teaching service.

**Exercise recovery card** reuses the existing `generate_recovery_card()` pattern in `adaptive_engine.py` — a thin async wrapper around a pure prompt builder + an LLM call with 3-retry back-off.

**Language propagation** follows the same "invalidate cache on write" pattern already used for style switches: the handler updates the student row, then mutates the session's `presentation_text` JSONB to clear cached cards and bump `cache_version`.

**Alternatives considered:**
- Event-driven invalidation (publish language-change event, async consumer clears caches) — rejected; over-engineering for a single-server deployment.
- Per-session heading cache in Redis — rejected; no Redis in the current stack; in-memory translation on demand is sufficient at current scale.

---

## 6. New Chunk Type Taxonomy

| Type | Example headings | Visible to student | Cards generated | Gates exam | `is_optional` |
|------|------------------|--------------------|-----------------|------------|---------------|
| `learning_objective` | "Learning Objectives", "Be Prepared" | Non-interactive panel | No | No | `False` |
| `section_review` | "1.1 Introduction to Whole Numbers" | Non-interactive panel | No | No | `False` |
| `teaching` | "Use Addition Notation", "Identify Multiples" | Study item | Teaching cards | Required | `False` |
| `exercise` | "Practice Makes Perfect", "Everyday Math", "Mixed Practice" | Study item with "Practice" badge | 2–3 MCQ from real problems | Required | `False` |
| `exercise` (optional) | "Writing Exercises" | Study item with "Optional" badge | 2–3 MCQ from real problems | Not required | `True` |
| `exercise_gate` | "Section Exam" (synthetic, never in DB) | Always last in list | — | — | `False` |

**Classification rules (priority order):**
1. Heading matches `^\d+\.\d+\s+` → `section_review`
2. Heading contains any of: "learning objectives", "be prepared" → `learning_objective`
3. Heading contains any of: "practice makes perfect", "everyday math", "mixed practice" → `exercise` (is_optional=False)
4. Heading contains "writing exercises" → `exercise` (is_optional=True)
5. Heading matches `^section\s+\d+` OR contains "(exercises)" → `section_review` (exam source, non-interactive)
6. Everything else → `teaching`

---

## 7. Language Change Flow

```
Student changes language in UI
        │
        ▼
PATCH /students/{id}/language
        │
        ├─ 1. Update Student.preferred_language in DB
        │
        ├─ 2. Find active session for this student (most recent non-completed)
        │       │
        │       ├─ 2a. Load current ChunkSummary list (from DB)
        │       ├─ 2b. Call _translate_summaries_headings(summaries, new_language, client)
        │       │       → single gpt-4o-mini call, batch of all headings
        │       │       → returns list[str] in same order
        │       ├─ 2c. Replace heading strings on in-memory summaries
        │       │
        │       ├─ 2d. Bust card cache: session.presentation_text JSON
        │       │       → set cache["cache_version"] = -1  (forces regeneration)
        │       │       → clear cache["cards"] if present
        │       │
        │       └─ 2e. Reset exam state: clear exam_* fields in session JSONB cache
        │
        ├─ 3. Commit DB transaction
        │
        └─ 4. Return updated StudentResponse + translated_headings list
```

**Frontend response to language change (StudentContext.jsx):**
- Calls `i18n.changeLanguage(newLang)` (already present)
- Dispatches `LANGUAGE_CHANGED` action to SessionContext
- `LANGUAGE_CHANGED` reducer: replaces `chunkList[*].heading` with translated headings, clears `cards`, resets `currentCardIndex` to 0

---

## 8. Socratic Chat Removal Rationale

The Socratic check flow (`/sessions/{id}/check` + `/sessions/{id}/respond`) was the original mastery assessment mechanism. The platform evolved to card-based learning with per-chunk completion, making Socratic chat redundant on teaching chunks. Keeping the file creates:

- Dead UI surface that confuses developers
- Dead API calls (`beginCheck`, `sendResponse`) that inflate the API surface
- Risk that future developers try to "resurrect" the feature without understanding the full context

**Replacement:** A "Complete" button appears on the last card of each chunk. Clicking it calls `POST /sessions/{id}/chunks/{chunk_id}/complete` and advances the chunk list. The endpoint is lightweight (DB write only, no LLM).

**Removed APIs:**
- `POST /api/v2/sessions/{id}/check`
- `POST /api/v2/sessions/{id}/respond`

**Removed frontend:**
- `frontend/src/components/learning/SocraticChat.jsx` (delete)
- Imports of `beginCheck`, `sendResponse` from `sessions.js` (remove)
- `beginCheck`, `sendResponse` exports from `sessions.js` (remove)

---

## 9. Technology Stack

No new dependencies. All changes use the existing stack:

| Component | Technology | Version |
|-----------|-----------|---------|
| API router | FastAPI async | 0.128+ |
| LLM client | AsyncOpenAI | existing |
| Translation model | `gpt-4o-mini` | `OPENAI_MODEL_MINI` constant |
| Recovery card model | `gpt-4o` | `OPENAI_MODEL` constant |
| DB | PostgreSQL 15 / SQLAlchemy async | existing |
| Frontend state | React Context reducer | existing |
| i18n | i18next | existing |

---

## 10. Key Architectural Decisions (ADRs)

### ADR-01: Extend `_get_chunk_type()` with six types rather than a new classifier class
**Decision:** Keep the function, expand the match rules, add `_is_optional_chunk()` as a companion.
**Rationale:** The function is used in exactly three call sites in the router. A class would add indirection without benefit at current scale.
**Trade-off:** Pattern matching in a single function becomes longer; mitigated by documented priority-order comments.

### ADR-02: Translate headings in the language-change handler (synchronous, batched)
**Decision:** One `gpt-4o-mini` call per language change event translating all headings in a single prompt.
**Rationale:** Heading count per concept is typically 5–15; a single call is faster than N calls and avoids per-heading latency stacking. 3 s budget is achievable.
**Trade-off:** If translation fails (LLM timeout), headings remain in original language; cache bust still happens so cards regenerate in the new language. Acceptable graceful degradation.

### ADR-03: Mark exercise recovery via `is_recovery=True` on the `LessonCard` schema
**Decision:** Reuse the existing `is_recovery` field (already on `LessonCard`) for exercise recovery cards.
**Rationale:** The field is already rendered differently in `CardLearningView.jsx`. No schema change needed.

### ADR-04: `POST /chunks/{chunk_id}/complete` requires no score field
**Decision:** Completion endpoint is a pure acknowledgement — the score is tracked separately in `chunk_progress` by `complete-chunk`.
**Rationale:** The "Complete" button on the last card fires after all MCQs are done; scores were already recorded by the `complete-chunk` call. This endpoint is a lightweight bookmark, not a scoring event.

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| `_translate_summaries_headings` times out mid-session | Low | Medium | On LLM error, return headings untranslated; cache bust still proceeds |
| Exam gate deduplication regex misidentifies an existing gate chunk | Low | High | Unit test all six classification paths; add assertion that at most one `exercise_gate` appears in response |
| Exercise MCQ generation returns fewer than 2 questions (sparse chunk text) | Medium | Low | Fallback: if LLM returns < 2 questions, pad with a single generic recall question using chunk heading text |
| Socratic API removal breaks existing sessions that are mid-check | Low | Medium | Remove routes after verifying no active sessions in the Socratic phase (verify via DB query before deploy) |
| `LANGUAGE_CHANGED` reducer clears cards mid-session (student loses progress) | Low | Medium | Reducer only clears `cards` array and resets `currentCardIndex`; `chunk_progress` (server-side) is unaffected — student can reload the chunk they were on |

---

## Key Decisions Requiring Stakeholder Input

1. **Exercise chunk exam gating:** Should optional (`is_optional=True`) exercise chunks ("Writing Exercises") be excluded from the "all study complete" check entirely, or should they appear in the chunk list but not block the exam gate? The current design excludes them from the completion check.

2. **Heading translation fallback language:** If `gpt-4o-mini` returns a translation that looks wrong or truncated, should the system fall back to the original English heading, or show the possibly-wrong translation? Current design: fall back to original.

3. **Socratic endpoint removal timing:** Should `POST /check` and `POST /respond` be removed immediately, or deprecated with a 410 Gone response for one release cycle? Current design: immediate removal.

4. **Complete button placement:** Should "Complete" appear on the last card only, or always be available as an escape hatch on any card after the first? Current design: last card only.
