# HLD — Complete i18n Coverage + Admin Re-trigger Invalidation

**Feature slug:** `i18n-complete-coverage`
**Date:** 2026-04-24
**Status:** Phase 0 — Design (approved plan: `problems-still-the-recent-deep-moore.md`)

---

## 1. Executive Summary

### Problem Statement

A student who does not read English must be able to use the entire Adaptive Learner platform end-to-end in their preferred language. Today this is broken in two independent ways:

1. **Static surface gaps.** Tutor-style and interest labels (`"Pirate"`, `"Gamer"`, `"Sports"`) are hardcoded English constants never routed through `t()`. The entire admin content editor (`AdminBookContentPage.jsx`) imports `useTranslation` but calls it zero times — every button, badge, toast, modal title, and confirm dialog is hardcoded English.

2. **Cache stale after admin edit.** When an admin renames a section, toggles optional/exam-gate, edits chunk text, merges, splits, promotes a chunk, or modifies prerequisites, the student's `presentation_text` card cache is not invalidated. Students with open sessions continue reading stale card text until their session expires. Only the language PATCH handler calls `CacheAccessor.mark_stale()` today.

### Business Problem Being Solved

A Malayalam-only student (or any of the 12 non-English supported locales) must be able to complete a full learning session — registration, interest/style selection, chunk reading, MCQ answering, exam gate, mid-session language/mode/style switch — without encountering a single English string. Simultaneously, admin content edits must propagate to active student sessions within one card fetch.

### Stakeholders

| Role | Interest |
|------|---------|
| Non-English students | All surfaces in their language |
| Admins | Edits reflected immediately; admin UI also in their language |
| Backend developer | Invalidation hook design, exam-question cache |
| Frontend developer | Locale key catalogue, LanguageSelector reload flow |
| Comprehensive tester | E2E and unit coverage for both gaps |
| DevOps engineer | CI integration of new Playwright specs |

### Scope

**Included:**
- Scoped cache invalidation on every admin mutation (section and chunk handlers, undo/redo)
- Exam-question caching inside `CacheAccessor` per language per chunk
- LanguageSelector reload of exam questions alongside cards after language switch
- Full i18n pass on `AdminBookContentPage.jsx`
- Tutor style and interest labels routed through `t()`
- Locale catalogue for all 13 files

**Explicitly excluded:**
- No new Alembic migration (no new DB columns needed)
- No retranslation of historical LLM content already stored in active sessions
- No deep-link or admin UI button to manually bust a student's cache
- No `recent_activities.label_translations` DB column (UI-key approach used instead)
- No Hebrew or other RTL language beyond Arabic (already present in locale list)

---

## 2. User Journeys

### Journey A — Malayalam student, complete end-to-end

1. Student opens registration page. Tutor styles show `"ഡിഫോൾട്ട്"` (Default in Malayalam), interests show `"കായികം"` (Sports). Student selects interests and style; both resolved via `t("tutorStyles.default")` and `t("interests.Sports")`.
2. Student starts a session. Dashboard phase labels (`IN_PROGRESS`, `COMPLETED`) resolve from `t("dashboard.*")`.
3. Student reads a chunk. Section header (`1.2 Introduction`) resolves via `heading_translations` from DB (migration 021 already landed). Card title and MCQ options are LLM-generated in Malayalam (language instruction appended to every card-gen prompt).
4. Student completes a chunk and hits the exam gate. Exam questions are fetched from the `exam_questions_by_chunk` cache slice (new). If the slice is cold (first visit), the LLM generates questions with `_language_instruction("ml")` and stores them. The student sees Malayalam questions.
5. Student passes the exam gate and advances.
6. Mid-session: student opens Settings and changes tutor style. The dialog title, option labels, and confirmation toast are all Malayalam.
7. Student opens LanguageSelector and switches from Malayalam to Tamil. The PATCH returns `session_cache_cleared: true`. `LanguageSelector.selectLanguage()` calls `reloadCurrentChunk()` AND dispatches a new `RELOAD_EXAM_QUESTIONS` action so the Tamil exam questions for the current chunk are fetched.
8. Student changes mode and interests. All confirmation dialogs, badge labels, and toasts are Tamil.
9. At no point does the student see an English string.

### Journey B — Admin edit propagates to active session

1. Admin opens Book Content Editor. All buttons (`Save Changes`, `Discard`, `Merge ↓`, `Split`, `Promote`, `Regen`, `Hide`, `Show`, etc.) are in the admin's selected language (e.g. Tamil).
2. Admin renames section `1.2`. `handleRenameSection()` calls `renameSection()` API. The admin router handler, after committing the DB change, calls `invalidate_chunk_cache(db, chunk_id)` for every chunk in that section.
3. A concurrent Malayalam student's session has a cached card for chunk X in section 1.2. The cache slice for `"ml"` is cleared. On the student's next `/chunk-cards` fetch, the card is regenerated with the new section name in Malayalam.
4. Admin toggles exam gate off for a section. The `invalidate_chunk_cache()` helper clears cached exam questions for that chunk slice. The student's client auto-advances (frontend skips exam gate when questions array is empty and gate is disabled).
5. Admin performs undo of the rename. `audit_service.py` `_undo_rename_section()` also calls `invalidate_chunk_cache()` so the student's next card reflects the reverted name.

