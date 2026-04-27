# Deploy Steps

Run these on the server after `git pull`.

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

## 3. One-time cache bust (recommended)

Sessions started before this deploy may have English content cached from the pre-fix per-card generator. Run once after deploy to clear them — student's next chunk-fetch then regenerates in their language:

```bash
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c \
  "UPDATE teaching_sessions SET presentation_text=NULL WHERE completed_at IS NULL;"
```

This is **safe**: the next API request from each affected student will lazily regenerate their cards with the new (correct-language) prompt.

## 3b. One-time stale-mastery cleanup (REQUIRED for mastery-rebuild release)

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

## 4. Smoke test

Open the app in a browser, log in, switch language to Malayalam, navigate to Settings:

- Sidebar "Settings" item → should display `ക്രമീകരണങ്ങൾ`.
- Profile / Account / Help & Support / Interests & Tutor Style headers → all in Malayalam.
- Tutor style names and preset interest names → all in Malayalam.

If any of the above shows English: hard-refresh (Cmd+Shift+R / Ctrl+F5) to bypass browser cache. If it persists after a hard refresh against a freshly-built `dist/`, file an issue.

## What's in this release

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
