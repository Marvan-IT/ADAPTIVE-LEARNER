# High-Level Design: Card Generation Rebuild

**Feature slug:** `card-generation-rebuild`
**Date:** 2026-03-09
**Author:** Solution Architect

---

## 1. Executive Summary

### Feature Name and Purpose
Card Generation Rebuild — a targeted defect-correction pass on the existing flashcard generation pipeline in `teaching_service.py` and `prompts.py`. The goal is to eliminate six identified root causes that cause cards to be silently dropped, content to be truncated, and adaptive density instructions to be ignored.

### Business Problem Being Solved
Students receive incomplete flashcard sets. A concept like "Whole Numbers" contains approximately 57 raw micro-sections after `_parse_sub_sections()` is called, yet the card deck arrives with large gaps in coverage because:
- The section-grouping method that was designed to consolidate those micro-sections into 8–10 coherent topic blocks is never called.
- The LLM hits a hard `max_tokens=8000` ceiling before finishing slower-learner decks that require 12,000–18,000 tokens.
- The prompt gives the LLM no density guidance (cards per section) for the adaptive profile that has already been computed.
- The fallback code path crashes with a `KeyError` for new students with no prior session history.

The net effect is that students see partial decks and miss key definitions, worked examples, and practice questions that the textbook mandates.

### Key Stakeholders
- Students (direct: incomplete decks degrade learning outcomes)
- Curriculum QA (indirect: decks must reflect full textbook coverage)
- Backend Developer (implements the six fixes)
- Comprehensive Tester (verifies coverage completeness and profile-adaptive token budgets)

### Scope

**Included:**
- Fix A: Wire the dead `_group_by_major_topic()` call into `generate_cards()`.
- Fix B: Compute a profile-adaptive `max_tokens` budget before each LLM call.
- Fix C: Add `max_tokens` parameter to `_generate_cards_single()`.
- Fix D: Add a CARD DENSITY block to `_build_card_profile_block()`.
- Fix E: Add a COMPLETENESS REQUIREMENT checklist to `build_cards_user_prompt()`.
- Fix F: Strengthen the "COMPLETE COVERAGE" line in `build_cards_system_prompt()`.

**Explicitly excluded:**
- DB schema changes (none required).
- Frontend changes (card schema is unchanged: `index`, `title`, `content`, `images`, `question`, `difficulty`).
- Changes to `build_next_card_prompt()` (adaptive per-card prompting — separate feature).
- Changes to `_parse_sub_sections()` (the header-splitting logic itself is correct).
- Changes to `_group_sub_sections()` (the character-limit grouper — not on the call path for this fix).
- Changes to image matching or ChromaDB retrieval.

---

## 2. Functional Requirements

| ID | Priority | Requirement |
|----|----------|-------------|
| FR-1 | Critical | `generate_cards()` MUST call `_group_by_major_topic()` after `_parse_sub_sections()` so that EXAMPLE / Solution / TRY IT micro-sections are absorbed into their parent topics before the prompt is built. |
| FR-2 | Critical | The fallback `sub_sections` dict when `_parse_sub_sections()` returns empty MUST use key `"text"`, matching what `build_cards_user_prompt()` reads via `sec["text"]`. |
| FR-3 | Critical | `_generate_cards_single()` MUST accept a `max_tokens` parameter instead of hard-coding 8000, so callers can pass a profile-derived budget. |
| FR-4 | High | `generate_cards()` MUST compute a profile-adaptive token budget before calling `_generate_cards_single()` using the SLOW/STRUGGLING / FAST/STRONG / NORMAL tiers defined in this design. |
| FR-5 | High | `_build_card_profile_block()` MUST include a CARD DENSITY instruction (cards per section) derived from the learner's adaptive profile. |
| FR-6 | High | `build_cards_user_prompt()` MUST append a numbered COMPLETENESS REQUIREMENT checklist listing every section title so the LLM cannot skip a section silently. |
| FR-7 | High | `build_cards_system_prompt()` MUST strengthen the existing "COMPLETE COVERAGE" line to make omission a hard constraint, not a preference. |

---

## 3. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Latency | P95 card generation latency MUST NOT increase by more than 15 seconds over pre-fix baseline. Token budget increase allows larger responses; this is the trade-off accepted. |
| Throughput | No change — card generation is already one call per session trigger. |
| Availability | No new failure modes introduced. All changes are in-process; no new external dependencies. |
| Correctness | After Fix A, a 57-section concept MUST produce 8–10 grouped sections fed to the LLM, not 57 raw micro-sections. |
| Correctness | After Fixes B+C, a SLOW learner concept with 10 sections MUST receive `max_tokens >= 12,000`. |
| Correctness | After Fix E, every section title enumerated in the user prompt MUST appear in the COMPLETENESS checklist appended to that same prompt. |
| Backward compatibility | The card schema output (`index`, `title`, `content`, `images`, `question`, `difficulty`) MUST remain identical; no frontend changes required. |
| Testability | Each fix MUST be independently unit-testable by calling the affected static or async method in isolation. |

---

## 4. System Context

```
Student Browser
      │
      │  POST /api/v2/sessions/{id}/cards
      ▼
teaching_router.py  ──►  TeachingService.generate_cards()
                               │
                   ┌───────────┼───────────────────────────────────┐
                   │           │                                   │
         KnowledgeService  _parse_sub_sections()          load_student_history()
         (ChromaDB + NX)       │                           load_wrong_option_pattern()
                               │  [FIX A] _group_by_major_topic()
                               │
                   ┌───────────┼───────────────┐
                   │                           │
        build_cards_system_prompt()   build_cards_user_prompt()
        [FIX D: density block]        [FIX E: completeness checklist]
        [FIX F: coverage line]
                               │
                  [FIX B: adaptive max_tokens computed]
                               │
                   _generate_cards_single(max_tokens=N)   [FIX C: param added]
                               │
                         OpenAI API (gpt-4o)
                               │
                         Post-processing + cache
                               │
                         JSON response to frontend
```

