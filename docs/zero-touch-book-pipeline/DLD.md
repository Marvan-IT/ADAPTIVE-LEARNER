# Detailed Low-Level Design: Zero-Touch Multi-Subject Book Pipeline

**Feature:** `zero-touch-book-pipeline`
**Date:** 2026-04-08
**Status:** Ready for implementation

---

## 1. Component Breakdown

| Component | File | Responsibility |
|---|---|---|
| **BookConfig YAML Loader** | `backend/src/config.py` | Replace hardcoded `BOOK_REGISTRY` dict with a YAML loader; expose same `get_book_config()` and `get_pdf_path()` interfaces |
| **Font Calibrator** | `backend/src/extraction/calibrate.py` | Detect section/chapter font signatures from a PDF and derive a complete `BOOK_REGISTRY` entry dict |
| **Book Watcher** | `backend/src/watcher/book_watcher.py` | Run watchdog `Observer` on `backend/data/`; enqueue new PDFs into asyncio pipeline queue |
| **Pipeline Runner** | `backend/src/watcher/pipeline_runner.py` | Execute 5 ordered async pipeline stages per book; write progress to per-book `pipeline.log` and to `pipeline_runs` DB table |
| **Image Retry + Validator** | `backend/src/extraction/chunk_builder.py` | Add `_download_image_with_retry()` and `_validate_and_clean_images()` |
| **Expert Graph YAML Loader** | `backend/src/graph/dependency_builder.py` | Load `prealgebra.yaml` (and any future slug YAMLs) from `backend/src/graph/expert_graphs/`; fall back to keyword builder for unknown slugs |
| **Admin Hot-Load Endpoint** | `backend/src/api/main.py` | `POST /api/admin/load-book/{slug}` — mount static image dir and add book slug to live routing tables without restart |
| **Admin Pipeline Runs Endpoint** | `backend/src/api/main.py` | `GET /api/admin/pipeline-runs?limit=N` — query `pipeline_runs` table |
| **Books API Enhancement** | `backend/src/api/main.py` | Add `subject` field to `/api/v1/books` response |
| **Bootstrap Script** | `backend/scripts/bootstrap_existing.py` | One-time scan of `backend/data/` to trigger pipeline for all PDFs not yet in `books.yaml` |
| **DB Migration** | Alembic | Remove `server_default="prealgebra"` from `teaching_sessions.book_slug`; add `pipeline_runs` table |

### Inter-component Interfaces

```
book_watcher  ──(asyncio.Queue)──►  pipeline_runner
                                         │
                    ┌────────────────────┼─────────────────────┐
                    ▼                    ▼                      ▼
            calibrate.py          chunk_builder.py       dependency_builder.py
            books.yaml            PostgreSQL              expert_graphs/*.yaml
                                  concept_chunks           graph.json
                                  chunk_images
                                         │
                                         ▼
                                  POST /api/admin/load-book/{slug}
                                  (httpx, X-API-Key header)
```

---

## 2. Data Design

### 2.1 `backend/books.yaml` — Full Schema

```yaml
# books.yaml — Runtime-appendable book registry
# All fields under each book entry key (= book_code, uppercase)

books:
  PREALG:                              # Required: uppercase book code, max 10 chars
    book_code: "PREALG"               # Required: string, same as key
    book_slug: "prealgebra"           # Required: snake_case, lowercase, unique
    pdf_filename: "maths/prealgebra.pdf"  # Required: relative to backend/data/
    title: "Prealgebra 2e"            # Required: human-readable display name
    subject: "mathematics"            # Required: folder name from data/{subject}/
    expert_graph: "prealgebra"        # Optional: slug of YAML in expert_graphs/; omit for keyword builder
    section_header_font: "RobotoSlab-Bold"    # Required: exact PyMuPDF font name
    section_header_size_min: 14.0     # Required: float, points
    section_header_size_max: 14.6     # Required: float, points
    chapter_header_font: "RobotoSlab-Bold"    # Required: exact PyMuPDF font name
    chapter_header_size_min: 17.0    # Required: float, points
    chapter_header_size_max: 17.5    # Required: float, points
    section_pattern: '^(\d+)\.(\d+)\s+(.+)'  # Required: regex string (no r-prefix in YAML)
    front_matter_end_page: 16        # Required: int, 0-indexed page where content starts
    exercise_marker_pattern: 'Section\s+\d+\.\d+\s+Exercises'  # Required: regex string

  FIACCT:
    book_code: "FIACCT"
    book_slug: "financial_accounting"
    pdf_filename: "Business/financial_accounting.pdf"
    title: "Financial Accounting"
    subject: "business"
    # expert_graph omitted → keyword builder used
    section_header_font: "NotoSerif-Bold"
    section_header_size_min: 13.5
    section_header_size_max: 14.5
    chapter_header_font: "NotoSerif-Bold"
    chapter_header_size_min: 16.5
    chapter_header_size_max: 17.5
    section_pattern: '^(\d+)\.(\d+)\s+(.+)'
    front_matter_end_page: 18
    exercise_marker_pattern: 'Exercises|Problems|Problem\s+Set'
```

**Field constraints enforced by `BookConfig` Pydantic model at load time:**
- `book_code`: `str`, `max_length=10`, `pattern=r'^[A-Z0-9]+$'`
- `book_slug`: `str`, `pattern=r'^[a-z][a-z0-9_]*$'`
- `pdf_filename`: `str` (path relative to `DATA_DIR`)
- `title`: `str`
- `subject`: `str` (folder name, normalised to lowercase)
- `expert_graph`: `str | None = None`
- `section_header_font`: `str`
- `section_header_size_min`: `float` (gt=0)
- `section_header_size_max`: `float` (gt=0)
- `chapter_header_font`: `str`
- `chapter_header_size_min`: `float` (gt=0)
- `chapter_header_size_max`: `float` (gt=0)
- `section_pattern`: `str` (validated as valid regex)
- `front_matter_end_page`: `int` (ge=0)
- `exercise_marker_pattern`: `str` (validated as valid regex)

### 2.2 `pipeline_runs` DB Table

```sql
CREATE TABLE pipeline_runs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_slug   VARCHAR(50)  NOT NULL,
    status      VARCHAR(20)  NOT NULL,   -- RUNNING | COMPLETED | FAILED
    stage       VARCHAR(30),             -- last stage reached: CALIBRATE | MATHPIX | CHUNKS | GRAPH | HOTLOAD
    error_msg   TEXT,                    -- NULL on success; truncated to 2000 chars
    started_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);
CREATE INDEX ix_pipeline_runs_book_slug ON pipeline_runs (book_slug);
CREATE INDEX ix_pipeline_runs_status    ON pipeline_runs (status);
```

ORM model added to `backend/src/db/models.py`:

