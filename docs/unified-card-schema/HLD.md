# High-Level Design — Unified Card Schema

**Feature slug:** `unified-card-schema`
**Date:** 2026-03-06
**Status:** Approved for implementation

---

## 1. Executive Summary

### Feature Name and Purpose

The Unified Card Schema simplifies the ADA learning card system by collapsing six heterogeneous card types (TEACH, EXAMPLE, VISUAL, QUESTION, RECAP, FUN) and two competing question formats (`quick_check` + `questions[]`) into a single, consistent card structure. Every card produced by the LLM and consumed by the frontend follows one schema with one MCQ. Images are assigned by the LLM rather than overridden by the backend's positional algorithm, and inline `[IMAGE:N]` markers allow images to flow into the card body at precisely the right educational moment.

### Business Problem Being Solved

The current card system has four compounding defects that produce a poor learning experience:

1. **Image clustering on card 1.** `teaching_service.py` calls `card.pop("image_indices", None)` on every card immediately before applying a positional assignment algorithm. Cards without a matching sub-section filename receive images via a round-robin that starts at card index 0, causing all "leftover" images to pile up on the first card regardless of relevance.

2. **Schema fragmentation.** The frontend must branch across six `card_type` values and two distinct question schemas (`quick_check` for TEACH/EXAMPLE, `questions[]` for QUESTION). True/False questions in QUESTION cards require separate state machines, separate handlers, and separate i18n strings. This complexity is the primary source of bugs when question logic changes.

3. **Artificial content ceiling.** `ADAPTIVE_CARD_CEILING = 20` in `config.py` and a sub-section soft cap of 10 sections in `teaching_service.py` together truncate what the LLM can produce. Long concept sections are silently capped, meaning students receive incomplete coverage.

4. **Confusing card progress display.** The header subtitle reads "Card N of X" where X is the total number of cards pre-generated. For adaptive sessions where cards are generated one at a time, X is always 1, making the counter meaningless.

### Key Stakeholders

- Backend developer — implements schema changes, prompt rewrites, image resolution logic
- Frontend developer — simplifies question rendering, implements `[IMAGE:N]` inline parser
- Tester — updates and extends test suite to cover new schema
- DevOps engineer — pipeline re-run for all 60 Prealgebra sections

### Scope

**Included:**
- New unified card JSON schema (backend LLM output contract)
- LLM-driven image assignment via `image_indices` + `[IMAGE:N]` content markers
- Removal of `card_type`, `quick_check`, and `questions[]` fields
- Removal of `ADAPTIVE_CARD_CEILING` constant and sub-section soft cap
- Fix of card progress display ("Card N" instead of "Card N of X")
- Pipeline re-run for all 60 Prealgebra concept sections

**Excluded:**
- Changes to the Socratic check phase (CHECKING, REMEDIATING, RECHECKING)
- Changes to the adaptive per-card generation path (`/api/v2/sessions/{id}/complete-card`)
- Changes to the spaced review or card history systems
- New UI components beyond what is required to render inline images
- Multi-book pipeline support (out of scope for this iteration)

---

## 2. Functional Requirements

