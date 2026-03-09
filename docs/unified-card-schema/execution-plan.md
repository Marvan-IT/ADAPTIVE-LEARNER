# Execution Plan — Unified Card Schema

**Feature slug:** `unified-card-schema`
**Date:** 2026-03-06
**Status:** Ready for implementation

---

## 1. Work Breakdown Structure (WBS)

Each task is atomic, independently testable, and assigned to a single component.

---

### Phase 1 — Backend: Config, Prompts, Schema

| ID   | Title | Description | Effort | Deps | Component |
|------|-------|-------------|--------|------|-----------|
| P1-1 | Remove `ADAPTIVE_CARD_CEILING` from config | Delete `ADAPTIVE_CARD_CEILING = 20` from `backend/src/config.py`. Remove the constant entirely — no rename, no deprecation comment. | 0.25d | — | `config.py` |
| P1-2 | Update Pydantic schemas | In `teaching_schemas.py`: (a) add `CardMCQ` model with fields `text`, `options`, `correct_index`, `explanation`. (b) Update `LessonCard`: remove `questions: list[CardQuestion]`; replace `quick_check` with `question: CardMCQ | None`; add `options: list[str] | None`. (c) Remove `CardQuestion` model. (d) Set `total_questions: int = 0` default on `CardsResponse`. | 0.5d | P1-1 | `teaching_schemas.py` |
| P1-3 | Rewrite `build_cards_system_prompt()` | Replace the CARD TYPES section (TEACH, EXAMPLE, VISUAL, QUESTION, RECAP, FUN instructions) and OUTPUT FORMAT section with unified schema instructions. Remove `quick_check` and `questions[]` rules. Add `[IMAGE:N]` inline marker instruction. Retain: EXPLANATION RULES block, CARD COUNT RULE (no upper limit), adaptive profile block, interests/style/language blocks. | 1.0d | P1-2 | `prompts.py` |
| P1-4 | Update `build_cards_user_prompt()` image block | Replace Diagram-N image listing with "AVAILABLE IMAGES: Index N: {description} (filename: {filename})" format. Update instruction text to tell the LLM to assign `image_indices` and embed `[IMAGE:N]` markers — remove "image placement is handled automatically" sentence. | 0.5d | P1-3 | `prompts.py` |
| P1-5 | Update `build_mid_session_checkin_card()` | Remove `card_type`, `quick_check`, and `questions` keys from the returned dict. Keep: `title`, `content`, `image_indices: []`, `images: []`, `options`. Do not add `question` key. | 0.25d | P1-2 | `prompts.py` |
| P1-6 | Update remediation prompt | In `teaching_service._build_remediation_prompt()`: replace inline JSON example string with unified schema shape. Replace "Each TEACH card MUST have a quick_check MCQ" instruction with "Every card MUST have a question (MCQ)". Remove `card_type` and `quick_check` from inline schema example. | 0.5d | P1-3 | `teaching_service.py` |

---

### Phase 2 — Backend: Service Post-Processor

| ID   | Title | Description | Effort | Deps | Component |
|------|-------|-------------|--------|------|-----------|
| P2-1 | Remove sub-section soft cap | In `generate_cards()`, delete the `elif len(sub_sections) > 10:` block (lines ~551–556). The LLM now receives all sub-sections. The minimum-4 guard (lines ~549–550) is retained. | 0.25d | — | `teaching_service.py` |
| P2-2 | Remove `ADAPTIVE_CARD_CEILING` import | Remove `ADAPTIVE_CARD_CEILING` from the `from config import (...)` statement at the top of `teaching_service.py`. Confirm no other usage in the file. | 0.25d | P1-1 | `teaching_service.py` |
| P2-3 | Replace image post-processor | In `generate_cards()`, delete the positional-assignment block and round-robin fallback (lines ~729–764). Insert the new index-resolution loop that validates each integer in `card["image_indices"]` against `available_images`, resolves to full image objects, attaches as `card["images"]`, and logs warnings for invalid indices. Do NOT pop `image_indices` from the card. | 1.0d | P1-4 | `teaching_service.py` |
| P2-4 | Replace per-card question normaliser | In `generate_cards()`, delete the `card_type` defaulting, `quick_check` defaulting, QUESTION card special-case, and True/False question ID assignment code. Insert the new unified question validator that checks `isinstance(card.get("question"), dict)`, validates `options` length == 4, clamps `correct_index`, and normalises all string fields. | 0.75d | P1-2 | `teaching_service.py` |
| P2-5 | Update remediation post-processor | In `_post_process_remediation_cards()` (~line 980), remove `card.setdefault("card_type", "TEACH")`, `card.setdefault("quick_check", None)`, and `card.setdefault("questions", [])`. Add the unified question validator (same logic as P2-4). | 0.5d | P2-4 | `teaching_service.py` |
| P2-6 | Update `total_questions` computation | In `generate_cards()`, remove the `total_questions += len(card["questions"])` counter. Set `result["total_questions"] = 0` unconditionally. | 0.25d | P2-4 | `teaching_service.py` |

