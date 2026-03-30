# Execution Plan — Chunk Card Fixes

**Feature slug:** `chunk-card-fixes`
**Date:** 2026-03-28
**Author:** solution-architect

---

## 1. Work Breakdown Structure

| ID | Title | Description | Effort (days) | Dependencies | Component |
|----|-------|-------------|---------------|--------------|-----------|
| P0-1 | Verify test fixtures | Confirm `conftest.py` has fixtures for `TeachingSession`, `Student`, mock `ChunkKnowledgeService`. Confirm `pytest-asyncio` and `pytest-mock` are in `requirements.txt`. | 0.25 | — | devops-engineer |
| P1-1 | Produce design docs | HLD, DLD, execution-plan in `docs/chunk-card-fixes/` | 0.5 | — | solution-architect |
| P2-1 | Fix 1: raise on empty | After normalization loop in `generate_per_chunk`: raise `ValueError` on empty `cards_data` (parse failure) AND on empty `cards` (post-normalization). Remove silent `cards_data = []` fallback. | 0.25 | P0-1, P1-1 | backend-developer |
| P2-2 | Fix 3: wire build_blended_analytics | Move `student` fetch before `build_blended_analytics` call. Add try/except-wrapped call. Write result back to `session.presentation_text`. Log new `[per-chunk] mode adapted` line. | 0.5 | P2-1 | backend-developer |
| P2-3 | Fix 2A: system prompt rewrite | Replace 9-line system prompt with new prompt including CRITICAL SOURCE RULE, COVERAGE RULE, MERGE RULES, combined-cards STRICT RULES, and `_CARD_MODE_DELIVERY` injection. Add `_CARD_MODE_DELIVERY` to import. | 0.5 | P2-2 | backend-developer |
| P2-4 | Fix 2B: prompt_builder.py additions | Append MCQ explanation length lines and style/interests integration lines to all three `_CARD_MODE_DELIVERY` blocks (STRUGGLING, NORMAL, FAST). | 0.25 | P2-3 | backend-developer |
| P2-5 | Fix 8: exercise chunk path | Add heading pattern detection. Add `get_chunks_for_concept` call (or confirm it exists). Build exercise system prompt with 2 MCQ per subsection. Branch before main system prompt. Log exercise chunk detection. | 1.0 | P2-3 | backend-developer |
| P3-1 | Test: raises on empty | `test_generate_per_chunk_raises_on_empty_llm_output` and `test_generate_per_chunk_raises_on_unparseable_json` | 0.25 | P2-1 | comprehensive-tester |
| P3-2 | Test: source rule in prompt | `test_generate_per_chunk_system_prompt_has_source_rule` | 0.25 | P2-3 | comprehensive-tester |
| P3-3 | Test: mode delivery injection | `test_generate_per_chunk_injects_mode_delivery_block` | 0.25 | P2-3, P2-2 | comprehensive-tester |
| P3-4 | Test: session mode written | `test_generate_per_chunk_updates_session_mode` | 0.25 | P2-2 | comprehensive-tester |
| P3-5 | Test: exercise chunk detection | `test_generate_per_chunk_exercise_chunk_detection` | 0.25 | P2-5 | comprehensive-tester |
| P4-1 | Fix 4: CHUNK_ADVANCE guard | Add `if (!(state.nextChunkCards?.cards?.length > 0)) return state;` guard to `CHUNK_ADVANCE` reducer | 0.25 | P1-1 | frontend-developer |
| P4-2 | Fix 4: goToNextChunk rewrite | Rewrite as `async`, add happy-path check, add on-demand fallback with `generateChunkCards`, dispatch `ERROR` with `t("learning.noCardsError")` on total failure. Update `useCallback` deps. | 0.5 | P4-1 | frontend-developer |
| P4-3 | Fix 5: chunk recovery wiring | Import `generateChunkRecoveryCard`. Add chunk-flow recovery branch before existing CASE A. First fail (wrongAttempts >= 1): call `/chunk-recovery-card`. Second fail (wrongAttempts >= 2): assemble RECAP card locally and advance. | 0.75 | P4-2 | frontend-developer |
| P4-4 | Fix 6: noCardsError locale keys | Add `"noCardsError"` under `"learning"` object in all 13 locale JSON files with translations from DLD. | 0.5 | P1-1 | frontend-developer |

**Total estimated effort: 6.5 engineer-days**

---

## 2. Phased Delivery Plan

### Stage 0 — Infrastructure (devops-engineer)
**Goal:** Ensure test infrastructure is ready for new tests.

Tasks: P0-1

**Acceptance criteria:**
- `backend/tests/conftest.py` provides usable fixtures for `TeachingSession`, `Student`, and a mock or in-memory `ChunkKnowledgeService`.
- `pytest-asyncio` is listed in `requirements.txt`.
- `pytest-mock` is listed in `requirements.txt`.
- `python -m pytest backend/tests/ -v` runs without import errors.

---

