# Execution Plan — i18n End-to-End Rework

**Feature slug:** `i18n-rework`
**Date authored:** 2026-04-23
**Source-of-truth docs:** `docs/i18n-rework/HLD.md`, `docs/i18n-rework/DLD.md`

---

## PR Template

Every PR for this effort must include the following header in its description:

```
## i18n-rework reference
- **Doc section:** [HLD §X / DLD §Y / execution-plan Phase Z]
- **Phase:** [0 / 1 / 2 / 3 / 4 / 5 / 6]
- **Task IDs:** [e.g. P3-1, P3-2]
- **Depends on:** [PR number or "none"]
- **Rollback step:** [command or "revert this commit"]
```

Agents must update `docs/i18n-rework/execution-plan.md` (mark tasks Done) before tagging the PR as Ready for Review.

---

## 1. Work Breakdown Structure (WBS)

### Phase 0 — Housekeeping (backend-developer, no deps)

| ID | Title | Description | Effort | Owner | Files Touched |
|----|-------|-------------|--------|-------|---------------|
| P0-1 | Update CLAUDE.md | Remove stale "language locked at session start → 409" note from CLAUDE.md gotchas | 0.1d | backend-developer | `CLAUDE.md` |
| P0-2 | Create `dependencies.py` | New file with `get_request_language()`, `resolve_translation()`, `SUPPORTED_LANG_CODES` | 0.5d | backend-developer | `backend/src/api/dependencies.py` (new) |
| P0-3 | Unit tests for helpers | `test_i18n_helpers.py` covering all branches of both helpers and `CacheAccessor` | 0.5d | comprehensive-tester | `backend/tests/test_i18n_helpers.py` (new) |

### Phase 1 — Locale Key Backfill (frontend-developer, no deps)

| ID | Title | Description | Effort | Owner | Files Touched |
|----|-------|-------------|--------|-------|---------------|
| P1-1 | Identify 33 missing keys | Confirm exact list via `python3` diff script (already run; 33 keys in `admin.settings.*` + `learning.completeChunk`) | 0.1d | frontend-developer | — |
| P1-2 | Backfill all 33 keys in 12 locale files | Add translations for each missing key using LLM or human review. Includes `map.sectionShort` and `lang.switchingTo` (already in `en.json`; confirm present in others). | 1.0d | frontend-developer | `frontend/src/locales/{ar,de,es,fr,hi,ja,ko,ml,pt,si,ta,zh}.json` |
| P1-3 | CI check script | Create `frontend/scripts/check-locales.mjs`; wire into `npm run lint:locales` and extend `npm run lint` | 0.5d | frontend-developer | `frontend/scripts/check-locales.mjs` (new), `frontend/package.json` |
| P1-4 | Tests — CI script | Run `node scripts/check-locales.mjs` in CI pipeline; confirm exit 0 | 0.2d | devops-engineer | `.github/workflows/` or equivalent CI config |

### Phase 2 — Frontend Re-fetch Wiring (frontend-developer, no deps)

| ID | Title | Description | Effort | Owner | Files Touched |
|----|-------|-------------|--------|-------|---------------|
| P2-1 | Dashboard dep arrays | Add `i18n.language` to `useEffect` deps at lines 75 and 78 of `DashboardPage.jsx` | 0.2d | frontend-developer | `frontend/src/pages/DashboardPage.jsx` |
| P2-2 | Localize `formatConceptTitle` | Update signature to accept optional `t`; add `t("map.sectionShort", {num})` path | 0.3d | frontend-developer | `frontend/src/utils/formatConceptTitle.js` |
| P2-3 | Dashboard activity — prefer backend title | In the Recent Activity section renderer, prefer `session.concept_title` (when present) over `formatConceptTitle(session.concept_id, t)` | 0.3d | frontend-developer | `frontend/src/pages/DashboardPage.jsx` |
| P2-4 | Remove AppShell selector | Delete `<LanguageSelector compact />` mount from `AppShell.jsx` line ~306 | 0.1d | frontend-developer | `frontend/src/components/layout/AppShell.jsx` |
| P2-5 | Unit test — `formatConceptTitle` | Verify `t` callback is invoked with correct key and param | 0.2d | comprehensive-tester | `frontend/src/utils/formatConceptTitle.test.js` (new) |
| P2-6 | E2E test — no selector on lesson | `e2e/language-no-selector-on-lesson.spec.js` — navigate to `/learn/**`, assert no selector | 0.2d | comprehensive-tester | `frontend/e2e/language-no-selector-on-lesson.spec.js` (new) |

