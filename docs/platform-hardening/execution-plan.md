# Execution Plan: Platform Hardening

**Feature slug:** `platform-hardening`
**Date:** 2026-03-01
**Author:** Solution Architect

---

## Agent Execution Order

```
Stage 0 (devops-engineer)
  └─► Stage 2 (backend-developer)
        └─► Stage 4 (frontend-developer)   [can start Stream 1 frontend after P2 completes]
              └─► Stage 3 (comprehensive-tester)
```

Streams 4 and 5 (query fixes, image pipeline) are pure backend — no frontend dependency.
Stream 1 frontend work (Axios interceptor) can proceed in parallel with Stream 2 backend work once the key contract is agreed.

---

## Phase 0 — Infrastructure (devops-engineer)

All database and infra prerequisites must land before any backend or frontend code is written.

### P0-1 — Alembic migration: `students.xp` + `students.streak`

**Description:** Add `xp INTEGER NOT NULL DEFAULT 0` and `streak INTEGER NOT NULL DEFAULT 0` columns to the `students` table. The `DEFAULT 0` backfills existing rows instantly without a separate UPDATE statement.

**File:** `backend/alembic/versions/{hash}_add_xp_streak_to_students.py`

```python
def upgrade():
    op.add_column('students', sa.Column('xp', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('students', sa.Column('streak', sa.Integer(), nullable=False, server_default='0'))

def downgrade():
    op.drop_column('students', 'streak')
    op.drop_column('students', 'xp')
```

**DoD:** `alembic upgrade head` runs without error on the dev database. `students` table has `xp` and `streak` columns. Existing rows show `0` for both.

**Effort:** 0.5 day
**Depends on:** None

---

### P0-2 — Alembic migration: 3 performance indices

**Description:** Add three indices to eliminate sequential scans on the hottest query paths.

**File:** `backend/alembic/versions/{hash}_add_performance_indices.py`

```python
def upgrade():
    op.create_index('ix_teaching_sessions_student_id',
                    'teaching_sessions', ['student_id'])
    op.create_index('ix_conversation_messages_session_id',
                    'conversation_messages', ['session_id'])
    op.create_index('ix_student_mastery_student_concept',
                    'student_mastery', ['student_id', 'concept_id'])

def downgrade():
    op.drop_index('ix_student_mastery_student_concept', table_name='student_mastery')
    op.drop_index('ix_conversation_messages_session_id', table_name='conversation_messages')
    op.drop_index('ix_teaching_sessions_student_id', table_name='teaching_sessions')
```

**DoD:** All three indices visible in `\d teaching_sessions`, `\d conversation_messages`, `\d student_mastery` via `psql`. `EXPLAIN ANALYZE` on `SELECT * FROM teaching_sessions WHERE student_id = X` shows Index Scan (not Seq Scan).

**Effort:** 0.5 day
**Depends on:** None (parallel with P0-1)

---

### P0-3 — `slowapi` added to `requirements.txt`

**Description:** Add `slowapi>=0.1.9` to `backend/requirements.txt`. Pin to minor version to avoid breaking changes.

**DoD:** `pip install -r requirements.txt` in a clean venv succeeds. `import slowapi` works in Python REPL.

**Effort:** 0.25 day
**Depends on:** None

---

### P0-4 — `.env.example` updates

**Description:** Document the two new required environment variables in `.env.example` files.

`backend/.env.example` — add:
```
API_SECRET_KEY=change-me-before-deploy
IMAGE_BLACK_THRESHOLD=5
```

`frontend/.env.example` — add:
```
VITE_API_SECRET_KEY=change-me-before-deploy
```

**DoD:** Both `.env.example` files contain the new keys with placeholder values. A developer following the README can configure a working environment from the example files alone.

**Effort:** 0.25 day
**Depends on:** None

---

### P0-5 — PostgreSQL `max_connections` confirmation

**Description:** Verify or update the PostgreSQL instance `max_connections` to at least 150 to accommodate `pool_size=20, max_overflow=80` plus headroom for admin connections.

**Action:** Check current value: `SHOW max_connections;` via `psql`. If < 150, update `postgresql.conf` and reload. Document the change in the deployment runbook.

**DoD:** `SHOW max_connections` returns a value >= 150 on the target PostgreSQL instance.

