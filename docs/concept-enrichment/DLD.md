# Detailed Low-Level Design — Concept Enrichment

**Feature slug:** `concept-enrichment`
**Date authored:** 2026-02-26
**Author:** Solution Architect

---

## 1. Component Breakdown

### 1.1 `chroma_store.py` — LaTeX Metadata Storage (modified)

**Single responsibility:** Upsert concept blocks into ChromaDB with complete metadata including serialised LaTeX expressions.

**Change:** In `store_concept_blocks()`, replace:
```python
"latex_count": len(block.latex),
```
with:
```python
"latex_count": len(block.latex),
"latex_expressions": json.dumps(block.latex, ensure_ascii=False),
```

**Interface contract (unchanged):**
```python
def store_concept_blocks(
    collection: chromadb.Collection,
    concept_blocks: list[ConceptBlock],
    dependency_edges: Optional[list[DependencyEdge]] = None,
    batch_size: int = 50,
) -> int: ...
```

**Import addition:** `import json` — already present in surrounding modules but must be added to `chroma_store.py` if not already there (verify at implementation time).

---

### 1.2 `knowledge_service.py` — LaTeX and Image Enrichment Read Path (modified)

**Single responsibility:** Provide enriched concept data to the API layer by fusing ChromaDB, NetworkX, LaTeX expressions, and annotated image metadata.

**Changes:**

1. `_get_latex(concept_id)` — extend to prefer ChromaDB metadata over `_latex_map` fallback:

```python
def _get_latex(self, concept_id: str) -> list[str]:
    """
    Get LaTeX expressions for a concept.
    Prefers ChromaDB metadata (latex_expressions field).
    Falls back to _latex_map loaded from concept_blocks.json.
    """
    # Primary: try ChromaDB metadata
    try:
        result = self.collection.get(ids=[concept_id], include=["metadatas"])
        if result and result["metadatas"]:
            raw = result["metadatas"][0].get("latex_expressions")
            if raw:
                return json.loads(raw)
    except Exception:
        pass
    # Fallback: in-memory map from concept_blocks.json
    return self._latex_map.get(concept_id, [])
```

NOTE: `get_concept_detail()` already calls `self.collection.get()` for the concept; implementation should reuse that result rather than making a second ChromaDB call. See Section 4 (Sequence Diagrams) for the merged flow.

2. `get_concept_images(concept_id)` — extend returned dict to include `description` and `relevance`:

```python
def get_concept_images(self, concept_id: str) -> list[dict]:
    """Get image metadata with URLs and vision annotations for a concept."""
    raw_images = self._image_map.get(concept_id, [])
    return [
        {
            "filename": img["filename"],
            "url": f"/images/{self.book_slug}/{img['filename']}",
            "width": img["width"],
            "height": img["height"],
            "image_type": img["image_type"],
            "page": img["page"],
            "description": img.get("description"),   # None if not annotated
            "relevance": img.get("relevance"),        # None if not annotated
        }
        for img in raw_images
    ]
```

NOTE: The current implementation hardcodes `"/images/{concept_id}/{img['filename']}"` without the book slug in the path. The corrected URL must include the book slug to align with the static files mount which may need to be parameterized per-book. This is addressed in Section 7 (Static Files Configuration).

---

### 1.3 `vision_annotator.py` — New Module

**Location:** `backend/src/images/vision_annotator.py`

**Single responsibility:** Accept image bytes and contextual metadata, call GPT-4o Vision, and return a structured annotation dict. Manage a disk-based JSON cache keyed by image content hash.

**Full module specification:**

