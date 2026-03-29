"""
Prerequisite remediation helpers.

Determines which (if any) direct prerequisite of a concept the student has
not yet mastered, using one-hop graph traversal.  The caller (adaptive_engine)
is responsible for building mastery_store from the database — these functions
receive it as a plain dict so they remain free of I/O.

Only direct predecessors are checked (one hop), not transitive ancestors.
Order follows NetworkX edge-insertion order, which equals curriculum order.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)


def find_remediation_prereq(
    concept_id: str,
    chunk_ksvc,             # ChunkKnowledgeService — typed as Any to avoid circular import
    book_slug: str,
    mastery_store: dict[str, bool],
) -> str | None:
    """
    Return the concept_id of the first direct prerequisite that the student
    has not yet mastered, or None if all prerequisites are mastered (or there
    are no prerequisites at all).

    Args:
        concept_id:    The concept currently being taught.
        chunk_ksvc:    ChunkKnowledgeService instance; used to access graph via
                       chunk_ksvc.get_predecessors(book_slug, concept_id).
        book_slug:     The book the concept belongs to.
        mastery_store: Mapping of concept_id → True for every concept the
                       student has mastered.  Missing keys are treated as
                       unmastered.

    Returns:
        A concept_id string, or None.
    """
    try:
        direct_prereqs = chunk_ksvc.get_predecessors(book_slug, concept_id)
    except Exception as exc:
        # Unknown node: get_predecessors returns [] for nodes not in graph
        logger.warning(
            "get_predecessors() failed for concept_id=%s: %s — skipping remediation",
            concept_id,
            exc,
        )
        return None

    for prereq_id in direct_prereqs:
        if not mastery_store.get(prereq_id, False):
            logger.debug(
                "Unmet prerequisite found for concept_id=%s: prereq=%s",
                concept_id,
                prereq_id,
            )
            return prereq_id

    return None


def has_unmet_prereq(
    concept_id: str,
    chunk_ksvc,
    book_slug: str,
    mastery_store: dict[str, bool],
) -> bool:
    """
    Return True if any direct prerequisite of concept_id is not mastered.

    Convenience wrapper around find_remediation_prereq.
    """
    return find_remediation_prereq(concept_id, chunk_ksvc, book_slug, mastery_store) is not None


def build_remediation_cards(
    prereq_concept_id: str,
    prereq_detail: dict,
) -> list[dict]:
    """
    Build exactly 3 template-based review cards for a prerequisite concept.

    Cards are constructed without an LLM call (v1 design decision — keeps
    latency and cost low; quality trade-off accepted by the product team).

    Args:
        prereq_concept_id: The concept_id of the prerequisite.
        prereq_detail:     The dict returned by
                           KnowledgeService.get_concept_detail(prereq_concept_id).

    Returns:
        A list of 3 dicts matching the AdaptiveLessonCard schema.
    """
    prereq_title = prereq_detail.get("concept_title", prereq_concept_id)
    prereq_text = prereq_detail.get("text", "")

    # Truncate source text for cards to keep them concise
    text_400 = prereq_text[:400].rstrip() + ("..." if len(prereq_text) > 400 else "")
    text_200 = prereq_text[:200].rstrip() + ("..." if len(prereq_text) > 200 else "")

    cards: list[dict] = [
        # Card 1 — explain: brief text excerpt
        {
            "type": "explain",
            "title": f"[Review] Understanding {prereq_title}",
            "content": text_400 if text_400.strip() else f"Let us briefly revisit **{prereq_title}** before continuing.",
            "answer": None,
            "hints": [],
            "difficulty": 1,
            "fun_element": None,
        },
        # Card 2 — example: key example from prereq text
        {
            "type": "example",
            "title": f"[Review] Quick Example: {prereq_title}",
            "content": (
                f"Before we continue, here is a key example from **{prereq_title}**:\n\n"
                + (text_200 if text_200.strip() else f"Recall the core idea of {prereq_title}.")
            ),
            "answer": None,
            "hints": [f"Think about the core idea of {prereq_title}"],
            "difficulty": 1,
            "fun_element": None,
        },
        # Card 3 — checkpoint: self-check in own words
        {
            "type": "checkpoint",
            "title": f"[Review] Check: {prereq_title}",
            "content": (
                f"Quick check: Can you recall the main idea from **{prereq_title}**?\n\n"
                "Write a one-sentence summary in your own words."
            ),
            "answer": None,
            "hints": ["Focus on the definition, not formulas"],
            "difficulty": 2,
            "fun_element": None,
        },
    ]

    logger.debug(
        "Built %d remediation cards for prereq=%s (%s)",
        len(cards),
        prereq_concept_id,
        prereq_title,
    )
    return cards
