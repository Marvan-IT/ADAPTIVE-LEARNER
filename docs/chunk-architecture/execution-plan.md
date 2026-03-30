# Execution Plan — ADA Chunk-Based Teaching Pipeline

## Revision History

| Date | Author | Summary |
|------|--------|---------|
| 2026-03-28 | solution-architect | Expanded Phase 5 WBS with explicit bug-fix tasks (F1-a through F1-e), pre-fetch state additions (F2), and updated DoD to cover short-concept Finish button, no difficulty bias UI, pre-fetch behaviour, and blank screen prevention |
| 2026-03-27 | solution-architect | Initial version |

---

**Feature:** Chunk-Based Teaching Pipeline (Mathpix + pgvector)
**Version:** 1.1
**Date:** 2026-03-28
**Author:** solution-architect

---

## Phase Overview

| Phase | Owner | Scope | Done When |
|-------|-------|-------|-----------|
| 0 — Infrastructure | devops-engineer | pgvector extension, Alembic migration (`concept_chunks`, `chunk_images`, new `teaching_sessions` columns), config constants, docker-compose pgvector | `alembic upgrade head` runs clean; tables and HNSW index verified in DB |
| 1 — Design | solution-architect | HLD, DLD, execution-plan in `docs/chunk-architecture/` | This document committed |
| 2 — Extraction | backend-developer | `mmd_parser.py`, `chunk_builder.py`, `graph_builder.py`, `mathpix_pdf_extractor.py`; run pipeline for prealgebra | `SELECT COUNT(*) FROM concept_chunks WHERE book_slug='prealgebra'` > 0; images on disk |
| 3 — Backend Services | backend-developer | `ChunkKnowledgeService`, `TeachingService` hybrid routing, `build_chunk_card_prompt()`, new endpoints (chunk-cards, recovery-card, exam), `main.py` book discovery, `r2_client.py` scaffold | Backend starts without error; `POST /chunks/{id}/cards` returns chunk-based `LessonCard[]` |
| 4 — Tests | comprehensive-tester | Unit + integration tests for all components per DLD Section 9 | All tests pass; coverage targets met per DoD |
| 5 — Frontend | frontend-developer | Dual `image_url`/`image_indices` rendering, Socratic exam UI (typed answers, score display, A/B retry choice), chunk progress indicator | Student completes full section in browser; images display correctly |
| 6 — AWS (deferred) | devops-engineer | ECR, ECS Fargate, RDS pgvector, S3/CloudFront, Secrets Manager, GitHub Actions CI/CD | `git push main` auto-deploys; images load from CloudFront |

**Note:** Phase 6 is deferred until Phases 0–5 are verified working locally on prealgebra.

---

## 1. Work Breakdown Structure (WBS)

### Phase 0 — Infrastructure

| Task ID | Title | Description | Effort (days) | Dependencies | Component |
|---------|-------|-------------|---------------|-------------|-----------|
| P0-01 | Install pgvector extension | Run `CREATE EXTENSION IF NOT EXISTS vector;` on PostgreSQL; verify `extversion >= 0.5.0`; document version | 0.25 | — | PostgreSQL |
| P0-02 | Add pgvector Python package | `pip install pgvector`; add to `requirements.txt`; verify SQLAlchemy `vector(1536)` type maps correctly | 0.25 | P0-01 | backend |
| P0-03 | Remove `Base.metadata.create_all()` | Delete call from `db/connection.py`; replace with comment pointing to Alembic | 0.25 | — | backend/db |
| P0-04 | Alembic migration: `concept_chunks` + `chunk_images` | Migration file adding both tables with all columns, HNSW index, btree composite index, and FK cascade. Include `CREATE EXTENSION IF NOT EXISTS vector` guard. | 1.5 | P0-01, P0-02, P0-03 | backend/db |
| P0-05 | Alembic migration: `teaching_sessions` columns | Migration adding `chunk_index INTEGER DEFAULT 0`, `exam_phase TEXT`, `exam_attempt INTEGER DEFAULT 0`, `exam_scores JSONB`, `failed_chunk_ids TEXT[] DEFAULT '{}'`. All nullable or defaulted — zero impact on existing rows. | 0.5 | P0-03 | backend/db |
| P0-06 | Config constants | Add to `config.py`: `CHUNK_MAX_TOKENS_STRUGGLING=3000`, `CHUNK_MAX_TOKENS_NORMAL=2000`, `CHUNK_MAX_TOKENS_FAST=1200`, `CHUNK_MAX_TOKENS_RECOVERY=800`, `CHUNK_MAX_TOKENS_EXAM_Q=600`, `CHUNK_MAX_TOKENS_EXAM_EVAL=400`, `CHUNK_EXAM_PASS_RATE=0.65`, `IMAGE_STORAGE`, `IMAGE_BASE_URL` | 0.5 | — | backend/config |
| P0-07 | `.env.example` update | Add `IMAGE_STORAGE=local`, `IMAGE_BASE_URL=http://localhost:8889/images` to both `backend/.env.example` and `frontend/.env.example` | 0.25 | P0-06 | config |
| P0-08 | Verify migration on clean DB | Run `alembic upgrade head` from scratch; verify all tables, indexes, and default values; confirm rollback via `alembic downgrade -1` | 0.5 | P0-04, P0-05 | QA |