### Phase 3 — JSONB Columns + Backfill + Endpoints (backend-developer + devops-engineer; depends on P0)

| ID | Title | Description | Effort | Owner | Files Touched |
|----|-------|-------------|--------|-------|---------------|
| P3-1 | Alembic migration | Author `021_add_i18n_translation_columns.py`; five JSONB columns, default `'{}'::jsonb` | 0.5d | devops-engineer | `backend/alembic/versions/021_...py` (new) |
| P3-2 | ORM model additions | Add 5 mapped columns to `Book`, `Subject`, `ConceptChunk`, `ChunkImage` | 0.3d | backend-developer | `backend/src/db/models.py` |
| P3-3 | `scripts/translate_catalog.py` | Full backfill script: argparse, idempotency, batch LLM, `_seed_from_legacy_cache` | 1.5d | backend-developer | `backend/scripts/translate_catalog.py` (new) |
| P3-4 | Update `GET /api/v1/books` | Use `get_request_language()`, `resolve_translation()`, add `subject_slug`, `has_translations` | 0.5d | backend-developer | `backend/src/api/main.py` |
| P3-5 | Update `GET /api/v1/graph/full` | Add per-request heading overlay from `heading_translations` | 0.5d | backend-developer | `backend/src/api/main.py` |
| P3-6 | Update `GET /students/{id}/sessions` | LATERAL join to resolve `concept_title` + `book_title` in student's language | 0.5d | backend-developer | `backend/src/api/teaching_router.py` |
| P3-7 | Integration tests — new endpoints | `test_books_endpoint_language.py`, `test_sessions_with_titles.py`, `test_graph_endpoint_language.py`, `test_untranslated_book_graceful.py` | 1.0d | comprehensive-tester | `backend/tests/test_i18n_endpoints.py` (new) |
| P3-8 | Dry-run Business Statistics backfill | `python scripts/translate_catalog.py --book business_statistics --dry-run` on dev | 0.2d | devops-engineer | — |
| P3-9 | Delete `useConceptMap.js` LLM block | Remove lines 42–57 and the `translateConceptTitles` import | 0.2d | frontend-developer | `frontend/src/hooks/useConceptMap.js` |
| P3-10 | Frontend — consume `concept_title` / `book_title` in Dashboard | Wire `session.concept_title` and `session.book_title` into Dashboard Recent Activity rendering (P2-3 already prepared the render path) | 0.2d | frontend-developer | `frontend/src/pages/DashboardPage.jsx` |

### Phase 3 Deployment (Production)

After Phase 3 tests pass in dev/staging:

1. `alembic upgrade head` — applies migration 021.
2. Restart backend service.
3. Confirm `GET /api/v1/books` returns English titles (schema is valid; translations column is `{}`).
4. Run one-time Business Statistics backfill:
   ```bash
   cd backend
   source ../.venv/bin/activate
   DATABASE_URL=<prod_url> OPENAI_API_KEY=<key> python scripts/translate_catalog.py \
     --book business_statistics \
     --languages all \
     --batch-size 50
   ```
   Expected runtime: 2–4 minutes. Expected cost: < $1 USD.
5. Verify: `GET /api/v1/books` with `Accept-Language: ml` returns Malayalam titles.
6. Verify: Concept map in the app loads with Malayalam node titles for Business Statistics.

**Rollback:** `alembic downgrade -1` removes the five JSONB columns. Zero data loss (columns were additive with empty defaults).

### Phase 4 — Delete Runtime LLM Translation (backend-developer + frontend-developer; depends on P3)

