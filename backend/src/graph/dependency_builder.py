"""
Dependency Builder — constructs TRUE prerequisite edges between concept blocks.

Two strategies:
  1. Expert graph: hand-curated prerequisite maps for known books (prealgebra, etc.)
  2. Keyword-based: analyzes concept names to infer logical dependencies for any book.

Design principles:
  - Prerequisites reflect SKILL dependency (cannot-do-without), NOT textbook sequence.
  - No transitive prerequisites — only DIRECT dependencies.
  - Parallel branches where topics are independent.
  - Operations hierarchy: ADD -> SUBTRACT, ADD -> MULTIPLY, SUBTRACT+MULTIPLY -> DIVIDE.
"""

from collections import defaultdict
from pathlib import Path

import sys
import os
import yaml as _yaml
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from extraction.domain_models import ConceptBlock, DependencyEdge


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

def build_dependency_edges(concept_blocks: list[ConceptBlock]) -> list[DependencyEdge]:
    """
    Build prerequisite relationships between concepts.
    Uses expert graph if available, otherwise falls back to keyword-based builder.
    """
    if not concept_blocks:
        return []

    book_slug = concept_blocks[0].book_slug
    concept_ids = {b.concept_id for b in concept_blocks}

    # Try expert graph first
    expert_map = _get_expert_graph(book_slug)
    if expert_map:
        # Validate that expert graph matches actual concept IDs
        expert_ids = set(expert_map.keys())
        if expert_ids == concept_ids:
            print(f"  Using expert dependency graph for {book_slug}")
            return _map_to_edges(concept_blocks, expert_map)
        else:
            missing = expert_ids - concept_ids
            extra = concept_ids - expert_ids
            if missing:
                print(f"  Warning: Expert graph has {len(missing)} IDs not in concepts")
            if extra:
                print(f"  Warning: {len(extra)} concepts not in expert graph")
            print("  Falling back to keyword-based builder")

    # Fallback: keyword-based builder
    print(f"  Using keyword-based dependency builder for {book_slug}")
    prereq_map = _build_keyword_dependencies(concept_blocks)
    return _map_to_edges(concept_blocks, prereq_map)


# ═══════════════════════════════════════════════════════════════════════
# EXPERT GRAPHS — hand-curated for known books
# ═══════════════════════════════════════════════════════════════════════

def _get_expert_graph(book_slug: str) -> dict | None:
    """Load expert dependency graph from YAML file if it exists for this book."""
    path = Path(__file__).parent / "expert_graphs" / f"{book_slug}.yaml"
    if not path.exists():
        return None
    data = _yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("dependencies", {})


# ═══════════════════════════════════════════════════════════════════════
# KEYWORD-BASED GENERAL BUILDER (for books without expert graphs)
# ═══════════════════════════════════════════════════════════════════════

# Domain keywords (checked against concept name)
_DOMAIN_KEYWORDS = {
    "WHOLE_NUMBERS": ["WHOLE_NUMBER", "COUNTING"],
    "INTEGERS": ["INTEGER"],
    "FRACTIONS": ["FRACTION", "MIXED_NUMBER", "DENOMINATOR", "NUMERATOR"],
    "DECIMALS": ["DECIMAL"],
    "PERCENT": ["PERCENT", "SALES_TAX", "COMMISSION", "DISCOUNT", "INTEREST"],
    "RATIOS": ["RATIO", "RATE", "PROPORTION"],
    "ALGEBRA": ["ALGEBRA", "LANGUAGE", "EXPRESSION", "VARIABLE"],
    "EQUATIONS": ["EQUATION", "SOLVE", "SOLVING"],
    "POLYNOMIALS": ["POLYNOMIAL", "MONOMIAL", "EXPONENT", "FACTOR"],
    "GEOMETRY": ["ANGLE", "TRIANGLE", "RECTANGLE", "CIRCLE", "VOLUME",
                 "SURFACE_AREA", "PERIMETER", "PYTHAGOREAN", "TRAPEZOID", "GEOMETRY"],
    "GRAPHING": ["GRAPH", "COORDINATE", "SLOPE", "INTERCEPT", "LINEAR"],
    "PROPERTIES": ["PROPERTY", "PROPERTIES", "COMMUTATIVE", "ASSOCIATIVE",
                   "DISTRIBUTIVE", "IDENTITY", "INVERSE"],
    "NUMBER_THEORY": ["FACTOR", "MULTIPLE", "PRIME", "LCM", "GCF", "DIVISIBILITY"],
    "STATISTICS": ["AVERAGE", "PROBABILITY", "STATISTICS", "MEAN", "MEDIAN"],
    "MEASUREMENT": ["MEASUREMENT", "METRIC", "CONVERT"],
    "REAL_NUMBERS": ["RATIONAL", "IRRATIONAL", "REAL_NUMBER"],
    "ROOTS": ["SQUARE_ROOT", "ROOT", "RADICAL"],
    "SCIENTIFIC": ["SCIENTIFIC_NOTATION"],
}