```python
"""
Vision Annotator — generates semantic descriptions for extracted math images
using GPT-4o Vision. Results are cached to disk by MD5(image_bytes).

Only processes FORMULA and DIAGRAM image types. DECORATIVE images are
returned immediately with null fields without any API call.
"""

import base64
import hashlib
import json
import logging
from pathlib import Path

from openai import AsyncOpenAI

from config import OPENAI_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an expert mathematics educator analysing images extracted from "
    "OpenStax mathematics textbooks. Your task is to describe the mathematical "
    "content of the image and explain its pedagogical purpose so that a "
    "teaching AI can reference it accurately when tutoring a student.\n\n"
    "Respond ONLY with a JSON object in this exact format — no markdown, no "
    "code blocks, no extra text:\n"
    '{"description": "<concise description of what the image shows>", '
    '"relevance": "<one sentence explaining why this image matters for understanding the concept>"}'
)

def _user_prompt(concept_title: str, image_type: str) -> str:
    return (
        f"This image was extracted from a section titled '{concept_title}'. "
        f"It has been classified as a {image_type} image. "
        "Describe its mathematical content and pedagogical relevance."
    )

SKIP_RESULT = {"description": None, "relevance": None}
ERROR_RESULT = {"description": None, "relevance": None}


async def annotate_image(
    image_bytes: bytes,
    concept_title: str,
    image_type: str,
    llm_client: AsyncOpenAI,
    model: str = OPENAI_MODEL,
    cache_dir: Path | None = None,
) -> dict:
    """
    Annotate a single image using GPT-4o Vision.

    Args:
        image_bytes:   Raw binary image data.
        concept_title: Title of the concept this image belongs to.
        image_type:    "FORMULA" or "DIAGRAM" (DECORATIVE is skipped).
        llm_client:    Shared AsyncOpenAI client instance.
        model:         OpenAI model to use (defaults to OPENAI_MODEL from config).
        cache_dir:     Directory for caching annotation results. If None,
                       caching is disabled.

    Returns:
        {"description": str | None, "relevance": str | None}
        Returns None values without API call for DECORATIVE images.
        Returns None values on API or parse error (logged as WARNING).
    """
    if image_type not in ("FORMULA", "DIAGRAM"):
        logger.debug("Skipping annotation for %s image type", image_type)
        return SKIP_RESULT

    # ── Cache lookup ──────────────────────────────────────────────
    md5_hash = hashlib.md5(image_bytes).hexdigest()
    cache_path: Path | None = None

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"vision_{md5_hash}.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                logger.debug("Cache hit for image hash %s", md5_hash)
                return cached
            except Exception as exc:
                logger.warning("Cache read failed for %s: %s", cache_path, exc)

    # ── API call ──────────────────────────────────────────────────
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    # Determine MIME type from magic bytes
    mime = "image/png"
    if image_bytes[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif image_bytes[:4] == b"GIF8":
        mime = "image/gif"

    try:
        response = await llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{b64}",
                                "detail": "high",
                            },
                        },
                        {
                            "type": "text",
                            "text": _user_prompt(concept_title, image_type),
                        },
                    ],
                },
            ],
            temperature=0.2,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning(
            "Vision API call failed for image hash %s (concept: %s): %s",
            md5_hash, concept_title, exc,
        )
        return ERROR_RESULT

    # ── Parse response ────────────────────────────────────────────
    raw = (response.choices[0].message.content or "").strip()
    try:
        result = json.loads(raw)
        annotation = {
            "description": result.get("description") or None,
            "relevance": result.get("relevance") or None,
        }
    except json.JSONDecodeError as exc:
        logger.warning(
            "Vision response parse failed for image hash %s: %s — raw: %r",
            md5_hash, exc, raw[:200],
        )
        return ERROR_RESULT

    # ── Write cache ───────────────────────────────────────────────
    if cache_path is not None:
        try:
            cache_path.write_text(
                json.dumps(annotation, ensure_ascii=False), encoding="utf-8"
            )
            logger.debug("Cached annotation for image hash %s", md5_hash)
        except Exception as exc:
            logger.warning("Cache write failed for %s: %s", cache_path, exc)

    logger.info(
        "Annotated %s image for concept '%s': %s",
        image_type, concept_title, annotation["description"],
    )
    return annotation
```

---

### 1.4 `extract_images.py` — Annotation Integration (modified)

**Single responsibility:** Extract FORMULA and DIAGRAM images from PDF, save to disk, call vision annotator for each, and write an enriched `image_index.json`.

**Signature change:** The function becomes async to allow `await annotate_image()`:

```python
async def extract_and_save_images(
    book_slug: str = "prealgebra",
    annotate: bool = True,
) -> dict:
```

The `annotate` parameter allows callers to skip annotation (e.g., tests, quick re-runs).

**Additions within the extraction loop:**

