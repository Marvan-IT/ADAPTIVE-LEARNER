# Master Card Generation Engine — High-Level Design

**Feature name:** Master Card Generation Engine
**Date:** 2026-03-11
**Status:** Design complete — awaiting stakeholder approval

---

## 1. Executive Summary

### Feature / System Name and Purpose
The Master Card Generation Engine replaces ADA's current flat-section card pipeline with a pedagogically-structured blueprint pipeline. It introduces a section-type classifier, 9 distinct card types, a 3-tier MCQ difficulty system, delivery-mode-specific prompt rules, and a frontend auto-advance safety valve for repeated wrong answers.

### Business Problem Being Solved
The current engine treats every `##` sub-section as a homogeneous text blob. Worked examples, Try-It exercises, definitions, and end-matter supplements are indistinguishable to the LLM, producing cards that:
- Lose the step-by-step reasoning embedded in textbook examples
- Provide no APPLICATION or EXERCISE card types for transfer learning
- Generate MCQs with no per-type strategy or difficulty graduation
- Leave STRUGGLING students permanently stuck when MCQ wrong × 2

### Key Stakeholders
- Product: Adaptive learning quality and student completion rates
- Engineering: Backend (FastAPI/prompts), Frontend (React card UI)
- Curriculum: Alignment with OpenStax pedagogical structure

### Scope

**Included:**
- `_SECTION_CLASSIFIER` regex-based section type classifier
- `_build_textbook_blueprint()` pipeline replacing `_group_by_major_topic()`
- Section Domain Classifier (TYPE_A through TYPE_G)
- 9 card type taxonomy (TEACH, EXAMPLE, APPLICATION, QUESTION, EXERCISE, VISUAL, RECAP, FUN, CHECKIN)
- MCQ difficulty system (EASY / MEDIUM / HARD) mapped to learner profile
- Per-type MCQ prompt rules and distractor strategy
- 3 delivery modes (STRUGGLING / NORMAL / FAST) with explicit prompt rules
- Frontend MCQ wrong × 2 auto-advance behavior
- APPLICATION and EXERCISE card badges in `CardLearningView.jsx`

**Excluded (Phase 2):**
- Concept-level shared card cache (3 LLM calls per concept, all students share sets)
- New DB table for card cache storage and Alembic migration
- Any changes to the Socratic check phase
- Changes to the spaced-review or boredom-detection subsystems

---

## 2. Functional Requirements

| ID | Priority | Requirement |
|----|----------|-------------|
| FR-01 | Must | Classify each `##` sub-section into one of: LEARNING_OBJECTIVES, EXAMPLE, TRY_IT, SOLUTION, HOW_TO, PREREQ_CHECK, TIP, END_MATTER, SUPPLEMENTARY |
| FR-02 | Must | Build a pedagogically-ordered blueprint preserving EXAMPLE and TRY_IT as independent items; merge SOLUTION into preceding EXAMPLE |
| FR-03 | Must | Skip PREREQ_CHECK, END_MATTER, and SUPPLEMENTARY sections in card generation |
| FR-04 | Must | Classify each section into one of 7 domain types (TYPE_A through TYPE_G) using keyword matching |
| FR-05 | Must | Generate cards of 9 distinct types: TEACH, EXAMPLE, APPLICATION, QUESTION, EXERCISE, VISUAL, RECAP, FUN, CHECKIN |
| FR-06 | Must | Attach `difficulty` field (EASY / MEDIUM / HARD) to every MCQ; map to learner speed/comprehension profile |
| FR-07 | Must | Apply per-card-type MCQ generation rules (definition test for TEACH, different numbers for EXAMPLE, operation identification for APPLICATION, quick recall for QUESTION) |
| FR-08 | Must | Randomize correct answer position across a/b/c/d per card |
| FR-09 | Must | Apply delivery-mode-specific prompt rules: STRUGGLING (step-by-step, analogy-first, 6-step APPLICATION scaffold), NORMAL (balanced), FAST (compact, multi-part QUESTION merging, HARD MCQ) |
| FR-10 | Must | Frontend: wrong MCQ answer × 2 (detected via presence of `replacementMcq`) triggers auto-advance to next card |
| FR-11 | Must | Frontend: render APPLICATION and EXERCISE card type badges in card header |
| FR-12 | Should | TIP sections merged into the preceding EXAMPLE or TEACH card as a "Pro tip" callout |
| FR-13 | Should | HOW_TO sections generate a TEACH card with numbered step rendering |

---

## 3. Non-Functional Requirements

