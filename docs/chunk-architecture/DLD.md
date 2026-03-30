# Detailed Low-Level Design — ADA Chunk-Based Teaching Pipeline

## Revision History

| Date | Author | Summary |
|------|--------|---------|
| 2026-03-28 | solution-architect | Added missing `GET /chunks` full endpoint spec with `ChunkListResponse` schema (Section 3.1); added Inter-Chunk Pre-Fetch Strategy section (Section 3.6); clarified card type discrimination via `question` field presence only (Section 2.3); added ADR-07 on difficulty bias UI removal (Section 10) |
| 2026-03-27 | solution-architect | Initial version |

---

**Feature:** Chunk-Based Teaching Pipeline (Mathpix + pgvector)
**Version:** 1.1
**Date:** 2026-03-28
**Author:** solution-architect

---

## 1. Component Breakdown

| Component | Location | Single Responsibility |
|-----------|----------|----------------------|
| `mathpix_pdf_extractor.py` | `backend/src/extraction/` | Calls Mathpix PDF API for a given book PDF; caches `.mmd` output to disk |
| `mmd_parser.py` | `backend/src/extraction/` | Parses `.mmd` text into structured chunk dicts (heading, text, latex, image_urls) with 3-copy deduplication |
| `chunk_builder.py` | `backend/src/extraction/` | Downloads CDN images, embeds chunks, INSERTs `concept_chunks` + `chunk_images` rows idempotently |
| `graph_builder.py` | `backend/src/extraction/` | Builds `graph.json` from `###` nodes, sequential edges, and LLM-extracted cross-chapter edges |
| `ChunkKnowledgeService` | `backend/src/api/knowledge_service.py` | Provides chunk retrieval by `chunk_id`, ordered chunk list for a concept, and pgvector similarity search |
| `TeachingService` (refactored) | `backend/src/api/teaching_service.py` | Hybrid routing (chunk vs ChromaDB); per-chunk card generation; Socratic exam orchestration |
| `prompt_builder.py` (extended) | `backend/src/adaptive/prompt_builder.py` | `build_chunk_card_prompt()` — builds chunk-based card generation prompts; existing functions unchanged |
| `teaching_router.py` (extended) | `backend/src/api/teaching_router.py` | New endpoints: chunk-cards, recovery-card, exam, exam-retry |
| `r2_client.py` | `backend/src/storage/r2_client.py` | Image URL resolution and (Phase 6) R2 upload; config-driven `local`/`r2` switch |
| `main.py` (updated) | `backend/src/api/main.py` | Hybrid book discovery: queries `concept_chunks` table first, falls back to `chroma_db/` directory |

### Inter-component interfaces

```
chunk_builder.py → PostgreSQL: INSERT concept_chunks, INSERT chunk_images
ChunkKnowledgeService → PostgreSQL: SELECT concept_chunks, SELECT chunk_images
TeachingService → ChunkKnowledgeService: get_chunk(), get_section_chunks()
TeachingService → prompt_builder: build_chunk_card_prompt()
TeachingService → OpenAI: chat.completions.create (vision or text)
teaching_router → TeachingService: generate_chunk_cards(), run_exam(), generate_recovery()
main.py lifespan → PostgreSQL: COUNT concept_chunks per book_slug
main.py lifespan → filesystem: os.path.exists(chroma_db/)
```

---

## 2. Data Design

### 2.1 New Tables

#### `concept_chunks`

```sql
CREATE TABLE concept_chunks (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    book_slug     TEXT        NOT NULL,
    concept_id    TEXT        NOT NULL,   -- reused from existing concepts.json (e.g. "prealgebra_1.1")
    section       TEXT        NOT NULL,   -- "1.1 Introduction to Whole Numbers"
    order_index   INTEGER     NOT NULL,   -- absolute textbook position; monotonically increasing per book
    heading       TEXT        NOT NULL,   -- "Round Whole Numbers" | "Be Careful: ..." | "Try It"
    text          TEXT        NOT NULL,   -- full subsection prose (markdown, with LaTeX inline)
    latex         TEXT[]      NOT NULL DEFAULT '{}',   -- extracted LaTeX expressions
    embedding     vector(1536),           -- text-embedding-3-small on (heading + "\n\n" + text)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW index for cosine similarity (requires pgvector >= 0.5.0)
CREATE INDEX concept_chunks_embedding_hnsw_idx
    ON concept_chunks USING hnsw (embedding vector_cosine_ops);

-- Composite btree for ordered retrieval
CREATE INDEX concept_chunks_book_concept_order_idx
    ON concept_chunks (book_slug, concept_id, order_index);

-- Deduplication lookup
CREATE UNIQUE INDEX concept_chunks_unique_heading_idx
    ON concept_chunks (book_slug, section, heading);
```

**Notes:**
- `order_index` is the absolute position across the entire book — it never changes and is the sole sort authority for card sequence.
- The `UNIQUE INDEX` on `(book_slug, section, heading)` enables idempotent extraction: re-running the pipeline skips existing rows.
- `text` is stored with markdown formatting (LaTeX as `$$...$$`); embedding is computed on a stripped version.

#### `chunk_images`

```sql
CREATE TABLE chunk_images (
    id           UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id     UUID    NOT NULL REFERENCES concept_chunks(id) ON DELETE CASCADE,
    image_url    TEXT    NOT NULL,   -- permanent URL: local http path (dev) or R2 URL (prod)
    caption      TEXT,               -- "Figure 1.4 — Number line showing rounding"
    order_index  INTEGER NOT NULL DEFAULT 0   -- for subsections with multiple images
);

CREATE INDEX chunk_images_chunk_id_idx ON chunk_images (chunk_id);
```

**Cascade:** deleting a `concept_chunks` row automatically removes all associated `chunk_images` rows.

### 2.2 Modified Table: `teaching_sessions`

New columns (all nullable with safe defaults — no impact on existing rows):

```sql
ALTER TABLE teaching_sessions
    ADD COLUMN chunk_index    INTEGER     NOT NULL DEFAULT 0,
    ADD COLUMN exam_phase     TEXT,           -- NULL | 'studying' | 'exam' | 'retry_study' | 'retry_exam'
    ADD COLUMN exam_attempt   INTEGER     NOT NULL DEFAULT 0,
    ADD COLUMN exam_scores    JSONB,          -- {"chunk_id_1": 1, "chunk_id_2": 0, ...}
    ADD COLUMN failed_chunk_ids TEXT[]    NOT NULL DEFAULT '{}';
```

