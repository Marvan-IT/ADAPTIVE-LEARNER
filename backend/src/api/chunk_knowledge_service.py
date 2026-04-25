"""
ChunkKnowledgeService — replaces KnowledgeService (ChromaDB) with pgvector SQL queries.

Provides chunk retrieval from PostgreSQL concept_chunks and chunk_images tables.
No initialization needed — queries DB on demand via AsyncSession.
"""

import asyncio
import json
import logging
import re
import threading
from uuid import UUID

import networkx as nx
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ConceptChunk, ChunkImage
from config import OUTPUT_DIR

logger = logging.getLogger(__name__)


_SAFE_IMAGE_URL_RE = re.compile(r"^/images/[a-zA-Z0-9_\-./() ]+$")


def _normalize_image_url(url: str) -> str:
    if not url:
        return url
    idx = url.find("/images/")
    normalized = url[idx:] if idx > 0 else url
    # Reject path traversal attempts
    if ".." in normalized:
        logger.warning("Rejected path traversal in image URL: %s", url)
        return ""
    # Reject URLs that don't match the expected /images/... pattern
    if not _SAFE_IMAGE_URL_RE.match(normalized):
        logger.warning("Rejected invalid image URL pattern: %s", url)
        return ""
    return normalized


_graph_cache: dict[str, nx.DiGraph] = {}
_graph_lock = threading.Lock()         # guards sync _load_graph / preload_graph (thread-pool)
_graph_async_lock = asyncio.Lock()     # guards reload_graph_with_overrides (event-loop)


def _load_graph(book_slug: str) -> nx.DiGraph:
    """Load graph.json as NetworkX DiGraph, cache module-level with thread safety."""
    with _graph_lock:
        if book_slug not in _graph_cache:
            path = OUTPUT_DIR / book_slug / "graph.json"
            if not path.exists():
                raise FileNotFoundError(
                    f"[chunk-ksvc] graph.json not found for '{book_slug}': {path}. "
                    f"Run: python -m src.extraction.graph_builder --book {book_slug}"
                )
            data = json.loads(path.read_text(encoding="utf-8"))
            G = nx.DiGraph()
            for node in data["nodes"]:
                G.add_node(node["id"], title=node.get("title", ""))
            for edge in data["edges"]:
                G.add_edge(edge["source"], edge["target"])
            _graph_cache[book_slug] = G
        return _graph_cache[book_slug]


def invalidate_graph_cache(book_slug: str) -> None:
    """Remove a book's graph from the in-memory cache."""
    _graph_cache.pop(book_slug, None)


def _apply_overrides(G: nx.DiGraph, overrides: list) -> nx.DiGraph:
    """Apply admin graph overrides (add/remove edges) to a copy of the graph."""
    G_copy = G.copy()
    for ov in overrides:
        if ov.action == "add_edge":
            # Only add if both nodes exist in graph
            if G_copy.has_node(ov.source_concept) and G_copy.has_node(ov.target_concept):
                G_copy.add_edge(ov.source_concept, ov.target_concept)
        elif ov.action == "remove_edge":
            if G_copy.has_edge(ov.source_concept, ov.target_concept):
                G_copy.remove_edge(ov.source_concept, ov.target_concept)
    return G_copy


async def reload_graph_with_overrides(book_slug: str, db) -> nx.DiGraph:
    """Reload graph from disk, apply admin overrides from DB, update cache.

    Called after admin adds/removes prerequisite overrides.
    """
    # Lazy import to avoid circular deps
    from db.models import AdminGraphOverride

    # Load base graph from disk (bypass cache)
    path = OUTPUT_DIR / book_slug / "graph.json"
    if not path.exists():
        raise FileNotFoundError(f"graph.json not found for '{book_slug}'")

    data = json.loads(path.read_text(encoding="utf-8"))
    G = nx.DiGraph()
    for node in data["nodes"]:
        G.add_node(node["id"], title=node.get("title", ""))
    for edge in data["edges"]:
        G.add_edge(edge["source"], edge["target"])

    # Fetch overrides from DB
    result = await db.execute(
        select(AdminGraphOverride).where(AdminGraphOverride.book_slug == book_slug)
    )
    overrides = result.scalars().all()

    # Apply overrides
    if overrides:
        G = _apply_overrides(G, overrides)

    # Atomically update cache (async lock so we don't block the event loop)
    async with _graph_async_lock:
        _graph_cache[book_slug] = G

    logger.info("[chunk-ksvc] Graph reloaded with %d overrides for '%s'", len(overrides), book_slug)
    return G


