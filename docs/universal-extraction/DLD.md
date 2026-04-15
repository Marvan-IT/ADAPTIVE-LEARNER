# Detailed Low-Level Design: Universal PDF Extraction Pipeline

**Feature name:** `universal-extraction`
**Date:** 2026-04-13
**Status:** Approved for design — implementation pending

---

## 1. Component Breakdown

### 1.1 Component Map

| Component | File | Single Responsibility |
|-----------|------|-----------------------|
| `TocAnalyzer` | `extraction/toc_analyzer.py` (new) | Parse the TOC block from book.mmd; return ordered list of `TocEntry` objects |
| `HeadingCorrector` | `extraction/toc_analyzer.py` (new) | Fuzzy-match garbled body headings against TOC entries; return a correction dict |
| `BoundaryScanner` | `extraction/toc_analyzer.py` (new) | Walk the entire MMD, extract all potential boundary signals with position and frequency stats |
| `BookProfiler` | `extraction/book_profiler.py` (new) | Send TOC + boundary report + chapter samples to LLM; parse and validate `BookProfile` response |
| `ProfileCache` | `extraction/book_profiler.py` (new) | Read/write `book_profile.json`; check MMD drift and log stale-cache warnings |
| `AdaptiveChunkParser` | `extraction/chunk_parser.py` (extended) | Accept optional `BookProfile`; apply profile-driven multi-signal boundary detection when present |
| `ExerciseZoneDetector` | `extraction/chunk_parser.py` (extended) | Classify headings as exercise zones based on `ExerciseMarker.behavior` from profile |
| `FeatureBoxHandler` | `extraction/chunk_parser.py` (extended) | Recognize feature box patterns from profile; absorb them as inline body content |
| `PostProcessor` | `extraction/chunk_parser.py` (extended) | Merge tiny chunks (< `min_chunk_words`), split large chunks (> `max_chunk_words`), run coverage check |
| `ChunkBuilder` | `extraction/chunk_builder.py` (modified) | Existing embedding + persistence stage; extended to respect `chunk_type_locked` |
| `GraphBuilder` | `extraction/graph_builder.py` (modified) | Extended to handle non-`X.Y` concept ID formats via `_safe_section_sort_key()` |
| `AdminChunkRouter` | `api/admin_router.py` (modified) | PATCH endpoint writes `chunk_type_locked = True` when `chunk_type` is patched |
| `AdminReviewPage` | `frontend/src/pages/AdminReviewPage.jsx` (modified) | Type toggle control calling PATCH endpoint |
| `ExerciseCardPrompt` | `api/prompts.py` (modified) | `build_exercise_card_prompt()` for PRACTICE and GUIDED card types |

### 1.2 Inter-Component Contracts

```
pipeline.py
  └── run_chunk_pipeline(book_slug, mmd_path, profile_path, db)
        │
        ├── [Stage 1] analyze_book_structure(mmd_text) → BoundaryReport
        │     ├── TocAnalyzer.parse_toc(mmd_text) → list[TocEntry]
        │     ├── HeadingCorrector.build_corrections(toc_entries, mmd_text) → dict[str, str]
        │     └── BoundaryScanner.scan(mmd_text, corrections) → BoundaryReport
        │
        ├── [Stage 2] get_or_create_book_profile(boundary_report, mmd_text, slug, profile_path) → BookProfile
        │     ├── ProfileCache.load(profile_path, mmd_text) → BookProfile | None
        │     └── BookProfiler.profile(boundary_report, mmd_text) → BookProfile
        │           └── ProfileCache.save(profile, profile_path)
        │
        ├── [Stage 3] parse_book_mmd(mmd_path, book_slug, profile) → list[ParsedChunk]
        │     ├── AdaptiveChunkParser (profile-driven when profile is not None)
        │     ├── ExerciseZoneDetector
        │     ├── FeatureBoxHandler
        │     └── PostProcessor
        │
        └── [Stage 4] build_chunks(book_slug, chunks, db) → None  [existing]
```

