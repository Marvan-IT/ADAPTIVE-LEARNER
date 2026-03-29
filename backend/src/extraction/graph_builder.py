"""
graph_builder.py — Build the concept dependency graph from the concept_chunks table.

Strategy (Phase 2):
  Sequential edges within each chapter: section N.k → N.(k+1).
  Each chapter forms an independent linear chain. No cross-chapter edges at this stage.

Future enhancement:
  Cross-chapter prerequisite edges detected by LLM analysis of "prerequisite" mentions
  in chunk text. That is deferred to a later phase.

Output: graph.json written to the book's output directory.
  Format:
    { "nodes": [{"id": "prealgebra_1.1", "title": "1.1 Introduction to Whole Numbers"}, ...],
      "edges": [{"source": "prealgebra_1.1", "target": "prealgebra_1.2"}, ...] }
"""

import json
import logging
from itertools import groupby
from pathlib import Path

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ConceptChunk

logger = logging.getLogger(__name__)


def _chapter_num(concept_id: str) -> str:
    """
    Extract chapter number string from a concept_id.

    e.g. "prealgebra_1.2" → "1"
         "prealgebra_10.3" → "10"
    """
    # concept_id format: "{book_slug}_{chapter}.{section}"
    after_slug = concept_id.split("_", 1)[-1]   # "1.2"
    return after_slug.split(".")[0]              # "1"


def _section_sort_key(concept_id: str) -> tuple[int, int]:
    """Return (chapter, section) ints for stable sorting."""
    after_slug = concept_id.split("_", 1)[-1]
    parts = after_slug.split(".")
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return 0, 0


async def build_graph(db: AsyncSession, book_slug: str, graph_path: Path) -> None:
    """
    Build and persist the concept dependency graph for a book.

    Reads all unique (concept_id, section) pairs from concept_chunks, adds one node
    per concept_id, then adds sequential prerequisite edges within each chapter.

    Args:
        db:         Open async SQLAlchemy session.
        book_slug:  e.g. "prealgebra".
        graph_path: Destination file for graph.json.
    """
    # Fetch unique (concept_id, section) pairs.
    # ORDER BY is omitted here because SELECT DISTINCT requires any ORDER BY column
    # to appear in the select list (PostgreSQL restriction). The caller sorts by
    # _section_sort_key after deduplication, which gives the correct chapter/section order.
    result = await db.execute(
        select(ConceptChunk.concept_id, ConceptChunk.section)
        .where(ConceptChunk.book_slug == book_slug)
        .distinct()
    )
    rows = result.fetchall()

    if not rows:
        logger.warning("No concept_chunks found for book_slug=%s — graph not built", book_slug)
        return

    # Deduplicate while preserving order (order_by above is per-chunk, not per-concept)
    seen_concepts: set[str] = set()
    ordered_sections: list[tuple[str, str]] = []  # (concept_id, section_title)
    for concept_id, section_title in rows:
        if concept_id not in seen_concepts:
            seen_concepts.add(concept_id)
            ordered_sections.append((concept_id, section_title))

    logger.info("Building graph for %s: %d unique concepts", book_slug, len(ordered_sections))

    G = nx.DiGraph()

    # Add nodes
    for concept_id, section_title in ordered_sections:
        G.add_node(concept_id, title=section_title)

    # Add sequential prerequisite edges within each chapter
    sorted_sections = sorted(ordered_sections, key=lambda x: _section_sort_key(x[0]))
    for _chapter, group in groupby(sorted_sections, key=lambda x: _chapter_num(x[0])):
        chapter_concepts = [item[0] for item in group]
        for i in range(len(chapter_concepts) - 1):
            G.add_edge(chapter_concepts[i], chapter_concepts[i + 1])

    # Serialize to graph.json
    data = {
        "nodes": [
            {"id": node_id, "title": G.nodes[node_id]["title"]}
            for node_id in G.nodes
        ],
        "edges": [
            {"source": u, "target": v}
            for u, v in G.edges
        ],
    }
    graph_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(
        "Graph saved to %s: %d nodes, %d edges",
        graph_path, len(G.nodes), len(G.edges),
    )


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import argparse
    import sys
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    from db.connection import async_session_factory
    from config import OUTPUT_DIR

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    ap = argparse.ArgumentParser(description="Build concept dependency graph from concept_chunks table")
    ap.add_argument("--book", default="prealgebra", help="Book slug (e.g. prealgebra)")
    args = ap.parse_args()

    graph_output = OUTPUT_DIR / args.book / "graph.json"

    async def _run():
        async with async_session_factory() as session:
            await build_graph(session, args.book, graph_output)
        print(f"Graph written to: {graph_output}")

    asyncio.run(_run())