# Operation keywords
_OPERATION_KEYWORDS = {
    "INTRO": ["INTRODUCTION", "VISUALIZE", "UNDERSTAND", "USE_THE_LANGUAGE", "USE_THE_RECTANGULAR"],
    "ADD": ["ADD"],
    "SUBTRACT": ["SUBTRACT"],
    "ADD_SUB": ["ADD_AND_SUBTRACT"],
    "MULTIPLY": ["MULTIPLY", "MULTIPLICATION"],
    "DIVIDE": ["DIVIDE", "DIVISION"],
    "MULT_DIV": ["MULTIPLY_AND_DIVIDE"],
    "SOLVE": ["SOLVE", "SOLVING"],
    "EVALUATE": ["EVALUATE", "SIMPLIFY", "TRANSLATE"],
}


def _classify_concept(concept_id: str, concept_title: str) -> dict:
    """Classify a concept by domain and operation based on its name."""
    name = concept_id.split(".")[-1]  # e.g., "ADD_WHOLE_NUMBERS"
    title_upper = concept_title.upper().replace(" ", "_")

    domains = set()
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in name or kw in title_upper:
                domains.add(domain)

    operations = set()
    for op, keywords in _OPERATION_KEYWORDS.items():
        for kw in keywords:
            if kw in name or kw in title_upper:
                operations.add(op)

    return {"domains": domains, "operations": operations, "name": name}


def _build_keyword_dependencies(concept_blocks: list[ConceptBlock]) -> dict:
    """
    Build prerequisite map using keyword analysis.
    Returns dict: concept_id -> list of prerequisite concept_ids.
    """
    # Classify all concepts
    classified = {}
    for block in concept_blocks:
        classified[block.concept_id] = {
            "block": block,
            "info": _classify_concept(block.concept_id, block.concept_title),
        }

    # Build index: find concepts by domain and operation
    by_domain = defaultdict(list)
    by_operation = defaultdict(list)
    for cid, data in classified.items():
        for d in data["info"]["domains"]:
            by_domain[d].append(cid)
        for o in data["info"]["operations"]:
            by_operation[o].append(cid)

    # Build prerequisite map
    prereq_map = {}
    id_lookup = {b.concept_id: b for b in concept_blocks}

    for block in concept_blocks:
        cid = block.concept_id
        info = classified[cid]["info"]
        prereqs = set()

        # Rule 1: Same-domain intro is prerequisite for operations
        if "INTRO" not in info["operations"]:
            for d in info["domains"]:
                for candidate in by_domain[d]:
                    if candidate == cid:
                        continue
                    candidate_info = classified[candidate]["info"]
                    if "INTRO" in candidate_info["operations"]:
                        # Only add if candidate is in an earlier or same chapter
                        if _is_earlier_section(id_lookup[candidate], block):
                            prereqs.add(candidate)

        # Rule 2: Operations hierarchy within same domain
        for d in info["domains"]:
            domain_concepts = [c for c in by_domain[d] if c != cid and _is_earlier_section(id_lookup[c], block)]

            if "SUBTRACT" in info["operations"] or "ADD_SUB" in info["operations"]:
                # Subtract requires Add in same domain
                for c in domain_concepts:
                    c_info = classified[c]["info"]
                    if "ADD" in c_info["operations"] and d in c_info["domains"]:
                        prereqs.add(c)

            if "MULTIPLY" in info["operations"] or "MULT_DIV" in info["operations"]:
                # Multiply requires Add in same domain (repeated addition)
                for c in domain_concepts:
                    c_info = classified[c]["info"]
                    if "ADD" in c_info["operations"] and d in c_info["domains"]:
                        prereqs.add(c)

            if "DIVIDE" in info["operations"]:
                # Divide requires Multiply and Subtract
                for c in domain_concepts:
                    c_info = classified[c]["info"]
                    if ("MULTIPLY" in c_info["operations"] or "SUBTRACT" in c_info["operations"]) and d in c_info["domains"]:
                        prereqs.add(c)

        # Rule 3: Higher-domain operations depend on lower-domain operations
        domain_hierarchy = [
            ("INTEGERS", "WHOLE_NUMBERS"),
            ("FRACTIONS", "WHOLE_NUMBERS"),
            ("DECIMALS", "WHOLE_NUMBERS"),
            ("PERCENT", "DECIMALS"),
            ("PERCENT", "FRACTIONS"),
            ("POLYNOMIALS", "ALGEBRA"),
        ]
        for higher, lower in domain_hierarchy:
            if higher in info["domains"]:
                for c in by_domain.get(lower, []):
                    if c == cid:
                        continue
                    c_info = classified[c]["info"]
                    # Find matching operation in lower domain
                    shared_ops = info["operations"] & c_info["operations"]
                    if shared_ops and _is_earlier_section(id_lookup[c], block):
                        prereqs.add(c)

        # Rule 4: Equation solving depends on expression evaluation
        if "SOLVE" in info["operations"] and "EQUATIONS" in info["domains"]:
            for c in by_operation.get("EVALUATE", []):
                if c != cid and _is_earlier_section(id_lookup[c], block):
                    prereqs.add(c)

        # Rule 5: Within same chapter, sequential sections with no other signal
        # get a dependency on the immediately previous section
        if not prereqs:
            prev = _find_previous_section(block, concept_blocks)
            if prev:
                prereqs.add(prev.concept_id)

        prereq_map[cid] = sorted(prereqs)

    # Remove transitive edges to keep graph minimal
    prereq_map = _remove_transitive_edges(prereq_map)

    return prereq_map


