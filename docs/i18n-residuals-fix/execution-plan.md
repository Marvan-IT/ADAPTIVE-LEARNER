# Execution Plan — i18n Residuals Fix

**Feature slug:** `i18n-residuals-fix`
**Date:** 2026-04-24
**Status:** Approved — Phase 0 design

---

## 1. Work Breakdown Structure (WBS)

| ID | Title | Description | Est. LOC | Dependencies | Component | Agent |
|----|-------|-------------|----------|-------------|-----------|-------|
| P1-01 | Add `admin_section_name_translations` to ORM model | Add mapped column to `ConceptChunk` in `db/models.py` following `heading_translations` pattern | ~3 | none | ORM | backend-developer |
| P1-02 | Create `translation_helper.py` | New module with `translate_one_string()`, retry logic, concurrent `asyncio.gather` across 12 langs | ~100 | P1-01 | Helper | backend-developer |
| P1-03 | Hook translation into `rename_section` handler | Insert translation call + second UPDATE + audit payload extension in `admin_router.py` | ~35 | P1-02 | Handler | backend-developer |
| P1-04 | Fix display-path fallback in `teaching_router.py` | Replace hardcoded `{}` with `admin_section_name_translations or {}` in `resolve_translation` call | ~8 | P1-01 | Router | backend-developer |
| P1-05 | Extend `snapshot_section` in `audit_service.py` | Add `admin_section_name_translations` field to snapshot dict | ~3 | P1-01 | Audit | backend-developer |
| P1-06 | Extend `_undo_rename_section` in `audit_service.py` | Restore `admin_section_name_translations` alongside `admin_section_name` | ~3 | P1-05 | Audit | backend-developer |
| P1-07 | Extend `apply_redo` rename branch in `audit_service.py` | Restore translations on redo | ~3 | P1-06 | Audit | backend-developer |
| P2-01 | Write Alembic migration `022_add_admin_section_name_translations.py` | `op.add_column` + `downgrade` drop, mirroring migration 021 | ~40 | P1-01 | Migration | devops-engineer |
| P2-02 | Apply migration + verify | `alembic upgrade head`; confirm column in `\d concept_chunks` | n/a | P2-01 | DB | devops-engineer |
| P3-01 | Write `test_admin_rename_translation.py` | 5 test classes: normal rename, translation failure mode, undo restoration, student-view language resolution, audit payload shape | ~180 | P1-03, P1-04, P1-06 | Tests | comprehensive-tester |
| P3-02 | Extend `test_admin_audit.py` rename tests | Assert snapshot includes `admin_section_name_translations`; assert undo restores both columns | ~40 | P1-05, P1-06 | Tests | comprehensive-tester |
| P4-01 | Import `useDialog` in `AdminReviewPage.jsx` | Add import + `const dialog = useDialog()` instantiation | ~3 | none | Frontend | frontend-developer |
| P4-02 | Replace `window.prompt` at line 387 | `handleRenameChunkHeading` — swap to `dialog.prompt()` with `adminReview.promptNewHeading` | ~5 | P4-01, P4-05 | Frontend | frontend-developer |
| P4-03 | Replace `window.prompt` at line 465 | `handlePromoteToSection` — swap to `dialog.prompt()` with `adminReview.promptPromoteLabel` | ~6 | P4-01, P4-05 | Frontend | frontend-developer |
| P4-04 | Replace `window.prompt` at line 501 | `handleRenameSection` — swap to `dialog.prompt()` with `adminReview.promptNewSectionName` | ~5 | P4-01, P4-05 | Frontend | frontend-developer |
| P4-05 | Add 3 keys to `en.json` | Add `adminReview.promptNewHeading`, `adminReview.promptPromoteLabel`, `adminReview.promptNewSectionName` | ~7 | none | Locale | frontend-developer |
| P4-06 | Populate 12 non-English locale files | Run `frontend/scripts/translate_locales.py`; verify keys present in all 12 files | ~0 dev, ~2s script | P4-05 | Locale | frontend-developer |

---

## 2. Phased Delivery Plan

### Phase 1 — Backend (backend-developer)