```python
# After: output_path.write_bytes(image_bytes)

annotation = {"description": None, "relevance": None}
if annotate:
    # Build concept title from page_to_concept mapping
    concept_meta = _get_concept_meta(concept_blocks, concept_id)
    annotation = await annotate_image(
        image_bytes=image_bytes,
        concept_title=concept_meta.get("concept_title", concept_id),
        image_type=image_type,
        llm_client=llm_client,
        model=OPENAI_MODEL,
        cache_dir=book_output_dir / "vision_cache",
    )
    await asyncio.sleep(VISION_RATE_LIMIT)

image_index[concept_id].append({
    "filename": filename,
    "xref": xref,
    "width": width,
    "height": height,
    "image_type": image_type,
    "page": page_num,
    "description": annotation["description"],
    "relevance": annotation["relevance"],
})
```

The `llm_client` is instantiated once at the top of `extract_and_save_images()`:

```python
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, VISION_RATE_LIMIT

llm_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
```

A new helper:

```python
def _get_concept_meta(concept_blocks: list[dict], concept_id: str) -> dict:
    """Return concept metadata dict for a given concept_id, or empty dict."""
    for block in concept_blocks:
        if block.get("concept_id") == concept_id:
            return block
    return {}
```

**Entry point:** Because `extract_and_save_images()` becomes async, the `__main__` block must use `asyncio.run()`:

```python
if __name__ == "__main__":
    import asyncio
    parser = argparse.ArgumentParser(description="Extract and annotate images from PDF")
    parser.add_argument("--book", default="prealgebra", help="Book slug")
    parser.add_argument("--no-annotate", action="store_true", help="Skip vision annotation")
    args = parser.parse_args()
    asyncio.run(extract_and_save_images(args.book, annotate=not args.no_annotate))
```

---

### 1.5 `schemas.py` — ConceptImage Extension (modified)

**Change:** Add optional `description` and `relevance` fields to `ConceptImage`:

```python
class ConceptImage(BaseModel):
    """An extracted image associated with a concept."""
    filename: str
    url: str
    width: int
    height: int
    image_type: str   # "FORMULA" or "DIAGRAM"
    page: int
    description: str | None = None   # Vision annotation: what the image shows
    relevance: str | None = None     # Vision annotation: pedagogical purpose
```

This is a backward-compatible change. Existing `ConceptImage` instantiation in `main.py` passes `**img` dicts; the new fields will default to `None` when absent.

---

### 1.6 `main.py` — Static Files Mount (review / minor fix)

**Current state (lines 116–118):**
```python
_images_dir = OUTPUT_DIR / "prealgebra" / "images"
if _images_dir.exists():
    app.mount("/images", StaticFiles(directory=str(_images_dir)), name="images")
```

**Issue:** `get_concept_images()` in `knowledge_service.py` currently constructs URLs as `/images/{concept_id}/{filename}` without the book slug. The static mount points to `output/prealgebra/images/` which contains subdirectories named by `concept_id`. This is correct for the single-book case — the URL `/images/{concept_id}/{filename}` maps correctly to the mounted directory.

**No code change required** to `main.py` for the single-book case. Document as known limitation for multi-book support.

The `get_concept_images()` URL must match this mount structure. See the corrected URL in Section 1.2.

---

### 1.7 `LearningPage.jsx` + `CardLearningView` — Image Caption Rendering (modified)

The `LearningPage.jsx` itself delegates image rendering to child components. The image rendering most likely occurs in `CardLearningView`. The design change is at the component level that renders `ConceptImage` objects.

**Required change in whichever component renders concept images:**

```jsx
// Before (conceptual pseudocode of current render):
<img src={image.url} alt={image.image_type} />

// After:
<figure className="my-4">
  <img
    src={image.url}
    alt={image.relevance ?? image.image_type}
    className="max-w-full rounded-lg mx-auto block"
  />
  {image.description && (
    <figcaption className="text-sm text-center text-[var(--color-text-muted)] mt-2 italic">
      {image.description}
    </figcaption>
  )}
</figure>
```

The `relevance` string is used as the `alt` attribute, providing accessible text that describes the pedagogical significance. The `description` is rendered as a visible caption. Both are guarded by null checks.

All user-visible strings must use `useTranslation()` where applicable — the image `description` and `relevance` are data values from the API, not UI labels, so they are exempt from i18n wrapping.

---

## 2. Data Design

### 2.1 ChromaDB Metadata Schema

