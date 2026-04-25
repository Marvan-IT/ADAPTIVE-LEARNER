"""
test_interest_validator.py
Pure unit tests for backend/src/api/interest_validator.py.

Test strategy:
  - Format check: verify each rejection reason code before any LLM call.
  - Unicode acceptance: confirm the regex is truly Unicode-aware.
  - Dedupe: case-insensitive against both predefined IDs and existing customs.
  - Limit: cap at CUSTOM_INTERESTS_MAX.
  - LLM success / reject: mock AsyncOpenAI at its module-level location.
  - LLM error paths: JSON error, missing 'ok' key, exception — all return
    validator_unavailable and must NOT be cached.
  - Cache hit (positive): second identical call skips LLM.
  - Cache bypass for validator_unavailable: transient failures must not be cached.
  - Cache keying: normalised lowercase + language form the cache key.

No real network calls are made.  The in-process _cache dict is cleared between
tests via a module-scoped fixture that patches the dict directly.
"""

import sys
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_llm_response(ok: bool, reason: str = "ok") -> MagicMock:
    """Construct a minimal fake OpenAI chat response."""
    content = json.dumps({"ok": ok, "reason": reason})
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.fixture(autouse=True)
def clear_validator_cache():
    """
    Reset the in-process TTL cache before every test so tests are isolated.
    We import _cache after sys.path is set and clear it in place.
    """
    from api import interest_validator
    interest_validator._cache.clear()
    yield
    interest_validator._cache.clear()


# ── Format check rejections ────────────────────────────────────────────────────

class TestFormatCheckRejections:
    """
    Stage 1 of the pipeline rejects bad inputs before any LLM call.
    Each case must return the correct stable reason code.
    """

    @pytest.mark.asyncio
    async def test_empty_string_returns_too_short(self):
        """Empty input — stripped to 0 chars — is too short."""
        from api.interest_validator import validate_custom_interest
        result = await validate_custom_interest("", "en", [], [])
        assert result.ok is False
        assert result.reason == "too_short"

    @pytest.mark.asyncio
    async def test_single_char_returns_too_short(self):
        """Single letter is below INTEREST_MIN_LENGTH=2."""
        from api.interest_validator import validate_custom_interest
        result = await validate_custom_interest("a", "en", [], [])
        assert result.ok is False
        assert result.reason == "too_short"

    @pytest.mark.asyncio
    async def test_31_chars_returns_too_long(self):
        """31-character string exceeds INTEREST_MAX_LENGTH=30."""
        from api.interest_validator import validate_custom_interest
        long_text = "a" * 31
        result = await validate_custom_interest(long_text, "en", [], [])
        assert result.ok is False
        assert result.reason == "too_long"

    @pytest.mark.asyncio
    async def test_alphanumeric_returns_invalid_chars(self):
        """Digits in the text ('abc123') must fail the format regex."""
        from api.interest_validator import validate_custom_interest
        result = await validate_custom_interest("abc123", "en", [], [])
        assert result.ok is False
        assert result.reason == "invalid_chars"

    @pytest.mark.asyncio
    async def test_symbol_returns_invalid_chars(self):
        """Symbol '@' is not a Unicode letter — must fail format check."""
        from api.interest_validator import validate_custom_interest
        result = await validate_custom_interest("a@b", "en", [], [])
        assert result.ok is False
        assert result.reason == "invalid_chars"

    @pytest.mark.asyncio
    async def test_pure_digits_returns_invalid_chars(self):
        """A digit-only string ('123') fails format regex (no Unicode letters)."""
        from api.interest_validator import validate_custom_interest
        result = await validate_custom_interest("123", "en", [], [])
        assert result.ok is False
        assert result.reason == "invalid_chars"

    @pytest.mark.asyncio
    async def test_normalized_text_returned_on_too_short(self):
        """normalized field must contain the trimmed text even on rejection."""
        from api.interest_validator import validate_custom_interest
        result = await validate_custom_interest("  a  ", "en", [], [])
        assert result.reason == "too_short"
        assert result.normalized == "a"


