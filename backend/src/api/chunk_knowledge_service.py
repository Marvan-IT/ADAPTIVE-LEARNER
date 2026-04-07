"""
ChunkKnowledgeService — replaces KnowledgeService (ChromaDB) with pgvector SQL queries.

Provides chunk retrieval from PostgreSQL concept_chunks and chunk_images tables.
No initialization needed — queries DB on demand via AsyncSession.
"""

import json
import logging
from pathlib import Path
from uuid import UUID

import networkx as nx
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ConceptChunk, ChunkImage
from config import OUTPUT_DIR

logger = logging.getLogger(__name__)


_graph_cache: dict[str, nx.DiGraph] = {}


def _load_graph(book_slug: str) -> nx.DiGraph:
    """Load graph.json as NetworkX DiGraph, cache module-level."""
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


class ChunkKnowledgeService:
    """Provides chunk retrieval from PostgreSQL. No initialization needed — queries DB on demand."""

    async def get_chunks_for_concept(
        self, db: AsyncSession, book_slug: str, concept_id: str
    ) -> list[dict]:
        """Return all chunks for a concept in order_index order."""
        result = await db.execute(
            select(ConceptChunk)
            .where(ConceptChunk.book_slug == book_slug, ConceptChunk.concept_id == concept_id)
            .order_by(ConceptChunk.order_index)
        )
        chunks = result.scalars().all()
        all_chunks = [self._chunk_to_dict(c) for c in chunks]
        # Exclude chunks with no real content — heading-only stubs (e.g. "SECTION 1.1 EXERCISES",
        # "Practice Makes Perfect (Exercises)") are extracted with < 100 chars of text and cannot
        # generate meaningful cards. This rule applies to all books and all sections.
        all_chunks = [c for c in all_chunks if len((c.get("text") or "").strip()) >= 100]
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

    async def get_chunk_images(self, db: AsyncSession, chunk_id: str) -> list[dict]:
        """Return all images for a chunk in order."""
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
        return [{"image_url": img.image_url, "caption": img.caption} for img in images]

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

    def _chunk_to_dict(self, chunk: ConceptChunk) -> dict:
        return {
            "id": str(chunk.id),
            "book_slug": chunk.book_slug,
            "concept_id": chunk.concept_id,
            "section": chunk.section,
            "order_index": chunk.order_index,
            "heading": chunk.heading,
            "text": chunk.text,
            "latex": chunk.latex or [],
            "images": [],  # populated separately via get_chunk_images()
        }

    # ── Graph methods (sync) ──────────────────────────────────────────────────

    def preload_graph(self, book_slug: str) -> None:
        """Preload graph into module cache at startup."""
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

    async def get_concept_detail(self, db: AsyncSession, concept_id: str, book_slug: str) -> dict | None:
        """Aggregate all chunks for a concept: longest text, all latex, all images."""
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
            {"image_url": img.image_url, "caption": img.caption,
             "url": img.image_url, "filename": (img.image_url or "").split("/")[-1],
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
        return {
            "concept_id": concept_id,
            "concept_title": primary.section,   # keep 'concept_title' key for compat with adaptive_engine
            "title": primary.section,
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