---

### Phase 3 — Frontend: CardLearningView Simplification

| ID   | Title | Description | Effort | Deps | Component |
|------|-------|-------------|--------|------|-----------|
| P3-1 | Add `parseInlineImages()` utility | Create a pure function (co-located in `CardLearningView.jsx` or extracted to `src/utils/cardUtils.js`) that splits a content string at `[IMAGE:N]` markers (case-insensitive regex) and returns an array of `{type: "text", value}` and `{type: "image", img}` segments. Add corresponding unit tests. | 0.75d | — | `CardLearningView.jsx` |
| P3-2 | Replace content render with inline image render | Replace the `<div className="markdown-content"><ReactMarkdown>` block with the `parseInlineImages()` map that renders text segments as ReactMarkdown and image segments as `<ConceptImage>`. Remove the separate "Card Images (non-VISUAL cards)" block that renders `card.images` as a block after content — images are now inline only. Remove the VISUAL card special-case rendering branch. | 1.0d | P3-1 | `CardLearningView.jsx` |
| P3-3 | Unify question state — remove TF | Remove `tfPool`, `currentTf`, `handleTfAnswer()`, and TF state keys (`tfIdx`, `tfCorrect`, `tfFeedback`) from component state. Update `getCardState()` default object to remove TF keys. Update `updateCardState()` call sites that set TF fields. | 0.75d | — | `CardLearningView.jsx` |
| P3-4 | Unify MCQ path to `card.question` | Change MCQ access from `card.questions.filter(q => q.type === "mcq")` pattern to direct `card.question` access. Rename `QuickCheckBlock` to `MCQBlock` (or update its prop interface in-place). Update prop: `quickCheck.question` → `question.text`. Verify the MCQ interaction loop (wrong → hint → retry) still works with the new prop shape. | 0.75d | P3-3 | `CardLearningView.jsx` |
| P3-5 | Simplify `canProceed` logic | Rewrite `canProceed` useMemo: CHECKIN (detect by `!card.question && Array.isArray(card.options)`) → `cs.checkinDone`; no question → `true`; has question → `cs.mcqCorrect`. Remove the card_type switch-case. | 0.5d | P3-3, P3-4 | `CardLearningView.jsx` |
| P3-6 | Remove CARD_TYPE_META and CardTypeBadge | Remove the `CARD_TYPE_META` lookup table and `CardTypeBadge` component. Remove the `cardType` and `typeMeta` variables in the main component. Remove `CardTypeBadge` from card header render. Remove the `MAX_ADAPTIVE_CARDS = 20` constant. | 0.5d | P3-5 | `CardLearningView.jsx` |
| P3-7 | Fix card counter display | Change card header subtitle from `t("learning.cardProgress", { current, total })` to `t("learning.cardN", { n: currentCardIndex + 1 })`. Add `"cardN": "Card {{n}}"` to all 13 locale JSON files in `frontend/src/locales/`. | 0.5d | — | `CardLearningView.jsx` + locale files |
| P3-8 | Remove `MAX_ADAPTIVE_CARDS` frontend guard | Remove `const MAX_ADAPTIVE_CARDS = 20` and any conditional that used it to gate card generation or display. Confirm no other reference to this constant in the frontend codebase. | 0.25d | P3-6 | `CardLearningView.jsx` |

---

### Phase 4 — Testing

