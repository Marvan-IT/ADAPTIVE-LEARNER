# Deploy Steps

Run these on the server after `git pull`.

> **Convention:** sections labelled **ONE-TIME** are tied to a specific release and should be **deleted (or moved to `docs/<release>-deploy.md`) once that release is fully deployed and verified**. Permanent steps live in sections 1, 2, and 4.

## 1. Backend

```bash
cd backend
source ../.venv/bin/activate

# Apply migrations (idempotent — no-op if already at head 022)
alembic upgrade head

# Restart backend (replace with your supervisor command)
# - systemd: sudo systemctl restart ada-backend
# - pm2:     pm2 restart ada-backend
# - docker:  docker compose restart backend
```

## 2. Frontend

```bash
cd ../frontend
npm ci
npm run build

# Restart static-asset server / point CDN at the new dist/
# - nginx:   sudo systemctl reload nginx
# - vercel:  vercel --prod
```

## 3. ONE-TIME — Round 4 cache bust (recommended; delete after deploy)

Sessions started before this deploy may have English content cached from the pre-fix per-card generator. Run once after deploy to clear them — student's next chunk-fetch then regenerates in their language:

```bash
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c \
  "UPDATE teaching_sessions SET presentation_text=NULL WHERE completed_at IS NULL;"
```

This is **safe**: the next API request from each affected student will lazily regenerate their cards with the new (correct-language) prompt.

## 3b. ONE-TIME — Round 4 stale-mastery cleanup (REQUIRED; delete after deploy)

Before the mastery rewrite, `complete-chunk` auto-mastered any concept where the student walked through all sub-chunks — regardless of MCQ/exam-gate score. Some students may now show mastered concepts they shouldn't have. Clear those rows so the new flow can re-evaluate them:

```bash
# Drop StudentMastery rows where the corresponding session has no chunk_progress
# entries with passed=True (i.e., auto-mastered with score=0 under the old code).
docker compose exec db psql -U postgres -d AdaptiveLearner -c "
DELETE FROM student_mastery sm
WHERE NOT EXISTS (
  SELECT 1
  FROM teaching_sessions ts,
       jsonb_each(ts.chunk_progress) AS prog(chunk_id, data)
  WHERE ts.id = sm.session_id
    AND (prog.data->>'passed')::boolean = TRUE
);
"
```

Students with cleared rows will need to retry the chunk's exam-gate (or finish its MCQs ≥50% for exam_disabled chunks) to remaster the concept.

## 3c. ONE-TIME — Round 4 two-type chunk_type wipe + re-ingest (delete after deploy)

This section is **required** when deploying the Round 4 commit that collapses `chunk_type` to
the two-canonical-value alphabet (`teaching`, `exercise`). The prealgebra_2e book must be wiped
and re-ingested so the DB contains no legacy `chapter_intro`, `chapter_review`, or `lab` rows.
No Alembic migration is needed — the `chunk_type` column already tolerates the smaller alphabet.

### Pre-deploy: wipe prealgebra_2e

Run on the server after `git pull` and before restarting the backend. Order matters:
`student_mastery.session_id` does not cascade, so its rows must be deleted before the
referenced teaching_sessions rows. Other FKs (conversation_messages, card_interactions,
chunks-via-concepts) cascade automatically.

```bash
docker compose exec db psql -U postgres -d AdaptiveLearner -c "
DELETE FROM student_mastery WHERE session_id IN (SELECT id FROM teaching_sessions WHERE book_slug='prealgebra_2e');
DELETE FROM student_mastery WHERE concept_id LIKE 'prealgebra_2e%';
DELETE FROM teaching_sessions WHERE book_slug='prealgebra_2e';
DELETE FROM concept_chunks WHERE book_slug='prealgebra_2e';
DELETE FROM concepts WHERE book_slug='prealgebra_2e';
DELETE FROM books WHERE slug='prealgebra_2e';
"
```

### Re-ingest

Stage 7 auto-translates into all 13 languages. **The pipeline takes the BOOK CODE
(registry key in `backend/src/config.py:BOOK_REGISTRY`), not the slug used in DB columns.**
For prealgebra_2e the code is `PREALG2E` (slug stored in `book_slug` column is `prealgebra_2e`).

```bash
docker compose exec backend python -m src.pipeline --book PREALG2E
```

### Restart

```bash
docker compose restart backend
```

### Verification SQL