```python
class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id:          Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_slug:   Mapped[str]              = mapped_column(String(50), nullable=False)
    status:      Mapped[str]              = mapped_column(String(20), nullable=False)
    stage:       Mapped[str | None]       = mapped_column(String(30), nullable=True)
    error_msg:   Mapped[str | None]       = mapped_column(Text, nullable=True)
    started_at:  Mapped[datetime]         = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None]  = mapped_column(TIMESTAMPTZ, nullable=True)
```

### 2.3 Alembic Migration

**Migration file:** `backend/alembic/versions/{hash}_pipeline_runs_and_remove_book_defaults.py`

```python
def upgrade() -> None:
    # Remove server_default from teaching_sessions.book_slug
    op.alter_column("teaching_sessions", "book_slug", server_default=None)

    # Create pipeline_runs table
    op.create_table(
        "pipeline_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("book_slug", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(30), nullable=True),
        sa.Column("error_msg", sa.Text, nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_pipeline_runs_book_slug", "pipeline_runs", ["book_slug"])
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"])

def downgrade() -> None:
    op.drop_table("pipeline_runs")
    op.alter_column("teaching_sessions", "book_slug", server_default="prealgebra")
```

### 2.4 Data Flow

```
PDF file lands in backend/data/{subject}/
         │
         ▼ FileCreatedEvent (watchdog)
book_watcher.py → derives slug from filename → enqueues (pdf_path, slug, subject) to asyncio.Queue
         │
         ▼ pipeline_runner.py consumes queue item
Stage 1: calibrate_book(pdf_path, slug, subject)
         → reads BOOK_CODE_MAP from books.yaml for existing slugs
         → if slug not found → scan PDF pages 15-40 → detect fonts → write new YAML block
         → INSERT pipeline_runs row (status=RUNNING, stage=CALIBRATE)
         → books.yaml appended (file lock via threading.Lock)

Stage 2: run_whole_pdf_pipeline(book_code)
         → Mathpix /v3/pdf submit → poll until complete → download MMD zip
         → writes backend/output/{slug}/book.mmd
         → UPDATE pipeline_runs (stage=MATHPIX)

Stage 3: build_chunks(slug, mmd_path, db) + _validate_and_clean_images(slug, db)
         → parse_book_mmd(mmd_path) → list[ParsedChunk]
         → for each chunk: embed → upsert concept_chunks + chunk_images rows
         → for each chunk_image: _download_image_with_retry(url, dest_path)
         → _validate_and_clean_images → delete DB rows with no file on disk
         → UPDATE pipeline_runs (stage=CHUNKS)

Stage 4: build_graph(db, slug, graph_path)
         → load ConceptBlock list from concept_chunks for slug
         → build_dependency_edges() → expert YAML or keyword builder
         → save_graph_json(graph, graph_path)
         → UPDATE pipeline_runs (stage=GRAPH)

Stage 5: POST /api/admin/load-book/{slug}  (httpx)
         → FastAPI mounts static image dir + adds slug to live routing tables
         → UPDATE pipeline_runs (status=COMPLETED, stage=HOTLOAD, finished_at=NOW())
```

### 2.5 Caching Strategy

- `books.yaml` is loaded once at FastAPI startup into `BOOK_REGISTRY` dict in memory. After a pipeline writes a new entry, the hot-load endpoint re-loads `books.yaml` so the in-memory registry is updated without restart.
- `pipeline.log` files are written per-slug to `backend/output/{slug}/pipeline.log`. These are append-only during a run and readable by DevOps via `docker compose exec book-watcher tail -f`.
- Mathpix MMD is cached at `backend/output/{slug}/book.mmd`. If this file exists, Stage 2 is skipped on retry.

### 2.6 Data Retention

- `pipeline_runs` rows are retained indefinitely. No auto-pruning is implemented in v1. Operators can manually DELETE rows older than N days if the table grows large.
- `pipeline.log` files accumulate. No rotation. Log rotation is handled by the OS/Docker logging driver.

---

## 3. API Design

### 3.1 Existing Endpoint Modified

**`GET /api/v1/books`** — add `subject` field to each book object in response.

```json
Response 200:
[
  {
    "slug": "prealgebra",
    "title": "Prealgebra 2e",
    "subject": "mathematics",
    "concept_count": 312
  },
  {
    "slug": "financial_accounting",
    "title": "Financial Accounting",
    "subject": "business",
    "concept_count": 198
  }
]
```

No version bump required — adding a field is non-breaking.

### 3.2 New Admin Endpoints

All admin endpoints require `X-API-Key: {API_SECRET_KEY}` header. They are mounted under `/api/admin/` and excluded from the student-facing rate limiter.

---

**`POST /api/admin/load-book/{slug}`**

```
POST /api/admin/load-book/{slug}
Headers: X-API-Key: <secret>

Path params:
  slug   string   Required. Book slug to load (must exist in books.yaml).

Response 200:
{
  "slug": "financial_accounting",
  "status": "loaded",
  "concept_count": 198,
  "image_dir_mounted": true
}

Response 404:
{
  "detail": "Slug 'financial_accounting' not found in books.yaml"
}

Response 409:
{
  "detail": "Book 'financial_accounting' is already loaded."
}
```

Implementation in `main.py`:
1. Reload `books.yaml` → update in-memory `BOOK_REGISTRY`.
2. Mount `StaticFiles` for `output/{slug}/images/` at `/images/{slug}` (catch `AssertionError` if already mounted — silent pass).
3. Instantiate or re-use `ChunkKnowledgeService` for the slug.
4. Return count of `concept_chunks` rows for the slug.

---

**`GET /api/admin/pipeline-runs`**

```
GET /api/admin/pipeline-runs?limit=20&book_slug=financial_accounting
Headers: X-API-Key: <secret>

Query params:
  limit       int    Optional. Default 20, max 100.
  book_slug   str    Optional. Filter by slug.

Response 200:
{
  "runs": [
    {
      "id": "uuid",
      "book_slug": "financial_accounting",
      "status": "COMPLETED",
      "stage": "HOTLOAD",
      "error_msg": null,
      "started_at": "2026-04-08T14:00:00Z",
      "finished_at": "2026-04-08T17:30:00Z"
    }
  ]
}
```

### 3.3 Authentication

Admin endpoints are protected by the existing `APIKeyMiddleware` via the `X-API-Key` header (`secrets.compare_digest`). No new auth mechanism is introduced.

### 3.4 Versioning Strategy

Admin endpoints live under `/api/admin/` — not versioned. They are operator-facing, not student-facing, and are not part of the public API contract.

### 3.5 Error Handling Conventions

- `404` when slug not found in `books.yaml`.
- `409` when book is already loaded (idempotent hot-load returns 200 for repeated calls to avoid breaking the pipeline runner on retry).
- `500` with `{"detail": "Internal error: <truncated message>"}` on unexpected failures. Full traceback is logged at `ERROR` level.

---

