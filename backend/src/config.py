"""
Configuration for the Adaptive Learner Hybrid Engine pipeline.
Contains all paths, API keys, book registry, and shared constants.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import yaml as _yaml
from pydantic import BaseModel

# Load .env from backend directory
_backend_dir = Path(__file__).resolve().parent.parent
load_dotenv(_backend_dir / ".env")

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = _backend_dir.parent
BACKEND_DIR = _backend_dir
DATA_DIR = BACKEND_DIR / "data"
OUTPUT_DIR = BACKEND_DIR / "output"
SRC_DIR = BACKEND_DIR / "src"

# ── API Keys ───────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_MODEL_MINI = os.getenv("OPENAI_MODEL_MINI", "gpt-4o-mini")
MATHPIX_APP_ID = os.getenv("MATHPIX_APP_ID", "")
MATHPIX_APP_KEY = os.getenv("MATHPIX_APP_KEY", "")

# ── Database ──────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
import logging as _cfg_log
_cfg_log.getLogger(__name__).info("Starting with ENVIRONMENT=%s", ENVIRONMENT)

# ── JWT ───────────────────────────────────────────────────────────────
JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
if not JWT_SECRET_KEY and ENVIRONMENT != "production":
    import secrets as _secrets
    JWT_SECRET_KEY = _secrets.token_hex(32)
    import logging as _cfg_logging
    _cfg_logging.getLogger(__name__).warning(
        "JWT_SECRET_KEY not set — generated random key for dev: %s...", JWT_SECRET_KEY[:8]
    )
if not JWT_SECRET_KEY and ENVIRONMENT == "production":
    raise ValueError("JWT_SECRET_KEY is required in production — set it in .env or environment")
JWT_ALGORITHM: str = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

# ── API Secret Key (generated if missing in dev) ─────────────────────
API_SECRET_KEY: str = os.getenv("API_SECRET_KEY", "")
if not API_SECRET_KEY and ENVIRONMENT == "production":
    raise ValueError("API_SECRET_KEY is required in production — set it in .env or environment")
if not API_SECRET_KEY and ENVIRONMENT != "production":
    if "_secrets" not in dir():
        import secrets as _secrets
    API_SECRET_KEY = _secrets.token_hex(32)

# ── Email / SMTP ──────────────────────────────────────────────────────
SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM: str = os.getenv("SMTP_FROM", "")
if not SMTP_HOST or not SMTP_USER:
    import logging as _cfg_logging2
    _cfg_logging2.getLogger(__name__).warning(
        "SMTP not configured — email sending (OTP verification) will fail silently"
    )

# ── OTP settings ──────────────────────────────────────────────────────
OTP_EXPIRE_MINUTES: int = 10
OTP_RESEND_COOLDOWN_SECONDS: int = 60

# ── Account security ─────────────────────────────────────────────────
MAX_FAILED_LOGIN_ATTEMPTS: int = 5
ACCOUNT_LOCKOUT_MINUTES: int = 15

# ── Embedding ──────────────────────────────────────────────────────────
EMBEDDING_MODEL = "text-embedding-3-small"

# ── Custom Interest Validation ────────────────────────────────────────────────
INTEREST_VALIDATOR_MODEL: str = OPENAI_MODEL_MINI  # cheapest capable model
INTEREST_MIN_LENGTH: int = 2
INTEREST_MAX_LENGTH: int = 30
CUSTOM_INTERESTS_MAX: int = 20
INTEREST_VALIDATOR_CACHE_TTL_SECONDS: int = 3600

# Predefined interest IDs — mirrors frontend/src/constants/tutorPreferences.js INTEREST_OPTIONS.
# Keep in sync with the frontend list; both sides must agree on the canonical IDs.
PREDEFINED_INTEREST_IDS: list[str] = [
    "Sports", "Gaming", "Music", "Movies", "Food",
    "Animals", "Space", "Technology", "Art", "Nature",
]

# ── Adaptive Learning Engine ────────────────────────────────────────────────
ADAPTIVE_ERROR_PENALTY_WEIGHT: float = 0.4   # Weight for error rate in confidence score
ADAPTIVE_HINT_PENALTY_WEIGHT: float = 0.2    # Weight for hint usage in confidence score

# ── Mastery ───────────────────────────────────────────────────────────────────
# DEPRECATED: No longer used in chunk-based teaching flow
# MASTERY_THRESHOLD = 70

# ── Socratic check settings ───────────────────────────────────────────────────
# DEPRECATED: No longer used in chunk-based teaching flow
# MAX_SOCRATIC_EXCHANGES      = 30
# SOCRATIC_MAX_ATTEMPTS       = 3
SOCRATIC_PROGRESS_INTERVAL  = 3   # Show progress summary every N questions

# ── Card session settings ─────────────────────────────────────────────────────
CARDS_MID_SESSION_CHECK_INTERVAL = 12  # Mood/engagement check-in every N cards
STARTER_PACK_INITIAL_SECTIONS: int = 2   # Sub-sections generated on first request (fast initial load)
STARTER_PACK_MAX_SECTIONS: int = 50    # Safety cap — rolling generation won't exceed this total

# ── Adaptive card generation ──────────────────────────────────────────────────
ADAPTIVE_CARD_MODEL   = OPENAI_MODEL_MINI   # gpt-4o-mini: fast for single-card generation
# ADAPTIVE_CARD_CEILING removed — card count is determined by content, not a ceiling

# ── Per-card adaptive generation token budget ──────────────────────────────────
NEXT_CARD_MAX_TOKENS: int = 1200   # Single card: title + content + 1 MCQ + motivational note

# ── Chunk-based card generation token budgets (per-chunk, per-mode) ────────────
CHUNK_MAX_TOKENS_STRUGGLING = 8000   # room for thorough scaffolded explanations
CHUNK_MAX_TOKENS_NORMAL     = 6000   # room for clear explanations with examples
CHUNK_MAX_TOKENS_FAST       = 5000   # enough for complete coverage at technical density
CHUNK_MAX_TOKENS_RECOVERY   = 800    # single recovery card+MCQ

# ── Socratic exam pass threshold for chunk-based architecture ─────────────────
CHUNK_EXAM_PASS_RATE = 0.50   # pass if student gets at least half right

# ── Card generation token budgets (profile-adaptive) ──────────────────────────
# Budget scales with section count × per-section multiplier, clamped to floor/ceiling.
# SLOW/STRUGGLING learners need 2-3 cards/section with richer explanations.
CARDS_MAX_TOKENS_SLOW: int = 40_000          # ceiling for SLOW or STRUGGLING profile
CARDS_MAX_TOKENS_SLOW_FLOOR: int = 8_000     # minimum even for short concepts
CARDS_MAX_TOKENS_SLOW_PER_SECTION: int = 6_000   # raised for rolling per-section generation

# NORMAL learners (default)
CARDS_MAX_TOKENS_NORMAL: int = 32_000
CARDS_MAX_TOKENS_NORMAL_FLOOR: int = 6_000
CARDS_MAX_TOKENS_NORMAL_PER_SECTION: int = 4_500  # raised for rolling per-section generation

# FAST/STRONG learners need fewer, denser cards
CARDS_MAX_TOKENS_FAST: int = 24_000
CARDS_MAX_TOKENS_FAST_FLOOR: int = 4_000
CARDS_MAX_TOKENS_FAST_PER_SECTION: int = 3_000   # raised for rolling per-section generation

# ── XP Award Values ────────────────────────────────────────────────────────────
XP_MASTERY: int = 50                  # Base XP awarded on concept mastery
XP_MASTERY_BONUS: int = 25            # Bonus XP when check_score >= XP_MASTERY_BONUS_THRESHOLD
XP_MASTERY_BONUS_THRESHOLD: int = 90  # Score (0-100) qualifying for mastery bonus
XP_CONSOLATION: int = 10              # Consolation XP when session completes without mastery

# ── Difficulty-Weighted XP ────────────────────────────────────────────────────
XP_PER_DIFFICULTY_POINT: int = 4     # Base XP per difficulty level (difficulty * this)
XP_HINT_PENALTY: float = 0.25       # XP reduction fraction per hint used (floor 0.25 total)
XP_WRONG_PENALTY: float = 0.15      # XP reduction fraction per wrong attempt (floor 0.25 total)
XP_FIRST_ATTEMPT_BONUS: float = 1.5 # Multiplier for first-attempt correct with no hints

# ── Adaptive Transparency ─────────────────────────────────────────────────────
WRONG_OPTION_PATTERN_THRESHOLD: int = 3  # Times a wrong option must be chosen to trigger pattern injection
CARD_HISTORY_DEFAULT_LIMIT: int = 50     # Default row limit for GET /card-history
CARD_HISTORY_MAX_LIMIT: int = 200        # Hard cap — prevents runaway queries

# ── Deviation-aware blending ──────────────────────────────────────────────────
ADAPTIVE_MIN_HISTORY_CARDS     = 5    # Minimum cards before history is blended in
ADAPTIVE_ACUTE_HIGH_TIME_RATIO = 2.0  # time_ratio > this -> distraction/illness detected
ADAPTIVE_ACUTE_LOW_TIME_RATIO  = 0.4  # time_ratio < this -> recovery/acceleration detected
ADAPTIVE_ACUTE_WRONG_RATIO     = 1.8  # wrong_ratio > this -> acute struggle detected
ADAPTIVE_ACUTE_CURRENT_WEIGHT  = 0.9  # Current-signal weight in acute deviation mode
ADAPTIVE_ACUTE_HISTORY_WEIGHT  = 0.1  # History weight in acute deviation mode
ADAPTIVE_NORMAL_CURRENT_WEIGHT = 0.6  # Current-signal weight in normal variance mode
ADAPTIVE_NORMAL_HISTORY_WEIGHT = 0.4  # History weight in normal variance mode

# ── Adaptive blend weights ────────────────────────────────────────────────────
ADAPTIVE_COLD_START_CURRENT_WEIGHT  = 0.80   # section_count == 0
ADAPTIVE_COLD_START_HISTORY_WEIGHT  = 0.20
ADAPTIVE_WARM_START_CURRENT_WEIGHT  = 0.70   # section_count == 1
ADAPTIVE_WARM_START_HISTORY_WEIGHT  = 0.30
ADAPTIVE_PARTIAL_CURRENT_WEIGHT     = 0.65   # section_count == 2
ADAPTIVE_PARTIAL_HISTORY_WEIGHT     = 0.35
ADAPTIVE_STATE_BLEND_CURRENT_WEIGHT = 0.60   # section_count >= 3
ADAPTIVE_STATE_BLEND_HISTORY_WEIGHT = 0.40

# ── Image serving ─────────────────────────────────────────────────────
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL", "")

# ── Boilerplate patterns to strip (line-level) ─────────────────────────
BOILERPLATE_PATTERNS = [
    r"Access for free at openstax\.org",
    r"Access for free at OpenStax\.org",
    r"This content is available for free at",
]

# ── Exercise / non-instructional markers ───────────────────────────────
EXERCISE_SECTION_MARKERS = [
    "Practice Makes Perfect",
    "Mixed Practice",
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
MATHPIX_RATE_LIMIT = 0.5   # Seconds between Mathpix API requests

# ── Vision annotation settings ────────────────────────────────────────
VISION_RATE_LIMIT: float = 0.5   # Seconds between GPT-4o Vision API requests

# ── Universal extraction pipeline defaults ────────────────────────────
DEFAULT_MIN_CHUNK_WORDS = 80           # Minimum words per chunk; smaller chunks get merged
DEFAULT_MAX_CHUNK_WORDS = 2000         # Maximum words per chunk; larger chunks get split at paragraph breaks
DEFAULT_RECURRING_HEADING_THRESHOLD = 5 # Headings appearing > this many times = recurring (feature box/exercise)
DEFAULT_COVERAGE_THRESHOLD = 0.95       # Minimum fraction of MMD content that must be assigned to chunks


class BookConfig(BaseModel):
    book_code: str
    book_slug: str
    pdf_filename: str
    title: str
    subject: str
    section_header_font: Optional[str] = None
    section_header_size_min: Optional[float] = None
    section_header_size_max: Optional[float] = None
    chapter_header_font: Optional[str] = None
    chapter_header_size_min: Optional[float] = None
    chapter_header_size_max: Optional[float] = None
    front_matter_end_page: int = 0
    section_pattern: Optional[str] = None
    toc_section_pattern: Optional[str] = None
    exercise_marker_pattern: Optional[str] = None


def _load_book_registry() -> dict:
    """Load book registry from books.yaml at runtime. Validates each entry with BookConfig."""
    _yaml_path = BACKEND_DIR / "books.yaml"
    _data = _yaml.safe_load(_yaml_path.read_text(encoding="utf-8"))
    registry = {}
    for b in _data["books"]:
        cfg = BookConfig(**b)
        registry[cfg.book_code] = cfg.model_dump()
    return registry


BOOK_REGISTRY = _load_book_registry()
BOOK_CODE_MAP = {b["book_slug"]: b["book_code"] for b in BOOK_REGISTRY.values()}


def get_book_config(book_code: str) -> dict:
    """Get configuration for a book by its code."""
    if book_code not in BOOK_REGISTRY:
        raise ValueError(f"Unknown book code: {book_code}. Available: {list(BOOK_REGISTRY.keys())}")
    return BOOK_REGISTRY[book_code]


def get_pdf_path(book_code: str) -> Path:
    """Get the full path to a book's PDF file."""
    config = get_book_config(book_code)
    return DATA_DIR / config["pdf_filename"]


# ── Startup validation ─────────────────────────────────────────────────────
_REQUIRED_ENV_VARS = {
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "DATABASE_URL": DATABASE_URL,
}
if ENVIRONMENT == "production":
    _API_SECRET_KEY_VAL = os.getenv("API_SECRET_KEY", "")
    if not _API_SECRET_KEY_VAL:
        _REQUIRED_ENV_VARS["API_SECRET_KEY"] = ""
    if not JWT_SECRET_KEY:
        _REQUIRED_ENV_VARS["JWT_SECRET_KEY"] = ""

def validate_required_env_vars() -> None:
    """Raise ValueError with a clear message if required env vars are missing."""
    missing = [name for name, val in _REQUIRED_ENV_VARS.items() if not val]
    if missing:
        raise ValueError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Copy backend/.env.example to backend/.env and fill in the values."
        )