Must return **exactly 2 rows** — one for `teaching`, one for `exercise`. Any other value means a
legacy type survived ingest and the pipeline fix was not applied:

```bash
docker compose exec db psql -U postgres -d AdaptiveLearner -c "
SELECT chunk_type, COUNT(*) FROM concept_chunks WHERE book_slug='prealgebra_2e' GROUP BY chunk_type;
"
```

### Smoke test (manual)

1. Log in as a Malayalam student.
2. Pick prealgebra_2e and navigate to any concept.
3. Walk through a **teaching** chunk: after all cards, exam-gate questions should appear.
4. Pass the exam → chunk `passed=True` → concept shows `MASTERED` + 50 XP with `score=<int>` (not `score=None`).
5. Fail the exam → chunk stays `passed=False` → no mastery granted.

### Rollback

No Alembic migration was added for Round 4 — rollback is a code revert followed by re-ingest:

```bash
git revert <round-4-commit>
git push
# SSH to server:
#   git pull
#   docker compose restart backend
# Re-run the pre-deploy wipe SQL above (clears any partially-ingested data)
# Re-run the re-ingest command to restore the book under the reverted pipeline
```

## 4. Smoke test

Open the app in a browser, log in, switch language to Malayalam, navigate to Settings:

- Sidebar "Settings" item → should display `ക്രമീകരണങ്ങൾ`.
- Profile / Account / Help & Support / Interests & Tutor Style headers → all in Malayalam.
- Tutor style names and preset interest names → all in Malayalam.

If any of the above shows English: hard-refresh (Cmd+Shift+R / Ctrl+F5) to bypass browser cache. If it persists after a hard refresh against a freshly-built `dist/`, file an issue.

## What's in this release

- Backend: chunk_type alphabet collapsed to two canonical types (teaching, exercise). Pipeline emits only those two; admin endpoint validates; mastery rule simplified to two-branch.
- Backend: mastery flow rebuilt. `complete-chunk` no longer auto-masters; mastery requires every required (non-hidden, non-optional) chunk to have `passed=True` in `chunk_progress`. For exam_disabled or exercise chunks, pass = card MCQ score ≥ 50%. For exam-enabled teaching chunks, pass = exam-gate evaluate ≥ 50%. Single helper `_check_concept_mastered` is the only path to `StudentMastery` insert + `award_mastery_xp`; uses `_mastery_awarded` sentinel in JSONB for idempotency.
- Backend: per-card LLM upgraded from `gpt-4o-mini` to `gpt-4o` for higher language fidelity (fixes English titles for non-English students).
- Backend: image URLs in LLM-generated `card.content` post-processed via `_rewrite_image_urls` so inline Markdown images resolve to `/images/<book>/mathpix_extracted/<file>` and get served by nginx + backend mount.
- Backend: per-card LLM prompts now include the strong language directive across all 6 student-facing paths.
- Backend: cache invalidation hooks on every admin content-edit handler + undo/redo paths.
- Backend: pipeline Stage 7 auto-translates new books into all 13 languages.
- Backend: admin section-rename auto-translates into 12 non-English languages.
- Frontend: `adaptiveCardLoading` now cleared on terminal reducer cases (`CHUNK_COMPLETED`, `SHOW_CHUNK_QUESTIONS`, `RETURN_TO_PICKER`). Fixes stuck "preparing your lesson cards" skeleton after chunk completion.
- Frontend: recovery-card double-wrong on the last card no longer leaves the student stuck — routes to exam gate or chunk completion.
- Frontend: every `<ReactMarkdown>` instance now uses a custom `img` component that runs URLs through `resolveImageUrl()`, defending against any URL format the LLM produces.
- Frontend: `useConceptMap` and `concepts.js` no longer accept null book_slug (legacy default removed; throws explicitly).
- Frontend: AdminBookContentPage + AdminReviewPage popups translatable via `dialog.prompt()`.
- Frontend: tutor styles + interests render translated labels.
- Locale files: 0 missing keys across all 13.
- Migration 022: adds `concept_chunks.admin_section_name_translations`.

## Rollback

```bash
# Backend
cd backend && alembic downgrade -1   # drops admin_section_name_translations column
git revert <merge-commit>
# Restart backend

# Frontend
git revert <merge-commit>
npm ci && npm run build
# Restart frontend
```

The rollback is safe: the new column is dropped cleanly; code paths fall back to the previous behaviour (English-only admin renames). Cached student card content stays valid.
