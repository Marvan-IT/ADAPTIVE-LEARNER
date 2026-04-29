# Adaptive Learner

AI-powered adaptive math tutor. PDF textbooks → pgvector + NetworkX graph → per-card adaptive lessons.
Backend: FastAPI async + SQLAlchemy 2.0 + PostgreSQL/pgvector + NetworkX + OpenAI.
Frontend: React 19 + Vite 7 + Zustand + i18next (13 languages) + Framer Motion + KaTeX.

## Commands

Prefix every shell command with `rtk` (token filter, installed at `~/.local/bin/rtk`).

```bash
# Backend (run from backend/, venv activated: source ../.venv/bin/activate)
python -m uvicorn src.api.main:app --reload --port 8889   # dev server (port 8889 is canonical)
alembic upgrade head                                      # apply migrations
alembic revision --autogenerate -m "msg"                  # new migration
pytest                                                    # tests (pytest.ini sets asyncio_mode=auto)
python -m src.pipeline --book <slug>                      # ingest a textbook

# Frontend (run from frontend/)
npm run dev          # Vite on 5173 (proxy → 8889)
npm run build
npm run lint         # eslint .
npm run test:e2e     # playwright test (Chromium, 1 worker, 60s timeout)
```

Use `python -m uvicorn`, not bare `uvicorn` — bare loses venv deps.

## Conventions

- **Schema changes → Alembic migration.** Never `Base.metadata.create_all()`. Coordinate with devops-engineer agent.
- **Constants in `backend/src/config.py`.** No magic thresholds/paths/model names in business logic. Mastery gate is `CHUNK_EXAM_PASS_RATE = 0.50`; `MASTERY_THRESHOLD = 70` is deprecated — don't reuse it.
- **New API endpoint = Pydantic schema + Axios wrapper in `frontend/src/api/` + test.** No direct `fetch`/axios in components.
- **All user-visible strings go through `useTranslation()` and must be added to all 13 locale files** under `frontend/src/locales/` (en, ar, de, es, fr, hi, ja, ko, ml, pt, si, ta, zh). A missing key breaks that language's UI.
- **Styling is inline `style={{}}` objects.** Tailwind classes are utility-only (spacing, layout). Design tokens live in `frontend/src/theme/themes.js`.
- **Cross-route state lives in a Context (`src/context/`) or the Zustand `adaptiveStore`.** Don't prop-drill beyond 2 levels.
- **Markdown rendering always uses `skipHtml={true}`** (XSS hardening; don't remove it).
- Backend logs via Python `logging`; frontend logs via `console.error`. No `print()` / `console.log` debug residue.

## Gotchas

- Port **8889** is the backend's canonical port. `vite.config.js` proxy and `FRONTEND_URL` env var both depend on it — don't change without updating both.
- LLM output can return invalid JSON (LaTeX `\ldots` etc.). Card parsing uses `json-repair` as fallback — preserve it.
- Per-card cards have a `cache_version` check in `teaching_service.py`. Bump the version whenever you change card-generation prompts or the schema, or stale cards survive forever.
- Settings (style, interests) are locked at session start. Changing them mid-session returns HTTP 409 — don't loosen this. **Language is the exception**: `PATCH /students/{id}/language` allows mid-session change and swaps the per-language card cache (no lesson corruption).
- `.venv/` is at **project root**, activated as `source ../.venv/bin/activate` from `backend/` (on macOS/Linux; `../.venv/Scripts/activate` on Windows).

## Workflows

**Sub-agent memory may be stale.** `.claude/agent-memory/` files predate recent work and are not auto-synced. When invoking any sub-agent for non-trivial work, remind it to verify memory claims against current code before acting (the memory hygiene protocol at the top of each MEMORY.md spells this out).

**New feature (non-trivial):** Use plan mode → launch `solution-architect` agent to produce `docs/{feature-slug}/{HLD.md,DLD.md,execution-plan.md}` → then `backend-developer` → `comprehensive-tester` → `frontend-developer`. These design docs are the source of truth — update them before code.

**Schema change:** Edit `backend/src/db/models.py`, then invoke `devops-engineer` agent to write the Alembic migration. Run `alembic upgrade head`. Never skip this for dev convenience.

**Architecture / cross-module questions:** Prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse extracted + inferred edges. Start with `graphify-out/GRAPH_REPORT.md` for god nodes and community structure. After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
