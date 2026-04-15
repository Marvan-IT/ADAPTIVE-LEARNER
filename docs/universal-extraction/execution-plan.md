# Execution Plan: Universal PDF Extraction Pipeline

**Feature name:** `universal-extraction`
**Date:** 2026-04-13
**Status:** Approved for implementation

---

## 1. Work Breakdown Structure (WBS)

### Phase 0 — Infrastructure (devops-engineer)

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P0-01 | Alembic migration: `chunk_type_locked` | Create `013_add_chunk_type_locked.py`. Add `chunk_type_locked BOOLEAN NOT NULL DEFAULT FALSE` column to `concept_chunks`. Add composite partial index on `(book_slug, chunk_type_locked) WHERE chunk_type_locked = TRUE`. | 0.5d | None |
| P0-02 | Update ORM model | Add `chunk_type_locked = Column(Boolean, nullable=False, server_default="false")` to `ConceptChunk` in `db/models.py`. | 0.25d | P0-01 |
| P0-03 | Test fixtures: nursing MMD sample | Extract first 50 pages of a nursing book MMD (or create a synthetic fixture with the 5 failure patterns: garbled headings, chapter bleed, feature boxes, bad subsections, exercise mismatch). Store at `backend/tests/fixtures/nursing_sample.mmd`. | 1d | None |
| P0-04 | Chunk count baselines | Run `--chunks` pipeline on all 16 existing books. Record chunk counts to `backend/tests/fixtures/chunk_baselines.json`. | 0.5d | None |

**Phase 0 total: 2.25 dev-days**

---

