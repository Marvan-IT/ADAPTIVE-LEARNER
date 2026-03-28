---
name: chunk-architecture-design
description: Key design decisions for ADA Chunk-Based Teaching Pipeline (Mathpix + pgvector) — designed 2026-03-27
type: project
---

### Chunk Architecture — Key Design Decisions (2026-03-27)

**Why:** Replace PyMuPDF extraction (loses image-text co-location) + ChromaDB (not horizontally scalable) with Mathpix PDF API + PostgreSQL pgvector. Fix adaptation to change writing STYLE, not just card count.

**Core invariant:** Same content, same MCQ difficulty for all modes. Only teaching STYLE adapts (vocabulary, analogy density, step depth, language register).

**Storage:**
- `concept_chunks` table: UUID PK, book_slug, concept_id, section, order_index (sole sort authority), heading, text, latex TEXT[], embedding vector(1536)
- HNSW index (not IVFFlat) — works at any row count
- `chunk_images` table: chunk_id FK CASCADE, image_url, caption, order_index
- Images stored as permanent URLs at extraction time; CDN expiry avoided by immediate download

**Chunking rule:** One `####` subsection = one chunk. Never split mid-subsection. `###` section = concept graph node.

**New `teaching_sessions` columns:** `chunk_index INTEGER DEFAULT 0`, `exam_phase TEXT`, `exam_attempt INTEGER DEFAULT 0`, `exam_scores JSONB`, `failed_chunk_ids TEXT[] DEFAULT '{}'`. All nullable/defaulted — zero impact on existing rows.

**New config constants (config.py):**
- `CHUNK_MAX_TOKENS_STRUGGLING=3000`, `CHUNK_MAX_TOKENS_NORMAL=2000`, `CHUNK_MAX_TOKENS_FAST=1200`
- `CHUNK_MAX_TOKENS_RECOVERY=800`, `CHUNK_EXAM_PASS_RATE=0.65`
- `IMAGE_STORAGE` (local|r2), `IMAGE_BASE_URL`

**Hybrid routing:** `main.py` lifespan checks `concept_chunks` COUNT per book_slug. If rows → `ChunkKnowledgeService`. If `chroma_db/` dir → `ChromaKnowledgeService`. Both paths coexist during migration period.

**Per-chunk card generation:** All cards for a chunk in ONE LLM call at chunk start. Vision call if chunk has images; text-only otherwise. Mode recalculated at each chunk boundary (never mid-chunk). `build_chunk_card_prompt()` added to `prompt_builder.py` (existing functions untouched).

**MCQ failure flow:**
1. First fail → recovery card (new LLM call, `CHUNK_MAX_TOKENS_RECOVERY`) → new MCQ
2. Second fail → RECAP card (content only) → advance unconditionally → mode locks STRUGGLING

**Socratic exam:** Triggers after all chunks in section complete. 2 typed-answer questions per teaching chunk. Pass = ≥65% (`CHUNK_EXAM_PASS_RATE`). Fail → A/B choice: targeted retry (failed subsections only) or full redo. Max 3 targeted retries; attempt 4+ = full redo only.

**LessonCard schema changes:**
- `image_url: str | None = None` (new — direct permanent URL)
- `caption: str | None = None` (new)
- `chunk_id: str` (new)
- `is_recovery: bool = False` (new)
- `question2` removed (recovery handled by new LLM call, not pre-packed)
- Legacy fields `image_indices: list[int] = []` and `images: list[dict] = []` kept for ChromaDB path
- Frontend checks `card.image_url` first; falls back to `image_indices` for ChromaDB sessions

**New endpoints (all /api/v2/):**
- `GET /sessions/{id}/chunks` — ordered chunk list for session's concept
- `POST /sessions/{id}/chunks/{chunk_id}/cards` — generate all cards for chunk
- `POST /sessions/{id}/chunks/{chunk_id}/recovery-card` — recovery card on MCQ fail
- `POST /sessions/{id}/exam/start` — start typed-answer exam
- `POST /sessions/{id}/exam/submit` — submit answers, get score + failed_chunks
- `POST /sessions/{id}/exam/retry` — set retry path (targeted|full_redo)

**New files:**
- `backend/src/extraction/mathpix_pdf_extractor.py`
- `backend/src/extraction/mmd_parser.py`
- `backend/src/extraction/chunk_builder.py`
- `backend/src/extraction/graph_builder.py`
- `backend/src/storage/r2_client.py` (scaffold — R2 upload deferred to Phase 6)

**Completed docs:** `docs/chunk-architecture/HLD.md`, `DLD.md`, `execution-plan.md`

**Phase 0 note (devops):** Must run `CREATE EXTENSION IF NOT EXISTS vector` BEFORE Alembic migration. Remove `Base.metadata.create_all()` from `db/connection.py` in Phase 0.

**Critical pre-Phase-2 check:** Mathpix PDF API is a distinct product from the per-image OCR API — needs separate plan/quota. Test on Chapter 1 manually before committing to full extraction.
