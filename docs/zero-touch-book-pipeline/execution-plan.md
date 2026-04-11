# Execution Plan: Zero-Touch Multi-Subject Book Pipeline

**Feature:** `zero-touch-book-pipeline`
**Date:** 2026-04-08
**Status:** Ready for implementation

---

## 1. Work Breakdown Structure (WBS)

Each task maps to exactly one CLAUDE.md stage (0=devops, 1=architect, 2=backend, 3=testing, 4=frontend). Dependencies are listed by task ID. Effort is in engineer-days.

### Stage 0 — Infrastructure (`devops-engineer`)

| ID | Title | Description | Effort | Depends On |
|---|---|---|---|---|
| P0-01 | Alembic migration: remove TeachingSession default | Remove `server_default="prealgebra"` from `teaching_sessions.book_slug` column | 0.25d | — |
| P0-02 | Alembic migration: add pipeline_runs table | Create `pipeline_runs` table with columns: id, book_slug, status, stage, error_msg, started_at, finished_at. Add two indexes. | 0.5d | P0-01 |
| P0-03 | Add watchdog + pyyaml to requirements.txt | Add `watchdog>=4.0` and `pyyaml>=6.0` to `backend/requirements.txt` | 0.25d | — |
| P0-04 | Add book-watcher Docker service | Add `book-watcher` service to `docker-compose.yml` with shared volumes for `books.yaml`, `data/`, `output/`; set `restart: always`; pass required env vars | 0.5d | — |
| P0-05 | Update .env.example | Add `API_BASE_URL=http://backend:8889` to `backend/.env.example` | 0.25d | — |
| P0-06 | Create books.yaml.example | Document all required fields with inline comments; include one complete example entry (PREALG) | 0.25d | — |
| P0-07 | Create expert_graphs/ directory and __init__ stubs | Create `backend/src/graph/expert_graphs/` with a `.gitkeep`; create `backend/src/watcher/__init__.py` | 0.25d | — |

**Stage 0 Total: 2.25 days**

---

### Stage 1 — Design (`solution-architect`)

| ID | Title | Description | Effort | Depends On |
|---|---|---|---|---|
| P1-01 | Write HLD.md | High-Level Design (completed) | 0d | — |
| P1-02 | Write DLD.md | Detailed Low-Level Design (completed) | 0d | P1-01 |
| P1-03 | Write execution-plan.md | This document | 0d | P1-02 |

**Stage 1 Total: 0 days (completed)**

---

### Stage 2 — Backend (`backend-developer`)

#### Sub-group A: Removal of Old Architecture

| ID | Title | Description | Effort | Depends On |
|---|---|---|---|---|
| P2-A01 | Remove DEFAULT_BOOK_SLUG from config.py | Delete line `DEFAULT_BOOK_SLUG = "prealgebra"` (config.py:37). Remove all import references in `main.py`. Verify no other file imports this constant. | 0.25d | P0-02 |
| P2-A02 | Remove BOOK_CODE_MAP and BOOK_REGISTRY from config.py | Delete hardcoded dicts (config.py:160-488). Replace with YAML loader (see P2-B01). These two tasks must be done together — do not remove the dicts until the YAML loader is in place. | 0.5d | P2-B01 |
| P2-A03 | Remove default="PREALG" from pipeline.py CLI | Delete `default="PREALG"` on the `--book` argparse argument (pipeline.py:364). Make the argument required. Update the usage docstring. | 0.25d | P0-01 |
| P2-A04 | Remove default="prealgebra" from chunk_builder.py CLI | Delete `default="prealgebra"` on the `--book` CLI arg (chunk_builder.py:294). Make required. | 0.25d | — |
| P2-A05 | Remove TeachingSession.book_slug default from models.py | Delete `default="prealgebra"` from `TeachingSession.book_slug` mapped_column (models.py:87). | 0.25d | P0-01 |
| P2-A06 | Remove hardcoded prealgebra expert graph from dependency_builder.py | Delete `_prealgebra_expert_graph()` function (lines 74-339) and its entry in the `registry` dict. Wire YAML loader in its place (see P2-C02). | 0.5d | P2-C02 |

