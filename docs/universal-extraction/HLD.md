# High-Level Design: Universal PDF Extraction Pipeline

**Feature name:** `universal-extraction`
**Date:** 2026-04-13
**Status:** Approved for design — implementation pending

---

## 1. Executive Summary

### Feature / System Name and Purpose

The Universal PDF Extraction Pipeline extends ADA's existing content ingestion system — currently a hardcoded, OpenStax-math-specific parser — to correctly extract, classify, and chunk **any** PDF textbook regardless of publisher, subject domain, or heading convention.

### Business Problem Being Solved

ADA's current `chunk_parser.py` embeds ~60 hardcoded assumptions derived exclusively from 16 OpenStax mathematics textbooks:

- `_MAX_REAL_SECTION_IN_CHAPTER = 10` — fails for nursing books with 20+ subsections per chapter
- 15 fixed `_NOISE_HEADING_PATTERNS` — OpenStax-specific (EXAMPLE, TRY IT, HOW TO, etc.); miss nursing feature boxes entirely
- `EXERCISE_SECTION_MARKERS` in `config.py` — lists "Practice Makes Perfect", "Mixed Practice" — nursing uses "Review Questions", "Competency-Based Assessments"
- `BACK_MATTER_MARKERS` — hardcoded to OpenStax math chapter-review names
- `SECTION_PATTERN` — assumes `X.Y` integer dot integer format; fails for nursing subsections identified by other schemes
- `_CHAPTER_HEADING` regex — assumes `## N | Title`; misses `## Chapter 13: Title` and similar patterns

Expansion to Clinical Nursing Skills, Business, and other domains requires either per-book forks of `chunk_parser.py` (maintenance catastrophe) or a principled, data-driven approach. This feature delivers the latter: a 4-stage pipeline that **learns the structural grammar of any book from its own content** before chunking it.

### Key Stakeholders

- **Platform Engineering** — owns the pipeline; primary implementer
- **Content Operations** — adds new textbooks; currently blocked by manual config edits
- **Teaching Quality** — adversely affected when sections are silently dropped or garbled
- **DevOps Engineer** — deploys pipeline; operates `books.yaml`

### Scope

**In scope:**
- Stage 1: TOC Validator + Structure Analyzer (local, $0 cost, no LLM)
- Stage 2: Book Profiler (LLM one-time call, result cached to disk as `book_profile.json`)
- Stage 3: Adaptive Chunking refactor of `chunk_parser.py` (profile-driven multi-signal boundary detection)
- Stage 4: Feature box handling — kept as inline body content of parent chunk (no new table)
- Exercise detection by **behavioral position** (not by heading name)
- `chunk_type_locked` boolean column on `concept_chunks` — admin overrides survive pipeline re-runs
- Admin UI type toggle in `AdminReviewPage.jsx`
- Exercise chunk cards — new `PRACTICE` and `GUIDED` card types via a separate prompt
- Backward compatibility: `parse_book_mmd()` accepts optional `profile` parameter; `None` = legacy mode for existing 16 books
- `legacy_profile_from_config()` converter creates a `BookProfile` from each `books.yaml` entry (used by existing books that do not need re-profiling)
- Alembic migration for `chunk_type_locked` column

**Out of scope:**
- Cross-publisher multi-format support (non-Mathpix OCR outputs, EPUB, DOCX)
- Automatic prerequisite graph inference via LLM (deferred; current sequential graph builder is sufficient)
- Real-time re-profiling triggered by student feedback
- Frontend pipeline monitoring dashboard (existing `/api/admin/pipeline-status` polling is sufficient)
- Changing the pgvector embedding model or dimensions

---

## 2. Functional Requirements