def _is_earlier_section(candidate: ConceptBlock, target: ConceptBlock) -> bool:
    """Check if candidate comes before target in book order."""
    c_key = _section_sort_key(candidate.section)
    t_key = _section_sort_key(target.section)
    return c_key < t_key


def _find_previous_section(block: ConceptBlock, all_blocks: list[ConceptBlock]) -> ConceptBlock:
    """Find the immediately preceding section in the same chapter."""
    same_chapter = [b for b in all_blocks if b.chapter == block.chapter and b.concept_id != block.concept_id]
    same_chapter.sort(key=lambda b: _section_sort_key(b.section))

    prev = None
    for b in same_chapter:
        if _section_sort_key(b.section) < _section_sort_key(block.section):
            prev = b
    return prev


def _remove_transitive_edges(prereq_map: dict) -> dict:
    """Remove edges that are already implied by transitivity."""
    def _all_ancestors(node, memo=None):
        if memo is None:
            memo = {}
        if node in memo:
            return memo[node]
        ancestors = set()
        for p in prereq_map.get(node, []):
            ancestors.add(p)
            ancestors |= _all_ancestors(p, memo)
        memo[node] = ancestors
        return ancestors

    memo = {}
    cleaned = {}
    for node, prereqs in prereq_map.items():
        direct = []
        for p in prereqs:
            # Check if p is already reachable through other prerequisites
            other_prereqs = [op for op in prereqs if op != p]
            reachable_through_others = set()
            for op in other_prereqs:
                reachable_through_others |= _all_ancestors(op, memo)
                reachable_through_others.add(op)
            if p not in reachable_through_others:
                direct.append(p)
        cleaned[node] = sorted(direct)
    return cleaned


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _map_to_edges(concept_blocks: list[ConceptBlock], prereq_map: dict) -> list[DependencyEdge]:
    """Convert a prereq_map dict to a list of DependencyEdge objects."""
    edges = []
    for block in concept_blocks:
        prereqs = prereq_map.get(block.concept_id, [])
        if isinstance(prereqs, set):
            prereqs = sorted(prereqs)
        edges.append(DependencyEdge(
            concept_id=block.concept_id,
            prerequisites=prereqs,
        ))
    return edges


def _section_sort_key(section_str: str) -> tuple:
    """Convert section string like '1.3' to a sortable tuple (1, 3)."""
    parts = section_str.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (999, 999)
