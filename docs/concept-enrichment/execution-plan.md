# Execution Plan — Concept Enrichment

**Feature slug:** `concept-enrichment`
**Date authored:** 2026-02-26
**Author:** Solution Architect

---

## 1. Work Breakdown Structure (WBS)

### Phase 1 — LaTeX Storage Fix

| ID | Title | Description | Effort | Dependencies | Component |
|---|---|---|---|---|---|
| P1-01 | Add `import json` to `chroma_store.py` | Verify `json` is imported at the top of `chroma_store.py`; add if absent | 0.25 d | — | `chroma_store.py` |
| P1-02 | Add `latex_expressions` to metadata dict | In `store_concept_blocks()`, add `"latex_expressions": json.dumps(block.latex, ensure_ascii=False)` to the metadata dict alongside the existing `latex_count` field | 0.25 d | P1-01 | `chroma_store.py` |
| P1-03 | Add metadata size warning | After building each metadata dict, log a WARNING if `len(metadata["latex_expressions"]) > 8192` using `logging` module | 0.25 d | P1-02 | `chroma_store.py` |
| P1-04 | Update `_get_latex()` in `knowledge_service.py` | Modify `_get_latex()` to extract `latex_expressions` from the ChromaDB metadata dict returned by `get_concept_detail()`'s existing `collection.get()` call. Fall back to `_latex_map` if field is absent or malformed | 0.5 d | P1-02 | `knowledge_service.py` |
| P1-05 | Wire `_get_latex()` into `get_concept_detail()` | Ensure `get_concept_detail()` passes the already-retrieved metadata to `_get_latex()` to avoid a second ChromaDB call | 0.25 d | P1-04 | `knowledge_service.py` |
| P1-06 | Unit tests — `chroma_store.py` | Write `test_store_concept_blocks_persists_latex_expressions`, `test_store_concept_blocks_latex_expressions_round_trips`, `test_store_concept_blocks_empty_latex_stores_empty_array` | 0.5 d | P1-02 | `tests/test_chroma_store.py` |
| P1-07 | Unit tests — `knowledge_service.py` LaTeX read path | Write `test_get_latex_prefers_chromadb_metadata`, `test_get_latex_falls_back_to_latex_map` | 0.5 d | P1-04 | `tests/test_knowledge_service.py` |
| P1-08 | Re-run pipeline for prealgebra book | Execute `python -m src.pipeline --book prealgebra` to populate `latex_expressions` in ChromaDB. Verify with a spot-check `collection.get()` call | 0.25 d | P1-02 | Ops / pipeline |

**Phase 1 total estimate:** 2.75 days

---

### Phase 2 — `vision_annotator.py` New Module

| ID | Title | Description | Effort | Dependencies | Component |
|---|---|---|---|---|---|
| P2-01 | Create `backend/src/images/vision_annotator.py` | Write the full module as specified in DLD Section 1.3: `annotate_image()` function, `SYSTEM_PROMPT`, `_user_prompt()`, cache read/write logic, MIME detection | 1.0 d | — | `vision_annotator.py` |
| P2-02 | Add `VISION_RATE_LIMIT` to `config.py` | Add `VISION_RATE_LIMIT: float = 0.5` constant to `backend/src/config.py` | 0.25 d | — | `config.py` |
| P2-03 | Unit test — DECORATIVE skip | `test_annotate_image_decorative_returns_null_fields`: assert no API call made and result has `None` fields | 0.25 d | P2-01 | `tests/test_vision_annotator.py` |
| P2-04 | Unit test — cache hit | `test_annotate_image_cache_hit_skips_api_call`: pre-seed cache file, assert `llm_client` not called | 0.25 d | P2-01 | `tests/test_vision_annotator.py` |
| P2-05 | Unit test — cache miss and write | `test_annotate_image_cache_miss_calls_api_and_writes_cache`: mock API, assert cache file created with correct content | 0.5 d | P2-01 | `tests/test_vision_annotator.py` |
| P2-06 | Unit test — API error recovery | `test_annotate_image_api_error_returns_null_fields`, `test_annotate_image_malformed_json_returns_null_fields` | 0.5 d | P2-01 | `tests/test_vision_annotator.py` |
| P2-07 | Unit test — no cache dir | `test_annotate_image_no_cache_dir_does_not_write_file`: assert function returns correctly with `cache_dir=None` | 0.25 d | P2-01 | `tests/test_vision_annotator.py` |

