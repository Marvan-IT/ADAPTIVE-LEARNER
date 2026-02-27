# High-Level Design — Concept Enrichment

**Feature slug:** `concept-enrichment`
**Date authored:** 2026-02-26
**Author:** Solution Architect

---

## 1. Executive Summary

### Feature Name and Purpose

Concept Enrichment adds two data-richness improvements to the ADA pipeline so that every concept surfaced to the adaptive tutor carries the same mathematical fidelity as the original OpenStax textbook:

- **Sub-feature A — LaTeX Storage Fix:** ChromaDB metadata currently stores only the integer count of LaTeX expressions per concept. The actual expressions extracted by Mathpix are discarded at storage time. This fix persists the full expression list as a JSON-encoded string in ChromaDB metadata and restores it on read through `knowledge_service.get_concept_detail()`.

- **Sub-feature B — Image Semantic Annotation:** Extracted FORMULA and DIAGRAM images carry no human-readable description. The teaching LLM therefore has no signal about what an image depicts. A new `vision_annotator.py` module calls GPT-4o Vision to generate a `description` and a `pedagogical_relevance` string for each qualifying image, caches the result to disk, augments `image_index.json` with the annotation fields, and surfaces them through `get_concept_detail()`.

### Business Problem Being Solved

When the teaching service generates explanations and Socratic questions it can currently reference concept text but cannot:
- Inline or reference specific formulas from the textbook (LaTeX is silently absent from context)
- Describe what a diagram or formula image shows (images have no semantic label)

This forces the LLM to hallucinate or omit visual content that is central to mathematics pedagogy. Students miss the visual clarity that a real textbook provides.

### Key Stakeholders

| Role | Interest |
|---|---|
| Learners (students) | Richer, more accurate concept presentations |
| Curriculum designers | Textbook fidelity — all OpenStax content surfaces correctly |
| Backend developers | Clear interfaces and backward-compatible changes |
| Frontend developers | Structured image metadata enabling captioned renders |

### Scope

**Included:**
- `chroma_store.py` — store `latex_expressions` as JSON string in metadata
- `knowledge_service.py` — parse `latex_expressions` from ChromaDB on read; load annotated images from `image_index.json`
- New `backend/src/images/vision_annotator.py` module
- `extract_images.py` — call annotator after each image save; write `description` and `relevance` into `image_index.json`
- `schemas.py` — add `description: str` and `relevance: str` to `ConceptImage`
- `main.py` — static files mount already present; confirm it handles per-book routing
- `frontend/src/pages/LearningPage.jsx` — render image captions using `description` and `relevance`

**Explicitly excluded:**
- Re-running Mathpix OCR (LaTeX is already cached in `mathpix_cache/`)
- Changing the ChromaDB embedding or collection schema (no re-indexing forced)
- Multi-book static file routing (Phase 4 note only; single book in scope)
- Annotation of DECORATIVE images (intentionally skipped)
- New API endpoints (existing `GET /api/v1/concepts/{concept_id}` is enriched in place)

---

## 2. Functional Requirements

| ID | Priority | Requirement |
|---|---|---|
| FR-01 | P0 | `store_concept_blocks()` in `chroma_store.py` must persist `latex_expressions` as `json.dumps(block.latex)` in ChromaDB metadata alongside the existing `latex_count` field. |
| FR-02 | P0 | `get_concept_detail()` in `knowledge_service.py` must return `latex: list[str]` sourced from ChromaDB metadata (parsed from `latex_expressions`), with fallback to `concept_blocks.json` via `_latex_map` if the field is absent (backward compatibility for already-indexed collections). |
| FR-03 | P0 | A new `vision_annotator.py` module must provide `annotate_image(image_bytes, concept_title, image_type, llm_client, model, cache_dir)` returning `{"description": str, "relevance": str}`. |
| FR-04 | P0 | `vision_annotator.py` must skip DECORATIVE images and only process FORMULA and DIAGRAM types. |
| FR-05 | P0 | Vision annotations must be cached to disk using MD5(image_bytes) as the cache key, stored as `vision_{md5}.json` under `cache_dir`. |
| FR-06 | P0 | `extract_and_save_images()` must call `annotate_image()` after each image is saved and write `description` and `relevance` into the corresponding `image_index.json` entry. |
| FR-07 | P1 | `ConceptImage` Pydantic schema must gain optional `description: str` and `relevance: str` fields (nullable, default `None`) so existing data without annotations is still valid. |
| FR-08 | P1 | `LearningPage.jsx` must render image captions below images using `description` when present, and show `relevance` as accessible alt-text or a tooltip. |
| FR-09 | P2 | The pipeline must log annotation progress (images annotated, cache hits, errors) using the Python `logging` module — no `print()` statements. |

---

## 3. Non-Functional Requirements

### Performance
- Vision annotation is a pipeline-time operation (offline, not on the hot API path). Per-image latency of 2–5 seconds from GPT-4o Vision is acceptable.
- Cache hit rate target: 100% for repeated pipeline runs on the same book. MD5-keyed cache guarantees idempotency.
- `GET /api/v1/concepts/{concept_id}` response time must remain under 200 ms (no change — all enrichment is precomputed at pipeline time).

