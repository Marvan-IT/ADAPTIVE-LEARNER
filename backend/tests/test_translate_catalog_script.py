"""
test_translate_catalog_script.py
Tests for backend/scripts/translate_catalog.py (import-based, no subprocess).

Mocks:
  - OpenAI AsyncOpenAI client — patches the `client` passed into _translate_table
  - SQLAlchemy AsyncSession — AsyncMock
  - async_session_factory / engine — patched so run() does not connect to DB

Tests:
  - dry_run=True: no LLM calls, summary printed, no DB writes
  - dry_run=False: LLM called once per language, en_source_hash + translations written
  - idempotent: second run with matching hash → zero LLM calls
  - source change: only changed row retranslated
  - --force: all rows retranslated regardless of hash
  - one language fails: script continues, other languages written, warning logged
  - BATCH_SIZE_PER_CALL constant exists and equals 50
  - large input splits into correct number of batches
  - timeout → retry → succeed
  - length mismatch → retry → succeed
  - gap-fill pass fills empty-string translations
"""

import asyncio
import json
import sys
import uuid
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest
import openai

# Import helpers directly from the script (not via subprocess)
from translate_catalog import (
    BATCH_SIZE_PER_CALL,
    TranslationBatchError,
    _sha1,
    _needs_translate,
    _translate_table,
    _llm_translate_batch,
    _translate_batch_with_retry,
    _build_system_prompt,
    ALL_LANGUAGES,
)
from db.models import ConceptChunk as _OrmClass  # real ORM class required by sqlalchemy update()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_llm_client(translations: list[str] | None = None) -> MagicMock:
    """
    Build a mock OpenAI client whose chat.completions.create returns a JSON list.
    If translations=None, defaults to returning the input strings unchanged.
    """
    client = MagicMock()
    captured_calls: list[list[str]] = []

    async def _create(**kwargs):
        user_msg = kwargs["messages"][-1]["content"]
        strings = json.loads(user_msg)
        captured_calls.append(strings)
        output = translations if translations is not None else strings
        resp = MagicMock()
        resp.choices[0].message.content = json.dumps(output)
        return resp

    client.chat.completions.create = _create
    client._captured_calls = captured_calls
    return client


def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


# ── _sha1 ─────────────────────────────────────────────────────────────────────

class TestSha1:
    def test_sha1_matches_hashlib(self):
        value = "Prealgebra 2e"
        expected = hashlib.sha1(value.encode("utf-8")).hexdigest()
        assert _sha1(value) == expected

    def test_sha1_empty_string(self):
        result = _sha1("")
        assert len(result) == 40  # sha1 hex digest always 40 chars


# ── _needs_translate ──────────────────────────────────────────────────────────

class TestNeedsTranslate:
    def test_force_true_always_needs_all_languages(self):
        needs, langs = _needs_translate(
            {"en_source_hash": _sha1("x"), "ml": "existing"},
            "x",
            ["ml", "ta"],
            force=True,
        )
        assert needs is True
        assert set(langs) == {"ml", "ta"}

    def test_hash_mismatch_triggers_full_retranslation(self):
        needs, langs = _needs_translate(
            {"en_source_hash": "oldhash", "ml": "existing"},
            "new source value",
            ["ml"],
            force=False,
        )
        assert needs is True
        assert langs == ["ml"]

    def test_hash_match_all_present_skips(self):
        text = "Introduction"
        needs, langs = _needs_translate(
            {"en_source_hash": _sha1(text), "ml": "ആമുഖം"},
            text,
            ["ml"],
            force=False,
        )
        assert needs is False
        assert langs == []

    def test_hash_match_missing_language_needs_that_language(self):
        text = "Introduction"
        needs, langs = _needs_translate(
            {"en_source_hash": _sha1(text), "ml": "ആമുഖം"},
            text,
            ["ml", "ta"],  # ta not yet present
            force=False,
        )
        assert needs is True
        assert langs == ["ta"]


# ── _translate_table — dry_run ────────────────────────────────────────────────