## 4. Sequence Diagrams

### 4.1 Happy Path — New PDF Drop to Book Live

```
DevOps                  book_watcher      pipeline_runner       Mathpix API       FastAPI (uvicorn)    PostgreSQL
  │                         │                   │                    │                  │                  │
  │ scp PDF to              │                   │                    │                  │                  │
  │ data/business/          │                   │                    │                  │                  │
  │────────────────────────►│                   │                    │                  │                  │
  │                         │ on_created event  │                    │                  │                  │
  │                         │ (watchdog)        │                    │                  │                  │
  │                         │ wait 5s stable    │                    │                  │                  │
  │                         │ Queue.put()       │                    │                  │                  │
  │                         │──────────────────►│                    │                  │                  │
  │                         │                   │ INSERT pipeline_run│                  │                  │
  │                         │                   │─────────────────────────────────────────────────────────►│
  │                         │                   │                    │                  │                  │
  │                         │                   │ [Stage 1] calibrate_book()            │                  │
  │                         │                   │ append to books.yaml                  │                  │
  │                         │                   │                    │                  │                  │
  │                         │                   │ [Stage 2] submit PDF                 │                  │
  │                         │                   │───────────────────►│                  │                  │
  │                         │                   │ poll until done    │                  │                  │
  │                         │                   │◄───────────────────│                  │                  │
  │                         │                   │ download MMD zip   │                  │                  │
  │                         │                   │                    │                  │                  │
  │                         │                   │ [Stage 3] build_chunks + embed        │                  │
  │                         │                   │─────────────────────────────────────────────────────────►│
  │                         │                   │ _validate_and_clean_images            │                  │
  │                         │                   │                    │                  │                  │
  │                         │                   │ [Stage 4] build_graph                 │                  │
  │                         │                   │─────────────────────────────────────────────────────────►│
  │                         │                   │ save graph.json                       │                  │
  │                         │                   │                    │                  │                  │
  │                         │                   │ [Stage 5] POST /api/admin/load-book   │                  │
  │                         │                   │──────────────────────────────────────►│                  │
  │                         │                   │                    │                  │ reload books.yaml │
  │                         │                   │                    │                  │ mount /images/slug│
  │                         │                   │                    │                  │ init KnowledgeSvc │
  │                         │                   │◄──────────────────────────────────────│                  │
  │                         │                   │ UPDATE pipeline_run COMPLETED         │                  │
  │                         │                   │─────────────────────────────────────────────────────────►│
```

### 4.2 Error Path — Stage 3 Chunk Embedding Fails

```
pipeline_runner                                           PostgreSQL
      │                                                       │
      │ [Stage 3] build_chunks raises OpenAI API error        │
      │ except Exception as e:                                │
      │   UPDATE pipeline_runs SET status='FAILED',           │
      │          stage='CHUNKS', error_msg=str(e)[:2000]     │
      │   logger.exception("[pipeline] FAILED stage CHUNKS")  │
      │──────────────────────────────────────────────────────►│
      │                                                        │
      │ raise → task ends cleanly                             │
      │ (watcher loop continues; book stays in FAILED state)  │
```

No automatic retry. DevOps must investigate `pipeline.log` and re-run `bootstrap_existing.py` or manually re-enqueue.

### 4.3 Image Retry Flow

```
chunk_builder._download_image_with_retry(url, dest_path, max_retries=3)
  attempt=0: GET url → 503 → sleep 2^0 = 1s → attempt=1
  attempt=1: GET url → 503 → sleep 2^1 = 2s → attempt=2
  attempt=2: GET url → 200 → write bytes to dest_path → return True
  → if all 3 attempts fail: logger.warning() → return False
```

---

## 5. Component Specifications

### 5.1 `backend/src/extraction/calibrate.py`

```python
def calibrate_book(pdf_path: Path, slug: str, subject: str) -> dict:
    """
    Scan PDF pages 15–40 with PyMuPDF to detect font signatures and
    structural patterns. Returns a complete BOOK_REGISTRY entry dict
    ready to be appended to books.yaml.

    Algorithm:
    1. Open PDF with fitz.open(pdf_path).
    2. Scan pages[15:41] — skips front matter, stays in main body.
    3. For each page, call page.get_text("dict")["blocks"].
    4. Collect all spans where span["flags"] & 16 (bold flag is bit 4).
    5. Bucket bold spans by font name + rounded size into a counter.
    6. section_header_font: most frequent bold font in size range 12–16pt
       whose text matches r'^\d+\.\d+\s+' (section number pattern).
    7. chapter_header_font: most frequent bold font in size range 16–20pt
       whose text matches r'^\d+\s+\w' (chapter heading pattern).
    8. front_matter_end_page: first page index where a span matches
       r'^\d+\.\d+\s+' at the detected section_header_font+size.
    9. exercise_marker_pattern: scan for first occurrence of
       "Exercises", "Problems", or "Problem Set" in bold text;
       derive pattern as r'Exercises|Problems|Problem\s+Set'.
    10. Derive book_code: first letter of each slug word (split on '_'),
        join, uppercase, truncate to 10 chars.
        Example: financial_accounting → FA → FIACCT (if FA taken, append digits).
    11. Return dict matching BookConfig schema.

    Returns:
        dict with all required BOOK_REGISTRY fields.

    Raises:
        ValueError: if section_header_font cannot be detected (< 3 matching spans found).
        FileNotFoundError: if pdf_path does not exist.
    """
```

**Slug derivation (internal helper):**

```python
def derive_slug_from_filename(pdf_filename: str) -> str:
    """
    Strip known suffixes, normalise to snake_case lowercase.

    Rules applied in order:
    1. Strip file extension.
    2. Remove -OP_[A-Za-z0-9]+ suffix (OpenStax CDN hash).
    3. Remove -WEB, -2e, -3e, version strings like -v2, -v3.
    4. Replace remaining hyphens and spaces with underscores.
    5. Lowercase.
    6. Collapse multiple consecutive underscores to one.
    7. Strip leading/trailing underscores.

    Examples:
      FinancialAccounting-OP_YioY6nY.pdf → financial_accounting
      Fundamentals_of_Nursing_-_WEB.pdf  → fundamentals_of_nursing
      Clinical-Nursing-Skills-WEB.pdf    → clinical_nursing_skills
      prealgebra.pdf                     → prealgebra
    """
    import re
    stem = Path(pdf_filename).stem
    stem = re.sub(r"-OP_[A-Za-z0-9]+", "", stem)
    stem = re.sub(r"[-_](WEB|2e|3e|v\d+)$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[-\s]+", "_", stem)
    stem = stem.lower()
    stem = re.sub(r"_+", "_", stem).strip("_")
    return stem


def derive_book_code(slug: str, existing_codes: set[str]) -> str:
    """
    Derive a unique book code from slug.
    Take first letter of each word, uppercase, max 10 chars.
    If collision, append incrementing digit suffix.

    Examples:
      financial_accounting → FA (if free) or FA2 (if FA taken)
      fundamentals_of_nursing → FON
    """
    words = slug.split("_")
    base = "".join(w[0].upper() for w in words if w)[:10]
    code = base
    suffix = 2
    while code in existing_codes:
        code = f"{base[:9]}{suffix}"
        suffix += 1
    return code
```