### Scalability
- 16 books x ~500 concepts/book x ~3 images/concept = ~24,000 images maximum annotation load.
- Annotation is embarrassingly parallelisable per-image but will initially run serially to avoid OpenAI rate limits. Rate limiting constant in `config.py`.
- Cache persists across re-runs so re-indexing a book only annotates new or changed images.

### Availability and Reliability
- Vision annotation failures must not abort the pipeline. Each image annotation must be wrapped in try/except; on failure the entry is written with `description: null, relevance: null` and a warning is logged.
- ChromaDB metadata changes are backward compatible: the existing `latex_count` field is retained; `latex_expressions` is additive.

### Security and Compliance
- Image bytes are base64-encoded and sent to the OpenAI API. No student data is included.
- API key handled via `OPENAI_API_KEY` from `config.py` — never hardcoded.

### Maintainability and Observability
- `vision_annotator.py` is a single-responsibility module with no side effects beyond disk I/O.
- All new code uses structured Python `logging` at appropriate levels (DEBUG for cache hits, INFO for annotations, WARNING for failures).
- Cache inspection is trivial: `backend/output/{book_slug}/vision_cache/vision_{md5}.json`.

---

## 4. System Context Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     ADA PIPELINE (offline)                      │
│                                                                 │
│  PDF Files ──► PyMuPDF ──► extract_images.py                   │
│                                    │                            │
│                                    ▼                            │
│                         [image bytes saved]                     │
│                                    │                            │
│                                    ▼                            │
│                         vision_annotator.py ◄── OpenAI GPT-4o  │
│                                    │           Vision API       │
│                                    │                            │
│                                    ▼                            │
│                         image_index.json                        │
│                         (+ description, relevance)              │
│                                    │                            │
│  concept_blocks.json               │                            │
│         │                          │                            │
│         ▼                          │                            │
│  chroma_store.py                   │                            │
│  (latex_expressions stored)        │                            │
│         │                          │                            │
│         ▼                          ▼                            │
│        ChromaDB ◄── knowledge_service.py ──► image_index.json  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ HTTP (runtime)
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI (runtime)                           │
│                                                                 │
│  GET /api/v1/concepts/{id}  ──► ConceptDetailResponse           │
│    - text                         - latex: list[str]            │
│    - latex (enriched)             - images[].description        │
│    - images (annotated)           - images[].relevance          │
│                                                                 │
│  GET /images/{concept_id}/{filename}  ──► StaticFiles mount     │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ Axios
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   React 19 Frontend                             │
│                                                                 │
│  LearningPage.jsx                                               │
│    CardLearningView ──► KaTeX (latex rendering)                 │
│                     ──► <img> + caption (description)           │
│                     ──► alt text (relevance)                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Architectural Style and Patterns

### Selected Style: Pipeline Enrichment + Cached Offline Annotation

The enrichment runs as an augmentation of the existing offline extraction pipeline rather than as a runtime service. This is a **data enrichment at ingestion** pattern: all expensive AI calls happen once at pipeline time; the runtime API serves pre-computed results.

**Justification:**
- GPT-4o Vision calls cost ~2–5 seconds each. Putting this on the hot path of `GET /api/v1/concepts/{id}` would make the endpoint unusable.
- The pipeline already has a similar pattern for Mathpix OCR (rate-limited, cached).
- Caching by MD5(image_bytes) is robust to re-runs and partial failures.

**Alternatives considered:**

| Option | Assessment |
|---|---|
| Runtime vision annotation per API request | Rejected: 2–5 s latency on every concept detail fetch is unacceptable |
| Store annotations in PostgreSQL | Overkill for this use case; `image_index.json` is already the canonical image store and co-location keeps the pipeline self-contained |
| Use a dedicated vision microservice | Over-engineering for current team size and load |

### LaTeX Storage Pattern: Metadata JSON Encoding

ChromaDB metadata values must be scalar types (`str | int | float | bool`). Storing a JSON-encoded string is the standard pattern for embedding structured data in ChromaDB metadata, consistent with how `prerequisites` and `dependents` are already stored as comma-delimited strings.

---

## 6. Technology Stack

All additions use the existing project stack.

| Concern | Technology | Rationale |
|---|---|---|
| Vision annotation | OpenAI GPT-4o (`OPENAI_MODEL`) | Already in stack; best-in-class vision understanding of math diagrams |
| Image encoding | Python `base64` stdlib | No new dependency; standard for OpenAI vision API |
| Cache key | Python `hashlib.md5` stdlib | No new dependency; fast, deterministic |
| Cache storage | JSON files on disk | Consistent with existing pipeline artifact pattern (`mathpix_cache/`) |
| Metadata serialisation | Python `json.dumps` / `json.loads` stdlib | Matches existing pattern in `chroma_store.py` for list fields |
| Frontend image rendering | HTML `<img>` + Tailwind CSS | No new library needed |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-01: Store LaTeX as JSON String in ChromaDB Metadata

**Decision:** Add `latex_expressions: json.dumps(block.latex)` to the ChromaDB metadata dict in `store_concept_blocks()`.