| # | Priority | Requirement |
|---|----------|-------------|
| FR-01 | Must | For any book.mmd file, the pipeline produces correctly bounded, non-overlapping chunks with < 5% section drop rate. |
| FR-02 | Must | Garbled OCR headings are corrected to their TOC-ground-truth text before chunking, using fuzzy matching. |
| FR-03 | Must | Chapter boundaries are detected regardless of Mathpix heading format (`## N \| Title`, `## Chapter N:`, LaTeX `\chapter{}`, etc.). |
| FR-04 | Must | Feature boxes (PATIENT CONVERSATIONS, REAL RN STORIES, etc.) are kept as inline body content inside their parent teaching chunk, not split into separate chunks. |
| FR-05 | Must | Exercise sections are detected by behavioral position (recurring heading, position > 0.80 in section) — not by matching a fixed list of names. |
| FR-06 | Must | `BookProfile` is derived by LLM one time per book and cached to `output/{slug}/book_profile.json`; re-runs use the cache with $0 additional cost. |
| FR-07 | Must | `parse_book_mmd()` accepts an optional `profile: BookProfile | None` parameter. When `None`, all existing hardcoded logic is used unchanged (backward compatibility for 16 existing books). |
| FR-08 | Must | Admin overrides on `chunk_type` are preserved across pipeline re-runs via the `chunk_type_locked` boolean column on `concept_chunks`. |
| FR-09 | Must | The Admin Review UI exposes a chunk-type toggle control that sets `chunk_type` and `chunk_type_locked = True` in a single PATCH call. |
| FR-10 | Must | Exercise chunks are surfaced to students as `PRACTICE` and `GUIDED` card types (prompt variant in `prompts.py`), not silently filtered. |
| FR-11 | Should | Post-processing merges chunks < 80 words into adjacent sibling chunks in the same section; splits chunks > 2000 words at paragraph boundaries. |
| FR-12 | Should | Coverage check after chunking logs a warning for any TOC section that produced zero chunks. |
| FR-13 | Could | `graph_builder.py` falls back to slug-based concept IDs when section IDs do not conform to `{int}.{int}` format. |

---

## 3. Non-Functional Requirements

| Category | Target |
|----------|--------|
| **Cost** | Stage 2 LLM call ≤ $0.05 per new book (one-time). Re-runs are free (cached). |
| **Latency** | Stage 1 (TOC analysis + boundary scan): ≤ 30s for any 1000-page book. Stage 2 (LLM profiling): ≤ 60s round-trip. Stage 3+4 (chunking + embedding): matches existing pipeline throughput. |
| **Accuracy** | Section drop rate ≤ 5% on any textbook verified against TOC. Feature box isolation accuracy ≥ 95% (measured on Clinical Nursing Skills ground truth). |
| **Backward compatibility** | All 16 existing OpenStax math books produce chunk counts within ±3% of pre-feature counts when processed with `profile=None`. |
| **Idempotency** | Re-running the pipeline on an already-chunked book updates chunks in place; admin-locked `chunk_type` values are never overwritten. |
| **Observability** | Every boundary decision is logged at DEBUG level with: `signal_type`, `heading_text`, `position_in_section`, `classified_as`. |
| **Testability** | Stage 1 and Stage 3 are pure functions (no I/O, no LLM). Stage 2 is injectable (accepts a mock LLM client). |
| **Maintainability** | `BookProfile` is a Pydantic model stored as JSON; an operator can hand-edit `book_profile.json` to override any LLM decision without code changes. |

---

## 4. System Context Diagram

```
                         ┌─────────────────────┐
                         │  book.mmd            │
                         │  (Mathpix output)    │
                         └────────┬────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │  Stage 1                    │
                    │  TOC Validator +            │
                    │  Structure Analyzer         │
                    │  (local, zero cost)         │
                    │                             │
                    │  • Parse TOC → ground truth │
                    │  • Fuzzy-match garbled hdrs │
                    │  • Detect chapter boundaries│
                    │  • Extract boundary signals │
                    │    (##, ###, bold, CAPS,    │
                    │     numbered) + frequencies │
                    └─────────────┬──────────────┘
                                  │ BoundaryReport
                    ┌─────────────▼──────────────┐
                    │  Stage 2                    │
                    │  Book Profiler              │
                    │  (LLM one-time, cached)     │
                    │                             │
                    │  Input: TOC + signals +     │
                    │         3 chapter samples   │
                    │  Output: BookProfile JSON   │
                    │  Cache: book_profile.json   │
                    └─────────────┬──────────────┘
                                  │ BookProfile
                    ┌─────────────▼──────────────┐
                    │  Stage 3                    │
                    │  Adaptive Chunking          │
                    │  (refactored chunk_parser)  │
                    │                             │
                    │  • Multi-signal boundaries  │
                    │  • Feature boxes → inline   │
                    │  • Exercise zone detection  │
                    │  • Merge/split post-proc    │
                    │  • Coverage check           │
                    └─────────────┬──────────────┘
                                  │ list[ParsedChunk]
                    ┌─────────────▼──────────────┐
                    │  Stage 4                    │
                    │  Embedding & Persistence    │
                    │  (existing chunk_builder)   │
                    │                             │
                    │  • Embed via OpenAI         │
                    │  • Upsert concept_chunks    │
                    │    (respects locked types)  │
                    │  • Save ChunkImage rows     │
                    └─────────────┬──────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │  PostgreSQL + pgvector      │
                    │  concept_chunks table       │
                    │  (chunk_type_locked col)    │
                    └────────────────────────────┘

External actors:
  Operator         →  drops book.mmd into output/{slug}/
  LLM (gpt-4o)     →  Stage 2 one-time call
  Admin UI         →  PATCH /api/admin/chunks/{id} (type toggle)
  Teaching Engine  →  reads concept_chunks + PRACTICE/GUIDED card types
```

