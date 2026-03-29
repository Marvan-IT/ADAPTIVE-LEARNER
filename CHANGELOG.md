# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased] — 2026-03-28

### Added
- `backend/src/extraction/chunk_parser.py` — Subsection-level MMD parser with 3-copy deduplication and noise-heading filtering
- `backend/src/extraction/chunk_builder.py` — Chunk builder: embeds chunks with text-embedding-3-small, downloads CDN images, stores to PostgreSQL
- `backend/src/extraction/graph_builder.py` — Graph builder: reads concept_chunks, builds sequential + LLM-extracted cross-chapter edges, writes graph.json
- `backend/src/api/chunk_knowledge_service.py` — PostgreSQL-backed knowledge service with 11 sync graph methods (NetworkX/graph.json) and 2 async concept-detail methods (pgvector SQL)
- `backend/alembic/versions/006_chunk_architecture.py` — Alembic migration: pgvector extension, concept_chunks table (HNSW index), chunk_images table, exam tracking columns on teaching_sessions
- `backend/tests/` — 18 test modules, 322+ tests covering chunk architecture, adaptive engine, per-card generation, analytics blending, and schema validation
- `backend/src/config.py` — `IMAGE_STORAGE` environment variable (default: "local")
- `docs/chunk-architecture/` — HLD, DLD, and execution-plan design documents

### Changed
- `backend/src/api/main.py` — Removed KnowledgeService initialization loop; graph/concept v1 endpoints now served by ChunkKnowledgeService; image mount path corrected to OUTPUT_DIR/book_slug (not /images subdirectory); health endpoint uses chunk_count from PostgreSQL
- `backend/src/api/teaching_service.py` — Fixed wrong keyword arg `card_index=` → `chunk_id=` in `_normalise_per_card()` call; replaced orphaned `card_dict["images"]` assignment with correct `image_url`/`caption` fields
- `backend/src/adaptive/adaptive_engine.py` — Added `db: AsyncSession` parameter to `generate_adaptive_lesson()` and `generate_recovery_card()`; removed `card_type`/`image_indices` from recovery card LLM prompt schema; updated to `image_url`/`caption`
- `backend/src/adaptive/adaptive_router.py` — Removed `adaptive_knowledge_services`, `adaptive_knowledge_svc`, `_get_adaptive_ksvc()` globals; all call sites now pass `chunk_ksvc`, `book_slug`, `db` directly
- `backend/src/adaptive/remediation.py` — Replaced `knowledge_svc.graph.predecessors()` with `chunk_ksvc.get_predecessors()`; updated function signatures to accept `chunk_ksvc` + `book_slug`
- `backend/src/api/teaching_router.py` — Removed `_knowledge_services` global; wired to ChunkKnowledgeService for concept readiness and session start
- `backend/src/api/teaching_schemas.py` — Removed `card_type`, `image_indices`, `question2`, `images` from `LessonCard`; added `image_url`, `caption`, `chunk_id`, `is_recovery`
- `backend/src/api/prompts.py` — Replaced `image_indices`/`card_type` references with `image_url`/`caption` in LLM instruction strings
- `backend/src/api/chunk_knowledge_service.py` — Added `FileNotFoundError` guard in `_load_graph()` for missing graph.json
- `backend/src/config.py` — Removed dead `CHROMA_DIR` and `CHROMA_COLLECTION_NAME` constants
- `frontend/src/api/sessions.js` — Fixed `getBookSlugFromConceptId()` to handle new `prealgebra_1.1` concept ID format (was parsing old `PREALG.C1.S1...` format only)
- `frontend/src/components/learning/CardLearningView.jsx` — Removed `card_type: card.card_type` from PostHog analytics event (field removed from LessonCard schema)
- `backend/tests/test_chunk_parser.py` — Updated `test_single_section_no_subheadings` body to ≥30 words to match `MIN_SECTION_BODY_WORDS` threshold

### Removed
- `backend/src/api/knowledge_service.py` — Deleted (ChromaDB-based; replaced by ChunkKnowledgeService)
- `backend/src/storage/chroma_store.py` — Deleted (ChromaDB wrapper; replaced by pgvector SQL)
- `chromadb>=0.5.0` from `backend/requirements.txt` — Removed package dependency
- `backend/output/prealgebra/chroma_db/` — Deleted dead ChromaDB data (~500MB)
- `frontend/src/components/learning/PresentationView.jsx` — Deleted dead legacy component (PRESENTING phase no longer used; was never imported)
- `backend/src/api/teaching_service.py` — Removed `_ChunkKnowledgeServiceAdapter` class (no longer needed after generate_recovery_card accepts chunk_ksvc directly)