**State machine mapping:**

| Student state | `phase` (existing) | `exam_phase` (new) |
|--------------|--------------------|--------------------|
| Working through chunks | `CARDS` | `studying` |
| On exercise chunk | `CARDS` | `studying` |
| Socratic exam active | `CHECKING` | `exam` |
| Targeted retry (re-studying failed chunks) | `REMEDIATING` | `retry_study` |
| Targeted retry (re-taking subset exam) | `RECHECKING` | `retry_exam` |
| Section mastered | `COMPLETED` | `NULL` |

**Existing sessions:** `exam_phase = NULL`, `chunk_index = 0`, `exam_attempt = 0`. These are detected as ChromaDB-path sessions and routed accordingly. No data migration required.

### 2.3 LessonCard Schema

The new unified `LessonCard` Pydantic model:

```python
class CardMCQ(BaseModel):
    question:      str
    options:       list[str]      # exactly 4 options
    correct_index: int            # 0-based
    explanation:   str            # shown after answer (depth adapts per mode)

class LessonCard(BaseModel):
    index:         int
    title:         str            # short heading — LLM-generated from chunk heading or paragraph label
    content:       str            # markdown with LaTeX; null for pure MCQ cards
    image_url:     str | None = None     # new: direct permanent URL from chunk_images
    caption:       str | None = None     # new: figure caption
    question:      CardMCQ | None = None # None = content card; set = MCQ card
    chunk_id:      str                   # which chunk generated this card
    is_recovery:   bool = False
    # Legacy fields — populated only for ChromaDB-path sessions:
    image_indices: list[int] = []
    images:        list[dict] = []
```

**Card type determination:** the presence or absence of the `question` field is the **sole discriminator**. There is no `card_type` enum field on chunk-path cards.

- `card.question != null` → MCQ card (student must answer before proceeding)
- `card.question == null` → content card (student reads and proceeds automatically)

Old `card_type` enum values (`TEACH`, `EXAMPLE`, `VISUAL`, `QUESTION`, `APPLICATION`, `EXERCISE`, `RECAP`, `FUN`, `CHECKIN`) do not appear in chunk-path responses. Any frontend logic that branches on `card_type` must be replaced with a `question` field presence check. The `canProceed` guard in `CardLearningView.jsx` must use `card.question != null` — not `card.card_type === "CHECKIN"`.

### 2.4 Data Flow

```
EXTRACTION (offline)
  prealgebra.pdf
      → Mathpix PDF API
      → .mmd cached at backend/output/prealgebra/prealgebra.mmd
      → mmd_parser.py → list[ParsedChunk]
      → chunk_builder.py:
            for each ParsedChunk:
              download CDN images → disk → insert chunk_images rows
              strip image tags from text
              embed (heading + "\n\n" + stripped_text) → vector(1536)
              INSERT INTO concept_chunks
      → concept_chunks: ~400 rows
      → chunk_images:   ~200 rows

RUNTIME (per session request)
  GET /api/v2/sessions/{id}/concepts/{concept_id}/chunks
      → SELECT * FROM concept_chunks
          WHERE book_slug = $1 AND concept_id = $2
          ORDER BY order_index ASC
      → return list of chunk summaries (id, heading, order_index)

  POST /api/v2/sessions/{id}/chunks/{chunk_id}/cards
      → SELECT * FROM concept_chunks WHERE id = $1 (full row incl. text, latex, embedding)
      → SELECT * FROM chunk_images WHERE chunk_id = $1 ORDER BY order_index
      → build_chunk_card_prompt(chunk, images, mode, student_profile)
      → if images: OpenAI vision call (gpt-4o)
         else:     OpenAI text call  (gpt-4o)
      → parse JSON → list[LessonCard]
      → inject chunk_id, image_url from chunk_images into cards
      → UPDATE teaching_sessions SET chunk_index = chunk_index + 1
      → return LessonCard[]

  POST /api/v2/sessions/{id}/exam
      → SELECT concept_chunks for session concept, filter teaching-type chunks
      → generate 2 typed questions per teaching chunk
      → stream questions to frontend; receive typed answers
      → GPT-4o evaluates each answer → per-chunk score
      → UPDATE exam_scores, failed_chunk_ids, exam_phase, exam_attempt
      → if score >= CHUNK_EXAM_PASS_RATE: INSERT student_mastery
```

### 2.5 Caching Strategy

- `.mmd` files cached to disk at `backend/output/{book_slug}/{book_slug}.mmd` — expensive Mathpix PDF API call is made once per book.
- `concept_chunks` table is the primary cache for all extracted content — no separate in-memory cache.
- Generated cards are NOT cached in Phase 3 (deferred optimization — see Future Optimizations in HLD).
- LLM call results stored transiently in `teaching_sessions.presentation_text` JSONB (repurposed as `session_cache` for exam state only in chunk path).

### 2.6 Data Retention

- `concept_chunks` and `chunk_images` are immutable after extraction — never updated, only inserted.
- `teaching_sessions`: `exam_scores` and `failed_chunk_ids` are overwritten on each exam attempt.
- No retention policy on student session data in Phase 3; deferred to compliance review.

---

## 3. API Design

### 3.1 New Endpoints

All endpoints are under `/api/v2/` (student/session resource — consistent with existing v2 convention).

#### `GET /api/v2/sessions/{session_id}/chunks`

Returns ordered list of chunks for the concept associated with the session. This is always the first call the frontend makes when entering a lesson — the response drives the chunk progress indicator and the pre-fetch strategy.

**Pydantic response schema (`ChunkListResponse`):**

```python
class ChunkSummary(BaseModel):
    chunk_id:    str       # UUID string
    order_index: int       # absolute textbook position (sort key)
    heading:     str       # e.g. "Use Addition Notation"
    has_images:  bool      # True if at least one chunk_images row exists
    has_mcq:     bool      # determined by heading rule (Appendix C)

class ChunkListResponse(BaseModel):
    concept_id:           str
    section_title:        str
    chunks:               list[ChunkSummary]
    current_chunk_index:  int   # value of teaching_sessions.chunk_index
```

