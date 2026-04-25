# High-Level Design — i18n Residuals Fix

**Feature slug:** `i18n-residuals-fix`
**Date:** 2026-04-24
**Status:** Approved — Phase 0 design

---

## 1. Executive Summary

**Feature name:** i18n Residuals Fix

**Business problem:** Two i18n gaps remain after the main i18n-complete-coverage work (Phases 0–4). Both affect non-English users today:

1. **admin_section_name drift** — when an admin renames a section via the Book Content or Book Review editor, the new English name is stored in `concept_chunks.admin_section_name` with no parallel translation. `teaching_router.py` passes an empty `{}` to `resolve_translation`, so a Malayalam or Arabic student sees the raw English rename instead of their language. Verified on `business_statistics_1.1`.

2. **AdminReviewPage native popups** — three `window.prompt()` calls (edit chunk heading, promote section label, rename section) display English browser-native dialogs regardless of the admin's chosen locale. This is the same bug class already fixed in `AdminBookContentPage.jsx` via `useDialog().prompt()`.

**Key stakeholders:** Admin content team (prompt UX), non-English student cohort (section name display), devops (migration).

**Scope — included:**
- New `admin_section_name_translations` JSONB column on `concept_chunks`.
- `translate_one_string` helper extracted into `backend/src/api/translation_helper.py`.
- `rename_section` handler wired to call OpenAI synchronously on each rename.
- `teaching_router.py` display-path fallback corrected to use the new column.
- `audit_service.py` snapshot and undo extended to cover the new column.
- `AdminReviewPage.jsx` three `window.prompt` calls replaced with `useDialog().prompt()`.
- Three new locale keys (`adminReview.promptNewHeading`, `adminReview.promptPromoteLabel`, `adminReview.promptNewSectionName`) added to all 13 locale files.
- Alembic migration `022_add_admin_section_name_translations.py`.

**Scope — explicitly excluded (non-goals):**
- No changes to pipeline Stage 7 auto-translation (already translates `heading_translations`).
- No changes to `translate_catalog.py` SHA-1 incrementality logic.
- No translation of book titles or raw `section` slugs on admin rename.
- No book-title or chunk-heading rename translation (separate roadmap item).
- No changes to the `invalidate_chunk_cache` mechanism (already hooked).
- No new API endpoints.

---

## 2. Functional Requirements

| # | Priority | Requirement |
|---|----------|-------------|
| FR-01 | P0 | When an admin renames a section, `admin_section_name_translations` is populated with translations in all 12 non-English locales before the response is returned. |
| FR-02 | P0 | A student whose `preferred_language` is non-English receives the translated section name from the chunk-list API response on the next fetch after a rename. |
| FR-03 | P0 | If the OpenAI call in FR-01 fails (timeout, network error), the rename still succeeds and the English name is shown to students (graceful degradation). |
| FR-04 | P0 | When an admin undoes a section rename, both `admin_section_name` and `admin_section_name_translations` are restored to their pre-rename values. |
| FR-05 | P1 | Opening `AdminReviewPage` with a non-English locale displays all three input prompts (edit heading, promote label, rename section) in the admin's language. |
| FR-06 | P1 | The three new locale keys are present and correct in all 13 locale JSON files. |

### User journeys

**Journey A — Admin renames a section (admin_section_name drift fix):**
1. Admin opens Book Content or Book Review page, locates section "1.1 Descriptive Statistics".
2. Admin clicks Rename and types "1.1 Basics of Probability".
3. Backend: `PATCH /api/admin/sections/{concept_id}/rename` — updates `admin_section_name`, then calls OpenAI to translate into 12 languages, stores result in `admin_section_name_translations`, calls `invalidate_chunk_cache`, commits.
4. Total admin wait: ~2 seconds.
5. Malayalam student: next `GET /api/v2/sessions/{id}/chunks/{concept_id}` → `section_title` returned as "1.1 സാധ്യതയുടെ അടിസ്ഥാനങ്ങള്‍".

**Journey B — Non-English admin opens AdminReviewPage:**
1. Admin switches UI to Malayalam in settings.
2. Admin opens the Book Review page for a book in `READY_FOR_REVIEW` status.
3. Admin clicks "Edit heading" on a chunk — `useDialog().prompt()` opens with Malayalam prompt text.
4. Admin clicks "Promote" on a chunk — `useDialog().prompt()` opens with Malayalam prompt text.
5. Admin clicks "Rename section" — `useDialog().prompt()` opens with Malayalam prompt text.

