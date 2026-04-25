# Execution Plan — Complete i18n Coverage + Admin Re-trigger Invalidation

**Feature slug:** `i18n-complete-coverage`
**Date:** 2026-04-24
**Delivery model:** Four independent, sequentially mergeable PRs

---

## 1. Work Breakdown Structure

| ID | Title | Component | Est. (days) | Depends on |
|----|-------|-----------|-------------|-----------|
| P1-1 | `CacheAccessor` schema extension + new methods | `cache_accessor.py` | 0.5 | — |
| P1-2 | `invalidate_chunk_cache()` helper | `teaching_service.py` | 1.0 | P1-1 |
| P1-3 | Hook into all chunk admin handlers (update, toggle, merge, split, promote) | `admin_router.py` | 1.5 | P1-2 |
| P1-4 | Hook into all section admin handlers (rename, optional, exam, visibility) | `admin_router.py` | 1.0 | P1-2 |
| P1-5 | Hook into graph edge handlers (add/remove prerequisite) | `admin_router.py` | 0.5 | P1-2 |
| P1-6 | Hook into undo/redo helpers | `audit_service.py` | 1.0 | P1-2 |
| P1-7 | Exam question cache read/write in `chunk-cards` endpoint | `teaching_router.py` | 1.0 | P1-1 |
| P1-8 | Audit `prompts.py` + `prompt_builder.py` for missing `_language_instruction` | `prompts.py`, `prompt_builder.py` | 0.5 | — |
| **P1 Total** | | | **7.0** | |
| P2-1 | `test_cache_accessor_exam_questions.py` | `backend/tests/` | 0.5 | P1-1 |
| P2-2 | `test_invalidate_chunk_cache.py` | `backend/tests/` | 1.0 | P1-2 |
| P2-3 | `test_language_switch_regenerates_exam_questions.py` | `backend/tests/` | 1.0 | P1-7 |
| P2-4 | `test_admin_edit_invalidates_student_cache.py` | `backend/tests/` | 1.5 | P1-3, P1-4, P1-5, P1-6 |
| P2-5 | `test_mcq_options_respect_language.py` | `backend/tests/` | 0.5 | P1-8 |
| P2-6 | Extend `test_admin_audit.py` with invalidation assertions | `backend/tests/` | 0.5 | P1-6 |
| **P2 Total** | | | **5.0** | |
| P3-1 | Remove `label` from `tutorPreferences.js`; update `RegisterPage` + `SettingsPage` | `frontend/src/constants/`, `pages/` | 0.5 | — |
| P3-2 | Full i18n pass on `AdminBookContentPage.jsx` (~55 keys) | `frontend/src/pages/` | 2.0 | — |
| P3-3 | Replace `window.prompt()` with `dialog.prompt()` in `AdminBookContentPage.jsx` | `frontend/src/pages/` | 0.5 | P3-2 |
| P3-4 | Add all new keys to `en.json` | `frontend/src/locales/en.json` | 0.5 | P3-1, P3-2 |
| P3-5 | Run `translate_locale.mjs` to propagate to 12 other locale files | `frontend/src/locales/` | 0.5 | P3-4 |
| P3-6 | Human review pass on all 13 locale files | All locales | 1.0 | P3-5 |
| P3-7 | `LanguageSelector.jsx` — ensure `reloadCurrentChunk()` also reloads exam questions | `frontend/src/components/` | 0.5 | P1-7 |
| P3-8 | Verify `SessionContext.jsx` exam question state replaced (not appended) on reload | `frontend/src/context/` | 0.25 | P3-7 |
| P3-9 | Dashboard phase label audit across 13 locale files | `frontend/src/locales/` | 0.5 | — |
| P3-10 | `npm run lint` clean + manual RTL check (Arabic) | Frontend | 0.5 | P3-1 through P3-9 |
| **P3 Total** | | | **6.75** | |
| P4-1 | CI: add Playwright specs to test matrix | `.github/workflows/` | 0.5 | P2, P3 |
| P4-2 | Verify no new Alembic migration needed; confirm schema is stable | `alembic/` | 0.25 | P1 |
| P4-3 | `bust_session_exam_cache.py` one-shot script with `--dry-run` | `backend/scripts/` | 0.5 | P1 |
| **P4 Total** | | | **1.25** | |
| **Grand Total** | | | **20.0** | |