**Sub-group A Total: 2.0 days**

#### Sub-group B: books.yaml + config.py YAML Loader

| ID | Title | Description | Effort | Depends On |
|---|---|---|---|---|
| P2-B01 | Create books.yaml with all 16 math books | Transcribe all 16 existing `BOOK_REGISTRY` entries from config.py into YAML format. Include the `expert_graph: prealgebra` field for PREALG. Validate manually that all 16 codes, slugs, fonts, sizes, patterns match the original dict exactly. | 1.5d | P0-06 |
| P2-B02 | Implement BookConfig Pydantic model + YAML loader in config.py | Add `BookConfig` Pydantic model with field validators (regex validation for `section_pattern`/`exercise_marker_pattern`). Implement `_load_books_yaml()` and `BOOK_CODE_MAP, BOOK_REGISTRY = _load_books_yaml(BOOKS_YAML_PATH)`. Add `BOOKS_YAML_PATH`, `API_SECRET_KEY`, `API_BASE_URL` constants. | 1.0d | P2-B01 |
| P2-B03 | Add `subject` field to /api/v1/books endpoint | Add `subject` field to the books list response schema in `main.py`. Source the value from `BOOK_REGISTRY[code]["subject"]`. | 0.5d | P2-B02 |

**Sub-group B Total: 3.0 days**

#### Sub-group C: New Files

| ID | Title | Description | Effort | Depends On |
|---|---|---|---|---|
| P2-C01 | Implement calibrate.py | Implement `calibrate_book()`, `derive_slug_from_filename()`, `derive_book_code()`, `append_to_books_yaml()` per DLD Section 5.1. Include `_yaml_write_lock` for thread safety. | 1.5d | P0-07 |
| P2-C02 | Implement expert_graphs YAML loader in dependency_builder.py | Replace `_get_expert_graph()` registry dict with YAML file loader per DLD Section 5.5. Load from `backend/src/graph/expert_graphs/{slug}.yaml`. | 0.5d | P0-07 |
| P2-C03 | Write prealgebra.yaml expert graph | Transcribe the `_prealgebra_expert_graph()` Python dict into the YAML schema defined in DLD Section 5.5. Validate node list against actual concept_ids in `concept_chunks` table for prealgebra. | 1.0d | P0-07, P2-C02 |
| P2-C04 | Implement book_watcher.py | Implement `PDFHandler`, `watch_forever()`, `main()` per DLD Section 5.2. Subject normalisation (`maths` → `mathematics`). File stability check (5-second poll). asyncio.Queue with maxsize=50. | 1.0d | P2-C01, P0-04 |
| P2-C05 | Implement pipeline_runner.py | Implement `run_pipeline_worker()` and `_run_pipeline()` with all 5 stages per DLD Section 5.3. Include per-book file handler for `pipeline.log`. DB status update helpers. Mathpix executor call. `_build_graph()` helper. `_hot_load()` via httpx. | 2.5d | P2-C01, P2-C04, P2-B02 |
| P2-C06 | Add image retry + validate functions to chunk_builder.py | Add `_download_image_with_retry()` (async, httpx) and `_validate_and_clean_images()` per DLD Section 5.4. Replace existing synchronous `download_image()` calls with the retry version in the `build_chunks()` path. | 1.0d | P2-B02 |
| P2-C07 | Add PipelineRun ORM model to models.py | Add `PipelineRun` mapped class per DLD Section 2.2. Coordinate with devops-engineer — Alembic migration P0-02 must be applied first. | 0.5d | P0-02 |
| P2-C08 | Implement admin endpoints in main.py | Implement `POST /api/admin/load-book/{slug}` (reload YAML, mount StaticFiles, init KnowledgeService, return concept count) and `GET /api/admin/pipeline-runs` (query DB with limit/filter). Both require X-API-Key header. | 1.5d | P2-B02, P2-C07 |
| P2-C09 | Implement bootstrap_existing.py | Implement per DLD Section 5.6. `--dry-run` flag. Load registered slugs from YAML. Scan DATA_DIR recursively. Print summary table. | 0.75d | P2-C01, P2-C05 |
| P2-C10 | Implement watcher rescan-on-startup | In `book_watcher.py` `main()`, before starting the Observer, query `pipeline_runs` for slugs with no COMPLETED row and re-enqueue their PDFs. | 0.5d | P2-C05, P2-C07 |

