---
name: Phase 3 Chunk-Based Architecture
description: Serving layer refactor from ChromaDB/batch-cards to PostgreSQL/per-chunk cards (2026-03-28)
type: project
---

## Phase 3: Chunk-Based Serving Layer (implemented 2026-03-28)

**Why:** Replace ChromaDB batch card generation with PostgreSQL pgvector chunk-based per-chunk generation.

### New file created
- `backend/src/api/chunk_knowledge_service.py` — `ChunkKnowledgeService` class with 5 async methods:
  `get_chunks_for_concept`, `get_chunk`, `get_chunk_images`, `get_active_books`, `get_chunk_count`

### LessonCard schema rewrite (teaching_schemas.py)
Old fields removed: `card_type`, `image_indices`, `images`, `question2`, `options`, `difficulty`
New fields: `image_url: str | None`, `caption: str | None`, `chunk_id: str = ""`, `is_recovery: bool = False`

New chunk schemas added: `ChunkCardsRequest`, `ChunkCardsResponse`, `RecoveryCardRequest`,
`SocraticExamStartRequest`, `SocraticExamAnswer`, `SocraticExamResult`

### TeachingService refactor (teaching_service.py)
- `__init__` signature changed: `def __init__(self)` — no `knowledge_services` param
- `_chunk_ksvc = ChunkKnowledgeService()` replaces `self.knowledge_services`
- `_get_ksvc()` method DELETED — all calls replaced with `_chunk_ksvc` DB queries
- `_ChunkKnowledgeServiceAdapter` shim class added for backward compat with `generate_recovery_card()`
- `generate_cards()` → stub (returns empty cards + deprecation log)
- `generate_next_section_cards()` → stub (returns empty result + deprecation log)
- `generate_presentation()` → now uses `_chunk_ksvc.get_chunks_for_concept()` for concept text
- `begin_socratic_check()` → now uses `_chunk_ksvc` for concept text
- `generate_remediation_cards()`, `begin_recheck()` → now use `_chunk_ksvc` for concept text
- `complete_card_interaction()` → recovery card uses chunk data via adapter
- NEW: `generate_per_chunk(session, db, chunk_id) → list[dict]` — single LLM call for all chunk cards
- NEW: `generate_recovery_card_for_chunk(session, chunk, chunk_images, card_index, wrong_answers) → dict | None`

### _normalise_per_card rewrite
Old signature: `_normalise_per_card(parsed: dict, card_index: int) -> dict`
New signature: `_normalise_per_card(parsed: dict, chunk_id: str) -> dict`
Handles both legacy `questions` list format and new `question` object format.

### main.py changes
- `TeachingService()` instantiated without args
- `chunk_ksvc = ChunkKnowledgeService()` created in lifespan
- `teaching_router_module.chunk_ksvc = chunk_ksvc` injected at startup
- Health endpoint now queries `chunk_count` from `concept_chunks` table

### teaching_router.py new endpoints
- `POST /api/v2/sessions/{id}/chunk-cards` → `ChunkCardsResponse`
- `POST /api/v2/sessions/{id}/chunk-recovery-card` → `LessonCard`
- `POST /api/v2/sessions/{id}/socratic-exam/start` → 501 (placeholder)
- `POST /api/v2/sessions/{id}/socratic-exam/answer` → 501 (placeholder)
- `chunk_ksvc` module-level var injected by main.py lifespan

### adaptive_engine.py (generate_recovery_card)
Old: `card["images"] = concept_images; card["image_indices"] = list(range(len(concept_images)))`
New: `card["image_url"] = first_img.get("url"); card["caption"] = ...; card.pop("image_indices", None)`

### adaptive/prompt_builder.py changes
- `_NEXT_CARD_JSON_SCHEMA` updated: removed `card_type`, `image_indices`, `questions[]`
  New fields: `index`, `title`, `content`, `image_url`, `caption`, `motivational_note`, `question` (object)
- `build_chunk_card_prompt()` added — builds user prompt for single-chunk generation
- `build_next_card_prompt()` override block updated to remove `card_type`/`image_indices` instructions

### Config constants used
`CHUNK_MAX_TOKENS_STRUGGLING=3000`, `CHUNK_MAX_TOKENS_NORMAL=2000`,
`CHUNK_MAX_TOKENS_FAST=1200`, `CHUNK_MAX_TOKENS_RECOVERY=800`