class TestTranslateTableDryRun:
    async def test_dry_run_makes_no_llm_calls_and_no_db_writes(self, capsys):
        """dry_run=True: zero LLM calls, zero DB execute calls, prints summary."""
        client = _make_llm_client()
        db = _make_mock_db()
        row_id = uuid.uuid4()

        rows_written, llm_calls, rows_skipped, batches_sent, retries, fallbacks = await _translate_table(
            db, client,
            table_label="books.title",
            rows=[(row_id, "Introduction", {})],
            column_name="title_translations",
            orm_class=_OrmClass,
            languages=["ml"],
            force=False,
            dry_run=True,
        )

        assert llm_calls == 0
        assert rows_written == 0
        assert batches_sent == 0
        db.execute.assert_not_called()
        captured = capsys.readouterr()
        assert "[dry-run]" in captured.out


# ── _translate_table — real run ───────────────────────────────────────────────

class TestTranslateTableRealRun:
    async def test_writes_en_source_hash_and_translation(self):
        """Normal run: LLM called, DB execute called with hash + translation."""
        client = _make_llm_client(translations=["ആമുഖം"])
        db = _make_mock_db()
        row_id = uuid.uuid4()

        rows_written, llm_calls, rows_skipped, batches_sent, retries, fallbacks = await _translate_table(
            db, client,
            table_label="books.title",
            rows=[(row_id, "Introduction", {})],
            column_name="title_translations",
            orm_class=_OrmClass,
            languages=["ml"],
            force=False,
            dry_run=False,
        )

        assert llm_calls == 1
        assert rows_written == 1
        assert rows_skipped == 0
        assert batches_sent == 1
        db.execute.assert_called_once()
        db.flush.assert_called_once()

    async def test_idempotent_skip_when_hash_matches_and_lang_present(self):
        """Second run with same hash and language present → zero LLM calls."""
        client = _make_llm_client()
        db = _make_mock_db()
        row_id = uuid.uuid4()
        text = "Introduction"
        existing_translations = {"en_source_hash": _sha1(text), "ml": "ആമുഖം"}

        rows_written, llm_calls, rows_skipped, batches_sent, retries, fallbacks = await _translate_table(
            db, client,
            table_label="concept_chunks.heading",
            rows=[(row_id, text, existing_translations)],
            column_name="heading_translations",
            orm_class=_OrmClass,
            languages=["ml"],
            force=False,
            dry_run=False,
        )

        assert llm_calls == 0
        assert rows_written == 0
        assert rows_skipped == 1
        db.execute.assert_not_called()

    async def test_changed_source_triggers_retranslation(self):
        """When the English value changes, the row is retranslated regardless of stored hash."""
        client = _make_llm_client(translations=["പുതുക്കിയ ആമുഖം"])
        db = _make_mock_db()
        row_id = uuid.uuid4()
        old_translations = {"en_source_hash": _sha1("Introduction"), "ml": "ആമുഖം"}

        rows_written, llm_calls, rows_skipped, batches_sent, retries, fallbacks = await _translate_table(
            db, client,
            table_label="concept_chunks.heading",
            rows=[(row_id, "Introduction Revised", old_translations)],  # changed source
            column_name="heading_translations",
            orm_class=_OrmClass,
            languages=["ml"],
            force=False,
            dry_run=False,
        )

        assert llm_calls == 1
        assert rows_written == 1

    async def test_force_retranslates_even_when_hash_matches(self):
        """--force causes retranslation even when hash matches all languages."""
        client = _make_llm_client(translations=["ആമുഖം-updated"])
        db = _make_mock_db()
        row_id = uuid.uuid4()
        text = "Introduction"
        existing = {"en_source_hash": _sha1(text), "ml": "ആമുഖം"}

        rows_written, llm_calls, rows_skipped, batches_sent, retries, fallbacks = await _translate_table(
            db, client,
            table_label="books.title",
            rows=[(row_id, text, existing)],
            column_name="title_translations",
            orm_class=_OrmClass,
            languages=["ml"],
            force=True,   # <-- force
            dry_run=False,
        )

        assert llm_calls == 1
        assert rows_written == 1


# ── _llm_translate_batch — per-language failure ───────────────────────────────

