"""
Data models for the ADA Hybrid Engine pipeline.
All structures used across the extraction, graph, storage, and validation modules.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ── Page-Level Models ──────────────────────────────────────────────────

@dataclass
class FontSpan:
    """A single text span with font metadata from a PDF page."""
    font: str
    size: float
    text: str
    bbox: tuple  # (x0, y0, x1, y1)


@dataclass
class PageText:
    """Raw extracted data from a single PDF page."""
    page_index: int          # 0-indexed
    page_number: int         # 1-indexed (page_index + 1)
    raw_text: str
    font_spans: list[FontSpan] = field(default_factory=list)
    image_xrefs: list[int] = field(default_factory=list)


# ── Section Boundary Model ─────────────────────────────────────────────

@dataclass
class SectionBoundary:
    """Detected start/end of a numbered instructional section."""
    chapter_number: int
    section_in_chapter: int
    section_number: str          # e.g., "1.1"
    section_title: str           # e.g., "Introduction to Whole Numbers"
    start_page_index: int        # page index where section header appears
    end_page_index: int          # page index where exercises/next section begins
    header_char_offset: int = 0  # character offset of header on start page


# ── Concept Block Model ────────────────────────────────────────────────

@dataclass
class ConceptBlock:
    """ONE instructional section = ONE concept block."""
    concept_id: str              # e.g., "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS"
    concept_title: str           # e.g., "Introduction to Whole Numbers"
    book_slug: str               # e.g., "prealgebra"
    book: str                    # e.g., "Prealgebra 2e"
    chapter: str                 # e.g., "1"
    section: str                 # e.g., "1.1"
    text: str                    # Cleaned instructional explanation
    latex: list[str] = field(default_factory=list)
    source_pages: list[int] = field(default_factory=list)  # 1-indexed page numbers

    def to_dict(self) -> dict:
        return {
            "concept_id": self.concept_id,
            "concept_title": self.concept_title,
            "book_slug": self.book_slug,
            "book": self.book,
            "chapter": self.chapter,
            "section": self.section,
            "text": self.text,
            "latex": self.latex,
            "source_pages": self.source_pages,
        }


# ── Dependency Edge Model ──────────────────────────────────────────────

@dataclass
class DependencyEdge:
    """A prerequisite relationship between two concepts."""
    concept_id: str              # target concept
    prerequisites: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "concept_id": self.concept_id,
            "prerequisites": self.prerequisites,
        }


# ── Validation Model ──────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """Validation status for a single concept block."""
    concept_id: str
    status: str                  # "VALID" or "INVALID"
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "concept_id": self.concept_id,
            "status": self.status,
            "issues": self.issues,
        }


# ── Image Models ───────────────────────────────────────────────────────

# ── Pipeline Output Model ─────────────────────────────────────────────

@dataclass
class PipelineOutput:
    """Complete output of the pipeline for one book."""
    concept_blocks: list[ConceptBlock] = field(default_factory=list)
    dependency_edges: list[DependencyEdge] = field(default_factory=list)
    validation_report: list[ValidationResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "concept_blocks": [b.to_dict() for b in self.concept_blocks],
            "dependency_edges": [e.to_dict() for e in self.dependency_edges],
            "validation_report": [v.to_dict() for v in self.validation_report],
        }