**Before (per concept document):**
```json
{
  "book_slug": "prealgebra",
  "book": "Prealgebra 2e",
  "chapter": "1",
  "section": "1.1",
  "concept_title": "Introduction to Whole Numbers",
  "word_count": 412,
  "source_pages_start": 17,
  "source_pages_end": 24,
  "latex_count": 14,
  "prerequisites": "PREALG.C1.S0.PREFACE",
  "dependents": "PREALG.C1.S2.ADD_WHOLE_NUMBERS",
  "prerequisite_count": 1
}
```

**After (additive — existing fields unchanged):**
```json
{
  "book_slug": "prealgebra",
  "book": "Prealgebra 2e",
  "chapter": "1",
  "section": "1.1",
  "concept_title": "Introduction to Whole Numbers",
  "word_count": 412,
  "source_pages_start": 17,
  "source_pages_end": 24,
  "latex_count": 14,
  "latex_expressions": "[\"x + y = z\", \"\\\\frac{a}{b}\"]",
  "prerequisites": "PREALG.C1.S0.PREFACE",
  "dependents": "PREALG.C1.S2.ADD_WHOLE_NUMBERS",
  "prerequisite_count": 1
}
```

`latex_expressions` is a JSON-serialised string. ChromaDB metadata value type: `str`.
Maximum expected value length: ~8 KB for concept blocks with many formulas.

### 2.2 `image_index.json` Schema

**Location:** `backend/output/{book_slug}/image_index.json`

**Before:**
```json
{
  "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS": [
    {
      "filename": "15593.png",
      "xref": 15593,
      "width": 300,
      "height": 80,
      "image_type": "FORMULA",
      "page": 18
    }
  ]
}
```

**After (new fields are additive; null when annotation failed or was skipped):**
```json
{
  "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS": [
    {
      "filename": "15593.png",
      "xref": 15593,
      "width": 300,
      "height": 80,
      "image_type": "FORMULA",
      "page": 18,
      "description": "A horizontal number line showing integers from 0 to 10 with tick marks at each integer.",
      "relevance": "Provides a visual anchor for understanding the ordering of whole numbers on a number line."
    }
  ]
}
```

Null example (annotation failed):
```json
{
  "description": null,
  "relevance": null
}
```

### 2.3 Vision Cache File Schema

**Location:** `backend/output/{book_slug}/vision_cache/vision_{md5}.json`

```json
{
  "description": "A horizontal number line showing integers from 0 to 10...",
  "relevance": "Provides a visual anchor for understanding..."
}
```

Cache files are standalone — one JSON file per unique image (by content hash). They are never read by the API layer directly; they are consulted only during pipeline runs.

### 2.4 API Response Schema (enriched)

`GET /api/v1/concepts/{concept_id}` — `ConceptDetailResponse`:

```json
{
  "concept_id": "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS",
  "concept_title": "Introduction to Whole Numbers",
  "chapter": "1",
  "section": "1.1",
  "text": "A whole number is a number that is...",
  "latex": [
    "x + y = z",
    "\\frac{a}{b}"
  ],
  "images": [
    {
      "filename": "15593.png",
      "url": "/images/PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS/15593.png",
      "width": 300,
      "height": 80,
      "image_type": "FORMULA",
      "page": 18,
      "description": "A horizontal number line showing integers from 0 to 10 with tick marks at each integer.",
      "relevance": "Provides a visual anchor for understanding the ordering of whole numbers on a number line."
    }
  ],
  "prerequisites": ["PREALG.C1.S0.PREFACE"],
  "dependents": ["PREALG.C1.S2.ADD_WHOLE_NUMBERS"]
}
```

### 2.5 Caching Strategy

| Layer | Mechanism | Key | Invalidation |
|---|---|---|---|
| Vision annotation | Disk JSON file | MD5(image_bytes) | Manual delete of `vision_cache/` dir or `--force-reannotate` flag |
| LaTeX in ChromaDB | Persisted in vector store | concept_id (ChromaDB document ID) | Re-running `store_concept_blocks()` (upsert) |
| `_latex_map` | In-memory dict in `KnowledgeService` | concept_id | API restart; reloaded from `concept_blocks.json` |
| `_image_map` | In-memory dict in `KnowledgeService` | concept_id | API restart; reloaded from `image_index.json` |
| Translation titles | `translation_cache.json` on disk | `(language, concept_id)` | Pre-existing mechanism, unchanged |

### 2.6 Data Retention and Archival