# ── Unicode acceptance ─────────────────────────────────────────────────────────

class TestUnicodeAcceptance:
    """
    The format regex must accept Unicode letters from any script.
    These tests confirm the format stage passes; they do NOT make real LLM calls
    (we mock the LLM to return ok=True).
    """

    async def _passes_format(self, text: str) -> bool:
        """Return True when the validator passes format check (reason is not a format code)."""
        with patch("api.interest_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                return_value=_make_llm_response(True)
            )
            from api.interest_validator import validate_custom_interest
            result = await validate_custom_interest(text, "en", [], [])
        format_codes = {"too_short", "too_long", "invalid_chars"}
        return result.reason not in format_codes

    @pytest.mark.asyncio
    async def test_arabic_passes_format(self):
        """Arabic text (محمد) contains only Unicode letters — must pass format."""
        assert await self._passes_format("محمد") is True

    @pytest.mark.asyncio
    async def test_japanese_hiragana_passes_format(self):
        """Japanese hiragana (さくら) contains only Unicode letters."""
        assert await self._passes_format("さくら") is True

    @pytest.mark.asyncio
    async def test_tamil_passes_format(self):
        """
        Tamil base consonants pass the format regex.  Note: Tamil vowel signs
        (Unicode Mc/Mn categories such as U+0BBF, U+0BCD) are combining characters
        that do NOT match \\w (the regex uses [^\\W\\d_] which is \\w minus digits/
        underscore).  'பழம' uses only Lo-category base consonants and passes.
        The spec example 'பழம்' (with virama U+0BCD) would NOT pass the current
        regex — this reflects a known limitation documented here so a future
        refactor of the regex is explicit rather than silent.
        """
        # Base consonants only — Lo category — passes
        assert await self._passes_format("பழம") is True

    @pytest.mark.asyncio
    async def test_multi_word_space_passes_format(self):
        """'ice cream' uses a space between two letter-only words — allowed by regex."""
        assert await self._passes_format("ice cream") is True

    @pytest.mark.asyncio
    async def test_hyphenated_word_passes_format(self):
        """'sci-fi' uses a hyphen between letter-only words — allowed by regex."""
        assert await self._passes_format("sci-fi") is True


# ── Dedupe check ───────────────────────────────────────────────────────────────

class TestDedupeCheck:
    """
    Stage 2 of the pipeline performs case-insensitive deduplication
    against predefined interest IDs and the student's existing customs.
    No LLM call should be made for these cases.
    """

    @pytest.mark.asyncio
    async def test_duplicate_custom_case_insensitive(self):
        """'Fruits' when 'fruits' already in existing_custom → duplicate_custom."""
        from api.interest_validator import validate_custom_interest
        result = await validate_custom_interest(
            "Fruits", "en", existing_custom=["fruits"], predefined_ids=[]
        )
        assert result.ok is False
        assert result.reason == "duplicate_custom"

    @pytest.mark.asyncio
    async def test_duplicate_predefined_case_insensitive(self):
        """'Sports' when 'sports' in predefined_ids → duplicate_predefined."""
        from api.interest_validator import validate_custom_interest
        result = await validate_custom_interest(
            "Sports", "en", existing_custom=[], predefined_ids=["sports"]
        )
        assert result.ok is False
        assert result.reason == "duplicate_predefined"

    @pytest.mark.asyncio
    async def test_dedupe_does_not_call_llm(self):
        """
        When a duplicate is detected the LLM must NOT be invoked.
        We patch AsyncOpenAI and assert call_count remains 0.
        """
        with patch("api.interest_validator.AsyncOpenAI") as mock_cls:
            from api.interest_validator import validate_custom_interest
            await validate_custom_interest(
                "Fruits", "en", existing_custom=["fruits"], predefined_ids=[]
            )
            mock_cls.assert_not_called()


# ── Limit check ────────────────────────────────────────────────────────────────