**Phase 2 total estimate:** 3.0 days

---

### Phase 3 — `extract_images.py` Integration

| ID | Title | Description | Effort | Dependencies | Component |
|---|---|---|---|---|---|
| P3-01 | Make `extract_and_save_images()` async | Change function signature to `async def extract_and_save_images(book_slug, annotate=True)`. Add `import asyncio`. Update `__main__` block to use `asyncio.run()` | 0.5 d | P2-01, P2-02 | `extract_images.py` |
| P3-02 | Add `_get_concept_meta()` helper | Implement `_get_concept_meta(concept_blocks, concept_id) -> dict` as specified in DLD Section 1.4 | 0.25 d | — | `extract_images.py` |
| P3-03 | Call `annotate_image()` in extraction loop | After `output_path.write_bytes(image_bytes)`, await `annotate_image()` with correct parameters. Add `asyncio.sleep(VISION_RATE_LIMIT)` after each call | 0.5 d | P3-01, P3-02, P2-01 | `extract_images.py` |
| P3-04 | Write `description` and `relevance` to `image_index` | Update `image_index[concept_id].append()` call to include `description` and `relevance` from annotation result | 0.25 d | P3-03 | `extract_images.py` |
| P3-05 | Replace `print()` with `logging` in `extract_images.py` | Convert all `print()` calls in `extract_images.py` to `logger.info()` / `logger.warning()` calls | 0.5 d | — | `extract_images.py` |
| P3-06 | Update `knowledge_service.py` `get_concept_images()` | Add `description` and `relevance` fields to the returned dict per DLD Section 1.2; fix URL to include `self.book_slug` | 0.5 d | — | `knowledge_service.py` |
| P3-07 | Update `ConceptImage` Pydantic schema | Add `description: str | None = None` and `relevance: str | None = None` to `ConceptImage` in `schemas.py` | 0.25 d | — | `schemas.py` |
| P3-08 | Unit test — `knowledge_service` image enrichment | `test_get_concept_images_includes_description_and_relevance`, `test_get_concept_images_handles_missing_annotation_fields` | 0.5 d | P3-06 | `tests/test_knowledge_service.py` |
| P3-09 | Verify `ConceptImage` schema contract | `test_concept_image_schema_accepts_null_description_and_relevance` | 0.25 d | P3-07 | `tests/test_schemas.py` |
| P3-10 | Run `extract_and_save_images` on prealgebra | Execute the updated extractor against the prealgebra PDF. Inspect `image_index.json` for `description`/`relevance` fields. Inspect `vision_cache/` for cache files | 0.5 d | P3-01 to P3-05 | Ops / pipeline |

**Phase 3 total estimate:** 4.0 days

---

### Phase 4 — Static Files, API Integration, and Frontend

