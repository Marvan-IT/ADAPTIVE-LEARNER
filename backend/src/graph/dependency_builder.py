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

import re
from collections import defaultdict

import sys, os
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
            print(f"  Falling back to keyword-based builder")

    # Fallback: keyword-based builder
    print(f"  Using keyword-based dependency builder for {book_slug}")
    prereq_map = _build_keyword_dependencies(concept_blocks)
    return _map_to_edges(concept_blocks, prereq_map)


# ═══════════════════════════════════════════════════════════════════════
# EXPERT GRAPHS — hand-curated for known books
# ═══════════════════════════════════════════════════════════════════════

def _get_expert_graph(book_slug: str) -> dict:
    """Return expert prerequisite map for a known book, or None."""
    registry = {
        "prealgebra": _prealgebra_expert_graph,
    }
    builder = registry.get(book_slug)
    return builder() if builder else None


def _prealgebra_expert_graph() -> dict:
    """
    Expert-designed dependency graph for Prealgebra 2e.

    Design rationale:
    - Ch1: Operations branch (Add→Subtract, Add→Multiply, Subtract+Multiply→Divide)
    - Ch2: Algebra branch (Language→Expressions→Equations) PARALLEL to
            Number theory branch (Divide→Factors→Prime/LCM)
    - Ch3: Integer operations follow same hierarchy as whole numbers
    - Ch4: Fraction mult/div branch PARALLEL to fraction add/sub branch;
            add/sub with different denom requires LCM from number theory
    - Ch5: Decimals depend on place value; decimal ops depend on whole-number ops
    - Ch6: Percents connect fractions+decimals; proportions connect ratios+equations
    - Ch7: Properties depend on relevant number systems
    - Ch8: Linear equations build on Ch2 equations + Ch3 integers + Ch7 properties
    - Ch9: Geometry uses equations + square roots; formula solving uses Ch8
    - Ch10: Polynomials use expressions + integer ops + distributive property
    - Ch11: Graphing uses coordinates (integers) + equation solving
    """
    P = "PREALG"
    return {
        # ── Chapter 1: Whole Numbers ────────────────────────────────
        # Operations branch: Add and Subtract are parallel from Intro
        # Multiply branches from Add; Divide requires both Subtract and Multiply
        f"{P}.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS": [],
        f"{P}.C1.S2.ADD_WHOLE_NUMBERS": [
            f"{P}.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS",
        ],
        f"{P}.C1.S3.SUBTRACT_WHOLE_NUMBERS": [
            f"{P}.C1.S2.ADD_WHOLE_NUMBERS",
        ],
        f"{P}.C1.S4.MULTIPLY_WHOLE_NUMBERS": [
            f"{P}.C1.S2.ADD_WHOLE_NUMBERS",               # multiplication is repeated addition
        ],
        f"{P}.C1.S5.DIVIDE_WHOLE_NUMBERS": [
            f"{P}.C1.S3.SUBTRACT_WHOLE_NUMBERS",           # long division uses subtraction
            f"{P}.C1.S4.MULTIPLY_WHOLE_NUMBERS",           # division is inverse of multiplication
        ],

        # ── Chapter 2: Language of Algebra ──────────────────────────
        # Algebra branch: Language → Expressions → Equations
        # Number theory branch: Divide → Factors → Prime/LCM  (PARALLEL)
        f"{P}.C2.S1.USE_THE_LANGUAGE_OF_ALGEBRA": [
            f"{P}.C1.S5.DIVIDE_WHOLE_NUMBERS",             # uses all four operations
        ],
        f"{P}.C2.S2.EVALUATE_SIMPLIFY_AND_TRANSLATE_EXPRESSIONS": [
            f"{P}.C2.S1.USE_THE_LANGUAGE_OF_ALGEBRA",
        ],
        f"{P}.C2.S3.SOLVING_EQUATIONS_USING_THE_SUBTRACTION_AND_ADDITION_PROPERTIES_OF_EQUALITY": [
            f"{P}.C2.S2.EVALUATE_SIMPLIFY_AND_TRANSLATE_EXPRESSIONS",
        ],
        f"{P}.C2.S4.FIND_MULTIPLES_AND_FACTORS": [
            f"{P}.C1.S5.DIVIDE_WHOLE_NUMBERS",             # factors require division; PARALLEL to algebra branch
        ],
        f"{P}.C2.S5.PRIME_FACTORIZATION_AND_THE_LEAST_COMMON_MULTIPLE": [
            f"{P}.C2.S4.FIND_MULTIPLES_AND_FACTORS",
        ],

        # ── Chapter 3: Integers ─────────────────────────────────────
        # Integer add/sub branch PARALLEL to integer mult/div branch
        f"{P}.C3.S1.INTRODUCTION_TO_INTEGERS": [
            f"{P}.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS",    # extends number line to negatives
        ],
        f"{P}.C3.S2.ADD_INTEGERS": [
            f"{P}.C3.S1.INTRODUCTION_TO_INTEGERS",
            f"{P}.C1.S3.SUBTRACT_WHOLE_NUMBERS",           # adding negatives uses subtraction concept
        ],
        f"{P}.C3.S3.SUBTRACT_INTEGERS": [
            f"{P}.C3.S2.ADD_INTEGERS",                     # a-b = a+(-b)
        ],
        f"{P}.C3.S4.MULTIPLY_AND_DIVIDE_INTEGERS": [
            f"{P}.C3.S1.INTRODUCTION_TO_INTEGERS",         # need integer concept
            f"{P}.C1.S5.DIVIDE_WHOLE_NUMBERS",             # need whole-number mult/div rules
        ],
        f"{P}.C3.S5.SOLVE_EQUATIONS_USING_INTEGERS_THE_DIVISION_PROPERTY_OF_EQUALITY": [
            f"{P}.C3.S3.SUBTRACT_INTEGERS",                # integer add/sub branch
            f"{P}.C3.S4.MULTIPLY_AND_DIVIDE_INTEGERS",     # integer mult/div branch
            f"{P}.C2.S3.SOLVING_EQUATIONS_USING_THE_SUBTRACTION_AND_ADDITION_PROPERTIES_OF_EQUALITY",  # equation solving
        ],

        # ── Chapter 4: Fractions ────────────────────────────────────
        # Mult/div fractions branch PARALLEL to add/sub fractions branch
        # Add/sub with different denom requires LCM from number theory
        f"{P}.C4.S1.VISUALIZE_FRACTIONS": [
            f"{P}.C1.S5.DIVIDE_WHOLE_NUMBERS",             # fractions represent division
        ],
        f"{P}.C4.S2.MULTIPLY_AND_DIVIDE_FRACTIONS": [
            f"{P}.C4.S1.VISUALIZE_FRACTIONS",
        ],
        f"{P}.C4.S3.MULTIPLY_AND_DIVIDE_MIXED_NUMBERS_AND_COMPLEX_FRACTIONS": [
            f"{P}.C4.S2.MULTIPLY_AND_DIVIDE_FRACTIONS",
        ],
        f"{P}.C4.S4.ADD_AND_SUBTRACT_FRACTIONS_WITH_COMMON_DENOMINATORS": [
            f"{P}.C4.S1.VISUALIZE_FRACTIONS",              # PARALLEL to mult/div branch
        ],
        f"{P}.C4.S5.ADD_AND_SUBTRACT_FRACTIONS_WITH_DIFFERENT_DENOMINATORS": [
            f"{P}.C4.S4.ADD_AND_SUBTRACT_FRACTIONS_WITH_COMMON_DENOMINATORS",
            f"{P}.C2.S5.PRIME_FACTORIZATION_AND_THE_LEAST_COMMON_MULTIPLE",  # LCD from LCM
        ],
        f"{P}.C4.S6.ADD_AND_SUBTRACT_MIXED_NUMBERS": [
            f"{P}.C4.S5.ADD_AND_SUBTRACT_FRACTIONS_WITH_DIFFERENT_DENOMINATORS",
        ],
        f"{P}.C4.S7.SOLVE_EQUATIONS_WITH_FRACTIONS": [
            f"{P}.C4.S2.MULTIPLY_AND_DIVIDE_FRACTIONS",    # mult/div branch
            f"{P}.C4.S5.ADD_AND_SUBTRACT_FRACTIONS_WITH_DIFFERENT_DENOMINATORS",  # add/sub branch
            f"{P}.C2.S3.SOLVING_EQUATIONS_USING_THE_SUBTRACTION_AND_ADDITION_PROPERTIES_OF_EQUALITY",  # equation solving
        ],

        # ── Chapter 5: Decimals ─────────────────────────────────────
        f"{P}.C5.S1.DECIMALS": [
            f"{P}.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS",    # place value extends to decimals
        ],
        f"{P}.C5.S2.DECIMAL_OPERATIONS": [
            f"{P}.C5.S1.DECIMALS",
            f"{P}.C1.S5.DIVIDE_WHOLE_NUMBERS",             # decimal ops mirror whole-number ops
        ],
        f"{P}.C5.S3.DECIMALS_AND_FRACTIONS": [
            f"{P}.C5.S1.DECIMALS",
            f"{P}.C4.S1.VISUALIZE_FRACTIONS",              # converting between representations
        ],
        f"{P}.C5.S4.SOLVE_EQUATIONS_WITH_DECIMALS": [
            f"{P}.C5.S2.DECIMAL_OPERATIONS",
            f"{P}.C2.S3.SOLVING_EQUATIONS_USING_THE_SUBTRACTION_AND_ADDITION_PROPERTIES_OF_EQUALITY",
        ],
        f"{P}.C5.S5.AVERAGES_AND_PROBABILITY": [
            f"{P}.C5.S2.DECIMAL_OPERATIONS",               # averages use division of decimals
        ],
        f"{P}.C5.S6.RATIOS_AND_RATE": [
            f"{P}.C5.S2.DECIMAL_OPERATIONS",
            f"{P}.C4.S1.VISUALIZE_FRACTIONS",              # ratios are fractions
        ],
        f"{P}.C5.S7.SIMPLIFY_AND_USE_SQUARE_ROOTS": [
            f"{P}.C1.S4.MULTIPLY_WHOLE_NUMBERS",           # perfect squares
            f"{P}.C5.S1.DECIMALS",                         # decimal approximation of roots
        ],

        # ── Chapter 6: Percents ─────────────────────────────────────
        # Sales tax and Interest are PARALLEL branches from general percent
        f"{P}.C6.S1.UNDERSTAND_PERCENT": [
            f"{P}.C5.S3.DECIMALS_AND_FRACTIONS",           # percents connect fractions and decimals
        ],
        f"{P}.C6.S2.SOLVE_GENERAL_APPLICATIONS_OF_PERCENT": [
            f"{P}.C6.S1.UNDERSTAND_PERCENT",
            f"{P}.C2.S3.SOLVING_EQUATIONS_USING_THE_SUBTRACTION_AND_ADDITION_PROPERTIES_OF_EQUALITY",
        ],
        f"{P}.C6.S3.SOLVE_SALES_TAX_COMMISSION_AND_DISCOUNT_APPLICATIONS": [
            f"{P}.C6.S2.SOLVE_GENERAL_APPLICATIONS_OF_PERCENT",
        ],
        f"{P}.C6.S4.SOLVE_SIMPLE_INTEREST_APPLICATIONS": [
            f"{P}.C6.S2.SOLVE_GENERAL_APPLICATIONS_OF_PERCENT",  # PARALLEL to sales tax
        ],
        f"{P}.C6.S5.SOLVE_PROPORTIONS_AND_THEIR_APPLICATIONS": [
            f"{P}.C5.S6.RATIOS_AND_RATE",                 # proportions extend ratios
            f"{P}.C2.S3.SOLVING_EQUATIONS_USING_THE_SUBTRACTION_AND_ADDITION_PROPERTIES_OF_EQUALITY",
        ],

        # ── Chapter 7: Properties of Real Numbers ───────────────────
        f"{P}.C7.S1.RATIONAL_AND_IRRATIONAL_NUMBERS": [
            f"{P}.C5.S7.SIMPLIFY_AND_USE_SQUARE_ROOTS",   # irrational numbers
            f"{P}.C4.S1.VISUALIZE_FRACTIONS",              # rational numbers
            f"{P}.C3.S1.INTRODUCTION_TO_INTEGERS",         # integers as rational
        ],
        f"{P}.C7.S2.COMMUTATIVE_AND_ASSOCIATIVE_PROPERTIES": [
            f"{P}.C2.S1.USE_THE_LANGUAGE_OF_ALGEBRA",      # properties use algebraic notation
        ],
        f"{P}.C7.S3.DISTRIBUTIVE_PROPERTY": [
            f"{P}.C2.S2.EVALUATE_SIMPLIFY_AND_TRANSLATE_EXPRESSIONS",  # distributing in expressions
        ],
        f"{P}.C7.S4.PROPERTIES_OF_IDENTITY_INVERSES_AND_ZERO": [
            f"{P}.C3.S1.INTRODUCTION_TO_INTEGERS",         # additive inverse = negatives
            f"{P}.C4.S1.VISUALIZE_FRACTIONS",              # multiplicative inverse = reciprocal
        ],
        f"{P}.C7.S5.SYSTEMS_OF_MEASUREMENT": [
            f"{P}.C5.S2.DECIMAL_OPERATIONS",               # metric conversions use decimals
            f"{P}.C4.S2.MULTIPLY_AND_DIVIDE_FRACTIONS",    # US/imperial uses fractions
        ],

        # ── Chapter 8: Solving Linear Equations ─────────────────────
        f"{P}.C8.S1.SOLVE_EQUATIONS_USING_THE_SUBTRACTION_AND_ADDITION_PROPERTIES_OF_EQUALITY": [
            f"{P}.C2.S3.SOLVING_EQUATIONS_USING_THE_SUBTRACTION_AND_ADDITION_PROPERTIES_OF_EQUALITY",
            f"{P}.C3.S3.SUBTRACT_INTEGERS",                # equations with integer solutions
        ],
        f"{P}.C8.S2.SOLVE_EQUATIONS_USING_THE_DIVISION_AND_MULTIPLICATION_PROPERTIES_OF_EQUALITY": [
            f"{P}.C8.S1.SOLVE_EQUATIONS_USING_THE_SUBTRACTION_AND_ADDITION_PROPERTIES_OF_EQUALITY",
            f"{P}.C3.S4.MULTIPLY_AND_DIVIDE_INTEGERS",
        ],
        f"{P}.C8.S3.SOLVE_EQUATIONS_WITH_VARIABLES_AND_CONSTANTS_ON_BOTH_SIDES": [
            f"{P}.C8.S2.SOLVE_EQUATIONS_USING_THE_DIVISION_AND_MULTIPLICATION_PROPERTIES_OF_EQUALITY",
            f"{P}.C7.S3.DISTRIBUTIVE_PROPERTY",
        ],
        f"{P}.C8.S4.SOLVE_EQUATIONS_WITH_FRACTION_OR_DECIMAL_COEFFICIENTS": [
            f"{P}.C8.S3.SOLVE_EQUATIONS_WITH_VARIABLES_AND_CONSTANTS_ON_BOTH_SIDES",
            f"{P}.C4.S2.MULTIPLY_AND_DIVIDE_FRACTIONS",    # clearing fractions
            f"{P}.C5.S2.DECIMAL_OPERATIONS",               # clearing decimals
        ],

        # ── Chapter 9: Math Models and Geometry ─────────────────────
        f"{P}.C9.S1.USE_A_PROBLEM_SOLVING_STRATEGY": [
            f"{P}.C8.S2.SOLVE_EQUATIONS_USING_THE_DIVISION_AND_MULTIPLICATION_PROPERTIES_OF_EQUALITY",
        ],
        f"{P}.C9.S2.SOLVE_MONEY_APPLICATIONS": [
            f"{P}.C9.S1.USE_A_PROBLEM_SOLVING_STRATEGY",
            f"{P}.C5.S2.DECIMAL_OPERATIONS",               # money = decimals
        ],
        f"{P}.C9.S3.USE_PROPERTIES_OF_ANGLES_TRIANGLES_AND_THE_PYTHAGOREAN_THEOREM": [
            f"{P}.C8.S2.SOLVE_EQUATIONS_USING_THE_DIVISION_AND_MULTIPLICATION_PROPERTIES_OF_EQUALITY",
            f"{P}.C5.S7.SIMPLIFY_AND_USE_SQUARE_ROOTS",    # Pythagorean theorem
        ],
        f"{P}.C9.S4.USE_PROPERTIES_OF_RECTANGLES_TRIANGLES_AND_TRAPEZOIDS": [
            f"{P}.C9.S3.USE_PROPERTIES_OF_ANGLES_TRIANGLES_AND_THE_PYTHAGOREAN_THEOREM",
        ],
        f"{P}.C9.S5.SOLVE_GEOMETRY_APPLICATIONS_CIRCLES_AND_IRREGULAR_FIGURES": [
            f"{P}.C9.S4.USE_PROPERTIES_OF_RECTANGLES_TRIANGLES_AND_TRAPEZOIDS",
            f"{P}.C5.S2.DECIMAL_OPERATIONS",               # pi calculations need decimals
        ],
        f"{P}.C9.S6.SOLVE_GEOMETRY_APPLICATIONS_VOLUME_AND_SURFACE_AREA": [
            f"{P}.C9.S5.SOLVE_GEOMETRY_APPLICATIONS_CIRCLES_AND_IRREGULAR_FIGURES",
        ],
        f"{P}.C9.S7.SOLVE_A_FORMULA_FOR_A_SPECIFIC_VARIABLE": [
            f"{P}.C8.S3.SOLVE_EQUATIONS_WITH_VARIABLES_AND_CONSTANTS_ON_BOTH_SIDES",
        ],

        # ── Chapter 10: Polynomials ─────────────────────────────────
        # Add/sub polys and exponent rules are PARALLEL; converge at multiply polys
        f"{P}.C10.S1.ADD_AND_SUBTRACT_POLYNOMIALS": [
            f"{P}.C2.S2.EVALUATE_SIMPLIFY_AND_TRANSLATE_EXPRESSIONS",
            f"{P}.C3.S3.SUBTRACT_INTEGERS",                # integer coefficients
        ],
        f"{P}.C10.S2.USE_MULTIPLICATION_PROPERTIES_OF_EXPONENTS": [
            f"{P}.C2.S2.EVALUATE_SIMPLIFY_AND_TRANSLATE_EXPRESSIONS",  # PARALLEL to poly add/sub
        ],
        f"{P}.C10.S3.MULTIPLY_POLYNOMIALS": [
            f"{P}.C10.S1.ADD_AND_SUBTRACT_POLYNOMIALS",
            f"{P}.C10.S2.USE_MULTIPLICATION_PROPERTIES_OF_EXPONENTS",
            f"{P}.C7.S3.DISTRIBUTIVE_PROPERTY",            # FOIL method = distributive
        ],
        f"{P}.C10.S4.DIVIDE_MONOMIALS": [
            f"{P}.C10.S2.USE_MULTIPLICATION_PROPERTIES_OF_EXPONENTS",
        ],
        f"{P}.C10.S5.INTEGER_EXPONENTS_AND_SCIENTIFIC_NOTATION": [
            f"{P}.C10.S4.DIVIDE_MONOMIALS",
            f"{P}.C3.S1.INTRODUCTION_TO_INTEGERS",         # negative exponents
            f"{P}.C5.S1.DECIMALS",                         # scientific notation uses decimals
        ],
        f"{P}.C10.S6.INTRODUCTION_TO_FACTORING_POLYNOMIALS": [
            f"{P}.C10.S3.MULTIPLY_POLYNOMIALS",            # factoring reverses multiplication
            f"{P}.C2.S4.FIND_MULTIPLES_AND_FACTORS",       # factor concept
        ],

        # ── Chapter 11: Graphs ──────────────────────────────────────
        # Intercepts and slope are PARALLEL branches from graphing linear equations
        f"{P}.C11.S1.USE_THE_RECTANGULAR_COORDINATE_SYSTEM": [
            f"{P}.C3.S1.INTRODUCTION_TO_INTEGERS",         # all four quadrants need negatives
        ],
        f"{P}.C11.S2.GRAPHING_LINEAR_EQUATIONS": [
            f"{P}.C11.S1.USE_THE_RECTANGULAR_COORDINATE_SYSTEM",
            f"{P}.C8.S2.SOLVE_EQUATIONS_USING_THE_DIVISION_AND_MULTIPLICATION_PROPERTIES_OF_EQUALITY",
        ],
        f"{P}.C11.S3.GRAPHING_WITH_INTERCEPTS": [
            f"{P}.C11.S2.GRAPHING_LINEAR_EQUATIONS",
        ],
        f"{P}.C11.S4.UNDERSTAND_SLOPE_OF_A_LINE": [
            f"{P}.C11.S2.GRAPHING_LINEAR_EQUATIONS",
            f"{P}.C4.S1.VISUALIZE_FRACTIONS",              # slope = rise/run = fraction
        ],
    }


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