class ChunkKnowledgeService:
    """Provides chunk retrieval from PostgreSQL. No initialization needed — queries DB on demand."""

    async def get_chunks_for_concept(
        self, db: AsyncSession, book_slug: str, concept_id: str,
        include_hidden: bool = False,
        lang: str = "en",
    ) -> list[dict]:
        """Return all chunks for a concept in order_index order.

        If *lang* is not 'en', heading and image captions are resolved from
        their respective JSONB translation columns, falling back to English.
        """
        from api.dependencies import resolve_translation
        query = (
            select(ConceptChunk)
            .where(ConceptChunk.book_slug == book_slug, ConceptChunk.concept_id == concept_id)
            .order_by(ConceptChunk.order_index)
        )
        if not include_hidden:
            query = query.where(ConceptChunk.is_hidden == False)  # noqa: E712
        result = await db.execute(query)
        chunks = result.scalars().all()
        all_chunks = [self._chunk_to_dict(c) for c in chunks]
        # Exclude chunks with no real content — heading-only stubs (e.g. "SECTION 1.1 EXERCISES",
        # "Practice Makes Perfect (Exercises)") are extracted with < 100 chars of text and cannot
        # generate meaningful cards. This rule applies to all books and all sections.
        all_chunks = [c for c in all_chunks if len((c.get("text") or "").strip()) >= 100]

        if lang != "en":
            # Overlay translated headings and image captions from the source ORM objects.
            chunk_orm_map: dict[str, ConceptChunk] = {str(c.id): c for c in chunks}
            for chunk_dict in all_chunks:
                orm = chunk_orm_map.get(chunk_dict["id"])
                if orm is None:
                    continue
                chunk_dict["heading"] = resolve_translation(
                    orm.heading, orm.heading_translations or {}, lang
                )
                for img in chunk_dict.get("images", []):
                    # Images are dicts with 'caption' key; caption may be None.
                    if img.get("caption") is None:
                        continue
                    # Find the matching ChunkImage ORM object via order_index if available.
                    # Since images are populated separately, we apply overlay at call-sites
                    # that call get_chunk_images — the dict here is always empty ("images": []).
                    # Caption overlay for images is handled in get_chunk_images.

        return all_chunks

    async def get_chunk(self, db: AsyncSession, chunk_id: str) -> dict | None:
        """Return a single chunk by UUID."""
        try:
            chunk_uuid = UUID(chunk_id)
        except ValueError:
            logger.warning("[chunk-ksvc] invalid chunk_id UUID: %s", chunk_id)
            return None
        result = await db.execute(
            select(ConceptChunk).where(ConceptChunk.id == chunk_uuid)
        )
        chunk = result.scalar_one_or_none()
        return self._chunk_to_dict(chunk) if chunk else None

    async def get_chunk_images(
        self, db: AsyncSession, chunk_id: str, lang: str = "en"
    ) -> list[dict]:
        """Return all images for a chunk in order.

        If *lang* is not 'en', captions are resolved from caption_translations,
        falling back to the English caption when the translation is absent.
        """
        from api.dependencies import resolve_translation
        try:
            chunk_uuid = UUID(chunk_id)
        except ValueError:
            logger.warning("[chunk-ksvc] invalid chunk_id UUID for images: %s", chunk_id)
            return []
        result = await db.execute(
            select(ChunkImage)
            .where(ChunkImage.chunk_id == chunk_uuid)
            .order_by(ChunkImage.order_index)
        )
        images = result.scalars().all()
        out = []
        for img in images:
            caption = img.caption
            if caption is not None and lang != "en":
                caption = resolve_translation(caption, img.caption_translations or {}, lang)
            out.append({"image_url": _normalize_image_url(img.image_url), "caption": caption})
        return out

    async def get_active_books(self, db: AsyncSession) -> set[str]:
        """Return set of book_slugs that have concept_chunks rows."""
        result = await db.execute(
            select(ConceptChunk.book_slug).distinct()
        )
        return {row[0] for row in result.fetchall()}

    async def get_chunk_count(self, db: AsyncSession, book_slug: str | None = None) -> int:
        """Count chunks (optionally filtered by book_slug)."""
        q = select(func.count(ConceptChunk.id))
        if book_slug:
            q = q.where(ConceptChunk.book_slug == book_slug)
        result = await db.execute(q)
        return result.scalar() or 0

    @staticmethod
    def _rewrite_image_urls(text: str | None, book_slug: str) -> str | None:
        """Rewrite Mathpix-style relative image refs in chunk Markdown to absolute paths
        served by the backend's /images/{book_slug}/mathpix_extracted mount.

        Mathpix puts ![alt](./images/<uuid>-<page>_<crop>.jpg) into the MMD output.
        Without rewriting, the browser resolves './images/...' against the current
        page URL (e.g. /learn/...) → 404.
        """
        if not text or "images/" not in text:
            return text
        import re as _re
        # Match  ![alt](./images/<file>)  OR  ![alt](images/<file>)
        # Capture only the trailing filename segment (handles spaces/parens via greedy chars-without-)).
        return _re.sub(
            r'(!\[[^\]]*\]\()(?:\./)?images/([^)\s]+)(\))',
            lambda m: f"{m.group(1)}/images/{book_slug}/mathpix_extracted/{m.group(2)}{m.group(3)}",
            text,
        )

    def _chunk_to_dict(self, chunk: ConceptChunk) -> dict:
        return {
            "id": str(chunk.id),
            "book_slug": chunk.book_slug,
            "concept_id": chunk.concept_id,
            "section": chunk.section,
            "order_index": chunk.order_index,
            "heading": chunk.heading,
            "text": self._rewrite_image_urls(chunk.text, chunk.book_slug),
            "latex": chunk.latex or [],
            "images": [],  # populated separately via get_chunk_images()
            "chunk_type": chunk.chunk_type,
            "is_optional": chunk.is_optional,
            "is_hidden": chunk.is_hidden,
            "exam_disabled": chunk.exam_disabled,
            "admin_section_name": chunk.admin_section_name,
        }

    # ── Graph methods (sync) ──────────────────────────────────────────────────

    def preload_graph(self, book_slug: str) -> None:
        """Preload graph into module cache, clearing any stale cached version."""
        with _graph_lock:
            _graph_cache.pop(book_slug, None)
        _load_graph(book_slug)

    def get_all_nodes(self, book_slug: str) -> list[dict]:
        """Return all nodes with title, chapter, section, in_degree, out_degree.
        chapter and section are derived from concept_id format 'prealgebra_1.1'."""
        G = _load_graph(book_slug)
        result = []
        for node_id, attrs in G.nodes(data=True):
            parts = node_id.split("_")
            # concept_id like 'prealgebra_1.1' — take last part
            num = parts[-1] if parts else node_id
            dot_idx = num.find(".")
            chapter = num[:dot_idx] if dot_idx != -1 else num
            section = num
            result.append({
                "concept_id": node_id,
                "title": attrs.get("title", ""),
                "chapter": chapter,
                "section": section,
                "in_degree": G.in_degree(node_id),
                "out_degree": G.out_degree(node_id),
            })
        result.sort(key=lambda n: (
            int(n["chapter"]) if n["chapter"].isdigit() else 999,
            float(n["section"]) if n["section"].replace(".", "", 1).isdigit() else 999,
        ))
        return result

    def get_all_edges(self, book_slug: str) -> list[dict]:
        G = _load_graph(book_slug)
        return [{"source": s, "target": t} for s, t in G.edges()]

    def get_graph_info(self, book_slug: str) -> dict:
        G = _load_graph(book_slug)
        roots = [n for n in G.nodes() if G.in_degree(n) == 0]
        leaves = [n for n in G.nodes() if G.out_degree(n) == 0]
        return {
            "num_nodes": G.number_of_nodes(),
            "num_edges": G.number_of_edges(),
            "is_dag": nx.is_directed_acyclic_graph(G),
            "root_concepts": roots,
            "leaf_concepts": leaves,
        }

    def get_topological_order(self, book_slug: str) -> list[dict]:
        G = _load_graph(book_slug)
        order = list(nx.topological_sort(G))
        result = []
        for depth, node_id in enumerate(order):
            attrs = G.nodes[node_id]
            num = node_id.split("_")[-1]
            dot_idx = num.find(".")
            chapter = num[:dot_idx] if dot_idx != -1 else num
            result.append({
                "concept_id": node_id,
                "title": attrs.get("title", ""),
                "chapter": chapter,
                "section": num,
                "depth": depth,
            })
        return result

    def get_all_prerequisites(self, book_slug: str, concept_id: str) -> list[str]:
        G = _load_graph(book_slug)
        if concept_id not in G:
            return []
        return list(nx.ancestors(G, concept_id))

    def get_predecessors(self, book_slug: str, concept_id: str) -> list[str]:
        G = _load_graph(book_slug)
        if concept_id not in G:
            return []
        return list(G.predecessors(concept_id))

    def get_concept_node(self, book_slug: str, concept_id: str) -> dict | None:
        G = _load_graph(book_slug)
        if concept_id not in G:
            return None
        attrs = G.nodes[concept_id]
        num = concept_id.split("_")[-1]
        dot_idx = num.find(".")
        chapter = num[:dot_idx] if dot_idx != -1 else num
        return {
            "concept_id": concept_id,
            "title": attrs.get("title", ""),
            "chapter": chapter,
            "section": num,
        }

    def get_next_concepts(self, book_slug: str, mastered: list[str]) -> list[dict]:
        """Return concepts whose all predecessors are in mastered (unlocked frontier)."""
        G = _load_graph(book_slug)
        mastered_set = set(mastered)
        result = []
        for node_id in G.nodes():
            if node_id in mastered_set:
                continue
            prereqs = list(G.predecessors(node_id))
            if all(p in mastered_set for p in prereqs):
                attrs = G.nodes[node_id]
                num = node_id.split("_")[-1]
                dot_idx = num.find(".")
                chapter = num[:dot_idx] if dot_idx != -1 else num
                result.append({
                    "concept_id": node_id,
                    "title": attrs.get("title", ""),
                    "chapter": chapter,
                    "section": num,
                    "missing_prerequisites": [],
                })
        return result

    def get_locked_concepts(self, book_slug: str, mastered: list[str]) -> list[dict]:
        """Return concepts that have at least one unmet prerequisite."""
        G = _load_graph(book_slug)
        mastered_set = set(mastered)
        result = []
        for node_id in G.nodes():
            if node_id in mastered_set:
                continue
            prereqs = list(G.predecessors(node_id))
            missing = [p for p in prereqs if p not in mastered_set]
            if missing:
                attrs = G.nodes[node_id]
                num = node_id.split("_")[-1]
                dot_idx = num.find(".")
                chapter = num[:dot_idx] if dot_idx != -1 else num
                result.append({
                    "concept_id": node_id,
                    "title": attrs.get("title", ""),
                    "chapter": chapter,
                    "section": num,
                    "missing_prerequisites": missing,
                })
        return result

    def get_learning_path(self, book_slug: str, target: str, mastered: list[str]) -> dict:
        """Return shortest path from any unmastered prereq to target."""
        G = _load_graph(book_slug)
        mastered_set = set(mastered)
        unmet = [p for p in nx.ancestors(G, target) if p not in mastered_set] if target in G else []
        # Build subgraph of relevant nodes
        path = []
        if unmet:
            for anc in nx.topological_sort(G):
                if anc in unmet or anc == target:
                    path.append(anc)
        else:
            path = [target]
        return {"target": target, "path": path, "total_steps": len(path)}

    # ── Async concept-detail methods ──────────────────────────────────────────

    async def get_concept_detail(self, db: AsyncSession, concept_id: str, book_slug: str, lang: str = "en") -> dict | None:
        """Aggregate all chunks for a concept: longest text, all latex, all images."""
        from api.dependencies import resolve_translation
        result = await db.execute(
            select(ConceptChunk)
            .where(ConceptChunk.book_slug == book_slug, ConceptChunk.concept_id == concept_id)
            .order_by(ConceptChunk.order_index)
        )
        chunks = result.scalars().all()
        if not chunks:
            return None
        primary = max(chunks, key=lambda c: len(c.text or ""))
        all_latex = [expr for c in chunks for expr in (c.latex or [])]
        chunk_ids = [c.id for c in chunks]
        img_result = await db.execute(
            select(ChunkImage)
            .where(ChunkImage.chunk_id.in_(chunk_ids))
            .order_by(ChunkImage.order_index)
        )
        images = [
            {"image_url": _normalize_image_url(img.image_url), "caption": img.caption,
             "url": _normalize_image_url(img.image_url), "filename": (img.image_url or "").split("/")[-1],
             "width": 0, "height": 0, "image_type": "figure",
             "page": 0, "description": img.caption or "", "relevance": "relevant"}
            for img in img_result.scalars().all()
        ]
        # Get graph info for prereqs/dependents
        try:
            prereqs = self.get_predecessors(book_slug, concept_id)
            G = _load_graph(book_slug)
            dependents = list(G.successors(concept_id)) if concept_id in G else []
        except Exception:
            prereqs, dependents = [], []
        num = concept_id.split("_")[-1]
        dot_idx = num.find(".")
        chapter = num[:dot_idx] if dot_idx != -1 else num
        heading = resolve_translation(primary.heading, primary.heading_translations or {}, lang)
        return {
            "concept_id": concept_id,
            "concept_title": heading,   # keep 'concept_title' key for compat with adaptive_engine
            "title": heading,
            "chapter": chapter,
            "section": num,
            "text": primary.text,
            "latex": all_latex,
            "images": images,
            "prerequisites": prereqs,
            "dependents": dependents,
            "sub_sections": [self._chunk_to_dict(c) for c in chunks],
        }

    async def query_similar_chunks(self, db: AsyncSession, book_slug: str,
                                    query_embedding: list[float], n: int = 5) -> list[dict]:
        """pgvector cosine similarity search."""
        sql = text("""
            SELECT id, concept_id, section, heading, text,
                   1 - (embedding <=> cast(:qvec as vector)) AS score
            FROM concept_chunks
            WHERE book_slug = :slug AND embedding IS NOT NULL
            ORDER BY embedding <=> cast(:qvec as vector)
            LIMIT :n
        """)
        rows = await db.execute(sql, {"qvec": str(query_embedding), "slug": book_slug, "n": n})
        results = []
        for row in rows:
            try:
                prereqs = self.get_all_prerequisites(book_slug, row.concept_id)
            except Exception:
                prereqs = []
            results.append({
                "concept_id": row.concept_id,
                "section": row.section,
                "heading": row.heading,
                "text": row.text,
                "score": float(row.score),
                "prerequisites": prereqs,
            })
        return results