**Effort:** 0.25 day
**Depends on:** None

---

## Phase 2 — Backend Implementation (backend-developer)

### P2-1 — `APIKeyMiddleware` implementation

**Description:** Add a custom `BaseHTTPMiddleware` subclass to `backend/src/api/main.py` that inspects the `X-API-Key` header on every incoming request. Skip the check for paths: `/health`, `/docs`, `/openapi.json`, `/redoc`. Return HTTP 401 `{"detail": "Unauthorized"}` for any other path where the header is absent or does not match `config.API_SECRET_KEY`.

**Key implementation notes:**
- Read `API_SECRET_KEY` from environment in `config.py`; call `sys.exit(1)` with a clear message at startup if it is absent or equals the placeholder `"change-me-before-deploy"`.
- Use `secrets.compare_digest()` for the key comparison to prevent timing-based key enumeration.
- Middleware must be added **before** `slowapi` middleware in the ASGI stack (auth fires first).

```python
# config.py addition
import os, sys, secrets as _secrets
API_SECRET_KEY: str = os.getenv("API_SECRET_KEY", "")
if not API_SECRET_KEY or API_SECRET_KEY == "change-me-before-deploy":
    sys.exit("FATAL: API_SECRET_KEY is not set. Refusing to start.")
```

```python
# main.py — middleware class
SKIP_AUTH_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in SKIP_AUTH_PATHS:
            return await call_next(request)
        key = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(key, config.API_SECRET_KEY):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)
```

**DoD:**
- `curl http://localhost:8000/api/v2/students` without `X-API-Key` returns 401.
- `curl` with correct key returns 200.
- `curl http://localhost:8000/health` without key returns 200.
- `curl http://localhost:8000/docs` without key returns 200.
- Starting the backend without `API_SECRET_KEY` set exits with a clear error message.

**Effort:** 0.5 day
**Depends on:** P0-4

---

### P2-2 — `slowapi` rate limiting

**Description:** Wire `slowapi` into the FastAPI app and apply rate limit decorators to all three tiers of endpoints.

**Implementation notes:**
- Instantiate `Limiter` with `key_func=get_remote_address` in `main.py`.
- Add `SlowAPIMiddleware` to the app — must be added **after** `APIKeyMiddleware` in registration order (middleware stack is LIFO in Starlette, so register slowapi first, then APIKeyMiddleware).
- Add `app.state.limiter = limiter` and register the `_rate_limit_exceeded_handler`.
- Apply `@limiter.limit("10/minute")` decorator to: `get_lesson` (v3), `create_session` (v2), `respond_to_check` (v2), `complete_card` (v2).
- Apply `@limiter.limit("120/minute")` decorator to: `list_students`, `get_student`, `list_concepts`, `get_card_history`.
- Remaining endpoints receive the default `@limiter.limit("60/minute")`.

**Constants to add to `config.py`:**
```python
RATE_LIMIT_DEFAULT    = "60/minute"
RATE_LIMIT_LLM_HEAVY  = "10/minute"
RATE_LIMIT_READ       = "120/minute"
```

**DoD:**
- Sending 11 POST requests to a LLM-heavy endpoint within 60 seconds from the same IP returns 429 on the 11th.
- 429 response includes a `Retry-After` header.
- Read endpoints allow up to 120 requests/minute before throttling.
- Health endpoint is not rate-limited.

**Effort:** 1 day
**Depends on:** P0-3, P2-1

---

### P2-3 — ORM update: `students.xp` + `students.streak`

**Description:** Add `xp` and `streak` columns to the `Student` SQLAlchemy model in `backend/src/db/models.py`.

```python
xp     = Column(Integer, nullable=False, default=0, server_default="0")
streak = Column(Integer, nullable=False, default=0, server_default="0")
```

Update the `StudentResponse` Pydantic schema in the relevant `schemas.py` to include `xp: int` and `streak: int`. Ensure `GET /api/v2/students/{id}` returns these fields.

**DoD:** `GET /api/v2/students/{id}` response body contains `"xp": 0` and `"streak": 0` for an existing student. Pydantic schema validation passes.

**Effort:** 0.5 day
**Depends on:** P0-1

---

### P2-4 — `PATCH /api/v2/students/{id}/progress` endpoint

**Description:** Add a new endpoint to the student router that atomically updates `xp` and `streak`.

