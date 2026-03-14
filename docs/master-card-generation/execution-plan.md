# Master Card Generation Engine — Execution Plan

**Feature name:** Master Card Generation Engine
**Date:** 2026-03-11
**Status:** Design complete — awaiting stakeholder approval

---

## Agentic Workflow Stages

This project follows the ADA 5-stage agentic workflow:

| Stage | Agent | Trigger |
|-------|-------|---------|
| Stage 0 | `devops-engineer` | Data verification (card_interactions schema check) |
| Stage 1 | `solution-architect` | Design complete (this document) |
| Stage 2 | `backend-developer` | DLD approved |
| Stage 3 | `comprehensive-tester` | Backend implementation complete |
| Stage 4 | `frontend-developer` | Backend tests passing |

---

## 1. Work Breakdown Structure (WBS) — Phase 1

### Stage 0 — Infrastructure (devops-engineer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| S0-01 | Verify `card_interactions` schema | Confirm `card_type VARCHAR(32)` accepts new values: EXAMPLE, APPLICATION, QUESTION, EXERCISE. Log findings. No migration needed if column is already VARCHAR(32). | 0.25d | None | DB |
| S0-02 | Add `pytest` test module scaffold | Create `backend/tests/test_blueprint.py` and `backend/tests/test_prompt_builder.py` as empty test files with module docstrings. Confirm `conftest.py` imports. | 0.25d | S0-01 | Testing infra |

**Stage 0 total: 0.5 dev-days**

---

### Stage 2 — Backend (backend-developer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P2-01 | Add `SectionType` and `DomainType` enums | Define `SectionType(StrEnum)` and `DomainType(StrEnum)` in `teaching_service.py`. | 0.25d | S0-01 | teaching_service.py |
| P2-02 | Implement `_SECTION_CLASSIFIER` constant | Define ordered list of `(re.Pattern, SectionType)` tuples as module-level constant. Include all 8 named types. | 0.5d | P2-01 | teaching_service.py |
| P2-03 | Implement `_classify_section()` | Iterate `_SECTION_CLASSIFIER`, return first match; default to SUPPLEMENTARY. | 0.25d | P2-02 | teaching_service.py |
| P2-04 | Define `BlueprintItem` dataclass | Add `@dataclass` with fields: `section_type`, `heading`, `text`, `index`, `domain_type`. | 0.25d | P2-01 | teaching_service.py |
| P2-05 | Implement `_build_textbook_blueprint()` | Full algorithm: classify each section, skip PREREQ_CHECK/END_MATTER/LEARNING_OBJECTIVES, merge SOLUTION into preceding EXAMPLE, merge TIP as "Pro tip:" suffix, empty-result fallback with WARNING log. | 1.0d | P2-03, P2-04 | teaching_service.py |
| P2-06 | Implement `_DOMAIN_KEYWORDS` and `_classify_domain()` | Keyword frequency vote per DomainType; TYPE_E default on tie or no match. | 0.5d | P2-01 | teaching_service.py |
| P2-07 | Add `difficulty` field to `CardMCQ` schema | `difficulty: Literal["EASY", "MEDIUM", "HARD"] = "MEDIUM"` with default. Verify backward compatibility with existing cache entries. | 0.25d | None | teaching_schemas.py |
| P2-08 | Expand `CARD_TYPES` literal and `LessonCard` schema | Add APPLICATION, QUESTION, EXERCISE to `CARD_TYPES`. Add `difficulty` and `domain_type` fields to `LessonCard`. | 0.25d | P2-07 | teaching_schemas.py |
| P2-09 | Implement delivery mode derivation | Add `_get_delivery_mode(profile: LearningProfile) -> str` returning "STRUGGLING" / "NORMAL" / "FAST" using LearningProfile speed/comprehension fields. | 0.25d | None | teaching_service.py |
| P2-10 | Add delivery mode prompt blocks to `build_cards_system_prompt()` | Inject STRUGGLING / NORMAL / FAST instruction blocks. Each block includes analogy-first rule, 6-step APPLICATION scaffold (STRUGGLING), multi-part merge rule (FAST), and MCQ difficulty instruction. | 1.0d | P2-09 | prompts.py |
| P2-11 | Add per-type MCQ rules to `build_cards_system_prompt()` | Inject per-card-type MCQ generation rules: TEACH (definition test), EXAMPLE (different numbers), APPLICATION (operation identification), QUESTION (quick recall). | 0.5d | P2-10 | prompts.py |
| P2-12 | Add domain-type distractor blocks to `build_cards_system_prompt()` | Inject domain-specific distractor strategy per TYPE_A–G. | 0.5d | P2-10 | prompts.py |
| P2-13 | Add correct-answer randomisation instruction | Add prompt rule: "Randomize the correct answer position across a, b, c, d — do not always place the correct answer in position 0 or 1." | 0.25d | P2-10 | prompts.py |
| P2-14 | Update `build_cards_user_prompt()` for blueprint items | Replace flat sub-section list with structured blueprint block format: `[BLUEPRINT ITEM N — type: X — domain: Y]`. | 0.5d | P2-05, P2-06 | prompts.py |
| P2-15 | Wire blueprint pipeline into `generate_cards()` | Replace `_group_by_major_topic()` call with `_build_textbook_blueprint()`. Pass `domain_type` list to prompt builder. Pass delivery mode to prompt builder. | 0.5d | P2-05, P2-09, P2-14 | teaching_service.py |
| P2-16 | Update `validate_and_repair_cards()` for new card types | Ensure unknown `card_type` values default to "TEACH" (not dropped). Ensure missing `difficulty` is handled (Pydantic default covers this). | 0.25d | P2-08 | teaching_service.py |
| P2-17 | Increment `cache_version` to 3 | Forces regeneration of all cached card sets using the new blueprint pipeline. | 0.25d | P2-15 | teaching_service.py |
| P2-18 | Add new structured log lines | Add `INFO` log for blueprint construction stats and delivery mode. Add `DEBUG` logs for domain classification and MCQ difficulty. | 0.25d | P2-15 | teaching_service.py |

