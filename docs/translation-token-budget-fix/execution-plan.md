# Execution Plan — Translation Token Budget Fix

## Phase 0 — Design (solution-architect) [COMPLETE]

**Deliverables:** `docs/translation-token-budget-fix/{HLD.md, DLD.md, execution-plan.md}`
**Estimated time:** ~5 min

**Acceptance criteria:**
- All three docs written to disk.
- Root cause, one-line patch, token math, and rollback documented.

---

## Phase 1 — Code Change (backend-developer)

**Estimated time:** < 1 min

**Task P1-1:** Edit `backend/scripts/translate_catalog.py` line 123.

```python
# Change
max_tokens=max(512, len(strings) * 60),
# To
max_tokens=max(512, len(strings) * 200),
```

Add the four-line comment block above the changed line (see DLD.md section 2 for exact text).

**Acceptance criteria:**
- `git diff` shows exactly one changed line in `translate_catalog.py`.
- No other files modified.
- `python -c "import backend.scripts.translate_catalog"` exits 0 (module syntax clean).

---

## Phase 2 — Test (comprehensive-tester)

**Estimated time:** ~2 min

**Task P2-1 — Import smoke test:**
```bash
cd backend && source ../.venv/bin/activate
python3 -c "from scripts import translate_catalog as tc; print(tc.BATCH_SIZE_PER_CALL)"
# Must exit 0
```

**Task P2-2 — Live LLM regression test:**
Write a short inline script that calls `_translate_batch_with_retry` with 5 synthetic Hindi captions
(50+ words each) and asserts `len(result) == 5` and no `fallback` path is triggered.
Cost: < $0.01.

**Task P2-3 — Pytest suite:**
```bash
python -m pytest tests/ -q
# Must pass — no regressions in any test importing translate_catalog
```

**Acceptance criteria:**
- All three checks pass.
- No `Unterminated string` errors in LLM test output.
- `fallbacks=0` observed in test run log.

---

## Phase 3 — Deploy (devops-engineer)

**Estimated time:** ~3 min deploy + 30–60 min for both books to finish translating

**Task P3-1 — Pull and rebuild:**
```bash
git pull
docker compose build backend
docker compose up -d backend
```

**Deploy side-effect — expected and safe:**
The restart kills the running `pipeline_runner` processes for `clinical_nursing_skills` and
`introduction_to_philosophy`. The watcher detects the existing PDF placeholders and book.mmd
cache files, then fires fresh `pipeline_runner` instances for each book. The resumed runs:

- **Skip Mathpix** — `book.mmd` cache is present for all 5 books. Confirmed across 4 prior restart events today. Verification: `grep -c "Submitting PDF to Mathpix" pipeline.log` must return 0.
- **Skip already-saved chunks** — chunk_builder runs with `rebuild=False`.
- **Apply SHA-1 idempotency** — `translate_catalog` skips rows with an existing translation hash. Only untranslated rows fetch new completions.
- **Run remaining translations at full batch speed** — the new 200-token multiplier is now in effect for all remaining batches.

**Task P3-2 — Monitor Mathpix safety:**
```bash
docker compose exec backend grep -c "Submitting PDF to Mathpix" \
  /app/output/clinical_nursing_skills/pipeline.log \
  /app/output/introduction_to_philosophy/pipeline.log
# Both must return 0
```

**Task P3-3 — Monitor translation pace:**
```bash
docker compose exec backend bash -c \
  'tail -f /app/output/clinical_nursing_skills/pipeline.log | grep "done in"'
# Each language: "done in Xs, fallbacks=0" — expect 3–7 min per language
# (was 50–80 min with fallbacks=465)
```

**Task P3-4 — Confirm pipeline completion:**
```bash
docker compose exec backend grep -E "Pipeline complete|Translated.*languages" \
  /app/output/clinical_nursing_skills/pipeline.log \
  /app/output/introduction_to_philosophy/pipeline.log
```

**Task P3-5 — Publish books:**
```sql
UPDATE books SET status='PUBLISHED', published_at=NOW()
WHERE book_slug IN ('clinical_nursing_skills', 'introduction_to_philosophy');
```

Note: a second backend restart is NOT needed — the post-Stage-6 hot-load mounts `/images/<slug>`
automatically once status is PUBLISHED.

**Acceptance criteria (Phase 3):**
- `grep -c "Submitting PDF to Mathpix"` returns 0 for both books.
- Both pipeline logs show `Pipeline complete` with `Translated N rows across 12 languages`.
- `fallbacks=0` in all per-language summary lines.
- Both books visible and accessible in the frontend after `UPDATE`.

---

## Dependencies and Critical Path

```
P0 (docs) → P1 (code) → P2 (tests) → P3 (deploy + monitor)
```

All phases are strictly sequential. No external team dependencies.
Blocking risk: if watcher fails to auto-restart a book, manual invocation:
```bash
docker compose exec backend python -m src.watcher.pipeline_runner \
  --pdf <path> --subject <subject> --slug <slug>
```

---

## Rollback Plan

Revert line 123 of `backend/scripts/translate_catalog.py` to:
```python
max_tokens=max(512, len(strings) * 60),
```
Rebuild and redeploy. No database changes to undo.

---

## Effort Summary

| Phase | Key Task | Estimated Time | Owner |
|-------|----------|---------------|-------|
| 0 | Write design docs | ~5 min | solution-architect |
| 1 | One-line code edit + comment | < 1 min | backend-developer |
| 2 | Smoke test + live LLM test + pytest | ~2 min | comprehensive-tester |
| 3 | Deploy + monitor both books to PUBLISHED | ~30–60 min | devops-engineer |

**Total wall-clock time to all 5 books PUBLISHED: ~45 min from Phase 1 start.**

---

## Key Decisions Requiring Stakeholder Input

None. All decisions are technical, reversible, and bounded to a single constant change.