**Request schema:**
```python
class ProgressUpdate(BaseModel):
    xp_delta: int = Field(ge=0, description="XP to add (non-negative)")
    streak:   int = Field(ge=0, description="Absolute new streak value")
```

**Response schema:**
```python
class ProgressResponse(BaseModel):
    id:     int
    xp:     int
    streak: int
```

**SQL pattern (via SQLAlchemy):**
```python
await db.execute(
    update(Student)
    .where(Student.id == student_id)
    .values(xp=Student.xp + progress.xp_delta, streak=progress.streak)
    .returning(Student.id, Student.xp, Student.streak)
)
```

**DoD:**
- `PATCH /api/v2/students/1/progress {"xp_delta": 10, "streak": 3}` returns 200 with updated values.
- Concurrent calls do not lose XP increments (verified by sequential double-call test where both deltas accumulate).
- Student not found returns 404.
- `xp_delta < 0` returns 422 (Pydantic validation).

**Effort:** 0.5 day
**Depends on:** P2-3

---

### P2-5 — N+1 fix in `list_students()`

**Description:** Rewrite `list_students()` in the student service to retrieve mastered-concept counts in a single query using a LEFT JOIN or correlated subquery. Current implementation issues one `COUNT` query per student.

**Pattern:**
```python
from sqlalchemy import func, select, outerjoin

stmt = (
    select(Student, func.count(StudentMastery.id).label("mastered_count"))
    .outerjoin(StudentMastery, StudentMastery.student_id == Student.id)
    .group_by(Student.id)
    .order_by(Student.id)
)
results = await db.execute(stmt)
```

**DoD:**
- `GET /api/v2/students` with 100 students in the DB completes in < 200 ms (measured with `time curl`).
- `EXPLAIN ANALYZE` shows a single query plan with a hash join or index nested loop — no repeated sequential scan on `student_mastery`.
- Response body is identical to current output (no schema change).

**Effort:** 0.5 day
**Depends on:** P0-2

---

### P2-6 — `.limit(200)` guard on `load_student_history()`

**Description:** Add `.limit(200)` to the SQLAlchemy query in `load_student_history()` (in `teaching_service.py` or the relevant service file). Log a WARNING if the result set was capped (i.e., `len(results) == 200`).

**DoD:**
- A student with 300 card interactions in the DB receives a 200-record response.
- A `WARNING` log line is emitted when the cap is hit.
- A student with 50 interactions receives all 50 records.

**Effort:** 0.25 day
**Depends on:** P0-2

---

### P2-7 — Connection pool tuning

**Description:** Update the SQLAlchemy `create_async_engine()` call in `backend/src/db/connection.py` to use `pool_size=20` and `max_overflow=80`.

```python
engine = create_async_engine(
    config.DATABASE_URL,
    pool_size=20,
    max_overflow=80,
    pool_timeout=30,
    pool_recycle=1800,
)
```

Add `POOL_SIZE`, `POOL_MAX_OVERFLOW`, `POOL_TIMEOUT`, `POOL_RECYCLE` constants to `config.py`.

**DoD:** Backend starts without error. Log output at startup shows engine created (add an `INFO` log confirming pool parameters). `SHOW max_connections` on PostgreSQL >= 150 (from P0-5).

**Effort:** 0.25 day
**Depends on:** P0-5

---

### P2-8 — Pillow image validation at extraction time

**Description:** In `backend/src/images/` (the image extraction module), after each image is decoded from the PDF page, open it with `Pillow` (`Image.open(BytesIO(image_bytes))`). If the open raises any exception, log a WARNING and skip the image. If the image is valid, compute its mean pixel intensity via `ImageStat.Stat(img).mean`; if the mean across all channels is below `config.IMAGE_BLACK_THRESHOLD` (default 5), log a WARNING with the page number and skip the image.

**Constants to add to `config.py`:**
```python
IMAGE_BLACK_THRESHOLD: int = int(os.getenv("IMAGE_BLACK_THRESHOLD", "5"))
```

**DoD:**
- A synthetically injected all-black PNG is not written to `image_index.json`.
- A valid diagram image passes validation and is written to the index.
- Corrupted image bytes (truncated JPEG) are skipped with a WARNING log, not a crash.
- The pipeline completes end-to-end without exception when a bad image is encountered.