**Phase 0 total effort:** ~4 days

---

### Phase 1 — Design

| Task ID | Title | Description | Effort (days) | Dependencies | Component |
|---------|-------|-------------|---------------|-------------|-----------|
| P1-01 | HLD.md | High-Level Design document | 0.5 | — | docs |
| P1-02 | DLD.md | Detailed Low-Level Design document | 1.0 | P1-01 | docs |
| P1-03 | execution-plan.md | This document | 0.5 | P1-01, P1-02 | docs |

**Phase 1 total effort:** ~2 days (complete)

---

### Phase 2 — Extraction Pipeline

| Task ID | Title | Description | Effort (days) | Dependencies | Component |
|---------|-------|-------------|---------------|-------------|-----------|
| P2-01 | Test Mathpix PDF API on Chapter 1 | Manual: call Mathpix PDF API for Chapter 1 of prealgebra only; inspect raw `.mmd` for `###`/`####` heading structure; confirm headings match expectations | 0.5 | P0-08 | manual |
| P2-02 | `mathpix_pdf_extractor.py` | Async function: submit PDF to Mathpix PDF API, poll for completion, download `.mmd`, save to `backend/output/{book_slug}/{book_slug}.mmd`. Skip if file exists (idempotent). | 1.0 | P2-01 | backend/extraction |
| P2-03 | `mmd_parser.py` | Implement heading hierarchy parser per DLD Appendix A. Handle all three content cases: normal `####`, orphan text, chapter-level summaries. CDN URL extraction. 3-copy deduplication. | 2.0 | P2-01 | backend/extraction |
| P2-04 | `chunk_builder.py` | Implement per DLD Appendix B. CDN image download with SHA-256 filename. Embedding via `text-embedding-3-small`. Idempotent INSERT. `chunk_images` linking. | 2.0 | P2-03, P0-04 | backend/extraction |
| P2-05 | `graph_builder.py` | Read `mmd_parser` output; build nodes (one per `###`); sequential edges within chapters; LLM cross-chapter prerequisite extraction; save `graph.json` in existing format | 1.5 | P2-03 | backend/extraction |
| P2-06 | `pipeline.py` orchestration update | Extend existing `pipeline.py` entry point to call new extraction chain for chunk path; preserve existing ChromaDB extraction for other books | 0.5 | P2-02, P2-04, P2-05 | backend |
| P2-07 | Run extraction for prealgebra | Execute pipeline on prealgebra book; monitor logs; verify row counts (`concept_chunks`, `chunk_images`); verify sample images on disk | 0.5 | P2-06 | ops |
| P2-08 | Verify extraction completeness | Run queries: COUNT by section, check orphan chunks captured, check image rows, check HNSW index populated | 0.5 | P2-07 | QA |

**Phase 2 total effort:** ~8.5 days

---

### Phase 3 — Backend Services