| ID   | Title | Description | Effort | Deps | Component |
|------|-------|-------------|--------|------|-----------|
| P4-1 | Backend unit tests — prompts | Write tests in `backend/tests/test_prompts.py`: (a) unified schema present in system prompt, (b) `card_type` absent from prompt, (c) `quick_check` absent from prompt, (d) image index format "Index N:" in user prompt, (e) checkin card has no `question` key. | 0.75d | P1-3, P1-4, P1-5 | `backend/tests/` |
| P4-2 | Backend unit tests — post-processor | Write tests in `backend/tests/test_teaching_service.py`: (a) valid image_indices resolved correctly, (b) out-of-range index dropped with warning, (c) question with 3 options nullified, (d) correct_index clamped, (e) card with no question passes through without error, (f) `ADAPTIVE_CARD_CEILING` not importable from config. | 1.0d | P2-3, P2-4 | `backend/tests/` |
| P4-3 | Backend integration test — generate_cards | Write a mocked end-to-end test: LLM mock returns 3 unified-schema cards with image_indices; knowledge_service mock returns 2 images; assert response shape, images resolved, no old fields. | 0.75d | P2-3, P2-4, P2-6 | `backend/tests/` |
| P4-4 | Frontend unit tests — parseInlineImages | Write tests for the `parseInlineImages()` utility: valid split, invalid index, case-insensitive match, empty content, no markers. | 0.5d | P3-1 | `frontend/src/` |
| P4-5 | Frontend unit tests — canProceed | Write tests for the simplified `canProceed` logic: CHECKIN returns false until selection, null question returns true, valid MCQ returns false until correct. | 0.5d | P3-5 | `frontend/src/` |

---

### Phase 5 — Pipeline Re-Run

| ID   | Title | Description | Effort | Deps | Component |
|------|-------|-------------|--------|------|-----------|
| P5-1 | Enumerate all 60 Prealgebra sections | Run `python -m src.pipeline --book prealgebra --list-sections` (or equivalent) and document the 60 section IDs. Verify the pipeline configuration in `config.py` is set to process all sections (not just the first 5). | 0.25d | — | `pipeline.py` |
| P5-2 | Smoke test pipeline on 3 sections | Run the pipeline on 3 representative sections (Chapter 1, Chapter 4, Chapter 9) with the new image description format. Confirm ChromaDB entries include correct image metadata. Confirm no pipeline errors. | 0.5d | P5-1, P1-4 | `pipeline.py` |
| P5-3 | Full pipeline run — all 60 sections | Run the pipeline for all 60 Prealgebra sections. Estimated wall-clock time: 15–25 minutes. Log total runtime, sections processed, and any errors. | 0.5d | P5-2 | `pipeline.py` |
| P5-4 | Post-run validation | For 5 randomly sampled sections: call `GET /api/v2/sessions/{id}/cards` on a test session; assert cards have `question` fields, `images` are resolved, no `card_type` field. | 0.5d | P5-3 | `backend/tests/` |

---

## 2. Phased Delivery Plan

### Phase 1 — Foundation (Backend: Config + Prompts + Schema)

**Goal:** All backend contracts (Pydantic models, prompt functions) match the unified schema. No service logic changed yet.

**Tasks:** P1-1, P1-2, P1-3, P1-4, P1-5, P1-6

**Acceptance criteria:**
- `ADAPTIVE_CARD_CEILING` is not importable from `config`
- `build_cards_system_prompt()` contains `"question"` schema and does not contain `"card_type"`, `"quick_check"`, or `"questions"` fields in the JSON spec section
- `build_cards_user_prompt()` produces `"Index N:"` format in the image block
- `build_mid_session_checkin_card()` returns a dict with no `card_type` or `quick_check` keys
- `LessonCard` Pydantic model has `question: CardMCQ | None` and no `questions` or `quick_check` fields
- All Phase 1 unit tests (P4-1 subset) pass

**Duration estimate:** 2.5 engineer-days

---

### Phase 2 — Core Logic (Backend Service Post-Processor)

**Goal:** `generate_cards()` produces correct unified-schema responses. Image resolution works correctly. Old branching logic is gone.

**Tasks:** P2-1, P2-2, P2-3, P2-4, P2-5, P2-6