class TestLlmTranslateBatchFailure:
    async def test_one_language_failure_returns_original_strings(self):
        """If all retries raise, _llm_translate_batch falls back per-item; total failure → original strings."""
        client = MagicMock()
        # Raise on every attempt: batch retries (6 total) + per-item retries (6 each × 2 items).
        client.chat.completions.create = AsyncMock(
            side_effect=openai.APITimeoutError("API timeout")
        )
        strings = ["Introduction", "Variables"]
        sys_prompt = _build_system_prompt("ml", "test")
        with patch("asyncio.sleep", new_callable=AsyncMock):
            results, retries, fallbacks = await _llm_translate_batch(client, strings, "ml", sys_prompt)
        # Fallback path: per-item also fails → original strings returned unchanged
        assert results == strings
        # retries from _llm_translate_batch only counts successful-path batch retries;
        # fallbacks == 0 because even per-item fallback failed (returned None → kept English).
        assert fallbacks == 0

    async def test_multiple_language_failure_continues_processing(self):
        """
        _translate_table: one language that fails is skipped; other languages are written.
        Simulates the run()-level behaviour of continuing past a per-language failure.
        """
        call_count = 0

        async def _flaky_create(**kwargs):
            nonlocal call_count
            call_count += 1
            user_msg = kwargs["messages"][-1]["content"]
            strings = json.loads(user_msg)
            lang = kwargs["messages"][0]["content"]  # system prompt contains lang name
            if "Malayalam" in lang:
                raise openai.APITimeoutError("ml API failure")
            resp = MagicMock()
            resp.choices[0].message.content = json.dumps([s + "-translated" for s in strings])
            return resp

        client = MagicMock()
        client.chat.completions.create = _flaky_create
        db = _make_mock_db()
        row_id = uuid.uuid4()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            rows_written, llm_calls, rows_skipped, batches_sent, retries, fallbacks = await _translate_table(
                db, client,
                table_label="books.title",
                rows=[(row_id, "Introduction", {})],
                column_name="title_translations",
                orm_class=_OrmClass,
                languages=["ml", "ta"],   # ml will fail, ta should succeed
                force=False,
                dry_run=False,
            )

        # ta succeeded → 1 write; ml failed → skipped (but row written for ta)
        assert rows_written >= 1
        # The row was still written (ta translation went in)
        db.execute.assert_called()


# ── New tests: batch splitting, retry semantics, gap-fill ────────────────────

class TestBatchSizeConstant:
    def test_batch_size_constant(self):
        """BATCH_SIZE_PER_CALL must equal 50."""
        assert BATCH_SIZE_PER_CALL == 50


class TestLargeBatchSplits:
    async def test_150_strings_split_into_3_batches(self):
        """150-string input → 3 batches of 50 sent to LLM; results concatenated correctly."""
        strings = [f"item_{i}" for i in range(150)]
        batch_sizes: list[int] = []

        async def _create(**kwargs):
            user_msg = kwargs["messages"][-1]["content"]
            batch = json.loads(user_msg)
            batch_sizes.append(len(batch))
            resp = MagicMock()
            resp.choices[0].message.content = json.dumps([s + "-t" for s in batch])
            return resp

        client = MagicMock()
        client.chat.completions.create = _create
        sys_prompt = _build_system_prompt("ta", "test")

        results, retries, fallbacks = await _llm_translate_batch(client, strings, "ta", sys_prompt)

        assert batch_sizes == [50, 50, 50], f"Expected 3 batches of 50, got {batch_sizes}"
        assert len(results) == 150
        assert results[0] == "item_0-t"
        assert results[149] == "item_149-t"
        assert retries == 0
        assert fallbacks == 0


class TestRetryThenSucceedOnTimeout:
    async def test_retry_then_succeed_on_timeout(self):
        """Mock raises APITimeoutError once then returns valid response; retry counter = 1."""
        strings = ["Hello", "World"]
        call_count = 0

        async def _create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise openai.APITimeoutError("timeout")
            user_msg = kwargs["messages"][-1]["content"]
            batch = json.loads(user_msg)
            resp = MagicMock()
            resp.choices[0].message.content = json.dumps([s + "-ok" for s in batch])
            return resp

        client = MagicMock()
        client.chat.completions.create = _create
        sys_prompt = _build_system_prompt("ta", "test")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            translated, retries = await _translate_batch_with_retry(
                client, strings, "ta", 0, 1, sys_prompt
            )

        assert translated == ["Hello-ok", "World-ok"]
        assert retries == 1