| Task ID | Title | Description | Effort (days) | Dependencies | Component |
|---------|-------|-------------|---------------|-------------|-----------|
| P3-01 | ORM models for new tables | Add `ConceptChunk` and `ChunkImage` SQLAlchemy models to `db/models.py` with all columns and relationships | 0.5 | P0-04 | backend/db |
| P3-02 | `ChunkKnowledgeService` | New class in `knowledge_service.py`. Methods: `get_chunk(chunk_id)`, `get_section_chunks(book_slug, concept_id)`, `similarity_search(embedding, book_slug, k=5)`. Queries `concept_chunks` + `chunk_images` via async SQLAlchemy. | 1.5 | P3-01, P2-07 | backend |
| P3-03 | `main.py` hybrid book discovery | Replace `_discover_processed_books()` filesystem scan with dual-source detection: check `concept_chunks` COUNT per book_slug; fall back to `chroma_db/` directory. Register `ChunkKnowledgeService` or `ChromaKnowledgeService` accordingly. | 1.0 | P3-02 | backend |
| P3-04 | `build_chunk_card_prompt()` | Add new function to `prompt_builder.py`. Accepts: chunk (heading, text, latex, images), student profile (mode, interests, style, language), `is_exercise_chunk: bool`. Returns prompt string per DLD Section 5.2. Does NOT touch existing prompt functions. | 1.5 | — | backend/adaptive |
| P3-05 | `build_exam_question_prompt()` | Add to `prompt_builder.py`. Accepts: list of teaching chunks for section, student language. Returns prompt generating 2 typed questions per chunk. | 0.75 | — | backend/adaptive |
| P3-06 | `build_exam_eval_prompt()` | Add to `prompt_builder.py`. Accepts: question, student answer. Returns prompt that evaluates correctness with brief reasoning. | 0.5 | — | backend/adaptive |
| P3-07 | `TeachingService.generate_chunk_cards()` | New method. Loads chunk + images from `ChunkKnowledgeService`. Builds prompt. Calls OpenAI (vision if images, text if none). Parses JSON. Injects `chunk_id` and `image_url`. Updates `chunk_index` in session. Returns `list[LessonCard]`. | 2.0 | P3-02, P3-04 | backend |
| P3-08 | `TeachingService.generate_recovery_card()` | New method. Accepts chunk + `failed_card_index` + `wrong_answer` + mode. Generates one recovery content card + new MCQ from same paragraph using `CHUNK_MAX_TOKENS_RECOVERY`. | 1.0 | P3-04 | backend |
| P3-09 | `TeachingService.run_exam()` (start) | New method. Verifies all chunks complete. Loads teaching-type chunks. Generates 2 questions per chunk. Stores questions in `session.exam_scores` JSONB (pending answers). Sets `exam_phase = 'exam'`. | 1.5 | P3-05 | backend |
| P3-10 | `TeachingService.submit_exam()` | New method. Evaluates typed answers via GPT-4o (one call per answer). Computes per-chunk scores. Determines pass/fail. Sets `failed_chunk_ids`. Inserts `student_mastery` on pass. Handles XP award. | 2.0 | P3-06 | backend |
| P3-11 | `TeachingService.set_retry()` | New method. Validates attempt limit. Sets `exam_phase = 'retry_study'` or `'retry_exam'`. Updates `exam_attempt`. Returns retry chunks list. | 0.75 | — | backend |
| P3-12 | New Pydantic schemas | Add to `teaching_schemas.py`: `ChunkCardsRequest`, `ChunkCardsResponse`, `RecoveryCardRequest`, `RecoveryCardResponse`, `ExamStartRequest`, `ExamStartResponse`, `ExamSubmitRequest`, `ExamSubmitResponse`, `ExamRetryRequest`, `ExamRetryResponse`. Update `LessonCard` per DLD Section 2.3. | 1.5 | — | backend |
| P3-13 | New API endpoints in `teaching_router.py` | Wire all 6 new endpoints per DLD Section 3.1. Connect to `TeachingService` methods. Apply existing auth middleware automatically (no extra decoration needed). | 1.5 | P3-07 to P3-12 | backend |
| P3-14 | `r2_client.py` scaffold | Implement `resolve_image_url()` (reads `IMAGE_STORAGE` env var; returns url as-is for both local and R2). Stub `upload_image()` for future Phase 6 use. Add `boto3` to `requirements.txt`. | 0.5 | P0-06 | backend/storage |
| P3-15 | FastAPI static mount for `images_downloaded/` | Ensure `main.py` mounts `backend/output/{book_slug}/images_downloaded/` at `/images/{book_slug}/images_downloaded/` for local dev. Confirm existing images mount unaffected. | 0.25 | — | backend |
| P3-16 | End-to-end smoke test (manual) | Start backend; call `GET /chunks`, `POST /chunks/{id}/cards` for a prealgebra chunk; verify JSON response, `image_url` populated, `chunk_index` incremented in DB | 0.5 | P3-13, P2-07 | QA |