| ID   | Priority | Requirement |
|------|----------|-------------|
| FR-1 | Must     | Every card produced by the LLM and served to the frontend has exactly the fields: `title`, `content`, `image_indices`, `question` |
| FR-2 | Must     | The `question` field contains exactly one MCQ object with `text`, `options` (4 strings), `correct_index`, and `explanation` |
| FR-3 | Must     | CHECKIN cards (mood check-in) are the only exception — they have no `question` field, and instead carry an `options` array at the card level |
| FR-4 | Must     | The LLM assigns images to cards via `image_indices` (0-based into the concept's image list) AND embeds `[IMAGE:N]` markers in `content` text at the precise location where the image is contextually relevant |
| FR-5 | Must     | The backend resolves `image_indices` to full image objects and attaches them as a `images` list on each card — the backend no longer pops or ignores `image_indices` |
| FR-6 | Must     | The frontend parses `[IMAGE:N]` markers in card content and renders a `<ConceptImage>` component inline at that position |
| FR-7 | Must     | `ADAPTIVE_CARD_CEILING` is removed from `config.py` and from all import/reference sites |
| FR-8 | Must     | The sub-section soft cap (10 sections) is removed from `teaching_service.py`; the LLM is free to generate as many cards as the content warrants |
| FR-9 | Must     | Card progress display reads "Card N" (no total) — except in remediation mode where the total is known |
| FR-10| Must     | The pipeline is re-run for all 60 Prealgebra sections so ChromaDB is populated with content that the new prompt schema can operate on |
| FR-11| Should   | The `build_cards_user_prompt()` function passes image descriptions as "Index N: {description} (filename: {filename})" so the LLM can reference them by 0-based index |
| FR-12| Should   | Remediation cards generated by `_build_remediation_prompt()` also follow the unified schema (no `quick_check`, no `card_type`) |

---

## 3. Non-Functional Requirements

| Category         | Target |
|------------------|--------|
| Latency (card generation) | LLM call for full card set unchanged — single call per session. No regression from current p95 |
| Backward compatibility | No DB schema changes required. Existing `card_interactions` rows are unaffected |
| Frontend bundle size | No new dependencies. `[IMAGE:N]` parsing is pure string splitting |
| Test coverage | All new logic covered at unit level; integration test for the happy-path card generation flow |
| i18n impact | All user-visible strings already use `useTranslation()`. No new string keys are required for this change |
| Accessibility | Inline images must carry `alt` text derived from the image's `description` field — same as current `ConceptImage` props |
| Pipeline runtime | 60-section re-run estimated at 15–25 minutes depending on LLM throughput; no new rate-limit concerns |

---

## 4. System Context Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          ADA Platform                                │
│                                                                     │
│  ┌──────────────────┐     ┌───────────────────────────────────┐    │
│  │  React Frontend   │     │          FastAPI Backend           │    │
│  │                  │     │                                   │    │
│  │  CardLearning     │◄────│  GET /api/v2/sessions/{id}/cards  │    │
│  │  View.jsx         │     │                                   │    │
│  │                  │     │  teaching_service.generate_cards() │    │
│  │  [IMAGE:N] parser│     │                                   │    │
│  │  ConceptImage     │     │  build_cards_system_prompt()      │    │
│  │  inline render   │     │  build_cards_user_prompt()         │    │
│  └──────────────────┘     │       (with image index block)    │    │
│                           │                                   │    │
│                           │  image_indices → images[] resolve │    │
│                           └──────────────┬────────────────────┘    │
│                                          │                          │
│                           ┌──────────────▼────────────────────┐    │
│                           │     OpenAI GPT-4o (LLM)           │    │
│                           │  Unified card JSON schema          │    │
│                           │  LLM assigns image_indices         │    │
│                           │  LLM embeds [IMAGE:N] in content   │    │
│                           └───────────────────────────────────┘    │
│                                                                     │
│  ┌──────────────────┐     ┌───────────────────────────────────┐    │
│  │  Data Pipeline   │     │    ChromaDB + image_index.json    │    │
│  │  (60 sections)   │────►│    KnowledgeService._image_map    │    │
│  └──────────────────┘     └───────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

**Data flow (card generation):**

1. Frontend calls `GET /api/v2/sessions/{id}/cards`
2. `teaching_service.generate_cards()` retrieves concept detail from `KnowledgeService` (ChromaDB + image_index.json)
3. `build_cards_user_prompt()` constructs an available-images block: `Index 0: {description} (filename: {filename})`
4. `build_cards_system_prompt()` instructs the LLM to use unified schema, assign `image_indices`, and embed `[IMAGE:N]` markers in content
5. LLM produces unified card JSON
6. Backend post-processor resolves `image_indices` to full image objects; attaches them as `card.images`
7. Frontend `CardLearningView` parses `card.content` for `[IMAGE:N]` markers and renders `<ConceptImage>` inline

---

## 5. Architectural Style and Patterns

**Style:** Existing layered service architecture (no change)

**Pattern changes introduced by this feature:**

| Pattern | Before | After |
|---------|--------|-------|
| LLM image assignment | Backend overrides LLM output with positional algorithm | LLM owns assignment; backend only resolves index → object |
| Question schema | Dual schema (quick_check / questions[]) with branching | Single MCQ per card; uniform access via `card.question` |
| Card type | 6 types driving branching in both backend and frontend | Type concept removed; CHECKIN is the only structural exception |
| Content inline images | Not supported — images always rendered as a block after content | `[IMAGE:N]` marker in content triggers inline `<ConceptImage>` render |

**Trade-offs:**

- Removing card_type eliminates the ability for frontend badge/color theming per card variant. Mitigation: the frontend can infer a display hint from the content structure (e.g., if `content` starts with a worked-example header) or simply drop type-specific badges — this is acceptable because the badge conveyed no learning value.
- Letting the LLM own image placement introduces LLM hallucination risk (assigning a non-existent index). Mitigation: backend validates all `image_indices` values against the actual image list and silently drops out-of-range indices.

**Alternatives considered:**

- Keep card_type but unify question schema only. Rejected: card_type branching in the frontend is the primary maintenance burden. Removing it entirely yields the largest simplification for the smallest risk.
- Replace `[IMAGE:N]` with absolute image paths in content. Rejected: image URLs include a server-side prefix (`/images/{concept_id}/...`) that the LLM should not be asked to produce; index-based references are model-stable.

---

## 6. Technology Stack

No new dependencies are introduced. All changes are within the existing stack.

| Component | Technology | Note |
|-----------|-----------|------|
| Backend card generation | Python + OpenAI `gpt-4o` | Prompt schema change only |
| Backend post-processing | Python + existing `teaching_service.py` | Remove pop/round-robin; add index-resolve loop |
| Frontend rendering | React 19 + `react-markdown` + `rehype-katex` | Add `[IMAGE:N]` splitting logic; no new npm package |
| Image serving | Existing static mount `/images` in FastAPI `main.py` | No change |
| Pipeline | Existing `python -m src.pipeline` entry point | Re-run for 60 sections |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-1: LLM Owns Image Placement

**Decision:** The LLM assigns `image_indices` and embeds `[IMAGE:N]` markers. The backend only resolves indices to image objects.

**Options considered:**
- A. Backend positional algorithm (current) — images matched to sub-sections by filename references in raw text
- B. LLM assigns indices, backend resolves (chosen)
- C. Frontend fetches all images and decides placement

**Chosen:** B

**Rationale:** Option A discards LLM output and silently causes clustering. Option C requires the frontend to understand concept content, violating separation of concerns. Option B keeps placement semantics in the LLM (which has full card context) and keeps the backend as a dumb resolver.

**Risk:** LLM may assign wrong index. Backend validation (range check + drop) handles this gracefully.

---

### ADR-2: `[IMAGE:N]` Inline Marker Format

**Decision:** The LLM embeds `[IMAGE:N]` tokens (e.g., `[IMAGE:0]`, `[IMAGE:1]`) directly in the `content` markdown string at the precise location where the image should appear.

**Options considered:**
- A. Separate `inline_image_positions` array with character offsets
- B. `[IMAGE:N]` text token in content (chosen)
- C. Special markdown syntax (e.g., `![](image:0)`)

**Chosen:** B

**Rationale:** Text tokens are the simplest thing the LLM can reliably produce. Character offsets (A) are fragile and require the LLM to count characters accurately. Custom markdown syntax (C) would require modifying the `remark` plugin pipeline, adding a dependency.

---

### ADR-3: Remove card_type Entirely

**Decision:** Remove `card_type` from the LLM schema and from frontend rendering logic.

**Options considered:**
- A. Keep card_type, remove question schema divergence only
- B. Remove card_type entirely (chosen)

**Chosen:** B

**Rationale:** `card_type` drove six distinct rendering branches in `CardLearningView.jsx` and seven conditional blocks in `build_cards_system_prompt()`. With a single question format, there is no remaining structural reason for the type distinction. CHECKIN cards are inserted by the backend (no LLM involvement) and remain structurally distinct.

---

### ADR-4: Remove ADAPTIVE_CARD_CEILING and Sub-section Cap

**Decision:** Remove `ADAPTIVE_CARD_CEILING = 20` from `config.py` and the `elif len(sub_sections) > 10` cap from `teaching_service.py`.

**Rationale:** The ceiling was a safety guard introduced when card counts were unpredictable. The LLM schema now produces exactly as many cards as the content requires. The frontend "Card N" counter (no total) eliminates the UX confusion that a large card count caused. The sub-section cap produced incomplete content coverage for rich sections.

**Risk:** A pathological concept with 50+ sub-sections could produce a very long card set. Mitigation: the existing `max_tokens=2800` cap on the LLM call provides a natural ceiling.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Severity | Mitigation |
|------|-----------|----------|------------|
| LLM assigns out-of-range image indices | Medium | Low | Backend resolver validates each index against `len(available_images)`; silently drops invalid indices |
| LLM emits malformed `[IMAGE:N]` syntax (e.g., `[Image:0]`, `[IMAGE:0 ]`) | Medium | Low | Frontend parser uses case-insensitive regex: `/\[IMAGE:(\d+)\]/gi`; non-matching tokens are rendered as plain text |
| LLM omits `question` field on some cards | Low | Medium | Backend post-processor checks for missing `question` and logs a warning; card is served without a question (advance is still possible) |
| Increased card counts slow page load | Low | Low | Cards are returned in a single API response as before; no per-card network round-trip |
| Pipeline re-run overwrites existing ChromaDB data | Certain (by design) | Low | ChromaDB upsert is idempotent; run is additive for sections already processed |
| Remediation prompt still uses old schema | Low | Medium | `_build_remediation_prompt()` is updated in the same PR as `build_cards_system_prompt()` |
| Frontend `cardStates` shape incompatible with new question path | Medium | Medium | `canProceed` logic reduced to: `card.question` answered correctly OR card has no `question`; no type-branching needed |

---

## Key Decisions Requiring Stakeholder Input

1. **CHECKIN card exception:** CHECKIN cards (mood check-in, inserted every 12 cards by the backend) have no `question` field and carry an `options` list at the card level. Should CHECKIN cards also receive an inline content marker for any future image, or is image-free guaranteed for CHECKIN cards permanently?

2. **Removal of card-type badges in the UI:** The `CARD_TYPE_META` lookup table and `CardTypeBadge` component currently render "Example", "Recap", "Fun Fact", and "Visual" pill badges in the card header. With card_type removed, these badges disappear. Confirm this is acceptable, or specify an alternative display signal (e.g., a badge derived from whether the card has an image, or no badge at all).

3. **Remediation path schema alignment:** The remediation card generator (`_build_remediation_prompt`) currently also uses the old `card_type` / `quick_check` schema. This design includes updating it to unified schema. Confirm this is in scope for this iteration.

4. **"Card N of X" in remediation mode:** For remediation sessions (REMEDIATING phase), the total card count is known upfront. Should those cards retain "Card N of X" display, or switch to "Card N" uniformly?
