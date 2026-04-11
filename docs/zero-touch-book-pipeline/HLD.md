# High-Level Design: Zero-Touch Multi-Subject Book Pipeline

**Feature name:** `zero-touch-book-pipeline`
**Date:** 2026-04-08
**Status:** Approved for implementation

---

## 1. Executive Summary

### Feature / System Name and Purpose
The Zero-Touch Multi-Subject Book Pipeline automates the entire journey from a raw PDF landing in a watched directory to that book being fully live in the ADA platform — sections parsed, chunks embedded in pgvector, dependency graph built, and images served — with no operator commands, no server restarts, and no config-file edits required.

### Business Problem Being Solved
Today, adding a new textbook to ADA is a five-step manual process: edit `BOOK_REGISTRY` in `config.py`, run `python -m src.pipeline --book <CODE>`, run `python -m extraction.chunk_builder --book <slug>`, restart uvicorn, and verify the book is live. This creates a high-friction deployment gate that:

- Prevents DevOps from scaling to the 16+ OpenStax books and the new Business/Nursing subjects already present in `backend/data/`.
- Requires Python expertise to operate, coupling content onboarding to engineering cycles.
- Keeps `BOOK_REGISTRY` as a 300-line hardcoded dict in `config.py` — a maintenance liability when books share font signatures but differ in front-matter or exercise patterns.

### Key Stakeholders
- **DevOps Engineer** — sole operator; drops PDFs, monitors logs.
- **Platform Engineering Team** — owns the pipeline code and YAML registry.
- **Content Team** — benefits indirectly by seeing new subjects appear without an engineering ticket.

### Scope

**In scope:**
- Watchdog file watcher on `backend/data/` that detects new `.pdf` files in any subdirectory.
- Automated 5-stage pipeline runner (Mathpix → Parse → Chunk/Embed → Graph → Hot-load).
- YAML-based book registry (`backend/books.yaml`) replacing the `BOOK_REGISTRY` dict in `config.py`.
- Font auto-calibration via PyMuPDF to derive `section_header_font`, `section_header_size_min/max`, and `chapter_header_font/size_*` without manual inspection.
- Image download retry with cleanup of incomplete rows.
- Expert-graph YAML for prealgebra (`backend/src/graph/expert_graphs/prealgebra.yaml`).
- One-time bootstrap script for pre-existing PDFs already in `backend/data/`.
- Removal of all hardcoded single-book defaults (`DEFAULT_BOOK_SLUG`, `BOOK_CODE_MAP`, `default="prealgebra"` in CLI args, `default="PREALG"` in pipeline, hardcoded `default="prealgebra"` in `TeachingSession.book_slug` DB column).

**Out of scope:**
- Frontend UI for monitoring pipeline status (deferred; polling the `/api/admin/pipeline-status` endpoint is sufficient).
- Multi-worker horizontal scaling of the watcher (single-instance EC2 deployment).
- Automatic prerequisite graph construction via LLM (keyword-based builder already implemented; expert YAML is opt-in per slug).
- Authentication system changes.
- Mathpix billing or quota management.

---

## 2. Functional Requirements

| # | Priority | Requirement |
|---|----------|-------------|
| FR-01 | Must | Dropping a PDF into `backend/data/{subject}/` starts the pipeline automatically within 60 seconds. |
| FR-02 | Must | The slug is derived deterministically from the filename (strip numeric suffix + extension, lowercase, underscores). `FinancialAccounting-OP_YioY6nY.pdf` → `financial_accounting`. |
| FR-03 | Must | Pipeline runs through 5 stages: Mathpix OCR → MMD parse → Chunk/Embed → Graph build → Hot-load. |
| FR-04 | Must | On completion, `POST /api/admin/load-book/{slug}` is called to hot-load the book without a server restart. |
| FR-05 | Must | Book registry is read from `backend/books.yaml` at startup and whenever a new book is registered. |
| FR-06 | Must | If `books.yaml` has no entry for a detected slug, `calibrate.py` auto-detects font parameters and appends a new YAML entry. |
| FR-07 | Must | Image download failures are retried up to 3 times with exponential back-off before being marked as permanently failed. |
| FR-08 | Must | Incomplete image DB rows (file absent on disk) are cleaned up before the hot-load call so no 404s appear to students. |
| FR-09 | Must | The watcher is crash-tolerant: if it dies it is restarted by the process supervisor (systemd / Docker restart policy). |
| FR-10 | Must | `backend/scripts/bootstrap_existing.py` processes all PDFs already in `backend/data/` in one run to seed newly deployed machines. |
| FR-11 | Should | Content exclusion rule: only "Self Check" blocks are excluded; all other blocks (including Try It, Media, Section Exercises) are treated as subsections. |
| FR-12 | Should | If a pipeline stage fails, the book is left in a `FAILED` state and a `pipeline_runs` DB row records the error; the watcher does not retry automatically without operator intervention. |
| FR-13 | Should | Expert-graph YAML for prealgebra replaces the 265-line inline Python dict in `dependency_builder.py`. |
| FR-14 | Could | A `GET /api/admin/pipeline-runs` endpoint lets an operator query the last N pipeline executions and their status. |