---

## 2. Phased Delivery Plan

---

### Phase 1 — Backend (PR #1)

**Goal:** All admin mutations invalidate the affected chunk's cache slice; exam questions are cached per-language-per-chunk and served from cache on repeat fetches.

**Ordered file changes:**

1. `backend/src/api/cache_accessor.py`
   - Add `get_exam_questions(chunk_id, lang)`, `set_exam_questions(chunk_id, questions, lang)`, `clear_exam_questions(chunk_id)` methods.
   - No change to existing methods or schema format (additive only).

2. `backend/src/api/teaching_service.py`
   - Add `async def invalidate_chunk_cache(db, chunk_ids)` helper function.
   - Import `CacheAccessor` (already imported in this file).

3. `backend/src/api/teaching_router.py` (exam question cache, lines ~971–1045)
   - Before the LLM call: check `ca.get_exam_questions(req.chunk_id)`.
   - On cache hit: return cached questions, skip LLM.
   - On cache miss: run LLM (existing code), call `ca.set_exam_questions(...)`, persist.
   - Add `from api.teaching_service import invalidate_chunk_cache` import (already in same file usually; check for circular import).

4. `backend/src/api/admin_router.py`
   - Add `from api.teaching_service import invalidate_chunk_cache` import at top.
   - In each of the 9 handler functions listed in DLD section 4: add one `await invalidate_chunk_cache(db, [chunk_id_or_list])` call after DB mutations, before `db.commit()`.

5. `backend/src/api/audit_service.py`
   - Add `from api.teaching_service import invalidate_chunk_cache` import.
   - In each `_undo_*` and `_redo_*` helper: add one `await invalidate_chunk_cache(...)` call.

6. `backend/src/api/prompts.py` + `backend/src/adaptive/prompt_builder.py`
   - Audit every function that constructs a system or user prompt for student-facing LLM calls.
   - Confirm `_language_instruction(lang)` is appended. Add where missing.

**Acceptance criteria:**

- `PATCH /students/{id}/language` followed by `POST /chunk-cards/next` returns exam questions in the new language (not English).
- After `POST /admin/sections/{id}/rename`, a concurrent active session's next `/chunk-cards` call returns regenerated cards (LLM mock call counter increments).
- `CacheAccessor.get_exam_questions()` returns cached questions on second call to `/chunk-cards` for same chunk/language (LLM mock call counter does NOT increment on second call).
- No change to any API response schema (additive fields only; no removals).
- `pytest -q backend/tests/` passes with no regressions.

**Estimated LOC:** ~200 new lines (helper ~60, cache methods ~40, admin hooks ~100).

**Rollback plan:** Revert the PR. The `invalidate_chunk_cache` helper is additive; not calling it simply restores the current behaviour (no invalidation). The exam-question caching path has a cache-miss fallback to the LLM, so even if removed, behaviour degrades to "always generate" (current behaviour).

---

**PR description draft:**

```
feat(backend): scoped cache invalidation + exam question caching

- Add `invalidate_chunk_cache(db, chunk_ids)` helper to teaching_service.
  Clears card + exam-question slices for the affected chunks across all
  active sessions, in every language. Called after every admin mutation.
- Add `get_exam_questions` / `set_exam_questions` / `clear_exam_questions`
  to CacheAccessor. Exam questions now cached in the per-language slice
  alongside cards, keyed by chunk_id.
- Exam question generation in teaching_router now checks cache first;
  LLM only called on cache miss.
- Hook `invalidate_chunk_cache` into all admin handlers (section rename,
  toggle optional/exam/visibility, chunk update/merge/split/promote,
  graph edge add/remove) and into all undo/redo helpers.
- Audit prompts.py + prompt_builder.py for missing _language_instruction.

No new Alembic migration. No API contract changes (additive only).

Closes: [ticket]
```