**Sub-group C Total: 10.75 days**

---

### Stage 3 — Testing (`comprehensive-tester`)

| ID | Title | Description | Effort | Depends On |
|---|---|---|---|---|
| P3-01 | Unit tests: calibrate.py (T-01 to T-06) | calibrate_book font detection, slug derivation (messy filenames, WEB suffix), book code collision | 1.0d | P2-C01 |
| P3-02 | Unit tests: YAML loader (T-07, T-08, T-09) | 16 books load, bad regex raises, DEFAULT_BOOK_SLUG absent | 0.5d | P2-B02 |
| P3-03 | Unit tests: pipeline_runner (T-10) | Mock all 5 stage functions; assert called once each in correct order | 1.0d | P2-C05 |
| P3-04 | Unit tests: image retry + validation (T-11 to T-14) | Mock httpx responses; assert retry behaviour; async DB fixture for orphan row cleanup | 1.0d | P2-C06 |
| P3-05 | Unit tests: book_watcher (T-15 to T-18) | Mock FileCreatedEvent; assert queue behaviour; subject normalisation | 0.75d | P2-C04 |
| P3-06 | Unit tests: expert graph YAML loader (T-19, T-20) | Load prealgebra.yaml; assert fallback for unknown slug | 0.5d | P2-C02, P2-C03 |
| P3-07 | Unit tests: admin endpoints (T-21) | GET /api/v1/books returns subject; POST /api/admin/load-book 200/404/409 | 0.75d | P2-C08 |
| P3-08 | Unit tests: bootstrap script (T-22, T-23) | Skip already-registered slugs; thread-safe YAML append | 0.5d | P2-C09 |
| P3-09 | Integration test: pipeline end-to-end (synthetic PDF) | Run all 5 stages against a 2-page minimal PDF with mock Mathpix. Assert pipeline_runs COMPLETED. Assert concept_chunks rows inserted. | 1.5d | P2-C05, P2-C06 |
| P3-10 | Integration test: hot-load endpoint | After chunk builder inserts rows for a test slug, call POST /api/admin/load-book/{slug}; assert GET /api/v1/books includes slug with subject. | 0.75d | P2-C08 |
| P3-11 | Verification SQL script | Write and document the 5 SQL verification queries from the plan as a `scripts/verify_pipeline.sql` file. | 0.25d | P2-C05 |

**Stage 3 Total: 8.5 days**

---

### Stage 4 — Frontend (`frontend-developer`)

| ID | Title | Description | Effort | Depends On |
|---|---|---|---|---|
| P4-01 | Update ConceptMapPage.jsx dropdown | Replace flat `<select>` with `<optgroup>` grouped by `book.subject`. Groups built dynamically from API response — no hardcoded subject list. Sort groups alphabetically. | 0.75d | P2-B03 |
| P4-02 | Add subjects keys to all 13 locale files | Add `"subjects": {"mathematics": "...", "business": "...", "nursing": "..."}` to all 13 `frontend/src/locales/*.json` files. Fallback in JSX uses capitalised folder name if translation key absent. | 0.5d | P4-01 |

**Stage 4 Total: 1.25 days**

---

## 2. Phased Delivery Plan

### Phase 0 — Foundation (devops-engineer)
**Goal:** Infrastructure ready; schema migrated; watcher service defined in Docker.

Tasks: P0-01, P0-02, P0-03, P0-04, P0-05, P0-06, P0-07

**Acceptance criteria:**
- `alembic upgrade head` applies cleanly: `teaching_sessions.book_slug` has no server default; `pipeline_runs` table exists with all required columns.
- `docker-compose.yml` has `book-watcher` service that starts successfully with `docker compose up --build`.
- `requirements.txt` includes `watchdog>=4.0` and `pyyaml>=6.0`.
- `.env.example` documents `API_BASE_URL`.

---