**Acceptance criteria:**
- `generate_cards()` does not pop `image_indices` from cards
- Cards in the API response have `images[]` populated by index resolution (not round-robin)
- Out-of-range image indices produce a WARNING log and empty `images[]` on the affected card
- Cards have `question` field (dict or None) and no `card_type`, `quick_check`, or `questions` fields
- `total_questions` in response is always 0
- Sub-section soft cap (10) is removed; large sections produce more than 10 cards
- All Phase 2 unit tests (P4-2) and integration test (P4-3) pass

**Duration estimate:** 3.0 engineer-days

---

### Phase 3 — Frontend Simplification

**Goal:** `CardLearningView.jsx` works correctly with the new schema. TF question path removed. Inline image rendering works. Card counter fixed.

**Tasks:** P3-1, P3-2, P3-3, P3-4, P3-5, P3-6, P3-7, P3-8

**Acceptance criteria:**
- `card.content` with `[IMAGE:0]` renders a `<ConceptImage>` inline at that position
- `card.content` with no markers renders as a single ReactMarkdown block (no regression)
- MCQ answer flow: wrong → assistant hint → retry; correct → advance enabled
- CHECKIN card renders correctly; any option selection enables Next
- No TF buttons appear anywhere in the session
- Card header shows "Card N" (no total)
- No references to `CARD_TYPE_META`, `CardTypeBadge`, `tfPool`, `quick_check`, `card_type`, or `MAX_ADAPTIVE_CARDS` remain in the codebase
- All Phase 3 frontend unit tests (P4-4, P4-5) pass

**Duration estimate:** 4.0 engineer-days (frontend is the largest change)

---

### Phase 4 — Testing and Hardening

**Goal:** All test coverage written. No regressions in Socratic, adaptive, or remediation flows.

**Tasks:** P4-1, P4-2, P4-3, P4-4, P4-5

**Acceptance criteria:**
- All listed unit tests pass
- Integration test passes with mocked LLM
- Socratic check flow (CHECKING phase) is unaffected — no test regressions
- Adaptive per-card flow (`/complete-card`) is unaffected — the `build_next_card_prompt()` schema in `adaptive/prompt_builder.py` is separately tracked and not modified by this feature

**Duration estimate:** 3.5 engineer-days

---

### Phase 5 — Pipeline Re-Run

**Goal:** ChromaDB populated with all 60 Prealgebra sections; image metadata in correct format for the new prompt.

**Tasks:** P5-1, P5-2, P5-3, P5-4

**Acceptance criteria:**
- Pipeline processes all 60 sections without errors
- 5 sampled post-run card sessions return unified schema with resolved images
- No section produces 0 cards

**Duration estimate:** 1.75 engineer-days

---

## 3. Dependencies and Critical Path

```
P1-1 ──► P1-2 ──► P1-3 ──► P1-4 ──► P2-3
                   │         │
                   ▼         ▼
                  P1-5      P4-1
                   │
                   ▼
                  P1-6 ──► P2-5

P1-2 ──► P2-4 ──► P2-6 ──► P4-3
P1-1 ──► P2-2

P2-1  (independent — can run in parallel with Phase 1)

P3-1 ──► P3-2
P3-3 ──► P3-4 ──► P3-5 ──► P3-6
          P3-5 ──► P3-7 (counter fix independent of MCQ refactor)

P4-2 depends on P2-3 and P2-4
P4-4 depends on P3-1

P5-1 ──► P5-2 ──► P5-3 ──► P5-4
P5-2 depends on P1-4 (image block format must be in place before pipeline smoke test)
```

**Critical path:** P1-1 → P1-2 → P1-3 → P1-4 → P2-3 → P4-3 → P5-2 → P5-3 → P5-4

**Blocking dependencies:**
- Phase 3 (frontend) can start in parallel with Phase 2 once Phase 1 is complete — the Pydantic schema (P1-2) defines the API contract the frontend implements against
- Pipeline re-run (Phase 5) should not run until P1-4 is complete, because the user prompt's image block format is what the LLM uses for image assignment

**External dependencies:**
- OpenAI API availability for pipeline re-run (P5-3)
- PostgreSQL test database availability for integration test (P4-3)

---

## 4. Definition of Done