**Hybrid routing signal:** when `chunks` is an empty list (`[]`), the session is on the ChromaDB path. The frontend must fall back to the existing card generation flow (`POST /api/v2/sessions/{id}/cards`) instead of the chunk-based flow. This signal eliminates the need for a separate routing endpoint.

```
Request:  GET /api/v2/sessions/{session_id}/chunks
Auth:     API_SECRET_KEY header (existing middleware)

Response 200:
{
  "concept_id": "prealgebra_1.2",
  "section_title": "Add Whole Numbers",
  "chunks": [
    {
      "chunk_id": "uuid",
      "order_index": 4,
      "heading": "Learning Objectives",
      "has_images": false,
      "has_mcq": false
    },
    {
      "chunk_id": "uuid",
      "order_index": 5,
      "heading": "Use Addition Notation",
      "has_images": false,
      "has_mcq": true
    }
  ],
  "current_chunk_index": 0    // value from teaching_sessions.chunk_index
}

// ChromaDB-path session — empty chunks list is the routing signal:
{
  "concept_id": "prealgebra_1.2",
  "section_title": "Add Whole Numbers",
  "chunks": [],
  "current_chunk_index": 0
}

Response 404: session not found
```

**Backend implementation notes:**
- Query: `SELECT id, order_index, heading FROM concept_chunks WHERE book_slug=$1 AND concept_id=$2 ORDER BY order_index ASC`
- `has_images`: `EXISTS (SELECT 1 FROM chunk_images WHERE chunk_id = cc.id)`
- `has_mcq`: determined by heading rule lookup (Appendix C) — no DB join required
- If no rows returned for the session's `book_slug`/`concept_id`, return `chunks: []` (ChromaDB routing signal). Do not return 409.
- `current_chunk_index` comes directly from `teaching_sessions.chunk_index`

#### `POST /api/v2/sessions/{session_id}/chunks/{chunk_id}/cards`

Generates all cards for a chunk in one LLM call. Returns immediately — no streaming.

```
Request:
{
  "student_mode": "NORMAL",     // "STRUGGLING" | "NORMAL" | "FAST"
  "advance": true               // true = increment chunk_index after generation
}

Response 200:
{
  "cards": [
    {
      "index": 0,
      "title": "What is Addition?",
      "content": "Addition combines two numbers...",
      "image_url": null,
      "caption": null,
      "question": null,
      "chunk_id": "uuid",
      "is_recovery": false
    },
    {
      "index": 1,
      "title": "Check: Addition Vocabulary",
      "content": null,
      "image_url": null,
      "caption": null,
      "question": {
        "question": "In 4 + 7 = 11, what are the addends?",
        "options": ["4 and 11", "7 and 11", "4 and 7", "4, 7, and 11"],
        "correct_index": 2,
        "explanation": "The addends are the numbers being added together: 4 and 7."
      },
      "chunk_id": "uuid",
      "is_recovery": false
    }
  ],
  "chunk_heading": "Use Addition Notation",
  "chunk_index_after": 1
}

Response 400: student_mode not in allowed values
Response 404: session_id or chunk_id not found
Response 409: chunk_id does not belong to session's concept
```

#### `POST /api/v2/sessions/{session_id}/chunks/{chunk_id}/recovery-card`

Generates a recovery card + new MCQ when student fails an MCQ for the first time.

```
Request:
{
  "failed_card_index": 2,       // index of the MCQ card that was failed
  "student_mode": "NORMAL",
  "wrong_answer": "A"           // student's selected wrong option
}

Response 200:
{
  "recovery_card": {
    "index": 99,                 // virtual index — not part of main card array
    "title": "Let us revisit this",
    "content": "...",            // different worked example from same paragraph
    "image_url": "http://...",
    "caption": null,
    "question": { ... },         // new MCQ testing same concept
    "chunk_id": "uuid",
    "is_recovery": true
  }
}

Response 404: session or chunk not found
```

#### `POST /api/v2/sessions/{session_id}/exam/start`

Triggers Socratic typed-answer exam after all chunks complete.

```
Request:
{
  "concept_id": "prealgebra_1.2"
}

Response 200:
{
  "exam_id": "uuid",
  "questions": [
    {
      "question_index": 0,
      "chunk_id": "uuid",
      "chunk_heading": "Use Addition Notation",
      "question_text": "If 3 + 5 = 8, what are the addends and what is the sum?"
    },
    ...
  ],
  "total_questions": 8,
  "pass_threshold": 0.65
}

Response 409: not all chunks completed for this concept
```

#### `POST /api/v2/sessions/{session_id}/exam/submit`

Submits typed answers for evaluation.

```
Request:
{
  "answers": [
    {"question_index": 0, "answer_text": "The addends are 3 and 5; the sum is 8."},
    ...
  ]
}

Response 200:
{
  "score": 0.625,
  "passed": false,
  "total_correct": 5,
  "total_questions": 8,
  "per_chunk_scores": {
    "uuid_chunk_2": 1.0,
    "uuid_chunk_3": 0.5,
    "uuid_chunk_4": 0.75,
    "uuid_chunk_5": 0.5
  },
  "failed_chunks": [
    {"chunk_id": "uuid_chunk_3", "heading": "Model Addition", "score": 0.5},
    {"chunk_id": "uuid_chunk_5", "heading": "Add Multiple Digit Numbers", "score": 0.5}
  ],
  "exam_attempt": 1,
  "retry_options": ["targeted", "full_redo"]   // both options available if attempt < 3
}

Response 400: wrong number of answers
Response 404: session not found
```

#### `POST /api/v2/sessions/{session_id}/exam/retry`

Initiates a retry path (targeted or full redo).

```
Request:
{
  "retry_type": "targeted",     // "targeted" | "full_redo"
  "failed_chunk_ids": ["uuid1", "uuid2"]   // required if retry_type = "targeted"
}

Response 200:
{
  "retry_chunks": [             // chunks to re-study (targeted) or all chunks (full_redo)
    {"chunk_id": "uuid1", "heading": "Model Addition", "order_index": 6},
    {"chunk_id": "uuid2", "heading": "Add Multiple Digit Numbers", "order_index": 8}
  ],
  "exam_phase": "retry_study",
  "exam_attempt": 2
}

Response 409: exam_attempt >= 3 and retry_type = "targeted"  (only full_redo allowed)
```

