# Real-Time Adaptive Cards — Design Notes

**Feature designed:** 2026-03-10
**Docs location:** `docs/real-time-adaptive-cards/`

## Key Design Decisions

- **Starter pack limit:** `STARTER_PACK_MAX_SECTIONS = 2` in `config.py` (line 54). Applied after `_group_by_major_topic()` in `generate_cards()`. Remaining sections covered by the adaptive loop on demand.
- **Per-section parallel generation:** `_generate_cards_per_section()` uses `asyncio.gather` — one LLM call per section, results merged in index order.
- **Text-driven token budget formula:** `max(budget//2, min(budget, text_len//3))` per section. `budget` is profile-adaptive (SLOW: 8000–16000; NORMAL: 6000–12000; FAST: 4000–8000).
- **Cache version:** `_CARDS_CACHE_VERSION = 3` as local constant inside `generate_cards()`. Bumping to 4 in future forces one-time regeneration for all cached sessions.
- **Envelope preservation:** `complete_card()` in `adaptive_router.py` reads full `presentation_text`, updates `cards` list in-place, writes envelope back. Dual-format read handles legacy list format and envelope dict format.
- **`_ADAPTIVE_CARD_CEILING = 20`:** Module-level constant in `adaptive_router.py` (NOT in `config.py`). Caps adaptive completions per session.
- **`REPLACE_UPCOMING_CARD` reducer:** Targets `currentCardIndex + 1`. Replace if slot exists; append otherwise. Re-stamps `index` field on replaced card.
- **`adaptiveCallInFlight` guard:** Boolean in `initialState`. Set by `ADAPTIVE_CALL_STARTED`, cleared in `finally` by `ADAPTIVE_CALL_DONE`. Prevents concurrent LLM calls; second rapid click only records interaction.
- **Gap-fill sort:** `_section_order_key()` — substring match of section titles against card text + content. Unknown section → sorted to end.
- **VISUAL image fallback:** Keyword-scoring over unassigned image pool. Word overlap (length > 3) between card text and image vision description. Pool exhaustion → share already-assigned image.
- **Rate limits:** `POST /complete-card` = 60/minute; `POST /api/v3/adaptive/lesson` = 10/minute.
- **Interaction persistence:** `CardInteraction` row saved with `flush()` + `commit()` BEFORE LLM call in `complete_card()` — signal is never lost on LLM timeout.
- **Effort:** ~5.3 engineer-days; 3 calendar days with 2 engineers + 1 tester.

## Architecture Pattern

Rolling Adaptive Replace (Prefetch-then-Replace):
1. Session start → starter pack (2 sections, fast)
2. Student reads card N → background `complete-card` call for card N+1
3. `REPLACE_UPCOMING_CARD` silently replaces N+1 slot
4. Student advances to N+1 — personalised card already waiting, zero wait

## Files Changed

- `backend/src/config.py` — `STARTER_PACK_MAX_SECTIONS`, token budget constants
- `backend/src/api/teaching_service.py` — starter pack slice, `_generate_cards_per_section`, gap-fill sort, VISUAL fallback, cache version
- `backend/src/adaptive/adaptive_router.py` — envelope preservation, `_ADAPTIVE_CARD_CEILING`, dual-format read
- `frontend/src/context/SessionContext.jsx` — `adaptiveCallInFlight`, `REPLACE_UPCOMING_CARD`, `ADAPTIVE_CALL_STARTED/DONE`