| ID | Title | Description | Effort | Owner | Files Touched |
|----|-------|-------------|--------|-------|---------------|
| P4-1 | Rewrite `PATCH /students/{id}/language` | Replace `_translate_summaries_headings` LLM call with DB SELECT on `heading_translations`; update session cache to use `CacheAccessor.mark_language_stale()` | 1.0d | backend-developer | `backend/src/api/teaching_router.py` |
| P4-2 | Delete `POST /api/v2/concepts/translate-titles` | Remove endpoint from `main.py:615`. Remove `TranslateTitlesRequest` class. Remove `_title_translation_cache` / `_load_translation_cache` / `_save_translation_cache`. Delete `backend/translation_cache.json`. | 0.5d | backend-developer | `backend/src/api/main.py` |
| P4-3 | Delete `translateConceptTitles` from frontend | Remove export from `concepts.js`; remove any remaining import sites. | 0.2d | frontend-developer | `frontend/src/api/concepts.js` |
| P4-4 | LanguageSelector race reversal | Update `selectLanguage()` to: overlay → API → i18n → localStorage; abort on API error; show toast | 0.5d | frontend-developer | `frontend/src/components/LanguageSelector.jsx` |
| P4-5 | Integration test — language switch latency | `test_language_change_fast.py` — asserts p95 < 200 ms; fails build if exceeded | 0.5d | comprehensive-tester | `backend/tests/test_language_change_fast.py` (new) |
| P4-6 | E2E test — error path | `language-switch.spec.js` test: mock API error; assert toast and language unchanged | 0.3d | comprehensive-tester | `frontend/e2e/language-switch.spec.js` (new/extend) |

### Phase 5 — Per-language Cache + Reducer Fix (backend-developer + frontend-developer; depends on P4)

| ID | Title | Description | Effort | Owner | Files Touched |
|----|-------|-------------|--------|-------|---------------|
| P5-1 | `CacheAccessor` class | Add `CacheAccessor` class to `teaching_service.py` per DLD §5.3 | 1.0d | backend-developer | `backend/src/api/teaching_service.py` |
| P5-2 | Wire `CacheAccessor` into chunk-cards and assist endpoints | Replace direct `json.loads(presentation_text)` calls with `CacheAccessor` reads/writes; guard all `json.loads` sites with `json-repair` fallback | 1.0d | backend-developer | `backend/src/api/teaching_service.py`, `backend/src/api/teaching_router.py` |
| P5-3 | Wire `CacheAccessor` into language-change endpoint | Call `CacheAccessor.ensure_by_language_shape()` then `mark_language_stale()` instead of flat JSON reset | 0.3d | backend-developer | `backend/src/api/teaching_router.py` |
| P5-4 | Fix `LANGUAGE_CHANGED` reducer | Update `SessionContext.jsx:383–395` to preserve `cardAnswers`, `currentCardIndex`, `maxReachedIndex` | 0.2d | frontend-developer | `frontend/src/context/SessionContext.jsx` |
| P5-5 | Unit tests — `CacheAccessor` | Legacy shape upgrade, LRU eviction at 5 languages, size cap enforcement, `mark_language_stale` | 0.5d | comprehensive-tester | `backend/tests/test_i18n_helpers.py` (extend P0-3) |
| P5-6 | Integration test — per-language cache | `test_per_language_cache.py` — ML → EN toggle reuses EN cache; cache miss triggers generation | 0.5d | comprehensive-tester | `backend/tests/test_per_language_cache.py` (new) |
| P5-7 | Integration test — legacy shape adapter | `test_legacy_cache_shape_adapter.py` — existing session with flat JSON is not broken | 0.3d | comprehensive-tester | `backend/tests/test_legacy_cache_shape_adapter.py` (new) |
| P5-8 | SessionContext unit test | `LANGUAGE_CHANGED` action preserves card state | 0.2d | comprehensive-tester | `frontend/src/context/SessionContext.test.js` (extend) |
| P5-9 | Full E2E language switch test | `language-switch.spec.js` — EN → ML on Dashboard: books/map/sessions all in ML; cards generate in ML | 0.5d | comprehensive-tester | `frontend/e2e/language-switch.spec.js` (extend) |

### Phase 6 — Pipeline Translation Hook (backend-developer; depends on P3)