| Category | Requirement | Target |
|----------|-------------|--------|
| Latency | P95 card generation time (full concept, NORMAL profile) | < 12s end-to-end |
| Latency | P95 card generation time (STRUGGLING, 10 sections) | < 18s (higher token budget) |
| Throughput | Concurrent card generation sessions | >= 20 (limited by OpenAI rate limits, not service) |
| LLM cost | Token budget vs. current | No regression; blueprint pipeline reduces context noise |
| Correctness | MCQ correct-answer position distribution | Uniform across a/b/c/d (chi-squared p > 0.1) |
| Reliability | Blueprint parse failure fallback | Graceful degradation to existing flat-section path |
| Maintainability | Section classifier rules externalized | Regex patterns defined as module-level constant `_SECTION_CLASSIFIER` |
| Observability | New log lines for blueprint construction | `blueprint: N items extracted, M skipped` per concept |
| Backward compat. | Existing card schema fields unchanged | `LessonCard`, `CardMCQ` schemas are additive only |
| Accessibility | New card type badges | WCAG 2.1 AA contrast ratio >= 4.5:1 |

---

## 4. System Context Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        ADA Backend (FastAPI)                     │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  TeachingService.generate_cards()                        │   │
│  │                                                          │   │
│  │  ┌──────────────────────┐    ┌────────────────────────┐ │   │
│  │  │ _SECTION_CLASSIFIER  │───▶│_build_textbook_        │ │   │
│  │  │ (regex dict)         │    │blueprint()             │ │   │
│  │  └──────────────────────┘    └───────────┬────────────┘ │   │
│  │                                          │              │   │
│  │                               ┌──────────▼────────────┐ │   │
│  │  LearnerProfile ─────────────▶│ Domain Classifier     │ │   │
│  │  (STRUGGLING/NORMAL/FAST)     │ (TYPE_A through TYPE_G)│ │   │
│  │                               └──────────┬────────────┘ │   │
│  │                                          │              │   │
│  │  build_cards_system_prompt() ◀───────────┘              │   │
│  │  build_cards_user_prompt()                               │   │
│  │       │                                                  │   │
│  │       ▼                                                  │   │
│  │  OpenAI gpt-4o (batch card generation)                  │   │
│  │       │                                                  │   │
│  │       ▼                                                  │   │
│  │  validate_and_repair_cards()                             │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  PostgreSQL 15 (card cache — Phase 2)                           │
└─────────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────┐           ┌─────────────────────┐
│ React 19 SPA    │           │ ChromaDB 0.5         │
│ CardLearning    │◀──cards───│ concept blocks       │
│ View.jsx        │           │ (source text)        │
│                 │           └─────────────────────┘
│ MCQ wrong×2     │
│ auto-advance    │
└─────────────────┘
```

---

## 5. Architectural Style and Patterns

### Selected Style: Incremental Enhancement of Existing Layered Architecture

The existing system follows a layered pattern: router → service → prompt builder → LLM → schema validation. This upgrade inserts a new **pre-processing stage** (blueprint pipeline) between the raw knowledge-service output and the prompt builder, and a new **prompt-rule stage** (delivery mode + MCQ difficulty) within the prompt builder.

No new services, routes, or databases are introduced in Phase 1.

### Patterns Used

| Pattern | Application |
|---------|-------------|
| Strategy | Delivery mode (STRUGGLING / NORMAL / FAST) selects prompt rule set |
| Chain of Responsibility | Section text → Classifier → Blueprint item → Card type → Prompt rule |
| Null Object | Skipped section types (PREREQ_CHECK, END_MATTER) return `None` blueprint items, filtered before LLM call |
| Template Method | `build_cards_system_prompt()` composes base rules + delivery-mode block + domain-type block |

### Alternatives Considered

| Alternative | Reason Rejected |
|-------------|-----------------|
| Fine-tuned section classifier (ML model) | Training data not available; regex achieves >95% accuracy on OpenStax format |
| Separate microservice for blueprint pipeline | Unnecessary operational complexity for a pure-function preprocessing step |
| Per-card LLM calls for blueprint | Cost prohibitive; batch call with structured blueprint context is sufficient |

---

## 6. Technology Stack

| Concern | Technology | Rationale |
|---------|------------|-----------|
| Blueprint classifier | Python `re` stdlib | Zero dependencies; OpenStax `##` headings follow deterministic patterns |
| Domain classifier | Python dict lookup + `str.lower()` keyword scan | Sufficient precision; interpretable; no ML overhead |
| Card generation LLM | `gpt-4o` (existing `OPENAI_MODEL`) | Batch card quality; unchanged from current stack |
| MCQ difficulty routing | Lookup table in `prompts.py` | Pure function; testable without mocking |
| Frontend badge rendering | Tailwind utility classes on existing card header | Consistent with project styling convention |
| Frontend wrong×2 detection | Existing `cardStates` in `SessionContext` | No new state shape; reads `!!cardStates[idx]?.replacementMcq` |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-01: Blueprint pipeline as a pre-processing function, not a new service

