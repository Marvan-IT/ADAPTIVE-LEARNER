---
name: chunk-classification-language design decisions
description: Key design decisions for the chunk classification overhaul, exam gate fix, language propagation, exercise practice mode, and Socratic chat removal
type: project
---

## Chunk Classification & Language Feature — Key Design Decisions (2026-04-01)

### New Chunk Type Taxonomy (6 types)
- `learning_objective` — "Learning Objectives", "Be Prepared" — non-interactive panel, no cards
- `section_review` — "1.1 Introduction to Whole Numbers" — non-interactive panel, no cards
- `teaching` — "Use Addition Notation" — study item, teaching cards
- `exercise` (is_optional=False) — "Practice Makes Perfect", "Everyday Math", "Mixed Practice" — study item, 2–3 MCQ from real problems, required for gate
- `exercise` (is_optional=True) — "Writing Exercises" — study item, optional badge, NOT required for gate
- `exercise_gate` — "Section Exam" (synthetic, never in DB) — always last

**Priority order for `_get_chunk_type()`:**
1. `^\d+\.\d+\s+` → section_review
2. contains "learning objectives" or "be prepared" → learning_objective
3. contains "writing exercises" → exercise (is_optional=True)
4. contains "practice makes perfect", "everyday math", "mixed practice" → exercise
5. `^section \d+` or contains "(exercises)" → section_review
6. else → teaching

**Companion function:** `_is_optional_chunk(heading)` → True only for "Writing Exercises"

### Exam Gate Deduplication Fix
- Bug: gate was appended unconditionally even when one already existed in DB
- Fix: `already_has_gate = any(s.chunk_type == "exercise_gate" for s in summaries)` — only inject if False
- Synthetic gate ID: `uuid5(NAMESPACE_DNS, f"exam_gate:{concept_id}")` — deterministic

### Language Change Propagation
- `PATCH /students/{id}/language` extended: finds active session, calls `_translate_summaries_headings()`, busts card cache (set `cache_version: -1`), resets exam state
- `_translate_summaries_headings()`: single `gpt-4o-mini` call, 10 s timeout, returns original list on any error
- Response extended with `translated_headings: list[str]` and `session_cache_cleared: bool`
- Frontend: `LANGUAGE_CHANGED` reducer replaces heading strings by index, clears `cards`, resets `currentCardIndex`
- `sessionDispatch` wired into `StudentContext` as optional prop from `LearningPage`

### Exercise Practice Mode
- Cards generated via `build_exercise_card_prompt()` in `prompt_builder.py` + `build_exercise_card_system_prompt()` in `prompts.py`
- 2 cards default; 3 cards if chunk text has 3+ distinct problems
- Two wrong answers on exercise MCQ → `generate_exercise_recovery_card()` in `adaptive_engine.py`
- Recovery card: `is_recovery=True`, `question.difficulty="EASY"`, step-by-step numbered walkthrough
- `NextCardRequest` extended with optional `failed_exercise_question: str | None` (max_length=500) and `student_wrong_answer: str | None`
- Branch logic in `next_card()` handler: `exercise` type → exercise path; else → existing teaching path

### Socratic Chat Removal
- `POST /check` and `POST /respond` routes deleted
- `SocraticChat.jsx` deleted; all imports removed
- `beginCheck`, `sendResponse` removed from `sessions.js`
- `CHECK_*`, `SOCRATIC_*` reducer cases removed from `SessionContext`
- Replacement: "Complete" button on last card → `POST /sessions/{id}/chunks/{chunk_id}/complete`

### New Endpoint
- `POST /api/v2/sessions/{session_id}/chunks/{chunk_id}/complete` — DB write only, no LLM, idempotent
- Response: `{chunk_id, next_chunk_id, all_study_complete}`
- `all_study_complete` logic: includes `teaching` + required `exercise` chunks; excludes `is_optional=True`

### Schema Changes (additive, no migration)
- `ChunkSummary.is_optional: bool = False` (new field)
- `NextCardRequest.failed_exercise_question: str | None = None` (new optional field)
- `NextCardRequest.student_wrong_answer: str | None = None` (new optional field)
- `CompleteChunkItemRequest` / `CompleteChunkItemResponse` (new schemas)
- `ChunkListResponse.translated: bool = False` (new field)
- `UpdateLanguageResponse` extended with `translated_headings` and `session_cache_cleared`

### Effort
- 17.5 dev-days total; ~8 calendar days with 2 engineers (1 backend, 1 frontend)
- Stages: 2a Socratic removal (2.25d), 2b Backend main (6.25d), 3 Tests (5.25d), 4 Frontend (3.75d)
- No DB migration required; no new npm packages required