| ID | Title | Description | Effort | Dependencies | Component |
|---|---|---|---|---|---|
| P4-01 | Verify `main.py` static files mount | Confirm the existing `/images` mount (`_images_dir = OUTPUT_DIR / "prealgebra" / "images"`) serves images correctly after P3-10. Manual test: `curl http://localhost:8000/images/{concept_id}/{filename}` | 0.25 d | P3-10 | `main.py` |
| P4-02 | Integration test — `GET /api/v1/concepts/{id}` enriched response | Write `test_concept_detail_endpoint_returns_latex_list`, `test_concept_detail_endpoint_returns_annotated_images`, `test_concept_detail_endpoint_tolerates_null_annotations` using FastAPI `TestClient` | 1.0 d | P1-05, P3-06, P3-07 | `tests/test_concept_enrichment_integration.py` |
| P4-03 | Implement image caption rendering in frontend | In whichever component renders `ConceptImage` objects (most likely `CardLearningView`), wrap image in `<figure>`, use `relevance` as `alt` text, render `description` as `<figcaption>` with conditional guard | 1.0 d | P3-07 | `frontend/src/components/learning/CardLearningView.jsx` |
| P4-04 | Apply Tailwind styling to image figure | Add `className` attributes for responsive image sizing, caption typography, spacing — consistent with existing Tailwind utility patterns in the component | 0.5 d | P4-03 | `frontend/src/components/learning/CardLearningView.jsx` |
| P4-05 | Frontend null guard testing | Manually verify that concepts with `description: null` render without caption, without errors, in both dark and light mode | 0.25 d | P4-03 | Frontend / QA |
| P4-06 | Accessibility review | Verify `alt` text (`relevance`) is meaningful for screen readers. Verify `figcaption` is visible and correctly associated with `<figure>`. Check WCAG 2.1 AA compliance | 0.25 d | P4-03 | Frontend / QA |

**Phase 4 total estimate:** 3.25 days

---

### Phase 5 — Hardening and Release

| ID | Title | Description | Effort | Dependencies | Component |
|---|---|---|---|---|---|
| P5-01 | Replace remaining `print()` in pipeline files | Audit `extract_images.py` and any caller in `pipeline.py` for remaining `print()` statements; replace with `logging` | 0.5 d | — | `extract_images.py`, `pipeline.py` |
| P5-02 | Full pipeline re-run on all 16 books | Annotate all books in `BOOK_CODE_MAP`. Monitor log output for error rates. Verify `image_index.json` coverage across books | 1.0 d | P3-10 | Ops / pipeline |
| P5-03 | Performance validation | Time `GET /api/v1/concepts/{concept_id}` for 10 concepts with images. Assert P95 under 200 ms. Use `curl` with `--trace-time` or a simple locust run | 0.5 d | P4-01 | QA |
| P5-04 | Code review | Peer review of all changed files: `chroma_store.py`, `knowledge_service.py`, `vision_annotator.py`, `extract_images.py`, `schemas.py`, `main.py`, `CardLearningView.jsx` | 0.5 d | All previous phases | Team |
| P5-05 | Update `docs/concept-enrichment/` if deviations found | Update HLD/DLD/execution-plan if implementation decisions deviated from design | 0.25 d | P5-04 | Solution Architect |
| P5-06 | Update `.env.example` | Verify `OPENAI_MODEL` and `OPENAI_BASE_URL` are documented in `backend/.env.example`. Add `VISION_RATE_LIMIT` note if operator-configurable | 0.25 d | P2-02 | DevOps |

**Phase 5 total estimate:** 3.0 days

---

## 2. Phased Delivery Plan

### Phase 1 — Foundation: LaTeX Storage Fix (2.75 days)

**Goal:** LaTeX expressions survive the ChromaDB round-trip. The API returns correct `latex: list[str]` sourced from ChromaDB metadata rather than a fallback JSON file.

**Deliverables:**
- Modified `chroma_store.py` storing `latex_expressions`
- Modified `knowledge_service.py` reading `latex_expressions` from metadata
- Unit tests passing for LaTeX storage and retrieval
- Prealgebra ChromaDB re-indexed

**Can be released independently:** Yes. The change is additive; no frontend work required.

---

### Phase 2 — Core Module: Vision Annotator (3.0 days)

**Goal:** `vision_annotator.py` is a working, tested module that can annotate any math image bytes with description and relevance.

**Deliverables:**
- `backend/src/images/vision_annotator.py` created
- `VISION_RATE_LIMIT` constant in `config.py`
- Full unit test coverage for all paths (cache hit, cache miss, errors, DECORATIVE skip)

**Can be released independently:** The module is not yet wired into the pipeline at this phase. Safe to merge to `main` without user-visible effect.

---

### Phase 3 — Integration: Image Index Enrichment (4.0 days)