**Phase 3 total effort:** ~17.25 days

---

### Phase 4 — Tests

| Task ID | Title | Description | Effort (days) | Dependencies | Component |
|---------|-------|-------------|---------------|-------------|-----------|
| P4-01 | `test_mmd_parser.py` | All 8 unit tests from DLD Section 9.1. Use sample `.mmd` fixtures — no external API calls. | 1.5 | P2-03 | tests |
| P4-02 | `test_chunk_builder.py` | All 5 integration tests from DLD Section 9.2. Use real test DB (no mocks). Use pre-downloaded test images (no CDN calls). | 1.5 | P2-04, P0-08 | tests |
| P4-03 | `test_chunk_card_generation.py` | All 9 unit tests from DLD Section 9.3. Mock OpenAI client. Use fixture chunks with and without images. | 2.0 | P3-07, P3-08 | tests |
| P4-04 | `test_mode_adaptation.py` | All 4 unit tests from DLD Section 9.4. Use fixture chunk with known paragraph count. | 1.0 | P3-07 | tests |
| P4-05 | `test_socratic_exam.py` | All 7 unit tests from DLD Section 9.5. Mock OpenAI for question generation and evaluation. | 2.0 | P3-09, P3-10, P3-11 | tests |
| P4-06 | `test_session_persistence.py` | All 4 integration tests from DLD Section 9.6. Use real DB. Verify DB state after each action. | 1.5 | P3-07, P3-09 | tests |
| P4-07 | `test_hybrid_routing.py` | All 3 integration tests from DLD Section 9.7. Test both routing paths; verify existing ChromaDB sessions unaffected. | 1.0 | P3-03 | tests |
| P4-08 | Performance baseline | Measure per-chunk card generation latency (text and vision); pgvector search latency; record as baseline for regressions | 0.5 | P4-03 | tests |

**Phase 4 total effort:** ~11 days

---

### Phase 5 — Frontend

#### P5 Group 1: Bug Fixes (must complete before new feature work)

| Task ID | Title | Description | Effort (days) | Dependencies | Component |
|---------|-------|-------------|---------------|-------------|-----------|
| F1-a | Remove `MIN_CARDS_BEFORE_FINISH` guard | Delete the `MIN_CARDS_BEFORE_FINISH = 4` constant and any guard logic in `CardLearningView.jsx` that prevents the Finish button appearing when `cards.length < 4`. Short concepts (≤ 3 cards, `has_more_concepts: false`) must show the Finish button — the Next button must not be stuck. | 0.25 | — | frontend |
| F1-b | Remove difficulty bias UI buttons | Remove TOO_EASY / TOO_HARD buttons and `SET_DIFFICULTY_BIAS` dispatch from `CardLearningView.jsx`. Remove `difficultyBias` from SessionContext state and the `ADAPTIVE_CARD_LOADED` clear logic. Per ADR-07: difficulty is fixed; presenting these buttons contradicts the fixed-difficulty design. | 0.5 | — | frontend |
| F1-c | Fix `canProceed` to use `question` field | Replace any `card.card_type === "CHECKIN"` (or equivalent `card_type` check) in `canProceed` logic with `card.question != null`. Chunk-path cards carry no `card_type` field — only `question` presence distinguishes MCQ from content cards. | 0.25 | — | frontend |
| F1-d | Fix image rendering priority | Update `CardLearningView.jsx` image display: check `card.image_url` first (chunk path); fall back to `card.image_indices` resolution only when `image_url` is null (ChromaDB path). Zero breakage on existing ChromaDB sessions. | 0.5 | — | frontend |
| F1-e | Remove rolling-batch dead code | Remove or stub out `getNextSectionCards` (the rolling-batch card fetch function) in `sessions.js`. Mark with `// DEPRECATED: replaced by chunk-based per-section fetching` if a full removal requires other changes; otherwise delete. Prevents confusion during chunk-path implementation. | 0.25 | — | frontend/api |

**Group 1 subtotal:** ~1.75 days

#### P5 Group 2: New Feature Work