### 3.2 Modified Endpoints

**`POST /api/v2/sessions` (start session):** No schema change. `chunk_index` initialised to 0 in new `teaching_sessions` columns.

**`GET /api/v2/students/{id}/sessions/{session_id}` (session state):** Response extended with `chunk_index`, `exam_phase`, `exam_attempt` when `book_slug` is on chunk path.

### 3.3 Authentication

All new endpoints use the existing `APIKeyMiddleware` (`API_SECRET_KEY` header). No per-user authentication changes.

### 3.4 Versioning Strategy

All new endpoints are `/api/v2/` (student/session resource domain). The `/api/v3/` prefix is reserved for adaptive learning engine endpoints; the chunks and exam endpoints are extensions of the existing session resource.

### 3.5 Error Handling Conventions

- `400 Bad Request`: invalid field values (mode not in enum, wrong answer count)
- `404 Not Found`: session_id or chunk_id does not exist in DB
- `409 Conflict`: business rule violation (not all chunks complete, attempt limit reached)
- `500 Internal Server Error`: LLM call failure after 3 retries; logged with `logger.exception()`

### 3.6 Inter-Chunk Pre-Fetch Strategy

**Problem:** `POST /chunks/{id}/cards` involves an LLM call that takes 5–20 seconds. Without pre-fetching, the student sees a loading spinner every time they click "Next Section", introducing perceptible lag at every chunk boundary.

**Strategy:**

When the student reaches the **second-to-last card** of the current chunk, the frontend silently fires `POST /chunks/{next_chunk_id}/cards` for the next chunk in the background. No user interaction is required.

On "Next Section" click:
- If the pre-fetch completed: swap `cards` array instantly — zero perceived lag.
- If the pre-fetch is still running: show an animated spinner with "Loading next section…" — this is the worst-case fallback; it should be rare when pre-fetch is wired correctly.

**Frontend state additions required (SessionContext):**

```javascript
// New state fields
nextChunkCards:    null,     // pre-fetched LessonCard[] or null
nextChunkInFlight: false,    // true while pre-fetch POST is in flight

// New reducer cases
NEXT_CHUNK_FETCH_STARTED  // set nextChunkInFlight = true
NEXT_CHUNK_CARDS_READY    // set nextChunkCards = payload, nextChunkInFlight = false
CHUNK_ADVANCE             // move nextChunkCards → cards, clear nextChunkCards
```

**Triggering condition:**

```javascript
// Inside CardLearningView, on every card render:
const isSecondToLast = currentCardIndex === cards.length - 2;
const hasNextChunk   = chunkIndex < chunkList.length - 1;

useEffect(() => {
  if (isSecondToLast && hasNextChunk && !nextChunkCards && !nextChunkInFlight) {
    dispatch({ type: "NEXT_CHUNK_FETCH_STARTED" });
    const nextChunkId = chunkList[chunkIndex + 1].chunk_id;
    fetchChunkCards(sessionId, nextChunkId, studentMode)
      .then(data => dispatch({ type: "NEXT_CHUNK_CARDS_READY", payload: data.cards }))
      .catch(err => {
        console.error("Pre-fetch failed:", err);
        dispatch({ type: "NEXT_CHUNK_FETCH_STARTED" }); // reset flag; will fetch on demand
      });
  }
}, [currentCardIndex]);
```

**Scope:** Pre-fetch is only applicable to the chunk path. ChromaDB-path sessions (`chunks: []`) are unaffected.

---

## 4. Sequence Diagrams

### 4.1 Happy Path — Student Completes One Chunk

```
Frontend                  teaching_router         TeachingService         OpenAI
   │                            │                       │                    │
   │ POST /chunks/{id}/cards    │                       │                    │
   │ {mode: "NORMAL"}           │                       │                    │
   ├───────────────────────────►│                       │                    │
   │                            │ generate_chunk_cards()│                    │
   │                            ├──────────────────────►│                    │
   │                            │                       │ SELECT concept_chunks
   │                            │                       │ SELECT chunk_images
   │                            │                       │ build_chunk_card_prompt()
   │                            │                       │ chat.completions.create
   │                            │                       ├───────────────────►│
   │                            │                       │                    │ (vision call
   │                            │                       │                    │  if has image)
   │                            │                       │◄───────────────────┤
   │                            │                       │ parse JSON cards   │
   │                            │                       │ inject chunk_id    │
   │                            │                       │ inject image_url   │
   │                            │                       │ UPDATE chunk_index │
   │                            │◄──────────────────────┤                    │
   │◄───────────────────────────┤ LessonCard[]          │                    │
   │                            │                       │                    │
   │ (student works cards)      │                       │                    │
   │ (instant — no API)         │                       │                    │
   │                            │                       │                    │
   │ (last MCQ passed)          │                       │                    │
   │ POST /chunks/{next}/cards  │                       │                    │
   │ (repeat for each chunk)    │                       │                    │
```

### 4.2 MCQ Failure — Recovery Card Flow

```
Frontend                  teaching_router         TeachingService         OpenAI
   │                            │                       │                    │
   │ (student fails MCQ)        │                       │                    │
   │                            │                       │                    │
   │ POST /recovery-card        │                       │                    │
   │ {failed_card_index: 2,     │                       │                    │
   │  wrong_answer: "B"}        │                       │                    │
   ├───────────────────────────►│                       │                    │
   │                            │ generate_recovery()   │                    │
   │                            ├──────────────────────►│                    │
   │                            │                       │ re-read chunk text │
   │                            │                       │ build_recovery_prompt
   │                            │                       ├───────────────────►│
   │                            │                       │◄───────────────────┤
   │                            │◄──────────────────────┤                    │
   │◄───────────────────────────┤ recovery LessonCard   │                    │
   │                            │                       │                    │
   │ (student works recovery)   │                       │                    │
   │                            │                       │                    │
   │ (fails recovery MCQ too)   │                       │                    │
   │ → frontend shows RECAP     │                       │                    │
   │   card (content only)      │                       │                    │
   │ → student clicks Next      │                       │                    │
   │ → chunk boundary           │                       │                    │
   │ → mode locked STRUGGLING   │                       │                    │
```

