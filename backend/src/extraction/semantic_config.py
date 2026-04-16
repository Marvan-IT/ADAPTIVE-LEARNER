"""
Semantic config loader — loads subject-specific patterns from YAML.

Usage:
    config = load_semantic_config("mathematics")
    # config["noise_headings"]       → list of compiled re.Pattern
    # config["worked_example_start"] → list of compiled re.Pattern
    # config["consumers"]            → list of consumer function names
"""

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Config directory: backend/config/semantic_patterns/
_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "semantic_patterns"


def _load_yaml(path: Path) -> dict:
    """Load a YAML file, return empty dict if missing."""
    if not path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return {}


def _compile_patterns(raw_list: list[str] | None) -> list[re.Pattern]:
    """Compile a list of regex strings into Pattern objects."""
    if not raw_list:
        return []
    compiled = []
    for pat_str in raw_list:
        try:
            compiled.append(re.compile(pat_str, re.IGNORECASE))
        except re.error as exc:
            logger.warning("Invalid regex pattern %r: %s", pat_str, exc)
    return compiled


def load_semantic_config(subject: str) -> dict[str, Any]:
    """
    Load and merge base + subject-specific semantic patterns.

    Args:
        subject: Subject name (e.g., "mathematics", "nursing").
                 Falls back to "_unknown" if subject YAML not found.

    Returns:
        Dict with compiled patterns:
          - "noise_headings": list[re.Pattern]
          - "worked_example_start": list[re.Pattern]
          - "solution_continuation": list[re.Pattern]
          - "try_it_continuation": list[re.Pattern]
          - "exercise_group_start": list[re.Pattern]
          - "feature_box_start": list[re.Pattern]
          - "how_to_start": list[re.Pattern]
          - "chapter_review_start": list[re.Pattern]
          - "always_drop_lines": list[re.Pattern]
          - "consumers": list[str]
          - "subject": str
    """
    # Load base config
    base = _load_yaml(_CONFIG_DIR / "_base.yaml")

    # Load subject-specific config
    subject_path = _CONFIG_DIR / f"{subject}.yaml"
    if subject_path.exists():
        subject_data = _load_yaml(subject_path)
    else:
        logger.warning(
            "No semantic config for subject '%s' — falling back to _unknown",
            subject,
        )
        subject_data = _load_yaml(_CONFIG_DIR / "_unknown.yaml")
        subject = "_unknown"

    # Merge: subject overrides base on key conflict
    # For list keys (noise_headings, etc.), concatenate base + subject
    merged: dict[str, Any] = {}

    # List keys: concatenate
    list_keys = [
        "noise_headings", "always_drop_lines", "chapter_review_start",
        "figure_start", "table_start",
        "worked_example_start", "solution_continuation", "try_it_continuation",
        "exercise_group_start", "feature_box_start", "how_to_start",
        "format_b_feature_box_start",
    ]
    for key in list_keys:
        base_list = base.get(key, []) or []
        subj_list = subject_data.get(key, []) or []
        merged[key] = base_list + subj_list

    # Scalar keys: subject overrides base
    for key in ["running_page_header_detection"]:
        merged[key] = subject_data.get(key, base.get(key))

    # Consumers: subject-specific only (no base consumers)
    merged["consumers"] = subject_data.get("consumers", ["consume_prose_run"])

    # Compile all pattern lists
    compiled: dict[str, Any] = {"subject": subject}
    for key in list_keys:
        compiled[key] = _compile_patterns(merged.get(key, []))
    compiled["consumers"] = merged["consumers"]
    compiled["running_page_header_detection"] = merged.get("running_page_header_detection")

    logger.info(
        "Loaded semantic config for '%s': %d noise patterns, %d consumers",
        subject,
        len(compiled.get("noise_headings", [])),
        len(compiled["consumers"]),
    )
    return compiled


def get_subject_for_book(book_slug: str) -> str:
    """Look up subject from books.yaml for a given book slug."""
    try:
        import yaml
        books_yaml = Path(__file__).resolve().parents[2] / "books.yaml"
        if books_yaml.exists():
            data = yaml.safe_load(books_yaml.read_text(encoding="utf-8"))
            for book in data.get("books", []):
                if book.get("book_slug") == book_slug:
                    return book.get("subject", "_unknown")
    except Exception as exc:
        logger.warning("Failed to read books.yaml for subject lookup: %s", exc)
    return "_unknown"