No new external systems are introduced. All changes are internal to `teaching_service.py` and `prompts.py`.

---

## 5. Architectural Style and Patterns

The existing pipeline is a **sequential service method** (not an event-driven or microservice pattern) — this is intentional and correct for a single-session, latency-sensitive flow. All six fixes follow the same pattern:

- **Pure static methods** (`_group_by_major_topic`, `_parse_sub_sections`, `_build_card_profile_block`) — no I/O, fully unit-testable.
- **Token budget computation as a derived value** — `max_tokens` is computed from the learner profile and section count, not from a global constant. This keeps `config.py` as the single source for the tier boundary values.
- **Prompt composition via concatenation** — consistent with all existing prompt builders; no templating engine introduced.

**Why not restructure into multiple LLM calls per section?** Rejected. A single LLM call preserves cross-section coherence (the LLM can build a consistent narrative arc), reduces latency variance, and avoids the ordering complexity of merging N partial responses. The token budget fix makes the single-call approach viable even for slow learners.

---

## 6. Technology Stack

No new dependencies introduced. All changes are within the existing stack:

| Concern | Technology | Notes |
|---------|-----------|-------|
| Service layer | Python 3.11, FastAPI async | `teaching_service.py` |
| Prompt building | Python string composition | `prompts.py` |
| LLM | OpenAI `gpt-4o` via `AsyncOpenAI` | `max_tokens` parameter already supported |
| Config | `config.py` | New constants: `CARDS_MAX_TOKENS_SLOW`, `CARDS_MAX_TOKENS_NORMAL`, `CARDS_MAX_TOKENS_FAST` |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-1: Wire `_group_by_major_topic()` between parse and prompt, not inside `_parse_sub_sections()`

**Options considered:**
- A. Call `_group_by_major_topic()` inside `_parse_sub_sections()` (merge into one method).
- B. Call `_group_by_major_topic()` in `generate_cards()` after `_parse_sub_sections()` returns.

**Decision:** Option B.

**Rationale:** `_parse_sub_sections()` is a pure structural parser (splits on `##` headers). `_group_by_major_topic()` applies semantic classification (major topic vs. supporting content). Keeping them separate preserves single responsibility and allows each to be unit-tested in isolation. The call site in `generate_cards()` is already the natural composition point.

### ADR-2: Compute `max_tokens` from section count and profile tier, not from a fixed table

**Options considered:**
- A. Fixed per-profile constants: SLOW=16000, NORMAL=12000, FAST=8000.
- B. Formula: `min(ceiling, max(floor, n_sections * tokens_per_section))`.

**Decision:** Option B.

**Rationale:** A concept with 3 grouped sections does not need 16,000 tokens even for a slow learner. The formula right-sizes the budget to the actual content, reducing unnecessary API cost and latency. Ceiling and floor values are stored as constants in `config.py` so they can be tuned without code changes.

### ADR-3: Completeness checklist in the user prompt, not the system prompt

**Options considered:**
- A. Add checklist to system prompt (global instruction).
- B. Add checklist to user prompt (per-request, dynamic section titles).

**Decision:** Option B.

**Rationale:** The section titles are only known at request time after `_group_by_major_topic()` runs. The system prompt is static across requests for the same profile. A numbered checklist with actual section titles in the user prompt gives the LLM a concrete, per-request verification list it can check against before closing its JSON response.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Larger `max_tokens` for slow learners increases OpenAI cost by ~2x per slow-learner session | Medium | Medium | Cost is per-session, not per-card. Slow learners already have the worst outcomes — the quality trade-off is justified. Monitor via existing OpenAI usage dashboard. |
| `_group_by_major_topic()` regex may misclassify an unusual section heading as "supporting" and absorb it into the wrong parent | Low | Low | The method already has a safe fallback: returns `sections` unchanged if `groups` is empty. Manual QA on 2–3 concepts post-deploy. |
| Increasing `max_tokens` to 16,000 pushes total prompt + response toward the model's context window limit for very large concepts | Low | High | The formula ceiling of 16,000 + a typical system prompt of ~3,000 tokens is well within `gpt-4o`'s 128K context window. Not a risk in practice. |
| Fix E's completeness checklist increases user prompt token count by ~50–150 tokens | Low | Negligible | Acceptable. The checklist is bounded by the number of section titles (~10 max after grouping). |
| Fallback key bug fix (`"content"` → `"text"`) only applies to the empty-parse path; existing sessions with cached `presentation_text` are unaffected | Low | None | Correct — cached sessions are served from `session.presentation_text` and never re-enter `generate_cards()`. |

---

## Key Decisions Requiring Stakeholder Input

1. **Token budget tier values** — The proposed formula constants (`CARDS_MAX_TOKENS_SLOW = 16000`, `CARDS_MAX_TOKENS_NORMAL = 12000`, `CARDS_MAX_TOKENS_FAST = 8000`, per-section multipliers 1800 / 1200 / 900) are engineering estimates based on observed card sizes. Product should confirm whether the resulting OpenAI cost increase per slow-learner session is acceptable before these constants are committed to `config.py`.

2. **Card density targets** — SUPPORT mode (2–3 cards/section) and ACCELERATE mode (1–2 cards/section) are inferred from the pedagogical intent of the existing profile system. Curriculum team should confirm these density ranges align with intended lesson length per profile.