**Goal:** All Python changes in place, testable without migration (SQLAlchemy model updated, migration will follow in Phase 2).

**Tasks:** P1-01 through P1-07 (can be done in a single PR; tasks are sequential within the phase).

**File changes:**

| File | Change type |
|------|------------|
| `backend/src/db/models.py` | Add `admin_section_name_translations` column |
| `backend/src/api/translation_helper.py` | NEW FILE |
| `backend/src/api/admin_router.py` | Insert ~35 lines in `rename_section` handler |
| `backend/src/api/teaching_router.py` | Replace `{}` with translation lookup (~8 lines) |
| `backend/src/api/audit_service.py` | Extend `snapshot_section`, `_undo_rename_section`, `apply_redo` |

**Acceptance:**
- `translation_helper.py` imports cleanly from within the FastAPI process: `from api.translation_helper import translate_one_string`.
- `rename_section` handler returns 200 with `chunks_updated > 0` when called against a dev DB with the migration applied.
- `teaching_router.py` uses the correct fallback: verified by reading the code diff.
- `audit_service.py` snapshot dict includes `admin_section_name_translations` key.
- `_undo_rename_section` sets `chunk.admin_section_name_translations`.

**Rollback plan:** Revert the PR. The migration in Phase 2 must be separately downgraded (`alembic downgrade -1`). If Phase 2 migration was not yet applied, no DB state to roll back.

**PR description draft:**
> Backend: wire admin_section_name_translations for section rename i18n
>
> - Adds `admin_section_name_translations` JSONB column to ConceptChunk ORM model.
> - New `translation_helper.py` with `translate_one_string()` (12-language concurrent OpenAI).
> - `rename_section` handler: await translation after name UPDATE, store to DB, extend audit payload.
> - `teaching_router`: fix display-path to use new column instead of hardcoded `{}`.
> - `audit_service`: snapshot, undo, and redo all cover `admin_section_name_translations`.
>
> Requires Phase 2 migration before deploying to staging/prod.

---

### Phase 2 — Migration (devops-engineer)

**Goal:** Add `admin_section_name_translations` JSONB column to `concept_chunks` in PostgreSQL.

**Tasks:** P2-01, P2-02.

**File changes:**

| File | Change type |
|------|------------|
| `backend/alembic/versions/022_add_admin_section_name_translations.py` | NEW FILE |

**Exact verification steps:**
```bash
cd backend
source ../.venv/bin/activate
alembic upgrade head
# Expected: "Running upgrade 021_add_i18n_translation_columns -> 022_add_admin_section_name_translations"
psql $DATABASE_URL -c "\d concept_chunks" | grep admin_section_name_translations
# Expected: "admin_section_name_translations | jsonb | not null | default '{}'::jsonb"
```

**Acceptance:**
- `alembic upgrade head` exits 0.
- Column exists in `concept_chunks` with correct type and default.
- `alembic downgrade -1` drops the column cleanly (verified in dev).

**Rollback plan:**
```bash
alembic downgrade -1
# Drops admin_section_name_translations column
# Code in Phase 1 PR must also be reverted — the column reference in models.py
# will cause SQLAlchemy errors if migration is rolled back but code is not.
```

**PR description draft:**
> Alembic 022: add admin_section_name_translations JSONB to concept_chunks
>
> NOT NULL DEFAULT '{}'::jsonb — no backfill needed, English fallback operates
> from empty dict. Mirrors pattern of migration 021. Downgrade drops the column.

---

### Phase 3 — Tests (comprehensive-tester)

**Goal:** Automated coverage for the backend changes; extend existing audit tests.

**Tasks:** P3-01, P3-02.

**File changes:**

| File | Change type |
|------|------------|
| `backend/tests/test_admin_rename_translation.py` | NEW FILE |
| `backend/tests/test_admin_audit.py` | EXTEND |

**`test_admin_rename_translation.py` structure:**