---

## 3. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Rename latency (P95) | < 3 seconds end-to-end (OpenAI gpt-4o-mini is typically 1–2s for a single short string) |
| Rename reliability | Rename succeeds in 100% of cases; translation success rate >= 98% (graceful degradation on failure) |
| LLM cost per rename | ~$0.00005 (negligible; one 12-language call on a short string) |
| Backwards compatibility | Existing rows with `admin_section_name_translations = '{}'` continue to display English (current behaviour unchanged) |
| Migration safety | `NOT NULL DEFAULT '{}'::jsonb` — no row backfill required; zero downtime |
| Locale coverage | All 13 locale files updated; missing key = broken UI in that language |
| Rollback | `alembic downgrade -1` drops the column; code path falls back to `{}` (original English-only behaviour) |

---

## 4. System Context

```
                          ┌──────────────────────────────────────────────────┐
                          │                  Browser                         │
                          │                                                  │
                          │  AdminReviewPage.jsx          StudentView         │
                          │  (3 window.prompt → useDialog) (ChunkListView)   │
                          └──────────┬───────────────────────────┬───────────┘
                                     │ PATCH /api/admin/...      │ GET /api/v2/sessions/.../chunks/...
                                     ▼                           ▼
                          ┌──────────────────────────────────────────────────┐
                          │               FastAPI Backend (port 8889)         │
                          │                                                  │
                          │  admin_router.py                                 │
                          │    rename_section()                              │
                          │      ↓ UPDATE admin_section_name                 │
                          │      ↓ translate_one_string() ──────► OpenAI     │
                          │      ↓ UPDATE admin_section_name_translations    │
                          │      ↓ invalidate_chunk_cache()                 │
                          │      ↓ audit_service.log_action()               │
                          │                                                  │
                          │  teaching_router.py                              │
                          │    get_chunks_for_session()                      │
                          │      ↓ resolve_translation(                      │
                          │          admin_section_name,                     │
                          │          admin_section_name_translations,  ◄──── NEW │
                          │          lang)                                   │
                          └──────────────────────────────┬───────────────────┘
                                                         │
                                                         ▼
                                              ┌──────────────────┐
                                              │   PostgreSQL 15   │
                                              │ concept_chunks    │
                                              │ + new JSONB col   │
                                              └──────────────────┘
```

---

## 5. Architectural Style and Patterns

**Selected style:** In-place incremental fix — no new services, no new routes. The change extends existing handler logic and adds one JSONB column.

**Patterns applied:**

- **Graceful degradation:** The translation call is wrapped in `asyncio.timeout(10.0)` + broad `except Exception` so a failing OpenAI call never blocks a successful rename.
- **Single source of truth for translations:** JSONB column on the row — same pattern as `heading_translations`, `caption_translations` (established in migration 021).
- **Reuse over reimplementation:** `translate_one_string` wraps `_translate_batch_with_retry` and `_call_llm_once` from `translate_catalog.py` — no new LLM plumbing.
- **Dialog provider pattern:** `useDialog().prompt()` (already live in `AdminBookContentPage.jsx`) — no new components, no new context.

**Why not async/background translation?**
The plan explicitly confirms synchronous rename translation (Decision 2). The ~2s wait is acceptable for an admin action and avoids a window where students see English before the background job completes ("no flicker" requirement).

---

## 6. Technology Stack

All additions use existing project stack. No new dependencies.

| Component | Technology | Notes |
|-----------|-----------|-------|
| New helper | Python async function | `backend/src/api/translation_helper.py` |
| LLM call | OpenAI `gpt-4o-mini` via existing `AsyncOpenAI` client | Same model as `translate_catalog.py` |
| DB column | PostgreSQL 15 JSONB `NOT NULL DEFAULT '{}'::jsonb` | Mirrors `heading_translations` |
| Migration | Alembic `op.add_column` | Pattern from `021_add_i18n_translation_columns.py` |
| Frontend dialog | `useDialog().prompt()` from existing `DialogProvider` context | Already used in `AdminBookContentPage.jsx` |
| Locale keys | i18next JSON files × 13 | Populated via existing `frontend/scripts/translate_locales.py` |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-01: Synchronous OpenAI call in rename handler

**Decision:** The rename handler awaits `translate_one_string()` before returning HTTP 200.