**YAML append (thread-safe):**

```python
_yaml_write_lock = threading.Lock()

def append_to_books_yaml(yaml_path: Path, book_code: str, entry: dict) -> None:
    """
    Thread-safe append of a new book entry to books.yaml.
    Uses threading.Lock (not asyncio.Lock) because file I/O is synchronous.
    Reads existing YAML, merges new entry, writes back atomically via
    a temp file + os.replace().
    """
    with _yaml_write_lock:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {"books": {}}
        data["books"][book_code] = entry
        tmp = yaml_path.with_suffix(".yaml.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        os.replace(tmp, yaml_path)
```

---

### 5.2 `backend/src/watcher/book_watcher.py`

```python
"""
book_watcher.py — Filesystem watcher for backend/data/{subject}/.

Starts a watchdog Observer on DATA_DIR and enqueues any new .pdf file
into a shared asyncio.Queue for the pipeline runner to consume.

Subject normalisation:
  The parent folder name is used as the subject.
  'maths' → 'mathematics'  (legacy normalisation — the existing maths folder)
  All other folder names are lowercased and used as-is.

Run as: python -m src.watcher.book_watcher
"""

import asyncio
import logging
import os
from pathlib import Path

from watchdog.events import FileCreatedEvent, FileMovedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from config import DATA_DIR

logger = logging.getLogger(__name__)

# Subject normalisation map
_SUBJECT_NORMALISE = {
    "maths": "mathematics",
}

_STABLE_WAIT_SECONDS = 5   # seconds to wait for file size to stabilise
_STABLE_POLL_INTERVAL = 1  # poll interval during stability check


class PDFHandler(FileSystemEventHandler):
    """
    Handles filesystem events in backend/data/.

    Only .pdf files trigger the pipeline. Directory creation events and
    non-PDF files are silently ignored.
    """

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
        self._queue = queue
        self._loop = loop

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".pdf":
            return
        self._schedule(path)

    def on_moved(self, event: FileMovedEvent) -> None:
        # Handles drag-and-drop or atomic rename into the watched dir
        if event.is_directory:
            return
        path = Path(event.dest_path)
        if path.suffix.lower() != ".pdf":
            return
        self._schedule(path)

    def _schedule(self, path: Path) -> None:
        """Derive subject + slug, wait for file stability, enqueue."""
        raw_subject = path.parent.name.lower()
        subject = _SUBJECT_NORMALISE.get(raw_subject, raw_subject)
        slug = derive_slug_from_filename(path.name)  # imported from calibrate
        logger.info("[watcher] New PDF detected: %s → slug=%s subject=%s", path, slug, subject)
        # Schedule the stability check + enqueue on the asyncio event loop
        asyncio.run_coroutine_threadsafe(
            self._wait_and_enqueue(path, slug, subject), self._loop
        )

    async def _wait_and_enqueue(self, path: Path, slug: str, subject: str) -> None:
        """Wait until file size is stable, then enqueue."""
        prev_size = -1
        for _ in range(60):  # max 60 seconds
            size = path.stat().st_size if path.exists() else 0
            if size == prev_size and size > 0:
                break
            prev_size = size
            await asyncio.sleep(_STABLE_POLL_INTERVAL)
        logger.info("[watcher] File stable at %d bytes: %s", prev_size, path)
        await self._queue.put((path, slug, subject))


async def watch_forever(queue: asyncio.Queue) -> None:
    """Start the watchdog Observer and block until cancelled."""
    handler = PDFHandler(queue, asyncio.get_event_loop())
    observer = Observer()
    observer.schedule(handler, str(DATA_DIR), recursive=True)
    observer.start()
    logger.info("[watcher] Watching %s for new PDFs", DATA_DIR)
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        observer.stop()
        observer.join()


async def main() -> None:
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    # Import here to avoid circular import during module load
    from watcher.pipeline_runner import run_pipeline_worker
    await asyncio.gather(
        watch_forever(queue),
        run_pipeline_worker(queue),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(main())
```

---

### 5.3 `backend/src/watcher/pipeline_runner.py`