- `vision_cache/` — pipeline artifact, excluded from git (already covered by `.gitignore` pattern for `backend/output/`). Retained indefinitely; re-generation is the only invalidation mechanism.
- `image_index.json` — pipeline artifact, excluded from git. Versioned implicitly by pipeline re-runs.
- No changes to PostgreSQL schema. No Alembic migration required.

---

## 3. API Design

### 3.1 Existing Endpoint — Enriched In Place

**`GET /api/v1/concepts/{concept_id}`**

No URL, method, or authentication change. Response schema gains two optional fields per image.

| Field | Change |
|---|---|
| `latex` | Now populated from ChromaDB `latex_expressions` (previously relied on `_latex_map` fallback) |
| `images[].description` | NEW — `str | null` |
| `images[].relevance` | NEW — `str | null` |

**Request:** unchanged
**Status codes:** unchanged (200, 404)
**Auth:** none (unchanged, public API within CORS policy)

### 3.2 Versioning Strategy

The enrichment adds fields to an existing response — this is a non-breaking additive change under the current `v1` prefix. No version bump is required. Frontend must tolerate `null` values for `description` and `relevance` (see Section 1.7).

### 3.3 Static Files Endpoint

**`GET /images/{concept_id}/{filename}`**

Served by FastAPI `StaticFiles` mount — already configured in `main.py`. No code change.

**Example:** `GET /images/PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS/15593.png`

**Response:** Binary image data (PNG/JPEG/GIF) with appropriate `Content-Type` header. FastAPI `StaticFiles` handles this automatically.

### 3.4 Error Handling Conventions

- Missing `concept_id` in ChromaDB: 404 with `{"detail": "Concept not found: {id}"}` — unchanged.
- `latex_expressions` parse failure in `_get_latex()`: silently falls back to `_latex_map`; logs WARNING.
- `image_index.json` entry missing `description`: returns `null` for that field; no error.

---

## 4. Sequence Diagrams

### 4.1 Pipeline Run — LaTeX Storage (happy path)

```
pipeline.py
    │
    ├── concept_builder → ConceptBlock(latex=["expr1", "expr2", ...])
    │
    └── chroma_store.store_concept_blocks(collection, concept_blocks)
            │
            ├── For each block:
            │   metadata["latex_count"]       = len(block.latex)        # existing
            │   metadata["latex_expressions"] = json.dumps(block.latex) # NEW
            │
            └── collection.upsert(ids, documents, metadatas)
                    └── ChromaDB persists to disk
```

### 4.2 Pipeline Run — Image Extraction + Annotation (happy path)

```
extract_images.extract_and_save_images(book_slug, annotate=True)
    │
    ├── Load mathpix_plan.json   → target_images (FORMULA + DIAGRAM only)
    ├── Load concept_blocks.json → page_to_concept map
    ├── Instantiate AsyncOpenAI client
    │
    └── For each target_image:
            │
            ├── doc.extract_image(xref) → image_bytes
            ├── output_path.write_bytes(image_bytes)
            │
            ├── vision_annotator.annotate_image(
            │       image_bytes, concept_title, image_type,
            │       llm_client, model, cache_dir
            │   )
            │       │
            │       ├── [Cache miss] → OpenAI Vision API call
            │       │       └── Returns {"description": "...", "relevance": "..."}
            │       │
            │       ├── [Cache hit] → Return cached dict immediately
            │       │
            │       └── [API error] → Log WARNING, return {"description": None, "relevance": None}
            │
            ├── asyncio.sleep(VISION_RATE_LIMIT)
            │
            └── image_index[concept_id].append({..., "description": ..., "relevance": ...})
    │
    └── json.dump(image_index, index_path)
```

### 4.3 Runtime — `GET /api/v1/concepts/{concept_id}` (happy path)

```
Client → GET /api/v1/concepts/PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS
    │
    └── main.py: get_concept()
            │
            └── knowledge_svc.get_concept_detail(concept_id)
                    │
                    ├── self.collection.get(ids=[concept_id])
                    │       └── ChromaDB returns document + metadata
                    │               (includes latex_expressions JSON string)
                    │
                    ├── json.loads(metadata["latex_expressions"])
                    │       └── Returns list[str]
                    │       └── [Fallback if absent] self._latex_map.get(concept_id, [])
                    │
                    ├── self.get_concept_images(concept_id)
                    │       └── self._image_map.get(concept_id, [])
                    │               (includes description, relevance from enriched image_index.json)
                    │
                    └── Returns ConceptDetailResponse(
                            latex=[...],
                            images=[ConceptImage(description=..., relevance=...), ...]
                        )
    │
    └── 200 OK — JSON response
```

