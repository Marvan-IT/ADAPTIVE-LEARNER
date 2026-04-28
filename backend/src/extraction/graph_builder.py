"""
graph_builder.py — Build the concept dependency graph from the concept_chunks table.

Strategy:
  1. Sequential edges within each chapter: section N.k → N.(k+1).
  2. LLM-based cross-chapter prerequisites: ask gpt-4o-mini which chapters
     are TRUE prerequisites for other chapters (works for ANY subject domain).
  3. Merge expert/keyword-based cross-chapter edges from dependency_graph.json (if exists).

Output: graph.json written to the book's output directory.
  Format:
    { "nodes": [{"id": "prealgebra_1.1", "title": "1.1 Introduction to Whole Numbers"}, ...],
      "edges": [{"source": "prealgebra_1.1", "target": "prealgebra_1.2"}, ...] }
"""

import json
import logging
import re
from itertools import groupby
from pathlib import Path

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ConceptChunk

logger = logging.getLogger(__name__)

# NOTE: graph_builder.py is an offline pipeline tool (Stage 3 ingestion); it does
# not have a live AsyncSession available at its entry points.  Live AdminConfig model
# resolution is deferred to a future patch.  See docs/round5-fixes/execution-plan.md P4-7.

# ── LLM-based cross-chapter prerequisite detection ──────────────────────────

async def _get_llm_chapter_prerequisites(
    chapter_sections: dict[str, list[str]],
    book_slug: str,
) -> dict[str, list[str]]:
    """Ask LLM which chapters are true prerequisites for other chapters.

    Args:
        chapter_sections: {"1": ["1.1 Introduction", "1.2 Add Numbers"], "2": [...], ...}
        book_slug: e.g. "prealgebra" or "clinical_nursing_skills"

    Returns:
        {"3": ["1"], "5": ["1", "3"]} meaning chapter 3 requires chapter 1, etc.
        Returns empty dict on any failure (graceful fallback).
    """
    try:
        from openai import AsyncOpenAI
        from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL_MINI
    except ImportError:
        logger.warning("[graph] OpenAI not available — skipping LLM cross-chapter analysis")
        return {}

    if not OPENAI_API_KEY:
        logger.warning("[graph] OPENAI_API_KEY not set — skipping LLM cross-chapter analysis")
        return {}

    # Build chapter summary for LLM
    chapter_list = []
    for ch_num in sorted(chapter_sections.keys(), key=lambda c: int(c) if c.isdigit() else 999):
        sections = chapter_sections[ch_num]
        # Use first section title as chapter title, list all section titles
        chapter_title = sections[0].split(" | ")[0] if sections else f"Chapter {ch_num}"
        section_names = ", ".join(s for s in sections[:8])  # limit to 8 sections for token efficiency
        if len(sections) > 8:
            section_names += f", ... (+{len(sections) - 8} more)"
        chapter_list.append(f"Chapter {ch_num}: {chapter_title}\n  Sections: {section_names}")

    chapters_text = "\n".join(chapter_list)

    prompt = f"""You are a curriculum designer analyzing a textbook's chapter structure.

Given the chapters below, determine which chapters are TRUE prerequisites for each chapter.
A prerequisite means a student CANNOT properly understand this chapter without completing
the prerequisite chapter first. This is about conceptual dependency, not just reading order.

IMPORTANT RULES:
- Many chapters may have NO prerequisites (they can be studied independently).
- Only list DIRECT prerequisites, not transitive ones.
  (If Ch3 needs Ch2, and Ch2 needs Ch1, list Ch3: ["2"], NOT Ch3: ["1", "2"])
- Do NOT assume every chapter depends on the previous one.
- Think about what knowledge is actually REQUIRED, not just recommended.

Book: {book_slug.replace("_", " ")}

{chapters_text}

Return a JSON object where each key is a chapter number (as string) and the value is
a list of prerequisite chapter numbers (as strings). Include ALL chapters, even those
with empty prerequisite lists.

Example: {{"1": [], "2": [], "3": ["1"], "4": ["2", "3"], "5": []}}"""

    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        response = await client.chat.completions.create(
            model=OPENAI_MODEL_MINI,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=30.0,
        )
        result_text = response.choices[0].message.content.strip()
        result = json.loads(result_text)

        # Validate: result should be {str: list[str]}
        validated: dict[str, list[str]] = {}
        valid_chapters = set(chapter_sections.keys())
        for ch, prereqs in result.items():
            ch_str = str(ch)
            if ch_str not in valid_chapters:
                continue
            if not isinstance(prereqs, list):
                continue
            valid_prereqs = [str(p) for p in prereqs if str(p) in valid_chapters and str(p) != ch_str]
            if valid_prereqs:
                validated[ch_str] = valid_prereqs

        logger.info(
            "[graph] LLM chapter prerequisites for %s: %d chapters with dependencies",
            book_slug, len(validated),
        )
        return validated

    except Exception as exc:
        logger.warning("[graph] LLM cross-chapter analysis failed for %s: %s", book_slug, exc)
        return {}