---

## 3. Surface Inventory

| Surface | Source | i18n Strategy | Gap Today | Fix |
|---------|--------|---------------|-----------|-----|
| Tutor style labels (`Default`, `Pirate`, `Space`, `Gamer`) | Static constant in `tutorPreferences.js` | `t("tutorStyles.<id>")` | Label hardcoded English; never through `t()` | Remove `label` field; render via `t()` at call sites |
| Interest labels (`Sports`, `Gaming`, …) | Static constant in `tutorPreferences.js` | `t("interests.<id>")` | Same gap | Same fix |
| Admin content editor — all strings | UI / hardcoded | `t("adminContent.<key>")` | `useTranslation()` imported but never called | Full i18n pass; ~40 keys |
| Section header in learning view | DB `heading_translations` column (migration 021) | `resolve_translation()` on backend | Already fixed via migration 021 | Confirm call site consistency |
| Card title + MCQ options | LLM-generated, cached per language in `presentation_text` | `_language_instruction(lang)` appended to every card-gen prompt | Stale if admin edits after cache is warm | `invalidate_chunk_cache()` on every admin mutation |
| Exam gate questions | LLM-generated ad-hoc in `teaching_router.py:971–1045` | `_language_instruction(lang)` already appended | Not cached — regenerated per request; after language switch, client holds stale English in state | Cache in `exam_questions_by_chunk` slice; reload after language switch |
| Dashboard phase labels (`IN_PROGRESS`, `COMPLETED`, `CARDS_DONE`) | UI key | `t("dashboard.*")` | Mostly fixed; needs 13-locale audit | Verify all 13 locale files have keys |
| Settings page — style/interest options | Derived from `tutorPreferences.js` | `t()` | Same gap as tutor styles | Same fix |
| Register page — style/interest options | Derived from `tutorPreferences.js` | `t()` | Same gap | Same fix |
| Toast notifications in learning view | UI key | `t()` | Some are hardcoded strings | Audit `CardLearningView`, `AssistantPanel` toast calls |
| Mode change dialog | UI key | `t()` | Partially translated | Audit `SessionContext` mode labels |
| Admin section badge labels (`Optional`, `Lab`) | `sectionBadges()` helper | `t("adminContent.*")` | Hardcoded English | Include in adminContent key catalogue |
| Prerequisite accordion labels | UI hardcoded | `t("adminContent.*")` | All hardcoded | Include in adminContent key catalogue |
| `"Would create a cycle"` error | Backend detail string | `t("adminContent.*")` or backend error code | Hardcoded English | Use error code; translate on frontend |

---

## 4. Per-Language Cache Topology After This Change

### Current shape (CacheAccessor `presentation_text`)

```json
{
  "cache_version": 3,
  "by_language": {
    "en": {
      "presentation": "...",
      "cards": [...],
      "concepts_queue": [...],
      "concepts_covered": [...]
    },
    "ml": {
      "presentation": "...",
      "cards": [...],
      "concepts_queue": [...],
      "concepts_covered": [...]
    }
  }
}
```

### New shape — adds `exam_questions_by_chunk` per language slice

```json
{
  "cache_version": 3,
  "by_language": {
    "en": {
      "presentation": "...",
      "cards": [...],
      "concepts_queue": [...],
      "concepts_covered": [...],
      "exam_questions_by_chunk": {
        "550e8400-e29b-41d4-a716-446655440000": [
          {"index": 0, "text": "Does the set of whole numbers include zero — yes or no?"},
          {"index": 1, "text": "True or false: 0 is a natural number."}
        ]
      }
    },
    "ml": {
      "presentation": "...",
      "cards": [...],
      "concepts_queue": [...],
      "concepts_covered": [...],
      "exam_questions_by_chunk": {
        "550e8400-e29b-41d4-a716-446655440000": [
          {"index": 0, "text": "മൊത്ത സംഖ്യകളുടെ ഗണത്തിൽ പൂജ്യം ഉൾപ്പെടുന്നുണ്ടോ — അതെ അല്ലെങ്കിൽ ഇല്ല?"}
        ]
      }
    }
  }
}
```

**Invalidation rules:**

| Trigger | Which slices cleared |
|---------|---------------------|
| Admin edits chunk X (any field) | `exam_questions_by_chunk[chunk_id]` cleared in every language slice of every active session touching that chunk |
| Admin edits section S (rename, toggle) | Same, for all chunks in section S |
| Admin undo/redo | Same as the original operation |
| Student switches language to L | `mark_stale(L)` clears entire language slice for L (existing behaviour; now clears exam questions too since they live inside the slice) |

---

## 5. Architectural Style and Patterns

**Selected style:** Layered service + thin adapter invalidation hook.

The invalidation is a cross-cutting concern: every admin mutation handler needs to call the same `invalidate_chunk_cache(db, chunk_id_list)` helper after its DB commit. This is implemented as a standalone async helper in `teaching_service.py` (where session state already lives), called as a side-effect from `admin_router.py` and `audit_service.py`.