**Options considered:**
1. Continue reading from `concept_blocks.json` at runtime (current workaround in `knowledge_service.py`)
2. Store as JSON string in ChromaDB (chosen)
3. Store as a separate per-concept sidecar file

**Chosen option rationale:** Option 1 requires loading a large JSON file into memory at startup and maintaining a separate in-memory dict. Option 3 adds file proliferation. Option 2 makes ChromaDB the single source of truth for concept data as intended. The `_latex_map` workaround in `knowledge_service.py` was explicitly noted in the code as temporary ("ChromaDB only stores latex_count, not the actual array"). The JSON string pattern is consistent with how `prerequisites` is already stored.

**Trade-offs:**
- ChromaDB metadata has a practical size limit per document (~16 KB total metadata). For concept blocks with hundreds of LaTeX expressions this could be a concern at upper end. Mitigation: log a warning if `len(json.dumps(block.latex)) > 8192`. The `_latex_map` fallback is retained during a transition period.
- Previously indexed collections will not have `latex_expressions`. The read path must fall back to `_latex_map` gracefully (backward compatibility requirement FR-02).

### ADR-02: Use GPT-4o Vision for Image Annotation

**Decision:** Call `gpt-4o` (the primary model constant `OPENAI_MODEL`) with a base64-encoded image and a domain-specific prompt. Do not use `gpt-4o-mini` for this task.

**Options considered:**
1. `gpt-4o` (full vision model)
2. `gpt-4o-mini` (lighter model)
3. Local vision model (e.g., LLaVA)
4. Rule-based description from image metadata (dimensions, type label)

**Chosen option rationale:** Math diagrams and formula images require strong spatial and symbolic reasoning. GPT-4o-mini has weaker vision comprehension for mathematical notation. Local models introduce a new infrastructure dependency. Rule-based descriptions (Option 4) provide no semantic content — "this is a FORMULA image 300x80px" is not useful to the teaching LLM. GPT-4o is already the primary model constant; using it here is consistent.

**Trade-offs:**
- Higher cost per image vs. GPT-4o-mini. Mitigated by offline execution and disk caching — each image is annotated at most once.
- API rate limits. Mitigated by per-image sleep using a configurable constant (reuse `MATHPIX_RATE_LIMIT` pattern) and per-image error recovery.

### ADR-03: Cache Annotations by MD5(image_bytes)

**Decision:** Use `hashlib.md5(image_bytes).hexdigest()` as the cache key; write to `{cache_dir}/vision_{md5}.json`.

**Rationale:** Image bytes are the canonical identity of an image — two images with the same bytes will always produce the same annotation. MD5 is fast, collision-resistant enough for this use case, and is a stdlib primitive with no new dependencies. The pattern mirrors Mathpix's existing `mathpix_cache/` directory structure.

**Trade-offs:** MD5 is not cryptographically secure but cache poisoning is not a threat model here (local filesystem, not user-controlled).

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| ChromaDB metadata size limit hit for concepts with many LaTeX expressions | Low | Medium | Log a warning when `len(json.dumps(latex)) > 8192`; keep `_latex_map` fallback in `knowledge_service.py` |
| OpenAI Vision API rate limits during large book annotation run | Medium | Low | Wrap each annotation in try/except; sleep between calls using configurable rate-limit constant; failed images written with `null` fields |
| Re-indexing ChromaDB required to surface `latex_expressions` in existing collections | High (existing deployments) | Medium | `_latex_map` fallback ensures zero regression; pipeline operator re-runs pipeline for updated enrichment |
| GPT-4o Vision misidentifies math content | Low | Low | Annotation is supplementary context; it does not replace the authoritative LaTeX or textbook text |
| `image_index.json` schema change breaks existing readers | Low | Medium | New fields `description` and `relevance` are additive; `ConceptImage` schema uses `Optional` with `None` defaults |
| Frontend renders captions for images with `null` description | Medium | Low | Frontend guards with `{image.description && <caption>}` conditional render |

---

## Key Decisions Requiring Stakeholder Input

1. **Re-annotation trigger policy:** Should `extract_and_save_images()` re-annotate existing images (overwrite cache) if `description` is already present in `image_index.json`? Current design: skip if cache hit exists — re-run with a `--force-reannotate` flag when needed. Confirm this behavior is acceptable.

2. **Vision model override:** The design uses `OPENAI_MODEL` (gpt-4o) for annotation. If cost is a concern, a separate `OPENAI_MODEL_VISION` constant could be introduced to allow routing to a cheaper or local model per environment. Confirm whether this override is needed.

3. **Multi-book static file routing:** The current `main.py` mounts `/images` pointing to `output/prealgebra/images/`. When additional books are onboarded, the mount must be parameterized. This is out of scope for this feature but must be tracked as follow-on technical debt.

4. **Rate limit constant reuse:** The design reuses `MATHPIX_RATE_LIMIT` (0.5 s) for vision annotation spacing. If vision calls should have a different rate, a separate `VISION_RATE_LIMIT` constant should be introduced in `config.py`. Confirm with the team.