```python
# Pseudocode — actual implementation by comprehensive-tester

class TestRenameTranslationPopulates:
    """Normal path: mock translate_one_string returns fixture dict."""
    async def test_rename_populates_translations(self, ...):
        # POST rename → assert admin_section_name_translations has 12 keys

    async def test_rename_returns_200(self, ...):
        # POST rename → HTTP 200, chunks_updated > 0

class TestRenameTranslationFailureMode:
    """Failure path: mock translate_one_string raises."""
    async def test_rename_succeeds_when_translation_fails(self, ...):
        # POST rename → 200, admin_section_name_translations stays {}

class TestStudentSeesTranslatedSectionTitle:
    """Display path: GET /chunks returns translated section_title."""
    async def test_ml_student_sees_translated_title(self, ...):
        # seed chunk with admin_section_name + admin_section_name_translations
        # GET chunks as ml student → section_title == translations["ml"]

    async def test_en_student_sees_english_title(self, ...):
        # GET chunks as en student → section_title == admin_section_name (English)

class TestUndoRestoresBothColumns:
    """Undo path: both admin_section_name and translations restored."""
    async def test_undo_restores_admin_section_name(self, ...):
        # POST rename → POST undo → assert admin_section_name == old
    async def test_undo_restores_translations(self, ...):
        # POST rename → POST undo → assert admin_section_name_translations == old_trans

class TestAuditPayloadShape:
    """Audit record: both fields present in old_value and new_value."""
    async def test_audit_old_value_includes_translations(self, ...):
        # POST rename → fetch audit row → old_value has admin_section_name_translations key
    async def test_audit_new_value_includes_translations(self, ...):
        # POST rename → fetch audit row → new_value has admin_section_name_translations key
```

**`test_admin_audit.py` extensions:**

Add to the existing `rename_section` test class:
- Assert `snapshot_section` returns dict with `admin_section_name_translations` key.
- Assert undo restores `admin_section_name_translations` to its pre-rename value.

**Mock pattern:**
```python
# Use pytest monkeypatch or unittest.mock.patch
from unittest.mock import AsyncMock, patch

FIXTURE_TRANSLATIONS = {
    "en_source_hash": "abc123",
    "ml": "പ്രോബബിലിറ്റി",
    "ta": "நிகழ்தகவு",
    # ... all 12 langs
}

@patch("api.admin_router.translate_one_string", new_callable=AsyncMock)
async def test_rename_populates_translations(mock_translate, ...):
    mock_translate.return_value = FIXTURE_TRANSLATIONS
    ...
```

**Run command:**
```bash
cd backend && source ../.venv/bin/activate
python -m pytest tests/test_admin_rename_translation.py tests/test_admin_audit.py -q
```

**Acceptance:**
- All new tests pass.
- No existing tests broken.
- Failure-mode test confirms rename returns 200 when `translate_one_string` raises.

**Rollback plan:** Tests are additive — deleting the new test file reverts to prior coverage.

---

### Phase 4 — Frontend (frontend-developer)

**Goal:** Replace 3 native `window.prompt` calls; add 3 locale keys to all 13 locale files.

**Tasks:** P4-01 through P4-06. Tasks P4-05 must be done before P4-02/P4-03/P4-04.

**File changes:**

| File | Change type | Lines changed |
|------|------------|--------------|
| `frontend/src/pages/AdminReviewPage.jsx` | Modify (3 sites + 1 import + 1 hook) | ~25 |
| `frontend/src/locales/en.json` | Add 3 keys | ~7 |
| `frontend/src/locales/ar.json` | Add 3 keys (via script) | ~7 |
| `frontend/src/locales/de.json` | Add 3 keys (via script) | ~7 |
| `frontend/src/locales/es.json` | Add 3 keys (via script) | ~7 |
| `frontend/src/locales/fr.json` | Add 3 keys (via script) | ~7 |
| `frontend/src/locales/hi.json` | Add 3 keys (via script) | ~7 |
| `frontend/src/locales/ja.json` | Add 3 keys (via script) | ~7 |
| `frontend/src/locales/ko.json` | Add 3 keys (via script) | ~7 |
| `frontend/src/locales/ml.json` | Add 3 keys (via script) | ~7 |
| `frontend/src/locales/pt.json` | Add 3 keys (via script) | ~7 |
| `frontend/src/locales/si.json` | Add 3 keys (via script) | ~7 |
| `frontend/src/locales/ta.json` | Add 3 keys (via script) | ~7 |
| `frontend/src/locales/zh.json` | Add 3 keys (via script) | ~7 |

