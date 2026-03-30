# High-Level Design — ADA Chunk-Based Teaching Pipeline

**Feature:** Chunk-Based Teaching Pipeline (Mathpix + pgvector)
**Version:** 1.0
**Date:** 2026-03-27
**Author:** solution-architect

---

## 1. Executive Summary

### Feature Name and Purpose

The ADA Chunk-Based Teaching Pipeline replaces the existing PyMuPDF extraction, ChromaDB vector store, and batch card generation with a unified pipeline built on Mathpix PDF API, PostgreSQL pgvector, and per-chunk LLM card generation with genuine style adaptation.

### Business Problem Being Solved

The current platform has three compounding problems that degrade learning quality:

**Problem 1 — Image-text co-location is permanently lost at extraction time.**
PyMuPDF extracts text and images in separate passes. The spatial relationship between a diagram and its explanation is broken before any card is generated. Images are then matched to cards by loose `concept_id` keyword lookup, producing wrong or missing images on a significant fraction of cards.

**Problem 2 — ChromaDB cannot scale.**
ChromaDB is a single-node embedded store. It cannot scale horizontally, has no replication, and requires a fragile `image_index.json` sidecar file for image mapping. It is not suitable for production with concurrent students across 16 books.

**Problem 3 — Adaptation changes card count but not presentation style.**
Cards are generated from multiple unrelated concept blocks retrieved by semantic search across the entire book — not from coherent subsection-level passages. The adaptation engine changes card count and MCQ difficulty per student mode, but does not adapt the writing style (vocabulary, analogy density, step depth, language register) because the source material is fragmented across concept blocks rather than anchored to a single coherent passage.

### Intended Outcome

Every student covers every concept in the textbook in its natural textbook order. No content is ever skipped. Adaptation changes only HOW the content is presented — not what is covered. Images on cards are always the correct diagram because they are stored together with their text at extraction time.

### Key Stakeholders

- Students: direct experience of correct images and style-adapted content
- Backend team: new extraction pipeline and service layer
- Frontend team: updated card rendering and exam UI
- DevOps: Alembic migration, pgvector extension, image storage

### Scope

**Included:**
- Mathpix `.mmd` → chunk parser → chunk builder → PostgreSQL pgvector extraction pipeline
- Hybrid book routing: prealgebra uses pgvector; other 15 books continue on ChromaDB
- Per-chunk LLM card generation with genuine style adaptation (vocabulary, analogies, step depth)
- Socratic typed-answer exam after each section with A/B retry choice
- Image co-location: images stored with their chunk at extraction time, sent to GPT-4o vision
- `concept_chunks` and `chunk_images` tables in PostgreSQL

**Explicitly Excluded:**
- Migration of all 16 books simultaneously (prealgebra first; others converted on demand)
- Cloudflare R2 image upload (local filesystem for development; R2 is deferred to Phase 6)
- AWS ECS/Fargate deployment (deferred to Phase 6 after local verification)
- Student authentication and multi-tenancy overhaul (out of scope per existing tech debt list)

---