---

### Phase 2 — Tests (PR #2)

**Goal:** Comprehensive unit and integration coverage so the backend invalidation guarantees are machine-verifiable before any frontend work.

**Ordered test files:**

1. `backend/tests/test_cache_accessor_exam_questions.py` (new)
   - `test_set_and_get_exam_questions_round_trips`
   - `test_mark_stale_clears_exam_questions_for_language`
   - `test_clear_exam_questions_across_all_languages`
   - `test_size_cap_eviction_does_not_corrupt_exam_questions`

2. `backend/tests/test_invalidate_chunk_cache.py` (new)
   - `test_no_sessions_returns_zero`
   - `test_session_not_referencing_chunk_untouched`
   - `test_single_session_single_chunk_cleared`
   - `test_multi_language_slices_all_cleared`
   - `test_other_language_slices_for_other_chunks_preserved`

3. `backend/tests/test_language_switch_regenerates_exam_questions.py` (new)
   - Mock AsyncOpenAI; assert mock called on cache miss after language switch.
   - Assert response contains Tamil text (non-ASCII threshold >= 5 chars non-ASCII).

4. `backend/tests/test_admin_edit_invalidates_student_cache.py` (new, parametrised)
   - Parameters: `rename_section`, `toggle_section_optional`, `toggle_section_exam_gate`, `toggle_section_visibility`, `update_chunk`, `toggle_chunk_visibility`, `toggle_chunk_exam_gate`, `merge_chunks`, `split_chunk`, `promote_chunk`, `prereq_add`, `prereq_remove`, `undo_rename`, `redo_rename`.
   - Each: seed active session with cached exam questions → call admin handler → assert `get_exam_questions()` returns None.

5. `backend/tests/test_mcq_options_respect_language.py` (new)
   - Capture system prompt strings via mock; assert `_language_instruction` fragment present.

6. `backend/tests/test_admin_audit.py` (extend existing)
   - Add `test_undo_invalidates_cache` and `test_redo_invalidates_cache`.

**Fixtures needed:**

| Fixture | Description |
|---------|-------------|
| `seeded_student_with_session` | Student + active TeachingSession with warm cache |
| `mock_openai_client` | AsyncMock returning deterministic JSON |
| `db_session` | Async SQLAlchemy session (already in `conftest.py`) |
| `admin_user` | User with `is_admin=True` |

**Estimated LOC:** ~450 new lines across 6 files.

**Dependencies:** Phase 1 merged.

**Rollback plan:** Tests are additive; deleting the test files has no production impact.

---

**PR description draft:**

```
test: unit + integration coverage for i18n cache invalidation

- test_cache_accessor_exam_questions.py: 4 unit tests for new
  CacheAccessor exam-question methods.
- test_invalidate_chunk_cache.py: 5 parametrised tests for
  the invalidation helper, including multi-language isolation.
- test_language_switch_regenerates_exam_questions.py: LLM
  mock counter asserts regeneration after language switch.
- test_admin_edit_invalidates_student_cache.py: 14-parameter
  suite covering every admin handler + undo/redo.
- test_mcq_options_respect_language.py: prompt audit tests.
- test_admin_audit.py: two new undo/redo invalidation assertions.

All tests pass locally: pytest -q backend/tests/

Closes: [ticket]
```

---

### Phase 3 — Frontend (PR #3)

**Goal:** Every user-visible string in the student and admin UI routes through `t()` and is present in all 13 locale files.

**Ordered file changes:**

1. `frontend/src/constants/tutorPreferences.js`
   - Remove `label` field from `TUTOR_STYLES` entries.
   - No change to `INTEREST_OPTIONS` (id already serves as lookup key).

2. `frontend/src/pages/RegisterPage.jsx` (~line 532)
   - Replace `style.label` with `t(\`tutorStyles.${style.id}\`)`.
   - Replace interest rendering with `t(\`interests.${opt.id}\`)`.

3. `frontend/src/pages/SettingsPage.jsx` (~line 318)
   - Same replacements as `RegisterPage.jsx`.

