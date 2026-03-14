# Hybrid Rolling Adaptive Card Generation (2026-03-14)

## Architecture

Cards are no longer generated all-at-once. Initial request generates first `STARTER_PACK_INITIAL_SECTIONS=2`
sub-sections only. Remaining sections stored in `concepts_queue` inside `session.presentation_text` JSON.
Each call to `POST /api/v2/sessions/{id}/next-section-cards` pops one section, generates cards with
live-signal adaptive mode blending, and appends to the cache.

## New Config Constants (config.py)
- `STARTER_PACK_INITIAL_SECTIONS = 2` — initial batch size
- `CARDS_MAX_TOKENS_SLOW_PER_SECTION = 6_000` (raised from 2_500)
- `CARDS_MAX_TOKENS_NORMAL_PER_SECTION = 4_500` (raised from 2_000)
- `CARDS_MAX_TOKENS_FAST_PER_SECTION = 3_000` (raised from 1_500)

## Session Cache JSON Shape (cache_version=11)
```json
{
  "cards": [...],
  "cache_version": 11,
  "concept_title": "...",
  "concepts_queue": [{sub_section dicts}],
  "concepts_covered": ["title1", "title2"],
  "concepts_total": 8,
  "system_prompt": "...",
  "_images": [...],
  "needs_review": [],
  "session_signals": [{"card_index": 0, "time_on_card_sec": 45, "wrong_attempts": 0, "hints_used": 0}]
}
```

## New API Endpoint (teaching_router.py)
`POST /api/v2/sessions/{id}/next-section-cards`
- Body: `NextSectionCardsRequest` (card_index, time_on_card_sec, wrong_attempts, hints_used, idle_triggers)
- Response: `NextSectionCardsResponse` (session_id, cards, has_more_concepts, concepts_total, concepts_covered_count, current_mode)
- Phase guard: PRESENTING or CARDS only
- Rate limit: 30/minute

## CardsResponse Rolling Metadata (teaching_schemas.py)
New fields on `CardsResponse`:
- `has_more_concepts: bool = False`
- `concepts_total: int = 0`
- `concepts_covered_count: int = 0`

## LessonCard.question2 (teaching_schemas.py)
`question2: CardMCQ | None` — second MCQ for same concept, shown when first is answered wrong.
Pre-generated with the card — no extra API call on wrong answer.

## Ceiling Removed (adaptive_router.py)
`_ADAPTIVE_CARD_CEILING` constant and `if len(existing_cards) >= _ADAPTIVE_CARD_CEILING:` guard
both deleted. The `complete-card` adaptive loop is now unlimited. Frontend gates "Finish Cards"
on `has_more_concepts == false`.

## Key Implementation Notes (teaching_service.py)

### _generate_cards_per_section signature change
Added `per_section_floor: int = 4_500` parameter.
`text_driven_budget = max(per_section_floor, text_len // 2)` — old 1500 floor removed.

### _section_index stamping (C6)
Inside `generate_for_section()`: `card["_section_index"] = idx` for stable integer sort.

### Gap-fill sort now integer-based (C7)
Old fuzzy `_section_order_key` + `sec_order` dict deleted.
Replaced by: `all_raw_cards.sort(key=lambda c: c.get("_section_index", len(sub_sections)))`

### generate_next_section_cards() method
Async instance method on `TeachingService`. Uses `load_student_history` + `build_blended_analytics`
from `adaptive.adaptive_engine` to compute live mode. Uses `_generate_cards_per_section` with a
single section. Appends new cards + updates `concepts_queue`/`concepts_covered`/`session_signals`
in the cache JSON.

### Starter pack split (C1)
```python
all_sub_sections = sub_sections[:]
sub_sections = all_sub_sections[:STARTER_PACK_INITIAL_SECTIONS]   # generate first N
concepts_queue = all_sub_sections[STARTER_PACK_INITIAL_SECTIONS:]  # remainder
```

## Prompts (prompts.py)
- Card JSON schema now includes `question2` field alongside `question`
- DUAL MCQ RULE added: always generate both `question` and `question2`; different scenario/numbers/wording
- OUTPUT FORMAT example updated to show `question2`