## 2. Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-01 | Extract every subsection of a book from Mathpix `.mmd` into discrete chunks preserving heading hierarchy, LaTeX, and image co-location | Critical |
| FR-02 | Store chunks in PostgreSQL `concept_chunks` with pgvector embeddings for semantic retrieval | Critical |
| FR-03 | Store chunk images in `chunk_images` table, linked by `chunk_id` foreign key, with permanent URLs | Critical |
| FR-04 | Generate all cards for a chunk in a single LLM call at the start of that chunk | Critical |
| FR-05 | Adapt card writing style per student mode (STRUGGLING / NORMAL / FAST) at each chunk boundary | Critical |
| FR-06 | Send chunk images to GPT-4o vision when the chunk has images; use text-only call otherwise | Critical |
| FR-07 | Attach the correct image URL to each card — no keyword guessing | Critical |
| FR-08 | Require MCQ pass before advancing to the next chunk | Critical |
| FR-09 | Generate a recovery card on first MCQ failure; show a RECAP card on second failure | High |
| FR-10 | Trigger a typed-answer Socratic exam after all chunks in a section are complete | Critical |
| FR-11 | Score exam at 65% pass threshold; identify failed subsections by chunk | Critical |
| FR-12 | Present student with A/B retry choice after exam failure (targeted retry or full redo) | High |
| FR-13 | Limit targeted retry to 3 attempts; after attempt 3, only full redo is offered | High |
| FR-14 | Persist chunk progress (`chunk_index`) and exam state to DB; resume correctly on re-entry | Critical |
| FR-15 | Route books to correct service: `concept_chunks` rows present → pgvector; otherwise → ChromaDB | Critical |
| FR-16 | Guarantee 100% PDF content coverage — no blocks dropped (including Be Careful, Try It, Exercises, Learning Objectives, Chapter Summaries) | High |
| FR-17 | Build and save `graph.json` (concept dependency graph) from `.mmd` heading structure | High |
| FR-18 | Support 13 student languages for card content generation | High |
| FR-19 | Exercise chunk generates 2 MCQ cards per preceding teaching subsection in the section | High |
| FR-20 | Book discovery queries `concept_chunks` table rather than filesystem `chroma_db/` directory | High |

---

## 3. Non-Functional Requirements

### Performance
- Card generation per chunk: median < 4 s (text-only), median < 8 s (vision), p99 < 15 s
- pgvector cosine similarity search on `concept_chunks`: < 50 ms for up to 10,000 rows per book
- Static image delivery: < 100 ms (local filesystem dev); < 50 ms (CloudFront CDN prod)
- Chunk extraction pipeline for prealgebra (~400 chunks): completes in < 30 minutes end-to-end

### Scalability
- `concept_chunks` HNSW index supports up to ~10,000 rows per book before requiring IVFFlat tuning
- Horizontal scaling of FastAPI workers is viable because all state is in PostgreSQL (not in-memory ChromaDB)
- Image storage switches from local filesystem to R2/S3 via env var — zero schema changes

### Availability and Reliability
- Session state persisted to DB after every chunk boundary; student never loses more than one in-progress chunk on crash
- Hybrid routing ensures existing ChromaDB books remain fully functional during prealgebra migration
- Recovery cards and RECAP cards prevent students from being stuck indefinitely

### Security and Compliance
- Image URLs are served from a static path (`/images/`) — no signed URL complexity in development
- No student PII in `concept_chunks` or `chunk_images` tables
- Mathpix API key stored in `backend/.env` — not committed; validated at startup

### Maintainability and Observability
- All configuration constants (`CHUNK_MAX_TOKENS_*`, `CHUNK_EXAM_PASS_RATE`) in `config.py`
- Structured Python `logging` throughout extraction pipeline and service layer
- Alembic migrations are the sole schema change path — `Base.metadata.create_all()` removed

---