### Phase 1 DoD
- [ ] `ADAPTIVE_CARD_CEILING` removed from `config.py`; no other file references it
- [ ] `CardQuestion` Pydantic model removed; `CardMCQ` added
- [ ] `LessonCard` has `question: CardMCQ | None` and `options: list[str] | None`; no `questions`, no `quick_check`
- [ ] `build_cards_system_prompt()` produces no `card_type`, `quick_check`, or `questions` instructions
- [ ] `build_cards_user_prompt()` image block uses `Index N:` format and instructs LLM to assign indices
- [ ] `build_mid_session_checkin_card()` returns dict without `card_type`, `quick_check`, `questions`
- [ ] All Phase 1 prompt unit tests pass (P4-1)
- [ ] Code reviewed and approved

### Phase 2 DoD
- [ ] `generate_cards()` does not call `.pop("image_indices")`
- [ ] `generate_cards()` performs index-based image resolution with range validation and warning logs
- [ ] `generate_cards()` performs unified question validation (options count, correct_index clamp)
- [ ] `generate_cards()` sets `total_questions = 0`
- [ ] Sub-section cap `elif len(sub_sections) > 10` is removed
- [ ] `_post_process_remediation_cards()` uses unified question validator
- [ ] `ADAPTIVE_CARD_CEILING` not imported in `teaching_service.py`
- [ ] All Phase 2 unit tests pass (P4-2) and integration test passes (P4-3)
- [ ] Code reviewed and approved

### Phase 3 DoD
- [ ] `parseInlineImages()` utility function exists and is tested
- [ ] Card content renders `<ConceptImage>` inline at `[IMAGE:N]` positions
- [ ] MCQ accesses `card.question.text`, `card.question.options`, `card.question.correct_index`, `card.question.explanation`
- [ ] No True/False handler, state, or render code remains
- [ ] `CARD_TYPE_META`, `CardTypeBadge`, `cardType`, `typeMeta` variables removed
- [ ] `canProceed` uses simplified logic (no card_type switch)
- [ ] Card header subtitle shows "Card N" using `t("learning.cardN", { n: ... })`
- [ ] `learning.cardN` key present in all 13 locale files
- [ ] `MAX_ADAPTIVE_CARDS` constant removed
- [ ] All frontend unit tests pass (P4-4, P4-5)
- [ ] Manual browser test: inline image appears at correct position in card content
- [ ] Code reviewed and approved

### Phase 4 DoD
- [ ] All specified unit tests written and passing (P4-1 through P4-5)
- [ ] No regressions in Socratic check test suite
- [ ] No regressions in adaptive per-card test suite
- [ ] Test run report attached to PR

### Phase 5 DoD
- [ ] Pipeline processes all 60 Prealgebra sections with zero errors
- [ ] Post-run validation: 5 sampled sections return unified-schema cards with images resolved
- [ ] Pipeline runtime documented in run log
- [ ] ChromaDB data committed to `backend/output/` (do not commit — documented in run log only)

---

## 5. Rollout Strategy

### Deployment Approach

**Single-branch PR.** All five phases are implemented together on a feature branch `feature/unified-card-schema`. The change is not behind a feature flag because:
- There is no legacy card endpoint to fall back to (cards are session-scoped and newly generated on each session start)
- Sessions started before the deployment will have cached card JSON in `session.presentation_text`. These sessions will be unaffected unless the student refreshes the page and triggers a re-generation. Re-generation will produce unified-schema cards; the new frontend can handle both the old shape (gracefully, with null question) and the new shape.

### Smoke Test on Single Section (Pre-Merge)

Before merging and before the full pipeline re-run:

1. Start the backend locally with the feature branch
2. Create a new student and session for `PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS`
3. Call `GET /api/v2/sessions/{id}/cards`
4. Assert response:
   - No `card_type` field on any card
   - No `quick_check` or `questions` field on any card
   - At least one card has `question` field populated with 4 options
   - If images are available: at least one card has `images[]` non-empty
   - `total_questions = 0`
5. Load the frontend and navigate to that session
6. Verify: MCQ renders; answering correctly enables Next; no TF buttons visible; card header shows "Card 1" (not "Card 1 of N")
7. If an image is resolved: verify it renders inline within the card body at the `[IMAGE:N]` position