### 4.3 Socratic Exam — Fail + Targeted Retry

```
Frontend                  teaching_router         TeachingService         OpenAI
   │                            │                       │                    │
   │ POST /exam/start           │                       │                    │
   ├───────────────────────────►│                       │                    │
   │                            │ run_exam_start()      │                    │
   │                            ├──────────────────────►│                    │
   │                            │                       │ SELECT chunks (teaching type only)
   │                            │                       │ build_exam_questions_prompt
   │                            │                       ├───────────────────►│
   │                            │                       │◄───────────────────┤
   │                            │◄──────────────────────┤ 8 questions        │
   │◄───────────────────────────┤ exam questions        │                    │
   │                            │                       │                    │
   │ (student types answers)    │                       │                    │
   │                            │                       │                    │
   │ POST /exam/submit          │                       │                    │
   │ {answers: [...8 answers]}  │                       │                    │
   ├───────────────────────────►│                       │                    │
   │                            │ evaluate_exam()       │                    │
   │                            ├──────────────────────►│                    │
   │                            │                       │ build_eval_prompt  │
   │                            │                       ├───────────────────►│
   │                            │                       │◄───────────────────┤
   │                            │                       │ score = 0.625 FAIL │
   │                            │                       │ UPDATE exam_scores │
   │                            │                       │ UPDATE failed_chunk_ids
   │                            │◄──────────────────────┤                    │
   │◄───────────────────────────┤ {score, failed, opts} │                    │
   │                            │                       │                    │
   │ (student sees A/B choice)  │                       │                    │
   │ POST /exam/retry           │                       │                    │
   │ {retry_type: "targeted"}   │                       │                    │
   ├───────────────────────────►│                       │                    │
   │                            │ set_retry()           │                    │
   │                            ├──────────────────────►│                    │
   │                            │                       │ UPDATE exam_phase='retry_study'
   │                            │                       │ UPDATE exam_attempt=2
   │                            │◄──────────────────────┤                    │
   │◄───────────────────────────┤ retry_chunks list     │                    │
   │                            │                       │                    │
   │ (student re-studies failed │                       │                    │
   │  chunks at STRUGGLING)     │                       │                    │
   │                            │                       │                    │
   │ POST /exam/start (attempt 2)│                      │                    │
   │ (4 questions this time)    │                       │                    │
```

### 4.4 Edge Case — Exit Mid-Session and Resume

```
Student exits (browser closed) after completing chunk 2 of 6 in section 1.2.

DB state preserved:
  teaching_sessions.chunk_index = 2
  teaching_sessions.exam_phase = 'studying'

Student returns:
  GET /api/v2/sessions/{id}/chunks
  → response: current_chunk_index = 2
  → frontend resumes at chunk 3 (index 2 = third chunk, 0-based)
  → POST /chunks/{chunk_3_id}/cards
  → session continues from chunk 3
```

---

## 5. Integration Design

### 5.1 Mathpix PDF API

- **Protocol:** HTTPS REST, POST to `https://api.mathpix.com/v3/pdf`
- **Authentication:** `app_id` + `app_key` headers (existing Mathpix credentials in `backend/.env`)
- **Flow:** Submit PDF → receive job ID → poll `GET /v3/pdf/{job_id}` until status = `completed` → download `.mmd`
- **Rate limits:** Up to 20 concurrent pages; pipeline uses sequential processing to avoid bursting
- **Retry:** 3 attempts with 5s back-off on transient errors; abort after 3 failures
- **Caching:** `.mmd` written to `backend/output/{book_slug}/{book_slug}.mmd` immediately on success; never re-requested if file exists

### 5.2 OpenAI API (vision + text)

- **Text call:** `model = OPENAI_MODEL` (gpt-4o), `max_tokens = CHUNK_MAX_TOKENS_{MODE}`, `timeout = 30.0`
- **Vision call:** Same parameters; `content` is a list with `{"type": "text", ...}` and `{"type": "image_url", "image_url": {"url": image_url}}` blocks
- **Retry:** 3 attempts, `asyncio.sleep(2 * attempt)` back-off (existing `LLM_RETRY` pattern)
- **JSON parsing:** Expect JSON array; fall back to `json-repair` on malformed output; raise `ValueError` after exhaustion
- **Token budget constants:**

```python
# config.py (new constants)
CHUNK_MAX_TOKENS_STRUGGLING = 3000
CHUNK_MAX_TOKENS_NORMAL     = 2000
CHUNK_MAX_TOKENS_FAST       = 1200
CHUNK_MAX_TOKENS_RECOVERY   = 800
CHUNK_MAX_TOKENS_EXAM_Q     = 600    # exam question generation
CHUNK_MAX_TOKENS_EXAM_EVAL  = 400    # per-answer evaluation
CHUNK_EXAM_PASS_RATE        = 0.65
```

### 5.3 Internal Service Communication

All internal communication is synchronous in-process function calls (monolith). No message queues. The extraction pipeline is invoked as a CLI command (`python -m src.pipeline --book prealgebra`), not as an API endpoint.

---

## 6. Security Design

### 6.1 Authentication and Authorization

- All new API endpoints are protected by `APIKeyMiddleware` (existing `API_SECRET_KEY` check using `secrets.compare_digest()`).
- No per-student authorization in Phase 3 — all authenticated clients can access any session. This is existing known technical debt.
- Mathpix API key and OpenAI API key stored in `backend/.env` only; validated at startup via `config.py` (raises `ValueError` if missing).

### 6.2 Data Encryption

- All API traffic: HTTPS in production (TLS termination at load balancer/CloudFront in Phase 6).
- PostgreSQL connections: `ssl=require` in production DATABASE_URL (Phase 6 config).
- Images: served over HTTP in development; HTTPS via CloudFront in production.
- No encryption at rest required for `concept_chunks` — this is public textbook content.

### 6.3 Input Validation