| Task ID | Title | Description | Effort (days) | Dependencies | Component |
|---------|-------|-------------|---------------|-------------|-----------|
| P5-01 | `sessions.js` API wrappers | Add Axios wrappers for all 6 new endpoints (`GET /chunks`, `POST /chunks/{id}/cards`, `POST /recovery-card`, `POST /exam/start`, `POST /exam/submit`, `POST /exam/retry`). Follow existing pattern: named async functions, error handling via `console.error`. | 1.0 | P3-13 | frontend/api |
| P5-02 | SessionContext state + reducer | Add new state fields: `chunkList`, `chunkIndex`, `nextChunkCards`, `nextChunkInFlight`. Add reducer cases: `CHUNK_LIST_LOADED`, `CHUNK_CARDS_LOADED`, `NEXT_CHUNK_FETCH_STARTED`, `NEXT_CHUNK_CARDS_READY`, `CHUNK_ADVANCE`, `EXAM_STARTED`, `EXAM_SUBMITTED`, `EXAM_RETRY_SET`. Update `startLesson` flow: call `GET /chunks` first; if `chunks: []` fall back to ChromaDB path. Store `chunkIndex`, `examPhase`, `examQuestions`, `examScores`. | 2.0 | P5-01 | frontend |
| P5-03 | Pre-fetch next chunk | Wire the inter-chunk pre-fetch strategy (DLD Section 3.6): when student reaches second-to-last card of current chunk, silently call `POST /chunks/{next}/cards` in background. On "Next Section" click: swap from `nextChunkCards` instantly if ready; show spinner if still in flight. Use `nextChunkInFlight` flag to prevent duplicate fetches. | 1.0 | P5-02 | frontend |
| P5-04 | Chunk progress indicator | Add visual indicator to `CardLearningView.jsx` showing current chunk position within section (e.g. "Subsection 2 of 4"). Read from `chunkList` in context state. Show nothing on ChromaDB-path sessions. | 0.75 | P5-02 | frontend |
| P5-05 | Socratic exam question UI | New component (or view within `LearningPage.jsx`): render typed-answer questions one at a time; text input with submit; show question number/total; no back navigation during exam. All text via `t()` calls. | 1.5 | P5-01 | frontend |
| P5-06 | Exam score display | After exam submission: show score (`5/8 = 62%`), pass/fail indicator, list of failed subsection names. All text via `useTranslation()` / `t()` calls. | 0.75 | P5-05 | frontend |
| P5-07 | A/B retry choice UI | After exam failure: show two buttons ("Review failed sections" / "Start from beginning"). Disable targeted retry after 3 attempts (show only full redo). Call `POST /exam/retry`. | 1.0 | P5-06 | frontend |
| P5-08 | i18n keys for new UI strings | Add translation keys for exam UI to all 13 locale files: `exam.question`, `exam.yourAnswer`, `exam.submit`, `exam.score`, `exam.passed`, `exam.failed`, `exam.retryTargeted`, `exam.retryFull`, `exam.attempt`, `exam.passThreshold`, `chunk.loadingNext`, `chunk.progress`. | 1.0 | P5-06, P5-07 | frontend |
| P5-09 | End-to-end browser test (manual) | Walk through a full prealgebra section in the browser: chunks → cards → MCQ pass/fail/recovery/RECAP → exercise chunk → Socratic exam → pass → mastery recorded. Verify: images display, short concepts show Finish not stuck Next, no difficulty bias buttons visible, section transitions are instant or show spinner (never blank screen). | 0.5 | P5-07, P5-08 | QA |

**Group 2 subtotal:** ~9.5 days

**Phase 5 total effort:** ~11.25 days (Group 1 + Group 2)

---

### Phase 6 — AWS Deployment (Deferred)