**Goal:** The extraction pipeline annotates images and writes `description` and `relevance` into `image_index.json`. The API surfaces these fields in `ConceptDetailResponse`.

**Deliverables:**
- Modified `extract_images.py` calling `annotate_image()` in the extraction loop
- Modified `knowledge_service.py` `get_concept_images()` returning annotation fields
- Modified `schemas.py` `ConceptImage` with optional `description` and `relevance`
- Unit tests for `get_concept_images()` enrichment
- Integration test for enriched API response
- Prealgebra `image_index.json` annotated

**Can be released independently:** Yes. Frontend renders images correctly without captions until Phase 4 is merged (new nullable fields are backward compatible with existing frontend image renders).

---

### Phase 4 — Frontend: Image Captions (3.25 days)

**Goal:** Students see textual captions below math images in the learning view. Images have meaningful accessible alt text.

**Deliverables:**
- Modified `CardLearningView.jsx` rendering `<figure>` + `<figcaption>`
- Null guard for images without annotations
- Accessible `alt` text from `relevance`
- Tailwind styling consistent with design system
- WCAG 2.1 AA compliance verified

**Can be released independently:** Yes, after Phase 3 is deployed.

---

### Phase 5 — Hardening and Release (3.0 days)

**Goal:** Production-grade quality across all 16 books, performance validated, code reviewed, logging clean.

**Deliverables:**
- All 16 books annotated in `image_index.json`
- No `print()` statements in modified files
- Performance benchmark passing (P95 < 200 ms for `GET /api/v1/concepts/{id}`)
- Code review completed
- `.env.example` updated

---

## 3. Dependencies and Critical Path

```
P1-01 ──► P1-02 ──► P1-03
                │
                ├──► P1-04 ──► P1-05 ──► [API enriched with LaTeX]
                │
                └──► P1-06, P1-07 (tests)
                └──► P1-08 (re-index pipeline)

P2-01 ──► P2-02 (config constant)
P2-01 ──► P2-03, P2-04, P2-05, P2-06, P2-07 (tests)

P2-01 + P2-02 ──► P3-01 ──► P3-03 ──► P3-04 ──► P3-10 (pipeline run)
P3-02 ──► P3-03
P3-05 ──► P3-10
P3-06 ──► P3-08 (tests)
P3-07 ──► P3-09 (schema test)

P1-05 + P3-06 + P3-07 ──► P4-02 (integration tests)
P3-07 ──► P4-03 ──► P4-04 ──► P4-05 ──► P4-06
P3-10 ──► P4-01 (verify static mount)

[All phases] ──► P5-01 ──► P5-02 ──► P5-03 ──► P5-04 ──► P5-05, P5-06
```

**Critical path (longest chain to production-ready state):**

```
P1-01 → P1-02 → P1-04 → P1-05
                                \
P2-01 → P3-01 → P3-03 → P3-04  \
                                 → P4-02 → P5-04 → P5-02 → P5-03
P3-06 → P3-07 ──────────────────/
```

**Estimated critical path duration:** ~10 working days

**Blocking dependencies on external systems:**
- OpenAI API must be reachable with a valid `OPENAI_API_KEY` for P3-10 (image annotation pipeline run) and P5-02 (full 16-book run).
- PDF files must be present in `backend/data/` for P1-08 and P3-10.

**External team dependencies:** None. All changes are within the backend and frontend of the ADA monorepo.

---

## 4. Definition of Done

### Phase 1 — LaTeX Storage Fix

- [ ] `store_concept_blocks()` metadata dict contains `"latex_expressions"` key for every concept block
- [ ] Value is a valid JSON string (parseable by `json.loads()`)
- [ ] `json.loads(latex_expressions)` equals original `block.latex` list for a sample of 10 concepts
- [ ] `get_concept_detail()` returns `latex` as a populated `list[str]` when concept has LaTeX expressions
- [ ] `get_concept_detail()` returns `latex: []` (not null, not error) for concepts with no LaTeX
- [ ] `_latex_map` fallback tested and working when `latex_expressions` absent
- [ ] All three `chroma_store.py` unit tests pass
- [ ] Both `knowledge_service.py` LaTeX unit tests pass
- [ ] No `print()` statements added (existing ones not yet required to be removed — tracked in P5-01)
- [ ] Code reviewed by one team member