### Stage 1 — Design (solution-architect)
**Goal:** Produce all design artifacts before any code is written.

Tasks: P1-1

**Acceptance criteria:**
- `docs/chunk-card-fixes/HLD.md` exists and covers problem statement, fix interaction chain, non-goals.
- `docs/chunk-card-fixes/DLD.md` exists with exact code changes specified for each fix.
- `docs/chunk-card-fixes/execution-plan.md` exists with this WBS, phased plan, DoD, and rollout.

---

### Stage 2 — Backend (backend-developer)
**Goal:** Fix the three root causes in `teaching_service.py` and the prompt improvements in `prompt_builder.py`.

Tasks: P2-1 → P2-2 → P2-3 → P2-4 → P2-5

**Sequencing:**
- P2-1 first (raise on empty is the smallest, safest change — establishes the error signal for Fix 4)
- P2-2 second (mode wiring must precede prompt injection because Fix 2A uses `_generate_as` computed by Fix 3)
- P2-3 after P2-2 (uses `_generate_as` and `_CARD_MODE_DELIVERY`)
- P2-4 after P2-3 (adds to the mode blocks that P2-3 injects)
- P2-5 after P2-3 (branches on `is_exercise_chunk` before the main system prompt; reuses `_CARD_MODE_DELIVERY`)

**Acceptance criteria:**
- `generate_per_chunk` raises `ValueError` when LLM returns unparseable JSON or 0 usable cards.
- System prompt for a teaching chunk contains the string `"CRITICAL SOURCE RULE"`.
- System prompt for a teaching chunk contains `"DELIVERY MODE: STRUGGLING"` when mode is STRUGGLING.
- `session.presentation_text` contains updated `current_mode` after a successful call.
- System prompt for an exercise chunk heading contains `"EXERCISE CHUNK MODE"`.
- Each `_CARD_MODE_DELIVERY` block contains the MCQ explanation length instruction for its mode.
- No existing imports, endpoints, or service methods are deleted.
- `python -m pytest backend/tests/ -v` passes (new tests added in Stage 3 will enforce this).

---

### Stage 3 — Testing (comprehensive-tester)
**Goal:** Add regression tests that pin the four core backend behaviours.

Tasks: P3-1 → P3-2 → P3-3 → P3-4 → P3-5

All tests go into `backend/tests/test_generate_per_chunk.py` (new file) unless the tester judges it better to extend an existing file.

**Acceptance criteria:**
- `test_generate_per_chunk_raises_on_empty_llm_output` passes.
- `test_generate_per_chunk_raises_on_unparseable_json` passes.
- `test_generate_per_chunk_system_prompt_has_source_rule` passes.
- `test_generate_per_chunk_injects_mode_delivery_block` passes (STRUGGLING mode).
- `test_generate_per_chunk_updates_session_mode` passes.
- `test_generate_per_chunk_exercise_chunk_detection` passes.
- All existing tests continue to pass (`python -m pytest backend/tests/ -v`).

---

### Stage 4 — Frontend (frontend-developer)
**Goal:** Fix chunk transition robustness, recovery card routing, and missing i18n keys.

Tasks: P4-1 → P4-2 → P4-3 → P4-4

**Sequencing:**
- P4-1 first (CHUNK_ADVANCE guard is a one-line change; reduces blast radius if P4-2 has an error)
- P4-2 after P4-1 (goToNextChunk rewrite dispatches CHUNK_ADVANCE — guard must exist first)
- P4-3 after P4-2 (recovery card branch in goToNextCard — independent of chunk advance but logically follows)
- P4-4 can run in parallel with P4-1/P4-2/P4-3 (locale files are JSON-only, no logic changes)

**Acceptance criteria:**
- `goToNextChunk` is declared `async`.
- `CHUNK_ADVANCE` reducer returns `state` unchanged when `nextChunkCards?.cards?.length` is 0 or falsy.
- Recovery card is triggered on first MCQ failure in chunk flow (not second).
- `/chunk-recovery-card` endpoint is called instead of `/complete-card` in chunk flow.
- RECAP card object is generated locally on second failure; `question` field is `null`.
- `t("learning.noCardsError")` resolves to a non-empty string in all 13 languages.
- `completeSection` and `regenerateMCQ` imports in `sessions.js` are untouched.
- No `console.log` or `print()` statements added.

---

## 3. Dependencies and Critical Path

```
P0-1 (fixtures)
  └── P1-1 (design docs)
        ├── P2-1 (raise on empty)
        │     └── P2-2 (wire analytics)
        │           └── P2-3 (system prompt)
        │                 ├── P2-4 (prompt_builder additions)
        │                 └── P2-5 (exercise chunk)
        │                       └── P3-5 (test exercise detection)
        │     └── P3-1 (test raise on empty)
        │     └── P3-4 (test session mode)
        │── P2-3 → P3-2 (test source rule)
        │── P2-3 + P2-2 → P3-3 (test mode injection)
        ├── P4-1 (CHUNK_ADVANCE guard)
        │     └── P4-2 (goToNextChunk rewrite)
        │           └── P4-3 (recovery card wiring)
        └── P4-4 (locale keys — parallel)
```