**Effort:** 0.75 day
**Depends on:** None (offline pipeline change)

---

### P2-9 — UNMAPPED proximity resolver

**Description:** In the image extraction pipeline, after the initial concept-assignment pass, collect all images still tagged as `UNMAPPED`. For each UNMAPPED image, scan `image_index.json` for all concepts sorted by their representative page range. Find the concept whose closest page is within ±5 pages of the image's source page. If found, reassign the image to that concept and log an INFO message. If no concept is within range, discard the image and log a WARNING.

**Constants to add to `config.py`:**
```python
UNMAPPED_PROXIMITY_PAGES: int = 5
```

**DoD:**
- A test image at page 42 that was previously UNMAPPED is assigned to the concept spanning pages 40–45.
- A test image at page 1 with no concept within ±5 pages is discarded.
- All assigned images appear in `image_index.json` under the correct `concept_id` key.
- The pipeline produces zero UNMAPPED entries in `image_index.json` after resolver runs (or logs the count discarded).

**Effort:** 1 day
**Depends on:** P2-8

---

### P2-10 — Vision annotator prompt replacement

**Description:** In `backend/src/images/` (the vision annotation module), replace the current structured prompt (which produces "What it shows: / Why it helps:" sections) with a new prompt that produces a single conversational paragraph.

**New prompt template:**
```
You are a math education assistant. Describe this image in a single conversational paragraph
as you would to a student reading a mathematics textbook. Focus on what the image depicts
mathematically and why it aids understanding of the concept. Do not use headers, bullet points,
or labels. Write between 40 and 120 words.
```

The response is stored as-is in `image_index.json` under the `description` key and in ChromaDB concept metadata under the `vision_description` field.

**DoD:**
- Running the vision annotator on a sample concept image produces a description with no "What it shows:" or "Why it helps:" substrings.
- The description is between 40 and 120 words (verified by word count assertion in the test).
- The description is stored correctly in `image_index.json`.

**Effort:** 0.5 day
**Depends on:** P2-9

---

### P2-11 — Vision description injection into LLM prompts

**Description:** Update `backend/src/api/prompts.py` (and any prompt-building functions in `adaptive/prompt_builder.py`) to include vision descriptions when available.

**Injection pattern:** When `KnowledgeService.get_concept_images()` returns one or more images with a non-empty `description` field, concatenate them into a `[Visual Context]` block and append to the prompt context string passed to each LLM call.

```
[Visual Context]
The following image accompanies this concept:
{description}
```

Apply to:
1. Presentation phase prompt (in `teaching_service.py` / `prompts.py`)
2. Socratic check prompt (in `teaching_service.py` / `prompts.py`)
3. Card generation prompt (in `adaptive/prompt_builder.py` — `build_next_card_prompt()`)

**DoD:**
- A concept with a vision description produces an LLM call whose prompt contains the `[Visual Context]` block (verifiable via `caplog` in tests).
- A concept with no images produces a prompt without the `[Visual Context]` block.
- Token count of prompts with injection does not exceed existing `max_tokens` caps (verified by manual inspection of a sample concept with a long description).

**Effort:** 1 day
**Depends on:** P2-10

---

## Phase 4 — Frontend Implementation (frontend-developer)

### P4-1 — Global Axios interceptor: `X-API-Key` header

**Description:** Add a request interceptor to the shared Axios instance in `frontend/src/api/` (likely `client.js` or `axios.js`) that attaches `X-API-Key: {VITE_API_SECRET_KEY}` to every outbound request.

```javascript
// frontend/src/api/client.js
const apiClient = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL });

apiClient.interceptors.request.use((config) => {
  config.headers['X-API-Key'] = import.meta.env.VITE_API_SECRET_KEY;
  return config;
});
```

**DoD:**
- Browser DevTools Network tab shows `X-API-Key` header on every API request.
- App functions correctly end-to-end with the key set in `frontend/.env`.
- A deliberate wrong key in `frontend/.env` causes all API calls to return 401 (visible in console).

**Effort:** 0.5 day
**Depends on:** P2-1

---

### P4-2 — Zustand store: load `xp`/`streak` from DB on app start