**Acceptance:**
- `npm run lint` exits 0.
- `npm run build` exits 0.
- All 13 locale files contain `adminReview.promptNewHeading`, `adminReview.promptPromoteLabel`, `adminReview.promptNewSectionName`.
- Manual smoke test: open AdminReviewPage in Malayalam locale → all 3 dialogs show Malayalam text.
- No `window.prompt` calls remain in `AdminReviewPage.jsx`: `grep -n "window.prompt" frontend/src/pages/AdminReviewPage.jsx` returns empty.

**Rollback plan:** Revert the PR. Locale keys are additive and safe to remove. The `window.prompt` revert restores original behaviour.

**PR description draft:**
> Frontend: replace AdminReviewPage window.prompt with useDialog + 13-locale keys
>
> - Import useDialog and instantiate dialog in AdminReviewPage.jsx.
> - Replace 3 window.prompt calls (lines 387, 465, 501) with dialog.prompt() using i18n keys.
> - Add adminReview.promptNewHeading, adminReview.promptPromoteLabel,
>   adminReview.promptNewSectionName to en.json and all 12 non-English locales
>   (generated via translate_locales.py).
> - No logic change — only dialog provider and text source changed.

---

## 3. Dependencies and Critical Path

```
P1-01 (ORM model)
  └─► P1-02 (translation_helper)
        └─► P1-03 (rename handler hook)
              └─► P3-01 (tests)
  └─► P1-04 (display path fix)
        └─► P3-01 (tests)
  └─► P1-05 (snapshot extension)
        └─► P1-06 (undo extension)
              └─► P1-07 (redo extension)
                    └─► P3-02 (audit test extension)

P2-01 (migration file)
  └─► P2-02 (alembic upgrade head)   ← BLOCKS staging/prod deploy of P1

P4-05 (en.json keys)
  └─► P4-06 (translate_locales.py)
  └─► P4-02, P4-03, P4-04 (component changes)
        ← P4-01 (useDialog import)

P1-01 BLOCKS P2-01 (devops needs the column name from the model)
P2-02 BLOCKS staging deploy of P1-03, P1-04 (DB column must exist)
```

**Critical path:**
`P1-01 → P1-02 → P1-03 → P2-01 → P2-02 → P3-01 → staging deploy`

**External blockers:**
- Phase 2 (devops-engineer) blocks staging deployment of Phase 1 backend changes.
- No external team dependencies.

---

## 4. Definition of Done

### Phase 1 (Backend)
- [ ] `admin_section_name_translations` column declared in `ConceptChunk` ORM model.
- [ ] `translation_helper.py` exists, imports cleanly, handles failure gracefully.
- [ ] `rename_section` handler: `admin_section_name_translations` populated on success; warning logged on failure; rename still returns 200 on failure.
- [ ] `teaching_router.py`: `section_title` uses `admin_section_name_translations` when `admin_section_name` is set.
- [ ] `audit_service.py`: snapshot, undo, and redo all include `admin_section_name_translations`.
- [ ] Code review approved by a second developer.

### Phase 2 (Migration)
- [ ] `022_add_admin_section_name_translations.py` exists with correct `down_revision`.
- [ ] `alembic upgrade head` runs cleanly in dev (exit 0, no errors).
- [ ] Column confirmed in `\d concept_chunks` output.
- [ ] `alembic downgrade -1` drops the column cleanly (tested in dev).

### Phase 3 (Tests)
- [ ] `test_admin_rename_translation.py`: all 5 test classes pass.
- [ ] `test_admin_audit.py`: extended rename tests pass.
- [ ] Failure-mode test confirms graceful degradation.
- [ ] No existing test regressions: `pytest tests/ -q` all green.