### Phase 1 — Stage 1: TOC Validator + Structure Analyzer (backend-developer)

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P1-01 | `TocEntry` + `BoundaryCandidate` dataclasses | Implement dataclasses in new `extraction/toc_analyzer.py`. No logic yet — just data models and type hints. | 0.25d | None |
| P1-02 | `TocAnalyzer.parse_toc()` | Parse the TOC block from book.mmd. Mathpix emits a TOC as a list of lines before the first chapter. Detection heuristic: lines matching `\d+\.?\d*\s+\w+` within the first 10% of the document. Extract `TocEntry` with `section_id`, `title`, `level`, `char_offset`. | 1d | P1-01 |
| P1-03 | `HeadingCorrector.build_corrections()` | For each `##` and `###` heading in the MMD, compute `difflib.SequenceMatcher` similarity against all `TocEntry.title` values. When best match ≥ 0.80 and is unambiguous (next-best match < 0.65), add `garbled → canonical` to the correction dict. Return `dict[str, str]`. | 1d | P1-02 |
| P1-04 | `BoundaryScanner.scan()` | Walk the entire MMD collecting `BoundaryCandidate` objects for: `heading_h2` (##), `heading_h3` (###), `bold_line` (line matching `\*\*[A-Z][^*]+\*\*\s*$`), `caps_line` (line of ALL CAPS ≥ 3 words), `numbered` (line matching `^\d+\.\s+[A-Z]`). For each candidate, compute `position_in_section` as character offset within its containing section divided by section length. | 1.5d | P1-03 |
| P1-05 | `SignalStats` aggregation + chapter samples | Group `BoundaryCandidate` by `(signal_type, corrected_text)`. Compute `occurrence_count`, `avg_position_in_section`, collect up to 5 `example_texts`. Extract 3 representative chapter bodies (first 800 words of chapters 2, mid, and last-1). Detect chapter boundary formats (unique raw heading texts that precede TOC chapter entries). Return `BoundaryReport`. | 1d | P1-04 |
| P1-06 | Unit tests: Stage 1 | Implement tests U-01 through U-06. Use `nursing_sample.mmd` fixture. Assert "The Mothated Leernes" corrects to "The Motivated Learner". Assert feature box at position 0.42 vs exercise marker at 0.91. | 1d | P0-03, P1-05 |

**Phase 1 total: 5.75 dev-days**

---

### Phase 2 — Stage 2: Book Profiler (backend-developer)

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P2-01 | `BookProfile` Pydantic model | Implement in new `extraction/book_profiler.py`. Define `HeadingLevel`, `SubsectionSignal`, `ExerciseMarker`, `BookProfile` with all fields from DLD Section 2.1. Include `model_validate_json()` and `model_dump_json(indent=2)` usage. | 0.5d | None |
| P2-02 | LLM prompt builder | Implement `build_profiling_prompt(report: BoundaryReport) -> list[dict]`. Format system prompt (schema + rules) and user prompt (TOC + signal stats table + chapter samples) as described in DLD Section 5.2. Keep user prompt under 16,000 tokens. | 1d | P2-01, P1-05 |
| P2-03 | `BookProfiler.profile()` | Call OpenAI `gpt-4o` with JSON mode. Parse response with `BookProfile.model_validate_json()`. Implement 3-retry loop with `asyncio.sleep(2 ** attempt)` back-off. Fall back to `legacy_profile_from_config()` on final failure for known books. | 1d | P2-02 |
| P2-04 | `ProfileCache.load()` / `save()` | `load()`: read `book_profile.json`, validate `profile_version`, check MMD char count drift (> 5% → log WARNING but still return cached profile). `save()`: write JSON, set `mmd_char_count` and `profiled_at`. | 0.5d | P2-01 |
| P2-05 | `legacy_profile_from_config()` | Convert an existing `books.yaml` entry (BookConfig) to a `BookProfile` using the existing hardcoded constants as field values. Used as fallback for known books when LLM fails; also enables proactive profiling of existing books. | 0.5d | P2-01 |
| P2-06 | CLI flags: `--profile`, `--re-profile` | Add `--profile` (Stage 1+2 only, no chunking) and `--re-profile` (delete cache before Stage 2) to `pipeline.py` argument parser. Wire into `run_chunk_pipeline()`. | 0.5d | P2-04 |
| P2-07 | Unit + integration tests: Stage 2 | Implement tests I-01, I-02 using a mock LLM client that returns a pre-crafted `BookProfile` JSON. Test `ProfileCache` load/save round-trip. Test stale cache warning (inject old `profiled_at` timestamp). | 1d | P0-03, P2-03, P2-04 |

**Phase 2 total: 5d dev-days**

---

### Phase 3 — Stage 3: Adaptive Chunking (backend-developer)

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P3-01 | `parse_book_mmd()` signature extension | Add `profile: BookProfile | None = None` parameter. At the top of the function: if `profile is None`, branch immediately to the existing unmodified code path. Add `# profile-driven path below` marker for clarity. | 0.25d | P2-01 |
| P3-02 | Chapter boundary detection (profile-driven) | Replace `_CHAPTER_HEADING = re.compile(r"^#{1,4}\s+(\d+)\s*[|:]\s+", ...)` with `[re.compile(p, re.MULTILINE) for p in profile.chapter_boundary_patterns]`. First match wins. | 0.75d | P3-01 |
| P3-03 | Max sections per chapter (profile-driven) | Replace `_MAX_REAL_SECTION_IN_CHAPTER = 10` with `profile.max_sections_per_chapter`. Also replace `MIN_SECTION_BODY_WORDS = 30` with `profile.min_chunk_words // 4` (a reasonable fraction of the merge threshold). | 0.25d | P3-01 |
| P3-04 | Section ID format generalization | Extend `SECTION_PATTERN` to support formats beyond `X.Y`. When `profile.section_id_format` is provided, compile that regex instead. Fallback: if no `X.Y` pattern matches, use TOC-derived section IDs from `heading_corrections` to assign `concept_id`. | 1d | P3-01, P1-03 |
| P3-05 | Multi-signal subsection boundary detection | Replace the `SUBHEADING_PATTERN` (##-only) lookup with a multi-signal check derived from `profile.subsection_signals`. A heading is a boundary when: (a) signal type appears in `profile.subsection_signals` with `is_boundary=True`, AND (b) it does not match `profile.feature_box_patterns`. | 1.5d | P3-01, P2-01 |
| P3-06 | Feature box absorption | Before the boundary decision, check if a heading matches any pattern in `profile.feature_box_patterns`. If yes, skip it as a boundary candidate (absorbed as body content). Log at DEBUG: `"feature_box absorbed: %r"`. | 0.75d | P3-05 |
| P3-07 | Noise pattern override (profile-driven) | Replace the 15-element `_NOISE_HEADING_PATTERNS` list with compiled patterns from `profile.noise_patterns` when profile is provided. The legacy list remains the default when `profile=None`. | 0.5d | P3-01 |
| P3-08 | Exercise zone detection (position-based) | For each `ExerciseMarker` in `profile.exercise_markers` with `behavior = "zone_section_end"`: check if a heading matches `marker.pattern` AND `position_in_section >= 0.75`. If yes, set `in_exercises_zone = True`. For `"zone_chapter_end"`: trigger once per chapter, at end of last section. | 1.5d | P3-05 |
| P3-09 | Back-matter and boilerplate override | Replace `BACK_MATTER_MARKERS` and `BOILERPLATE_PATTERNS` lookups with `profile.back_matter_markers` and `profile.boilerplate_patterns` when profile is provided. | 0.25d | P3-01 |
| P3-10 | Post-processor: merge tiny chunks | After deduplication, merge any chunk with word count < `profile.min_chunk_words` into the next sibling chunk in the same `concept_id`. If no next sibling, merge with previous sibling. Log DEBUG per merge. | 0.75d | P3-01 |
| P3-11 | Post-processor: split large chunks | After merge step, split any chunk with word count > `profile.max_chunk_words` at the last paragraph boundary (`\n\n`) before the `max_chunk_words` limit. Assign new `order_index` values. Log DEBUG per split. | 0.75d | P3-10 |
| P3-12 | Coverage check | After post-processing, compare the set of `concept_id` values produced against `profile.toc_sections`. For each TOC section ID with no matching `concept_id`, log WARNING: `"coverage_gap: TOC section %s produced zero chunks"`. | 0.5d | P3-11 |
| P3-13 | `graph_builder.py` generalization | Replace `_chapter_num()` and `_section_sort_key()` hardcoded string splits with a safe parser: try `X.Y` format first; fall back to treating the entire suffix after `{slug}_` as the section key and sorting lexicographically. This prevents KeyError for nursing-style concept IDs. | 0.75d | None |
| P3-14 | Unit tests: Stage 3 | Implement tests U-07 through U-13 from DLD Section 9.1. Regression test: all 16 existing books within ±3% chunk count using baselines from P0-04. Nursing fixture integration test: zero coverage gaps for chapters 1–5. | 2d | P0-04, P0-03, P3-12 |

**Phase 3 total: 11.25 dev-days**

---

### Phase 4 — Stage 4 + Exercise Cards (backend-developer)

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P4-01 | `chunk_builder.py`: respect `chunk_type_locked` | In `save_chunk()`, when `existing.chunk_type_locked is True`, skip the `existing.chunk_type = chunk.chunk_type` update. Log DEBUG when skipping. All other fields (text, order_index, embedding) are still updated. | 0.5d | P0-02 |
| P4-02 | Integration test: locked type survives re-run | Unit test U-14 from DLD Section 9.1: insert a chunk with `chunk_type_locked=True`, run `save_chunk()` with a different `chunk_type`, verify DB row unchanged. | 0.5d | P4-01 |
| P4-03 | Remove exercise chunk filter in teaching_service | Remove `c.chunk_type == "teaching"` filter (or extend to include `"exercise"`). Add `"learning_objective"` to the allowed set. Ensure no other downstream filters silently drop exercise chunks. | 0.5d | P0-02 |
| P4-04 | `build_exercise_card_prompt()` in `prompts.py` | New function returning `(system_prompt, user_prompt)` for `PRACTICE` and `GUIDED` card types. System prompt emphasizes: hint-based guidance, never give the answer directly, encourage student to attempt first. Follows same structure as `build_adaptive_prompt()`. | 1d | None |
| P4-05 | Wire exercise prompt into teaching flow | In `teaching_service.py`, detect `chunk.chunk_type == "exercise"` and call `build_exercise_card_prompt()` instead of the standard card prompt. Pass `card_type = "GUIDED"` for STRUGGLING students; `card_type = "PRACTICE"` otherwise. | 0.75d | P4-03, P4-04 |
| P4-06 | `_clean_output_dir()` updated | Add `"book_profile.json"` to the `_preserve` set in `admin_router.py`'s `_clean_output_dir()` function so profile cache survives pipeline artifact cleanup. | 0.25d | None |

**Phase 4 total: 3.5 dev-days**

---

### Phase 5 — Admin UI + Frontend (frontend-developer)

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P5-01 | PATCH endpoint: write `chunk_type_locked` | Modify `admin_router.py` PATCH `/api/admin/chunks/{id}`: when `"chunk_type"` key is in request body, set `chunk.chunk_type_locked = True`. Return `chunk_type_locked` in the response dict. | 0.5d | P0-02 |
| P5-02 | Admin API client update | Update `frontend/src/api/admin.js` `updateChunk()` function to pass `chunk_type` in the request body and read `chunk_type_locked` from the response. | 0.25d | P5-01 |
| P5-03 | Type toggle control in `AdminReviewPage.jsx` | Add a `<select>` dropdown (or segmented control) next to each chunk row for chunk type: `teaching | exercise | learning_objective | lab`. On change, call `updateChunk({ chunk_type: value })`. Display a lock icon when `chunk_type_locked === true`. | 1d | P5-02 |
| P5-04 | i18n strings for type toggle | Add `chunkType.teaching`, `chunkType.exercise`, `chunkType.learning_objective`, `chunkType.lab`, `chunkType.locked` to all 13 locale files. | 0.5d | P5-03 |

**Phase 5 total: 2.25 dev-days**

---

### Phase 6 — Hardening + Documentation (backend-developer + comprehensive-tester)

| ID | Title | Description | Effort | Dependencies |
|----|-------|-------------|--------|--------------|
| P6-01 | Integration test: full pipeline nursing fixture | End-to-end test on nursing sample fixture (no real DB required; use SQLite or mock). Assert chunk counts, coverage gaps, feature box absorption, exercise classification. | 1d | P3-14, P4-02 |
| P6-02 | Regression test suite run | Execute all 16 existing book regression tests against `chunk_baselines.json`. Must all pass within ±3%. | 0.5d | P3-14 |
| P6-03 | Pipeline CLI smoke test | Manually run `--profile` on a real nursing book.mmd (if available). Verify `book_profile.json` produced. Run `--chunks` and verify chunk count vs TOC coverage. | 1d | P2-06, P3-12 |
| P6-04 | Manual validation checklist | Execute the checklist from DLD Section 9.5: verify PATIENT CONVERSATIONS (55 instances) not top-level chunks; verify exercise sections classified correctly. | 0.5d | P6-03 |
| P6-05 | Performance test: Stage 1 on large MMD | Time `BoundaryScanner.scan()` on a 5MB MMD file. Assert < 30s. Profile with `cProfile` if slow. | 0.5d | P1-06 |
| P6-06 | Operator runbook | Document in `docs/universal-extraction/runbook.md`: how to add a new non-math book, how to use `--profile` and `--re-profile`, how to hand-edit `book_profile.json`, when to use `--legacy`. | 0.5d | All Phase 1–5 |

**Phase 6 total: 4d dev-days**

---

## 2. Phased Delivery Plan

### Phase 0 — Foundation (Days 1–2)
Infrastructure prerequisites: Alembic migration, ORM update, test fixtures, baseline chunk counts.

**Goal:** Database is ready; nursing fixture is available; baseline regression snapshot captured.

### Phase 1 — TOC Validator (Days 2–5)
Stage 1 implemented and unit tested. `BoundaryReport` produced from any book.mmd.

**Goal:** Can reliably correct garbled headings and identify all boundary signal types in nursing book.

### Phase 2 — Book Profiler (Days 5–9)
Stage 2 implemented and unit tested. `BookProfile` JSON produced from any book.mmd via one LLM call.

**Goal:** `book_profile.json` for nursing book exists and is human-readable/hand-editable.

### Phase 3 — Adaptive Chunking (Days 9–16)
Stage 3 implemented and regression tested. All 16 existing books pass ±3% chunk count test.

**Goal:** Nursing book produces correct chunks. Feature boxes absorbed. Exercise zones detected. Coverage gaps < 5%.

### Phase 4 — Exercise Cards (Days 16–18)
Exercise chunks surface to students. `chunk_type_locked` respected in pipeline re-runs. Prompt for exercise cards working.

**Goal:** A student starting a session on a nursing concept sees exercise chunks as PRACTICE/GUIDED cards.

### Phase 5 — Admin UI (Days 18–20)
Type toggle in Admin Review Page. `chunk_type_locked` displayed with lock icon.

**Goal:** Admin can reclassify any chunk type with one click; classification survives next pipeline run.

### Phase 6 — Hardening (Days 20–23)
Integration tests, regression suite, manual validation checklist, performance test, operator runbook.

**Goal:** PR is mergeable. All tests green. Operator knows how to onboard a new non-math book.

---

## 3. Dependencies and Critical Path

```
P0-03 ──► P1-06 ──► P3-14 ──► P6-01
P0-04 ──► P3-14 ──► P6-02

P1-01 ──► P1-02 ──► P1-03 ──► P1-04 ──► P1-05 ──► P1-06
                               │
                               └──► P2-07

P2-01 ──► P2-02 ──► P2-03 ──► P2-07
          │
          └──► P2-04 ──► P2-06

P3-01 ──► P3-02 through P3-12 (sequential)
P3-13 (independent — can parallelize with P3-01 through P3-12)
P3-12 ──► P3-14 ──► P6-01

P0-02 ──► P4-01 ──► P4-02
P4-03 ──► P4-05
P4-04 ──► P4-05

P0-02 ──► P5-01 ──► P5-02 ──► P5-03 ──► P5-04
```

**Critical path:** P0-03 → P1-01 → P1-02 → P1-03 → P1-04 → P1-05 → P2-02 → P2-03 → P3-01 → P3-05 → P3-12 → P3-14 → P6-01

**Blocking dependencies on external teams:**
- P0-03 (devops-engineer must produce nursing fixture) blocks P1-06, P2-07, P3-14 — must be completed in Day 1.
- P0-04 (baseline chunk counts) blocks P3-14 regression test — must be completed before Phase 3 ends.

**Tasks that can run in parallel:**
- P3-13 (`graph_builder.py` generalization) can run in parallel with any of P3-01 through P3-12.
- Phase 5 (Admin UI) can run in parallel with Phase 3 and 4, needing only P0-02 (Alembic migration).
- P4-04 (`build_exercise_card_prompt`) can run in parallel with Phase 3.

---

## 4. Definition of Done

### Phase 0 DoD
- [ ] `013_add_chunk_type_locked.py` Alembic migration applies cleanly with `alembic upgrade head`
- [ ] `ConceptChunk.chunk_type_locked` column visible in `\d concept_chunks` in psql
- [ ] `backend/tests/fixtures/nursing_sample.mmd` exists (≥ 3 chapters, ≥ 10,000 words)
- [ ] `backend/tests/fixtures/chunk_baselines.json` contains counts for all 16 books

### Phase 1 DoD
- [ ] `extraction/toc_analyzer.py` exists with `TocAnalyzer`, `HeadingCorrector`, `BoundaryScanner`
- [ ] Unit tests U-01 through U-06 all pass
- [ ] "The Mothated Leernes" correctly maps to "The Motivated Learner" in the test fixture
- [ ] `BoundaryReport` produced for nursing fixture in < 30s

### Phase 2 DoD
- [ ] `extraction/book_profiler.py` exists with `BookProfile`, `BookProfiler`, `ProfileCache`
- [ ] `legacy_profile_from_config()` produces valid `BookProfile` for `prealgebra`
- [ ] Integration test I-02 passes (mock LLM client)
- [ ] `book_profile.json` successfully round-trips through `model_dump_json()` / `model_validate_json()`
- [ ] `--profile` and `--re-profile` CLI flags recognized by `pipeline.py`

### Phase 3 DoD
- [ ] `parse_book_mmd(..., profile=None)` is 100% identical to pre-feature behavior (verified by regression test)
- [ ] All 16 existing book regression tests pass within ±3% chunk count tolerance
- [ ] Nursing fixture integration test I-03 passes (0 coverage gaps, feature boxes not top-level chunks)
- [ ] Unit tests U-07 through U-13 all pass
- [ ] `graph_builder.py` does not raise `KeyError` or `ValueError` for nursing-style concept IDs
- [ ] `ruff` lint passes on all modified files

### Phase 4 DoD
- [ ] `chunk_type_locked=True` chunks retain their `chunk_type` after `build_chunks()` re-run (test U-14)
- [ ] Exercise chunks appear in session chunk list (integration test I-05)
- [ ] `build_exercise_card_prompt()` returns non-empty system and user prompt strings
- [ ] `_clean_output_dir()` preserves `book_profile.json`

### Phase 5 DoD
- [ ] PATCH `/api/admin/chunks/{id}` returns `chunk_type_locked: true` after type change
- [ ] `AdminReviewPage.jsx` shows type dropdown and lock icon per chunk
- [ ] All 13 locale files contain `chunkType.*` keys
- [ ] No hardcoded English strings in the type toggle control

### Phase 6 DoD
- [ ] Integration test P6-01 passes
- [ ] Regression suite P6-02 passes (all 16 books)
- [ ] Stage 1 performance test P6-05 passes (< 30s on 5MB MMD)
- [ ] Manual nursing validation checklist P6-04 signed off
- [ ] Operator runbook exists at `docs/universal-extraction/runbook.md`
- [ ] All tests pass in CI

---

## 5. Rollout Strategy

### Deployment Approach

This is a pipeline-only change (offline batch process). It does not affect the live API or any student-facing endpoint until exercise chunks are surfaced (Phase 4). Deployment is incremental:

1. **Phases 0–2:** Deploy migrations and new profiling code. No student impact.
2. **Phase 3:** Deploy refactored `chunk_parser.py`. Existing books continue to use `profile=None` path (zero impact on live data).
3. **Phase 4 (exercise chunk surface):** This is a behavior change. Gate behind a feature flag in `config.py`:
   ```python
   EXERCISE_CHUNKS_ENABLED: bool = os.getenv("EXERCISE_CHUNKS_ENABLED", "false").lower() == "true"
   ```
   Enable per-environment by setting the env var. Do not enable on production until Phase 6 validation is complete.
4. **Phase 5 (admin UI):** Deploy independently; no student impact.
5. **Phase 6:** After manual validation on nursing book, enable `EXERCISE_CHUNKS_ENABLED=true` on production.

### Rollback Plan

| Rollback target | Action |
|----------------|--------|
| `chunk_parser.py` behavior regression | Set `profile=None` explicitly in `run_chunk_pipeline()` call — legacy path activates immediately |
| Exercise chunk surface regression | Set `EXERCISE_CHUNKS_ENABLED=false` env var; no DB change required |
| `chunk_type_locked` column issue | Drop column with `alembic downgrade -1`; all chunk types revert to pipeline-assigned values |
| `book_profile.json` bad profile | Delete `book_profile.json`; run `--re-profile` to regenerate, or hand-edit JSON |

### Post-Launch Validation Steps

1. Run `--profile` on Clinical Nursing Skills book; review `book_profile.json` in admin console.
2. Run `--chunks` on nursing book; inspect chunk counts and coverage gaps in logs.
3. Admin: review 20 random chunks in `AdminReviewPage`; verify feature box absorption and exercise classification.
4. QA: start a teaching session on a nursing concept; verify exercise chunks appear as PRACTICE cards.
5. Monitor logs for `coverage_gap` warnings; investigate any gap > 2% of TOC sections.

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 0 — Foundation | Alembic migration, ORM, test fixtures, baselines | 2.25 dev-days | devops-engineer |
| Phase 1 — TOC Validator | `toc_analyzer.py`, fuzzy correction, boundary scan, unit tests | 5.75 dev-days | backend-developer |
| Phase 2 — Book Profiler | `book_profiler.py`, `BookProfile` schema, LLM prompt, cache, CLI flags | 5.0 dev-days | backend-developer |
| Phase 3 — Adaptive Chunking | `chunk_parser.py` profile-driven path, post-processor, graph builder fix, regression tests | 11.25 dev-days | backend-developer |
| Phase 4 — Exercise Cards | `chunk_type_locked` in pipeline, exercise prompt, filter removal | 3.5 dev-days | backend-developer |
| Phase 5 — Admin UI | PATCH endpoint extension, type toggle, i18n | 2.25 dev-days | frontend-developer |
| Phase 6 — Hardening | Integration tests, regression suite, performance test, runbook | 4.0 dev-days | comprehensive-tester + backend-developer |
| **Total** | | **34.0 dev-days** | |

**Calendar estimate with 2 parallel engineers (backend + frontend/devops):**
~17–19 calendar days (3.5–4 weeks)

**Critical path items (must not slip):**
- P0-03 (nursing fixture) — blocks Phases 1–3 tests
- P1-05 (BoundaryReport) — blocks Phase 2
- P3-05 (multi-signal boundary) — largest single task; plan for 1-day overrun buffer
- P3-14 (regression suite) — gate before Phase 4 deploy

---

## Key Decisions Requiring Stakeholder Input

1. **Exercise chunk visibility default:** Hidden (`is_hidden=True`) or visible by default on first pipeline run for a new book? Recommend hidden-by-default with admin opt-in.

2. **Existing 16 books:** Should they be run through Stage 1+2 now to proactively generate `book_profile.json`? This enables future improvements but is not strictly required.

3. **Feature flag scope for `EXERCISE_CHUNKS_ENABLED`:** Per-book or platform-wide? A per-book flag requires a new `books.yaml` field; platform-wide is simpler to implement.

4. **LLM profiling model:** `gpt-4o` (recommended for accuracy) or `gpt-4o-mini` (lower cost: ~$0.005 per book vs $0.05)? Recommend testing `gpt-4o-mini` on 2 books and comparing `BookProfile` quality before deciding.

5. **PRACTICE vs GUIDED card type assignment:** Should exercise card type be determined by student mode (STRUGGLING → GUIDED, others → PRACTICE) as specified, or should it always be GUIDED for pedagogical safety? Requires product decision.