**Description:** In `frontend/src/store/adaptiveStore.js`, the store's `xp` and `streak` fields currently initialise to `0`. Update the app initialisation flow so that when a student is loaded (i.e., when `StudentContext` resolves `GET /api/v2/students/{id}`), the returned `xp` and `streak` values are written into the Zustand store via a new action `HYDRATE_PROGRESS`.

**Zustand action:**
```javascript
hydrateProgress: (xp, streak) => set({ xp, streak }),
```

**Trigger point:** In `StudentContext` or `LearningPage`, after the student fetch resolves, call `useAdaptiveStore.getState().hydrateProgress(student.xp, student.streak)`.

**DoD:**
- Refresh the browser on a student with `xp=150, streak=5`. The XP bar and streak meter show the persisted values immediately (not reset to 0).
- A student with default `xp=0, streak=0` sees no regression.

**Effort:** 0.5 day
**Depends on:** P2-3, P4-1

---

### P4-3 — XP sync after card completion

**Description:** After each successful card completion (currently handled in `CardLearningView.jsx` in the `ADAPTIVE_CARD_LOADED` dispatch or the completion handler), call `PATCH /api/v2/students/{id}/progress` with the XP delta earned and the new streak value from the Zustand store.

**Implementation:**
- Add `patchStudentProgress(studentId, xpDelta, streak)` to `frontend/src/api/students.js`.
- Call it fire-and-forget (do not `await` in the UI path to avoid blocking card render).
- Catch errors silently, log to console as a warning (do not surface to user).

```javascript
// fire-and-forget sync
patchStudentProgress(student.id, xpEarned, currentStreak).catch((err) =>
  console.warn('[progress-sync] failed:', err.message)
);
```

**DoD:**
- After completing a card that awards 10 XP, `GET /api/v2/students/{id}` returns `xp` incremented by 10.
- A network failure during sync does not cause the UI to freeze or display an error.
- After a sync failure, the Zustand store retains the correct in-memory value.

**Effort:** 0.5 day
**Depends on:** P2-4, P4-2

---

### P4-4 — Remove vision description labels; render as italic paragraph

**Description:** Locate the image display component(s) in the frontend (likely within `CardLearningView.jsx`, `SocraticChat.jsx`, or a shared `ConceptImage` component). Remove any code that prepends "What it shows:" or "Why it helps:" prefixes. Render the raw `description` field from the image object as an `<em>` paragraph below the image.

```jsx
{image.description && (
  <p className="text-sm italic text-gray-500 mt-2">
    <em>{image.description}</em>
  </p>
)}
```

**DoD:**
- An image with a description shows only the prose text in italic, with no label prefix.
- An image without a description shows nothing in the description area.
- The change is applied consistently across all views that render concept images.

**Effort:** 0.5 day
**Depends on:** P2-10 (new description format must be in the DB/index before this renders correctly)

---

## Phase 3 — Testing (comprehensive-tester)

### P3-1 — Auth middleware tests

**Test file:** `backend/tests/test_auth_middleware.py`

| Test ID | Description | Expected |
|---|---|---|
| T-AUTH-01 | Request with correct `X-API-Key` → 200 | Pass |
| T-AUTH-02 | Request with missing `X-API-Key` → 401 `{"detail": "Unauthorized"}` | Pass |
| T-AUTH-03 | Request with wrong key → 401 | Pass |
| T-AUTH-04 | GET `/health` without key → 200 | Pass |
| T-AUTH-05 | GET `/docs` without key → 200 | Pass |
| T-AUTH-06 | GET `/openapi.json` without key → 200 | Pass |

**Effort:** 0.5 day
**Depends on:** P2-1

---

### P3-2 — Rate limiting tests

**Test file:** `backend/tests/test_rate_limiting.py`

| Test ID | Description | Expected |
|---|---|---|
| T-RATE-01 | 10 LLM-heavy requests → all 200; 11th → 429 | Pass |
| T-RATE-02 | 429 response includes `Retry-After` header | Pass |
| T-RATE-03 | Read endpoint allows 120 requests before 429 | Pass |
| T-RATE-04 | Counter resets after minute window | Pass |

Note: Use pytest-mock or monkeypatching to freeze time for window-reset test.

**Effort:** 0.75 day
**Depends on:** P2-2

---

### P3-3 — XP/streak persistence tests

**Test file:** `backend/tests/test_student_progress.py`

