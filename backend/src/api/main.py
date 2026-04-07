"""
ADA REST API — FastAPI application.
Week 1: RAG + Graph integrated endpoints.
Week 2: Pedagogical Loop — teaching sessions with Socratic checks.
"""

import asyncio
import json
import logging
import os
import secrets
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Ensure src is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.schemas import (
    ConceptQuery, ConceptQueryResponse, ConceptResult, PrerequisiteStatus,
    NextConceptsRequest, NextConceptsResponse,
    LearningPathRequest, LearningPathResponse, LearningPathStep,
    ConceptDetailResponse, GraphInfoResponse,
)
from api.chunk_knowledge_service import ChunkKnowledgeService
from api.teaching_router import router as teaching_router
from api.teaching_service import TeachingService
import api.teaching_router as teaching_router_module
from adaptive.adaptive_router import router as adaptive_router, cards_router as adaptive_cards_router
import adaptive.adaptive_router as adaptive_router_module
from db.connection import init_db, close_db
from config import OUTPUT_DIR, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL_MINI, validate_required_env_vars, DEFAULT_BOOK_SLUG
from api.prompts import LANGUAGE_NAMES


logger = logging.getLogger(__name__)

# ── Rate limiter (shared via rate_limiter module to avoid circular imports) ─
from api.rate_limiter import limiter  # noqa: E402

# ── Auth constants ─────────────────────────────────────────────────────
_API_KEY = os.getenv("API_SECRET_KEY", "")
_SKIP_AUTH = {"/health", "/docs", "/openapi.json", "/redoc"}


# ── Lifespan: load services once at startup ────────────────────────

_chunk_knowledge_svc: ChunkKnowledgeService = None  # chunk-based service (PostgreSQL + graph)
_openai_client: AsyncOpenAI = None
_cache_write_lock: asyncio.Lock | None = None

# Persistent translation cache: { (language, concept_id): translated_title }
_title_translation_cache: dict[tuple[str, str], str] = {}
_TRANSLATION_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "translation_cache.json"


def _load_translation_cache() -> None:
    """Load translation cache from disk if it exists."""
    global _title_translation_cache
    if _TRANSLATION_CACHE_FILE.exists():
        try:
            with open(_TRANSLATION_CACHE_FILE, "r", encoding="utf-8") as f:
                raw: dict = json.load(f)
            # Keys stored as "lang|concept_id" strings
            _title_translation_cache = {
                tuple(k.split("|", 1)): v for k, v in raw.items()
            }
            logger.info("[translation-cache] Loaded %d entries from disk.", len(_title_translation_cache))
        except Exception as e:
            logger.error("[translation-cache] Failed to load cache: %s", e)