---

## 2. Data Design

### 2.1 New Data Models

```python
# extraction/toc_analyzer.py

from dataclasses import dataclass, field

@dataclass
class TocEntry:
    section_id: str          # e.g. "1.1", "Chapter 2", "Unit 3 - Section 1"
    title: str               # normalized heading text from TOC
    level: int               # 1 = chapter, 2 = section, 3 = subsection
    char_offset: int         # position in MMD where TOC line was found


@dataclass
class BoundaryCandidate:
    char_offset: int         # position in MMD
    signal_type: str         # "heading_h2" | "heading_h3" | "bold_line" | "caps_line" | "numbered"
    text: str                # raw heading text (may be garbled)
    corrected_text: str      # after fuzzy TOC correction (same as text if no match)
    section_id: str          # nearest enclosing section (from TOC scan)
    body_words_after: int    # word count of text following this candidate before next candidate
    position_in_section: float  # 0.0 = top, 1.0 = bottom of section body


@dataclass
class SignalStats:
    signal_type: str
    pattern_text: str        # the exact text or regex if recurring
    occurrence_count: int
    avg_position_in_section: float   # 0.0–1.0
    example_texts: list[str] = field(default_factory=list)


@dataclass
class BoundaryReport:
    toc_entries: list[TocEntry]
    heading_corrections: dict[str, str]      # garbled_text → corrected_text
    all_candidates: list[BoundaryCandidate]
    signal_stats: list[SignalStats]          # frequency analysis per heading pattern
    chapter_sample_texts: list[str]          # 3 representative chapter bodies (first 800 words each)
    chapter_boundary_formats: list[str]      # detected raw chapter heading formats (for LLM)
```

```python
# extraction/book_profiler.py

from pydantic import BaseModel, Field
from typing import Literal


class HeadingLevel(BaseModel):
    markdown_level: int                     # 1–4 (number of # symbols)
    role: Literal["chapter", "section", "subsection", "noise", "feature_box"]
    example: str                            # one representative heading text


class SubsectionSignal(BaseModel):
    signal_type: str                        # "heading_h2", "bold_line", "caps_line", etc.
    pattern: str | None = None             # optional regex if heading text is patterned
    is_boundary: bool                       # True = creates a new chunk; False = inline content
    examples: list[str] = Field(default_factory=list)


class ExerciseMarker(BaseModel):
    pattern: str                            # regex or exact heading text
    behavior: Literal[
        "zone_section_end",     # recurring heading at end of each section body
        "zone_chapter_end",     # appears once at end of each chapter
        "inline_single",        # one-off exercise within a section, not a zone
    ]
    avg_position_in_section: float          # observed average; used to validate zone_section_end


class BookProfile(BaseModel):
    book_slug: str
    subject: str                            # "math" | "nursing" | "business" | ...
    heading_hierarchy: list[HeadingLevel]
    section_id_format: str                  # regex describing concept IDs, e.g. r"\d+\.\d+"
    chapter_boundary_patterns: list[str]    # list of regex patterns that mark chapter starts
    toc_sections: list[dict]               # raw TocEntry data for reference
    subsection_signals: list[SubsectionSignal]
    feature_box_patterns: list[str]        # regex patterns identifying feature box headings
    noise_patterns: list[str]              # headings to treat as inline content (not boundaries)
    exercise_markers: list[ExerciseMarker]
    min_chunk_words: int = 80              # merge threshold
    max_chunk_words: int = 2000            # split threshold
    max_sections_per_chapter: int = 30     # replaces hardcoded _MAX_REAL_SECTION_IN_CHAPTER = 10
    back_matter_markers: list[str] = Field(default_factory=list)
    boilerplate_patterns: list[str] = Field(default_factory=list)
    mmd_char_count: int = 0               # snapshot for stale-cache drift detection
    profiled_at: str = ""                  # ISO timestamp
    profile_version: int = 1
```