| Test ID | Description | Expected |
|---|---|---|
| T-PROG-01 | `GET /api/v2/students/{id}` returns `xp` and `streak` fields | Pass |
| T-PROG-02 | `PATCH /progress {"xp_delta": 10, "streak": 3}` → `{"xp": 10, "streak": 3}` | Pass |
| T-PROG-03 | Two sequential `PATCH /progress {"xp_delta": 10}` → `xp = 20` | Pass (atomic accumulation) |
| T-PROG-04 | `PATCH /progress` for unknown student → 404 | Pass |
| T-PROG-05 | `PATCH /progress {"xp_delta": -1}` → 422 (Pydantic validation) | Pass |

**Effort:** 0.5 day
**Depends on:** P2-4

---

### P3-4 — Query performance tests

**Test file:** `backend/tests/test_query_performance.py`

| Test ID | Description | Expected |
|---|---|---|
| T-PERF-01 | `list_students()` with 100 students issues exactly 1 DB query (assert via `sqlalchemy.event` listener) | Pass |
| T-PERF-02 | Student with 300 history records → `load_student_history()` returns exactly 200 | Pass |
| T-PERF-03 | History cap emits a WARNING log entry | Pass |

**Effort:** 0.5 day
**Depends on:** P2-5, P2-6

---

### P3-5 — Image pipeline tests

**Test file:** `backend/tests/test_image_pipeline.py`

| Test ID | Description | Expected |
|---|---|---|
| T-IMG-01 | All-black PNG (mean < 5) is skipped; not in `image_index.json` | Pass |
| T-IMG-02 | Truncated/corrupted JPEG bytes → pipeline continues, WARNING logged | Pass |
| T-IMG-03 | UNMAPPED image at page 42, concept at pages 40–45 → reassigned | Pass |
| T-IMG-04 | UNMAPPED image at page 1 with no nearby concept → discarded, WARNING logged | Pass |
| T-IMG-05 | Vision prompt response contains no "What it shows:" substring | Pass |
| T-IMG-06 | Vision description injected into presentation prompt when image exists | Pass |
| T-IMG-07 | No `[Visual Context]` block in prompt when concept has no images | Pass |

**Effort:** 1 day
**Depends on:** P2-8, P2-9, P2-10, P2-11

---

## Dependencies and Critical Path

```
P0-1 ──────────────► P2-3 ──► P2-4 ──► P4-2 ──► P4-3 ──► P3-3
P0-2 ──────────────► P2-5
                  └─► P2-6
P0-3 ──────────────► P2-2
P0-4 ──────────────► P2-1 ──► P2-2 ──► P4-1 ──────────────► P3-1, P3-2
P0-5 ──────────────► P2-7
P2-8 ──► P2-9 ──► P2-10 ──► P2-11 ──► P3-5
                           └─► P4-4
```

**Critical path:** `P0-1 → P2-3 → P2-4 → P4-2 → P4-3 → P3-3`

The XP persistence chain is the longest sequential dependency and should start first. Auth (`P2-1`) can be worked on in parallel by the backend developer once `P0-4` is done.

---

## Definition of Done

### Phase 0 (devops-engineer)
- [ ] `alembic upgrade head` runs cleanly on a fresh DB and on the dev DB with existing data
- [ ] `students` table has `xp` and `streak` columns with `DEFAULT 0`
- [ ] Three performance indices exist and are confirmed via `psql \d`
- [ ] `slowapi` is in `requirements.txt` and installs without conflict
- [ ] Both `.env.example` files updated with new keys
- [ ] PostgreSQL `max_connections >= 150` confirmed

### Phase 2 (backend-developer)
- [ ] `APIKeyMiddleware` rejects all non-exempt paths without the correct key (returns 401)
- [ ] Backend refuses to start without `API_SECRET_KEY` set
- [ ] Rate limits enforced at all three tiers; 429 includes `Retry-After`
- [ ] `GET /api/v2/students/{id}` response includes `xp` and `streak`
- [ ] `PATCH /api/v2/students/{id}/progress` atomically accumulates XP
- [ ] `list_students()` verified as single-query via `EXPLAIN ANALYZE`
- [ ] `load_student_history()` caps at 200 rows with a WARNING log on cap
- [ ] Connection pool set to `pool_size=20, max_overflow=80`
- [ ] Corrupted/black images skipped at extraction with WARNING logs
- [ ] UNMAPPED images resolved or discarded; zero UNMAPPED entries remain in `image_index.json`
- [ ] Vision descriptions use prose format (no label prefixes)
- [ ] Vision descriptions injected into all three LLM prompt types

