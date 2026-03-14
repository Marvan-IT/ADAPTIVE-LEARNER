# Master Card Generation Engine — Design Notes
Date: 2026-03-11

## Key Design Decisions

### Architecture
- Blueprint pipeline is a pure private function `_build_textbook_blueprint()` inside `teaching_service.py`. No new service or class.
- Replaces `_group_by_major_topic()` entirely. `cache_version` bumped to 3 to evict stale cached cards.
- No new API endpoints, no new DB tables in Phase 1.

### Section Classifier
- `_SECTION_CLASSIFIER`: ordered list of `(re.Pattern, SectionType)` tuples — first match wins.
- `SectionType(StrEnum)`: LEARNING_OBJECTIVES, EXAMPLE, TRY_IT, SOLUTION, HOW_TO, PREREQ_CHECK, TIP, END_MATTER, SUPPLEMENTARY.
- SOLUTION merges into preceding EXAMPLE text. TIP merges as "Pro tip:" suffix.
- PREREQ_CHECK and END_MATTER are skipped. Empty-result fallback: all sections become SUPPLEMENTARY with WARNING log.

### Domain Classifier
- `DomainType(StrEnum)`: TYPE_A (Arithmetic) through TYPE_G (Exponents). TYPE_E is default on tie/no match.
- Keyword frequency vote on lowercase text. Module-level `_DOMAIN_KEYWORDS` dict.

### Card Types (9)
TEACH, EXAMPLE, APPLICATION, QUESTION, EXERCISE, VISUAL, RECAP, FUN, CHECKIN
- New types vs. current: APPLICATION, EXERCISE added to schema `CARD_TYPES` literal.

### MCQ Difficulty
- `CardMCQ.difficulty: Literal["EASY", "MEDIUM", "HARD"] = "MEDIUM"` — additive, backward compatible.
- Delivery mode → difficulty mapping: STRUGGLING→EASY, NORMAL→MEDIUM, FAST→HARD.
- Delivery mode derived from `LearningProfile` speed/comprehension fields at prompt-build time. Not stored.

### Delivery Modes
- STRUGGLING: analogy-first, step-by-step labels, 6-step APPLICATION scaffold, EASY MCQ.
- NORMAL: balanced, MEDIUM MCQ.
- FAST: compact notation, consecutive TRY_IT merge into multi-part QUESTION, HARD MCQ.
- Injected as a block into `build_cards_system_prompt()` alongside domain-type distractor block.

### Frontend Changes
- `CardLearningView.jsx`: MCQ wrong × 2 auto-advance detected by `!!cardStates[idx]?.replacementMcq`. Dispatch `NEXT_CARD`. No backend change needed.
- Card type badges: APPLICATION (orange), EXERCISE (purple), EXAMPLE (blue), QUESTION (green).
- 13 locale files: new `cardType.*` keys.

### Phase 2 (deferred)
- `concept_card_cache` DB table: 3 LLM calls per concept (one per delivery mode), shared by all students.
- Alembic migration `006_concept_card_cache`. Expected 80–95% LLM cost reduction at scale.
- Phase 2 must not start until Phase 1 stable in production for 1+ week.

### Effort
- Total Phase 1: ~15.75 dev-days across backend, testing, frontend agents.
- Calendar time: ~6 days with 3 parallel agents.
- Phase 2 (future): ~5.75 dev-days.
