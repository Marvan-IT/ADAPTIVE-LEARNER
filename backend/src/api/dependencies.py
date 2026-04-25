"""Language resolution helpers for FastAPI request handlers."""

from fastapi import Request

from api.prompts import LANGUAGE_NAMES
from db.models import Student

SUPPORTED_LANG_CODES: frozenset[str] = frozenset(LANGUAGE_NAMES.keys())


async def get_request_language(
    request: Request,
    student: Student | None = None,
) -> str:
    """Resolve request language from student profile, then Accept-Language header, then 'en'."""
    if student and student.preferred_language:
        lang = student.preferred_language.strip().lower()
        return lang if lang in SUPPORTED_LANG_CODES else "en"
    header = request.headers.get("Accept-Language", "en")
    base = header.split(",")[0].split(";")[0].split("-")[0].strip().lower()
    return base if base in SUPPORTED_LANG_CODES else "en"


def resolve_translation(
    english_value: str,
    translations: dict,
    lang: str,
) -> str:
    """Return translated value for lang, falling back to english_value if absent or empty."""
    if lang == "en" or not translations:
        return english_value
    translated = translations.get(lang)
    if translated and isinstance(translated, str) and translated.strip():
        return translated
    return english_value