**Stage 2 total: 7.75 dev-days**

---

### Stage 3 — Testing (comprehensive-tester)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P3-01 | Unit tests for `_classify_section()` | Cover all 8 named types + SUPPLEMENTARY default, case-insensitivity, empty string. | 0.5d | P2-03 | tests/test_blueprint.py |
| P3-02 | Unit tests for `_build_textbook_blueprint()` | Cover SOLUTION merge, TIP merge, PREREQ_CHECK skip, empty fallback + WARNING log assertion. | 0.75d | P2-05 | tests/test_blueprint.py |
| P3-03 | Unit tests for `_classify_domain()` | Cover all 7 domain types, tie-break to TYPE_E, no-match default. | 0.5d | P2-06 | tests/test_blueprint.py |
| P3-04 | Unit tests for `CardMCQ` schema changes | `difficulty` default "MEDIUM", invalid value raises `ValidationError`, correct_index bounds. | 0.25d | P2-07 | tests/test_schemas.py |
| P3-05 | Unit tests for delivery mode derivation | SLOW speed → STRUGGLING, FAST+STRONG → FAST, all other combinations → NORMAL. | 0.25d | P2-09 | tests/test_prompt_builder.py |
| P3-06 | Prompt content assertions for delivery modes | Assert STRUGGLING system prompt contains "Step 1:", FAST prompt contains "multi-part", NORMAL is neither. | 0.5d | P2-10 | tests/test_prompt_builder.py |
| P3-07 | Integration test: full `generate_cards()` with blueprint | Use `PREALG.C1.S1` fixture; assert output contains at least one EXAMPLE card and at least one card with `difficulty` field set. | 0.75d | P2-15 | tests/test_cards_integration.py |
| P3-08 | Integration test: STRUGGLING profile → EASY MCQ | Assert all `question.difficulty == "EASY"` when profile is STRUGGLING. | 0.5d | P2-07, P2-15 | tests/test_cards_integration.py |
| P3-09 | Integration test: empty blueprint fallback | Provide concept fixture with only PREREQ_CHECK sections; assert non-empty card set returned. | 0.5d | P2-05 | tests/test_cards_integration.py |
| P3-10 | Performance test: P95 latency by profile | Measure wall-clock time for card generation across 3 profiles. Document results. Fail if STRUGGLING P95 > 18s or NORMAL P95 > 12s. | 0.5d | P2-15 | tests/test_perf.py |
| P3-11 | MCQ correct_index distribution test | Generate 100 cards; assert correct_index is not always 0 (chi-squared or simple frequency check). | 0.25d | P2-13 | tests/test_cards_integration.py |