### 4.4 Edge Case — Vision Annotation Failure

```
extract_and_save_images()
    │
    └── annotate_image(image_bytes, ...)
            │
            ├── [OpenAI timeout or 429 rate limit]
            │       └── except Exception → logger.warning(...)
            │               └── return {"description": None, "relevance": None}
            │
            └── image_index entry written with description=null, relevance=null
                    → pipeline continues; next image processed
```

### 4.5 Edge Case — Backward Compatibility for Pre-Enrichment Collections

```
KnowledgeService._get_latex(concept_id)
    │
    ├── self.collection.get(ids=[concept_id], include=["metadatas"])
    │       └── metadata["latex_expressions"] → KeyError or empty string (old collection)
    │
    └── [Fallback] self._latex_map.get(concept_id, [])
            └── Loaded from concept_blocks.json at startup
            └── Returns list[str] (may be empty if concept_blocks.json absent)
```

---

## 5. Integration Design

### 5.1 OpenAI Vision API Integration

**Protocol:** HTTPS REST — handled by `openai` Python SDK (`AsyncOpenAI`)

**Request format:**
```python
await llm_client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:{mime};base64,{b64}", "detail": "high"}},
            {"type": "text", "text": _user_prompt(concept_title, image_type)},
        ]},
    ],
    temperature=0.2,
    max_tokens=300,
    response_format={"type": "json_object"},
)
```

**Authentication:** `OPENAI_API_KEY` from environment via `config.py`.

**Retry logic:** No automatic retry in `annotate_image()`. The pipeline is offline and long-running; on transient errors the image is written with null annotation and the operator re-runs with cache already populated for successful images.

**Circuit breaker:** Not implemented at the module level. If the API is fully down, all annotations return null and the pipeline completes. Operator monitors the log for WARNING counts.

**Rate limiting:** `await asyncio.sleep(VISION_RATE_LIMIT)` called by `extract_and_save_images()` after each annotate call. The constant `VISION_RATE_LIMIT` is defined in `config.py` (see Section 6).

### 5.2 ChromaDB Integration