- `student_mode`: validated against `Literal["STRUGGLING", "NORMAL", "FAST"]` in Pydantic schema.
- `chunk_id`: UUID format validation via Pydantic `UUID` type; DB query returns 404 if not found.
- `failed_card_index`: integer range check (0 ≤ index < known card count for that chunk).
- `answer_text` in exam submission: max length 2000 characters; HTML stripped before LLM evaluation.
- `retry_type`: validated against `Literal["targeted", "full_redo"]`.

### 6.4 Secrets Management

- `MATHPIX_APP_ID`, `MATHPIX_APP_KEY`, `OPENAI_API_KEY`, `API_SECRET_KEY` — all in `backend/.env`.
- `backend/.env.example` documents all required variables; `.env` is gitignored.
- Config startup validation raises `ValueError` with clear message if any required variable is absent.

---

## 7. Observability Design

### 7.1 Logging

All modules use `logging.getLogger(__name__)` with structured format (existing project convention). Never use `print()`.

Key log events:

| Event | Level | Fields |
|-------|-------|--------|
| Chunk extraction started | INFO | book_slug, chunk_count |
| Image download success | DEBUG | chunk_id, filename, bytes |
| Image download failure | WARNING | chunk_id, cdn_url, error |
| LLM card generation | INFO | chunk_id, mode, card_count, tokens_used, latency_ms |
| LLM call failure (retry) | WARNING | attempt, error |
| LLM exhausted retries | ERROR | chunk_id, error |
| Exam started | INFO | session_id, concept_id, question_count |
| Exam submitted | INFO | session_id, score, passed |
| Section mastered | INFO | session_id, student_id, concept_id |
| Targeted retry started | INFO | session_id, failed_chunk_count, attempt |

### 7.2 Metrics (Phase 6)

Priority KPIs to instrument:
- `chunk_cards_generation_latency_ms` (histogram, by mode and has_vision)
- `exam_pass_rate` (counter, by book_slug and attempt_number)
- `recovery_card_trigger_rate` (counter, by mode)
- `recap_trigger_rate` (counter, by mode)
- `mode_distribution` (gauge, STRUGGLING/NORMAL/FAST per active session)

### 7.3 Alerting

- Alert if `chunk_cards_generation_latency_ms` p99 > 20,000 ms (LLM timeout approaching)
- Alert if `exam_pass_rate` drops below 0.40 (suggests content or question quality issue)
- Alert if `image_download_failure_rate` > 0.05 (Mathpix CDN access issues)

### 7.4 Distributed Tracing

Not implemented in Phase 3. OpenTelemetry traces deferred to Phase 6 with AWS X-Ray.

---

## 8. Error Handling and Resilience

### 8.1 LLM Call Failures

```python
# Pattern (same as existing TeachingService)
for attempt in range(3):
    try:
        response = await openai_client.chat.completions.create(...)
        cards = json.loads(response.choices[0].message.content)
        return cards
    except Exception as e:
        logger.warning(f"LLM attempt {attempt+1} failed: {e}")
        if attempt < 2:
            await asyncio.sleep(2 * (attempt + 1))

logger.error("LLM exhausted retries for chunk_id=%s", chunk_id)
raise ValueError("Card generation failed after 3 attempts")
```

The router catches `ValueError` and returns HTTP 503 with a user-friendly error message.

### 8.2 Image Download Failures (Extraction Pipeline)

```python
try:
    response = httpx.get(cdn_url, timeout=10)
    response.raise_for_status()
    with open(local_path, "wb") as f:
        f.write(response.content)
    image_url = IMAGE_BASE_URL + "/" + local_filename
except Exception as e:
    logger.warning("Image download failed for chunk=%s url=%s: %s", chunk_id, cdn_url, e)
    image_url = None  # chunk inserted without image — card generation still proceeds
```

### 8.3 Chunk Index Drift Prevention

`chunk_index` is only incremented inside a DB transaction after successful card generation. If card generation fails, `chunk_index` is not incremented and the student can retry.

```python
async with db.begin():
    cards = await generate_chunk_cards(chunk_id, mode, student_profile)
    session.chunk_index += 1
    db.add(session)
# Transaction commits only if generate_chunk_cards succeeds
```

### 8.4 RECAP Anti-Infinite-Loop

The frontend enforces the RECAP rule: after two MCQ failures on the same card, the RECAP card is shown and the user is unconditionally advanced to the next content card. The backend has no logic to block this advance — the frontend is the authority on within-chunk navigation.

### 8.5 Exam Attempt Limit Enforcement

```python
if session.exam_attempt >= 3 and retry_type == "targeted":
    raise HTTPException(status_code=409,
        detail="Targeted retry limit reached. Only full redo is available.")
```

### 8.6 `failed_chunk_ids` NULL Safety

All code reading `failed_chunk_ids` must use `session.failed_chunk_ids or []` because SQLAlchemy may return `None` for empty `TEXT[]` columns on some PostgreSQL configurations.

---

## 9. Testing Strategy

### 9.1 chunk_parser.py — Unit Tests

| Test | Coverage criterion |
|------|--------------------|
| `test_orphan_text_captured` | Introductory text between `###` and first `####` is captured as a chunk |
| `test_chapter_summary_no_children` | `###` with no `####` children becomes one chunk |
| `test_normal_subsection_parsed` | `####` heading starts a new chunk |
| `test_deduplication_keeps_most_words` | 3-copy duplicate keeps the occurrence with most words |
| `test_all_lines_assigned` | Every line in a sample `.mmd` belongs to exactly one chunk |
| `test_cdn_image_urls_extracted` | `![](https://cdn.mathpix.com/...)` pattern extracted into `image_urls` list |
| `test_order_index_monotonic` | `order_index` values are strictly increasing across all chunks |
| `test_learning_objectives_heading` | Chunk with heading "Learning Objectives" has `has_mcq = False` |

### 9.2 chunk_builder.py — Integration Tests (real DB, no mocks)

| Test | Coverage criterion |
|------|--------------------|
| `test_idempotent_insert` | Running builder twice on same chunk does not create duplicate rows |
| `test_image_downloaded_and_linked` | CDN image downloaded to disk; `chunk_images` row inserted with correct `chunk_id` FK |
| `test_embedding_shape` | Embedding stored in DB is `vector(1536)` |
| `test_latex_stored` | `latex` array contains all `$$...$$` expressions from chunk text |
| `test_chunk_images_cascade_delete` | Deleting `concept_chunks` row deletes its `chunk_images` rows |

