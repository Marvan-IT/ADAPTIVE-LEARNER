"""
Validator — validates each concept block for completeness and quality.

Checks:
  - Has meaningful content (word count thresholds)
  - Does not contain exercise text
  - Does not contain boilerplate
  - Concept ID follows correct format
  - Section is logically self-contained
"""

import re

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from extraction.domain_models import ConceptBlock, ValidationResult
from config import BOILERPLATE_PATTERNS, EXERCISE_SECTION_MARKERS


def validate_concept_block(block: ConceptBlock) -> ValidationResult:
    """
    Validate a single concept block.
    Returns a ValidationResult with status VALID or INVALID and any issues.
    """
    issues = []
    word_count = len(block.text.split())

    # Check: minimum content
    if word_count < 50:
        issues.append(f"EMPTY_CONTENT: Only {word_count} words (minimum 50)")

    # Check: concept_id format — book code may contain digits (e.g. ALG1, CALC1)
    id_pattern = re.compile(r"^[A-Z][A-Z0-9]*\.C\d+\.S\d+\.[A-Z0-9_]+$")
    if not id_pattern.match(block.concept_id):
        issues.append(f"INVALID_ID_FORMAT: '{block.concept_id}' does not match expected pattern")

    # Check: no exercise markers in text
    text_upper = block.text.upper()
    for marker in EXERCISE_SECTION_MARKERS:
        if marker.upper() in text_upper:
            issues.append(f"CONTAINS_EXERCISES: Found '{marker}' in concept text")

    # Check: no boilerplate in text
    for pattern in BOILERPLATE_PATTERNS:
        if re.search(pattern, block.text, re.IGNORECASE):
            issues.append("CONTAINS_BOILERPLATE: Found boilerplate pattern in text")
            break

    # Check: no exercise instruction patterns
    exercise_patterns = [
        r"In the following exercises",
        r"Practice Makes Perfect",
        r"Writing Exercises",
        r"Everyday Math",
    ]
    for pat in exercise_patterns:
        if re.search(pat, block.text, re.IGNORECASE):
            issues.append(f"CONTAINS_EXERCISES: Found '{pat}' pattern in text")

    # Check: text is not just a fragment
    if word_count > 0 and word_count < 20:
        issues.append(f"FRAGMENT: Text appears to be a fragment ({word_count} words)")

    # Check: has section number
    if not block.section:
        issues.append("MISSING_SECTION: No section number assigned")

    # Check: has chapter
    if not block.chapter:
        issues.append("MISSING_CHAPTER: No chapter number assigned")

    # Determine status
    status = "INVALID" if issues else "VALID"

    return ValidationResult(
        concept_id=block.concept_id,
        status=status,
        issues=issues,
    )


def validate_all_blocks(blocks: list[ConceptBlock]) -> list[ValidationResult]:
    """Validate all concept blocks and return results."""
    return [validate_concept_block(block) for block in blocks]


def get_validation_summary(results: list[ValidationResult]) -> dict:
    """Return summary statistics from validation results."""
    total = len(results)
    valid = sum(1 for r in results if r.status == "VALID")
    invalid = total - valid

    # Count issue types
    issue_counts = {}
    for r in results:
        for issue in r.issues:
            issue_type = issue.split(":")[0] if ":" in issue else issue
            issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1

    return {
        "total_blocks": total,
        "valid_blocks": valid,
        "invalid_blocks": invalid,
        "validation_rate": round(valid / total * 100, 1) if total > 0 else 0,
        "issue_counts": issue_counts,
    }