**Options considered:**
- A. Synchronous (chosen) — admin waits ~2s; no translation gap window for students.
- B. Background task (Celery/asyncio task) — faster response, but students may see English for seconds/minutes.

**Rationale:** Decision confirmed by user. A rename is a rare admin action; 2s is tolerable. Option B introduces a state gap that violates the "no flicker" requirement.

**Trade-offs:** +Simplicity, +no gap; -slightly slower admin UX on rename.

---

### ADR-02: New JSONB column vs. separate translations table

**Decision:** Single `admin_section_name_translations JSONB` column on `concept_chunks`.

**Options considered:**
- A. JSONB column (chosen) — mirrors `heading_translations`; zero join overhead; atomic update.
- B. Separate `section_name_translations` table — normalised but adds a join on every chunk fetch.

**Rationale:** Consistent with the pattern established in migration 021. The translations dict is small (<2 KB). No need for per-language row-level access.

---

### ADR-03: `translate_one_string` in `translation_helper.py` (not inline)

**Decision:** Extract into a new importable module rather than inlining in admin_router.py.

**Rationale:** admin_router.py already imports from multiple service modules. Keeping LLM logic in a dedicated helper makes it testable in isolation and reusable for future single-string translation needs (e.g., if book title renames are added later).

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| OpenAI outage during rename | Low | Medium | `asyncio.timeout(10.0)` + broad except; rename still succeeds; English shown until re-translated |
| `admin_section_name_translations` column missing after partial migration | Very low | High | `alembic upgrade head` is atomic per-column; verify with `\d concept_chunks` before deploying code |
| Stale cache after rename with translation failure | Low | Low | `invalidate_chunk_cache` is called regardless of translation success; students re-fetch and get latest English name |
| Audit undo restores English-only (pre-fix) row | Low | Low | `_undo_rename_section` already restores to `old_value`; we extend snapshot to include `admin_section_name_translations` so undo also restores translations |
| Locale key missing from one of 13 files | Medium | Medium | `translate_locales.py` is idempotent; CI lint (`npm run lint`) does not catch missing i18n keys — manual check required |
| `window.prompt` removal breaks existing tests | Low | Low | Only affects `AdminReviewPage.jsx`; Playwright e2e tests that relied on native dialog automation must be updated |

---

## Translation Lifecycle Diagram

```
New book ingestion (offline)
─────────────────────────────
pipeline.py Stage 7
  └─► translate_catalog.py (bulk, SHA-1 fingerprinted)
        └─► populates heading_translations, caption_translations,
            title_translations, subject_translations, label_translations
            (admin_section_name_translations NOT touched — column only
             populated on demand when admin sets a custom name)

Incremental re-run (changed rows only)
──────────────────────────────────────
translate_catalog.py --book <slug>
  └─► SHA-1 check: skip rows where en_source_hash matches AND
      all 12 lang keys present
  └─► Re-translate only changed or missing-language rows
      (this PR does NOT alter this path)

Admin section rename (on demand, synchronous)
─────────────────────────────────────────────
PATCH /api/admin/sections/{concept_id}/rename
  ├─► UPDATE concept_chunks SET admin_section_name = :name
  ├─► translate_one_string(name)  ──► OpenAI (~2s)
  ├─► UPDATE concept_chunks SET admin_section_name_translations = :t
  ├─► invalidate_chunk_cache()
  └─► commit

Per-language cache topology (already in place from Phase 1 main i18n)
──────────────────────────────────────────────────────────────────────
Teaching session chunk cache is keyed per (chunk_id, lang).
invalidate_chunk_cache() drops ALL language variants for affected chunks.
On next fetch, teaching_router re-resolves section_title via:
  resolve_translation(admin_section_name, admin_section_name_translations, lang)
```

---

## Key Decisions Requiring Stakeholder Input

1. **Backfill existing renamed sections:** Sections already renamed before this fix have `admin_section_name_translations = '{}'`. Non-English students continue to see English for those sections until re-translated. Options: (a) accept current gap — admins re-save to trigger translation; (b) run a one-off backfill script post-migration. No decision required to ship this PR, but product should be aware.

2. **Redo path for rename:** The current `apply_redo` in `audit_service.py` re-applies `admin_section_name` but not `admin_section_name_translations`. The DLD proposes extending redo to also re-call `translate_one_string`. Confirm this is acceptable (adds ~2s to redo).