4. `frontend/src/pages/AdminBookContentPage.jsx`
   - Add `const { t } = useTranslation();` (currently `useTranslation()` is called but `t` is not destructured).
   - Replace every hardcoded string with `t("adminContent.<key>")` per the catalogue in DLD section 5c.
   - Replace two `window.prompt()` calls with `await dialog.prompt(t("adminContent.<key>"))` using `DialogProvider`.
   - Replace `alert()` in rename-book handler with `toast()`.

5. `frontend/src/components/LanguageSelector.jsx`
   - Confirm that after `reloadCurrentChunk()`, the `examQuestions` state in `SessionContext` is fully replaced.
   - If not, add dispatch of appropriate action (see DLD section 7).

6. `frontend/src/context/SessionContext.jsx`
   - Confirm `LANGUAGE_CHANGED` reducer and `reloadCurrentChunk()` consumer overwrites `examQuestions`.
   - Add `RELOAD_EXAM_QUESTIONS` action if needed (clears `examQuestions` to null, triggering refetch).

7. `frontend/src/locales/en.json`
   - Add all keys from DLD catalogue sections 5a, 5b, 5c.
   - Estimated additions: 4 tutorStyles + 10 interests + ~55 adminContent = ~69 keys.

8. `frontend/src/locales/{ar,de,es,fr,hi,ja,ko,ml,pt,si,ta,zh}.json` (12 files)
   - Run `scripts/translate_locale.mjs` (new Node helper using OpenAI) with `en.json` diff as source.
   - Script reads new keys from `en.json`, calls OpenAI with target language, writes translated values.
   - Human review pass on all 12 files (especially tutor style cultural terms).

9. `frontend/src/pages/DashboardPage.jsx`
   - Audit all phase label strings. Ensure all use `t("dashboard.*")` keys present in all 13 locales.

**Locale population approach:**

```bash
# 1. Update en.json with all new keys (manual, step 7 above)
# 2. Run translation helper
node scripts/translate_locale.mjs \
  --source frontend/src/locales/en.json \
  --output-dir frontend/src/locales/ \
  --languages ar,de,es,fr,hi,ja,ko,ml,pt,si,ta,zh \
  --keys-file scripts/new_i18n_keys.txt  # list of only new keys to avoid re-translating existing

# 3. Human review: open each file in diff view, adjust culturally loaded terms
# 4. npm run lint
# 5. Manual RTL check: switch UI to Arabic; verify admin editor and student views layout correctly
```

**Estimated LOC:** ~600 new lines (AdminBookContentPage refactor ~200, locale files ~350, other ~50).

**Dependencies:** Phase 1 merged (exam question reload path). Phase 2 not a hard dependency (tests are backend-only) but should be green before PR #3 merges.

**Rollback plan:** All changes are purely additive (new locale keys) or substitutional (hardcoded string → `t()` call). Rolling back removes the translated strings but does not break any data or API contracts. Feature flag not needed — the locale fallback (`en`) is always present.

---

**PR description draft:**

```
feat(frontend): complete i18n pass — admin editor, tutor styles, interests

- AdminBookContentPage: destructure t() from useTranslation (was imported
  but unused). Replace all ~55 hardcoded strings with t("adminContent.*").
  Replace window.prompt() with dialog.prompt() for translatable labels.
  Replace alert() with toast().
- tutorPreferences.js: remove label field from TUTOR_STYLES.
  RegisterPage + SettingsPage render t(`tutorStyles.${id}`) and
  t(`interests.${id}`) instead.
- en.json: +69 new keys (4 tutorStyles, 10 interests, 55 adminContent).
- All 12 other locale files: LLM-generated translations, human-reviewed.
- LanguageSelector: confirm exam questions reload alongside cards after
  language switch (session_cache_cleared path).
- DashboardPage: phase label i18n audit across all 13 locales.

npm run lint: clean.
Manual RTL (Arabic) walkthrough: admin editor + student views verified.

Closes: [ticket]
```

---

### Phase 4 — DevOps (PR #4)