ChromaDB is accessed synchronously (the `chromadb` library's `PersistentClient` is not async). The existing `chroma_store.py` uses the synchronous client; this is unchanged. `KnowledgeService.__init__` loads ChromaDB synchronously at startup.

### 5.3 Internal Service Communication

All changes are within the backend monolith. No inter-service calls introduced.

---

## 6. Security Design

### 6.1 Authentication and Authorization

No change. The enriched `GET /api/v1/concepts/{concept_id}` endpoint remains unauthenticated within the existing CORS policy.

### 6.2 Data Encryption

- Image bytes are transmitted to OpenAI over HTTPS (TLS 1.2+) by the `openai` SDK.
- No student PII is included in vision annotation requests — only image bytes and the concept title (a textbook section heading).
- Vision cache files are stored on the local filesystem. No encryption at rest is implemented (consistent with existing pipeline artifacts).

### 6.3 Input Validation and Sanitisation

- `image_type` parameter in `annotate_image()` is validated against the allowlist `("FORMULA", "DIAGRAM")` before any API call.
- `concept_title` is a trusted internal value from `concept_blocks.json` — no user input.
- `latex_expressions` read from ChromaDB is parsed with `json.loads()` inside a try/except — malformed JSON falls back silently.

### 6.4 Secrets Management

- `OPENAI_API_KEY` sourced from `backend/.env` via `config.py` `os.getenv()`. Never hardcoded.
- No new secrets introduced.

---

## 7. Observability Design

### 7.1 Logging Strategy

All logging uses Python `logging` module. No `print()` calls in production paths.

| Event | Level | Message Format |
|---|---|---|
| Image type skipped (DECORATIVE) | DEBUG | `"Skipping annotation for %s image type"` |
| Cache hit | DEBUG | `"Cache hit for image hash %s"` |
| Successful annotation | INFO | `"Annotated %s image for concept '%s': %s"` |
| Cache write failure | WARNING | `"Cache write failed for %s: %s"` |
| Vision API call failure | WARNING | `"Vision API call failed for image hash %s (concept: %s): %s"` |
| JSON parse failure | WARNING | `"Vision response parse failed for image hash %s: %s — raw: %r"` |
| LaTeX metadata size warning | WARNING | `"latex_expressions for concept %s is %d bytes — approaching metadata limit"` (threshold: 8192 bytes) |
| Annotation run summary | INFO | `"Annotation complete: %d annotated, %d cache hits, %d skipped, %d errors"` |

Logger name: `images.vision_annotator` (mirrors module path `backend/src/images/vision_annotator.py`).

### 7.2 Metrics

No new runtime metrics. The pipeline is offline — progress is observable through log output.

API-level metrics (response time for `GET /api/v1/concepts/{concept_id}`) are unchanged and are expected to remain under 200 ms since all enrichment is precomputed.

### 7.3 Alerting

Not applicable for the pipeline enrichment path. For runtime API health, the existing `/health` endpoint provides collection count and graph node count — unchanged.

### 7.4 Distributed Tracing

Not applicable. The pipeline is a local synchronous process. The API is a single FastAPI instance without distributed tracing infrastructure.

---

## 8. Error Handling and Resilience

### 8.1 Vision Annotation Failures

- **Timeout / HTTP error:** Caught by `except Exception` around `await llm_client.chat.completions.create()`. Returns `ERROR_RESULT = {"description": None, "relevance": None}`. WARNING logged. Pipeline continues.
- **JSON parse error:** `json.loads(raw)` inside `except json.JSONDecodeError`. Returns `ERROR_RESULT`. WARNING logged.
- **Empty response:** `response.choices[0].message.content or ""` guard — empty string triggers the JSON parse failure branch.

### 8.2 LaTeX Metadata Recovery

- **Missing `latex_expressions` field:** `metadata.get("latex_expressions")` returns `None`. Falls through to `_latex_map` fallback.
- **Malformed JSON in `latex_expressions`:** `json.loads()` inside `except Exception`. Falls through to `_latex_map` fallback.
- **`_latex_map` absent (no `concept_blocks.json`):** Returns `[]`. No exception raised; the concept is served without LaTeX.

### 8.3 Graceful Degradation

The system degrades gracefully across all enrichment failure modes:

| Failure | Degraded behaviour |
|---|---|
| Vision API unavailable during pipeline | Images served without captions; core teaching unaffected |
| `latex_expressions` absent in old ChromaDB | LaTeX loaded from `concept_blocks.json` fallback |
| `image_index.json` absent | Images list returned as `[]`; no crash |
| `description` / `relevance` null in response | Frontend renders image without caption (conditional render guard) |

### 8.4 Retry Policies

- No retry at the `annotate_image()` level. The pipeline is operator-driven; re-running the pipeline re-processes only images without cache entries.
- A future enhancement could add exponential backoff with `tenacity` for transient 429/5xx errors, but this is out of scope for the current feature.

---

## 9. Testing Strategy

### 9.1 Unit Tests

**File:** `backend/tests/test_vision_annotator.py`

| Test name | What it verifies |
|---|---|
| `test_annotate_image_decorative_returns_null_fields` | DECORATIVE type returns `{"description": None, "relevance": None}` without any API call |
| `test_annotate_image_cache_hit_skips_api_call` | Second call with same image bytes hits cache; `llm_client.chat.completions.create` not called |
| `test_annotate_image_cache_miss_calls_api_and_writes_cache` | Cache miss triggers API call; result written to `vision_{md5}.json` |
| `test_annotate_image_api_error_returns_null_fields` | API raises exception; returns `ERROR_RESULT`; does not raise |
| `test_annotate_image_malformed_json_returns_null_fields` | API returns non-JSON; returns `ERROR_RESULT`; does not raise |
| `test_annotate_image_no_cache_dir_does_not_write_file` | `cache_dir=None`; result returned correctly; no file written |

Mock strategy: `unittest.mock.AsyncMock` for `llm_client.chat.completions.create`. Temporary directory (`tmp_path` pytest fixture) for cache files.

**File:** `backend/tests/test_chroma_store.py`

| Test name | What it verifies |
|---|---|
| `test_store_concept_blocks_persists_latex_expressions` | After upsert, ChromaDB metadata contains `latex_expressions` as valid JSON string |
| `test_store_concept_blocks_latex_expressions_round_trips` | `json.loads(metadata["latex_expressions"])` equals original `block.latex` list |
| `test_store_concept_blocks_empty_latex_stores_empty_array` | Block with `latex=[]` stores `"[]"` string, not absent field |

Mock strategy: In-memory ChromaDB client (`chromadb.Client()`) — no disk I/O.

**File:** `backend/tests/test_knowledge_service.py`

| Test name | What it verifies |
|---|---|
| `test_get_latex_prefers_chromadb_metadata` | When `latex_expressions` present in ChromaDB, `_get_latex()` returns parsed list |
| `test_get_latex_falls_back_to_latex_map` | When `latex_expressions` absent, `_get_latex()` returns `_latex_map` entry |
| `test_get_concept_images_includes_description_and_relevance` | Images from enriched `image_index.json` include `description` and `relevance` in output |
| `test_get_concept_images_handles_missing_annotation_fields` | Images from old `image_index.json` (no `description`/`relevance`) return `None` for those fields |

### 9.2 Integration Tests

**File:** `backend/tests/test_concept_enrichment_integration.py`

| Test name | What it verifies |
|---|---|
| `test_concept_detail_endpoint_returns_latex_list` | `GET /api/v1/concepts/{id}` returns `"latex": [...]` as a list, not null |
| `test_concept_detail_endpoint_returns_annotated_images` | `GET /api/v1/concepts/{id}` returns `images[].description` and `images[].relevance` when `image_index.json` contains annotations |
| `test_concept_detail_endpoint_tolerates_null_annotations` | `GET /api/v1/concepts/{id}` returns `images[].description: null` without HTTP error when annotation absent |

Mock strategy: FastAPI `TestClient`. ChromaDB seeded with a test collection containing one concept with `latex_expressions` in metadata. `image_index.json` written to a temp directory.

### 9.3 End-to-End Tests

Manual pipeline test (not automated in CI for the initial phase due to PDF/API key requirements):

1. Run `python -m images.extract_images --book prealgebra` on a sample PDF.
2. Verify `image_index.json` contains `description` and `relevance` for at least one image.
3. Verify `vision_cache/vision_{md5}.json` files created.
4. Start the API. Call `GET /api/v1/concepts/{concept_id}` for a concept with images.
5. Verify response `images[0].description` is a non-empty string.

### 9.4 Performance Tests

- `GET /api/v1/concepts/{concept_id}` must respond in under 200 ms for a concept with 5 images. Test with `pytest-benchmark` or manual `curl` timing. Expected: no measurable change from baseline since enrichment is read-only from pre-loaded in-memory dicts.

### 9.5 Contract Tests

`ConceptImage` Pydantic schema enforces the contract between backend and frontend. The schema test `test_concept_image_schema_accepts_null_description_and_relevance` verifies that instantiating `ConceptImage` without `description` or `relevance` does not raise a validation error.

---

## Key Decisions Requiring Stakeholder Input

1. **`_get_latex()` double ChromaDB call:** `get_concept_detail()` already calls `self.collection.get()` for the full concept document. `_get_latex()` currently would make a second `collection.get()` call if implemented naively. The implementation must extract `latex_expressions` from the metadata dict already retrieved in `get_concept_detail()` and pass it to a private helper rather than calling `_get_latex()` separately. Confirm this optimization is acceptable (it changes the call chain slightly from what is described in the feature brief).

2. **`extract_and_save_images()` async signature change:** Making this function `async` is required to `await` the vision annotator. The existing `pipeline.py` entry point must call it with `asyncio.run()` or `await` it in an async context. Confirm that `pipeline.py` callers can accommodate this change without breaking the synchronous pipeline entry point.

3. **`VISION_RATE_LIMIT` constant:** A new constant `VISION_RATE_LIMIT` (suggested default: `0.5`) must be added to `config.py`. Confirm this value is appropriate for the OpenAI account's vision API rate limits (typically 500 RPM for GPT-4o tier 1 — 0.5 s interval gives 120 RPM which is conservative).

4. **Image URL path with book slug:** The current `get_concept_images()` returns URLs of the form `/images/{concept_id}/{filename}`. The static mount points to `output/prealgebra/images/`. For multi-book support, URLs must include the book slug and the mount must be book-aware. Confirm whether this is in scope now or tracked as follow-on debt.