### 2.2 Database Schema Changes

#### Migration: `013_add_chunk_type_locked.py`

```sql
-- Add admin-lock column to concept_chunks
ALTER TABLE concept_chunks
    ADD COLUMN chunk_type_locked BOOLEAN NOT NULL DEFAULT FALSE;

-- Index for admin queries filtering on locked chunks
CREATE INDEX ix_concept_chunks_type_locked
    ON concept_chunks (book_slug, chunk_type_locked)
    WHERE chunk_type_locked = TRUE;
```

**ORM change in `db/models.py`:**

```python
class ConceptChunk(Base):
    # ... existing columns ...
    chunk_type_locked = Column(Boolean, nullable=False, server_default="false")
```

No other schema changes. `book_profile.json` lives on disk, not in the database.

### 2.3 File System Artifacts

```
output/{book_slug}/
├── book.mmd                    # Mathpix output (existing)
├── book_profile.json           # NEW — cached BookProfile (Stage 2 output)
├── images_downloaded/          # existing
└── graph.json                  # existing
```

`book_profile.json` format: `BookProfile.model_dump_json(indent=2)` — human-readable, hand-editable.

### 2.4 Caching Strategy

| Cache | Location | Key | Invalidation |
|-------|----------|-----|--------------|
| Book profile | `output/{slug}/book_profile.json` | book slug | Manual via `--re-profile`; warning logged on MMD drift > 5% |
| Chunk embeddings | PostgreSQL `concept_chunks.embedding` | `(book_slug, concept_id, heading)` | Existing upsert logic; unchanged |

### 2.5 Data Retention

`book_profile.json` is a pipeline artifact. It should be preserved across pipeline re-runs (same as `book.mmd`). The `_clean_output_dir()` function in `admin_router.py` must be updated to add `"book_profile.json"` to the `_preserve` set.

---

## 3. API Design

### 3.1 Modified Admin PATCH Endpoint

**`PATCH /api/admin/chunks/{chunk_id}`**

Existing endpoint, extended behavior:

```
Request body (unchanged):
{
  "chunk_type": "exercise" | "teaching" | "learning_objective" | ...,
  "is_optional": bool,
  "is_hidden": bool,
  "exam_disabled": bool,
  "heading": str,
  "text": str
}

New behavior:
  When "chunk_type" key is present in request body:
    → set chunk.chunk_type = body["chunk_type"]
    → set chunk.chunk_type_locked = True   ← NEW
  When "chunk_type" key is absent:
    → chunk_type_locked is not touched

Response (extended):
{
  "id": "...",
  "heading": "...",
  "text": "...",
  "chunk_type": "exercise",
  "chunk_type_locked": true,          ← NEW field in response
  "is_optional": false,
  "is_hidden": false,
  "exam_disabled": false,
  "order_index": 42
}
```

**Authorization:** Existing `X-API-Key` header check; no change.

### 3.2 Pipeline CLI Extension

New flags added to `pipeline.py` argument parser:

```
--profile          Run Stage 1 + 2 profiling only; do not chunk or embed.
                   Useful for previewing BookProfile before committing to a full run.

--re-profile       Ignore cached book_profile.json and re-run Stage 2 LLM profiling.
                   Useful after major book re-OCR.

--legacy           (existing) Use hardcoded parser; equivalent to profile=None.
```

Existing `--chunks` flag continues to run the full Stage 1–4 pipeline (Stage 1+2 are new additions to this path).

### 3.3 Error Handling Conventions

All new pipeline stages use the existing `logger.exception()` pattern:

| Stage | Error | Behavior |
|-------|-------|----------|
| Stage 1 TOC parse | No TOC block found | Log WARNING; set `toc_entries=[]`; continue with frequency-only analysis |
| Stage 1 fuzzy match | Match below 0.80 threshold | Skip correction; use original heading text |
| Stage 2 LLM call | JSON parse failure | Retry up to 3 times (existing `json-repair` fallback); raise `ValueError` after exhaustion |
| Stage 2 LLM call | Pydantic validation fails | Log ERROR with raw response; fall back to `legacy_profile_from_config()` for known books; raise for unknown |
| Stage 3 chunking | Zero chunks produced for a TOC section | Log WARNING with section ID; continue |
| Stage 4 embedding | OpenAI timeout | Existing retry logic in `chunk_builder.py`; unchanged |

---

## 4. Sequence Diagrams

### 4.1 Happy Path — New Book, First Run

```
pipeline.py          TocAnalyzer    BoundaryScanner  BookProfiler   ProfileCache   chunk_parser   chunk_builder
     │                    │               │               │               │               │               │
     │ read book.mmd      │               │               │               │               │               │
     │──────────────────► │               │               │               │               │               │
     │ parse_toc()        │               │               │               │               │               │
     │◄────────────────── │               │               │               │               │               │
     │                    │               │               │               │               │               │
     │ build_corrections()│               │               │               │               │               │
     │────────────────────►               │               │               │               │               │
     │                                    │               │               │               │               │
     │ scan(mmd, corrections)             │               │               │               │               │
     │───────────────────────────────────►│               │               │               │               │
     │ BoundaryReport                     │               │               │               │               │
     │◄───────────────────────────────────│               │               │               │               │
     │                                                    │               │               │               │
     │ load(profile_path, mmd_text)                       │               │               │               │
     │────────────────────────────────────────────────────►               │               │               │
     │ None (cache miss)                                  │               │               │               │
     │◄────────────────────────────────────────────────────               │               │               │
     │                                                                    │               │               │
     │ profile(boundary_report, mmd_text)                                 │               │               │
     │───────────────────────────────────────────────────────────────────►│               │               │
     │                                    ┌──────────────────────────────►│               │               │
     │                                    │ OpenAI gpt-4o call            │               │               │
     │                                    │◄──────────────────────────────│               │               │
     │                                                                    │               │               │
     │ save(profile, profile_path)        │                               │               │               │
     │────────────────────────────────────────────────────────────────────►               │               │
     │ BookProfile                                                        │               │               │
     │◄───────────────────────────────────────────────────────────────────│               │               │
     │                                                                                    │               │
     │ parse_book_mmd(mmd_path, slug, profile)                                            │               │
     │───────────────────────────────────────────────────────────────────────────────────►│               │
     │ list[ParsedChunk]                                                                  │               │
     │◄───────────────────────────────────────────────────────────────────────────────────│               │
     │                                                                                                    │
     │ build_chunks(book_slug, chunks, db)                                                                │
     │───────────────────────────────────────────────────────────────────────────────────────────────────►│
     │ Done                                                                                               │
     │◄───────────────────────────────────────────────────────────────────────────────────────────────────│
```

### 4.2 Happy Path — Re-run (Profile Cached)

```
pipeline.py          ProfileCache   chunk_parser   chunk_builder
     │                   │               │               │
     │ load(path, mmd)   │               │               │
     │──────────────────►│               │               │
     │ BookProfile (hit) │               │               │
     │◄──────────────────│               │               │
     │                                   │               │
     │ parse_book_mmd(...)               │               │
     │──────────────────────────────────►│               │
     │ list[ParsedChunk]                 │               │
     │◄──────────────────────────────────│               │
     │                                                   │
     │ build_chunks(...)                                 │
     │──────────────────────────────────────────────────►│
     │ (locked chunks skipped for type override)         │
     │◄──────────────────────────────────────────────────│
```

### 4.3 Admin Type Override Flow