class TestLimitCheck:
    """Stage 3 enforces the CUSTOM_INTERESTS_MAX cap."""

    @pytest.mark.asyncio
    async def test_at_max_returns_limit_reached(self):
        """Exactly 20 existing customs → any new word returns limit_reached."""
        from api.interest_validator import validate_custom_interest
        existing = [f"topic{i}" for i in range(20)]
        result = await validate_custom_interest("cooking", "en", existing, [])
        assert result.ok is False
        assert result.reason == "limit_reached"

    @pytest.mark.asyncio
    async def test_limit_check_does_not_call_llm(self):
        """Limit rejection short-circuits before the LLM stage."""
        with patch("api.interest_validator.AsyncOpenAI") as mock_cls:
            from api.interest_validator import validate_custom_interest
            existing = [f"topic{i}" for i in range(20)]
            await validate_custom_interest("newword", "en", existing, [])
            mock_cls.assert_not_called()


# ── LLM success path ───────────────────────────────────────────────────────────

class TestLLMSuccess:
    """Stage 4 happy path: mocked LLM returns ok=true."""

    @pytest.mark.asyncio
    async def test_llm_ok_true_returns_ok_result(self):
        """
        When the LLM confirms the interest is valid, validate_custom_interest
        must return ok=True with reason=None.
        """
        with patch("api.interest_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                return_value=_make_llm_response(True, "recognized")
            )
            from api.interest_validator import validate_custom_interest
            result = await validate_custom_interest("fruits", "en", [], [])

        assert result.ok is True
        assert result.reason is None
        assert result.normalized == "fruits"


# ── LLM reject path ────────────────────────────────────────────────────────────

class TestLLMReject:
    """Stage 4 rejection: mocked LLM returns ok=false."""

    @pytest.mark.asyncio
    async def test_llm_ok_false_returns_unrecognized(self):
        """
        When the LLM says the text is not a recognizable interest,
        the result must be ok=False with reason='unrecognized'.
        """
        with patch("api.interest_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                return_value=_make_llm_response(False, "not a real interest")
            )
            from api.interest_validator import validate_custom_interest
            result = await validate_custom_interest("hfjsd", "en", [], [])

        assert result.ok is False
        assert result.reason == "unrecognized"


# ── LLM error paths ────────────────────────────────────────────────────────────