---

## 5. Architectural Style and Patterns

**Selected style: Sequential Pipeline with Data-Driven Configuration**

Each stage is a pure function (or near-pure) that transforms data from the previous stage. Configuration is extracted from the book itself rather than from hardcoded constants. This is a classic ETL pipeline extended with an LLM-powered profiling stage.

**Key patterns:**

| Pattern | Application |
|---------|-------------|
| Strategy Object | `BookProfile` acts as the strategy; `chunk_parser.py` selects parsing behavior from it rather than from module-level constants |
| Null Object | `profile=None` triggers the existing hardcoded path, preserving backward compatibility without if/else sprawl |
| Cache-Aside | `book_profile.json` on disk serves as the cache; Stage 2 only calls the LLM on cache miss |
| Behavioral Detection | Exercise zones classified by `position_in_section > threshold` rather than by exact name matching |
| Fuzzy Correction | TOC ground truth used as a correction dictionary for garbled Mathpix headings (Levenshtein distance) |

**Alternatives considered:**

| Alternative | Rejected because |
|-------------|-----------------|
| Per-book config files (YAML overrides) | Doesn't fix garbled OCR headings; requires manual authoring per book; doesn't scale |
| Full LLM chunking (send entire MMD to LLM) | Context window limit (~200k tokens) too small for 800+ page books; cost $5-15/book; non-deterministic |
| Supervised classifier for heading types | Requires labeled training data we don't have; over-engineered for the observed failure modes |
| Separate `chunk_parser_v2.py` | Creates maintenance fork; existing 16-book tests stop being authoritative |

---

## 6. Technology Stack

All choices are constrained to the existing project stack. No new dependencies required.

| Concern | Technology | Notes |
|---------|-----------|-------|
| Fuzzy heading matching | `difflib.SequenceMatcher` (stdlib) | Already used in `boredom_detector.py`; no new dependency |
| LLM profiling (Stage 2) | OpenAI `gpt-4o` via existing `AsyncOpenAI` client | Same pattern as `teaching_service.py` — 3 retries, 30s timeout |
| BookProfile schema | Pydantic v2 `BaseModel` | Validates LLM JSON output; JSON-serializable for disk cache |
| Pipeline orchestration | Existing `pipeline.py` extended with new `--profile` flag | No new entry points required |
| DB migration | Alembic | `chunk_type_locked` column added via new migration `013_add_chunk_type_locked.py` |
| Admin API | Existing `admin_router.py` PATCH endpoint extended | `chunk_type_locked` written when `chunk_type` is patched |
| Frontend type toggle | Existing `AdminReviewPage.jsx` extended | New toggle control, no new page |
| Exercise card prompts | New function in existing `prompts.py` | `build_exercise_card_prompt()` — same pattern as other prompt builders |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-01: Feature Boxes Are Inline Content, Not Separate Chunks

**Decision:** Feature boxes (PATIENT CONVERSATIONS, REAL RN STORIES, LINK TO LEARNING, etc.) are kept as body text within their parent teaching chunk rather than extracted into separate chunk rows.

**Options considered:**
- A) Extract as separate chunks with `chunk_type = "feature_box"` (rejected)
- B) Keep inline in parent chunk (chosen)

**Rationale:** Feature boxes have 20-150 words — too short to be meaningful teaching units or generate quality cards independently. As inline content they provide contextual richness for LLM card generation and embedding quality. Extracting them would also require a new teaching flow path (the current flow has no concept of feature-box chunks).

**Trade-off:** Feature box content is included in parent chunk embeddings, which may slightly reduce retrieval precision for concept-specific queries. Acceptable given the alternative cost.

---

### ADR-02: Exercise Detection Is Position-Based, Not Name-Based

**Decision:** Exercise zones are detected by measuring the average position of a recurring heading within its section body (`position_in_section > 0.80`), not by matching against a list of known exercise heading names.

**Rationale:** "Review Questions", "Competency-Based Assessments", "Critical Thinking Activities" are domain-specific names that will differ across every new textbook. The behavioral signal (recurring heading that always appears at the end of sections) is domain-invariant.

