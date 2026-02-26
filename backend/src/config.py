"""
Configuration for the ADA Hybrid Engine pipeline.
Contains all paths, API keys, book registry, and shared constants.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from backend directory
_backend_dir = Path(__file__).resolve().parent.parent
load_dotenv(_backend_dir / ".env")

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = _backend_dir.parent
BACKEND_DIR = _backend_dir
DATA_DIR = BACKEND_DIR / "data"
OUTPUT_DIR = BACKEND_DIR / "output"
CHROMA_DIR = OUTPUT_DIR / "chroma_db"
SRC_DIR = BACKEND_DIR / "src"

# ── API Keys ───────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_MODEL_MINI = os.getenv("OPENAI_MODEL_MINI", "gpt-4o-mini")
MATHPIX_APP_ID = os.getenv("MATHPIX_APP_ID", "")
MATHPIX_APP_KEY = os.getenv("MATHPIX_APP_KEY", "")

# ── Database ──────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postre2002@localhost:5432/AdaptiveLearner")

# ── Embedding ──────────────────────────────────────────────────────────
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# ── ChromaDB ───────────────────────────────────────────────────────────
CHROMA_COLLECTION_NAME = "openstax_concepts"

# ── Adaptive Learning Engine ────────────────────────────────────────────────
ADAPTIVE_ERROR_PENALTY_WEIGHT: float = 0.4   # Weight for error rate in confidence score
ADAPTIVE_HINT_PENALTY_WEIGHT: float = 0.2    # Weight for hint usage in confidence score

# ── Boilerplate patterns to strip (line-level) ─────────────────────────
BOILERPLATE_PATTERNS = [
    r"Access for free at openstax\.org",
    r"Access for free at OpenStax\.org",
    r"This content is available for free at",
]

# ── Exercise / non-instructional markers ───────────────────────────────
EXERCISE_SECTION_MARKERS = [
    "Practice Makes Perfect",
    "Everyday Math",
    "Writing Exercises",
    "Self Check",
]

CONTENT_EXCLUDE_MARKERS = [
    "BE PREPARED",
    "ACCESS ADDITIONAL ONLINE RESOURCES",
]

BACK_MATTER_MARKERS = [
    "CUMULATIVE REVIEW",
    "Answer Key",
    "Powers and Roots Tables",
    "Geometric Formulas",
]

# ── Mathpix OCR settings ──────────────────────────────────────────────
MATHPIX_DPI = 200          # Resolution for page rendering (balances quality vs size)
MATHPIX_RATE_LIMIT = 0.5   # Seconds between API requests

# ── Book-slug to book-code mapping ─────────────────────────────────────
BOOK_CODE_MAP = {
    "prealgebra": "PREALG",
    "elementary_algebra": "ELEMALG",
    "algebra_1": "ALG1",
    "intermediate_algebra": "INTERALG",
    "college_algebra_coreq": "COLALGCRQ",
    "college_algebra": "COLALG",
    "algebra_trigonometry": "ALGTRIG",
    "precalculus": "PRECALC",
    "calculus_1": "CALC1",
    "calculus_2": "CALC2",
    "calculus_3": "CALC3",
    "intro_statistics": "INSTATS",
    "statistics": "STATS",
    "business_statistics": "BUSTATS",
    "contemporary_math": "CONTMATH",
    "principles_data_science": "PDS",
}

# ── Book order (early → late) for cross-book guardrail ─────────────────
BOOK_ORDER = [
    "prealgebra",
    "elementary_algebra",
    "algebra_1",
    "intermediate_algebra",
    "college_algebra_coreq",
    "college_algebra",
    "algebra_trigonometry",
    "precalculus",
    "calculus_1",
    "calculus_2",
    "calculus_3",
    "intro_statistics",
    "statistics",
    "business_statistics",
    "contemporary_math",
    "principles_data_science",
]

# ── Book Registry ──────────────────────────────────────────────────────
# Each entry maps a book_code to its PDF-specific configuration.
# These values are discovered empirically by inspecting each PDF.

BOOK_REGISTRY = {
    "PREALG": {
        "book_code": "PREALG",
        "book_slug": "prealgebra",
        "pdf_filename": "prealgebra.pdf",
        "title": "Prealgebra 2e",
        "section_header_font": "RobotoSlab-Bold",
        "section_header_size_min": 14.0,
        "section_header_size_max": 14.6,
        "chapter_header_font": "RobotoSlab-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 16,  # 0-indexed; content starts at index 16
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "ELEMALG": {
        "book_code": "ELEMALG",
        "book_slug": "elementary_algebra",
        "pdf_filename": "elementary_algebra.pdf",
        "title": "Elementary Algebra 2e",
        "section_header_font": "RobotoSlab-Bold",
        "section_header_size_min": 14.0,
        "section_header_size_max": 14.6,
        "chapter_header_font": "RobotoSlab-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "INTERALG": {
        "book_code": "INTERALG",
        "book_slug": "intermediate_algebra",
        "pdf_filename": "intermediate_algebra.pdf",
        "title": "Intermediate Algebra 2e",
        "section_header_font": "RobotoSlab-Bold",
        "section_header_size_min": 14.0,
        "section_header_size_max": 14.6,
        "chapter_header_font": "RobotoSlab-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "COLALG": {
        "book_code": "COLALG",
        "book_slug": "college_algebra",
        "pdf_filename": "college_algebra.pdf",
        "title": "College Algebra 2e",
        "section_header_font": "RobotoSlab-Bold",
        "section_header_size_min": 14.0,
        "section_header_size_max": 14.6,
        "chapter_header_font": "RobotoSlab-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "COLALGCRQ": {
        "book_code": "COLALGCRQ",
        "book_slug": "college_algebra_coreq",
        "pdf_filename": "college_algebra_corequisite.pdf",
        "title": "College Algebra with Corequisite Support 2e",
        "section_header_font": "RobotoSlab-Bold",
        "section_header_size_min": 14.0,
        "section_header_size_max": 14.6,
        "chapter_header_font": "RobotoSlab-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "ALGTRIG": {
        "book_code": "ALGTRIG",
        "book_slug": "algebra_trigonometry",
        "pdf_filename": "algebra_trigonometry.pdf",
        "title": "Algebra and Trigonometry 2e",
        "section_header_font": "RobotoSlab-Bold",
        "section_header_size_min": 14.0,
        "section_header_size_max": 14.6,
        "chapter_header_font": "RobotoSlab-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "PRECALC": {
        "book_code": "PRECALC",
        "book_slug": "precalculus",
        "pdf_filename": "precalculus.pdf",
        "title": "Precalculus 2e",
        "section_header_font": "RobotoSlab-Bold",
        "section_header_size_min": 14.0,
        "section_header_size_max": 14.6,
        "chapter_header_font": "RobotoSlab-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "CALC1": {
        "book_code": "CALC1",
        "book_slug": "calculus_1",
        "pdf_filename": "calculus_1.pdf",
        "title": "Calculus Volume 1",
        "section_header_font": "LiberationSans-Bold",
        "section_header_size_min": 13.8,
        "section_header_size_max": 14.4,
        "chapter_header_font": "LiberationSans-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "CALC2": {
        "book_code": "CALC2",
        "book_slug": "calculus_2",
        "pdf_filename": "calculus_2.pdf",
        "title": "Calculus Volume 2",
        "section_header_font": "LiberationSans-Bold",
        "section_header_size_min": 13.8,
        "section_header_size_max": 14.4,
        "chapter_header_font": "LiberationSans-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "CALC3": {
        "book_code": "CALC3",
        "book_slug": "calculus_3",
        "pdf_filename": "calculus_3.pdf",
        "title": "Calculus Volume 3",
        "section_header_font": "LiberationSans-Bold",
        "section_header_size_min": 13.8,
        "section_header_size_max": 14.4,
        "chapter_header_font": "LiberationSans-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "INSTATS": {
        "book_code": "INSTATS",
        "book_slug": "intro_statistics",
        "pdf_filename": "intro_statistics.pdf",
        "title": "Introductory Statistics 2e",
        "section_header_font": "RobotoSlab-Bold",
        "section_header_size_min": 14.0,
        "section_header_size_max": 14.6,
        "chapter_header_font": "RobotoSlab-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "STATS": {
        "book_code": "STATS",
        "book_slug": "statistics",
        "pdf_filename": "statistics.pdf",
        "title": "Introductory Statistics",
        "section_header_font": "LiberationSans-Bold",
        "section_header_size_min": 13.8,
        "section_header_size_max": 14.4,
        "chapter_header_font": "LiberationSans-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "BUSTATS": {
        "book_code": "BUSTATS",
        "book_slug": "business_statistics",
        "pdf_filename": "business_statistics.pdf",
        "title": "Introductory Business Statistics 2e",
        "section_header_font": "RobotoSlab-Bold",
        "section_header_size_min": 14.0,
        "section_header_size_max": 14.6,
        "chapter_header_font": "RobotoSlab-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "CONTMATH": {
        "book_code": "CONTMATH",
        "book_slug": "contemporary_math",
        "pdf_filename": "contemporary_maths.pdf",
        "title": "Contemporary Mathematics",
        "section_header_font": "RobotoSlab-Bold",
        "section_header_size_min": 14.0,
        "section_header_size_max": 14.6,
        "chapter_header_font": "RobotoSlab-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "ALG1": {
        "book_code": "ALG1",
        "book_slug": "algebra_1",
        "pdf_filename": "algebra_1.pdf",
        "title": "Algebra 1",
        "section_header_font": "RobotoSlab-Bold",
        "section_header_size_min": 14.0,
        "section_header_size_max": 14.6,
        "chapter_header_font": "RobotoSlab-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 17.5,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
    "PDS": {
        "book_code": "PDS",
        "book_slug": "principles_data_science",
        "pdf_filename": "principles_data_science.pdf",
        "title": "Principles of Data Science",
        "section_header_font": "RobotoCondensed-Bold",
        "section_header_size_min": 15.0,
        "section_header_size_max": 16.0,
        "chapter_header_font": "RobotoCondensed-Bold",
        "chapter_header_size_min": 17.0,
        "chapter_header_size_max": 18.0,
        "section_pattern": r"^(\d+)\.(\d+)\s+(.+)",
        "front_matter_end_page": 14,
        "exercise_marker_pattern": r"Section\s+\d+\.\d+\s+Exercises",
    },
}


def get_book_config(book_code: str) -> dict:
    """Get configuration for a book by its code."""
    if book_code not in BOOK_REGISTRY:
        raise ValueError(f"Unknown book code: {book_code}. Available: {list(BOOK_REGISTRY.keys())}")
    return BOOK_REGISTRY[book_code]


def get_pdf_path(book_code: str) -> Path:
    """Get the full path to a book's PDF file."""
    config = get_book_config(book_code)
    return DATA_DIR / config["pdf_filename"]
