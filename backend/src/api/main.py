"""
ADA REST API — FastAPI application.
Week 1: RAG + Graph integrated endpoints.
Week 2: Pedagogical Loop — teaching sessions with Socratic checks.
"""

import json
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
    TopologicalOrderItem,
    ConceptDetailResponse, ConceptImage,
    GraphInfoResponse, GraphNodeInfo,
)
from api.knowledge_service import KnowledgeService
from api.teaching_router import router as teaching_router
from api.teaching_service import TeachingService
import api.teaching_router as teaching_router_module
from adaptive.adaptive_router import router as adaptive_router, cards_router as adaptive_cards_router
import adaptive.adaptive_router as adaptive_router_module
from db.connection import init_db, close_db
from config import OUTPUT_DIR, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_MODEL_MINI
from api.prompts import LANGUAGE_NAMES


# ── Rate limiter (shared via rate_limiter module to avoid circular imports) ─
from api.rate_limiter import limiter

# ── Auth constants ─────────────────────────────────────────────────────
_API_KEY = os.getenv("API_SECRET_KEY", "")
_SKIP_AUTH = {"/health", "/docs", "/openapi.json", "/redoc"}


# ── Lifespan: load services once at startup ────────────────────────

knowledge_svc: KnowledgeService = None

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
            print(f"[translation-cache] Loaded {len(_title_translation_cache)} entries from disk.")
        except Exception as e:
            print(f"[translation-cache] Failed to load cache: {e}")