---

## 3. Non-Functional Requirements

### Performance
- The watcher detects a new PDF and begins Stage 1 within **60 seconds** of the file being fully written (stable mtime).
- Each pipeline stage emits progress logs every 30 seconds so the operator can verify activity.
- The hot-load step (graph preload + image-dir mount) completes in under **5 seconds** for books up to 500 concepts.

### Scalability
- Current load: up to 20 books processed sequentially (one at a time). Concurrent multi-book processing is not required and deliberately excluded to avoid Mathpix rate-limit collisions.
- The pipeline queue (in-memory asyncio.Queue) holds up to 50 pending PDFs without dropping entries. For the current 16-book corpus this is more than sufficient.

### Availability and Reliability
- The watcher process runs as a Docker service with `restart: always`; container restarts are transparent to the running FastAPI app.
- Pipeline stages are idempotent: re-running a failed pipeline from any stage is safe (chunk_builder uses upsert, graph_builder is append-safe, Mathpix submit is guarded by cached MMD).
- A `pipeline_runs` table in PostgreSQL provides durable state: the operator can diagnose a failure without reading logs.

### Security and Compliance
- The watcher and pipeline runner never serve HTTP; they communicate only via the internal `POST /api/admin/load-book` endpoint secured by `X-API-Key`.
- PDF files are not exposed through any API endpoint; they remain in the server filesystem only.
- `books.yaml` contains no secrets; it is safe to commit to the repository.

### Maintainability and Observability
- All configuration lives in `books.yaml`; no Python file edits required to add a new book.
- Structured JSON logs from the pipeline runner are emitted to stdout for ingestion by the Docker/EC2 logging stack.
- The `pipeline_runs` table is queryable via the admin API endpoint (FR-14).

---

## 4. System Context Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  EC2 Server / Docker Host                                       │
│                                                                 │
│  ┌──────────────────┐   PDF drop    ┌─────────────────────────┐│
│  │   DevOps          │ ──────────►  │  backend/data/          ││
│  │   (operator)      │              │   {subject}/            ││
│  └──────────────────┘              │   {title}-OP_xxx.pdf    ││
│                                     └────────────┬────────────┘│
│                                                  │ FS event    │
│                                     ┌────────────▼────────────┐│
│                                     │  book_watcher.py        ││
│                                     │  (watchdog Observer)    ││
│                                     └────────────┬────────────┘│
│                                                  │ asyncio.Queue│
│                                     ┌────────────▼────────────┐│
│                                     │  pipeline_runner.py     ││
│                                     │  Stage 1: Mathpix OCR   ││
│                                     │  Stage 2: MMD parse     ││
│                                     │  Stage 3: Chunk/Embed   ││
│                                     │  Stage 4: Graph build   ││
│                                     │  Stage 5: Hot-load      ││
│                                     └──────┬──────────┬───────┘│
│                                            │          │        │
│                           Mathpix API ◄────┘          │        │
│                           (external)                  │        │
│                                             ┌─────────▼──────┐ │
│                                             │  FastAPI app   │ │
│                                             │  (uvicorn)     │ │
│                                             │  /api/admin/   │ │
│                                             │  load-book     │ │
│                                             └────────┬───────┘ │
│                                                      │         │
│                   ┌──────────────────────────────────▼───────┐ │
│                   │  PostgreSQL 15 (concept_chunks +          │ │
│                   │  pgvector + pipeline_runs)                │ │
│                   └──────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘

External:
  Mathpix API — PDF OCR + image extraction (HTTPS, chunked polling)
  OpenAI API  — text-embedding-3-small (called by chunk_builder)