```
Admin UI             AdminReviewPage     admin_router.py     PostgreSQL
     │                    │                    │                  │
     │ click type toggle  │                    │                  │
     │──────────────────► │                    │                  │
     │                    │ PATCH /chunks/{id} │                  │
     │                    │ {chunk_type: "exercise"}              │
     │                    │──────────────────► │                  │
     │                    │                    │ UPDATE chunk     │
     │                    │                    │ SET chunk_type="exercise",
     │                    │                    │     chunk_type_locked=TRUE
     │                    │                    │──────────────────►│
     │                    │                    │ 200 OK           │
     │                    │                    │◄──────────────────│
     │                    │ {chunk_type_locked: true}             │
     │                    │◄────────────────── │                  │
     │ lock icon shown    │                    │                  │
     │◄────────────────── │                    │                  │
```

### 4.4 Error Path — LLM Profiling Failure

```
pipeline.py          BookProfiler    OpenAI API
     │                   │               │
     │ profile(report)   │               │
     │──────────────────►│               │
     │                   │ POST /chat/completions
     │                   │──────────────►│
     │                   │ 500 error     │
     │                   │◄──────────────│
     │                   │ sleep(2s), retry attempt 2
     │                   │──────────────►│
     │                   │ 500 error     │
     │                   │◄──────────────│
     │                   │ sleep(4s), retry attempt 3
     │                   │──────────────►│
     │                   │ 500 error     │
     │                   │◄──────────────│
     │                   │ raise ValueError("LLM profiling failed after 3 attempts")
     │                   │◄
     │ catch ValueError  │
     │ known book → legacy_profile_from_config()
     │ unknown book → re-raise, pipeline aborts with clear error message
```

---

## 5. Integration Design

### 5.1 Stage 1 → Stage 2: BoundaryReport → BookProfile

The `BoundaryReport` is a pure Python dataclass — no serialization required. It is passed directly as an argument. The LLM prompt is constructed from:
- `report.toc_entries` — the ground-truth section list
- `report.signal_stats` — heading signal frequencies and positions
- `report.chapter_sample_texts` — three chapter bodies (first 800 words each) for LLM context
- `report.chapter_boundary_formats` — raw chapter heading texts observed

### 5.2 LLM Prompt Contract (Stage 2)

```
System:
  You are a textbook structure analyst. Analyze the provided table of contents,
  heading statistics, and chapter samples for a PDF textbook converted to Markdown.
  Return a JSON object matching the BookProfile schema exactly.
  
  Rules:
  - "is_boundary: true" signals create new chunks; "is_boundary: false" signals are inline content.
  - Feature boxes are recurring headings with fixed titles that appear mid-section (position < 0.80).
  - Exercise markers are recurring headings with avg_position_in_section > 0.80.
  - Set min_chunk_words to 80 and max_chunk_words to 2000 unless book structure requires otherwise.
  - Do not invent signals not present in the statistics.
  
  JSON schema:
  {BookProfile schema as JSON Schema string}

User:
  Table of Contents ({N} sections):
  {toc_entries formatted as numbered list}
  
  Heading Signal Statistics:
  {signal_stats formatted as table: signal_type | pattern | occurrences | avg_position}
  
  Chapter boundary formats observed:
  {chapter_boundary_formats as list}
  
  Chapter sample 1 (first 800 words):
  {chapter_sample_texts[0]}
  
  Chapter sample 2:
  {chapter_sample_texts[1]}
  
  Chapter sample 3:
  {chapter_sample_texts[2]}
```

**Model:** `gpt-4o` (OPENAI_MODEL from config)
**Max tokens:** 2000 (profile JSON is bounded)
**Timeout:** 30s
**Retries:** 3 with exponential back-off (matching existing LLM retry pattern)

### 5.3 Stage 3: BookProfile → chunk_parser.py Integration

`parse_book_mmd()` signature change (fully backward compatible):

```python
def parse_book_mmd(
    mmd_path: Path,
    book_slug: str,
    profile: BookProfile | None = None,   # NEW — defaults to None (legacy path)
) -> list[ParsedChunk]:
```

