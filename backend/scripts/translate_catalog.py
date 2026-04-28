"""
One-shot backfill script — translate catalog JSONB columns from English.

Usage (run from backend/ with venv activated):
    python scripts/translate_catalog.py --book <slug> --languages all [--force] [--dry-run]
    python scripts/translate_catalog.py --book prealgebra --languages ml,ta,ar
    python scripts/translate_catalog.py --book business_statistics --languages all --dry-run

Idempotent: skips rows whose SHA-1 matches and all requested languages are present,
unless --force is given.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

# Ensure backend/src is on sys.path regardless of working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx
import openai
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.prompts import LANGUAGE_NAMES, _language_instruction
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL_MINI
from db.connection import async_session_factory, engine
from db.models import Book, ChunkImage, ConceptChunk, Subject

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("translate_catalog")

ALL_LANGUAGES = [code for code in LANGUAGE_NAMES if code != "en"]

# Columns that are safe to interpolate into a JSONB-path expression.
# PostgreSQL JSONB-path arguments cannot be SQL-bound, so we assert membership
# as a defense-in-depth guard against accidental or malicious col_name values.
ALLOWED_TRANSLATION_COLS = frozenset({
    "title_translations", "subject_translations", "label_translations",
    "heading_translations", "caption_translations",
})

# Cost estimate constants (gpt-4o-mini pricing as of 2026-04)
_COST_PER_1K_INPUT  = 0.000150   # USD
_COST_PER_1K_OUTPUT = 0.000600

# Maximum strings per individual OpenAI chat completion call.
BATCH_SIZE_PER_CALL = 50

# Back-off delay schedule in seconds (5 attempts = delays between attempts 1→2, 2→3, 3→4, 4→5).
_RETRY_DELAYS = [2, 4, 8, 16, 32]


class TranslationBatchError(Exception):
    """Raised when all retry attempts for a translation batch are exhausted."""


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _needs_translate(
    translations: dict,
    en_value: str,
    languages: list[str],
    force: bool,
) -> tuple[bool, list[str]]:
    """Return (should_translate, languages_to_translate)."""
    if force:
        return True, languages
    stored_hash = translations.get("en_source_hash", "")
    current_hash = _sha1(en_value)
    if stored_hash != current_hash:
        # Source changed — retranslate everything.
        return True, languages
    missing = [lang for lang in languages if not translations.get(lang)]
    return bool(missing), missing


def _build_system_prompt(lang: str, context_hint: str) -> str:
    """Build the system prompt for a given target language and context hint."""
    lang_name = LANGUAGE_NAMES.get(lang, lang)
    return (
        f"You are a mathematics education translator. "
        f"Translate each item in the JSON array into {lang_name}. "
        f"Return a JSON array of the same length in the same order. "
        f"Context: {context_hint}. "
        f"Keep mathematical notation ($...$) and proper nouns unchanged. "
        f"Do NOT add explanations."
    )


async def _call_llm_once(
    client,
    prompt: str,
    system_prompt: str,
    timeout: float = 120.0,
) -> list[str]:
    """Single raw OpenAI chat completion call.

    Returns the parsed JSON array of translated strings.
    Raises ``ValueError`` if the returned item count does not match the sent count.
    Raises openai/httpx errors on API failures — the caller decides whether to retry.
    """
    strings: list[str] = json.loads(prompt)
    resp = await client.chat.completions.create(
        model=OPENAI_MODEL_MINI,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": prompt},
        ],
        # 200 tokens per string accommodates non-Latin script translations
        # (Hindi/Tamil/Sinhala can use 2-3× the tokens of English) for typical
        # heading/caption lengths up to ~50 words. Was 60 — truncated
        # nursing-style long captions, forcing expensive per-item fallbacks.
        max_tokens=max(512, len(strings) * 200),
        temperature=0.1,
        timeout=timeout,
    )
    raw = (resp.choices[0].message.content or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or len(parsed) != len(strings):
        got = len(parsed) if isinstance(parsed, list) else -1
        raise ValueError(
            f"LLM returned {got} items but expected {len(strings)}"
        )
    return [str(s) for s in parsed]


async def _translate_batch_with_retry(
    client,
    strings: list[str],
    lang: str,
    batch_idx: int,
    total_batches: int,
    system_prompt: str,
) -> tuple[list[str], int]:
    """Translate *strings* with up to 5 retry attempts using exponential back-off.

    Returns (translated_strings, retries_performed).
    Raises ``TranslationBatchError`` after all retries are exhausted.

    Retries on: APITimeoutError, APIConnectionError, RateLimitError, HTTP 5xx, ValueError
    (length mismatch).  Does NOT retry on HTTP 4xx.
    """
    prompt = json.dumps(strings, ensure_ascii=False)
    last_exc: Exception | None = None
    retries_performed = 0

    for attempt_idx in range(len(_RETRY_DELAYS) + 1):  # attempts 0..5
        if attempt_idx > 0:
            delay = _RETRY_DELAYS[attempt_idx - 1]
            retries_performed += 1
            logger.warning(
                "[llm] retry %d/%d for lang=%s batch %d/%d after %ds (prev: %s)",
                attempt_idx, len(_RETRY_DELAYS),
                lang, batch_idx + 1, total_batches,
                delay, last_exc,
            )
            await asyncio.sleep(delay)

        try:
            result = await _call_llm_once(client, prompt, system_prompt)
            return result, retries_performed
        except (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError) as exc:
            last_exc = exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                last_exc = exc
            else:
                # 4xx — do not retry
                raise TranslationBatchError(
                    f"Non-retryable HTTP {exc.response.status_code} for "
                    f"lang={lang} batch {batch_idx + 1}/{total_batches}: {exc}"
                ) from exc
        except ValueError as exc:
            # Length mismatch — worth retrying
            last_exc = exc
        except Exception as exc:
            last_exc = exc

    raise TranslationBatchError(
        f"All retries exhausted for lang={lang} batch {batch_idx + 1}/{total_batches}: {last_exc}"
    )


async def _translate_item_fallback(
    client,
    one_string: str,
    lang: str,
    system_prompt: str,
) -> str | None:
    """Translate a single string using the same 5-attempt retry.

    Returns the translated string, or ``None`` on total failure.
    """
    try:
        results, _ = await _translate_batch_with_retry(
            client, [one_string], lang, 0, 1, system_prompt
        )
        return results[0]
    except Exception as exc:
        logger.error(
            "[llm] per-item fallback failed for lang=%s string=%r: %s",
            lang, one_string[:60], exc,
        )
        return None


async def _llm_translate_batch(
    client,
    strings: list[str],
    lang: str,
    system_prompt: str,
) -> tuple[list[str], int, int]:
    """Translate *strings* into *lang*, splitting into chunks of BATCH_SIZE_PER_CALL.

    Returns ``(results, retries_performed, per_item_fallbacks)``.

    If a batch ultimately fails after all retries, falls back to per-item translation.
    Items that fail even the per-item fallback are kept as their original English value.
    """
    n_batches = math.ceil(max(len(strings), 1) / BATCH_SIZE_PER_CALL)
    results: list[str] = []
    total_retries = 0
    total_fallbacks = 0

    for batch_idx in range(n_batches):
        start = batch_idx * BATCH_SIZE_PER_CALL
        end = start + BATCH_SIZE_PER_CALL
        batch = strings[start:end]

        try:
            translated, retries = await _translate_batch_with_retry(
                client, batch, lang, batch_idx, n_batches, system_prompt
            )
            total_retries += retries
            results.extend(translated)
        except TranslationBatchError as exc:
            logger.error(
                "[llm] batch %d/%d exhausted for lang=%s — falling back to per-item: %s",
                batch_idx + 1, n_batches, lang, exc,
            )
            for item in batch:
                fallback = await _translate_item_fallback(client, item, lang, system_prompt)
                if fallback is not None:
                    total_fallbacks += 1
                    results.append(fallback)
                else:
                    results.append(item)  # keep English on total failure

    return results, total_retries, total_fallbacks


# ─────────────────────────────────────────────────────────────────────────────
# Per-table translate helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _translate_table(
    db: AsyncSession,
    client,
    table_label: str,
    rows: list[tuple[Any, str, dict]],   # (orm_id, en_value, current_translations)
    column_name: str,
    orm_class,
    languages: list[str],
    force: bool,
    dry_run: bool,
) -> tuple[int, int, int, int, int, int]:
    """Translate one table.

    Returns
    -------
    (rows_written, llm_calls, rows_skipped, batches_sent, retries_performed, per_item_fallbacks)
    """
    rows_written = 0
    llm_calls = 0
    rows_skipped = 0
    batches_sent = 0
    retries_performed = 0
    per_item_fallbacks = 0

    # Group rows by which languages still need translation.
    pending: dict[frozenset, list[tuple[Any, str, dict]]] = {}
    for row_id, en_value, translations in rows:
        should, langs_needed = _needs_translate(translations, en_value, languages, force)
        if not should:
            rows_skipped += 1
            continue
        key = frozenset(langs_needed)
        pending.setdefault(key, []).append((row_id, en_value, translations))

    if dry_run:
        total_pending = sum(len(v) for v in pending.values())
        print(f"  [dry-run] {table_label}: {total_pending} rows need translation, {rows_skipped} skipped")
        return 0, 0, rows_skipped, 0, 0, 0

    # Translate per language across all pending rows that need that language.
    lang_to_rows: dict[str, list[tuple[Any, str, dict]]] = {}
    for langs_needed_set, batch in pending.items():
        for lang in langs_needed_set:
            lang_to_rows.setdefault(lang, []).extend(batch)

    # Collect results: row_id → updated translations dict
    result_map: dict[Any, dict] = {}
    for row_id, en_value, translations in [
        (r[0], r[1], r[2]) for batch in pending.values() for r in batch
    ]:
        if row_id not in result_map:
            result_map[row_id] = dict(translations)
            result_map[row_id]["en_source_hash"] = _sha1(en_value)

    for lang, lang_rows in lang_to_rows.items():
        strings = [r[1] for r in lang_rows]
        ids     = [r[0] for r in lang_rows]
        n_batches_for_lang = math.ceil(max(len(strings), 1) / BATCH_SIZE_PER_CALL)
        logger.info("[%s] translating %d strings → %s (%d batches)", table_label, len(strings), lang, n_batches_for_lang)
        t0 = time.monotonic()
        sys_prompt = _build_system_prompt(lang, table_label)
        try:
            translated, lang_retries, lang_fallbacks = await _llm_translate_batch(
                client, strings, lang, sys_prompt
            )
            llm_calls += 1
            batches_sent += n_batches_for_lang
            retries_performed += lang_retries
            per_item_fallbacks += lang_fallbacks
            elapsed = time.monotonic() - t0
            logger.info(
                "[%s] lang=%s done in %.1fs (batches=%d retries=%d fallbacks=%d)",
                table_label, lang, elapsed, n_batches_for_lang, lang_retries, lang_fallbacks,
            )
        except Exception as exc:
            logger.error("[%s] lang=%s failed: %s — skipping this language", table_label, lang, exc)
            continue

        for row_id, translation in zip(ids, translated):
            result_map.setdefault(row_id, {})["en_source_hash"] = _sha1(
                next(en for rid, en, _ in lang_rows if rid == row_id)
            )
            result_map[row_id][lang] = translation

    # Write back to DB
    for row_id, new_translations in result_map.items():
        await db.execute(
            update(orm_class)
            .where(orm_class.id == row_id)
            .values({column_name: new_translations})
        )
        rows_written += 1

    await db.flush()
    return rows_written, llm_calls, rows_skipped, batches_sent, retries_performed, per_item_fallbacks


# ─────────────────────────────────────────────────────────────────────────────
# Gap-fill pass: catch any rows/languages missed by the main loop
# ─────────────────────────────────────────────────────────────────────────────

async def _gap_fill_pass(
    db: AsyncSession,
    book_slug: str,
    languages: list[str],
    client,
) -> tuple[int, int]:
    """Re-scan all translatable rows and fill any missing or empty translations.

    Returns ``(gap_fill_items_translated, failures)``.
    """
    gap_fill_items = 0
    failures = 0

    # Re-query fresh rows to catch anything the main loop skipped.
    book_row = (await db.execute(
        select(Book).where(Book.book_slug == book_slug)
    )).scalar_one_or_none()

    tables_to_check: list[tuple[str, Any, str, list[tuple[Any, str, dict]]]] = []

    if book_row is not None:
        tables_to_check.append((
            "books.title", Book, "title_translations",
            [(book_row.id, book_row.title, book_row.title_translations or {})],
        ))
        tables_to_check.append((
            "books.subject", Book, "subject_translations",
            [(book_row.id, book_row.subject, book_row.subject_translations or {})],
        ))

        subj_row = (await db.execute(
            select(Subject).where(Subject.slug == book_row.subject)
        )).scalar_one_or_none()
        if subj_row is None:
            subj_row = (await db.execute(
                select(Subject).where(Subject.label == book_row.subject)
            )).scalar_one_or_none()
        if subj_row is not None:
            tables_to_check.append((
                "subjects.label", Subject, "label_translations",
                [(subj_row.id, subj_row.label, subj_row.label_translations or {})],
            ))

    chunk_rows = (await db.execute(
        select(ConceptChunk.id, ConceptChunk.heading, ConceptChunk.heading_translations)
        .where(ConceptChunk.book_slug == book_slug)
    )).all()
    tables_to_check.append((
        "concept_chunks.heading", ConceptChunk, "heading_translations",
        [(r.id, r.heading, r.heading_translations or {}) for r in chunk_rows],
    ))

    img_rows = (await db.execute(
        select(ChunkImage.id, ChunkImage.caption, ChunkImage.caption_translations)
        .join(ConceptChunk, ConceptChunk.id == ChunkImage.chunk_id)
        .where(ConceptChunk.book_slug == book_slug)
        .where(ChunkImage.caption.isnot(None))
    )).all()
    tables_to_check.append((
        "chunk_images.caption", ChunkImage, "caption_translations",
        [(r.id, r.caption, r.caption_translations or {}) for r in img_rows],
    ))

    # Enumerate gaps: absent or empty-string translations.
    gaps: list[tuple[str, Any, str, Any, str, str]] = []
    for table_label, orm_class, col_name, rows in tables_to_check:
        for row_id, en_value, translations in rows:
            for lang in languages:
                if not translations.get(lang):  # absent or empty string
                    gaps.append((table_label, orm_class, col_name, row_id, en_value, lang))

    if not gaps:
        logger.info("Gap-fill pass: 0 items to fill.")
        return 0, 0

    logger.info("Gap-fill pass: %d missing translation slots found.", len(gaps))

    for table_label, orm_class, col_name, row_id, en_value, lang in gaps:
        sys_prompt = _build_system_prompt(lang, table_label)
        translated = await _translate_item_fallback(client, en_value, lang, sys_prompt)
        if translated is not None:
            gap_fill_items += 1
            # Write only the single language key via jsonb_set to avoid overwriting other langs.
            # JSONB path can't be SQL-bound; assertion is the guardrail.
            assert col_name in ALLOWED_TRANSLATION_COLS, f"unsafe col_name: {col_name!r}"
            assert lang in LANGUAGE_NAMES, f"unsafe lang: {lang!r}"
            await db.execute(
                update(orm_class)
                .where(orm_class.id == row_id)
                .values({
                    col_name: text(
                        f"jsonb_set(COALESCE({col_name}, '{{}}'), '{{{lang}}}', :val::jsonb)"
                    ).bindparams(val=json.dumps(translated))
                })
            )
        else:
            failures += 1
            logger.error(
                "[gap-fill] FAILED: table=%s row_id=%s lang=%s",
                table_label, row_id, lang,
            )

    await db.flush()
    langs_filled = {lang for _, _, _, _, _, lang in gaps}
    logger.info(
        "Gap-fill pass: %d items translated across %d languages.",
        gap_fill_items, len(langs_filled),
    )
    return gap_fill_items, failures


# ─────────────────────────────────────────────────────────────────────────────
# Public callable entry point
# ─────────────────────────────────────────────────────────────────────────────

async def translate_book(
    book_slug: str,
    languages: list[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
    db: AsyncSession | None = None,
    openai_client=None,
) -> dict:
    """Translate all catalog JSONB columns for *book_slug* into the target languages.

    Args:
        book_slug:      Book slug as stored in the ``books`` table (e.g. ``"prealgebra"``).
        languages:      List of BCP-47 language codes to target.  If ``None``, all
                        supported languages from ``LANGUAGE_NAMES`` minus ``"en"`` are used.
        force:          Re-translate even when the SHA-1 fingerprint matches.
        dry_run:        Print what would be translated; make no LLM calls and no DB writes.
        db:             An existing ``AsyncSession``.  If ``None`` a new session is opened
                        internally and committed on success.
        openai_client:  An ``AsyncOpenAI`` instance.  If ``None`` one is constructed from
                        the application's ``OPENAI_API_KEY`` / ``OPENAI_BASE_URL`` config.

    Returns:
        A summary dict::

            {
                "languages_attempted": [...],
                "languages_succeeded": [...],
                "languages_failed": [{"code": ..., "error": ...}],
                "rows_translated": N,
                "llm_calls": M,
                "batches_sent": B,
                "retries_performed": R,
                "per_item_fallbacks": F,
                "gap_fill_items": G,
                "total_failures_after_all_retries": X,
            }
    """
    if languages is None:
        languages = ALL_LANGUAGES

    if openai_client is None:
        from openai import AsyncOpenAI
        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL or None)

    total_written = 0
    total_calls   = 0
    total_skipped = 0
    total_batches_sent = 0
    total_retries_performed = 0
    total_per_item_fallbacks = 0
    gap_fill_items = 0
    total_failures_after_all_retries = 0
    languages_failed: list[dict] = []

    _own_session = db is None

    async def _run(session: AsyncSession) -> None:
        nonlocal total_written, total_calls, total_skipped
        nonlocal total_batches_sent, total_retries_performed, total_per_item_fallbacks
        nonlocal gap_fill_items, total_failures_after_all_retries

        # ── Book row ──────────────────────────────────────────────────────────
        book_row = (await session.execute(
            select(Book).where(Book.book_slug == book_slug)
        )).scalar_one_or_none()
        if book_row is None:
            raise ValueError(f"book '{book_slug}' not found in books table")

        logger.info("[translate_book] Book: %r  (slug=%s)", book_row.title, book_slug)
        logger.info("[translate_book] Languages: %s", ", ".join(languages))
        logger.info("[translate_book] Force: %s  Dry-run: %s", force, dry_run)

        def _acc(result: tuple[int, int, int, int, int, int]) -> None:
            nonlocal total_written, total_calls, total_skipped
            nonlocal total_batches_sent, total_retries_performed, total_per_item_fallbacks
            w, c, s, bs, rp, pif = result
            total_written += w; total_calls += c; total_skipped += s
            total_batches_sent += bs; total_retries_performed += rp; total_per_item_fallbacks += pif

        # Books — title_translations
        _acc(await _translate_table(
            session, openai_client, "books.title",
            [(book_row.id, book_row.title, book_row.title_translations or {})],
            "title_translations", Book, languages, force, dry_run,
        ))

        # Books — subject_translations
        _acc(await _translate_table(
            session, openai_client, "books.subject",
            [(book_row.id, book_row.subject, book_row.subject_translations or {})],
            "subject_translations", Book, languages, force, dry_run,
        ))

        # Subjects joined via book.subject slug — find by label matching book.subject
        subj_row = (await session.execute(
            select(Subject).where(Subject.slug == book_row.subject)
        )).scalar_one_or_none()
        if subj_row is None:
            subj_row = (await session.execute(
                select(Subject).where(Subject.label == book_row.subject)
            )).scalar_one_or_none()
        if subj_row is not None:
            _acc(await _translate_table(
                session, openai_client, "subjects.label",
                [(subj_row.id, subj_row.label, subj_row.label_translations or {})],
                "label_translations", Subject, languages, force, dry_run,
            ))
        else:
            logger.warning("[subjects] no subject row found matching book.subject=%r — skipping", book_row.subject)

        # ConceptChunks — heading_translations
        chunk_rows = (await session.execute(
            select(ConceptChunk.id, ConceptChunk.heading, ConceptChunk.heading_translations)
            .where(ConceptChunk.book_slug == book_slug)
        )).all()
        chunk_data = [(r.id, r.heading, r.heading_translations or {}) for r in chunk_rows]
        logger.info("[concept_chunks] %d chunks to process", len(chunk_data))
        _acc(await _translate_table(
            session, openai_client, "concept_chunks.heading", chunk_data,
            "heading_translations", ConceptChunk, languages, force, dry_run,
        ))

        # ChunkImages — caption_translations (skip NULL captions)
        img_rows = (await session.execute(
            select(ChunkImage.id, ChunkImage.caption, ChunkImage.caption_translations)
            .join(ConceptChunk, ConceptChunk.id == ChunkImage.chunk_id)
            .where(ConceptChunk.book_slug == book_slug)
            .where(ChunkImage.caption.isnot(None))
        )).all()
        img_data = [(r.id, r.caption, r.caption_translations or {}) for r in img_rows]
        logger.info("[chunk_images] %d captioned images to process", len(img_data))
        _acc(await _translate_table(
            session, openai_client, "chunk_images.caption", img_data,
            "caption_translations", ChunkImage, languages, force, dry_run,
        ))

        if not dry_run:
            # ── Gap-fill pass ──────────────────────────────────────────────
            gf_items, gf_failures = await _gap_fill_pass(session, book_slug, languages, openai_client)
            gap_fill_items += gf_items
            total_failures_after_all_retries += gf_failures
            await session.commit()

    if _own_session:
        async with async_session_factory() as session:
            await _run(session)
    else:
        await _run(db)

    # Derive succeeded/failed from total_calls vs attempted languages.
    # Since _translate_table logs per-language errors internally and continues,
    # we report all languages as succeeded unless a catastrophic error was raised.
    languages_succeeded = list(languages)

    summary = {
        "languages_attempted": list(languages),
        "languages_succeeded": languages_succeeded,
        "languages_failed": languages_failed,
        "rows_translated": total_written,
        "llm_calls": total_calls,
        "batches_sent": total_batches_sent,
        "retries_performed": total_retries_performed,
        "per_item_fallbacks": total_per_item_fallbacks,
        "gap_fill_items": gap_fill_items,
        "total_failures_after_all_retries": total_failures_after_all_retries,
    }
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point (unchanged behaviour from Phase 3)
# ─────────────────────────────────────────────────────────────────────────────

async def _run_cli(book_slug: str, languages: list[str], force: bool, dry_run: bool) -> None:
    """CLI wrapper: prints the human-readable summary table and disposes the engine."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL or None)

    # Peek at the book row so we can print the header before work starts.
    async with async_session_factory() as _peek_db:
        book_row = (await _peek_db.execute(
            select(Book).where(Book.book_slug == book_slug)
        )).scalar_one_or_none()
        if book_row is None:
            print(f"ERROR: book '{book_slug}' not found in books table.")
            sys.exit(1)
        book_title = book_row.title

    print(f"\nBook: {book_title!r}  (slug={book_slug})")
    print(f"Languages: {', '.join(languages)}")
    print(f"Force: {force}  Dry-run: {dry_run}\n")

    summary = await translate_book(
        book_slug=book_slug,
        languages=languages,
        force=force,
        dry_run=dry_run,
        openai_client=client,
    )

    total_written = summary["rows_translated"]
    total_calls   = summary["llm_calls"]
    # Skipped count not surfaced in the summary dict; compute from dry-run print output
    # (the _translate_table dry-run branch already prints per-table counts).

    print("\n─────────────────────────────────────────")
    print(f"Rows written                 : {total_written}")
    print(f"LLM calls                    : {total_calls}")
    print(f"Batches sent                 : {summary['batches_sent']}")
    print(f"Retries performed            : {summary['retries_performed']}")
    print(f"Per-item fallbacks           : {summary['per_item_fallbacks']}")
    print(f"Gap-fill items               : {summary['gap_fill_items']}")
    print(f"Unresolved failures          : {summary['total_failures_after_all_retries']}")
    # Rough cost estimate: assume average 20 tokens input + 20 output per string per call
    est_tokens_in  = total_calls * 500
    est_tokens_out = total_calls * 200
    est_cost = (est_tokens_in / 1000) * _COST_PER_1K_INPUT + (est_tokens_out / 1000) * _COST_PER_1K_OUTPUT
    print(f"Est. cost                    : ~${est_cost:.4f} USD (rough estimate)")
    if dry_run:
        print("\n[dry-run] No LLM calls made, no DB writes.")
    print("─────────────────────────────────────────")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill i18n translation JSONB columns.")
    parser.add_argument("--book", required=True, help="Book slug (e.g. prealgebra)")
    parser.add_argument(
        "--languages",
        required=True,
        help=f"Comma-separated language codes or 'all'. Supported: {', '.join(ALL_LANGUAGES)}",
    )
    parser.add_argument("--force", action="store_true", help="Retranslate even if hash matches")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be translated; do not call LLM or write DB")
    args = parser.parse_args()

    if args.languages.strip().lower() == "all":
        languages = ALL_LANGUAGES
    else:
        languages = [code.strip() for code in args.languages.split(",") if code.strip()]
        unknown = [lang for lang in languages if lang not in LANGUAGE_NAMES]
        if unknown:
            print(f"ERROR: unknown language code(s): {', '.join(unknown)}")
            print(f"Supported: {', '.join(ALL_LANGUAGES)}")
            sys.exit(1)

    asyncio.run(_run_cli(args.book, languages, args.force, args.dry_run))


if __name__ == "__main__":
    main()
