# Card Generation Rebuild (implemented 2026-03-10)

## Feature slug: `card-generation-rebuild`

## Core architectural change: per-section parallel generation
- Old: single LLM call for all sections, sections truncated to 600 chars
- New: `_generate_cards_per_section()` — one LLM call per section, all in parallel via `asyncio.gather`
- Gap-fill pass via `_find_missing_sections()` re-runs on sections with no card coverage

## New methods in TeachingService (teaching_service.py)
- `_generate_cards_per_section(system_prompt, concept_title, concept_overview, sections, latex, images, max_tokens_per_section)` — async, returns list[dict]
- `_find_missing_sections(cards, sections)` — static, returns sections whose title doesn't appear in any card
- `_extract_failed_topics_from_messages(messages, covered_topics)` — static, improved correction-phrase detection

## New config constants (config.py)
```python
CARDS_MAX_TOKENS_SLOW: int = 16_000
CARDS_MAX_TOKENS_SLOW_FLOOR: int = 8_000
CARDS_MAX_TOKENS_SLOW_PER_SECTION: int = 1_800
CARDS_MAX_TOKENS_NORMAL: int = 12_000
CARDS_MAX_TOKENS_NORMAL_FLOOR: int = 6_000
CARDS_MAX_TOKENS_NORMAL_PER_SECTION: int = 1_200
CARDS_MAX_TOKENS_FAST: int = 8_000
CARDS_MAX_TOKENS_FAST_FLOOR: int = 4_000
CARDS_MAX_TOKENS_FAST_PER_SECTION: int = 900
MAX_SOCRATIC_EXCHANGES = 30  # raised from 20
```

## build_cards_user_prompt() new params (prompts.py)
- `concept_overview: str | None = None` — first 400 chars of concept text
- `section_position: str | None = None` — e.g. "section 2 of 8"
When both are provided, a per-section preamble is prepended to the prompt.

## build_cards_system_prompt() new param (prompts.py)
- `remediation_weak_concepts: list[str] | None = None` — appends REMEDIATION RE-ATTEMPT block

## Socratic question scaling (prompts.py)
- `min_questions` and `max_questions` now scale with `len(covered_topics)`:
  `base_min = max(8, n_topics)`, `base_max = min(15, n_topics + 4)`
- SPREAD RULE added to scope block: distribute questions across ALL topics

## Path A 60/40 blend (teaching_service.py)
- `generate_cards()` now imports `build_blended_analytics, CardBehaviorSignals`
- Constructs synthetic `CardBehaviorSignals` from history averages
- Calls `build_blended_analytics(current_signals, history, concept_id, student_id)`
- Falls back to direct-history `AnalyticsSummary` if blending fails

---

# Master Card Generation Engine Upgrade (implemented 2026-03-11)

## Cache version bump: 6 → 7

## CardMCQ schema change (teaching_schemas.py)
- Added `difficulty: str = Field(default="MEDIUM", description="EASY | MEDIUM | HARD")` to `CardMCQ`
- `LessonCard.card_type` description updated to include APPLICATION, EXERCISE card types

## Module-level constants (teaching_service.py, after logger)
- `_SECTION_CLASSIFIER: list[tuple[str, str]]` — 9 regex patterns → section type names
  Types: LEARNING_OBJECTIVES, EXAMPLE, TRY_IT, SOLUTION, HOW_TO, SUPPLEMENTARY, TIP, PREREQ_CHECK, END_MATTER
- `_SECTION_DOMAIN_MAP: list[tuple[str, str]]` — 7 regex patterns → TYPE_A through TYPE_G

## New static methods on TeachingService (teaching_service.py)
- `_classify_sections(sections)` — tags each section dict with `section_type` key using `_SECTION_CLASSIFIER`
- `_build_textbook_blueprint(classified)` — ordered pedagogical blueprint:
  SOLUTION → merged into preceding EXAMPLE, TIP → merged into preceding item,
  SUPPLEMENTARY/PREREQ_CHECK/END_MATTER → dropped entirely
- `_classify_section_type(concept_id, concept_title)` → returns TYPE_A–G string

## generate_cards() flow change (teaching_service.py)
- Replaces `_group_by_major_topic()` call with blueprint pipeline:
  `classified = _classify_sections(sub_sections)` → `blueprint = _build_textbook_blueprint(classified)`
  Falls back to `_group_by_major_topic()` if blueprint yields < 2 items
- Computes `section_domain = _classify_section_type(concept_id, concept_title)`
- Passes `section_domain=section_domain` as new kwarg to `build_cards_system_prompt()`
- `_STALE_TITLE_RE` narrowed to only reject bare "solution", "how to", "(r)" — no longer rejects
  "Example 1.41", "Learning Objectives" etc. which are now valid blueprint titles

## prompts.py changes
- `build_cards_system_prompt()` gains `section_domain: str = "TYPE_A"` param
- CARD TYPES block: added APPLICATION, EXERCISE types; updated RECAP/FUN rules
- CARD SEQUENCE ORDER item 2: updated for APPLICATION cards + HOW_TO → one TEACH card rule
- New TEXTBOOK BLUEPRINT RULES block inserted before EXPLANATION RULES
  Covers [TYPE: LEARNING_OBJECTIVES], [TYPE: CONCEPT], [TYPE: HOW_TO], [TYPE: EXAMPLE],
  [TYPE: TRY_IT], [TYPE: TIP] with per-mode instructions
- MCQ QUALITY RULE block replaced with ## MCQ RULES block:
  Adds `difficulty` to MCQ FORMAT, DIFFICULTY BY DELIVERY MODE, MCQ RULES BY CARD TYPE,
  UNIVERSAL DISTRACTOR RULES with position randomization requirement
- Card schema JSON example updated to include `difficulty: "EASY|MEDIUM|HARD"` in question
- `_build_card_profile_block()`: STRUGGLING mode appends EXAMPLE/APPLICATION/MCQ-difficulty instructions
  FAST mode appends compact EXAMPLE, APPLICATION, QUESTION merging, HARD MCQ instructions
- `_DOMAIN_NOTES` dict (TYPE_A–G domain-specific rules) computed inside `build_cards_system_prompt()`
  `domain_block` injected just before `{images_block}` in base_prompt f-string
- `build_cards_user_prompt()` section headers: include `[TYPE: X]` tag when `section_type` key present
- `build_cards_user_prompt()` completeness checklist: includes `[TYPE]` tag in section list items