| Task ID | Title | Description | Effort (days) | Dependencies | Component |
|---------|-------|-------------|---------------|-------------|-----------|
| P6-01 | R2/S3 image upload script | One-time script: upload all `backend/output/*/images_downloaded/` to Cloudflare R2 bucket; update `chunk_images.image_url` rows to R2 URLs | 1.0 | Phases 0–5 | backend/scripts |
| P6-02 | RDS PostgreSQL + pgvector | Provision RDS PostgreSQL 15 with pgvector extension; run `alembic upgrade head`; verify HNSW index | 1.0 | P0-08 | infra |
| P6-03 | ECR + Docker image | Dockerfile for backend (multi-stage); push to ECR; Docker Compose for local parity | 1.0 | — | infra |
| P6-04 | ECS Fargate task definition | Task def with env vars from Secrets Manager; health check `/health`; autoscaling on CPU 70% | 1.0 | P6-02, P6-03 | infra |
| P6-05 | CloudFront for images | CloudFront distribution fronting R2/S3 image bucket; cache headers 30 days; update `IMAGE_BASE_URL` | 0.75 | P6-01 | infra |
| P6-06 | GitHub Actions CI/CD | On push to `main`: run pytest, build Docker image, push to ECR, deploy to ECS Fargate | 1.5 | P6-03, P6-04 | CI/CD |
| P6-07 | Secrets Manager integration | Rotate `API_SECRET_KEY`, `OPENAI_API_KEY`, `DATABASE_URL` via AWS Secrets Manager; update ECS task env | 0.5 | P6-04 | infra |
| P6-08 | Smoke test on production | Hit production endpoints: GET /health, POST /chunks/{id}/cards, GET an image URL via CloudFront | 0.5 | P6-01–P6-07 | QA |

**Phase 6 total effort:** ~7.25 days

---

## 2. Dependencies and Critical Path

```
P0-01 → P0-02 → P0-04 ──────────────────────────────┐
P0-03 ──────────────────────────────────────────────►P0-08
P0-04 ──────────────────────────────────────────────►P0-08
P0-05 ──────────────────────────────────────────────►P0-08

P0-08 → P2-07 (need tables before populating them)
P2-01 → P2-02 → P2-06 → P2-07 → P2-08
P2-01 → P2-03 → P2-04 → P2-06
P2-03 → P2-05

CRITICAL PATH:
P0-01 → P0-02 → P0-04 → P0-08 → P2-07 → P3-02 → P3-07 → P3-13 → P5-01 → P5-09

Key blocking dependencies:
- P2-01 (Mathpix API test): blocks ALL extraction work. Must be verified manually before P2-02+.
- P0-04 (Alembic migration): blocks all backend service work that touches new tables.
- P3-07 (generate_chunk_cards): blocks P4-03 and P5-02 (core card generation path).
- P3-09 + P3-10 (exam): blocks P4-05 and P5-05.
- F1-a through F1-e (Group 1 bug fixes): should be completed before P5-02+ to avoid regressions introduced while extending SessionContext. These have NO backend dependencies and can start immediately.
```

**External blocking dependencies:**
- Mathpix PDF API plan/quota access — must be confirmed by stakeholder before Phase 2 starts (see HLD Section 7 risks)
- GPT-4o vision API access — existing OpenAI account; confirm `gpt-4o` model has vision enabled in account settings before P3-07

---

## 3. Definition of Done (DoD)

### Phase 0
- [ ] `alembic upgrade head` runs cleanly from scratch with no errors
- [ ] `\d concept_chunks` shows all columns including `embedding vector(1536)`
- [ ] HNSW index visible in `\di concept_chunks*`
- [ ] `teaching_sessions` shows new columns with correct defaults
- [ ] `alembic downgrade -1` successfully reverts both migrations
- [ ] All new constants present in `config.py`
- [ ] `.env.example` files updated

### Phase 1
- [ ] `docs/chunk-architecture/HLD.md` committed
- [ ] `docs/chunk-architecture/DLD.md` committed
- [ ] `docs/chunk-architecture/execution-plan.md` committed

### Phase 2
- [ ] `SELECT COUNT(*) FROM concept_chunks WHERE book_slug='prealgebra'` > 0
- [ ] Every `###` section in prealgebra has at least one `concept_chunks` row
- [ ] `SELECT COUNT(*) FROM chunk_images WHERE chunk_id IN (SELECT id FROM concept_chunks WHERE book_slug='prealgebra')` > 0
- [ ] Sample chunk from each content type (orphan, subsection, chapter summary) present in DB
- [ ] Image files on disk at `backend/output/prealgebra/images_downloaded/`
- [ ] `graph.json` updated with nodes and edges derived from `.mmd`
- [ ] Re-running the pipeline does not create duplicate rows