| ID | Title | Description | Effort | Owner | Files Touched |
|----|-------|-------------|--------|-------|---------------|
| P6-1 | `translate_catalog_for_book()` in backfill script | Extract reusable async function from `translate_catalog.py` that accepts `book_slug`, `db`, `dry_run` | 0.5d | backend-developer | `backend/scripts/translate_catalog.py` |
| P6-2 | Pipeline Stage 3 hook | Insert `translate_catalog_inline()` call at end of `--chunks` pipeline run in `pipeline.py` | 0.5d | backend-developer | `backend/src/pipeline.py` |
| P6-3 | Pipeline integration test | Run pipeline on a small test book slug; confirm Stage 3 populates `heading_translations`; confirm re-run costs 0 LLM calls | 0.5d | comprehensive-tester | `backend/tests/test_pipeline_translation.py` (new) |

---

## 2. Phased Delivery Plan

### Phase 0 — Foundation (Day 1)
**Scope:** CLAUDE.md cleanup + `dependencies.py` + unit tests.
**Acceptance:** `test_i18n_helpers.py` passes with 100 % coverage of both helper functions and `CacheAccessor`.
**Rollback:** Revert `dependencies.py`. No schema change. No migration.

### Phase 1 — Locale Gaps (Day 1–2, parallel with Phase 0)
**Scope:** 33 missing keys + `map.sectionShort` + CI check.
**Acceptance:** `npm run lint:locales` exits 0 on all locale files. CI fails on a deliberately removed key (verified locally by the developer before merge).
**Rollback:** Revert locale file changes. The CI check going away is not harmful.

### Phase 2 — Frontend Re-fetch Wiring (Day 2–3, parallel with Phase 0)
**Scope:** Dashboard dep arrays + `formatConceptTitle` signature + AppShell selector removal.
**Acceptance:** After switching language on Dashboard, `getSessions()` and `getAvailableBooks()` are called again (confirmed via browser network tab). No language selector visible in lesson routes. `formatConceptTitle.test.js` passes.
**Rollback:** Revert the three frontend file changes.

### Phase 3 — DB + Endpoints (Day 3–6; depends on P0)
**Scope:** Migration + ORM + backfill script + books/graph/sessions endpoint changes + frontend graph hook cleanup.
**Acceptance:**
- `alembic upgrade head` succeeds in staging.
- `GET /api/v1/books` with `Accept-Language: ml` returns `title` in Malayalam for Business Statistics (after backfill).
- `GET /api/v1/graph/full` node titles in Malayalam.
- `GET /students/{id}/sessions` returns `concept_title` in student's language.
- All integration tests pass.
- `test_untranslated_book_graceful.py` passes (Prealgebra returns English, not empty).
**Rollback:** `alembic downgrade -1`. Revert endpoint changes in `main.py` and `teaching_router.py`.

### Phase 4 — Delete LLM Translation (Day 7–8; depends on P3)
**Scope:** `PATCH /students/{id}/language` rewrite + endpoint deletion + frontend cleanup + LanguageSelector race reversal.
**Acceptance:**
- `test_language_change_fast.py` passes (p95 < 200 ms).
- `POST /api/v2/concepts/translate-titles` returns 404.
- Frontend `useConceptMap` does not call `translateConceptTitles` (verified by test).
- Language switch success path: overlay shows, API succeeds, i18n changes, localStorage updated.
- Language switch failure path: toast shown, language unchanged.
**Rollback:** Revert `main.py` (restore endpoint) + revert `teaching_router.py` + revert `LanguageSelector.jsx`. Re-deploy `translation_cache.json` from backup.

### Phase 5 — Per-language Cache (Day 9–11; depends on P4)
**Scope:** `CacheAccessor` class + wire into teaching service + `LANGUAGE_CHANGED` reducer fix.
**Acceptance:**
- `test_per_language_cache.py` passes.
- `test_legacy_cache_shape_adapter.py` passes.
- EN → ML → EN toggle: second EN load is instant (cache hit, no LLM call).
- Existing sessions (flat JSON) are not broken after deploy.
**Rollback:** Revert `teaching_service.py` and `SessionContext.jsx`. No schema change to roll back.

### Phase 6 — Pipeline Hook (Day 9–11, parallel with Phase 5; depends on P3)
**Scope:** `translate_catalog_for_book()` extraction + pipeline Stage 3 insertion.
**Acceptance:**
- Running pipeline on a test book slug results in `heading_translations` populated.
- Re-running the same pipeline costs 0 OpenAI calls (hash check).
- Pipeline exits non-zero if Stage 0–2 fails; Stage 3 failure is non-fatal (warning).
**Rollback:** Revert `pipeline.py`. Stage 3 is a try/except; removing it is safe.

