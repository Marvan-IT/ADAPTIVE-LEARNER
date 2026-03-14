# Hybrid Rolling Adaptive Card Generation — Key Design Decisions (2026-03-14)

## Problem Solved
5 confirmed bugs: token starvation (2-3 cards/section), RC4 fuzzy sort order, same MCQ repeat, no real-time adaptation, "Finish Cards" visible before all sections delivered.

## Core Architecture Pattern
Client-driven rolling window. Backend stateless per request. All rolling state in `presentation_text` JSON blob (no DB schema change). Frontend fires pre-fetch at 2-card lookahead.

## Key Design Decisions

### State Storage (ADR-01)
- `concepts_queue` stored in existing `presentation_text` TEXT column as v11 JSON
- Fields: `version=11`, `presentation`, `cached_cards`, `concepts_queue`, `generated_sections`, `total_sections`
- Zero DB migration — existing column already holds JSON blob

### `question2` Pre-generation (ADR-02)
- Second MCQ generated in same LLM call as `question` (~150 tokens overhead)
- Frontend swaps to `question2` on first wrong answer — zero API call (eliminates B3 bug)
- `difficulty` must be MEDIUM or HARD; `correct_index` must differ from `question.correct_index`

### Rolling Fetch Trigger (ADR-03)
- Frontend fires `POST /next-section-cards` when `cards.length - 1 - currentCardIndex <= 2`
- Non-blocking (fire-and-forget); card advance does NOT wait for response
- `ROLLING_PREFETCH_TRIGGER_DISTANCE = 2` in `config.py`

### Ordering Fix (ADR-04)
- `_section_index: int` stamped on every card by `_stamp_section_index()` at generation time
- Replaces RC4 fuzzy sort entirely: `cards.sort(key=lambda c: c.get("_section_index", 0))`

### Cache Version
- Bumped to 11 (forces stale bulk-gen sessions to regenerate)
- `pt.get("version", 0) < 11` is the miss condition (handles missing key safely)

## New Endpoints
- `POST /api/v2/sessions/{id}/next-section-cards` — v2 (session-scoped resource)
- Returns `204 No Content` when queue already empty (idempotent; requires Axios `validateStatus`)
- Rate limit: `RATE_LIMIT_LLM_HEAVY` (10/minute)

## New Config Constants
- `STARTER_PACK_INITIAL_SECTIONS = 2`
- `ROLLING_PREFETCH_TRIGGER_DISTANCE = 2`
- Floor changes: `SLOW_FLOOR: 8000→6000`, `NORMAL_FLOOR: 6000→4500`, `FAST_FLOOR: 4000→3000`

## New Schemas (teaching_schemas.py)
- `LessonCard.question2: CardMCQ | None = None`
- `CardsResponse.has_more_concepts: bool = False`
- `CardsResponse.sections_total: int = 0`
- `CardsResponse.sections_done: int = 0`
- `NextSectionCardsRequest` (empty body, reserved)
- `NextSectionCardsResponse`

## Frontend State Additions (SessionContext.jsx)
- New state: `hasMoreConcepts`, `sectionsTotal`, `sectionsDone`
- New reducer actions: `APPEND_CARDS`, `SET_HAS_MORE_CONCEPTS`
- `CARDS_LOADED` updated to extract rolling metadata from starter pack response
- `MAX_ADAPTIVE_CARDS` removed entirely

## goToNextCard() 3-Case Logic
- Case A: `wrongAttempts >= 2` → POST /complete-card (recovery, unlimited)
- Case B: `cardsFromEnd <= 2 && hasMoreConcepts && !adaptiveCallInFlight` → background POST /next-section-cards
- Case D: all other cases → recordCardInteraction + NEXT_CARD

## Ceiling Removal
- `_ADAPTIVE_CARD_CEILING = 20` deleted from `adaptive_router.py` (line 32 + guard block line 227)
- Recovery cards are now unlimited

## Removed Constants
- `STARTER_PACK_MAX_SECTIONS = 50` deprecated (still in config.py — confirm removal with backend dev)

## Conflict Registry Key Items
- C11: `204` response from `next-section-cards` requires `validateStatus: (s) => s < 500` in Axios
- C12: `complete-cards` handler needs guard: if `concepts_queue` non-empty → 409
- C14: Cache version check must use `pt.get("version", 0) < 11` (handles missing `version` key)

## Effort Summary
- Backend: 7.75 dev-days
- Testing: 8.25 dev-days
- Frontend: 5.0 dev-days
- Total: ~20.5 dev-days; ~6-7 calendar days with 3 engineers