### Phase 3
- [ ] `GET /api/v2/sessions/{id}/chunks` returns ordered chunk list for a prealgebra session
- [ ] `POST /api/v2/sessions/{id}/chunks/{chunk_id}/cards` returns valid `LessonCard[]` JSON
- [ ] Response contains interleaved content + MCQ pairs for normal teaching chunk
- [ ] `card.image_url` is a valid accessible URL when chunk has images
- [ ] `chunk_index` in DB incremented after successful card generation call
- [ ] `POST /recovery-card` returns a new card with `is_recovery = true`
- [ ] `POST /exam/start` returns questions; `POST /exam/submit` returns score; `POST /exam/retry` updates `exam_phase`
- [ ] Existing ChromaDB-path sessions (non-prealgebra books) still function correctly
- [ ] Backend starts without errors; no regressions in existing endpoint tests
- [ ] All new endpoints return correct HTTP status codes per DLD Section 3.5

### Phase 4
- [ ] All unit tests pass (zero failures, zero skips)
- [ ] All integration tests pass against real test DB
- [ ] `test_hybrid_routing.py`: ChromaDB and chunk paths verified independently
- [ ] `test_socratic_exam.py`: all 7 exam scenarios covered
- [ ] Performance baseline recorded: chunk card generation p50 < 4s (text), p50 < 8s (vision)
- [ ] No regressions in existing test files (if any still present)

### Phase 5
- [ ] Short concept (≤ 3 cards, `has_more_concepts: false`) — Finish button appears immediately; Next button is NOT stuck
- [ ] No TOO_EASY / TOO_HARD difficulty bias buttons visible anywhere in the card learning view
- [ ] `canProceed` gate uses `card.question != null` (not `card_type`) — MCQ and content cards distinguished correctly
- [ ] Student sees correct image on image-bearing card (`card.image_url` used first; `image_indices` fallback only when `image_url` is null)
- [ ] ChromaDB-path cards still display images via `image_indices` fallback (zero regression)
- [ ] `getNextSectionCards` deprecated stub or removed — no rolling-batch fetch code active
- [ ] `GET /chunks` called at lesson start; `chunks: []` triggers ChromaDB fallback path automatically
- [ ] Second-to-last card of each chunk silently pre-fetches the next chunk in background
- [ ] "Next Section" transition is instant (pre-fetch ready) or shows animated spinner (pre-fetch still running) — never a blank screen
- [ ] Chunk progress indicator visible during session (chunk path only; hidden on ChromaDB path)
- [ ] Socratic exam UI renders typed-answer questions; submits answers; displays score
- [ ] A/B retry choice appears on exam failure; targeted retry disabled after 3 attempts
- [ ] All new UI strings present in all 13 locale files (`exam.*` and `chunk.*` keys)
- [ ] No hardcoded English strings in new UI components
- [ ] WCAG 2.1 AA: exam input accessible via keyboard; score result announced to screen readers

### Phase 6 (deferred)
- [ ] `git push main` triggers GitHub Actions CI that builds, tests, and deploys automatically
- [ ] Images load from CloudFront URL in production with < 100 ms latency
- [ ] RDS `alembic upgrade head` applied; HNSW index verified on production DB
- [ ] No secrets in environment variables in plain text — all via Secrets Manager

---

## 4. Rollout Strategy

### Deployment Approach

**Feature-flag pattern (implicit via hybrid routing):** prealgebra is migrated to chunk path by running the extraction pipeline. Other books continue on ChromaDB. No feature flag toggle required — the presence of `concept_chunks` rows is the flag.

**Local verification before any cloud deployment:** Phases 0–5 must be completed and manually verified (P3-16, P5-09) on the developer's machine before any cloud infrastructure (Phase 6) is provisioned.

### Rollback Plan

| Scope | Rollback action |
|-------|----------------|
| Phase 0 migration | `alembic downgrade -1` (twice to revert both migrations); new columns dropped, tables dropped |
| Phase 2 extraction | `DELETE FROM concept_chunks WHERE book_slug='prealgebra'` (cascades to chunk_images); re-run ChromaDB extraction if needed |
| Phase 3 endpoints | Remove new router registrations from `teaching_router.py`; revert `main.py` book discovery to filesystem-only scan |
| Phase 5 frontend | Revert `CardLearningView.jsx` dual image logic to original `image_indices`-only path |

All rollbacks are non-destructive to student data (`students`, `teaching_sessions`, `student_mastery`, `conversation_messages` tables unchanged).