### Full Pipeline Re-Run (Post-Merge, Pre-Production)

Run immediately after merging to main, before the production backend is restarted:

```bash
cd backend
source ../.venv/Scripts/activate
python -m src.pipeline --book prealgebra
```

Monitor output for:
- Section count (expect 60)
- Any ERROR level log lines
- Total runtime

### Rollback Plan

If the deployment produces errors:

1. Revert the backend to the previous commit (`git revert` or re-deploy prior image)
2. The frontend is a SPA; the prior frontend build can be re-served
3. Cached sessions in `session.presentation_text` may contain unified-schema JSON if the new backend ran even briefly. These sessions are isolated to the session that generated them; reverting the backend will cause new sessions to use the old schema again.
4. No database migration was performed — no migration rollback is required.

### Post-Launch Validation

After production deployment:

1. Monitor application logs for `[image-resolve]` WARNING lines — a high frequency indicates LLM index assignment quality issues
2. Monitor for `[card-schema]` WARNING lines — indicates LLM question format regressions
3. Check PostHog `question_answered` events — confirm `question_type: "mcq"` is the only value (no `"true_false"`)
4. Check PostHog `card_viewed` events — confirm no `card_type` field appears in event properties (frontend should stop sending it)
5. After 24 hours, sample 10 recent sessions and visually inspect card quality

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members |
|-------|-----------|-----------------|--------------|
| Phase 1 — Backend: Config + Prompts + Schema | P1-1 through P1-6 | 3.0 engineer-days | 1 backend developer |
| Phase 2 — Backend: Service Post-Processor | P2-1 through P2-6 | 3.0 engineer-days | 1 backend developer |
| Phase 3 — Frontend: CardLearningView | P3-1 through P3-8 | 4.0 engineer-days | 1 frontend developer |
| Phase 4 — Testing | P4-1 through P4-5 | 3.5 engineer-days | 1 tester (can overlap with Phase 3) |
| Phase 5 — Pipeline Re-Run | P5-1 through P5-4 | 1.75 engineer-days | 1 backend developer |
| **Total** | 23 tasks | **~15.25 engineer-days** | 2 engineers + 1 tester |

**Calendar estimate:**
- With 2 engineers (1 backend, 1 frontend) working in parallel from Phase 2 onward, plus 1 tester overlapping from Phase 3:
- Phases 1–2 (backend serial): 3.0 calendar days
- Phase 3 (frontend, parallel with backend Phase 2): completes in ~4.0 days
- Phase 4 (testing, overlapping): completes within the Phase 3 window
- Phase 5 (pipeline): 1.0 calendar day after merge
- **Total wall-clock: approximately 5–6 calendar days**

---

## Key Decisions Requiring Stakeholder Input

1. **`difficulty` field in unified schema:** The DLD does not include `difficulty` in the LLM output schema. The frontend `DifficultyBadge` component and the adaptive blending algorithm both read `card.difficulty`. Decide: (a) add `difficulty` back to the LLM schema (and update the system prompt), or (b) have the backend assign a static default of 3 for all cards until adaptive difficulty is re-integrated.

2. **Pipeline re-run timing relative to deployment:** The pipeline re-run (Phase 5) regenerates ChromaDB content with the new image description format. If the pipeline is run before the backend is deployed, the new image format is in ChromaDB but the old backend still discards `image_indices`. Confirm sequencing: deploy backend first, then re-run pipeline.

3. **Adaptive per-card schema (`/complete-card`):** The `build_next_card_prompt()` function in `adaptive/prompt_builder.py` uses a separate `_NEXT_CARD_JSON_SCHEMA` that still includes `true_false` questions and the old schema structure. This is explicitly out of scope for this feature. Confirm that adaptive per-card generation (on-demand cards via `/complete-card`) will continue to use the old schema until a follow-up feature aligns it. The two schemas will coexist in the session: batch cards (from `/cards`) use unified schema; adaptive next-cards (from `/complete-card`) use the old schema.

4. **Remediation card schema after unification:** Once `_build_remediation_prompt()` is updated (P1-6), the LLM will produce unified-schema remediation cards. The `_post_process_remediation_cards()` update (P2-5) must happen in the same PR. Confirm both changes are in scope for this iteration.