**Goal:** CI runs the new Playwright specs; a one-shot cache-bust script is available for ops.

**Ordered changes:**

1. `.github/workflows/` (or equivalent CI config)
   - Add Playwright test step that runs:
     ```bash
     cd frontend && npm run test:e2e -- \
       non-english-student.spec.js \
       admin-content-crud.spec.js \
       admin-i18n.spec.js
     ```
   - Ensure the backend dev server is started before the Playwright step (use existing `before-test` setup hook or add a start script).
   - Set `PLAYWRIGHT_TIMEOUT=90000` for the non-English student spec (LLM calls in test may be slow).

2. `backend/scripts/bust_session_exam_cache.py` (new)
   - CLI script to clear `exam_questions_by_chunk` from all active sessions.
   - Usage: `python -m scripts.bust_session_exam_cache --dry-run` shows count; without flag, clears.
   - Use case: one-time bust after Phase 1 deploys, to clear any exam questions cached before the language instruction fix.
   - Implementation: iterate `TeachingSession` where `completed_at IS NULL`; use `CacheAccessor` to clear `exam_questions_by_chunk` from all language slices.

3. Alembic check
   - Confirm no migration is required (Phase 1 uses only existing `presentation_text` JSON column).
   - Document in PR that migration is intentionally absent.

**Estimated LOC:** ~80 new lines (CI config ~20, bust script ~60).

**Dependencies:** Phase 1, 2, and 3 all merged.

**Rollback plan:** Removing the CI step re-disables the new E2E specs but does not affect production. The bust script is a read-only diagnostic under `--dry-run`; the write path is idempotent (clearing an already-empty field is a no-op).

---

**PR description draft:**

```
ci: add Playwright i18n specs + session exam cache bust script

- CI: three new Playwright spec files run in test matrix.
  Backend started before Playwright step; timeout 90s for LLM-backed specs.
- scripts/bust_session_exam_cache.py: one-shot CLI to clear
  exam_questions_by_chunk from all active sessions. Use --dry-run to preview.
  Intended for post-deploy ops run after Phase 1 ships.
- Alembic: no migration needed; JSON column extension is schema-free.

Closes: [ticket]
```

---

## 3. Dependencies and Critical Path

```
P1-1 (CacheAccessor)
  └─ P1-2 (invalidate helper)
       ├─ P1-3 (chunk handlers)
       ├─ P1-4 (section handlers)
       ├─ P1-5 (graph handlers)
       └─ P1-6 (undo/redo)        ←─ CRITICAL PATH (undo coverage is easily missed)
P1-1 ──► P1-7 (exam cache in router)
P1-8 (prompt audit) — independent

Phase 2 depends on Phase 1 (all P1 tasks).
Phase 3 depends on P1-7 (exam reload on language switch).
Phase 4 depends on all phases.

Critical path: P1-1 → P1-2 → P1-6 → P2-6 (undo test)
```

**Blocking external dependencies:**

| Dependency | Phase | Owner |
|-----------|-------|-------|
| Human reviewer for locale files | P3 | Product / regional leads |
| CI environment has Playwright + Chromium | P4 | DevOps |
| Backend dev server startable in CI | P4 | DevOps |

---

## 4. Definition of Done

### Phase 1

- [ ] `pytest -q backend/tests/` green (no regressions).
- [ ] `GET /chunk-cards` returns cached exam questions on second fetch for same chunk/language (verified by mock counter).
- [ ] After any admin mutation, active session's exam questions for that chunk cleared (verified by `ca.get_exam_questions()` returning None).
- [ ] Code reviewed; no magic constants (all thresholds in `config.py`).
- [ ] Logging confirms `[invalidate]` entries for each admin mutation in integration test.

### Phase 2

- [ ] All new test files pass: `pytest -q backend/tests/test_cache_accessor_exam_questions.py backend/tests/test_invalidate_chunk_cache.py backend/tests/test_language_switch_regenerates_exam_questions.py backend/tests/test_admin_edit_invalidates_student_cache.py backend/tests/test_mcq_options_respect_language.py`.
- [ ] `test_admin_edit_invalidates_student_cache.py` covers all 14 parametrised operations.
- [ ] Code reviewed.