---

## 3. Dependencies and Critical Path

```
P0 ──────────────────────────────────────────────── P3 → P4 → P5
                                                     ↑
P1 ─── (parallel, no blocking dep) ─────────────────┘ (P1 blocks Phase 3 PR
                                                         merge only for locale check)
P2 ─── (parallel, no blocking dep) ─────────────────────────────────────────────────────
                                                     P3 ──── P6 (parallel with P5)
```

**Critical path:** P0-2 → P3-1 through P3-7 → P4-1 through P4-5 → P5-1 through P5-9.

**Blocking external dependencies:**
- `alembic upgrade head` must run on production before Phase 3 endpoint changes are deployed. The devops-engineer agent owns the migration.
- Business Statistics backfill command (see Phase 3 Deployment section) must run before Phase 4 deploys on production (otherwise, the language-change endpoint switches to DB lookup but `heading_translations` is empty for Business Statistics).

---

## 4. Definition of Done

### Per-phase DoD

**Phase 0:**
- [ ] `CLAUDE.md` no longer contains stale 409 language note.
- [ ] `backend/src/api/dependencies.py` exists and exports `get_request_language`, `resolve_translation`, `SUPPORTED_LANG_CODES`.
- [ ] `test_i18n_helpers.py` passes; coverage includes all branches.
- [ ] PR references `DLD §5.1, §5.2` and `execution-plan Phase 0`.

**Phase 1:**
- [ ] `npm run lint:locales` exits 0.
- [ ] `npm run lint` includes locale check (fails on missing key).
- [ ] All 33 previously-missing keys are present across all 12 non-EN files.
- [ ] `map.sectionShort` and `lang.switchingTo` confirmed present in all 12 files.
- [ ] CI pipeline runs locale check on every PR.

**Phase 2:**
- [ ] Language switch on Dashboard re-fetches books and sessions.
- [ ] No `<LanguageSelector>` rendered on lesson routes (E2E test passes).
- [ ] `formatConceptTitle.test.js` passes.
- [ ] `DashboardPage.jsx` uses `session.concept_title` when available.

**Phase 3:**
- [x] Migration `021_add_i18n_translation_columns.py` exists and passes `alembic upgrade head` in staging.
- [x] All five JSONB columns exist in production schema.
- [ ] Business Statistics backfill command ran successfully on production.
- [x] `GET /api/v1/books` with `Accept-Language: ml` returns ML titles for Business Statistics.
- [x] `GET /api/v1/graph/full` returns ML node titles for Business Statistics.
- [x] `GET /students/{id}/sessions` returns `concept_title` and `book_title` fields.
- [x] Prealgebra graceful fallback test passes.
- [x] `useConceptMap.js` no longer imports or calls `translateConceptTitles`.
- [x] All integration tests in `test_i18n_endpoints.py` pass.
- [x] `subject_slug` present in `GET /api/v1/books` response (DLD §3.1; closeout F2, 2026-04-24).

**Phase 4:**
- [x] `POST /api/v2/concepts/translate-titles` returns 404.
- [ ] `test_language_change_fast.py` passes (p95 < 200 ms in test environment).
- [x] `LanguageSelector.jsx` follows new race order (API first, i18n on success, abort on error).
- [x] Error toast shown on API failure (verifiable in E2E test).
- [x] `backend/translation_cache.json` file deleted (closeout F3, 2026-04-24).
- [x] All Phase 4 tests pass.

**Phase 5:**
- [x] `CacheAccessor` class present in `teaching_service.py` with all five methods.
- [ ] EN → ML → EN triple-toggle: third load is instant (no LLM).
- [x] `test_legacy_cache_shape_adapter.py` passes.
- [x] `LANGUAGE_CHANGED` reducer preserves card progress (unit test passes).
- [ ] E2E language switch test passes end-to-end.
- [x] Cache log keys match DLD §12.2 metric names: `i18n_session_cache_eviction_total`, `session_cache_truncated` (closeout F6, 2026-04-24).
- [x] `PATCH /students/{id}/language` returns 503 on DB timeout instead of swallowing as 200 (closeout F5, 2026-04-24).
- [x] `translate_catalog._upsert_translations` SQL guarded by `assert col_name in ALLOWED_TRANSLATION_COLS` and `assert lang in LANGUAGE_NAMES` (closeout F4, 2026-04-24).