```python
"""
pipeline_runner.py — 5-stage async orchestrator for book ingestion.

Consumes (pdf_path, slug, subject) tuples from asyncio.Queue.
Runs one book at a time (sequential processing — avoids Mathpix rate limits).

Stage summary:
  1. CALIBRATE  — detect fonts; append entry to books.yaml
  2. MATHPIX    — submit PDF to Mathpix; wait; download MMD zip
  3. CHUNKS     — parse MMD → embed → upsert to PostgreSQL; validate images
  4. GRAPH      — build dependency graph; write graph.json
  5. HOTLOAD    — POST /api/admin/load-book/{slug}

Each stage updates pipeline_runs.stage in DB.
On any exception, pipeline_runs.status → FAILED and the error is logged.
The worker then picks up the next queue item — it never crashes.
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    OUTPUT_DIR,
    API_SECRET_KEY,    # new constant: os.getenv("API_SECRET_KEY")
    API_BASE_URL,      # new constant: os.getenv("API_BASE_URL", "http://localhost:8889")
    BOOKS_YAML_PATH,   # new constant: BACKEND_DIR / "books.yaml"
)
from db.connection import get_async_session
from db.models import PipelineRun
from extraction.calibrate import calibrate_book, append_to_books_yaml
from extraction.chunk_builder import build_chunks, _validate_and_clean_images
from graph.dependency_builder import build_dependency_edges
from graph.graph_store import save_graph_json

logger = logging.getLogger(__name__)

_STAGE_CALIBRATE = "CALIBRATE"
_STAGE_MATHPIX   = "MATHPIX"
_STAGE_CHUNKS    = "CHUNKS"
_STAGE_GRAPH     = "GRAPH"
_STAGE_HOTLOAD   = "HOTLOAD"


async def run_pipeline_worker(queue: asyncio.Queue) -> None:
    """Consume queue items indefinitely; process one book at a time."""
    while True:
        pdf_path, slug, subject = await queue.get()
        try:
            await _run_pipeline(pdf_path, slug, subject)
        except Exception:
            logger.exception("[pipeline] Unhandled error for slug=%s — continuing", slug)
        finally:
            queue.task_done()


async def _run_pipeline(pdf_path: Path, slug: str, subject: str) -> None:
    log_path = OUTPUT_DIR / slug / "pipeline.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(file_handler)

    async with get_async_session() as db:
        run = PipelineRun(book_slug=slug, status="RUNNING", stage=_STAGE_CALIBRATE,
                          started_at=datetime.now(timezone.utc))
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

        try:
            # ── Stage 1: Calibrate ──────────────────────────────────────
            logger.info("[pipeline:%s] Stage 1 CALIBRATE", slug)
            entry = calibrate_book(pdf_path, slug, subject)
            book_code = entry["book_code"]
            append_to_books_yaml(BOOKS_YAML_PATH, book_code, entry)
            await _update_stage(db, run_id, _STAGE_MATHPIX)

            # ── Stage 2: Mathpix OCR ────────────────────────────────────
            logger.info("[pipeline:%s] Stage 2 MATHPIX", slug)
            mmd_path = OUTPUT_DIR / slug / "book.mmd"
            if not mmd_path.exists():
                await asyncio.get_event_loop().run_in_executor(
                    None, _run_mathpix_sync, book_code
                )
            else:
                logger.info("[pipeline:%s] MMD cache hit — skipping Mathpix", slug)
            await _update_stage(db, run_id, _STAGE_CHUNKS)

            # ── Stage 3: Chunk/Embed/Images ─────────────────────────────
            logger.info("[pipeline:%s] Stage 3 CHUNKS", slug)
            await build_chunks(slug, mmd_path, db)
            deleted = await _validate_and_clean_images(slug, db)
            logger.info("[pipeline:%s] Image validation removed %d orphan rows", slug, deleted)
            await _update_stage(db, run_id, _STAGE_GRAPH)

            # ── Stage 4: Dependency Graph ───────────────────────────────
            logger.info("[pipeline:%s] Stage 4 GRAPH", slug)
            graph_path = OUTPUT_DIR / slug / "graph.json"
            await _build_graph(slug, graph_path, db)
            await _update_stage(db, run_id, _STAGE_HOTLOAD)

            # ── Stage 5: Hot-Load ───────────────────────────────────────
            logger.info("[pipeline:%s] Stage 5 HOTLOAD", slug)
            await _hot_load(slug)

            # ── Success ─────────────────────────────────────────────────
            await _mark_completed(db, run_id)
            logger.info("[pipeline:%s] COMPLETED — book is LIVE", slug)

        except Exception as exc:
            err_msg = str(exc)[:2000]
            logger.exception("[pipeline:%s] FAILED", slug)
            await _mark_failed(db, run_id, err_msg)
            raise
        finally:
            logger.removeHandler(file_handler)
            file_handler.close()


def _run_mathpix_sync(book_code: str) -> None:
    """Synchronous Mathpix call — run in executor to avoid blocking event loop."""
    from pipeline import run_whole_pdf_pipeline
    run_whole_pdf_pipeline(book_code)


async def _build_graph(slug: str, graph_path: Path, db: AsyncSession) -> None:
    from sqlalchemy import select
    from db.models import ConceptChunk
    from extraction.domain_models import ConceptBlock
    from graph.dependency_builder import build_dependency_edges
    from graph.graph_store import create_graph, save_graph_json

    result = await db.execute(
        select(ConceptChunk).where(ConceptChunk.book_slug == slug)
    )
    chunks = result.scalars().all()
    # Build minimal ConceptBlock list from chunk rows (concept_id + book_slug + heading)
    seen = {}
    blocks = []
    for c in chunks:
        if c.concept_id not in seen:
            seen[c.concept_id] = True
            blocks.append(ConceptBlock(
                concept_id=c.concept_id,
                book_slug=slug,
                title=c.heading or c.concept_id,
                text="",
                prerequisites=[],
            ))
    edges = build_dependency_edges(blocks)
    graph = create_graph(blocks, edges)
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    save_graph_json(graph, graph_path)


async def _hot_load(slug: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{API_BASE_URL}/api/admin/load-book/{slug}",
            headers={"X-API-Key": API_SECRET_KEY},
        )
        resp.raise_for_status()


async def _update_stage(db: AsyncSession, run_id, stage: str) -> None:
    from sqlalchemy import update
    from db.models import PipelineRun
    await db.execute(
        update(PipelineRun).where(PipelineRun.id == run_id).values(stage=stage)
    )
    await db.commit()


async def _mark_completed(db: AsyncSession, run_id) -> None:
    from sqlalchemy import update
    from db.models import PipelineRun
    await db.execute(
        update(PipelineRun).where(PipelineRun.id == run_id).values(
            status="COMPLETED",
            stage=_STAGE_HOTLOAD,
            finished_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


async def _mark_failed(db: AsyncSession, run_id, error_msg: str) -> None:
    from sqlalchemy import update
    from db.models import PipelineRun
    await db.execute(
        update(PipelineRun).where(PipelineRun.id == run_id).values(
            status="FAILED",
            error_msg=error_msg,
            finished_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
```

---

### 5.4 Image Retry and Validation

These functions are added to `backend/src/extraction/chunk_builder.py`:

```python
async def _download_image_with_retry(
    url: str,
    dest_path: Path,
    max_retries: int = 3,
) -> bool:
    """
    Download an image from url to dest_path with exponential back-off retry.

    Returns True on success, False if all attempts exhausted.

    Back-off: sleep 2^attempt seconds before each retry (attempt 0 → 1s, 1 → 2s, 2 → 4s).
    Uses httpx.AsyncClient for async-safe downloads.
    Skips download if dest_path already exists and size > 0 (idempotent).
    """
    if dest_path.exists() and dest_path.stat().st_size > 0:
        return True
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
            dest_path.write_bytes(resp.content)
            return True
        except Exception as exc:
            wait = 2 ** attempt
            logger.warning(
                "[image-retry] attempt %d/%d failed for %s: %s — retrying in %ds",
                attempt + 1, max_retries, url, exc, wait,
            )
            await asyncio.sleep(wait)
    logger.error("[image-retry] All %d attempts failed for %s", max_retries, url)
    return False


async def _validate_and_clean_images(book_slug: str, db: AsyncSession) -> int:
    """
    Query all chunk_images rows for book_slug, check each referenced file
    exists on disk, delete DB rows where the file is absent.

    Returns the count of deleted rows.

    This prevents 404 errors from reaching students after the pipeline
    completes if Mathpix CDN image downloads failed silently.
    """
    from sqlalchemy import select, delete
    from db.models import ChunkImage, ConceptChunk

    result = await db.execute(
        select(ChunkImage, ConceptChunk.book_slug)
        .join(ConceptChunk, ChunkImage.chunk_id == ConceptChunk.id)
        .where(ConceptChunk.book_slug == book_slug)
    )
    rows = result.all()
    orphan_ids = []
    for img, _ in rows:
        # image_url is the public URL; derive local path from URL
        local_path = _url_to_local_path(img.image_url, book_slug)
        if not local_path.exists():
            orphan_ids.append(img.id)

    if orphan_ids:
        await db.execute(delete(ChunkImage).where(ChunkImage.id.in_(orphan_ids)))
        await db.commit()
        logger.info("[validate-images] Deleted %d orphan rows for %s", len(orphan_ids), book_slug)
    return len(orphan_ids)


def _url_to_local_path(image_url: str, book_slug: str) -> Path:
    """
    Convert a public image URL back to its local filesystem path.
    URL format: /images/{book_slug}/images_downloaded/{filename}
    Local path: OUTPUT_DIR/{book_slug}/images_downloaded/{filename}
    """
    from config import OUTPUT_DIR
    filename = Path(image_url).name
    return OUTPUT_DIR / book_slug / "images_downloaded" / filename
```