**Critical path:** P0-1 → P1-1 → P2-1 → P2-2 → P2-3 → P2-5 → P3-5

**Blocking external dependencies:**
- Fix 8 (P2-5) requires `ChunkKnowledgeService.get_chunks_for_concept()` to exist. The backend developer must check `backend/src/api/chunk_knowledge_service.py` before starting P2-5. If absent, it must be added (estimated 0.25 additional days — not in WBS because it may already exist).

---

## 4. Definition of Done

### Per-task DoD
- Code reviewed by at least one other engineer.
- No new `print()` or `console.log` debug statements.
- No magic strings: constants and thresholds referenced from `config.py` where applicable.
- All pre-existing tests pass.

### Feature-level DoD
- All 6 WBS stages completed and their acceptance criteria met.
- `python -m pytest backend/tests/ -v` passes with all 6 new tests green.
- Manual verification checklist below passes on `localhost:5173/learn/prealgebra_1.1`.

### Manual verification checklist
1. Navigate to a lesson. Click through all cards in subsection 1 — each card has BOTH an explanation AND an MCQ question. No content-only cards.
2. All card content can be traced to the textbook chunk text; no invented examples.
3. Click "Next Section" — subsection 2 cards load within 1 s (pre-fetched) or a spinner appears and cards load within 15 s (fallback).
4. Repeat through all sections — no blank screen, no "Could not load" raw key string.
5. With browser DevTools open, disconnect the network between the second-to-last card and clicking "Next Section". Reconnect. Click "Next Section" — spinner appears, cards load.
6. Fail one MCQ intentionally (wrong answer on first attempt) — a recovery card appears immediately.
7. Fail the recovery MCQ — a RECAP card appears showing the key rule. Clicking Next advances normally.
8. Navigate to a "Section Exercises" chunk — cards are MCQ-only with real textbook difficulty. Two cards per teaching subsection.
9. Set student language to Arabic — `learning.noCardsError` on a forced error shows Arabic text, not the raw key string.
10. Check backend logs — `[per-chunk] mode adapted` log line appears with correct mode for students who answered many MCQs wrong.

---

## 5. Rollout Strategy

### Deployment approach
This is a pure logic and prompt fix with no schema changes. No blue/green or canary deployment is required.

- **Backend:** Changes to `teaching_service.py` and `prompt_builder.py` are picked up by `uvicorn --reload` automatically. No manual restart required.
- **Frontend:** Changes to `SessionContext.jsx` and locale JSON files are picked up by Vite HMR automatically. No manual restart required.

### Rollback plan
All changes are in Python service/prompt code and JSX/JSON frontend files. Git revert of the feature branch restores the previous state within seconds. No DB migration to revert.

### Monitoring at launch
Watch for:
- Reduction in `[per-chunk] JSON parse failed` log lines (Fix 1 converts these to ValueError → HTTP 500 → frontend retries)
- Appearance of `[per-chunk] mode adapted` log lines (confirms Fix 3 is running)
- Absence of `[per-chunk] generated: ... cards=0` log lines (Fix 1 should eliminate these)
- Backend error rate: HTTP 500 on `/chunk-cards` should not increase beyond the pre-fix HTTP 200 `cards=0` rate — they are the same events, now surfaced as errors rather than silent failures

### Post-launch validation (day 1)
- Check that `[per-chunk] mode adapted` appears for at least 80 % of chunk card requests (confirming Fix 3 is live)
- Verify no `learning.noCardsError` raw key strings appear in frontend error reports
- Verify that exercise sections produce cards with `difficulty: "HARD"` (visible in browser devtools network tab response)

---

## 6. Effort Summary

| Stage | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Stage 0 — Infrastructure | Verify test fixtures and deps | 0.25 days | devops-engineer |
| Stage 1 — Design | HLD, DLD, execution-plan | 0.5 days | solution-architect |
| Stage 2 — Backend | Fixes 1, 2A, 2B, 3, 8 in teaching_service.py + prompt_builder.py | 2.5 days | backend-developer |
| Stage 3 — Testing | 6 new tests in test_generate_per_chunk.py | 1.25 days | comprehensive-tester |
| Stage 4 — Frontend | Fix 4 (goToNextChunk), Fix 5 (recovery), Fix 6 (13 locale files) | 2.0 days | frontend-developer |
| **Total** | | **6.5 days** | |

With backend and frontend running in parallel (Stages 2 and 4 can overlap after Stage 1 is complete):
- **Minimum calendar days:** 3 days (Stage 0+1 day 1; Stage 2 + Stage 4 in parallel days 2–3; Stage 3 day 3)
- **Team size:** 1 backend-developer + 1 frontend-developer + 1 tester + devops-engineer for Stage 0