**Phase 6:**
- [ ] `translate_catalog_inline()` called in `pipeline.py` after Stage 2.
- [ ] Pipeline integration test passes.
- [ ] Idempotency test: re-run = 0 LLM calls.

---

## 5. Rollout Strategy

**Deployment approach:** Standard rolling deploy (no canary, no blue/green required — all changes are additive until Phase 4 deletes the translate-titles endpoint).

**Phase 3 is the highest-risk deploy** (schema migration + one-time backfill on production). Procedure:

1. Deploy backend code for Phase 3 (endpoint changes) to staging; run all integration tests.
2. Run `alembic upgrade head` on **staging** DB. Confirm clean.
3. Deploy backend code to production.
4. Run `alembic upgrade head` on **production** DB. Confirm clean (`alembic current` shows `021_...`).
5. Run backfill on production (see Phase 3 Deployment section above). Monitor logs.
6. Smoke-test via verification runbook (below).
7. Deploy Phase 3 frontend changes (useConceptMap cleanup).

**Phase 4 ships frontend and backend together** — the frontend stops calling the LLM endpoint and the backend stops serving it. Must be deployed atomically (same release window). If frontend deploys first with the endpoint still alive, it simply stops making calls — safe. If backend deploys first and deletes the endpoint before frontend update, the frontend call will 404 — the existing silent catch means the map falls back to English titles temporarily. This is safe for < 1 hour.

**Rollback plan per phase:**

| Phase | Rollback Command |
|-------|-----------------|
| 0 | `git revert <commit>` — no DB change |
| 1 | `git revert <commit>` — no DB change |
| 2 | `git revert <commit>` — no DB change |
| 3 (code only) | `git revert <commit>` — re-deploy |
| 3 (migration) | `alembic downgrade -1` then `git revert <commit>` |
| 4 | `git revert <commit>` — restore translation cache JSON from backup; re-deploy |
| 5 | `git revert <commit>` — no DB change |
| 6 | `git revert <commit>` — no DB change; pipeline runs without Stage 3 |

---

## 6. Verification Runbook — 11-Step Manual Smoke Test

Run this on staging after Phase 3+4 deploy, and again after Phase 5.

**Setup:** A test student account with `preferred_language = "en"` and at least one completed Business Statistics session. Browser DevTools Network tab open.

| Step | Action | Pass Criteria | Fail Criteria |
|------|--------|---------------|---------------|
| 1 | Log in; navigate to Dashboard | Dashboard loads with English book and session titles | Any visible error; titles show as slugs |
| 2 | On Dashboard, click `<LanguageSelector>`, select Malayalam (മലയാളം) | Overlay appears with native language name "Malayalam" or "മലയാളം"; Network shows `PATCH /students/{id}/language` completing in < 2 s | Overlay never shows; API call takes > 5 s; language toggle fails |
| 3 | After overlay closes: inspect Dashboard book cards | Business Statistics book title is in Malayalam | Book title remains in English |
| 4 | Inspect Recent Activity section | Session rows show `concept_title` in Malayalam | Session titles show as "Section 1.1" or raw concept IDs |
| 5 | Navigate to Concept Map for Business Statistics | Chapter/section node titles displayed in Malayalam | All nodes in English; loading spinner stuck |
| 6 | Navigate back to Dashboard; open a new lesson | Cards load; lesson content in Malayalam | Cards in English; 500 error on card generation |
| 7 | Navigate to Settings; check LanguageSelector | Settings shows Malayalam selected | Settings shows English |
| 8 | In Settings, switch back to English | Overlay shows; Dashboard and map return to English after navigation | English switch fails; content mixed |
| 9 | Navigate to a lesson route (`/learn/...`) | No `<LanguageSelector>` visible anywhere in the page DOM (verify via DevTools Elements) | Language selector visible in lesson header or sidebar |
| 10 | Navigate to Prealgebra concept map with browser `Accept-Language: ml` (set in DevTools) | Map loads with English node titles (no translation available); no empty strings; no errors | Empty node titles; 500 error; crash |
| 11 | In DevTools Network, filter for `translate-titles` | Zero calls to `POST /api/v2/concepts/translate-titles` during the entire session | Any call to that endpoint |