When `profile` is not `None`:
- Chapter boundary detection uses `profile.chapter_boundary_patterns` instead of `_CHAPTER_HEADING`
- `_MAX_REAL_SECTION_IN_CHAPTER` is replaced by `profile.max_sections_per_chapter`
- `_NOISE_HEADING_PATTERNS` is replaced by compiled regexes from `profile.noise_patterns`
- `_EXERCISE_ZONE_PATTERN` is replaced by `profile.exercise_markers` with position-based detection
- Feature box headings matching `profile.feature_box_patterns` are absorbed as inline body content
- Subsection boundaries are determined by `profile.subsection_signals` (multi-signal, not just `##`)

When `profile` is `None`: all existing code paths run unchanged.

### 5.4 Stage 4: chunk_type_locked Respect

`chunk_builder.py` `save_chunk()` modified:

```python
if existing is not None:
    # Existing lock check — NEW
    if existing.chunk_type_locked:
        logger.debug(
            "Chunk type locked by admin, skipping type update: %s / %s (locked as %s)",
            chunk.concept_id, chunk.heading, existing.chunk_type,
        )
    else:
        existing.chunk_type = chunk.chunk_type
    # All other fields updated as before (text, order_index, etc.)
```

### 5.5 Exercise Card Integration with Teaching Engine

`teaching_service.py` currently filters out exercise chunks at line 638 (approximately):

```python
# BEFORE (remove this filter):
chunks = [c for c in chunks if c.chunk_type == "teaching"]

# AFTER:
chunks = [c for c in chunks if c.chunk_type in ("teaching", "exercise", "learning_objective")]
```

Exercise chunks use a new prompt function in `prompts.py`:

```python
def build_exercise_card_prompt(
    chunk_text: str,
    chunk_heading: str,
    concept_title: str,
    card_type: Literal["PRACTICE", "GUIDED"],
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for an exercise card."""
```

Card type mapping:
- `PRACTICE` — student attempts the exercise independently (MCQ or short answer)
- `GUIDED` — step-by-step hints provided without revealing the full answer

---

## 6. Security Design

### 6.1 Authentication and Authorization

No new endpoints. All admin operations continue to use the existing `X-API-Key` header check via `_check_api_key()` in `admin_router.py`. The `chunk_type_locked` field is only writable via authenticated admin endpoints.

### 6.2 Encryption

No change. `book_profile.json` is a pipeline artifact on the server filesystem; it contains no PII or secrets. The LLM call uses the existing `OPENAI_API_KEY` from the environment.

### 6.3 Input Validation

**Stage 1 — MMD input:**
- `mmd_text` is read from a local file; no external input
- Fuzzy correction threshold ≥ 0.80 prevents false substitutions
- All regex patterns compiled at import time; malformed patterns raise at startup

**Stage 2 — LLM output:**
- `BookProfile` is validated via Pydantic before use; invalid LLM JSON is rejected and retried
- `profile_version` field guards against loading profiles from incompatible schema versions

**Stage 3+4 — Chunk text:**
- All existing sanitization in `_clean_chunk_text()` applies unchanged
- Feature box content absorbed as-is (same sanitization as all other body content)

**Admin PATCH:**
- `chunk_type` value must be one of the allowed types; the existing `_allowed` set controls which fields are writable
- `chunk_type_locked` is only set by the server-side logic, never accepted from the request body

### 6.4 Secrets Management

No new secrets. `OPENAI_API_KEY` already in `backend/.env`. No new environment variables required.

---

## 7. Observability Design

### 7.1 Logging

All new modules use `logger = logging.getLogger(__name__)`. No `print()` calls.