def _save_translation_cache() -> None:
    """Persist translation cache to disk."""
    try:
        serialisable = {f"{lang}|{cid}": title for (lang, cid), title in _title_translation_cache.items()}
        with open(_TRANSLATION_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(serialisable, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[translation-cache] Failed to save cache: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global knowledge_svc
    print("Loading KnowledgeService (ChromaDB + NetworkX)...")
    knowledge_svc = KnowledgeService(book_slug="prealgebra")
    print("Initializing PostgreSQL...")
    await init_db()
    teaching_router_module.teaching_svc = TeachingService(knowledge_svc)
    adaptive_router_module.adaptive_knowledge_svc = knowledge_svc
    adaptive_router_module.adaptive_llm_client = AsyncOpenAI(
        api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL
    )
    _load_translation_cache()
    print("Services loaded. API ready.")
    yield
    _save_translation_cache()
    await close_db()
    print("Shutting down.")


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
    allow_origins=[o.strip() for o in os.getenv("FRONTEND_URL", "http://localhost:5173").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── API-key authentication middleware ──────────────────────────────
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Reject requests missing a valid X-API-Key header, except for public paths."""
    api_key = os.getenv("API_SECRET_KEY", "")
    if (request.method == "OPTIONS"
            or request.url.path in _SKIP_AUTH
            or request.url.path.startswith("/images/")
            or not api_key):
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

# ── Static files: serve extracted images ──────────────────────────
_images_dir = OUTPUT_DIR / "prealgebra" / "images"
if _images_dir.exists():
    app.mount("/images", StaticFiles(directory=str(_images_dir)), name="images")


# ═══════════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "collection_count": knowledge_svc.collection.count() if knowledge_svc else 0,
        "graph_nodes": knowledge_svc.graph.number_of_nodes() if knowledge_svc else 0,
        "graph_edges": knowledge_svc.graph.number_of_edges() if knowledge_svc else 0,
    }


# ═══════════════════════════════════════════════════════════════════
# CONCEPTS — RAG + Graph
# ═══════════════════════════════════════════════════════════════════

@app.post("/api/v1/concepts/query", response_model=ConceptQueryResponse)
async def query_concepts(req: ConceptQuery):
    """
    THE Week 1 deliverable:
    "Get me the concept of 'Variables' knowing the child has mastered 'Integers'."

    Combines ChromaDB semantic search (RAG) with NetworkX prerequisite checking (Graph).
    """
    results = knowledge_svc.query_concept_with_prerequisites(
        query_text=req.query,
        mastered_concepts=req.mastered_concepts,
        n_results=req.n_results,
    )

    concept_results = [
        ConceptResult(
            concept_id=r["concept_id"],
            concept_title=r["concept_title"],
            chapter=r["chapter"],
            section=r["section"],
            text=r["text"],
            latex=r["latex"],
            images=[ConceptImage(**img) for img in r.get("images", [])],
            distance=r["distance"],
            prerequisites=[PrerequisiteStatus(**p) for p in r["prerequisites"]],
            all_prerequisites_met=r["all_prerequisites_met"],
            ready_to_learn=r["ready_to_learn"],
        )
        for r in results
    ]

    return ConceptQueryResponse(
        query=req.query,
        results=concept_results,
        mastered_concepts=req.mastered_concepts,
    )


@app.post("/api/v1/concepts/next", response_model=NextConceptsResponse)
async def next_concepts(req: NextConceptsRequest):
    """Given mastered concepts, return all concepts now ready to learn and locked ones."""
    ready = knowledge_svc.get_next_concepts(req.mastered_concepts)
    locked = knowledge_svc.get_locked_concepts(req.mastered_concepts)
    return NextConceptsResponse(
        mastered_concepts=req.mastered_concepts,
        ready_to_learn=ready,
        locked=locked,
    )


@app.get("/api/v1/concepts/{concept_id}", response_model=ConceptDetailResponse)
async def get_concept(concept_id: str):
    """Full detail for a single concept including prerequisites and dependents."""
    detail = knowledge_svc.get_concept_detail(concept_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Concept not found: {concept_id}")
    return ConceptDetailResponse(**detail)


@app.get("/api/v1/concepts/{concept_id}/prerequisites")
async def get_prerequisites(concept_id: str):
    """All transitive prerequisites for a concept."""
    all_prereqs = knowledge_svc.get_all_prerequisites(concept_id)
    return {
        "concept_id": concept_id,
        "prerequisites": all_prereqs,
        "count": len(all_prereqs),
    }


# ═══════════════════════════════════════════════════════════════════
# IMAGES
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/v1/concepts/{concept_id}/images")
async def get_concept_images(concept_id: str):
    """List all extracted images for a concept."""
    images = knowledge_svc.get_concept_images(concept_id)
    return {"concept_id": concept_id, "images": images, "count": len(images)}


# ═══════════════════════════════════════════════════════════════════
# GRAPH
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/v1/graph/info", response_model=GraphInfoResponse)
async def graph_info():
    """Dependency graph statistics."""
    info = knowledge_svc.get_graph_info()
    return GraphInfoResponse(
        num_nodes=info["num_nodes"],
        num_edges=info["num_edges"],
        is_dag=info["is_dag"],
        root_concepts=info["root_concepts"],
        leaf_concepts=info["leaf_concepts"],
    )


@app.get("/api/v1/graph/nodes")
async def graph_nodes():
    """List all concept nodes with graph properties."""
    nodes = knowledge_svc.get_all_nodes()
    return {"nodes": nodes, "count": len(nodes)}


@app.post("/api/v1/graph/learning-path", response_model=LearningPathResponse)
async def learning_path(req: LearningPathRequest):
    """Compute the optimal learning path to reach a target concept."""
    result = knowledge_svc.get_learning_path(req.target_concept_id, req.mastered_concepts)
    return LearningPathResponse(
        target=result["target"],
        path=[LearningPathStep(**step) for step in result["path"]],
        total_steps=result["total_steps"],
    )


@app.get("/api/v1/graph/full")
async def graph_full():
    """Full graph with nodes and edges for frontend visualization."""
    nodes = knowledge_svc.get_all_nodes()
    edges = [
        {"source": u, "target": v}
        for u, v in knowledge_svc.graph.edges()
    ]
    return {"nodes": nodes, "edges": edges}


@app.get("/api/v1/graph/topological-order")
async def topological_order():
    """Return all concepts in a valid learning sequence."""
    order = knowledge_svc.get_topological_order()
    return {"order": order, "count": len(order)}


# ═══════════════════════════════════════════════════════════════════
# CONCEPT TITLE TRANSLATION
# ═══════════════════════════════════════════════════════════════════


class TranslateTitlesRequest(BaseModel):
    titles: dict[str, str]  # { concept_id: english_title }
    language: str  # target language code


@app.post("/api/v2/concepts/translate-titles")
async def translate_concept_titles(req: TranslateTitlesRequest):
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
        client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        translation_model = OPENAI_MODEL_MINI  # mini is sufficient for mechanical JSON translation
        response = await client.chat.completions.create(
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

        for i, (cid, _) in enumerate(items):
            if i < len(translated_list):
                translated = translated_list[i]
                _title_translation_cache[(req.language, cid)] = translated
                translations[cid] = translated
            else:
                translations[cid] = untranslated[cid]  # fallback to English

        # Persist after each batch so cache survives crashes
        _save_translation_cache()

    except Exception as e:
        import traceback
        print(f"[translate-titles] ERROR: {e}")
        traceback.print_exc()
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
        port=8000,
        reload=True,
    )