### 9.3 Card Generation — Unit Tests (mock OpenAI)

| Test | Coverage criterion |
|------|--------------------|
| `test_cards_interleaved_content_mcq` | Returned array alternates content/MCQ pairs |
| `test_struggling_more_cards_than_fast` | STRUGGLING mode produces more cards than FAST for same chunk |
| `test_image_url_injected` | `card.image_url` matches `chunk_images.image_url` for image-bearing chunk |
| `test_learning_objectives_no_mcq` | Chunk with "Learning Objectives" heading returns zero MCQ cards |
| `test_exercise_chunk_mcq_only` | Exercise chunk returns only MCQ cards (no content cards) |
| `test_exercise_chunk_card_count` | Exercise chunk with N preceding subsections returns 2N MCQ cards |
| `test_chunk_id_injected` | All returned cards have `chunk_id` set to the requested chunk UUID |
| `test_vision_call_when_has_image` | When chunk has images, OpenAI call includes `image_url` content block |
| `test_text_only_call_when_no_image` | When chunk has no images, OpenAI call is text-only |

### 9.4 Mode Adaptation — Unit Tests

| Test | Coverage criterion |
|------|--------------------|
| `test_mode_recalculated_at_chunk_boundary` | `build_blended_analytics()` called once per chunk completion |
| `test_shift_to_struggling_on_recap` | `recap_count >= 1` triggers STRUGGLING for next chunk |
| `test_shift_to_fast_on_perfect_run` | `first_try_pass_rate = 1.0` + `hints = 0` triggers FAST |
| `test_no_mid_chunk_mode_change` | All cards for a chunk use the same mode; mode fixed at chunk start |

### 9.5 Socratic Exam — Unit Tests

| Test | Coverage criterion |
|------|--------------------|
| `test_exam_not_triggered_until_all_chunks_done` | POST /exam/start returns 409 if `chunk_index < total_chunks` |
| `test_pass_at_65_percent` | Score 0.65 → `passed = True`, `student_mastery` row inserted |
| `test_fail_below_65_percent` | Score 0.625 → `passed = False`, failed chunks identified |
| `test_failed_chunks_correctly_identified` | Per-chunk scores computed correctly; only failing chunks listed |
| `test_targeted_retry_limit` | 3rd targeted retry attempt returns 409 if `retry_type = targeted` |
| `test_full_redo_always_available` | `full_redo` never rejected regardless of `exam_attempt` |
| `test_exam_resumes_on_return` | Student with `exam_phase = 'exam'` and partial answers resumes from correct question |

### 9.6 Session Persistence — Integration Tests

| Test | Coverage criterion |
|------|--------------------|
| `test_chunk_index_persisted` | After POST /cards, `chunk_index` in DB equals previous + 1 |
| `test_resume_from_chunk_index` | GET /chunks returns `current_chunk_index` matching DB value |
| `test_exam_scores_persisted` | After POST /exam/submit, `exam_scores` JSONB stored correctly |
| `test_exit_mid_exam_resume` | Session with `exam_phase = 'exam'` resumes at correct question index |

### 9.7 Hybrid Routing — Integration Tests

| Test | Coverage criterion |
|------|--------------------|
| `test_prealgebra_routes_to_chunk_service` | When concept_chunks rows exist, `ChunkKnowledgeService` is used |
| `test_other_book_routes_to_chroma_service` | When no concept_chunks rows but chroma_db exists, `ChromaKnowledgeService` is used |
| `test_existing_chroma_session_unaffected` | Existing ChromaDB-path session completes correctly after migration |

### 9.8 Performance Tests

- Measure chunk card generation latency for STRUGGLING/NORMAL/FAST modes (text and vision)
- Verify pgvector cosine search returns in < 50 ms for ~400-row prealgebra corpus
- Verify extraction pipeline completes prealgebra in < 30 minutes

---

## 10. Architectural Decision Records (DLD-Level)

These ADRs supplement the HLD ADRs (ADR-01 through ADR-06) with decisions that are implementation-level rather than architectural.

### ADR-07: Remove TOO_EASY / TOO_HARD Difficulty Bias UI

**Context:** An earlier iteration of the adaptive card UI included "TOO EASY" and "TOO HARD" buttons that students could press to signal difficulty preference. These buttons fed a `difficulty_bias` field (`Literal["TOO_EASY", "TOO_HARD"] | None`) into the per-card generation prompt.

**Decision:** Remove the TOO_EASY / TOO_HARD difficulty bias buttons from the card learning view entirely.

**Rationale:** Per ADR-05 in the HLD, MCQ difficulty is intentionally fixed across all learning modes. Only the **style** of explanation adapts (vocabulary level, analogy density, step depth) — not the conceptual difficulty of the question itself. Presenting difficulty feedback buttons implies to students that they can change the difficulty of questions, which directly contradicts the fixed-difficulty design principle. This creates a false expectation and undermines the pedagogical model.

**Changes required:**
- Frontend: Remove TOO_EASY / TOO_HARD button elements and the `SET_DIFFICULTY_BIAS` dispatch from `CardLearningView.jsx`
- Frontend: Remove `difficultyBias` from SessionContext state and the `ADAPTIVE_CARD_LOADED` clear logic
- Backend: `difficulty_bias` field may remain in `CardBehaviorSignals` and `NextCardRequest` schemas for backward compatibility, but the prompt builder must ignore it (or it can be removed in the same PR — either is acceptable)
- No DB migration required — `difficulty_bias` was never persisted

**Alternatives considered:**
- Keep the buttons but only affect style (not difficulty) — rejected because the UI label "TOO EASY / TOO HARD" is inherently about difficulty, not style. Renaming to "TOO FAST / TOO SLOW" was considered but deemed confusing given the existing FAST/SLOW speed signal.
- Keep the buttons and actually vary difficulty — rejected because fixed-difficulty MCQ is a core pedagogical principle (ADR-05).

**Status:** Accepted
**Date:** 2026-03-28

---