## 4. System Context Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  EXTRACTION PIPELINE  (offline — run once per book)                         │
│                                                                             │
│  prealgebra.pdf                                                             │
│       │                                                                     │
│       ▼                                                                     │
│  Mathpix PDF API ──────────────────────────────► book.mmd (cached, 1.8 MB) │
│                                                        │                   │
│                                                        ▼                   │
│                                                 mmd_parser.py              │
│                                               (heading hierarchy,           │
│                                                image URL extraction)        │
│                                                        │                   │
│                                                        ▼                   │
│                                                 chunk_builder.py            │
│                                          (download CDN images, embed,       │
│                                           INSERT concept_chunks +           │
│                                           chunk_images)                     │
│                                                   │          │             │
│                                                   ▼          ▼             │
│                                             PostgreSQL   local disk         │
│                                             pgvector     images/           │
└───────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  GRAPH BUILDER  (offline — run once per book)                               │
│                                                                             │
│  mmd_parser output                                                          │
│       │                                                                     │
│       ▼                                                                     │
│  graph_builder.py                                                           │
│  (### nodes, sequential edges, LLM cross-chapter edges)                     │
│       │                                                                     │
│       ▼                                                                     │
│  graph.json  (same format as existing — ConceptMapPage unchanged)           │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  RUNTIME — PER-SESSION REQUEST FLOW                                         │
│                                                                             │
│  Student browser                                                            │
│       │  POST /api/v2/sessions/{id}/chunks/{chunk_id}/cards                 │
│       ▼                                                                     │
│  FastAPI (teaching_router.py)                                               │
│       │                                                                     │
│       ▼                                                                     │
│  ChunkKnowledgeService                                                      │
│  (pgvector SQL: SELECT * FROM concept_chunks WHERE ...)                     │
│       │                                                                     │
│       ├─► chunk has images? ──YES──► GPT-4o vision call                    │
│       │                                                                     │
│       └─► no images?        ──────► GPT-4o text call                       │
│                                           │                                │
│                                           ▼                                │
│                                   LessonCard[] JSON                        │
│                                   (interleaved content + MCQ pairs)        │
│                                           │                                │
│                                           ▼                                │
│                               Frontend — CardLearningView.jsx              │
│                               (renders card.image_url directly)            │
│                                                                             │
│  Socratic exam  POST /api/v2/sessions/{id}/exam                            │
│       │                                                                     │
│       ▼                                                                     │
│  TeachingService.run_socratic_exam()                                        │
│       │                                                                     │
│       ▼                                                                     │
│  GPT-4o evaluates typed answers → score → pass/fail → INSERT student_mastery│
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  HYBRID BOOK ROUTING  (during prealgebra-first migration)                   │
│                                                                             │
│  main.py lifespan                                                           │
│       │                                                                     │
│       ├─► concept_chunks rows exist for book? → ChunkKnowledgeService      │
│       │                                                                     │
│       └─► chroma_db/ directory exists?       → ChromaKnowledgeService      │
└─────────────────────────────────────────────────────────────────────────────┘

STORAGE TIERS

  Tier 1: PostgreSQL 15 + pgvector
    concept_chunks (text, LaTeX, embedding vector(1536))
    chunk_images   (image_url, caption — linked to chunk)
    teaching_sessions + chunk_index + exam_phase columns
    All existing student/mastery/session tables (unchanged)

  Tier 2: Local filesystem (development)
    backend/output/{book_slug}/images_downloaded/*.jpg
    Served as static files by FastAPI at /images/{book_slug}/...

  Tier 3: Cloudflare R2 / AWS S3 (production — Phase 6)
    Same image files; switch via IMAGE_STORAGE=r2 env var
    Zero schema changes required
```

---

## 5. Architectural Style and Patterns

### Selected Style: Layered Monolith with Pluggable Storage Backends

The existing ADA codebase is a layered FastAPI monolith. This redesign extends that pattern with two explicit choices:

**Pluggable knowledge backend (strategy pattern):** `ChunkKnowledgeService` and the existing `ChromaKnowledgeService` share the same interface. The router calls whichever service is registered for the book at startup. This allows parallel operation of old and new paths without any conditional logic in route handlers.

**Offline extraction pipeline (separate from runtime):** Extraction (`mmd_parser`, `chunk_builder`, `graph_builder`) runs offline as a CLI command — not as part of the API server. This is consistent with the existing `pipeline.py` pattern.

### Why Not Microservices

The team is small (one agent per domain). Microservices would add significant operational overhead (service discovery, inter-service auth, distributed tracing) that is not justified at current scale. The pluggable backend pattern provides the isolation needed without splitting the deployment unit.

### Why pgvector Over Managed Vector Database

| Option | Pros | Cons |
|--------|------|------|
| pgvector (chosen) | Single DB for all data; ACID; existing Alembic; no extra service | HNSW index rebuild on large datasets |
| Pinecone / Weaviate | Horizontally scalable vector ops | Extra service, cost, latency hop, separate auth |
| ChromaDB (existing) | Already deployed | Single-node, no replication, fragile sidecar files |

For ADA's volume (~400 chunks per book, 16 books = ~6,400 total rows), pgvector HNSW performs well within SLA targets. The scalability ceiling is acceptable for the current product phase.

---

## 6. Technology Stack

| Concern | Technology | Rationale |
|---------|-----------|-----------|
| Text + embedding storage | PostgreSQL 15 + pgvector | Existing DB; adds vector type without new service |
| Vector index | HNSW (`ivfflat` deferred) | HNSW works at any row count; IVFFlat needs minimum rows |
| PDF text extraction | Mathpix PDF API | Best-in-class LaTeX + image co-location for OpenStax multi-column |
| LLM (card generation with vision) | `gpt-4o` | Vision capability required for image-aware card generation |
| LLM (lightweight tasks) | `gpt-4o-mini` | Existing project convention — used for recovery cards if cost matters |
| Embeddings | `text-embedding-3-small` (1536 dim) | Existing project convention; unchanged |
| Image storage (dev) | Local filesystem + FastAPI static mount | Zero new services; existing mount already in `main.py` |
| Image storage (prod) | Cloudflare R2 (Phase 6) | Zero egress fees; S3-compatible (`boto3` works unchanged) |
| Backend framework | FastAPI 0.128+ async | Existing project stack — unchanged |
| Migrations | Alembic | Existing project stack — `create_all()` removed in Phase 0 |
| Python pgvector client | `pgvector` Python package | Required by SQLAlchemy for `vector(1536)` column type |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-01: One Chunk = One Subsection (`####` heading)

**Decision:** Each `####` subsection in the Mathpix `.mmd` becomes exactly one row in `concept_chunks`. Chunks are never split by size.

**Options considered:**
- Fixed token-size splitting (512 tokens) — standard RAG pattern
- One chunk per `###` section (coarser)
- One chunk per `####` subsection (chosen)

**Rationale:** OpenStax subsections are pedagogically coherent units — the same unit a human teacher would use. They fit comfortably within the 8,191 token embedding limit. Splitting by token count would break mid-explanation and destroy the natural paragraph structure that the LLM uses for card generation.

**Trade-offs:** Longer subsections produce more cards per chunk. This is intentional — STRUGGLING students get more granular cards from longer content; FAST students get fewer merged cards.

### ADR-02: Cards Generated Per Chunk, Not Per Card

**Decision:** All cards for a chunk are generated in a single LLM call at the start of that chunk. Navigation within the chunk is instant (no API call). An API call only occurs at the chunk boundary.

**Options considered:**
- Per-card generation (existing architecture): one LLM call per card advance
- Per-section batch (legacy): entire section batched upfront
- Per-chunk (chosen): one LLM call per subsection

**Rationale:** Per-card generation produces the cheapest individual calls but the most API round-trips. Per-section batching reduces API calls but requires large token budgets (up to 40,000 tokens) and produces all content before knowing how the student performed on earlier cards. Per-chunk balances cost and adaptability: mode is recalculated after each chunk using real performance signals, and the token budget per call (1,200–3,000 tokens) stays manageable.

**Trade-offs:** A brief loading indicator is shown at each chunk boundary. This is a known UX cost accepted in exchange for correct mode adaptation.

### ADR-03: Image Co-location at Extraction Time

**Decision:** Images are downloaded from Mathpix CDN and stored in `chunk_images` as permanent URLs during extraction, not at card generation time.

**Rationale:** Mathpix CDN URLs expire within ~1 hour. Deferring download to card generation time would require CDN re-requests that may fail. By downloading at extraction time and storing permanent local/R2 URLs, cards always have a valid image URL regardless of when they are generated.

**Trade-offs:** Extraction pipeline must download all images upfront. The pipeline handles failures gracefully (logged, image row skipped — chunk still inserted without image).

### ADR-04: Hybrid Routing During Migration

**Decision:** `main.py` lifespan checks `concept_chunks` table for each book slug. If rows exist, `ChunkKnowledgeService` is registered; if `chroma_db/` directory exists, `ChromaKnowledgeService` is registered.

**Rationale:** Migrating all 16 books simultaneously introduces too much risk. Prealgebra is migrated first. The 15 remaining books continue on ChromaDB unchanged. The hybrid routing layer is removed after all books are migrated.

**Trade-offs:** Two code paths exist in parallel during the migration period. This increases code complexity but keeps the migration reversible per book.

### ADR-05: MCQ Difficulty is the Same for All Modes; Only Style Adapts

**Decision:** MCQ questions test real textbook-level content regardless of student mode. What adapts is the writing style of content cards (vocabulary, analogy density, step depth), the wrong-answer explanation depth, and the number of content cards generated from each chunk.

**Rationale:** Making easier MCQ questions for STRUGGLING students would obscure whether they actually learned the material. The purpose of adaptation is to ensure every student can reach the same assessment, not to lower the bar. A STRUGGLING student who passes at difficulty level 1 has not demonstrated the same mastery as a FAST student who passes at difficulty level 4-5.

**Trade-offs:** STRUGGLING students face the same MCQ difficulty as FAST students. This means their pass rate may be lower on first attempt, triggering more recovery cards. This is acceptable — recovery and RECAP mechanisms exist precisely to handle this.

### ADR-06: Socratic Exam Pass Rate Set at 65%

**Decision:** `CHUNK_EXAM_PASS_RATE = 0.65` — distinct from `MASTERY_THRESHOLD = 70` used in the ChromaDB Socratic check.

**Rationale:** The chunk-based exam uses typed-answer questions which are harder than the score-accumulation model. A 65% threshold on typed answers represents genuine understanding of the subsection content. The 70 threshold is preserved unchanged for ChromaDB-path sessions.

---

## 8. Risks and Mitigations

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| Mathpix PDF API `###`/`####` heading hierarchy inconsistent across chapters | High | Medium | Test on Chapter 1 only before committing to full extraction. Inspect raw `.mmd` manually before running full pipeline. |
| Mathpix CDN URLs expire before `chunk_builder` downloads them | Medium | Low | Download images immediately after receiving `.mmd` (within the same pipeline run). Log and skip on failure — chunk inserted without image. |
| HNSW index performance degrades with full 16-book corpus (~6,400 rows) | Low | Low | HNSW handles this size without tuning. Add IVFFlat as deferred optimization if needed post-migration. |
| GPT-4o vision token cost exceeds budget for image-heavy books | Medium | Medium | Per-chunk cost is bounded by `CHUNK_MAX_TOKENS_*` constants. Vision calls only fire when chunk has images. Monitor cost per book during extraction. |
| Hybrid routing adds permanent complexity if migration stalls | Medium | Medium | Set a milestone (e.g., all 16 books migrated within 2 months). After milestone, delete `ChromaKnowledgeService` and all ChromaDB code. |
| pgvector HNSW index not available (pgvector < 0.5.0) | High | Low | Pre-check: `SELECT extversion FROM pg_extension WHERE extname = 'vector'`. Abort Phase 0 if < 0.5.0. |
| LLM generates cards out of natural paragraph order | Medium | Low | System prompt explicitly instructs: "Do NOT reorder content. Follow natural paragraph order." Verified in test suite (Phase 4). |
| Session cache format conflict breaks existing student sessions | High | Medium | New columns (`chunk_index`, `exam_phase`) are nullable with safe defaults. Old sessions: `chunk_index = 0`, `exam_phase = null`. ChromaDB path detects `exam_phase is null` and uses legacy flow. |

---

## Key Decisions Requiring Stakeholder Input

1. **Mathpix PDF API plan:** The Mathpix PDF API is a distinct product from the single-image OCR currently in use. It may require a separate plan or quota upgrade. Confirm access and test on Chapter 1 before committing to Phase 2.

2. **Book migration schedule:** The design migrates prealgebra first. The other 15 books remain on ChromaDB until explicitly migrated. A decision is needed on the migration timeline and whether books should be migrated one at a time or in batches.

3. **Image storage for production:** The design uses local filesystem for development and defers Cloudflare R2 to Phase 6. If the deployment timeline moves up, R2 setup should be pulled forward.

4. **Exam question authorship:** The Socratic exam questions are LLM-generated (2 per subsection). A decision is needed on whether human-authored question banks should supplement LLM questions for critical concepts.

5. **Card cache strategy:** The design does not cache generated cards in Phase 3. For the same chunk + mode + style + language combination, the LLM is called every time. A caching layer (JSONB in PostgreSQL) is listed as a future optimization. If cost becomes a concern early, this should be promoted.