### Phase 2 — Vision Annotator Module

- [ ] `vision_annotator.py` exists at `backend/src/images/vision_annotator.py`
- [ ] `annotate_image()` signature matches DLD specification exactly
- [ ] DECORATIVE images return `{"description": None, "relevance": None}` without API call — verified by test
- [ ] Cache hit path skips API call — verified by test
- [ ] Cache miss path calls API and writes `vision_{md5}.json` — verified by test
- [ ] API error returns `ERROR_RESULT` without raising — verified by test
- [ ] Malformed JSON response returns `ERROR_RESULT` without raising — verified by test
- [ ] `cache_dir=None` does not attempt file I/O — verified by test
- [ ] `VISION_RATE_LIMIT` constant present in `config.py`
- [ ] All 5 unit tests pass (`pytest backend/tests/test_vision_annotator.py`)
- [ ] Code reviewed by one team member

### Phase 3 — Image Index Enrichment

- [ ] `extract_and_save_images()` is `async`; `__main__` uses `asyncio.run()`
- [ ] `--no-annotate` flag works (skips vision calls)
- [ ] Running the extractor on prealgebra produces `image_index.json` with `description` and `relevance` fields on at least 80% of non-DECORATIVE images (20% allowed for API errors)
- [ ] `vision_cache/` directory created with at least one `vision_{md5}.json` file
- [ ] Re-running the extractor immediately after shows 100% cache hit rate (no new API calls)
- [ ] `get_concept_images()` returns dicts with `description` and `relevance` keys
- [ ] `ConceptImage` Pydantic schema accepts `description=None` and `relevance=None` without validation error
- [ ] `GET /api/v1/concepts/{concept_id}` for an annotated concept returns non-null `description` and `relevance`
- [ ] `GET /api/v1/concepts/{concept_id}` for an unannotated concept returns null fields without HTTP error
- [ ] Unit tests for `get_concept_images()` pass
- [ ] Integration tests pass (`pytest backend/tests/test_concept_enrichment_integration.py`)
- [ ] Code reviewed by one team member

### Phase 4 — Frontend Image Captions

- [ ] Images in `CardLearningView` are wrapped in `<figure>` elements
- [ ] `alt` attribute contains `image.relevance` when non-null, otherwise `image.image_type`
- [ ] `<figcaption>` is rendered when `image.description` is non-null
- [ ] `<figcaption>` is absent (not empty string, not `"null"`) when `image.description` is null
- [ ] Caption text is visually distinct from concept body text (different font size / color)
- [ ] Images responsive (`max-w-full`) and centered
- [ ] Dark mode and light mode both render correctly
- [ ] No hardcoded English UI labels (data values `description`/`relevance` are exempt from i18n)
- [ ] WCAG 2.1 AA: images have descriptive alt text; captions are associated with images via `<figure>`
- [ ] Manually verified in Chrome and Firefox

### Phase 5 — Hardening and Release

- [ ] Zero `print()` statements in `extract_images.py` and `vision_annotator.py`
- [ ] All 16 books have `image_index.json` with annotation fields present
- [ ] `GET /api/v1/concepts/{concept_id}` P95 response time < 200 ms under light load
- [ ] All unit and integration tests pass in a clean environment (`pytest backend/tests/`)
- [ ] `backend/.env.example` includes `OPENAI_MODEL` documented
- [ ] Code review sign-off from at least one team member on each modified file
- [ ] No regressions in existing teaching session flow (manual smoke test: start a session, complete a card, verify Socratic check works)

---

## 5. Rollout Strategy

### Deployment Approach

This feature modifies the offline pipeline and two existing API response shapes. There are no database schema changes and no new endpoints.