## Appendix A — chunk_parser.py Algorithm (Detailed)

```python
# Heading detection patterns
SECTION_PATTERN = re.compile(r"^#{2,3}\s+(\d+)\.(\d+)\s+(.+)")   # level-agnostic section
SUBSECTION_PATTERN = re.compile(r"^####\s+(.+)")
CDN_IMAGE_PATTERN = re.compile(r"!\[\]\((https://cdn\.mathpix\.com/[^)]+)\)")

def parse_mmd(mmd_text: str) -> list[ParsedChunk]:
    chunks = []
    current_section = None
    current_chunk = None
    orphan_text_lines = []
    order_index = 0

    for line in mmd_text.splitlines():

        # Chapter heading — metadata only, no chunk
        if line.startswith("# ") and not line.startswith("## "):
            save_orphan_if_any(chunks, current_section, orphan_text_lines, order_index)
            orphan_text_lines = []

        # Section heading (## or ### with digit.digit pattern)
        elif SECTION_PATTERN.match(line):
            save_orphan_if_any(chunks, current_section, orphan_text_lines, order_index)
            if current_chunk:
                chunks.append(finalise(current_chunk)); order_index += 1
            current_section = line.lstrip("#").strip()
            current_chunk = None
            orphan_text_lines = []

        # Subsection heading (####)
        elif SUBSECTION_PATTERN.match(line):
            if orphan_text_lines and current_section:
                chunks.append(make_orphan_chunk(current_section, orphan_text_lines, order_index))
                order_index += 1
                orphan_text_lines = []
            if current_chunk:
                chunks.append(finalise(current_chunk)); order_index += 1
            current_chunk = start_new_chunk(line, current_section)

        # Content line
        else:
            image_match = CDN_IMAGE_PATTERN.search(line)
            if current_chunk:
                current_chunk.text_lines.append(line)
                if image_match:
                    current_chunk.image_urls.append(image_match.group(1))
            else:
                orphan_text_lines.append(line)
                # (image URLs in orphan text are preserved through orphan chunk)

    # Finalise last chunk
    if current_chunk:
        chunks.append(finalise(current_chunk)); order_index += 1
    if orphan_text_lines:
        chunks.append(make_orphan_chunk(current_section, orphan_text_lines, order_index))

    # 3-copy deduplication: group by (section, heading), keep most words
    return deduplicate(chunks)
```

**3-copy deduplication:**

```python
def deduplicate(chunks: list[ParsedChunk]) -> list[ParsedChunk]:
    groups: dict[tuple, list[ParsedChunk]] = {}
    for chunk in chunks:
        key = (chunk.section, chunk.heading)
        groups.setdefault(key, []).append(chunk)
    result = []
    for group in groups.values():
        best = max(group, key=lambda c: len(c.text.split()))
        result.append(best)
    return sorted(result, key=lambda c: c.order_index)
```

---

## Appendix B — chunk_builder.py Algorithm (Detailed)

```python
async def build_chunks(parsed_chunks: list[ParsedChunk], book_slug: str, db: AsyncSession):
    embedder = OpenAIEmbedder()

    for chunk in parsed_chunks:
        # Idempotency check
        existing = await db.scalar(
            select(ConceptChunk.id)
            .where(ConceptChunk.book_slug == book_slug,
                   ConceptChunk.section == chunk.section,
                   ConceptChunk.heading == chunk.heading)
            .limit(1)
        )
        if existing:
            continue  # skip — already in DB

        # Download images
        image_rows = []
        for idx, cdn_url in enumerate(chunk.image_urls):
            local_filename = sha256(cdn_url.encode()).hexdigest()[:16] + ".jpg"
            local_path = OUTPUT_DIR / book_slug / "images_downloaded" / local_filename
            try:
                resp = httpx.get(cdn_url, timeout=10)
                resp.raise_for_status()
                local_path.write_bytes(resp.content)
                image_url = f"{IMAGE_BASE_URL}/{book_slug}/images_downloaded/{local_filename}"
                # Extract caption if present in surrounding lines
                caption = extract_caption(chunk.text, cdn_url)
                image_rows.append(ChunkImageData(url=image_url, caption=caption, idx=idx))
            except Exception as e:
                logger.warning("Image download failed chunk=%s url=%s: %s", chunk.heading, cdn_url, e)

        # Strip image tags before embedding
        stripped_text = CDN_IMAGE_PATTERN.sub("", chunk.text).strip()
        embed_input = chunk.heading + "\n\n" + stripped_text
        embedding = await embedder.embed(embed_input)

        # INSERT concept_chunks
        db_chunk = ConceptChunk(
            book_slug=book_slug,
            concept_id=chunk.concept_id,
            section=chunk.section,
            order_index=chunk.order_index,
            heading=chunk.heading,
            text=chunk.text,       # kept with markdown image tags for display
            latex=chunk.latex,
            embedding=embedding,
        )
        db.add(db_chunk)
        await db.flush()  # get db_chunk.id

        # INSERT chunk_images
        for img in image_rows:
            db.add(ChunkImage(
                chunk_id=db_chunk.id,
                image_url=img.url,
                caption=img.caption,
                order_index=img.idx,
            ))

    await db.commit()
```

---

## Appendix C — Heading Rule → Card Behaviour Lookup

| Heading pattern | Content cards | MCQ | Counted in Socratic exam |
|-----------------|--------------|-----|--------------------------|
| Normal `####` (concept teaching) | Natural paragraph split | 1 at end of each group | Yes — 2 questions |
| Contains "Be Careful" | 1 warning card | 1 MCQ | Yes — 2 questions |
| Contains "Try It" or "Practice" | 1 worked-example card | 1 MCQ | Yes — 2 questions |
| Contains "Learning Objectives" | 1 overview card | None | No |
| Orphan intro (heading == parent `###` title) | 1 context card | None | No |
| Contains "Exercises" (section-level) | None — MCQ only | 2 per preceding teaching chunk | No |
| Contains "Key Terms" / "Key Concepts" | 1 reference card | None | No |
| Contains "Summary" / "Chapter Review" | 1–2 recap cards | None | No |
| Contains "Review Exercises" / "Practice Test" (chapter-level) | None — MCQ only | 2 per section in chapter | No |