**Why not event-driven (e.g. DB trigger or message queue)?** The app has no message broker; adding one for a single cross-cutting concern would be disproportionate overhead. The synchronous hook pattern (call helper inside the same DB transaction) is consistent with how `mark_stale()` is already used in the language-PATCH handler.

**Alternatives considered:**

| Option | Verdict |
|--------|---------|
| Full-book cache bust on any admin edit | Rejected — over-invalidates; forces LLM regen for all students across all chunks |
| Admin UI "Bust cache" button | Rejected — manual; students see stale content until admin notices |
| DB trigger + background worker | Rejected — no broker in stack; operational complexity unjustified |
| Scoped invalidation per mutated chunk (chosen) | Approved — surgical, fits existing `CacheAccessor` model |

---

## 6. Technology Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Backend | FastAPI async, SQLAlchemy 2.0 async | No new dependencies |
| Cache layer | `CacheAccessor` (in-process JSON column) | Schema extended, no new tables |
| LLM | `gpt-4o-mini` via AsyncOpenAI | Exam question generation; same client |
| Frontend | React 19, i18next 13, Vite 7 | No new packages |
| Locale automation | Node.js + OpenAI (new `scripts/translate_locale.mjs`) | One-time helper, not shipped to prod |
| Tests | pytest-asyncio, Playwright | New spec files only |

All choices are consistent with existing project stack (CLAUDE.md confirmed).

---

## 7. Key Architectural Decisions (ADRs)

### ADR-1 — Scoped chunk invalidation, not full-book bust

**Decision:** `invalidate_chunk_cache(db, chunk_id_list)` iterates only the sessions whose cached queues reference a mutated chunk and clears only the matching chunk's exam-question slice plus the card entries for that chunk.

**Options considered:** Full-book bust, manual button, event-driven worker, scoped (chosen).

**Rationale:** Minimises LLM regen cost; other students' cached content for unrelated chunks is preserved.

**Trade-off:** More complex query (must identify sessions referencing the chunk). Mitigated by the fact that `concepts_queue` in the session already stores chunk IDs, so a straightforward JSON column query suffices.

### ADR-2 — Exam questions cached inside per-language CacheAccessor slice

**Decision:** Add `exam_questions_by_chunk` dict inside each language slice. No new DB table.

**Options considered:** New `exam_question_cache` table (requires Alembic migration), existing `presentation_text` JSON extension (chosen).

**Rationale:** Preserves the "CacheAccessor is the single source of truth for session state" invariant. `mark_stale(lang)` already wipes the language slice, which automatically wipes exam questions for that language — no additional clearing logic needed for language switches.

**Trade-off:** Increases `presentation_text` row size. Mitigated by existing `_CACHE_MAX_BYTES = 512 KB` eviction logic in `CacheAccessor.set_slice()`.

### ADR-3 — IDs stay English, only labels translate

**Decision:** `tutorPreferences.js` keeps `id: "Pirate"` etc. as immutable DB keys. Consumers call `t("tutorStyles.pirate")`.

**Rationale:** Existing `student.preferred_style` and `student.interests` rows in PostgreSQL store the English ID. No DB migration needed. Locale translation is purely a display concern.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Severity | Mitigation |
|------|-----------|---------|-----------|
| LLM regen cost spike from admin edits in active periods | Medium | Medium | Scoped invalidation (ADR-1) — only affected chunks, not whole book |
| `presentation_text` row size growth from exam question cache | Low | Low | Existing 512 KB cap + LRU eviction in `CacheAccessor.set_slice()` |
| Arabic/RTL regressions in admin editor after i18n pass | Medium | Medium | Manual RTL walkthrough acceptance criterion; existing `i18n.js:24,37-41` dir handling |
| Translation quality for culturally loaded terms (`"Pirate"`, `"Gamer"`) | Medium | Low | Human reviewer pass per-locale after LLM auto-translation |
| Undo/redo invalidation forgotten in `audit_service.py` | High (easy to miss) | High | Each `_undo_*` helper explicitly listed in DLD hook table; test coverage parametrised |
| OpenAI non-determinism breaking test assertions | Medium | Medium | Mock OpenAI in unit tests; use character-threshold heuristics in E2E |
| Frontend state stale exam questions after language switch | High (current bug) | Medium | `LanguageSelector` dispatches `RELOAD_EXAM_QUESTIONS` after PATCH; covered by E2E |

---

## Key Decisions Requiring Stakeholder Input

1. **Exam question cache invalidation granularity for section-level edits:** when an admin toggles optional on an entire section (not a single chunk), should all chunks' exam caches be cleared or only teaching-type chunks? Current design clears all chunk IDs in the section.

2. **Machine translation review process:** the `translate_locale.mjs` script produces auto-translations for 12 languages. Who is the designated human reviewer per locale, and what is the SLA before the PR can merge?

3. **Admin language switch scope:** should admin users be able to use the admin editor in their own preferred language independently of a student's language? Current design treats them as separate (admin's `i18n.language` drives admin UI strings independently).