| Log Level | Event |
|-----------|-------|
| INFO | Stage 1 start/end + candidate counts |
| INFO | Stage 2 cache hit/miss; LLM call start/end |
| INFO | Stage 3 profile applied: `book_slug=%s, min_chunk=%d, max_chunk=%d, signals=%d` |
| WARNING | No TOC block found; using frequency analysis only |
| WARNING | MMD drift > 5% with stale profile (> 7 days old) |
| WARNING | TOC section produced zero chunks (coverage gap) |
| WARNING | Fuzzy match below threshold — heading kept uncorrected |
| DEBUG | Every boundary decision: `signal_type=%s heading=%r position=%.2f classified_as=%s` |
| ERROR | LLM profiling failed all retries |

### 7.2 Metrics

No new metrics infrastructure required (no server process). The following are logged as INFO after each stage for operator visibility:

- Stage 1: `signal_candidates={N}, toc_entries={N}, corrections_applied={N}`
- Stage 2: `profile_source=cache|llm, profile_version={V}`
- Stage 3: `raw_chunks={N}, after_dedup={N}, after_merge_split={N}, coverage_gaps={N}`
- Stage 4: unchanged existing metrics

### 7.3 Alerting

Operators should monitor pipeline logs for:
- `WARNING.*coverage_gap` — section silently dropped; may indicate profile needs hand-tuning
- `ERROR.*LLM profiling failed` — manual intervention required; use `--legacy` flag as fallback
- `WARNING.*MMD drift` — consider running `--re-profile`

---

## 8. Error Handling and Resilience

### 8.1 Stage 1 Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|----------|
| TOC block absent | `toc_entries == []` after parse | Log WARNING; `heading_corrections = {}`; continue with raw signals |
| All headings garbled beyond fuzzy threshold | `corrections == {}` | Log WARNING; proceed with uncorrected text; exercise detection may be inaccurate |
| No boundary candidates found | `all_candidates == []` | Log ERROR; fallback to `profile=None` (legacy parser) |

### 8.2 Stage 2 Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|----------|
| LLM returns invalid JSON | `json.JSONDecodeError` | `json-repair` fallback; retry up to 3 times |
| Pydantic validation error | `ValidationError` | Log ERROR with raw JSON; for known books use `legacy_profile_from_config()`; for unknown books abort |
| LLM timeout | `asyncio.TimeoutError` | Retry with exponential back-off; abort after 3 attempts |
| Profile schema version mismatch | `profile.profile_version != CURRENT_VERSION` | Log WARNING; treat as cache miss; re-profile |

### 8.3 Stage 3 Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Regex pattern in profile fails to compile | `re.error` at startup | Log ERROR per pattern; skip that pattern (degrade gracefully) |
| Zero chunks produced for entire book | `len(chunks) == 0` | Raise `RuntimeError`; do not write to DB |
| Post-processor split produces empty halves | `len(half.split()) == 0` | Keep original chunk unsplit; log WARNING |

### 8.4 Retry Policy

All LLM calls follow the existing project pattern:

```python
for attempt in range(3):
    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=2000,
            timeout=30.0,
        )
        raw_json = response.choices[0].message.content
        profile = BookProfile.model_validate_json(raw_json)
        return profile
    except Exception as exc:
        logger.warning("LLM profiling attempt %d failed: %s", attempt + 1, exc)
        if attempt < 2:
            await asyncio.sleep(2 ** (attempt + 1))
raise ValueError("LLM profiling failed after 3 attempts")
```

---

## 9. Testing Strategy

### 9.1 Unit Tests (`backend/tests/test_universal_extraction.py`)

All Stage 1 and Stage 3 functions are pure (no I/O) and can be tested without mocks.