---

### 5.5 `backend/src/graph/expert_graphs/prealgebra.yaml`

```yaml
# Expert prerequisite graph for Prealgebra 2e
# Format:
#   nodes: list of concept_id strings (must match concept_ids in concept_chunks table)
#   edges: list of [from_concept_id, to_concept_id] pairs
#          meaning "from is a prerequisite of to"
#          i.e., to cannot be studied without first completing from.

metadata:
  slug: prealgebra
  version: 1
  description: >
    Hand-curated prerequisite DAG for OpenStax Prealgebra 2e.
    Design principles: skill dependency only (not textbook sequence),
    no transitive edges (direct prerequisites only),
    parallel branches for independent topics.

nodes:
  - whole_numbers
  - language_of_algebra
  - integers
  - fractions
  - decimals
  - percents
  - properties_of_real_numbers
  - solving_linear_equations
  - math_models
  - graphs
  - polynomials
  - factoring
  - rational_expressions
  - roots_and_radicals
  - quadratic_equations

edges:
  # Operations hierarchy
  - [whole_numbers, language_of_algebra]
  - [whole_numbers, integers]
  - [integers, fractions]
  - [fractions, decimals]
  - [decimals, percents]
  # Algebra branch
  - [language_of_algebra, solving_linear_equations]
  - [solving_linear_equations, math_models]
  - [solving_linear_equations, graphs]
  # Polynomial branch (requires algebra + fractions)
  - [solving_linear_equations, polynomials]
  - [polynomials, factoring]
  - [factoring, rational_expressions]
  - [fractions, rational_expressions]
  # Radicals (requires decimals + algebra)
  - [decimals, roots_and_radicals]
  - [solving_linear_equations, roots_and_radicals]
  # Quadratic (requires factoring + radicals)
  - [factoring, quadratic_equations]
  - [roots_and_radicals, quadratic_equations]
  # Properties (parallel; prerequisite for abstract algebra)
  - [integers, properties_of_real_numbers]
```

**YAML loader in `dependency_builder.py`:**

```python
_EXPERT_GRAPHS_DIR = Path(__file__).resolve().parent / "expert_graphs"

def _get_expert_graph(book_slug: str) -> dict | None:
    """
    Load expert prerequisite map from YAML file for the given slug.
    Returns dict[concept_id -> list[prerequisite_concept_id]] or None.
    Falls back to keyword builder if no YAML file exists for the slug.
    """
    yaml_path = _EXPERT_GRAPHS_DIR / f"{book_slug}.yaml"
    if not yaml_path.exists():
        return None
    import yaml
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    # Build adjacency: to_node → [from_nodes] (prereq map)
    prereq_map: dict[str, list[str]] = {node: [] for node in data.get("nodes", [])}
    for from_id, to_id in data.get("edges", []):
        if to_id in prereq_map:
            prereq_map[to_id].append(from_id)
    return prereq_map if prereq_map else None
```

---

### 5.6 `backend/scripts/bootstrap_existing.py`

```python
#!/usr/bin/env python3
"""
bootstrap_existing.py — One-time bootstrap for PDFs already in backend/data/.

Scans DATA_DIR recursively for *.pdf files.
Skips any slug already registered in books.yaml.
For each new PDF, directly calls pipeline_runner._run_pipeline() synchronously
(not via watchdog queue — this is a one-shot operator script, not the watcher).

Usage:
    python scripts/bootstrap_existing.py [--dry-run]

Options:
    --dry-run   Print what would be processed without actually running the pipeline.

Output:
    For each PDF: prints "SKIP {slug} (already in books.yaml)" or "QUEUE {slug}".
    On completion: prints summary table with status for each slug.
"""

import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml
from config import DATA_DIR, BOOKS_YAML_PATH
from extraction.calibrate import derive_slug_from_filename

_SUBJECT_NORMALISE = {"maths": "mathematics"}


def _load_registered_slugs(yaml_path: Path) -> set[str]:
    if not yaml_path.exists():
        return set()
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {v["book_slug"] for v in data.get("books", {}).values()}


def _find_pdfs() -> list[tuple[Path, str, str]]:
    """Return list of (pdf_path, slug, subject) for all PDFs in DATA_DIR."""
    results = []
    for pdf in sorted(DATA_DIR.rglob("*.pdf")):
        raw_subject = pdf.parent.name.lower()
        subject = _SUBJECT_NORMALISE.get(raw_subject, raw_subject)
        slug = derive_slug_from_filename(pdf.name)
        results.append((pdf, slug, subject))
    return results


async def bootstrap(dry_run: bool = False) -> None:
    registered = _load_registered_slugs(BOOKS_YAML_PATH)
    pdfs = _find_pdfs()

    print(f"Found {len(pdfs)} PDF(s) in {DATA_DIR}")
    print(f"Already registered: {len(registered)} slug(s)")
    print()

    to_process = []
    for pdf_path, slug, subject in pdfs:
        if slug in registered:
            print(f"  SKIP {slug:40s}  (already in books.yaml)")
        else:
            print(f"  QUEUE {slug:39s}  subject={subject}  pdf={pdf_path.name}")
            to_process.append((pdf_path, slug, subject))

    print()
    if not to_process:
        print("Nothing to process. All PDFs are already registered.")
        return

    if dry_run:
        print(f"[dry-run] Would process {len(to_process)} PDF(s).")
        return

    print(f"Processing {len(to_process)} PDF(s) sequentially...")
    from watcher.pipeline_runner import _run_pipeline

    results = []
    for pdf_path, slug, subject in to_process:
        print(f"\n--- Starting pipeline for: {slug} ---")
        try:
            await _run_pipeline(pdf_path, slug, subject)
            results.append((slug, "COMPLETED"))
        except Exception as exc:
            results.append((slug, f"FAILED: {exc}"))

    print("\n=== Bootstrap Summary ===")
    for slug, status in results:
        print(f"  {slug:40s}  {status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap pre-existing PDFs into the ADA pipeline.")
    parser.add_argument("--dry-run", action="store_true", help="Print without executing.")
    args = parser.parse_args()
    asyncio.run(bootstrap(dry_run=args.dry_run))
```

---