### Phase 1 — Design (solution-architect)
**Goal:** Full DLD and execution plan written and approved before any backend code is written.

Tasks: P1-01, P1-02, P1-03

**Acceptance criteria (completed):**
- HLD.md, DLD.md, and execution-plan.md exist in `docs/zero-touch-book-pipeline/`.
- All function signatures, YAML schemas, DB models, and API contracts are specified in DLD.
- No ambiguous requirements remain — all four open stakeholder questions are documented.

---

### Phase 2 — Backend Core (backend-developer)
**Goal:** Old architecture removed; YAML registry live; calibration, watcher, and pipeline runner implemented.

Sub-phase 2a (parallel): P2-B01 + P2-C03 (data entry — can be done concurrently by two engineers)
Sub-phase 2b (sequential): P2-B02 → P2-A02 → P2-A01, P2-A03, P2-A04, P2-A05 (atomic removal after loader is proven)
Sub-phase 2c (new files): P2-C01 → P2-C02 → P2-C04 → P2-C05 → P2-C06 → P2-C07 → P2-C08 → P2-C09 → P2-C10
Sub-phase 2d: P2-A06, P2-B03 (cleanup + API enhancement)

**Acceptance criteria:**
- `grep -r "DEFAULT_BOOK_SLUG" backend/src/` returns no results.
- `grep -r "default=\"prealgebra\"" backend/src/` returns no results.
- `python -c "from src.config import BOOK_REGISTRY; assert len(BOOK_REGISTRY) == 16"` passes.
- `books.yaml` contains all 16 math book entries; `pydantic` validation passes for all.
- `backend/src/watcher/book_watcher.py` and `pipeline_runner.py` exist with all specified functions.
- `backend/scripts/bootstrap_existing.py --dry-run` lists all PDFs in `backend/data/` without errors.
- `POST /api/admin/load-book/prealgebra` returns 200 with correct concept count.
- `GET /api/admin/pipeline-runs` returns 200 with empty list (no runs yet).
- `GET /api/v1/books` response includes `subject` field on all entries.

---

### Phase 3 — Testing (comprehensive-tester)
**Goal:** All 23 unit tests pass; integration tests confirm end-to-end flow.

Tasks: P3-01 through P3-11

**Acceptance criteria:**
- `pytest backend/tests/test_book_pipeline.py -v` shows 23+ tests, 0 failures.
- Integration test confirms a synthetic minimal PDF reaches `pipeline_runs.status = COMPLETED`.
- Integration test confirms hot-load endpoint adds a new slug to `/api/v1/books` without server restart.
- `scripts/verify_pipeline.sql` documented and runnable against production DB.

---

### Phase 4 — Frontend (frontend-developer)
**Goal:** ConceptMapPage dropdown groups books by subject dynamically.

Tasks: P4-01, P4-02

**Acceptance criteria:**
- Concept map page shows `<optgroup>` elements: "Mathematics", "Business", "Nursing" (once Business/Nursing books are live).
- Fallback: if a `subject` key has no i18n translation, the capitalised folder name is displayed.
- All 13 locale files include `subjects` keys.
- No hardcoded subject names in JSX — subject groups are derived from API response.

---

## 3. Dependencies and Critical Path

### Dependency Graph

```
P0-01 ──► P0-02 ──► P2-C07 ──► P2-C08
                                    ▲
P0-06 ──► P2-B01 ──► P2-B02 ──► P2-A02
               │
               └──► P2-C03
                         ▲
P0-07 ──► P2-C01 ──► P2-C02 ──► P2-A06
               │
               ├──► P2-C04 ──► P2-C10
               │         │
               │         ▼
               └──► P2-C05 ──► P2-C09
                         │
                         ▼
                    P2-C06 ──► P3-04
                    P2-C08 ──► P3-07 ──► P4-01 ──► P4-02
                    P2-C05 ──► P3-03
                    P2-C04 ──► P3-05
                    P2-C02 ──► P3-06
                    P2-B02 ──► P3-02
                    P2-C01 ──► P3-01
```

### Critical Path

The longest dependency chain (minimum calendar time assuming one engineer):