---

## 7. Risk Register

The following table is copied from the plan document and adapted for this execution-plan context.

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| OpenAI outage during Business Statistics backfill | Low | Medium | Per-language failures logged; English fallback covers gap; operator re-runs `--languages <failed>` |
| `alembic upgrade head` fails on production (locks or errors) | Low | High | Run in off-peak hours; have `alembic downgrade -1` ready; test on staging first |
| `presentation_text` row exceeds 512 KB in production | Low | Low | LRU eviction enforced by `CacheAccessor`; telemetry alert at 450 KB |
| Business Statistics `heading_translations` empty when Phase 4 deploys | Medium | Medium | Phase 3 deployment checklist includes backfill verification before tagging Phase 4 ready |
| Legacy flat `presentation_text` shape not handled | Medium | High | `CacheAccessor` legacy-shape adapter tested by `test_legacy_cache_shape_adapter.py` before Phase 5 merges |
| Frontend calls `translateConceptTitles` after endpoint is deleted (Phase 4 race) | Low | Low | Silent 404 catch in `useConceptMap.js` means English fallback; no user-visible error; window < 1 hour |
| Locale key gaps introduced by future developers | Medium | Low | CI `lint:locales` check blocks merge permanently after Phase 1 |
| Student mid-session on EN switches to ML via browser back-button to Dashboard | Low | Low | UI enforces: no selector on lesson routes; back-navigation does not reset language |
| Performance regression on `GET /students/{id}/sessions` (LATERAL join) | Low | Medium | LATERAL join uses `ix_concept_chunks_book_concept_order` index; explain-analyze confirms < 10 ms on 50 rows |
| `en_source_hash` collision (SHA-1) | Very Low | Negligible | SHA-1 collision probability negligible for < 1 M short strings; mitigable by switching to SHA-256 inside JSONB without schema change |

---

## 8. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| 0 — Housekeeping | CLAUDE.md + `dependencies.py` + unit tests | 1.0d | backend-developer (0.6d), comprehensive-tester (0.5d) |
| 1 — Locale Gaps | 33-key backfill + CI check | 1.8d | frontend-developer (1.5d), devops-engineer (0.2d) |
| 2 — Frontend Re-fetch | Dep arrays + formatConceptTitle + AppShell | 1.3d | frontend-developer (1.0d), comprehensive-tester (0.4d) |
| 3 — DB + Endpoints | Migration + backfill script + 3 endpoints + tests | 5.0d | backend-developer (3.3d), devops-engineer (0.7d), comprehensive-tester (1.0d) |
| 4 — Delete LLM Path | Language endpoint rewrite + endpoint delete + frontend cleanup | 3.0d | backend-developer (1.5d), frontend-developer (0.7d), comprehensive-tester (0.8d) |
| 5 — Per-language Cache | CacheAccessor + teaching service wiring + reducer fix + tests | 3.5d | backend-developer (2.3d), frontend-developer (0.2d), comprehensive-tester (1.5d) |
| 6 — Pipeline Hook | translate_catalog_for_book extraction + pipeline Stage 3 | 1.5d | backend-developer (1.0d), comprehensive-tester (0.5d) |
| **Total** | | **~17d** | backend-developer (~9d), frontend-developer (~3d), comprehensive-tester (~5d), devops-engineer (~1d) |

With Phases 0, 1, and 2 running in parallel starting Day 1, and Phase 5 and 6 running in parallel starting after Phase 4:
**Estimated calendar duration: 9–10 working days** with three agents working in parallel.

---

## Key Decisions Requiring Stakeholder Input

1. **Phase 3 deployment window** — the `alembic upgrade head` + one-shot backfill should run during a low-traffic window (< 100 concurrent users). Confirm the acceptable window (e.g., weekday night UTC).
2. **Phase 4 atomic deployment** — frontend and backend must ship together. Confirm the CI/CD pipeline supports same-window deploys for both services, or accept the < 1-hour English-fallback window if they ship sequentially.
3. **`presentation_text` cleanup cron ownership** — proposed daily cron (completed sessions: purge `presentation_text` after 7 days). Confirm devops-engineer agent should author this as a separate Celery task or a separate cron-job PR within Phase 5 scope.