**Stage 3 total: 5.25 dev-days**

---

### Stage 4 — Frontend (frontend-developer)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|--------------|-----------|
| P4-01 | Add card type badge component | Define `CARD_TYPE_BADGE` map. Render badge in card header for APPLICATION, EXERCISE, EXAMPLE, QUESTION types. WCAG 2.1 AA contrast check. | 0.5d | None | CardLearningView.jsx |
| P4-02 | Implement MCQ wrong × 2 auto-advance | In `handleMCQAnswer`: check `!!cardStates[currentCardIndex]?.replacementMcq` on wrong answer; if true dispatch `NEXT_CARD`; else existing regen flow. | 0.5d | None | CardLearningView.jsx |
| P4-03 | Add i18n keys for new card type labels | Add `cardType.application`, `cardType.exercise`, `cardType.example`, `cardType.question` to all 13 locale JSON files. | 0.5d | P4-01 | locales/*.json |
| P4-04 | Smoke test: card type badge renders | Manual or Playwright check that APPLICATION badge renders orange, EXERCISE renders purple. | 0.25d | P4-01, P4-03 | E2E |
| P4-05 | Smoke test: wrong × 2 auto-advance | Manual session: answer wrong twice on same card; verify auto-advance without hang. | 0.25d | P4-02 | E2E |

**Stage 4 total: 2.0 dev-days**

---

## 2. Phased Delivery Plan

### Phase 1 — Foundation (Stage 0 + Stage 2 core)
**Tasks:** S0-01, S0-02, P2-01 through P2-06
**Goal:** Section classifier and blueprint builder implemented and verifiable in isolation. No changes yet to prompts or card generation call path.
**Duration:** ~2 calendar days

### Phase 2 — Core Functionality (Stage 2 continued)
**Tasks:** P2-07 through P2-18
**Goal:** Full pipeline wired into `generate_cards()`. New prompt rules active. `cache_version` bumped to 3. Existing integration confirmed unbroken.
**Duration:** ~3 calendar days

### Phase 3 — Testing (Stage 3)
**Tasks:** P3-01 through P3-11
**Goal:** All unit and integration tests pass. Performance benchmarks documented. MCQ distribution verified.
**Duration:** ~3 calendar days

### Phase 4 — Frontend (Stage 4)
**Tasks:** P4-01 through P4-05
**Goal:** Card type badges rendered. Wrong × 2 auto-advance deployed. All 13 locales updated.
**Duration:** ~1 calendar day (parallel with Stage 3 P3-10/P3-11)

### Phase 5 — Hardening and Release
**Tasks:** Cache version verification in staging, load test, PostHog event check, runbook update.
**Goal:** Production-ready. Rollout via `cache_version: 3` (automatic stale-cache eviction).
**Duration:** 0.5 calendar days

---

## 3. Dependencies and Critical Path

```
S0-01 ──▶ S0-02
           │
           ▼
P2-01 ──▶ P2-02 ──▶ P2-03 ──▶ P2-05 ──▶ P2-15 ──▶ P2-17 ──▶ P3-07
           │                    │           │
           ▼                    ▼           ▼
          P2-04               P2-06       P2-09 ──▶ P2-10 ──▶ P2-11
                                           │           │
                                           ▼           ▼
                                         P3-05       P2-12 ──▶ P2-13
                                                       │
                                                       ▼
                                                     P2-14 ──▶ P2-15

P2-07 ──▶ P2-08 ──▶ P3-04
P2-15 ──▶ P3-07, P3-08, P3-09, P3-10, P3-11

P4-01 ──▶ P4-03 ──▶ P4-04
P4-02 ──▶ P4-05
```

**Critical path:** P2-01 → P2-02 → P2-03 → P2-05 → P2-06 → P2-14 → P2-15 → P2-17 → P3-07 → Phase 5

**External blocking dependencies:**
- Stage 0 completion (S0-01 schema verification) must precede P2-08 finalization.
- `cache_version: 3` bump (P2-17) must not be deployed until all backend tests pass (P3-07 through P3-11).

---

## 4. Definition of Done

### Phase 1 (Foundation)
- [ ] `_SECTION_CLASSIFIER` covers all 8 named `SectionType` values
- [ ] `_build_textbook_blueprint()` returns non-empty output for any valid concept
- [ ] Empty-result fallback emits WARNING log and returns SUPPLEMENTARY items
- [ ] `_classify_domain()` returns one of 7 domain types for any text input
- [ ] All Phase 1 unit tests pass (P3-01, P3-02, P3-03)

### Phase 2 (Core Functionality)
- [ ] `LessonCard` includes `difficulty` and `domain_type` fields
- [ ] `CardMCQ.difficulty` defaults to "MEDIUM"; invalid values rejected by Pydantic
- [ ] System prompt includes delivery-mode block and domain-type distractor block
- [ ] User prompt uses blueprint item format with `[BLUEPRINT ITEM N — type: X — domain: Y]`
- [ ] `generate_cards()` uses `_build_textbook_blueprint()` (not `_group_by_major_topic()`)
- [ ] `cache_version` set to 3
- [ ] Structured log lines present for blueprint stats, delivery mode, MCQ difficulty
- [ ] No regression in existing card generation for NORMAL profile

### Phase 3 (Testing)
- [ ] All 11 test cases (P3-01 through P3-11) pass
- [ ] STRUGGLING P95 latency < 18s (documented)
- [ ] NORMAL P95 latency < 12s (documented)
- [ ] MCQ correct_index not uniformly 0 across 100 generated cards
- [ ] Integration test with empty blueprint fallback passes

### Phase 4 (Frontend)
- [ ] APPLICATION card badge renders (orange, WCAG 2.1 AA contrast)
- [ ] EXERCISE card badge renders (purple, WCAG 2.1 AA contrast)
- [ ] Wrong × 2 auto-advance works without page reload or hang
- [ ] All 13 locale files contain new `cardType.*` keys
- [ ] Smoke tests P4-04 and P4-05 pass

### Phase 5 (Release)
- [ ] Staging deployment confirms `cache_version: 3` eviction of stale cards
- [ ] PostHog `card_generated` events include `card_type`, `difficulty`, `domain_type`
- [ ] No increase in card generation error rate vs. pre-deployment baseline
- [ ] Runbook updated with new log line reference

---

## 5. Rollout Strategy

### Deployment Approach
No feature flag required. The blueprint pipeline is a drop-in replacement for `_group_by_major_topic()`. The `cache_version: 3` bump acts as a natural rollout gate — all concepts regenerate on first access, not all at once.

**Deploy sequence:**
1. Deploy backend (Phase 2 complete, tests passing).
2. Deploy frontend (badge rendering + wrong × 2 fix).
3. Monitor error rate on `POST /api/v2/sessions/{id}/cards` for 30 minutes.
4. Monitor `blueprint empty fallback` log count — expected: 0 for all known OpenStax Prealgebra concepts.

### Rollback Plan
- Backend: revert `teaching_service.py` and `prompts.py` to previous commit. Decrement `cache_version` back to 2. Stale cards from version 2 will be served.
- Frontend: revert `CardLearningView.jsx` to remove badge rendering and wrong × 2 logic. No DB change required.
- Rollback is independent for backend and frontend (frontend changes are purely additive UI).

### Post-launch Validation
- [ ] Verify at least 3 distinct `card_type` values appear in first 24 hours of PostHog `card_generated` events
- [ ] Verify `difficulty` distribution is not 100% "MEDIUM" (indicates delivery mode derivation is working)
- [ ] Confirm no `blueprint empty fallback` WARNING logs in production for Prealgebra book
- [ ] MCQ wrong × 2 auto-advance: check for absence of stuck-session support tickets

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Agent |
|-------|-----------|-----------------|-------|
| Phase 1 — Foundation | Section classifier, blueprint builder, domain classifier | 2.75 dev-days | backend-developer |
| Phase 2 — Core Functionality | Schema changes, prompt rules, pipeline wiring, cache bump | 5.25 dev-days | backend-developer |
| Phase 3 — Testing | 11 test cases, integration, performance | 5.25 dev-days | comprehensive-tester |
| Phase 4 — Frontend | Badges, wrong × 2 fix, i18n | 2.0 dev-days | frontend-developer |
| Phase 5 — Release | Staging validation, monitoring, runbook | 0.5 dev-days | devops-engineer |
| **Total Phase 1** | | **15.75 dev-days** | 3 agents |
| | | | |
| **Phase 2 — Concept Card Cache (future)** | DB table, Alembic migration, cache lookup in generate_cards(), cache invalidation on re-index | **~8 dev-days** | backend-developer + devops-engineer |

**With 3 agents working in parallel (Stages 2, 3, 4 overlap after Phase 1):**
Estimated calendar time: ~6 working days.

---

## Phase 2 — Concept-Level Shared Card Cache (Future Scope)

### Problem
Every student generates their own LLM card set per concept. At scale (1000+ students on the same concept), this is 1000+ identical or near-identical LLM calls.

### Solution
Pre-generate exactly 3 card sets per concept (one per delivery mode: STRUGGLING, NORMAL, FAST) and cache them in a new `concept_card_cache` PostgreSQL table. All students sharing the same delivery mode receive the same cached set. Cache is invalidated when the concept is re-indexed (ChromaDB update).

### Phase 2 WBS (indicative)

| ID | Title | Effort | Agent |
|----|-------|--------|-------|
| C2-01 | Alembic migration `006_concept_card_cache` | 0.5d | devops-engineer |
| C2-02 | ORM model `ConceptCardCache` | 0.25d | backend-developer |
| C2-03 | Cache lookup in `generate_cards()` (read path) | 0.5d | backend-developer |
| C2-04 | Cache write after LLM generation | 0.5d | backend-developer |
| C2-05 | Cache invalidation on concept re-index | 0.5d | backend-developer |
| C2-06 | Admin endpoint `DELETE /api/v1/concepts/{id}/cache` | 0.5d | backend-developer |
| C2-07 | Background pre-warm job (optional) | 1.0d | backend-developer |
| C2-08 | Integration tests for cache hit/miss paths | 1.0d | comprehensive-tester |
| C2-09 | Load test: 100 concurrent students, 1 concept | 0.5d | comprehensive-tester |
| C2-10 | Monitoring: cache hit rate metric in PostHog | 0.5d | frontend-developer |
| **Total** | | **5.75 dev-days** | |

**Expected impact:** 80–95% reduction in LLM calls for active concepts. Latency for cached responses drops to < 50ms (DB read only).

**Phase 2 prerequisite:** Phase 1 complete and stable in production for at least 1 week.

---

## Key Decisions Requiring Stakeholder Input

1. **EXERCISE card inclusion** — Should END_MATTER numbered practice problems generate EXERCISE cards, or should all END_MATTER be skipped in Phase 1? This affects scope of P2-05 and P3-09.
2. **Phase 2 cache timeline** — Should Phase 2 be designed alongside Phase 1 implementation (to avoid a second DB migration) or deferred until Phase 1 metrics show scale need?
3. **Cache invalidation trigger** — Who owns the concept re-index pipeline? The devops-engineer or backend-developer? This determines which agent owns C2-05.
4. **Wrong × 2 behavior for STRUGGLING students** — Auto-advance may remove a learning opportunity for students who genuinely need more attempts. Should STRUGGLING mode instead show a "Show answer" button rather than auto-advancing?