**Decision:** Implement `_build_textbook_blueprint()` as a private module function within `teaching_service.py`, not as a separate class or service.

**Options considered:**
- A. Module-level private function (chosen)
- B. New `BlueprintService` class
- C. Inline logic within `generate_cards()`

**Rationale:** Keeps the call graph shallow. The function is a pure transformation (text → ordered list of blueprint items) with no I/O, making it trivially testable. Option C increases cognitive load of `generate_cards()` beyond readability thresholds. Option B introduces indirection for a function used in exactly one place.

**Trade-off:** Blueprint logic is not independently deployable. Acceptable for Phase 1; revisit if blueprint complexity grows.

---

### ADR-02: MCQ difficulty as a string literal field, not an integer

**Decision:** `difficulty: Literal["EASY", "MEDIUM", "HARD"]` on `CardMCQ`.

**Options considered:**
- A. String literal enum (chosen)
- B. Integer 1–3
- C. Float 0.0–1.0

**Rationale:** String literals are self-documenting in API responses and frontend debugging. Pydantic validates them at schema boundaries. Future prompt rules reference the labels directly. Integer/float variants require a decode step.

**Trade-off:** Adding a 4th difficulty level later requires a schema change. Acceptable given the pedagogical model has no current need for granularity beyond 3 tiers.

---

### ADR-03: Delivery mode as a prompt-time parameter, not a session field

**Decision:** Delivery mode (STRUGGLING / NORMAL / FAST) is derived at prompt-build time from the current `LearnerProfile`; it is not stored as a session field or passed as a request parameter.

**Rationale:** Delivery mode is a function of the student's real-time signal blend, which already lives in `LearningProfile`. Storing it separately would create two sources of truth. Phase 2 caching will materialise three sets of pre-generated cards (one per mode) using the same derivation function.

---

### ADR-04: Wrong × 2 auto-advance detected client-side from existing `replacementMcq` state

**Decision:** Frontend detects wrong × 2 by checking `!!cardStates[idx]?.replacementMcq` at wrong-answer submission time. No new API field or backend change required.

**Rationale:** `replacementMcq` is only populated after the first wrong answer (existing MCQ regen call). A second wrong answer on a card that already has a `replacementMcq` is definitionally wrong × 2. This avoids a new backend counter field and keeps the detection purely reactive to existing state.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Regex classifier misses non-standard OpenStax headings (e.g., translated or reformatted PDFs) | Medium | Medium | Fallback: unrecognised heading types default to SUPPLEMENTARY and are treated as TEACH content, not skipped |
| Blueprint produces zero items for a concept (all sections classified as skipped) | Low | High | Guard in `_build_textbook_blueprint()`: if result is empty, fall back to flat section list with WARNING log |
| MCQ difficulty inflation: HARD distractors confuse NORMAL students if profile mis-classified | Low | Medium | MASTERY_THRESHOLD enforcement acts as safety valve; wrong × 2 auto-advance prevents permanent blocking |
| Token budget overrun on large STRUGGLING concepts | Medium | Low | Existing `CARDS_MAX_TOKENS_SLOW` ceiling enforced; no regression |
| Frontend wrong × 2 detection race condition (state update timing) | Low | Low | Detection is inside the same `handleMCQAnswer` callback; no async boundary |
| LLM ignores per-type MCQ rules despite explicit prompt instructions | Medium | Medium | Validated by comprehensive-tester agent against a sample concept set; fallback: schema validator enforces `difficulty` field presence |

---

## Key Decisions Requiring Stakeholder Input

1. **APPLICATION card 6-step scaffold** — Should the scaffold labels be configurable per domain type (e.g., different steps for geometry vs. algebra)? Currently designed as a single universal template.
2. **FAST mode: merging consecutive Try Its** — Should multi-part QUESTION cards be gated behind a feature flag to allow A/B testing vs. single-item QUESTION cards?
3. **Section type PREREQ_CHECK skipping** — Some "Be Prepared" sections contain prerequisite definitions relevant to the lesson. Should they generate a CHECKIN card instead of being skipped entirely?
4. **Phase 2 cache invalidation policy** — When a concept's ChromaDB content is updated (re-indexed), how are stale cached card sets detected and evicted? Requires agreement before Phase 2 DB design.