| Test ID | Function | Assertion |
|---------|----------|-----------|
| U-01 | `TocAnalyzer.parse_toc()` | Parses 5-entry TOC from fixture MMD; returns correct `TocEntry` list |
| U-02 | `HeadingCorrector.build_corrections()` | "The Mothated Leernes" corrects to "The Motivated Learner" (≥ 0.80 similarity) |
| U-03 | `HeadingCorrector.build_corrections()` | "EXAMPLE 1.1" is not corrected (no TOC match ≥ 0.80) |
| U-04 | `BoundaryScanner.scan()` | Returns `BoundaryCandidate` with correct `position_in_section` for heading at 80% of section body |
| U-05 | `SignalStats` aggregation | "PATIENT CONVERSATIONS" with avg_position=0.42 classified as feature box candidate |
| U-06 | `SignalStats` aggregation | "Review Questions" with avg_position=0.91 classified as exercise zone candidate |
| U-07 | `parse_book_mmd(..., profile=None)` | Prealgebra book produces same chunk count as before (within ±3%) — regression test |
| U-08 | `parse_book_mmd(..., profile=nursing_profile)` | Nursing book produces 0 coverage gaps for chapters 1–3 (validated against manual ground truth) |
| U-09 | Feature box absorption | "PATIENT CONVERSATIONS" heading does not create a new chunk; its text appears in parent chunk body |
| U-10 | Exercise zone detection | "Review Questions" at position 0.88 classified as `exercise`; "Clinical Reasoning" at 0.45 classified as `teaching` |
| U-11 | Merge post-processor | Chunk with 45 words merged into next sibling; resulting chunk has combined word count |
| U-12 | Split post-processor | Chunk with 2400 words split at paragraph boundary into two chunks; neither chunk < `min_chunk_words` |
| U-13 | `legacy_profile_from_config()` | Converts prealgebra `books.yaml` entry to valid `BookProfile` with matching exercise markers |
| U-14 | `chunk_type_locked` in save_chunk | Existing chunk with `chunk_type_locked=True` retains its `chunk_type` after pipeline re-run |

### 9.2 Integration Tests

| Test ID | Scope | Assertion |
|---------|-------|-----------|
| I-01 | Stage 1 on real nursing MMD fixture (first 50 pages) | ≥ 5 chapter boundaries detected; `heading_corrections` non-empty |
| I-02 | Stage 2 with mock LLM client | `BookProfile` returned matches expected JSON schema; profiled_at timestamp set |
| I-03 | Full Stage 1–3 pipeline on nursing fixture (no DB) | Chunk count in expected range 200–600; zero chunks with `heading == ""` |
| I-04 | Admin PATCH sets chunk_type_locked | After PATCH, DB row has `chunk_type_locked = True`; subsequent pipeline run leaves type unchanged |
| I-05 | Exercise cards not filtered out | After removing filter in `teaching_service.py`, exercise chunks appear in session chunk list |

### 9.3 Regression Tests (Existing Books)

The `--chunks` pipeline run on all 16 existing books must produce chunk counts within ±3% of pre-feature baseline. Baselines captured before implementing this feature and stored in `backend/tests/fixtures/chunk_baselines.json`.

```json
{
  "prealgebra": {"expected": 478, "tolerance": 0.03},
  "elementary_algebra": {"expected": 391, "tolerance": 0.03},
  ...
}
```

### 9.4 Performance Tests

Stage 1 (BoundaryScanner) must complete in ≤ 30 seconds on a 1000-page book MMD (approx. 5MB). Run with `time python -m extraction.toc_analyzer --book clinical_nursing_skills` and assert wall clock < 30s.

### 9.5 Manual Validation Checklist (Clinical Nursing Skills)

Before merging:
- [ ] All chapter boundaries detected (manually verify against TOC)
- [ ] PATIENT CONVERSATIONS (55 instances) — zero appear as top-level chunks
- [ ] REAL RN STORIES (45 instances) — zero appear as top-level chunks
- [ ] Review Questions sections — all classified as `exercise`
- [ ] Competency-Based Assessments sections — all classified as `exercise`
- [ ] No teaching chunk has < 80 words (post-merge step validation)
- [ ] Coverage: zero WARNING log lines for coverage gaps in chapters 1–5
