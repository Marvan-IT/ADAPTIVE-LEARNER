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

## 4. Smoke test

Open the app in a browser, log in, switch language to Malayalam, navigate to Settings:

- Sidebar "Settings" item → should display `ക്രമീകരണങ്ങൾ`.
- Profile / Account / Help & Support / Interests & Tutor Style headers → all in Malayalam.
- Tutor style names and preset interest names → all in Malayalam.

If any of the above shows English: hard-refresh (Cmd+Shift+R / Ctrl+F5) to bypass browser cache. If it persists after a hard refresh against a freshly-built `dist/`, file an issue.

## What's in this release

- Backend: per-card LLM prompts now include the strong language directive across all 6 student-facing paths (per-card, recovery, remediation, exam questions, MCQ regen, adaptive engine).
- Backend: cache invalidation hooks on every admin content-edit handler + undo/redo paths. Students see admin edits on their next card fetch in their own language.
- Backend: pipeline Stage 7 auto-translates new books into all 13 languages at ingestion time. No manual `translate_catalog.py` runs needed.
- Backend: admin section-rename now translates the new name to all 12 non-English languages and stores in `admin_section_name_translations` JSONB column.
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