async def _get_llm_section_prerequisites(
    chapter_sections: dict[str, list[str]],
    chapter_deps: dict[str, list[str]],
    book_slug: str,
) -> list[tuple[str, str]]:
    """Ask GPT-4o for section-level cross-chapter prerequisites.

    For each chapter with dependencies, asks which specific sections from
    prerequisite chapters are needed by each section in the dependent chapter.

    Returns list of (source_concept_id, target_concept_id) edges.
    """
    try:
        from openai import AsyncOpenAI
        from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
    except ImportError:
        logger.warning("[graph] OpenAI not available — skipping section-level analysis")
        return []

    if not OPENAI_API_KEY:
        return []

    chapters_to_analyze = {ch: deps for ch, deps in chapter_deps.items() if deps}
    if not chapters_to_analyze:
        return []

    all_edges: list[tuple[str, str]] = []
    client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    # Build section_number → concept_id mapping
    sec_to_cid: dict[str, str] = {}
    for ch, secs in chapter_sections.items():
        for sec_title in secs:
            sec_num_match = re.match(r"(\d+\.\d+)", sec_title)
            if sec_num_match:
                sec_to_cid[sec_num_match.group(1)] = f"{book_slug}_{sec_num_match.group(1)}"

    # Process in batches of 3 chapters per LLM call
    dep_items = list(chapters_to_analyze.items())
    for batch_start in range(0, len(dep_items), 3):
        batch = dep_items[batch_start:batch_start + 3]

        prompt_parts = [
            "You are a curriculum designer analyzing section-level prerequisites.\n\n"
            "For each TARGET section below, determine which specific sections from the "
            "PREREQUISITE chapters a student MUST complete first to understand the target.\n\n"
            "RULES:\n"
            "- Only list DIRECT cross-chapter prerequisites.\n"
            "- Within-chapter sequential dependencies (3.1→3.2→3.3) are already handled — skip those.\n"
            "- Be specific — list exact section numbers, not whole chapters.\n"
            "- A section may have 0 cross-chapter prerequisites — omit it from output.\n"
            "- Think about what mathematical/conceptual knowledge is REQUIRED.\n\n"
        ]

        for dep_ch, prereq_chs in batch:
            target_secs = chapter_sections.get(dep_ch, [])
            prompt_parts.append(f"TARGET — Chapter {dep_ch}:")
            for s in target_secs[:12]:
                prompt_parts.append(f"  {s}")
            prompt_parts.append("")

            prompt_parts.append("PREREQUISITE CHAPTERS:")
            for prereq_ch in prereq_chs:
                prereq_secs = chapter_sections.get(prereq_ch, [])
                prompt_parts.append(f"  Chapter {prereq_ch}:")
                for s in prereq_secs[:12]:
                    prompt_parts.append(f"    {s}")
            prompt_parts.append("")

        prompt_parts.append(
            'Return JSON mapping target section numbers to lists of prerequisite section numbers.\n'
            'Only include sections with cross-chapter prerequisites.\n'
            'Example: {"3.1": ["1.1"], "3.2": ["1.1", "1.3"], "5.1": ["3.2"]}'
        )

        try:
            response = await client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": "\n".join(prompt_parts)}],
                response_format={"type": "json_object"},
                temperature=0.1,
                timeout=60.0,
            )
            result = json.loads(response.choices[0].message.content.strip())

            batch_edges = 0
            for target_sec, prereq_secs in result.items():
                target_cid = sec_to_cid.get(str(target_sec))
                if not target_cid or not isinstance(prereq_secs, list):
                    continue
                for prereq_sec in prereq_secs:
                    prereq_cid = sec_to_cid.get(str(prereq_sec))
                    if prereq_cid and prereq_cid != target_cid:
                        src_ch = str(prereq_sec).split(".")[0]
                        tgt_ch = str(target_sec).split(".")[0]
                        if src_ch != tgt_ch:
                            all_edges.append((prereq_cid, target_cid))
                            batch_edges += 1

            logger.info("[graph] Section-level batch %d: %d edges", batch_start // 3 + 1, batch_edges)

        except Exception as exc:
            logger.warning("[graph] Section-level LLM call failed (batch %d): %s", batch_start // 3 + 1, exc)

    logger.info("[graph] Section-level prerequisites total: %d edges for %s", len(all_edges), book_slug)
    return all_edges


def _chapter_num(concept_id: str) -> str:
    """
    Extract chapter number string from a concept_id.

    e.g. "prealgebra_1.2" → "1"
         "prealgebra_10.3" → "10"
         "prealgebra2e_0qbw93r_(1)_1.2" → "1"
    """
    # concept_id format: "{book_slug}_{chapter}.{section}"
    # Use rsplit to handle slugs with underscores
    after_slug = concept_id.rsplit("_", 1)[-1]   # "1.2"
    return after_slug.split(".")[0]               # "1"


def _section_sort_key(concept_id: str) -> tuple[int, int]:
    """Return (chapter, section) ints for stable sorting."""
    after_slug = concept_id.rsplit("_", 1)[-1]
    parts = after_slug.split(".")
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return 999, 999


def _parse_dep_graph_chapter_section(dep_node_id: str) -> tuple[int, int] | None:
    """Parse chapter.section from a dependency_graph.json node ID.

    Formats handled:
      "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS" → (1, 1)
      "prealgebra_1.1"                              → (1, 1)
    """
    # Try PREALG.C{ch}.S{sec}.TITLE format
    m = re.match(r".*\.C(\d+)\.S(\d+)\.", dep_node_id)
    if m:
        return int(m.group(1)), int(m.group(2))
    # Try book_slug_{ch}.{sec} format
    after = dep_node_id.rsplit("_", 1)[-1]
    parts = after.split(".")
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    return None


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

    # ── LLM-based cross-chapter prerequisites ───────────────────────────
    # Instead of forcing a linear chain (ch1 → ch2 → ch3), ask LLM which
    # chapters truly depend on others. Works for any subject domain.

    # Build chapter → [concept_ids] and chapter → [section_titles] maps
    _ch_concepts: dict[str, list[str]] = {}
    _ch_titles: dict[str, list[str]] = {}
    for concept_id, section_title in ordered_sections:
        ch = _chapter_num(concept_id)
        if ch not in _ch_concepts:
            _ch_concepts[ch] = []
            _ch_titles[ch] = []
        if concept_id not in _ch_concepts[ch]:
            _ch_concepts[ch].append(concept_id)
            _ch_titles[ch].append(section_title or concept_id)

    for ch in _ch_concepts:
        _ch_concepts[ch].sort(key=_section_sort_key)

    # Ask LLM for cross-chapter dependencies
    llm_deps = await _get_llm_chapter_prerequisites(_ch_titles, book_slug)

    # Add LLM-determined cross-chapter edges
    llm_edge_count = 0
    llm_skipped_cycle = 0
    for dependent_ch, prereq_chapters in llm_deps.items():
        if dependent_ch not in _ch_concepts:
            continue
        first_of_dependent = _ch_concepts[dependent_ch][0]
        for prereq_ch in prereq_chapters:
            if prereq_ch not in _ch_concepts:
                continue
            last_of_prereq = _ch_concepts[prereq_ch][-1]
            if G.has_edge(last_of_prereq, first_of_dependent):
                continue
            # Only add if it doesn't create a cycle
            if nx.has_path(G, first_of_dependent, last_of_prereq):
                llm_skipped_cycle += 1
                continue
            G.add_edge(last_of_prereq, first_of_dependent)
            llm_edge_count += 1

    logger.info(
        "LLM cross-chapter edges for %s: %d added, %d skipped (cycle prevention)",
        book_slug, llm_edge_count, llm_skipped_cycle,
    )

    # ── Section-level cross-chapter prerequisites (GPT-4o) ────────────
    section_edges = await _get_llm_section_prerequisites(_ch_titles, llm_deps, book_slug)
    section_edge_count = 0
    section_skipped = 0
    for src, tgt in section_edges:
        if src in G.nodes and tgt in G.nodes:
            if not G.has_edge(src, tgt):
                if not nx.has_path(G, tgt, src):  # cycle prevention
                    G.add_edge(src, tgt)
                    section_edge_count += 1
                else:
                    section_skipped += 1
    logger.info(
        "Section-level edges for %s: %d added, %d skipped (cycle prevention)",
        book_slug, section_edge_count, section_skipped,
    )

    # Merge expert/keyword edges from dependency_graph.json (if available)
    dep_graph_path = graph_path.parent / "dependency_graph.json"
    if dep_graph_path.exists():
        try:
            dep_data = json.loads(dep_graph_path.read_text(encoding="utf-8"))
            dep_nodes = dep_data.get("nodes", [])
            dep_edges = dep_data.get("edges", [])

            # Build mapping: (chapter, section) → concept_id in our graph
            ch_sec_to_id: dict[tuple[int, int], str] = {}
            for cid in G.nodes:
                key = _section_sort_key(cid)
                if key != (999, 999):
                    ch_sec_to_id[key] = cid

            # Build mapping: dep_graph node_id → (chapter, section)
            dep_id_to_ch_sec: dict[str, tuple[int, int]] = {}
            for dn in dep_nodes:
                parsed = _parse_dep_graph_chapter_section(dn["id"])
                if parsed:
                    dep_id_to_ch_sec[dn["id"]] = parsed

            merged_count = 0
            skipped_cycle = 0
            for de in dep_edges:
                src_cs = dep_id_to_ch_sec.get(de["source"])
                tgt_cs = dep_id_to_ch_sec.get(de["target"])
                if not src_cs or not tgt_cs:
                    continue
                src_id = ch_sec_to_id.get(src_cs)
                tgt_id = ch_sec_to_id.get(tgt_cs)
                if not src_id or not tgt_id:
                    continue
                if src_id == tgt_id:
                    continue
                if G.has_edge(src_id, tgt_id):
                    continue
                # Only add if it doesn't create a cycle
                if G.has_node(tgt_id) and G.has_node(src_id) and nx.has_path(G, tgt_id, src_id):
                    skipped_cycle += 1
                    continue
                G.add_edge(src_id, tgt_id)
                merged_count += 1

            logger.info(
                "Merged %d expert edges from dependency_graph.json (%d skipped due to cycles)",
                merged_count, skipped_cycle,
            )
        except Exception as exc:
            logger.warning("Could not merge dependency_graph.json: %s", exc)

    logger.info("Final graph: %d nodes, %d edges", len(G.nodes), len(G.edges))

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


def _save_graph(graph_path: Path, G: nx.DiGraph) -> None:
    """Serialize a NetworkX DiGraph to the graph.json format used by this project."""
    data = {
        "nodes": [
            {"id": node_id, "title": G.nodes[node_id].get("title", "")}
            for node_id in G.nodes
        ],
        "edges": [
            {"source": u, "target": v}
            for u, v in G.edges
        ],
    }
    graph_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def insert_section_node(
    graph_path: Path,
    new_concept_id: str,
    label: str,
    after_concept_id: str,
) -> None:
    """Insert a new section node into graph.json after an existing section.

    Graph wiring performed:
      1. Add the new node with the given label.
      2. Add edge:  after_concept_id → new_concept_id
      3. Rewire successors: for every direct successor S of after_concept_id,
         remove the edge after_concept_id → S and add new_concept_id → S.
         This inserts the new section into the existing linear chain.

    The modified graph is written back to graph_path atomically (write then rename).

    Args:
        graph_path:      Path to graph.json on disk.
        new_concept_id:  The concept_id of the new section node to insert.
        label:           Human-readable section title stored as the node's "title".
        after_concept_id: The existing node that will become the immediate predecessor.

    Raises:
        FileNotFoundError: If graph_path does not exist.
        ValueError:        If after_concept_id is not in the graph, or if
                           new_concept_id already exists in the graph.
    """
    if not graph_path.exists():
        raise FileNotFoundError(f"graph.json not found: {graph_path}")

    data = json.loads(graph_path.read_text(encoding="utf-8"))

    G = nx.DiGraph()
    for node in data["nodes"]:
        G.add_node(node["id"], title=node.get("title", ""))
    for edge in data["edges"]:
        G.add_edge(edge["source"], edge["target"])

    if not G.has_node(after_concept_id):
        raise ValueError(
            f"after_concept_id '{after_concept_id}' not found in graph {graph_path}"
        )
    if G.has_node(new_concept_id):
        raise ValueError(
            f"new_concept_id '{new_concept_id}' already exists in graph {graph_path}"
        )

    # Collect successors before mutating the graph
    successors = list(G.successors(after_concept_id))

    # Add new node and edge from predecessor → new node
    G.add_node(new_concept_id, title=label)
    G.add_edge(after_concept_id, new_concept_id)

    # Rewire: detach each successor from the old node and attach to the new node
    for successor in successors:
        G.remove_edge(after_concept_id, successor)
        G.add_edge(new_concept_id, successor)

    # Write back atomically: write to a temp file then replace
    tmp_path = graph_path.with_suffix(".json.tmp")
    _save_graph(tmp_path, G)
    tmp_path.replace(graph_path)

    logger.info(
        "insert_section_node: added '%s' after '%s' in %s "
        "(rewired %d successor(s))",
        new_concept_id, after_concept_id, graph_path, len(successors),
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