### Monitoring Setup for Launch

Before opening prealgebra chunk path to real students:
1. Confirm structured logging outputs to console (and to log aggregator in Phase 6)
2. Verify `chunk_index` persists correctly across simulated session interruptions
3. Run full section 1.1 manually as a student (P5-09 smoke test)
4. Confirm exam pass inserts `student_mastery` row correctly
5. Confirm concept graph shows section 1.2 as unlocked after section 1.1 mastered

### Post-Launch Validation Steps

1. Monitor logs for LLM retry warnings (> 5% retry rate indicates prompt or timeout issue)
2. Monitor image 404 errors (indicates `image_url` resolution problem)
3. Review exam pass rates after first 10 real student attempts (expect 60–80% first-attempt pass)
4. Check `chunk_index` values in DB for any sessions that appear stuck (index not advancing)

---

## 5. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members |
|-------|-----------|-----------------|--------------|
| 0 — Infrastructure | pgvector migration, config constants | ~4 days | devops-engineer |
| 1 — Design | HLD, DLD, execution-plan | ~2 days | solution-architect (complete) |
| 2 — Extraction | mmd_parser, chunk_builder, graph_builder, pipeline run | ~8.5 days | backend-developer |
| 3 — Backend Services | ChunkKnowledgeService, card generation, exam endpoints | ~17.25 days | backend-developer |
| 4 — Tests | Unit + integration for all components | ~11 days | comprehensive-tester |
| 5 — Frontend (Group 1: bug fixes) | MIN_CARDS guard, bias UI removal, canProceed fix, image rendering, dead code | ~1.75 days | frontend-developer |
| 5 — Frontend (Group 2: new features) | sessions.js, SessionContext, pre-fetch, chunk progress, exam UI, i18n | ~9.5 days | frontend-developer |
| 6 — AWS (deferred) | RDS, ECS, CloudFront, CI/CD | ~7.25 days | devops-engineer |
| **Total (Phases 0–5)** | | **~53.5 days** | |
| **Total with Phase 6** | | **~60.75 days** | |

**Parallelism opportunities:**
- Phase 3 and Phase 4 can overlap: tests are written against mocked OpenAI as Phase 3 services are delivered incrementally.
- Phase 5 Group 1 (bug fixes) can begin immediately — these have no backend dependencies and should be completed before any new feature work starts to prevent regressions.
- Phase 5 Group 2 can begin with P5-01 (`sessions.js` API wrappers) and P5-02 (SessionContext reducer) as soon as Phase 3 schemas are finalised (P3-12).
- With 3 parallel agents (backend, tester, frontend) working concurrently on Phases 3/4/5, calendar time reduces to approximately 21–23 calendar days.

---

## 6. Key Decisions Requiring Stakeholder Input

1. **Mathpix PDF API access:** The Mathpix PDF API is distinct from the per-image OCR API already in use. Access must be confirmed and tested on Chapter 1 before Phase 2 begins. The entire extraction pipeline depends on this.

2. **Migration timeline for remaining 15 books:** This plan migrates only prealgebra. A decision is needed on when and in what order the remaining 15 books will be migrated to chunk path, and whether the ChromaDB code should be preserved indefinitely or given a sunset date.

3. **Card caching (Phase 3 vs future):** Generated cards are not cached in Phase 3. Every student session generates new cards via LLM. If OpenAI costs become significant, a JSONB card cache keyed on `(chunk_id, mode, style, language)` should be promoted from "future optimization" to Phase 3 scope.

4. **Exam question source:** Exam questions are LLM-generated (2 per subsection). If pedagogical quality requires human-authored questions for key concepts, a question-bank table should be added to the schema and this work assigned to Phase 3.

5. **Phase 6 timing:** Phase 6 (AWS deployment) is explicitly deferred. A milestone decision is needed on when Phase 6 begins and whether it runs in parallel with Phase 5 or sequentially after.

6. **Image URL scheme for `chunk_images`:** Local development stores images at `backend/output/{book_slug}/images_downloaded/{filename}` and serves them via FastAPI static mount. If the domain or port changes in staging or production before Phase 6 is complete, `chunk_images.image_url` rows will need to be updated. A decision is needed on whether to store relative paths in the DB (resolved at serve time) rather than absolute URLs.