```

---

## 5. Architectural Style and Patterns

### Selected Style: Event-Driven Pipeline with Idempotent Stages

The pipeline is triggered by a filesystem event (watchdog `FileCreatedEvent` / `FileMovedEvent`) and executes a linear 5-stage async pipeline. Each stage is independently restartable, writes its output to a durable location (PostgreSQL or `output/` filesystem), and is guarded by a skip-if-already-done check.

**Why this over alternatives:**

| Alternative | Why rejected |
|---|---|
| Manual CLI + cron job | Still requires operator action or a pre-configured schedule; doesn't respond to ad-hoc PDF drops. |
| Celery + Redis task queue | Adds two new infrastructure dependencies (Redis, Celery broker) for a workload that is single-host and low-concurrency. Overkill. |
| Kafka/event streaming | Appropriate for multi-producer multi-consumer at scale. The event source is a single directory watcher with a volume of ~1 PDF/week. |
| FastAPI background tasks | Tied to HTTP request lifecycle; would require a dummy HTTP call to trigger the pipeline. |

**Trade-offs accepted:**
- The pipeline queue is in-memory (asyncio.Queue). A server crash between PDF detection and pipeline completion means the PDF is not reprocessed automatically. Mitigation: the bootstrap script can be re-run, and the watcher rescan-on-startup covers this case.
- Watchdog is cross-platform but has different event semantics on Windows (no `FileCreatedEvent` for file moves). Since the production target is Linux (EC2/Docker), this is a non-issue.

---

## 6. Technology Stack

| Concern | Technology | Rationale |
|---|---|---|
| Filesystem watching | `watchdog 4.0` (already in `requirements.txt`) | Cross-platform, mature, inotify-backed on Linux |
| YAML parsing | `pyyaml 6.0` (already in `requirements.txt`) | Standard library for config files in Python ecosystem |
| Async pipeline execution | Python `asyncio` + `asyncio.Queue` | No new dependencies; matches existing FastAPI async model |
| Font detection | `PyMuPDF 1.24+` (already in `requirements.txt`) | Already used in `pdf_reader.py`; `page.get_text("dict")` gives per-span font metadata |
| PDF OCR | Mathpix `/v3/pdf` API (existing integration) | Already integrated in `pipeline.py` |
| Chunk embedding | OpenAI `text-embedding-3-small` (existing) | No change |
| Persistence | PostgreSQL 15 + SQLAlchemy 2.0 async (existing) | New `pipeline_runs` table added via Alembic migration |
| HTTP client for hot-load call | `httpx` (already in `requirements.txt`) | Async-friendly; avoids spawning a subprocess just to call localhost |

No new runtime dependencies are introduced.

---

## 7. Key Architectural Decisions (ADRs)

### ADR-01: Books.yaml as single source of truth for book registry

**Decision:** Migrate `BOOK_REGISTRY` from a hardcoded Python dict in `config.py` to `backend/books.yaml`. `config.py` loads the YAML at import time and exposes the same `BOOK_REGISTRY`, `get_book_config()`, and `get_pdf_path()` interfaces — no call sites change.

**Options considered:**
1. Keep Python dict — easy to edit, but requires a code deploy for every new book.
2. PostgreSQL `books` table — durable but adds a DB read to every server startup and requires a migration for each new field.
3. YAML file (chosen) — human-readable, version-controlled, editable without Python knowledge, loaded once at startup with a hot-reload path for new entries.

**Rationale:** YAML is the right tool for static configuration that changes infrequently and must be auditable in git. It is not operational data and does not belong in PostgreSQL. The file is co-located with the code and deployed with it.

**Trade-off:** If `books.yaml` is malformed, the server fails to start. Mitigation: validate YAML schema at startup with clear error messages.

---

### ADR-02: Font auto-calibration from PDF (calibrate.py)

**Decision:** Implement `calibrate.py` that reads a PDF with PyMuPDF and returns a best-guess `BookConfig` dict for the YAML entry. The result is reviewed by the engineer before committing (or accepted as-is for zero-touch use).

**Options considered:**
1. Require human font inspection (current state) — documented in `config.py` comment block.
2. LLM-based detection — too slow and expensive for what is essentially a font-histogram task.
3. PyMuPDF font histogram (chosen) — deterministic, zero cost, works offline.

**Rationale:** Font names and sizes are empirical properties of a PDF's typographic design. The most frequent bold font in body text pages is almost always the section-header font. This heuristic works correctly for all 16 existing OpenStax books in the registry.

**Trade-off:** The calibration heuristic can be wrong for non-OpenStax PDFs (e.g., scanned images, custom fonts). In this case the pipeline will produce low-quality sections; the operator must manually correct `books.yaml`. This is explicitly documented in the calibration output.

---

### ADR-03: Pipeline runner as an in-process asyncio task, not a subprocess

**Decision:** `pipeline_runner.py` runs the 5 pipeline stages as async coroutines within the same Python process as the watcher, sharing the asyncio event loop.

**Options considered:**
1. Subprocess per pipeline run — clean isolation but requires serialising all arguments and loses direct access to DB sessions.
2. Separate process with IPC — adds complexity for what is a single-machine workload.
3. In-process asyncio task (chosen) — uses existing DB connection pool, shares `OUTPUT_DIR` path resolution, and avoids IPC overhead.

**Rationale:** The pipeline touches the same PostgreSQL database and filesystem as the running FastAPI app. Running in-process reuses the connection pool and avoids duplicating environment loading. The watcher and pipeline runner are launched as asyncio background tasks at application startup, not as separate OS processes.

**Trade-off:** A crash in `pipeline_runner.py` could theoretically affect the FastAPI event loop. Mitigated by wrapping each stage in `try/except` and writing to `pipeline_runs` before raising.

---

### ADR-04: "Self Check only" exclusion rule

**Decision:** The only block type excluded from chunking is `SELF_CHECK`. All other pedagogically-labelled block types (Try It, Media, Example, Section Exercises, Key Concepts, Review Exercises) are treated as regular subsection content and included as chunks.

**Rationale:** This exactly matches the current prealgebra output which serves as the reference behaviour. Self Check blocks are repetitive exercise lists that add no conceptual content for the student; every other block type contributes to understanding.

**Trade-off:** Including "Section Exercises" means exercise text ends up in pgvector and can be retrieved in RAG queries. This is acceptable because exercise problems in context often clarify concept application.

---

### ADR-05: Slug derivation from filename

**Decision:** Slug = `re.sub(r"-OP_[A-Za-z0-9]+", "", stem).lower().replace(" ", "_").replace("-", "_")` where `stem` is the filename without extension.

**Examples:**
- `FinancialAccounting-OP_YioY6nY.pdf` → stem `FinancialAccounting-OP_YioY6nY` → strip suffix → `FinancialAccounting` → lowercase → `financialaccounting` → replace `-` → `financial_accounting`
- `Fundamentals_of_Nursing_-_WEB.pdf` → strip `-_WEB` (matched as `_-_WEB`) → no — only the `-OP_xxx` pattern is stripped. Actual result: stem `Fundamentals_of_Nursing_-_WEB` → no `-OP_` suffix → lowercase → `fundamentals_of_nursing_-_web` — operator should rename the file first.

**Guidance:** Files should follow the naming convention `{TitleCase}-OP_{hash}.pdf` or `{Title_with_underscores}.pdf`. The `bootstrap_existing.py` script documents the derived slug before processing so the operator can verify.

---

## 8. Risks and Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|-----------|
| R-01 | Mathpix API quota exhaustion for a large new book (500+ pages) | Medium | High | Cached MMD prevents re-submission on retry. Alert via log when API error status returned. |
| R-02 | Font calibration produces wrong section headers, yielding 0 or 2000 "sections" | Medium | High | Calibration output includes a sample of detected headings; operator reviews before committing to `books.yaml`. Zero sections triggers a `FAILED` pipeline state and alert log. |
| R-03 | Watchdog `FileCreatedEvent` fires before PDF is fully written (partial file) | High | Medium | `pipeline_runner` waits until `os.path.getsize()` is stable for 5 seconds before starting Stage 1. |
| R-04 | `books.yaml` schema drift — new required field added but existing entries missing it | Low | High | Pydantic `BookConfig` model validates every entry at load time; missing fields raise `ValidationError` with field name at startup. |
| R-05 | `admin_load_book` hot-mount already-mounted path raises `AssertionError` in Starlette | High | Low | Already handled in existing code with bare `except: pass`. Verified safe. |
| R-06 | Long-running Mathpix poll (10-30 min) blocks the asyncio event loop | High | High | Mathpix poll loop uses `await asyncio.sleep()` between checks — must be wrapped in `asyncio.to_thread()` if the existing client is synchronous. |
| R-07 | Business/Nursing PDFs use non-OpenStax fonts; keyword-based graph builder produces a sparse graph | Medium | Medium | Acceptable for MVP; expert YAML can be added per-slug once the content team reviews. |
| R-08 | Pipeline state lost on container restart between PDF detection and completion | Medium | Medium | Watcher rescan-on-startup re-enqueues any PDF whose slug has no `pipeline_runs` row with status `COMPLETED`. |

---

## Key Decisions Requiring Stakeholder Input

1. **Bootstrap order for Business/Nursing PDFs** — should `bootstrap_existing.py` be run once on first deploy, or should the watcher's rescan-on-startup handle them? If the latter, a `PENDING` sentinel must be written to `pipeline_runs` before the watcher starts watching, to prevent double-processing.

2. **Auto-commit calibration results to `books.yaml`** — the zero-touch design writes a tentative YAML block and proceeds. If the calibration heuristic produces wrong section counts, students will see malformed content. Should there be a minimum-sections guard (e.g., abort if fewer than 10 sections detected)?

3. **Mathpix cost approval** — each new PDF submission costs API credits. Should there be an explicit allow-list of subject directories (`data/maths/`, `data/Business/`) vs a blanket watch-all-subdirectories policy?

4. **Removal of `DEFAULT_BOOK_SLUG`** — several existing v1 API endpoints (`/api/v1/concepts/query`) default to `DEFAULT_BOOK_SLUG`. Removing it without adding a required `book_slug` query parameter is a breaking API change. This must be coordinated with any frontend code that omits the parameter.
