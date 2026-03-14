# Section Coverage Fix: Premature "Finish Cards" Bug

## Date
2026-03-14

## Problem
Students hit "Finish Cards" before all textbook section content is covered.
The card deck ended after 4–8 cards even though the concept had 10–15 sub-sections.

## Root Cause
`STARTER_PACK_MAX_SECTIONS = 2` in `config.py` truncated all section cards to the first 2
sub-sections. Sub-sections 3–N never received cards. The adaptive loop (`/complete-card`)
was incorrectly assumed to cover remaining sections — it does not; it only generates
replacement cards for already-visible sections using the full concept text.

Additionally, the token ceilings (`CARDS_MAX_TOKENS_*`) were too low to accommodate
all sections: with 15 sections, the ceiling divided per-section budget below 1,100 tokens —
insufficient for a complete card.

## Fix

### `backend/src/config.py`
| Constant | Before | After |
|----------|--------|-------|
| `STARTER_PACK_MAX_SECTIONS` | `2` | `15` |
| `CARDS_MAX_TOKENS_SLOW` | `20_000` | `40_000` |
| `CARDS_MAX_TOKENS_NORMAL` | `16_000` | `32_000` |
| `CARDS_MAX_TOKENS_FAST` | `12_000` | `24_000` |

### `backend/src/api/teaching_service.py`
- `_CARDS_CACHE_VERSION` (local in `generate_cards()`): `9` → `10`

## Effect
- Sessions now generate cards for all concept sub-sections (up to 15) in the initial batch
- Token budget per section stays at 2,000 tokens (NORMAL) — only the ceiling was raised
- GPT-4o-mini handles 15 parallel per-section calls efficiently
- All 3 delivery modes (STRUGGLING / NORMAL / FAST) now cover full section content
- Cache version bump forces stale 2-section decks to regenerate

## Flow After Fix
1. All section cards loaded at session start (30–45 cards for typical concept)
2. Student completes all cards → "Finish Cards" appears on the LAST card
3. Student clicks "Finish Cards" → Socratic chat begins
4. Socratic chat assesses full concept mastery (not just 2 sub-sections)