### 5.7 `backend/src/config.py` YAML Loader (replacing hardcoded dicts)

```python
# ── Books YAML Registry ────────────────────────────────────────────────
import yaml as _yaml
from pydantic import BaseModel, field_validator
import re as _re

BOOKS_YAML_PATH = BACKEND_DIR / "books.yaml"

class BookConfig(BaseModel):
    book_code:               str
    book_slug:               str
    pdf_filename:            str
    title:                   str
    subject:                 str
    expert_graph:            str | None = None
    section_header_font:     str
    section_header_size_min: float
    section_header_size_max: float
    chapter_header_font:     str
    chapter_header_size_min: float
    chapter_header_size_max: float
    section_pattern:         str
    front_matter_end_page:   int
    exercise_marker_pattern: str

    @field_validator("section_pattern", "exercise_marker_pattern")
    @classmethod
    def valid_regex(cls, v: str) -> str:
        try:
            _re.compile(v)
        except _re.error as e:
            raise ValueError(f"Invalid regex pattern: {v!r} → {e}") from e
        return v


def _load_books_yaml(yaml_path: Path) -> tuple[dict, dict]:
    """
    Load books.yaml and return (BOOK_REGISTRY, BOOK_CODE_MAP).
    Validates every entry with BookConfig.
    Raises ValueError with field name on schema mismatch.
    """
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"books.yaml not found at {yaml_path}. "
            "Create it from books.yaml.example or run calibrate_book() first."
        )
    with open(yaml_path, "r", encoding="utf-8") as f:
        raw = _yaml.safe_load(f) or {}

    registry: dict = {}
    code_map: dict = {}
    for book_code, entry in raw.get("books", {}).items():
        validated = BookConfig(**entry).model_dump()
        registry[book_code] = validated
        code_map[validated["book_slug"]] = book_code

    return registry, code_map


BOOK_REGISTRY, BOOK_CODE_MAP = _load_books_yaml(BOOKS_YAML_PATH)

# New constants for watcher/pipeline
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")
API_BASE_URL   = os.getenv("API_BASE_URL", "http://localhost:8889")
```

---

## 6. Security Design

### Authentication and Authorization
- Admin endpoints (`/api/admin/*`) require `X-API-Key: {API_SECRET_KEY}` header. The existing `APIKeyMiddleware` covers this — no new middleware needed.
- The `API_SECRET_KEY` used by `pipeline_runner.py` to call the hot-load endpoint is read from the environment variable of the same name — the same key as the FastAPI server. Both services (FastAPI and watcher) mount the same `.env` via docker-compose shared environment.

### Data Encryption
- `books.yaml` contains no secrets (no API keys, passwords, or PII). It is safe to commit to version control.
- PDF files are never served over HTTP. They remain on the server filesystem only. No API endpoint exposes the raw PDF bytes.
- All Mathpix API calls use HTTPS. The Mathpix credentials remain in `.env` only.

### Input Validation and Sanitization
- `derive_slug_from_filename()` produces a slug using only `[a-z0-9_]` characters — no path traversal is possible.
- `calibrate_book()` only opens the PDF file at the path provided by the watcher (a watchdog `FileCreatedEvent.src_path`). The watcher only listens to `DATA_DIR` (not a user-facing upload endpoint), so arbitrary file reads are not possible.
- `BookConfig` Pydantic model validates every field of a YAML entry at load time, including regex pattern validity.

### Secrets Management
- `API_SECRET_KEY` and `API_BASE_URL` are added to `.env.example` as documented empty strings. They are never hardcoded in source.
- The watcher Docker service receives secrets via docker-compose `environment:` block referencing host env vars — not committed values.

---

## 7. Observability Design

### Logging Strategy

All pipeline log messages use the prefix pattern `[pipeline:{slug}]` or `[watcher]` for easy filtering.

| Logger | Level | When |
|---|---|---|
| `book_watcher` | INFO | PDF detected, file stable, item enqueued |
| `pipeline_runner` | INFO | Stage start, stage complete, book LIVE |
| `pipeline_runner` | WARNING | Mathpix retry, image download retry |
| `pipeline_runner` | ERROR | Stage failed, error message included |
| `calibrate` | INFO | Detected font, detected page range, generated slug |
| `calibrate` | WARNING | Low section count detected (< 10 sections) |
| `chunk_builder` | WARNING | Image download retry / all retries exhausted |

All log messages also written to `backend/output/{slug}/pipeline.log` (per-book file handler added/removed per pipeline run).

Structured log format (stdout — for Docker logging stack ingestion):
```
%(asctime)s [%(levelname)s] %(name)s: %(message)s
```

### Key Metrics (manual monitoring via DB query)

```sql
-- Books processing in last 24h
SELECT book_slug, status, stage,
       EXTRACT(EPOCH FROM (finished_at - started_at))/3600 AS hours
FROM pipeline_runs
WHERE started_at > NOW() - INTERVAL '24 hours'
ORDER BY started_at DESC;
```

### Alerting

No automated alerting in v1. Operators monitor via:
1. `docker compose logs book-watcher -f` for real-time output.
2. `GET /api/admin/pipeline-runs` (admin endpoint) for status dashboard.
3. `SELECT * FROM pipeline_runs WHERE status='FAILED'` for failures.

### Distributed Tracing

Not applicable — single-host deployment with no cross-service fan-out beyond the Mathpix API call.

---

## 8. Error Handling and Resilience

### Retry Policies

| Failure | Retry | Back-off |
|---|---|---|
| Image CDN download | Up to 3 attempts | Exponential: 1s, 2s, 4s |
| Mathpix PDF submission | Not retried automatically (expensive, uses quota) | Manual re-run via bootstrap |
| `POST /api/admin/load-book` | Not retried — if hot-load fails, pipeline is marked FAILED | Operator re-runs bootstrap |
| OpenAI embedding (chunk_builder) | Existing retry logic in `chunk_builder.py` | Unchanged |

### Timeouts

| Call | Timeout |
|---|---|
| `httpx.AsyncClient` for hot-load | 10 seconds |
| `httpx.AsyncClient` for image download | 30 seconds |
| Mathpix poll interval | `await asyncio.sleep(30)` between polls |
| File stability check | Max 60 seconds, then proceeds with current size |

### Graceful Degradation

- If `calibrate_book()` cannot detect a section header font (fewer than 3 matching spans), it raises `ValueError`. The pipeline stage is marked `FAILED`. The book is not added to `books.yaml`. The operator must inspect the PDF manually and add the YAML entry by hand.
- If `_validate_and_clean_images()` fails (DB error), it logs the exception and returns 0 — the pipeline continues. Orphan rows may cause 404s for some images but do not prevent the book from going live.
- If the `books.yaml` file is missing at startup, FastAPI raises `FileNotFoundError` with a clear message pointing to `books.yaml.example`. The server does not start with an empty registry.