### Phase 3

- [ ] `npm run lint` clean.
- [ ] All 13 locale files contain every key from the DLD catalogue (automated check: `scripts/check_locale_keys.mjs`).
- [ ] No `window.prompt()` or `window.alert()` calls remain in `AdminBookContentPage.jsx`.
- [ ] `useTranslation()` is called and `t` is used in `AdminBookContentPage.jsx`.
- [ ] Manual walkthrough: Malayalam student sees no English strings end-to-end.
- [ ] Manual walkthrough: Arabic admin editor lays out correctly (RTL).
- [ ] Human reviewer sign-off on all 12 non-English locale files.

### Phase 4

- [ ] CI pipeline green with all three Playwright specs.
- [ ] `bust_session_exam_cache.py --dry-run` runs without error.
- [ ] Alembic check: `alembic check` returns "no new upgrade operations detected".

---

## 5. Rollout Strategy

**Deployment approach:** Standard deploy (no feature flags required for backend invalidation logic — it is a pure improvement with no behaviour regression risk). Frontend locale additions are purely additive; missing key falls back to `en` so no UI breakage even if a locale file is incomplete.

**Deployment order:**
1. Phase 1 (backend) → deploy to staging → run `bust_session_exam_cache.py --dry-run`.
2. Phase 2 (tests) → merge to main alongside or after Phase 1; no deployment needed.
3. Phase 3 (frontend) → deploy after Phase 1 is live (exam reload depends on Phase 1 API behaviour).
4. Phase 4 (devops) → CI update; run `bust_session_exam_cache.py` (without `--dry-run`) once in production.

**Rollback plan:**
- Phase 1 rollback: revert PR #1. Admin edits will no longer bust cache (existing behaviour). No data loss.
- Phase 3 rollback: revert PR #3. Tutor style labels fall back to rendering the English ID string. No data loss.

**Post-launch validation steps:**
1. Trigger an admin rename on a live section while a student session is active (staging). Verify the student's next card fetch logs `[exam-cache] miss` and generates in the correct language.
2. Switch language to Malayalam on a live session. Verify next `/chunk-cards` response contains non-ASCII exam question text.
3. Check `i18n_session_cache_eviction_total` metric does not spike after deploy (would indicate unexpected large-session size growth).

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 1 — Backend | CacheAccessor extension, invalidation helper, 9 admin hooks, undo/redo hooks, exam cache in router, prompt audit | 7.0 days | 1 backend developer |
| Phase 2 — Tests | 6 test files, 14-parametrised suite, mock fixtures | 5.0 days | 1 comprehensive tester |
| Phase 3 — Frontend | Admin editor i18n (~55 keys), tutor/interest labels, locale propagation, LanguageSelector reload, human review | 6.75 days | 1 frontend developer + human locale reviewers |
| Phase 4 — DevOps | CI Playwright step, bust script, Alembic check | 1.25 days | 1 devops engineer |
| **Total** | | **20.0 days** | 4 roles, parallel after P1 merges |

With Phase 1 on the critical path, realistic calendar time with 4 parallel agents after P1 ships: **~10–12 calendar days**.

---

## Key Decisions Requiring Stakeholder Input

1. **Locale review SLA:** The human review pass on 12 locale files (Phase 3, P3-6) is estimated at 1.0 day but depends on reviewers being available. If this is a bottleneck, Phase 3 can ship without human-reviewed locales (LLM-only) and the review pass can follow in a fast-follow PR.

2. **`bust_session_exam_cache.py` run timing:** Should this script run automatically as a post-deploy step (Phase 4 CI), or be run manually by an operator? Current plan is manual with `--dry-run` safety.

3. **Exam question cache TTL:** Should there be a configurable TTL (e.g. `EXAM_QUESTION_CACHE_TTL_HOURS` in `config.py`) so questions older than N hours are regenerated? Not in current design — stakeholder input requested before Phase 1 implementation.