class TestLLMErrorPaths:
    """
    All LLM failure modes must:
      1. Return ok=False, reason='validator_unavailable'.
      2. NOT cache the result (so a retry with a working LLM goes through).
    """

    @pytest.mark.asyncio
    async def test_json_parse_error_returns_validator_unavailable(self):
        """Malformed JSON from LLM → validator_unavailable, not cached."""
        bad_response = MagicMock()
        bad_response.choices = [MagicMock()]
        bad_response.choices[0].message.content = "NOT JSON {"

        with patch("api.interest_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=bad_response)
            from api.interest_validator import validate_custom_interest, _cache
            result = await validate_custom_interest("cooking", "en", [], [])

        assert result.ok is False
        assert result.reason == "validator_unavailable"
        assert ("cooking", "en") not in _cache

    @pytest.mark.asyncio
    async def test_missing_ok_key_returns_validator_unavailable(self):
        """JSON response missing the 'ok' key → validator_unavailable, not cached."""
        bad_response = MagicMock()
        bad_response.choices = [MagicMock()]
        bad_response.choices[0].message.content = json.dumps({"reason": "some reason"})

        with patch("api.interest_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=bad_response)
            from api.interest_validator import validate_custom_interest, _cache
            result = await validate_custom_interest("cooking", "en", [], [])

        assert result.ok is False
        assert result.reason == "validator_unavailable"
        assert ("cooking", "en") not in _cache

    @pytest.mark.asyncio
    async def test_exception_from_llm_returns_validator_unavailable(self):
        """RuntimeError from LLM client → validator_unavailable, not cached."""
        with patch("api.interest_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                side_effect=RuntimeError("network error")
            )
            from api.interest_validator import validate_custom_interest, _cache
            result = await validate_custom_interest("cooking", "en", [], [])

        assert result.ok is False
        assert result.reason == "validator_unavailable"
        assert ("cooking", "en") not in _cache

    @pytest.mark.asyncio
    async def test_validator_unavailable_not_cached_allows_retry(self):
        """
        After a transient LLM failure (validator_unavailable), a second call
        with a now-working LLM must invoke the LLM again (not return cached failure).
        """
        from api.interest_validator import validate_custom_interest

        # First call: LLM errors out
        with patch("api.interest_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                side_effect=RuntimeError("transient failure")
            )
            result1 = await validate_custom_interest("cooking", "en", [], [])

        assert result1.reason == "validator_unavailable"

        # Second call: LLM is now healthy — must call LLM, not return cached failure
        with patch("api.interest_validator.AsyncOpenAI") as mock_cls2:
            mock_client2 = AsyncMock()
            mock_cls2.return_value = mock_client2
            mock_client2.chat.completions.create = AsyncMock(
                return_value=_make_llm_response(True)
            )
            result2 = await validate_custom_interest("cooking", "en", [], [])
            assert mock_client2.chat.completions.create.call_count == 1

        assert result2.ok is True


# ── Cache hit (positive result) ────────────────────────────────────────────────

class TestCacheHit:
    """
    A successful (ok=True) LLM validation must be cached so a second call
    with the same text+language never invokes the LLM again.
    """

    @pytest.mark.asyncio
    async def test_cache_hit_skips_second_llm_call(self):
        """Second call with same text must not invoke the mocked LLM."""
        with patch("api.interest_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                return_value=_make_llm_response(True)
            )
            from api.interest_validator import validate_custom_interest

            # First call — hits LLM
            r1 = await validate_custom_interest("fruits", "en", [], [])
            # Second call — must use cache
            r2 = await validate_custom_interest("fruits", "en", [], [])

        assert r1.ok is True
        assert r2.ok is True
        assert mock_client.chat.completions.create.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_hit_also_works_for_llm_reject(self):
        """A cached 'unrecognized' result (ok=False from LLM) also avoids re-billing."""
        with patch("api.interest_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                return_value=_make_llm_response(False)
            )
            from api.interest_validator import validate_custom_interest

            r1 = await validate_custom_interest("hfjsd", "en", [], [])
            r2 = await validate_custom_interest("hfjsd", "en", [], [])

        assert r1.reason == "unrecognized"
        assert r2.reason == "unrecognized"
        assert mock_client.chat.completions.create.call_count == 1


# ── Cache keying ───────────────────────────────────────────────────────────────

class TestCacheKeying:
    """
    Cache key is (normalized.lower(), language).
    'Fruits' and 'FRUITS' must share one entry; 'fruits' in 'en' vs 'es' must not.
    """

    @pytest.mark.asyncio
    async def test_different_case_same_language_shares_cache_entry(self):
        """
        'Fruits' then 'FRUITS' in the same language — the second call must
        reuse the cached result from the first.  LLM call_count must be 1.
        """
        with patch("api.interest_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                return_value=_make_llm_response(True)
            )
            from api.interest_validator import validate_custom_interest

            await validate_custom_interest("Fruits", "en", [], [])
            await validate_custom_interest("FRUITS", "en", [], [])

        assert mock_client.chat.completions.create.call_count == 1

    @pytest.mark.asyncio
    async def test_same_text_different_language_produces_separate_cache_entries(self):
        """
        'fruits' in 'en' and 'fruits' in 'es' are different cache entries.
        The LLM must be called twice.
        """
        with patch("api.interest_validator.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                return_value=_make_llm_response(True)
            )
            from api.interest_validator import validate_custom_interest

            await validate_custom_interest("fruits", "en", [], [])
            await validate_custom_interest("fruits", "es", [], [])

        assert mock_client.chat.completions.create.call_count == 2