**P0-01 → P0-02 → P2-C07 → P2-B01 → P2-B02 → P2-C01 → P2-C04 → P2-C05 → P2-C06 → P2-C08 → P3-09 → P3-10 → P4-01 → P4-02**

Estimated critical path duration (single engineer): **~14 calendar days**

With two engineers working in parallel on independent tracks:
- Engineer A: P0-01, P0-02, P2-B01, P2-B02, P2-C07, P2-C08, P2-B03, P2-A01–A06
- Engineer B: P0-03–P0-07, P2-C01, P2-C02, P2-C03, P2-C04, P2-C05, P2-C06, P2-C09, P2-C10

**Estimated with 2 engineers: ~8 calendar days** (Phase 0 + 2 overlap; Phase 3 and 4 follow sequentially).

### Blocking Dependencies on External Teams or Systems

| Dependency | Blocking Task | Risk |
|---|---|---|
| Mathpix API credentials in `.env` | P2-C05 (Stage 2 of pipeline) | Medium — Mathpix must be configured in the watcher Docker env before testing end-to-end |
| PostgreSQL `pipeline_runs` table created (Alembic migration) | P2-C07, P3-09 | High — backend developer cannot implement ORM model until devops applies migration |
| `books.yaml` with 16 entries validated against live DB | P2-A02 (removal of hardcoded BOOK_REGISTRY) | High — must confirm YAML loader returns identical data before deleting the hardcoded dict |

---

## 4. Definition of Done (DoD)

### Per-Task DoD
- All specified functions/classes implemented with docstrings.
- No `print()` statements — all logging via Python `logging` module.
- No magic strings — all thresholds/constants added to `config.py`.
- Code reviewed by at least one other engineer (or architect if no second engineer).
- Ruff lint passes (`ruff check backend/src/`).

### Phase 0 DoD
- [ ] `alembic upgrade head` succeeds on a fresh DB and on a DB with existing prealgebra data.
- [ ] `alembic downgrade -1` succeeds (rollback is safe).
- [ ] `docker compose up --build` starts `book-watcher` container without errors.
- [ ] `requirements.txt` includes pinned versions: `watchdog>=4.0`, `pyyaml>=6.0`.

### Phase 2 DoD (Backend)
- [ ] `grep -r "DEFAULT_BOOK_SLUG" backend/src/` → zero results.
- [ ] `grep -r 'default="prealgebra"' backend/src/` → zero results.
- [ ] `python -c "from src.config import BOOK_REGISTRY; print(len(BOOK_REGISTRY))"` → `16`.
- [ ] `python -c "from src.config import BOOK_CODE_MAP; assert 'prealgebra' in BOOK_CODE_MAP"` → passes.
- [ ] `books.yaml` passes Pydantic validation for all 16 entries (run via `python -m src.config` with a validation print).
- [ ] `calibrate_book(prealgebra_pdf_path, "prealgebra", "mathematics")` returns dict with `section_header_font == "RobotoSlab-Bold"`.
- [ ] `derive_slug_from_filename("FinancialAccounting-OP_YioY6nY.pdf")` == `"financial_accounting"`.
- [ ] `GET /api/admin/pipeline-runs` returns `{"runs": []}` with valid X-API-Key.
- [ ] `POST /api/admin/load-book/prealgebra` returns 200 with concept count > 0.
- [ ] `GET /api/v1/books` response for prealgebra includes `"subject": "mathematics"`.
- [ ] `python scripts/bootstrap_existing.py --dry-run` exits 0 with correct output.

### Phase 3 DoD (Testing)
- [ ] `pytest backend/tests/test_book_pipeline.py -v` → ≥23 tests, 0 failures, 0 errors.
- [ ] `pytest backend/tests/ -v` → all pre-existing tests still pass (no regressions).
- [ ] Integration test: pipeline for synthetic PDF → `pipeline_runs.status = COMPLETED` in DB.
- [ ] Integration test: hot-load adds new slug to `/api/v1/books` response.