### Phase 4 (Frontend)
- [ ] No `window.prompt` calls remain in `AdminReviewPage.jsx`.
- [ ] `useDialog` imported and instantiated in the component.
- [ ] All 3 locale key values populated in all 13 locale files.
- [ ] `npm run lint` exits 0.
- [ ] `npm run build` exits 0.
- [ ] Manual spot-check: AdminReviewPage in Malayalam shows translated prompts for all 3 actions.

### Overall PR
- [ ] Backend and frontend changes are bundled in one PR (per Decision 1).
- [ ] Migration is a separate PR (devops-engineer workflow).
- [ ] Verification walkthrough from the plan file completed:
  - Admin renames section → `admin_section_name_translations` populated in DB.
  - Malayalam student GET chunk list → `section_title` is Malayalam.
  - Admin undoes rename → both columns restored.
  - `translate_catalog.py` re-run → skips unchanged rows (incremental behaviour intact).
  - AdminReviewPage in Malayalam → all 3 dialogs in Malayalam.

---

## 5. Rollout Strategy

**Deployment order (mandatory):**
1. Deploy Phase 2 migration (`alembic upgrade head`) on staging.
2. Deploy Phase 1 + Phase 3 backend code on staging.
3. Deploy Phase 4 frontend code on staging.
4. Run verification walkthrough (see plan file Section "Verification").
5. Repeat order on production.

**Feature flags:** None required. The new column has a safe default (`{}`). The display-path fix is backwards compatible — existing rows with `{}` continue showing English.

**Canary / blue-green:** Not required for this fix. The change is backwards compatible at the DB and API layer. If the migration fails, the existing code continues to work without the new column (provided the ORM model is not yet deployed).

**Monitoring at launch:**
- Watch backend logs for `[admin] admin_section_name translation failed` warnings on first renames post-deploy.
- Confirm no 500 errors on `PATCH /api/admin/sections/.../rename` or `GET /api/v2/sessions/.../chunks/...`.

**Post-launch validation:**
1. Admin renames one section in production.
2. Check DB: `SELECT admin_section_name_translations FROM concept_chunks WHERE concept_id = 'X' LIMIT 1;` — expect 12-key JSON.
3. Switch student account to Malayalam, fetch chunk list — verify translated `section_title`.
4. Open AdminReviewPage in Malayalam — verify 3 dialogs use translated text.

**Rollback (production emergency):**
1. Revert backend + frontend code deploy.
2. Run `alembic downgrade -1` (drops column — acceptable; data is regeneratable).
3. Students see English section names again (original behaviour).

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated LOC | Estimated Effort | Team Members |
|-------|-----------|--------------|-----------------|--------------|
| Phase 1 — Backend | ORM, translation_helper, rename hook, display fix, audit extension | ~155 | 1.5 days | 1 backend-developer |
| Phase 2 — Migration | Alembic migration file + verify | ~40 | 0.5 days | 1 devops-engineer |
| Phase 3 — Tests | test_admin_rename_translation.py + audit test extension | ~220 | 1.0 day | 1 comprehensive-tester |
| Phase 4 — Frontend | AdminReviewPage 3 swaps + 13 locale files | ~105 | 0.5 days | 1 frontend-developer |
| **Total** | | **~520** | **3.5 dev-days** | **4 agents, ~2 calendar days** |

---

## Key Decisions Requiring Stakeholder Input

1. **Backfill of pre-fix renamed sections:** Sections renamed before this fix ship have empty `admin_section_name_translations`. Non-English students see English for those. Options: (a) accept gap — admin re-saves to trigger translation; (b) one-off backfill script. No code change needed to ship, but product must decide communication to admin team.

2. **Redo path re-translation:** The current design restores `admin_section_name_translations` from the audit record during redo (no new OpenAI call). This is correct if the translation was captured at rename time. Confirm this is the desired behaviour (vs. re-calling OpenAI on redo).

3. **`ALLOWED_TRANSLATION_COLS` in `translate_catalog.py`:** The new column `admin_section_name_translations` is not added to `ALLOWED_TRANSLATION_COLS` in `translate_catalog.py` because `translate_catalog.py` does not currently process `admin_section_name`. If future bulk re-translation is needed (e.g., backfill script), this frozenset must be extended. Flag to the team.