### Phase 4 (frontend-developer)
- [ ] Every API request carries `X-API-Key` header (verified in DevTools)
- [ ] App shows persisted `xp`/`streak` immediately after browser refresh
- [ ] Card completion triggers a fire-and-forget sync to `PATCH /progress`
- [ ] Image descriptions render as single italic paragraph with no label prefix

### Phase 3 (comprehensive-tester)
- [ ] All test cases in P3-1 through P3-5 pass
- [ ] No existing tests regressed
- [ ] Test coverage for new code paths >= 80%

---

## Rollout Strategy

### Deployment Order
1. Run `alembic upgrade head` (P0-1, P0-2) — zero downtime, additive migrations
2. Deploy backend with `API_SECRET_KEY` set in environment
3. Deploy frontend with `VITE_API_SECRET_KEY` set in build environment
4. Smoke test: confirm `/health` is accessible without key; confirm `/api/v2/students` requires key
5. Run image pipeline re-extraction for any book where UNMAPPED or corrupted images are known

### Rollback Plan
- **Auth middleware:** Remove `APIKeyMiddleware` registration in `main.py` and redeploy; no DB change.
- **Rate limiting:** Remove `SlowAPIMiddleware` and all `@limiter.limit` decorators; no DB change.
- **XP/streak:** Alembic downgrade removes columns (data loss — XP/streak values are lost). Accept this risk; columns are new and contain no legacy data.
- **Query fixes:** Revert service file changes; index drops are in the Alembic downgrade.
- **Image pipeline:** Re-run pipeline from previous extraction output (images are idempotently regenerated).

### Post-Launch Validation
- Monitor `/health` endpoint response time (should remain < 10 ms)
- Monitor 401 rate in API logs — high 401 rate indicates misconfigured client
- Monitor 429 rate in API logs — sustained 429s may indicate threshold is too strict
- Verify XP accumulation for one test student end-to-end
- Run `EXPLAIN ANALYZE` on `list_students` in production to confirm index usage

---

## Effort Summary Table

| Phase | Agent | Key Tasks | Estimated Effort | Notes |
|---|---|---|---|---|
| Phase 0 | devops-engineer | 2 Alembic migrations, requirements.txt, .env.example, pg max_connections | 1.5 days | All parallelizable |
| Phase 2 | backend-developer | Auth middleware, rate limiting, XP endpoint, query fixes, image pipeline | 6.25 days | Auth + rate limiting critical path; image pipeline parallelizable |
| Phase 4 | frontend-developer | Axios interceptor, Zustand hydration, XP sync, image label removal | 2.0 days | Can start P4-1 as soon as P2-1 is done |
| Phase 3 | comprehensive-tester | Auth, rate limit, XP, query, image pipeline test suites | 3.25 days | Can run in parallel with Phase 4 |
| **Total** | | | **~13 days** | With 2 engineers (1 backend, 1 frontend/tester): ~7 calendar days |

---

## Key Decisions Requiring Stakeholder Input

1. **Rate limit thresholds** — 10/min for LLM endpoints may be too low if the platform runs automated classroom batch sessions. Confirm acceptable burst patterns before Phase 2 starts.
2. **Shared API key vs. per-client keys** — A single `API_SECRET_KEY` means all frontend deployments share the same credential. If multiple independent deployments are planned, a key-per-deployment model requires a simple key registry (out of current scope).
3. **XP monotonicity** — The `PATCH /progress` schema rejects negative `xp_delta`. Confirm this is the intended game design (XP never decreases). If streak resets should also reset XP, the schema requires a separate `xp_set` field.
4. **Image re-extraction scope** — The Pillow validation and UNMAPPED resolver only take effect when the pipeline is re-run. Confirm whether all 16 books need to be re-extracted or only those with known image quality issues.
5. **Vision description length cap** — The new vision prompt requests 40–120 words. Confirm this range is appropriate. Shorter descriptions reduce token overhead; longer descriptions may improve LLM context quality.