### Phase 4 DoD (Frontend)
- [ ] `ConceptMapPage.jsx` book selector shows optgroup grouping when multiple subjects are present.
- [ ] All 13 locale files include `subjects.mathematics`, `subjects.business`, `subjects.nursing` keys.
- [ ] Fallback (no translation key) displays capitalised folder name — verified manually.
- [ ] No hardcoded subject strings in JSX — confirmed by code review.

---

## 5. Rollout Strategy

### Deployment Approach

**Strategy:** Rolling deploy with feature-flag-free cutover. The YAML loader is a direct replacement for the hardcoded dict. There is no partial state — the migration either fully succeeds or is rolled back via Alembic.

**Deploy sequence:**

```
Step 1: Run Alembic migration (devops-engineer)
  → alembic upgrade head
  → Removes server_default from teaching_sessions.book_slug
  → Creates pipeline_runs table
  → Safe on live DB with existing prealgebra data (non-breaking column change)

Step 2: Deploy backend + book-watcher (docker compose)
  → docker compose up --build -d backend book-watcher
  → backend restarts with YAML loader (books.yaml must exist before this step)
  → book-watcher starts watching backend/data/

Step 3: Verify backend is healthy
  → GET /health → 200
  → GET /api/v1/books → returns ≥1 book with subject field
  → GET /api/admin/pipeline-runs → returns {"runs": []}

Step 4: Deploy frontend
  → docker compose up --build -d frontend
  → Verify concept map shows optgroup if multiple subjects are present

Step 5: Run bootstrap for Business + Nursing PDFs
  → docker compose exec book-watcher python scripts/bootstrap_existing.py --dry-run
  → Review dry-run output; confirm slugs are correct
  → docker compose exec book-watcher python scripts/bootstrap_existing.py
  → Monitor: docker compose logs book-watcher -f
  → Monitor: GET /api/admin/pipeline-runs (poll every 5 minutes)

Step 6: Verify Business + Nursing books live
  → Run verify_pipeline.sql against PostgreSQL
  → GET /api/v1/books → includes financial_accounting, managerial_accounting, etc.
  → Start a lesson on Financial Accounting → content, images, cards, Socratic all work
  → Concept map → Business group appears in dropdown
```

### Rollback Plan

| Issue | Rollback Action |
|---|---|
| `books.yaml` malformed — FastAPI won't start | Restore previous `books.yaml` from git; redeploy backend |
| Alembic migration fails | `alembic downgrade -1` — restores `server_default="prealgebra"` and drops `pipeline_runs` |
| pipeline_runner crashes the watcher | `docker compose restart book-watcher` — watcher restarts; rescan-on-startup re-enqueues |
| Bootstrap produces malformed chunks (wrong font calibration) | Manually edit `books.yaml` to correct font fields; delete `concept_chunks` rows for the slug; re-run bootstrap |
| Frontend optgroup breaks in IE/old browser (unlikely) | Revert ConceptMapPage.jsx to flat `<select>` — single commit revert |

### Monitoring and Alerting Setup for Launch

```bash
# Watch watcher logs live
docker compose logs book-watcher -f

# Poll pipeline status (refresh every 30 seconds)
watch -n 30 'curl -s -H "X-API-Key: $API_SECRET_KEY" \
  http://localhost:8889/api/admin/pipeline-runs?limit=10 | python3 -m json.tool'

# Check for failed runs
psql $DATABASE_URL -c "SELECT book_slug, status, stage, error_msg, \
  started_at FROM pipeline_runs WHERE status='FAILED';"

# Verify chunk counts after bootstrap
psql $DATABASE_URL -c "SELECT book_slug, COUNT(*) as chunks \
  FROM concept_chunks GROUP BY book_slug ORDER BY book_slug;"
```

### Post-Launch Validation

After bootstrap completes for all Business + Nursing PDFs:

```sql
-- 1. No hardcoded defaults remain
SELECT server_default FROM information_schema.columns
WHERE table_name='teaching_sessions' AND column_name='book_slug';
-- → NULL

-- 2. All books have meaningful chunk counts
SELECT book_slug, COUNT(*) as chunks, AVG(LENGTH(text))::int as avg_len
FROM concept_chunks GROUP BY book_slug ORDER BY book_slug;
-- Each book: > 100 chunks, avg_len > 200 chars

-- 3. No orphan image rows
SELECT COUNT(*) FROM pipeline_runs WHERE status='FAILED';
-- → 0 (or investigate each failure)

-- 4. Self Check not in chunks
SELECT COUNT(*) FROM concept_chunks WHERE text ILIKE '## self check%';
-- → 0

-- 5. All pipeline runs completed
SELECT book_slug, status, stage,
  EXTRACT(EPOCH FROM (finished_at - started_at))/3600 AS hours
FROM pipeline_runs ORDER BY started_at;
```

```bash
# 6. Watcher service healthy
docker compose ps book-watcher  # → Up

# 7. Drop a test PDF and watch the full cycle
cp /tmp/test_mini.pdf backend/data/business/
tail -f backend/output/test_mini/pipeline.log
# → stages 1-5 complete → "COMPLETED — book is LIVE"

# 8. Verify frontend groups
# Open /concept-map → dropdown shows Mathematics / Business / Nursing optgroups

# 9. Start a lesson on Financial Accounting
# → presentation loads, cards generate, Socratic check works

# 10. Concept map for Financial Accounting
# → graph renders with prerequisite edges
```

---

## 6. Effort Summary Table

| Phase | Stage | Key Tasks | Estimated Effort | Team Members Needed |
|---|---|---|---|---|
| 0 | Infrastructure | Alembic migrations, docker-compose watcher service, requirements, .env.example, stubs | **2.25 days** | 1 devops-engineer |
| 1 | Design | HLD, DLD, execution-plan (completed) | **0 days** | 1 solution-architect |
| 2a | Backend: Data Entry | books.yaml (16 books), prealgebra.yaml expert graph | **2.5 days** | 1 backend-developer |
| 2b | Backend: YAML Loader + Removal | BookConfig model, YAML loader, remove all old hardcoded dicts/defaults | **2.25 days** | 1 backend-developer |
| 2c | Backend: New Components | calibrate.py, book_watcher.py, pipeline_runner.py, image retry, admin endpoints, bootstrap script, rescan-on-startup | **9.25 days** | 1-2 backend-developers |
| 3 | Testing | 23 unit tests + 2 integration tests + verification SQL | **8.5 days** | 1 comprehensive-tester |
| 4 | Frontend | ConceptMapPage optgroup, 13 locale files | **1.25 days** | 1 frontend-developer |
| **Total** | | | **~26 days** | 2 engineers in parallel |

**Parallelism estimate:** With 2 engineers — one devops/backend for infrastructure + YAML data entry, one backend for new components — the critical path is approximately **12-14 calendar days** from start to production validation.

---

## Key Decisions Requiring Stakeholder Input

1. **Bootstrap order**: Should `bootstrap_existing.py` be run once manually after deploy, or should the watcher's rescan-on-startup handle pre-existing PDFs automatically? Manual bootstrap (recommended) gives the operator a dry-run preview before committing. Rescan-on-startup is fully automatic but skips the dry-run review step.

2. **Minimum sections guard**: If `calibrate_book()` detects fewer than `CALIBRATE_MIN_SECTION_COUNT = 10` sections, should the pipeline abort with `FAILED` status? This prevents malformed content reaching students but also blocks legitimate short books. Recommend: **yes, abort with FAILED and log the count** — operator can lower the threshold in `config.py` per-deploy if needed.

3. **Watch scope (all subdirs vs allow-list)**: Should the watcher watch all subdirectories of `backend/data/`, or only an explicit allow-list (`["maths", "Business", "Nursing"]`)? Allow-list prevents accidental processing of scratch PDFs but requires a code change for every new subject. Recommend: **watch all subdirs** and rely on slug validation to reject unexpected content.

4. **Removal of `DEFAULT_BOOK_SLUG` — API coordination**: The `/api/v1/concepts/query` endpoint currently defaults to `DEFAULT_BOOK_SLUG` when no `book_slug` parameter is supplied. Removing this default without a coordinated frontend change will cause a regression. **This removal must be gated on a frontend audit confirming all `book_slug` parameters are supplied explicitly.** Do not merge P2-A01 until this audit is complete.