### Failure Scenarios

| Scenario | Behaviour |
|---|---|
| Watcher process crashes | Docker `restart: always` restarts it. On restart, `rescan_on_startup()` re-enqueues any PDF whose slug has no `COMPLETED` pipeline_runs row. |
| `books.yaml` is corrupt YAML | `_load_books_yaml()` raises `yaml.YAMLError` at startup with line number — server fails fast with clear error. |
| Mathpix quota exhausted | Mathpix API returns HTTP 429. `run_whole_pdf_pipeline()` logs the error. Pipeline stage marked `FAILED`. Operator resolves quota and re-runs. |
| PDF partially written when event fires | 5-second file-size stability check absorbs write completion for files up to ~5 MB/s. For very large PDFs (>2 GB) on slow storage, the operator should use `scp` followed by `mv` (atomic rename triggers `on_moved`). |
| Duplicate PDF drop (same slug) | `calibrate_book()` detects existing entry in `books.yaml` (check before writing) and skips append. Mathpix skips if MMD exists. Chunk upsert is idempotent. Pipeline runs to completion safely. |

---

## 9. Testing Strategy

### Unit Tests

File: `backend/tests/test_book_pipeline.py`

| Test ID | Test Name | Assertion |
|---|---|---|
| T-01 | `test_calibrate_detects_fonts_from_pdf` | `calibrate_book()` returns dict with non-empty `section_header_font` for a real OpenStax PDF |
| T-02 | `test_calibrate_derives_slug_from_messy_filename` | `derive_slug_from_filename("FinancialAccounting-OP_YioY6nY.pdf")` == `"financial_accounting"` |
| T-03 | `test_calibrate_derives_slug_web_suffix` | `derive_slug_from_filename("Fundamentals_of_Nursing_-_WEB.pdf")` == `"fundamentals_of_nursing"` |
| T-04 | `test_calibrate_detects_front_matter_end_page` | `front_matter_end_page > 0` for prealgebra PDF |
| T-05 | `test_derive_book_code_no_collision` | `derive_book_code("financial_accounting", set())` == `"FA"` |
| T-06 | `test_derive_book_code_collision` | `derive_book_code("financial_accounting", {"FA"})` == `"FA2"` |
| T-07 | `test_books_yaml_loads_all_16_math_books` | After loading `books.yaml`, `BOOK_REGISTRY` contains all 16 known math slugs |
| T-08 | `test_books_yaml_validates_bad_regex` | `BookConfig` raises `ValueError` for entry with invalid `section_pattern` |
| T-09 | `test_no_default_book_slug_in_config` | `hasattr(config, "DEFAULT_BOOK_SLUG")` is `False` |
| T-10 | `test_pipeline_runner_all_5_stages_called` | Mock all 5 stage functions; assert each called once in order for a mock book |
| T-11 | `test_image_retry_succeeds_on_second_attempt` | Mock HTTP 503 then 200; assert `_download_image_with_retry()` returns `True` |
| T-12 | `test_image_retry_all_fail_returns_false` | Mock HTTP 503 × 3; assert returns `False`, no exception raised |
| T-13 | `test_validate_cleans_orphan_image_rows` | Insert ChunkImage row pointing to non-existent file; assert `_validate_and_clean_images()` returns 1 and row is deleted |
| T-14 | `test_validate_keeps_valid_image_rows` | Insert ChunkImage row with existing file; assert 0 rows deleted |
| T-15 | `test_watcher_triggers_on_pdf_creation` | Simulate `FileCreatedEvent` for `.pdf`; assert `Queue.put()` called |
| T-16 | `test_watcher_ignores_non_pdf_files` | Simulate `FileCreatedEvent` for `.txt`; assert `Queue.put()` not called |
| T-17 | `test_watcher_ignores_directory_creation` | Simulate `FileCreatedEvent` with `is_directory=True`; assert ignored |
| T-18 | `test_watcher_normalises_maths_to_mathematics` | Event in `data/maths/` → subject = `"mathematics"` |
| T-19 | `test_expert_graph_loads_from_yaml_for_prealgebra` | `_get_expert_graph("prealgebra")` returns non-empty dict with `whole_numbers` key |
| T-20 | `test_expert_graph_falls_back_to_keyword_for_new_book` | `_get_expert_graph("unknown_book")` returns `None` |
| T-21 | `test_books_api_includes_subject_field` | `GET /api/v1/books` response items include `"subject"` field |
| T-22 | `test_bootstrap_skips_already_registered_books` | Run `bootstrap()` with prealgebra already in `books.yaml`; assert prealgebra not re-processed |
| T-23 | `test_append_to_books_yaml_thread_safe` | 5 threads concurrently call `append_to_books_yaml()`; assert all 5 entries written without corruption |

### Integration Tests

- Pipeline runner integration: run all 5 stages against a small synthetic PDF (2-page single-section) with a mock Mathpix client. Assert `pipeline_runs` row reaches `COMPLETED` status in DB.
- Hot-load integration: call `POST /api/admin/load-book/{slug}` after chunk builder completes; assert `GET /api/v1/books` includes the new slug in response.

### Performance Tests

- `calibrate_book()` must complete in under 10 seconds for a 600-page PDF (PyMuPDF is synchronous; test on CI with the prealgebra PDF).
- Chunk upsert throughput: 100 chunks must embed and upsert in under 60 seconds (existing baseline from prealgebra run).

---

## Key Decisions Requiring Stakeholder Input

1. **Minimum section guard before proceeding**: Should `calibrate_book()` abort the pipeline if fewer than 10 sections are detected (indicating a non-OpenStax PDF or wrong font detection)? This prevents students seeing empty or malformed content but also stops valid short books. Recommended: implement the guard with a configurable threshold constant `CALIBRATE_MIN_SECTION_COUNT = 10` in `config.py`.

2. **Watch-all-subdirectories vs explicit allow-list**: The current design watches all subdirectories of `backend/data/`. Should there be an allow-list of permitted subject directories (e.g., `["maths", "Business", "Nursing"]`) to prevent accidental processing of temporary or test files? This is a one-line config change but requires a stakeholder decision on policy.

3. **Rescan-on-startup scope**: Should the watcher rescan on startup only for slugs with no `pipeline_runs` row at all, or also for slugs with `status=FAILED`? Rescanning FAILED slugs enables automatic retry on container restart, but may repeatedly re-attempt pipelines that will always fail (e.g., Mathpix quota issues). Recommended: rescan for `NULL` rows only; leave FAILED as operator-resolved.

4. **`GET /api/v1/books` breaking change coordination**: Adding the `subject` field is backward-compatible. However, removing `DEFAULT_BOOK_SLUG` means any frontend code that calls `/api/v1/concepts/query` without a `book_slug` parameter will break. Confirm that all frontend API calls include `book_slug` explicitly before merging the backend change.