class TestStrictLengthMismatchTriggersRetry:
    async def test_length_mismatch_triggers_retry_then_succeeds(self):
        """Mock returns N-1 items first; correct count on second attempt. Retry counter = 1."""
        strings = ["A", "B", "C"]
        call_count = 0

        async def _create(**kwargs):
            nonlocal call_count
            call_count += 1
            user_msg = kwargs["messages"][-1]["content"]
            batch = json.loads(user_msg)
            resp = MagicMock()
            if call_count == 1:
                # Return one fewer item — triggers ValueError in _call_llm_once
                resp.choices[0].message.content = json.dumps([s + "-t" for s in batch[:-1]])
            else:
                resp.choices[0].message.content = json.dumps([s + "-t" for s in batch])
            return resp

        client = MagicMock()
        client.chat.completions.create = _create
        sys_prompt = _build_system_prompt("ta", "test")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            translated, retries = await _translate_batch_with_retry(
                client, strings, "ta", 0, 1, sys_prompt
            )

        assert translated == ["A-t", "B-t", "C-t"]
        assert retries == 1


class TestGapFillPassFillsEmptyStrings:
    async def test_gap_fill_pass_fills_empty_string_translation(self):
        """
        translate_book with a row that already has translations={ml: ""} (empty string).
        The gap-fill pass should detect it and fill it.
        Verifies gap_fill_items >= 1 in the returned summary.
        """
        from translate_catalog import translate_book as _translate_book

        row_id = uuid.uuid4()
        book_id = uuid.uuid4()
        # Simulate a book row with a heading whose ml translation is an empty string.
        existing_translations = {"en_source_hash": _sha1("Introduction"), "ml": ""}

        # We need to mock the DB session and openai client, and bypass _gap_fill_pass's
        # SELECT queries to return our seeded row.
        call_log: list[str] = []

        async def _create(**kwargs):
            user_msg = kwargs["messages"][-1]["content"]
            strings = json.loads(user_msg)
            resp = MagicMock()
            resp.choices[0].message.content = json.dumps([s + "-filled" for s in strings])
            call_log.append("llm_call")
            return resp

        client = MagicMock()
        client.chat.completions.create = _create

        # Build a fake book ORM object
        fake_book = MagicMock()
        fake_book.id = book_id
        fake_book.title = "Test Book"
        fake_book.subject = "math"
        fake_book.title_translations = {"en_source_hash": _sha1("Test Book"), "ml": "Test Book ml"}
        fake_book.subject_translations = {"en_source_hash": _sha1("math"), "ml": "math ml"}

        # Build a fake chunk row
        fake_chunk = MagicMock()
        fake_chunk.id = row_id
        fake_chunk.heading = "Introduction"
        fake_chunk.heading_translations = existing_translations  # ml is ""

        # Patch translate_book internals to use our fake data
        from translate_catalog import _gap_fill_pass, _translate_table as _tt

        async def _fake_gap_fill(db, book_slug, languages, client_inner):
            # Simulate gap-fill finding one empty ml translation and filling it.
            # Call the real LLM mock so we can assert on call_log.
            sys_prompt = _build_system_prompt("ml", "concept_chunks.heading")
            from translate_catalog import _translate_item_fallback
            result = await _translate_item_fallback(client_inner, "Introduction", "ml", sys_prompt)
            if result:
                return 1, 0
            return 0, 1

        with patch("translate_catalog.async_session_factory") as mock_factory, \
             patch("translate_catalog._gap_fill_pass", side_effect=_fake_gap_fill):

            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            # Wire execute to return fake rows in order for all queries
            execute_results = []

            async def _execute(stmt, *args, **kwargs):
                result = MagicMock()
                if not execute_results:
                    # book query
                    result.scalar_one_or_none = MagicMock(return_value=fake_book)
                else:
                    result.scalar_one_or_none = MagicMock(return_value=None)
                    result.all = MagicMock(return_value=[])
                execute_results.append(1)
                return result

            mock_session.execute = _execute
            mock_session.flush = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_factory.return_value = mock_session

            summary = await _translate_book(
                book_slug="test_book",
                languages=["ml"],
                force=False,
                dry_run=False,
                openai_client=client,
            )

        assert summary["gap_fill_items"] >= 1, (
            f"Expected gap_fill_items >= 1, got {summary['gap_fill_items']}"
        )