**Rollout order:**
1. Deploy backend changes (Phases 1–3) to the development environment.
2. Re-run the pipeline for the prealgebra book in development to enrich ChromaDB and `image_index.json`.
3. Verify API responses manually.
4. Deploy frontend changes (Phase 4).
5. Smoke test end-to-end in development.
6. Deploy to production.
7. Re-run the pipeline for all 16 books in production (Phase 5, P5-02).

### Feature Flags

Not required. The API changes are additive (new nullable fields); the frontend renders captions conditionally. There is no binary on/off state to gate.

### Rollback Plan

**Backend rollback:**
- The `chroma_store.py` change adds a field to ChromaDB metadata. Rolling back the code while leaving the enriched ChromaDB in place is safe — the previous code ignores `latex_expressions`. No data migration required.
- The `schemas.py` change adds optional fields. Rolling back is safe — the previous schema simply did not include those fields.
- `vision_annotator.py` can be deleted without affecting any other module until `extract_images.py` is updated.
- If `extract_images.py` is rolled back, `image_index.json` retains any already-written `description`/`relevance` fields — these are ignored by the previous version of `knowledge_service.py`.

**Frontend rollback:**
- Reverting `CardLearningView.jsx` to the previous render restores the original image-only display. Safe at any time.

**Risk summary:** All rollback paths are safe. No breaking changes, no migrations.

### Monitoring and Alerting for Launch

- Watch the `/health` endpoint after API restart to confirm ChromaDB collection count is unchanged.
- Check the backend logs for any `WARNING` messages from `knowledge_service.py` related to `latex_expressions` parse failures — expected count: zero for re-indexed books.
- For the pipeline run (P5-02), monitor log output for `images.vision_annotator` WARNING messages. Acceptable error rate: < 5% of images per book.

### Post-Launch Validation Steps

1. Call `GET /api/v1/concepts/{concept_id}` for 5 concepts in the prealgebra book. Verify `latex` list is non-empty for formula-heavy concepts (e.g., the section on fractions). Verify `images[].description` is a meaningful English sentence.
2. Open the LearningPage in the frontend for a concept with images. Confirm captions render below images.
3. Open the LearningPage for a concept without images. Confirm no errors, no empty caption elements.
4. Inspect `backend/output/prealgebra/vision_cache/` — verify file count matches number of non-DECORATIVE images extracted.
5. Re-run `GET /api/v1/concepts/{concept_id}` 10 times in rapid succession. Confirm P95 < 200 ms.

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|---|---|---|---|
| Phase 1 — LaTeX Storage Fix | `chroma_store.py` metadata update, `knowledge_service.py` read path, unit tests, pipeline re-run | 2.75 days | 1 backend developer |
| Phase 2 — Vision Annotator Module | Create `vision_annotator.py`, add config constant, full unit test suite | 3.0 days | 1 backend developer |
| Phase 3 — Image Index Enrichment | `extract_images.py` async + annotation loop, `knowledge_service.py` + `schemas.py` update, integration tests, pipeline run | 4.0 days | 1 backend developer |
| Phase 4 — Frontend Image Captions | `CardLearningView.jsx` figure/figcaption render, Tailwind styling, null guards, accessibility review | 3.25 days | 1 frontend developer |
| Phase 5 — Hardening and Release | All 16 books annotated, logging audit, performance validation, code review, `.env.example` update | 3.0 days | 1 backend developer + 1 reviewer |
| **Total** | | **~16 days** | **1 backend + 1 frontend + 1 reviewer** |

**Notes:**
- Phases 1 and 2 can run in parallel if two backend developers are available (no shared files).
- Phase 4 (frontend) can start as soon as the `ConceptImage` schema change from Phase 3 (P3-07) is merged — the frontend can work against mock data for `description` and `relevance` before the full pipeline run completes.
- Phase 5 pipeline run (P5-02) across all 16 books is the longest single serial operation (~24,000 images at 0.5 s/image ≈ 3.3 hours of wall-clock time for annotation). This is an operator task, not a development task.