**Trade-off:** Position-based detection requires seeing the heading in ≥ 2 sections to compute an average. First-occurrence classification defers to LLM confirmation or defaults to `teaching` (safe fallback, correctable via admin toggle).

---

### ADR-03: BookProfile Is Cached and Hand-Editable

**Decision:** `BookProfile` is stored as `output/{slug}/book_profile.json` and read from disk on all subsequent runs. The operator can hand-edit this file to override any LLM decision without code changes.

**Rationale:** LLM profiling costs ~$0.05 and takes 60 seconds. Forcing it on every pipeline run would be unnecessary. The cache also acts as a paper trail — operators can diff `book_profile.json` across runs to see what changed.

**Trade-off:** If the book.mmd changes significantly (e.g. after re-OCR), the cached profile may be stale. The pipeline will log a warning if the MMD character count changes by > 5% and the profile is older than 7 days. Force-refresh via `--re-profile` CLI flag.

---

### ADR-04: Backward Compatibility via `profile=None`

**Decision:** `parse_book_mmd(mmd_path, book_slug, profile=None)` — when `profile` is `None`, all existing hardcoded logic runs unchanged.

**Rationale:** The 16 existing OpenStax math books are well-tested and produce correct output. There is no value in re-profiling them. The `None` path costs zero additional development effort and preserves all existing tests.

**Trade-off:** Two code paths exist in `chunk_parser.py` temporarily. Once confidence in the profile-driven path is established (validated on ≥ 3 non-math books), the legacy path can be removed in a future cleanup PR.

---

### ADR-05: `chunk_type_locked` Protects Admin Overrides

**Decision:** A new boolean column `chunk_type_locked` on `concept_chunks` prevents pipeline re-runs from overwriting manually reviewed chunk type classifications.

**Rationale:** Without this, every pipeline re-run (e.g. when improving the exercise detector) would silently undo admin corrections. The locked flag is set only via the Admin PATCH endpoint, never by the pipeline itself.

**Trade-off:** Locked chunks may be incorrect if the book is substantially re-OCR'd (admin must manually unlock). This is acceptable given the low frequency of full re-OCR events.

---

## 8. Risks and Mitigations

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| LLM misclassifies a common heading type (e.g. CRITICAL THINKING as feature box instead of exercise) | High | Medium | Admin type toggle provides a one-click correction; `chunk_type_locked` prevents regression |
| TOC not present or garbled in book.mmd | Medium | Low | Stage 1 falls back to frequency analysis of heading signals without TOC correction; logs warning |
| Fuzzy match creates wrong heading corrections (false positive) | Medium | Low | Match threshold ≥ 0.80 similarity; correction only applied when single unambiguous TOC match exists |
| `book_profile.json` cache becomes stale after book re-OCR | Low | Medium | Pipeline warns when MMD size drift > 5% and profile age > 7 days; `--re-profile` flag forces LLM refresh |
| Backward compat: profile-driven path produces different chunk counts for existing books | High | Low | Guarded by `profile=None` default; existing books never see the new path unless explicitly re-profiled |
| Exercise card generation quality lower than teaching cards | Medium | Medium | Separate `PRACTICE`/`GUIDED` prompt tuned for guided hints; admin can hide exercise chunks via `is_hidden` |
| Graph builder fails for books without `X.Y` concept IDs | Medium | High (for non-math) | `graph_builder.py` generalized to use slug-based fallback IDs and sequential ordering by `order_index` |

---

## Key Decisions Requiring Stakeholder Input

1. **Which non-math books should be validated first?** The design assumes Clinical Nursing Skills as the primary validation target. Confirm this is the next book to be added.

2. **Exercise chunk visibility default:** Should exercise chunks be visible to students by default (`is_hidden = False`) on first pipeline run, or hidden until an admin explicitly enables them? Recommend hidden-by-default for new books until reviewed.

3. **LLM model for profiling:** `gpt-4o` is specified for Stage 2. If cost is a concern, `gpt-4o-mini` may suffice for profiling since the prompt is structured with explicit JSON schema and the task is classification rather than generation. Needs a test run to validate quality.

4. **Re-profiling trigger policy:** Should the `--re-profile` flag be available only to operators, or should it trigger automatically when MMD drift > 5%? Auto-trigger may cause unexpected LLM spend; recommend operator-triggered only.

5. **Existing 16 books:** Should they be run through Stage 1 + Stage 2 proactively to generate `book_profile.json` files (enabling future improvements), or remain on the legacy path indefinitely until a defect is reported?