def _save_translation_cache() -> None:
    """Persist translation cache to disk."""
    try:
        serialisable = {f"{lang}|{cid}": title for (lang, cid), title in _title_translation_cache.items()}
        with open(_TRANSLATION_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(serialisable, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("[translation-cache] Failed to save cache: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_required_env_vars()
    global _chunk_knowledge_svc, _openai_client, _cache_write_lock
    _cache_write_lock = asyncio.Lock()
    logger.info("Initializing PostgreSQL...")
    await init_db()
    # Chunk-based knowledge service (PostgreSQL + graph.json — no ChromaDB)
    _chunk_knowledge_svc = ChunkKnowledgeService()
    try:
        _chunk_knowledge_svc.preload_graph(DEFAULT_BOOK_SLUG)
        logger.info("Graph preloaded for book: %s", DEFAULT_BOOK_SLUG)
    except Exception:
        logger.exception("Failed to preload graph for %s — graph endpoints will error on demand.", DEFAULT_BOOK_SLUG)
    app.state.chunk_knowledge_svc = _chunk_knowledge_svc
    teaching_router_module.teaching_svc = TeachingService()
    teaching_router_module.chunk_ksvc = _chunk_knowledge_svc
    adaptive_router_module.adaptive_chunk_ksvc = _chunk_knowledge_svc
    adaptive_router_module.adaptive_llm_client = AsyncOpenAI(
        api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL
    )
    _openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    _load_translation_cache()
    # Mount per-book output directories so frontend can resolve /images/{book_slug}/...
    # DB image URLs are like: http://localhost:8889/images/prealgebra/images_downloaded/{hash}.jpg
    for _bslug in [DEFAULT_BOOK_SLUG]:
        _book_out_dir = OUTPUT_DIR / _bslug
        if _book_out_dir.exists():
            try:
                app.mount(
                    f"/images/{_bslug}",
                    StaticFiles(directory=str(_book_out_dir)),
                    name=f"images_{_bslug}",
                )
                logger.info("Mounted /images/%s → %s", _bslug, _book_out_dir)
            except Exception:
                logger.exception("Failed to mount image dir for %s", _bslug)
    logger.info("Services loaded. API ready.")
    yield
    _save_translation_cache()
    await close_db()
    logger.info("Shutting down.")


app = FastAPI(
    title="ADA - Adaptive Math Learning API",
    description="Hybrid RAG + Graph engine for adaptive math tutoring",
    version="1.0.0",
    lifespan=lifespan,
)

# Wire slowapi into the app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("FRONTEND_URL", "http://localhost:5173").split(",") if o.strip()],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)


# ── API-key authentication middleware ──────────────────────────────
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Reject requests missing a valid X-API-Key header, except for public paths."""
    from config import ENVIRONMENT
    api_key = os.getenv("API_SECRET_KEY", "")
    if (request.method == "OPTIONS"
            or request.url.path in _SKIP_AUTH
            or request.url.path.startswith("/images/")
            or request.url.path.startswith("/static/")):
        return await call_next(request)
    if not api_key:
        if ENVIRONMENT == "production":
            return JSONResponse(
                {"detail": "Server misconfigured: API_SECRET_KEY not set"},
                status_code=503,
            )
        # dev/test — allow through without key
        return await call_next(request)
    provided = request.headers.get("X-API-Key", "")
    if not secrets.compare_digest(provided, api_key):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


# ── Week 2: Teaching router ──────────────────────────────────────
app.include_router(teaching_router)

# ── Week 3: Adaptive Learning Engine router ───────────────────────
app.include_router(adaptive_router)
app.include_router(adaptive_cards_router)

# Serve whole-PDF extracted images (Mathpix /v3/pdf output)
# Mounted at /static/output/{book_slug}/mathpix_extracted/{filename}
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static/output", StaticFiles(directory=str(OUTPUT_DIR)), name="static_output")


# ═══════════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    from db.connection import get_db
    chunk_count = 0
    graph_nodes = 0
    graph_edges = 0
    try:
        async for _db in get_db():
            chunk_count = await _chunk_knowledge_svc.get_chunk_count(_db) if _chunk_knowledge_svc else 0
            break
    except Exception as exc:
        logger.warning("[health] chunk_count query failed: %s", exc)
    try:
        if _chunk_knowledge_svc:
            graph_info = _chunk_knowledge_svc.get_graph_info(DEFAULT_BOOK_SLUG)
            graph_nodes = graph_info["num_nodes"]
            graph_edges = graph_info["num_edges"]
    except Exception as exc:
        logger.warning("[health] graph_info failed: %s", exc)
    return {
        "status": "ok",
        "chunk_count": chunk_count,
        "graph_nodes": graph_nodes,
        "graph_edges": graph_edges,
    }


# ═══════════════════════════════════════════════════════════════════
# CONCEPTS — RAG + Graph
# ═══════════════════════════════════════════════════════════════════

@app.post("/api/v1/concepts/query", response_model=ConceptQueryResponse)
@limiter.limit("60/minute")
async def query_concepts(request: Request, req: ConceptQuery, book_slug: str = DEFAULT_BOOK_SLUG):
    """
    Semantic search using pgvector similarity.
    Combines PostgreSQL vector search (RAG) with NetworkX prerequisite checking (Graph).
    """
    from db.connection import get_db as _get_db
    # Generate embedding for the query
    try:
        embed_response = await _openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=req.query,
        )
        query_embedding = embed_response.data[0].embedding
    except Exception as exc:
        logger.error("[query_concepts] embedding generation failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to generate query embedding")

    mastered_set = set(req.mastered_concepts or [])
    async for _db in _get_db():
        raw_results = await _chunk_knowledge_svc.query_similar_chunks(
            _db, book_slug, query_embedding, n=req.n_results
        )
        break

    concept_results = []
    for r in raw_results:
        prereqs = r.get("prerequisites", [])
        all_met = all(p in mastered_set for p in prereqs)
        prereq_statuses = [
            PrerequisiteStatus(
                concept_id=p,
                concept_title=p,
                mastered=p in mastered_set,
            )
            for p in prereqs
        ]
        concept_results.append(ConceptResult(
            concept_id=r["concept_id"],
            concept_title=r.get("section", r["concept_id"]),
            chapter=r["concept_id"].split("_")[-1].split(".")[0] if "_" in r["concept_id"] else "",
            section=r["concept_id"].split("_")[-1] if "_" in r["concept_id"] else r["concept_id"],
            text=r["text"],
            latex=[],
            images=[],
            distance=1.0 - r.get("score", 0.0),
            prerequisites=prereq_statuses,
            all_prerequisites_met=all_met,
            ready_to_learn=all_met,
        ))

    return ConceptQueryResponse(
        query=req.query,
        results=concept_results,
        mastered_concepts=req.mastered_concepts,
    )


@app.post("/api/v1/concepts/next", response_model=NextConceptsResponse)
@limiter.limit("60/minute")
async def next_concepts(request: Request, req: NextConceptsRequest, book_slug: str = DEFAULT_BOOK_SLUG):
    """Given mastered concepts, return all concepts now ready to learn and locked ones."""
    ready = _chunk_knowledge_svc.get_next_concepts(book_slug, req.mastered_concepts)
    locked = _chunk_knowledge_svc.get_locked_concepts(book_slug, req.mastered_concepts)
    return NextConceptsResponse(
        mastered_concepts=req.mastered_concepts,
        ready_to_learn=ready,
        locked=locked,
    )


@app.get("/api/v1/concepts/{concept_id}", response_model=ConceptDetailResponse)
async def get_concept(concept_id: str, book_slug: str = DEFAULT_BOOK_SLUG):
    """Full detail for a single concept including prerequisites and dependents."""
    from db.connection import get_db as _get_db
    async for _db in _get_db():
        detail = await _chunk_knowledge_svc.get_concept_detail(_db, concept_id, book_slug)
        break
    if not detail:
        raise HTTPException(status_code=404, detail=f"Concept not found: {concept_id}")
    return ConceptDetailResponse(**detail)


@app.get("/api/v1/concepts/{concept_id}/prerequisites")
async def get_prerequisites(concept_id: str, book_slug: str = DEFAULT_BOOK_SLUG):
    """All transitive prerequisites for a concept."""
    all_prereqs = _chunk_knowledge_svc.get_all_prerequisites(book_slug, concept_id)
    return {
        "concept_id": concept_id,
        "prerequisites": all_prereqs,
        "count": len(all_prereqs),
    }


# ═══════════════════════════════════════════════════════════════════
# IMAGES
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/v1/concepts/{concept_id}/images")
async def get_concept_images(concept_id: str, book_slug: str = DEFAULT_BOOK_SLUG):
    """List all extracted images for a concept."""
    from db.connection import get_db as _get_db
    async for _db in _get_db():
        detail = await _chunk_knowledge_svc.get_concept_detail(_db, concept_id, book_slug)
        break
    images = detail.get("images", []) if detail else []
    return {"concept_id": concept_id, "images": images, "count": len(images)}


# ═══════════════════════════════════════════════════════════════════
# GRAPH
# ═══════════════════════════════════════════════════════════════════

def _require_book(book_slug: str) -> None:
    """Raise 404 if graph.json does not exist for the given book_slug."""
    graph_path = OUTPUT_DIR / book_slug / "graph.json"
    if not graph_path.exists():
        raise HTTPException(status_code=404, detail=f"Book '{book_slug}' not found or not yet processed")


@app.get("/api/v1/graph/info", response_model=GraphInfoResponse)
async def graph_info(book_slug: str = DEFAULT_BOOK_SLUG):
    """Dependency graph statistics."""
    _require_book(book_slug)
    info = _chunk_knowledge_svc.get_graph_info(book_slug)
    return GraphInfoResponse(
        num_nodes=info["num_nodes"],
        num_edges=info["num_edges"],
        is_dag=info["is_dag"],
        root_concepts=info["root_concepts"],
        leaf_concepts=info["leaf_concepts"],
    )


@app.get("/api/v1/graph/nodes")
async def graph_nodes(book_slug: str = DEFAULT_BOOK_SLUG):
    """List all concept nodes with graph properties."""
    _require_book(book_slug)
    nodes = _chunk_knowledge_svc.get_all_nodes(book_slug)
    return {"nodes": nodes, "count": len(nodes)}


@app.post("/api/v1/graph/learning-path", response_model=LearningPathResponse)
@limiter.limit("60/minute")
async def learning_path(request: Request, req: LearningPathRequest, book_slug: str = DEFAULT_BOOK_SLUG):
    """Compute the optimal learning path to reach a target concept."""
    _require_book(book_slug)
    result = _chunk_knowledge_svc.get_learning_path(book_slug, req.target_concept_id, req.mastered_concepts)
    return LearningPathResponse(
        target=result["target"],
        path=[LearningPathStep(**step) for step in result["path"]],
        total_steps=result["total_steps"],
    )


@app.get("/api/v1/graph/full")
async def graph_full(book_slug: str = DEFAULT_BOOK_SLUG):
    """Full graph with nodes and edges for frontend visualization."""
    _require_book(book_slug)
    nodes = _chunk_knowledge_svc.get_all_nodes(book_slug)
    edges = _chunk_knowledge_svc.get_all_edges(book_slug)
    return {"nodes": nodes, "edges": edges}


@app.get("/api/v1/graph/topological-order")
async def topological_order(book_slug: str = DEFAULT_BOOK_SLUG):
    """Return all concepts in a valid learning sequence."""
    _require_book(book_slug)
    order = _chunk_knowledge_svc.get_topological_order(book_slug)
    return {"order": order, "count": len(order)}


@app.get("/api/v1/books")
async def list_books_v1():
    from config import BOOK_REGISTRY
    from db.connection import get_db as _get_db
    _slug_to_title = {cfg["book_slug"]: cfg.get("title", cfg["book_slug"]) for cfg in BOOK_REGISTRY.values()}
    all_slugs = sorted(_slug_to_title.keys())
    active_books: set[str] = set()
    try:
        async for _db in _get_db():
            active_books = await _chunk_knowledge_svc.get_active_books(_db)
            break
    except Exception as exc:
        logger.warning("[list_books_v1] get_active_books failed: %s", exc)
    return [
        {
            "slug": s,
            "title": _slug_to_title.get(s, s),
            "processed": s in active_books,
        }
        for s in all_slugs
    ]


# ═══════════════════════════════════════════════════════════════════
# CONCEPT TITLE TRANSLATION
# ═══════════════════════════════════════════════════════════════════


class TranslateTitlesRequest(BaseModel):
    titles: dict[str, str]  # { concept_id: english_title }
    language: str  # target language code


@app.post("/api/v2/concepts/translate-titles")
@limiter.limit("20/minute")
async def translate_concept_titles(request: Request, req: TranslateTitlesRequest):
    """Translate concept titles in batch using LLM, with in-memory caching."""
    if not req.titles or req.language == "en":
        return {"translations": req.titles}

    lang_name = LANGUAGE_NAMES.get(req.language, req.language)

    # Check cache for already-translated titles
    translations = {}
    untranslated = {}
    for cid, title in req.titles.items():
        cached = _title_translation_cache.get((req.language, cid))
        if cached:
            translations[cid] = cached
        else:
            untranslated[cid] = title

    # If all cached, return immediately
    if not untranslated:
        return {"translations": translations}

    # Build a numbered list for the LLM
    items = list(untranslated.items())
    numbered = "\n".join(f"{i+1}. {title}" for i, (_, title) in enumerate(items))

    try:
        translation_model = OPENAI_MODEL_MINI  # mini is sufficient for mechanical JSON translation
        response = await _openai_client.chat.completions.create(
            model=translation_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Translate the following math concept titles to {lang_name}. "
                        "These are educational math topic names for children. "
                        "Return ONLY a JSON object with key 'titles' containing a list "
                        "of translations in the same order. No extra text. Example: "
                        '{"titles": ["translated1", "translated2"]}'
                    ),
                },
                {"role": "user", "content": numbered},
            ],
            temperature=0.3,
            max_tokens=1000,
            timeout=20.0,
        )

        if not response.choices:
            raise ValueError("LLM returned empty response for translation")
        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            raise ValueError("LLM returned empty response")
        # Extract JSON from response (handle markdown code blocks)
        if "```" in raw:
            import re as _re
            m = _re.search(r"```(?:json)?\s*(.*?)```", raw, _re.DOTALL)
            if m:
                raw = m.group(1).strip()
        result = json.loads(raw)
        translated_list = result.get("titles", [])

        async with _cache_write_lock:
            for i, (cid, _) in enumerate(items):
                if i < len(translated_list):
                    translated = translated_list[i]
                    _title_translation_cache[(req.language, cid)] = translated
                    translations[cid] = translated
                else:
                    translations[cid] = untranslated[cid]  # fallback to English
        # Persist after each batch so cache survives crashes — run blocking I/O off event loop
        await asyncio.get_event_loop().run_in_executor(None, _save_translation_cache)

    except Exception as e:
        logger.error("[translate-titles] ERROR: %s", e, exc_info=True)
        # On error, return English titles as fallback
        for cid, title in untranslated.items():
            translations[cid] = title

    return {"translations": translations}


# ── Run with uvicorn ───────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8889,
        reload=True,
    )
