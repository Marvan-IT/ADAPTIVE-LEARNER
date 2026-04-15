# Detailed Low-Level Design — Admin Console + Simplified Registration

**Feature slug:** `admin-console`
**Date:** 2026-04-13
**Status:** Approved for implementation

---

## 1. Component Breakdown

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `admin_router.py` | `backend/src/api/admin_router.py` | All `/api/admin/*` endpoint handlers — extended with ~25 new endpoints |
| `ChunkKnowledgeService` | `backend/src/api/chunk_knowledge_service.py` | Chunk queries with `is_hidden` filter; graph cache with Lock; `_apply_overrides()` |
| `TeachingService` | `backend/src/api/teaching_service.py` | Exam gate logic — respects `exam_disabled` flag on chunks |
| `TeachingRouter` | `backend/src/api/teaching_router.py` | `all_study_complete` check excludes hidden + optional chunks |
| Auth schemas | `backend/src/auth/schemas.py` | Remove `interests`/`preferred_style`; add `age` to `RegisterRequest` |
| Auth service | `backend/src/auth/service.py` | Update `Student()` constructor — pass `age`, use defaults for removed fields |
| `models.py` | `backend/src/db/models.py` | New fields on `Student`, `ConceptChunk`; new `AdminGraphOverride`, `AdminConfig` ORM models |
| `config.py` | `backend/src/config.py` | New constants; runtime override from `admin_config` table |
| `admin.js` | `frontend/src/api/admin.js` | ~25 Axios wrapper functions for all admin endpoints |
| `RegisterPage.jsx` | `frontend/src/pages/RegisterPage.jsx` | Remove interests + style fields; add age number input |
| `AdminPage.jsx` | `frontend/src/pages/AdminPage.jsx` | Enhanced dashboard with stat cards and nav grid |
| `AdminStudentsPage.jsx` | `frontend/src/pages/AdminStudentsPage.jsx` | NEW — searchable student table |
| `AdminStudentDetailPage.jsx` | `frontend/src/pages/AdminStudentDetailPage.jsx` | NEW — student profile editor + mastery control |
| `AdminSessionsPage.jsx` | `frontend/src/pages/AdminSessionsPage.jsx` | NEW — session list with filters |
| `AdminAnalyticsPage.jsx` | `frontend/src/pages/AdminAnalyticsPage.jsx` | NEW — concept difficulty + mastery rate charts |
| `AdminSettingsPage.jsx` | `frontend/src/pages/AdminSettingsPage.jsx` | NEW — system config form |
| `AdminReviewPage.jsx` | `frontend/src/pages/AdminReviewPage.jsx` | Enhanced — adds section + chunk + graph controls |
| `AdminBookContentPage.jsx` | `frontend/src/pages/AdminBookContentPage.jsx` | NEW — post-publish content editing (same layout as enhanced ReviewPage) |
| `App.jsx` | `frontend/src/App.jsx` | 6 new admin routes |

---

## 2. Database Design

### 2a. New Columns — `students` table (migration 011)

```sql
ALTER TABLE students
  ADD COLUMN age INTEGER NULL;
  -- No range constraint at DB level; validation in Pydantic schema
  -- NULL = not provided (existing + new students who skip the field)
```

ORM addition to `backend/src/db/models.py` (`Student` class):
```python
age: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

### 2b. New Columns — `concept_chunks` table (migration 012)

```sql
ALTER TABLE concept_chunks
  ADD COLUMN is_hidden     BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN exam_disabled BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN admin_section_name TEXT NULL;
```

ORM additions to `ConceptChunk` class:
```python
is_hidden          = Column(Boolean, nullable=False, server_default="false")
exam_disabled      = Column(Boolean, nullable=False, server_default="false")
admin_section_name = Column(Text, nullable=True)
```

### 2c. New Table — `admin_graph_overrides` (migration 012)

```sql
CREATE TABLE admin_graph_overrides (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_slug      TEXT NOT NULL,
    action         TEXT NOT NULL CHECK (action IN ('add_edge', 'remove_edge')),
    source_concept TEXT NOT NULL,
    target_concept TEXT NOT NULL,
    created_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (book_slug, action, source_concept, target_concept)
);
```

ORM model (`models.py`):
```python
class AdminGraphOverride(Base):
    __tablename__ = "admin_graph_overrides"
    __table_args__ = (
        UniqueConstraint("book_slug", "action", "source_concept", "target_concept",
                         name="uq_graph_override"),
        CheckConstraint("action IN ('add_edge', 'remove_edge')",
                        name="ck_graph_override_action"),
    )

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_slug      = Column(Text, nullable=False)
    action         = Column(Text, nullable=False)
    source_concept = Column(Text, nullable=False)
    target_concept = Column(Text, nullable=False)
    created_by     = Column(UUID(as_uuid=True),
                            ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at     = Column(TIMESTAMPTZ(timezone=True), server_default=func.now())
```

### 2d. New Table — `admin_config` (migration 012)

```sql
CREATE TABLE admin_config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

ORM model (`models.py`):
```python
class AdminConfig(Base):
    __tablename__ = "admin_config"

    key        = Column(Text, primary_key=True)
    value      = Column(Text, nullable=False)
    updated_by = Column(UUID(as_uuid=True),
                        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(TIMESTAMPTZ(timezone=True), server_default=func.now(),
                        onupdate=func.now())
```

### 2e. Indexes to Add (migration 012)

```sql
-- For admin student queries
CREATE INDEX ix_students_user_id ON students(user_id);
-- For chunk admin queries
CREATE INDEX ix_concept_chunks_is_hidden ON concept_chunks(book_slug, concept_id) WHERE is_hidden = true;
CREATE INDEX ix_concept_chunks_exam_disabled ON concept_chunks(book_slug, concept_id) WHERE exam_disabled = true;
-- For graph overrides lookup
CREATE INDEX ix_admin_graph_overrides_book ON admin_graph_overrides(book_slug);
```

### 2f. Data Flow Summary

```
Registration flow:
  RegisterRequest (name, email, password, age?)
    → auth/service.py  →  Student(interests=[], preferred_style="default", age=age)
    → students table

Admin chunk edit flow:
  PATCH /api/admin/chunks/{id}
    → UPDATE concept_chunks SET heading=?, text=?, ... WHERE id=?
    → Student next session calls get_chunks_for_concept() → sees updated text immediately

Graph override flow:
  POST /api/admin/graph/{slug}/edges
    → INSERT admin_graph_overrides(action, source, target, created_by)
    → reload_graph_with_overrides(book_slug, db)
    → _graph_cache[book_slug] replaced atomically under Lock
    → All subsequent teaching flow prerequisite checks use new graph

Embedding regeneration flow:
  POST /api/admin/chunks/{id}/regenerate-embedding
    → Fetch chunk text from DB
    → OpenAI embeddings.create(input=text, model="text-embedding-3-small")
    → UPDATE concept_chunks SET embedding=? WHERE id=?
    → Chunk re-enters semantic search pool
```

---

## 3. API Design

### Authentication
All `/api/admin/*` endpoints require the `require_admin` FastAPI dependency (JWT role check via `auth/dependencies.py`). HTTP 401 if unauthenticated, 403 if authenticated but not admin role.

### Error Conventions
```
400 Bad Request     — validation failure (missing field, invalid value)
401 Unauthorized    — no valid JWT
403 Forbidden       — valid JWT but not admin role
404 Not Found       — resource not found
409 Conflict        — duplicate (e.g., duplicate graph edge), or merge-across-concepts
422 Unprocessable   — cycle detected in graph edge addition
```

### Versioning
Admin endpoints remain under `/api/admin/` (unversioned prefix) consistent with existing `admin_router.py` convention.

---

### 3a. Dashboard

#### `GET /api/admin/dashboard`
```
Auth: require_admin
Response 200:
{
  "total_students": int,
  "active_students_7d": int,      // students with session in last 7 days
  "active_sessions_now": int,     // sessions with phase != "COMPLETED" and updated_at > 1h ago
  "mastery_completions_today": int,
  "avg_accuracy_rate": float,     // average of students.overall_accuracy_rate
  "total_concepts_mastered": int,
  "books_published": int
}
```

---

### 3b. Students

#### `GET /api/admin/students`
```
Auth: require_admin
Query params:
  q        string  — search display_name or email (ILIKE)
  sort     string  — "name"|"created_at"|"xp"|"accuracy" (default: "created_at")
  dir      string  — "asc"|"desc" (default: "desc")
  limit    int     — max 200, default 50
  offset   int     — default 0
  active   bool    — filter is_active (requires is_active column on students — see note)

Response 200:
{
  "students": [
    {
      "id": UUID,
      "display_name": str,
      "email": str,           // from users table via user_id FK
      "age": int | null,
      "preferred_language": str,
      "xp": int,
      "streak": int,
      "section_count": int,
      "overall_accuracy_rate": float,
      "concepts_mastered": int,
      "last_active_at": ISO8601 | null,  // max(sessions.updated_at)
      "created_at": ISO8601,
      "is_active": bool
    }
  ],
  "total": int,
  "limit": int,
  "offset": int
}
```

**Note:** `is_active` requires adding a boolean column to `students`. This is a lightweight column — not a separate migration if combined with 011 or added to 012. The plan document does not explicitly include it; add as `students.is_active BOOLEAN NOT NULL DEFAULT true` in migration 012.

#### `GET /api/admin/students/{student_id}`
```
Auth: require_admin
Response 200:
{
  "id": UUID,
  "display_name": str,
  "email": str,
  "age": int | null,
  "preferred_language": str,
  "preferred_style": str,
  "interests": [str],
  "xp": int,
  "streak": int,
  "section_count": int,
  "overall_accuracy_rate": float,
  "avg_state_score": float,
  "boredom_pattern": str | null,
  "frustration_tolerance": str | null,
  "recovery_speed": str | null,
  "state_distribution": {struggling: int, normal: int, fast: int},
  "effective_analogies": [str],
  "effective_engagement": [str],
  "ineffective_engagement": [str],
  "concepts_mastered": [
    {"concept_id": str, "mastered_at": ISO8601, "session_id": UUID | null}
  ],
  "recent_sessions": [
    {"id": UUID, "concept_id": str, "book_slug": str, "phase": str,
     "started_at": ISO8601, "completed_at": ISO8601 | null}
  ],  // last 10
  "created_at": ISO8601,
  "is_active": bool
}
```

#### `PATCH /api/admin/students/{student_id}`
```
Auth: require_admin
Request body (all optional):
{
  "display_name": str,
  "preferred_language": str,
  "preferred_style": str,
  "age": int | null
}
Response 200: updated student object (same shape as GET detail)
```

#### `PATCH /api/admin/students/{student_id}/access`
```
Auth: require_admin
Request body: { "is_active": bool }
Response 200: { "id": UUID, "is_active": bool }
```

#### `DELETE /api/admin/students/{student_id}`
```
Auth: require_admin
Description: Soft delete — sets is_active=false, does not cascade-delete learning data
Response 204: no body
```

#### `POST /api/admin/students/{student_id}/reset-password`
```
Auth: require_admin
Request body: { "new_password": str }   // min 8 chars validated by Pydantic
Response 200: { "message": "Password updated" }
```

#### `POST /api/admin/students/{student_id}/mastery/{concept_id}`
```
Auth: require_admin
Description: Manually mark a concept mastered for a student
Request body: {} (empty — no payload needed)
Response 200:
{
  "student_id": UUID,
  "concept_id": str,
  "mastered_at": ISO8601,
  "manual": true
}
409 if already mastered
```

#### `DELETE /api/admin/students/{student_id}/mastery/{concept_id}`
```
Auth: require_admin
Description: Remove a mastery record
Response 204: no body
404 if not found
```

---

### 3c. Sessions

#### `GET /api/admin/sessions`
```
Auth: require_admin
Query params:
  student_id  UUID    — filter by student
  book_slug   str     — filter by book
  phase       str     — filter by phase (PRESENTING|CARDS|CHECKING|COMPLETED|...)
  from_date   ISO8601 — started_at >=
  to_date     ISO8601 — started_at <=
  limit       int     — max 200, default 50
  offset      int     — default 0

Response 200:
{
  "sessions": [
    {
      "id": UUID,
      "student_id": UUID,
      "student_name": str,
      "concept_id": str,
      "book_slug": str,
      "phase": str,
      "questions_asked": int,
      "questions_correct": float,
      "best_check_score": int | null,
      "concept_mastered": bool,
      "started_at": ISO8601,
      "completed_at": ISO8601 | null
    }
  ],
  "total": int,
  "limit": int,
  "offset": int
}
```

---

### 3d. Analytics

#### `GET /api/admin/analytics`
```
Auth: require_admin
Query params:
  book_slug  str  — optional; defaults to all books

Response 200:
{
  "concept_difficulty": [
    {
      "concept_id": str,
      "book_slug": str,
      "attempt_count": int,
      "mastery_rate": float,      // mastered / attempted
      "avg_accuracy": float,
      "avg_attempts_to_master": float
    }
  ],
  "student_accuracy_bands": {
    "0-40": int,     // count of students in band
    "41-60": int,
    "61-80": int,
    "81-100": int
  },
  "daily_mastery": [
    {"date": "YYYY-MM-DD", "count": int}
  ]  // last 30 days
}
```

---

### 3e. Admin User Management

#### `GET /api/admin/users`
```
Auth: require_admin
Query params: role str (optional, default "admin")
Response 200:
{
  "users": [
    {"id": UUID, "email": str, "role": str, "created_at": ISO8601, "last_login_at": ISO8601 | null}
  ]
}
```

#### `POST /api/admin/users/create-admin`
```
Auth: require_admin
Request body: { "email": str, "password": str, "display_name": str }
Response 201: { "id": UUID, "email": str, "role": "admin" }
409 if email already exists
```

#### `PATCH /api/admin/users/{user_id}/role`
```
Auth: require_admin
Request body: { "role": "admin" | "student" }
Response 200: { "id": UUID, "role": str }
403 if attempting to demote the last admin
```

---

### 3f. System Config

#### `GET /api/admin/config`
```
Auth: require_admin
Response 200:
{
  "config": [
    {"key": str, "value": str, "updated_by": UUID | null, "updated_at": ISO8601}
  ]
}
```

#### `PATCH /api/admin/config`
```
Auth: require_admin
Request body:
{
  "updates": [
    {"key": str, "value": str}   // key must be in ALLOWED_CONFIG_KEYS whitelist
  ]
}
Response 200: { "updated": [str] }  // list of keys updated
400 if any key not in allowlist
```

**Allowed config keys (constant in `config.py`):**
```python
ALLOWED_CONFIG_KEYS = frozenset({
    "MASTERY_THRESHOLD",
    "XP_PER_CORRECT_MCQ",
    "XP_PER_SHORT_ANSWER",
    "ADAPTIVE_CARD_CEILING",
    "OPENAI_MODEL",
    "OPENAI_MODEL_MINI",
})
```

---

### 3g. Chunk Operations

#### `PATCH /api/admin/chunks/{chunk_id}`
```
Auth: require_admin
Request body (all optional):
{
  "heading": str,
  "text": str,
  "chunk_type": str,
  "is_optional": bool,
  "is_hidden": bool,
  "exam_disabled": bool,
  "admin_section_name": str | null
}
Response 200:
{
  "id": UUID,
  "heading": str,
  "text": str,
  "chunk_type": str,
  "is_optional": bool,
  "is_hidden": bool,
  "exam_disabled": bool,
  "admin_section_name": str | null,
  "embedding_stale": bool    // true if text was changed and embedding NOT regenerated
}
Side effect: if "text" is in the update, set embedding=NULL on the chunk row.
```

#### `PATCH /api/admin/chunks/{chunk_id}/visibility`
```
Auth: require_admin
Request body: { "is_hidden": bool }
Response 200: { "id": UUID, "is_hidden": bool }
```

#### `PATCH /api/admin/chunks/{chunk_id}/exam-gate`
```
Auth: require_admin
Request body: { "exam_disabled": bool }
Response 200: { "id": UUID, "exam_disabled": bool }
```

#### `POST /api/admin/chunks/merge`
```
Auth: require_admin
Request body:
{
  "chunk_id_a": UUID,   // earlier chunk (lower order_index)
  "chunk_id_b": UUID    // later chunk (must be adjacent and same concept_id)
}
Response 200:
{
  "merged_chunk_id": UUID,
  "embedding_stale": true,
  "active_sessions_affected": int
}
409 if chunks are not in the same concept (M8)
422 if chunks are not adjacent (order_index must differ by 1)
Algorithm:
  1. Validate same concept_id; validate adjacency
  2. Combine: merged_text = chunk_a.text + "\n\n" + chunk_b.text
               merged images = chunk_a.images ∪ chunk_b.images (re-indexed)
  3. UPDATE chunk_a: text=merged_text, heading=chunk_a.heading, embedding=NULL
  4. DELETE chunk_b
  5. Re-sequence order_index for all chunks in concept (close the gap)
  6. Migrate chunk_progress: for each session with chunk_progress containing chunk_b.id,
       move chunk_b progress value to chunk_a entry (keep highest score)
  7. Return active_sessions_affected count
```

#### `POST /api/admin/chunks/{chunk_id}/split`
```
Auth: require_admin
Request body:
{
  "split_after_paragraph": int   // 0-indexed paragraph boundary (split after paragraph N)
}
Response 200:
{
  "chunk_a_id": UUID,   // original chunk (now shorter)
  "chunk_b_id": UUID,   // new chunk (remainder)
  "embedding_stale": true,
  "active_sessions_affected": int
}
422 if split_after_paragraph is out of bounds (must be 0 < N < total_paragraphs)
Algorithm:
  1. Split text at paragraph boundary (split on "\n\n")
  2. UPDATE chunk: text=paragraphs[:N]..., embedding=NULL
  3. INSERT new chunk: text=paragraphs[N:]..., order_index=original+1, embedding=NULL
  4. Re-sequence order_index for all chunks after the split point
  5. Migrate chunk_progress: copy original chunk's progress entry to both chunk IDs
  6. Return active_sessions_affected count
```

#### `PUT /api/admin/concepts/{concept_id}/reorder`
```
Auth: require_admin
Request body:
{
  "book_slug": str,
  "chunk_order": [UUID]   // full ordered list of chunk IDs for the concept
}
Response 200: { "updated": int }  // count of chunks re-indexed
422 if chunk_order does not contain exactly all chunk IDs for the concept
Algorithm:
  For i, chunk_id in enumerate(chunk_order):
    UPDATE concept_chunks SET order_index=i WHERE id=chunk_id AND concept_id=concept_id
```

#### `POST /api/admin/chunks/{chunk_id}/regenerate-embedding`
```
Auth: require_admin
Response 200:
{
  "id": UUID,
  "embedding_regenerated": true,
  "model": "text-embedding-3-small"
}
Algorithm:
  1. Fetch chunk.text from DB
  2. openai_client.embeddings.create(input=chunk.text, model="text-embedding-3-small")
  3. UPDATE concept_chunks SET embedding=vector WHERE id=chunk_id
```

#### `POST /api/admin/concepts/{concept_id}/regenerate-embeddings`
```
Auth: require_admin
Request body: { "book_slug": str }
Response 200:
{
  "total": int,
  "regenerated": int,
  "skipped": int    // chunks where embedding was already non-NULL
}
Note: processes stale (embedding IS NULL) chunks only; 100ms sleep between OpenAI calls
```

---

### 3h. Section Controls

#### `PATCH /api/admin/sections/{concept_id}/rename`
```
Auth: require_admin
Request body: { "book_slug": str, "section": str, "new_name": str }
Response 200: { "chunks_updated": int }
Algorithm:
  UPDATE concept_chunks
    SET admin_section_name = :new_name
    WHERE concept_id = :concept_id AND book_slug = :book_slug AND section = :section
```

#### `PATCH /api/admin/sections/{concept_id}/optional`
```
Auth: require_admin
Request body: { "book_slug": str, "section": str, "is_optional": bool }
Response 200: { "chunks_updated": int }
```

#### `PATCH /api/admin/sections/{concept_id}/exam-gate`
```
Auth: require_admin
Request body: { "book_slug": str, "section": str, "exam_disabled": bool }
Response 200: { "chunks_updated": int }
```

---

### 3i. Graph / Prerequisite Editing

#### `GET /api/admin/graph/{book_slug}/edges`
```
Auth: require_admin
Response 200:
{
  "edges": [
    {"source": str, "target": str, "source": "base" | "override"}
  ],
  "override_count": int
}
```

#### `GET /api/admin/graph/{book_slug}/overrides`
```
Auth: require_admin
Response 200:
{
  "overrides": [
    {
      "id": UUID,
      "action": "add_edge" | "remove_edge",
      "source_concept": str,
      "target_concept": str,
      "created_by": UUID | null,
      "created_at": ISO8601
    }
  ]
}
```

#### `POST /api/admin/graph/{book_slug}/edges`
```
Auth: require_admin
Request body:
{
  "action": "add_edge" | "remove_edge",
  "source_concept": str,
  "target_concept": str
}
Response 200:
{
  "override_id": UUID,
  "graph_reloaded": true
}
409 if duplicate override already exists
422 if add_edge would create a cycle (nx.has_path check)
Algorithm:
  1. Validate both node IDs exist in the graph
  2. If action == "add_edge": check nx.has_path(G, target, source) → cycle detection
  3. INSERT admin_graph_overrides(...)
  4. Call reload_graph_with_overrides(book_slug, db)
```

#### `DELETE /api/admin/graph/{book_slug}/overrides/{override_id}`
```
Auth: require_admin
Response 204
Algorithm:
  1. DELETE admin_graph_overrides WHERE id=?
  2. Call reload_graph_with_overrides(book_slug, db)
```

---

## 4. Sequence Diagrams

### 4a. Admin Edits a Chunk (Happy Path)

```
Admin Browser          admin_router.py           PostgreSQL
     │                        │                       │
     │  PATCH /chunks/{id}    │                       │
     │ ──────────────────────►│                       │
     │                        │  SELECT * FROM        │
     │                        │  concept_chunks       │
     │                        │  WHERE id=?           │
     │                        │──────────────────────►│
     │                        │◄──────────────────────│
     │                        │  chunk row            │
     │                        │                       │
     │                        │  UPDATE concept_chunks│
     │                        │  SET text=?,          │
     │                        │  embedding=NULL       │
     │                        │──────────────────────►│
     │                        │◄──────────────────────│
     │                        │  OK                   │
     │◄──────────────────────│                       │
     │  {embedding_stale:true}│                       │
```

### 4b. Admin Adds Graph Edge (Happy Path)

```
Admin Browser       admin_router.py      chunk_knowledge_service    PostgreSQL
     │                    │                        │                      │
     │  POST /graph/      │                        │                      │
     │  prealgebra/edges  │                        │                      │
     │──────────────────►│                        │                      │
     │                    │  cycle detection       │                      │
     │                    │  nx.has_path(G, t, s)  │                      │
     │                    │───────────────────────►│                      │
     │                    │◄───────────────────────│  no cycle            │
     │                    │                        │                      │
     │                    │  INSERT overrides      │                      │
     │                    │────────────────────────────────────────────►│
     │                    │◄────────────────────────────────────────────│
     │                    │                        │                      │
     │                    │  reload_graph_with_    │                      │
     │                    │  overrides()           │                      │
     │                    │───────────────────────►│                      │
     │                    │                        │  SELECT overrides    │
     │                    │                        │─────────────────────►│
     │                    │                        │◄─────────────────────│
     │                    │                        │  apply to graph      │
     │                    │                        │  _graph_cache[slug]= │
     │                    │                        │  new_graph (Lock)    │
     │                    │◄───────────────────────│  done                │
     │◄──────────────────│                        │                      │
     │  {graph_reloaded}  │                        │                      │
```

### 4c. Merge Chunks with Active Session Migration

```
Admin Browser        admin_router.py                  PostgreSQL
     │                     │                               │
     │  POST /chunks/merge │                               │
     │────────────────────►│                               │
     │                     │  SELECT chunk_a, chunk_b      │
     │                     │  validate same concept_id,    │
     │                     │  adjacency check              │
     │                     │──────────────────────────────►│
     │                     │◄──────────────────────────────│
     │                     │                               │
     │                     │  BEGIN TRANSACTION            │
     │                     │  UPDATE chunk_a (merged text, │
     │                     │    embedding=NULL)            │
     │                     │  Transfer chunk_b images      │
     │                     │  DELETE chunk_b               │
     │                     │  Re-sequence order_index      │
     │                     │──────────────────────────────►│
     │                     │                               │
     │                     │  SELECT sessions with         │
     │                     │  chunk_progress containing    │
     │                     │  chunk_b.id                   │
     │                     │──────────────────────────────►│
     │                     │◄──────────────────────────────│
     │                     │  N active sessions            │
     │                     │                               │
     │                     │  UPDATE each session's        │
     │                     │  chunk_progress JSONB         │
     │                     │  (migrate chunk_b → chunk_a)  │
     │                     │──────────────────────────────►│
     │                     │  COMMIT                       │
     │                     │◄──────────────────────────────│
     │◄───────────────────│                               │
     │  {merged_chunk_id,  │                               │
     │   embedding_stale,  │                               │
     │   active_sessions_  │                               │
     │   affected: N}      │                               │
```

### 4d. Student Views Chunk (is_hidden Enforcement)

```
Student Browser      teaching_router.py      ChunkKnowledgeService    PostgreSQL
     │                      │                        │                      │
     │  GET /sessions/{id}/ │                        │                      │
     │  chunks              │                        │                      │
     │─────────────────────►│                        │                      │
     │                      │  get_chunks_for_       │                      │
     │                      │  concept(db, slug, cid)│                      │
     │                      │───────────────────────►│                      │
     │                      │                        │  SELECT * FROM       │
     │                      │                        │  concept_chunks      │
     │                      │                        │  WHERE book_slug=?   │
     │                      │                        │  AND concept_id=?    │
     │                      │                        │  AND is_hidden=FALSE │
     │                      │                        │──────────────────────►│
     │                      │                        │◄──────────────────────│
     │                      │◄───────────────────────│  visible chunks only │
     │◄─────────────────────│                        │                      │
     │  chunks (no hidden)  │                        │                      │
```

---

## 5. Integration Design

### 5a. Graph Cache with Thread Safety

New module-level state in `chunk_knowledge_service.py`:

```python
import threading

_graph_cache: dict[str, nx.DiGraph] = {}
_graph_lock = threading.Lock()


def _load_graph(book_slug: str) -> nx.DiGraph:
    """Load graph.json as NetworkX DiGraph, cache module-level (thread-safe)."""
    with _graph_lock:
        if book_slug not in _graph_cache:
            # ... existing load logic ...
            _graph_cache[book_slug] = G
    return _graph_cache[book_slug]


async def reload_graph_with_overrides(book_slug: str, db: AsyncSession) -> None:
    """Reload graph from disk and apply all admin overrides. Thread-safe."""
    path = OUTPUT_DIR / book_slug / "graph.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    G = nx.DiGraph()
    for node in data["nodes"]:
        G.add_node(node["id"], title=node.get("title", ""))
    for edge in data["edges"]:
        G.add_edge(edge["source"], edge["target"])

    # Apply overrides from DB
    result = await db.execute(
        select(AdminGraphOverride).where(AdminGraphOverride.book_slug == book_slug)
    )
    for override in result.scalars().all():
        if override.action == "add_edge":
            G.add_edge(override.source_concept, override.target_concept)
        elif override.action == "remove_edge":
            if G.has_edge(override.source_concept, override.target_concept):
                G.remove_edge(override.source_concept, override.target_concept)

    with _graph_lock:
        _graph_cache[book_slug] = G

    logger.info("[graph] Reloaded %s with %d override(s)", book_slug, len(overrides))


def _apply_overrides(G: nx.DiGraph, overrides: list) -> nx.DiGraph:
    """Apply a list of AdminGraphOverride objects to a graph copy. Pure function."""
    G2 = G.copy()
    for o in overrides:
        if o.action == "add_edge":
            G2.add_edge(o.source_concept, o.target_concept)
        elif o.action == "remove_edge" and G2.has_edge(o.source_concept, o.target_concept):
            G2.remove_edge(o.source_concept, o.target_concept)
    return G2
```

### 5b. Modified `get_chunks_for_concept()` — is_hidden Filter

```python
async def get_chunks_for_concept(
    self, db: AsyncSession, book_slug: str, concept_id: str,
    include_hidden: bool = False          # ← new parameter
) -> list[dict]:
    q = (
        select(ConceptChunk)
        .where(
            ConceptChunk.book_slug == book_slug,
            ConceptChunk.concept_id == concept_id,
        )
        .order_by(ConceptChunk.order_index)
    )
    if not include_hidden:
        q = q.where(ConceptChunk.is_hidden == False)   # noqa: E712
    result = await db.execute(q)
    chunks = result.scalars().all()
    all_chunks = [self._chunk_to_dict(c) for c in chunks]
    all_chunks = [c for c in all_chunks if len((c.get("text") or "").strip()) >= 100]
    return all_chunks
```

Admin calls pass `include_hidden=True`. All existing student-facing callers use the default (`include_hidden=False`).

Updated `_chunk_to_dict()` to include new fields:
```python
def _chunk_to_dict(self, chunk: ConceptChunk) -> dict:
    return {
        "id": str(chunk.id),
        "book_slug": chunk.book_slug,
        "concept_id": chunk.concept_id,
        "section": chunk.section,
        "order_index": chunk.order_index,
        "heading": chunk.heading,
        "text": chunk.text,
        "latex": chunk.latex or [],
        "images": [],
        "chunk_type":  chunk.chunk_type,
        "is_optional": chunk.is_optional,
        # New admin fields:
        "is_hidden":   getattr(chunk, "is_hidden", False),
        "exam_disabled": getattr(chunk, "exam_disabled", False),
        "admin_section_name": getattr(chunk, "admin_section_name", None),
        "embedding_stale": chunk.embedding is None,
    }
```

### 5c. Teaching Router — `all_study_complete` and Exam Gate

In `teaching_router.py`, the check for whether all chunks are studied must exclude hidden and optional chunks:

```python
# Before (approximate current logic):
all_study_complete = all(
    str(c["id"]) in chunk_progress and chunk_progress[str(c["id"])].get("completed_at")
    for c in chunks
)

# After:
study_required_chunks = [
    c for c in chunks
    if not c.get("is_hidden") and not c.get("is_optional")
]
all_study_complete = all(
    str(c["id"]) in chunk_progress and chunk_progress[str(c["id"])].get("completed_at")
    for c in study_required_chunks
)
```

Exam gate — when generating exam questions per chunk, skip `exam_disabled` chunks:
```python
exam_chunks = [c for c in chunks if not c.get("exam_disabled") and not c.get("is_hidden")]
```

If `exam_chunks` is empty (all chunks have exam disabled), the session auto-advances to COMPLETED with a synthetic score of 100 (all exam gates open).

---

## 6. Security Design

### Authentication
All `/api/admin/*` endpoints use the `require_admin` dependency from `auth/dependencies.py`. This validates the JWT from the `Authorization: Bearer <token>` header and asserts `user.role == "admin"`. Non-admin requests receive HTTP 403.

### Password Reset by Admin
`POST /api/admin/students/{id}/reset-password` writes a bcrypt hash directly to `users.hashed_password`. Requires `require_admin`. The student is not notified by the system (notification is out of scope). The new password must be at least 8 characters (Pydantic `min_length=8`).

### Config Key Allowlist
`PATCH /api/admin/config` validates each key against `ALLOWED_CONFIG_KEYS` (frozenset in `config.py`) before writing. Unknown keys return HTTP 400 with the offending key name.

### Audit Trail
- `admin_graph_overrides.created_by` — FK to `users.id`, SET NULL on user delete
- `admin_config.updated_by` — FK to `users.id`, SET NULL on user delete
- All admin mutation endpoints emit `logger.info("[admin] user=%s action=%s target=%s", user.id, action, target)` at INFO level

### Input Validation
- Chunk text updates: no HTML stripping needed (content is stored raw for LLM use); but length cap `MAX_CHUNK_TEXT_LENGTH = 10000` enforced in Pydantic schema to prevent pathological inputs
- Graph edge concepts: both `source_concept` and `target_concept` validated as existing node IDs in the loaded graph before INSERT
- Paragraph split index: validated `0 < split_after_paragraph < paragraph_count`

---

## 7. Observability Design

### Logging
All admin mutation endpoints log at INFO level with structured fields:
```
[admin] user=<user_id> action=patch_chunk chunk=<chunk_id> fields=["text","heading"]
[admin] user=<user_id> action=merge_chunks a=<id_a> b=<id_b> sessions_affected=3
[admin] user=<user_id> action=add_graph_edge book=prealgebra source=X target=Y
[admin] user=<user_id> action=update_config keys=["MASTERY_THRESHOLD"]
```

### Metrics (recommended additions to existing monitoring)
| Metric | Type | Labels |
|--------|------|--------|
| `admin_chunk_edits_total` | Counter | action (edit/hide/merge/split) |
| `admin_embedding_regenerations_total` | Counter | book_slug |
| `admin_graph_overrides_total` | Counter | book_slug, action |
| `admin_config_updates_total` | Counter | key |

### Alerting Thresholds
- `admin_embedding_regenerations_total` > 500 in 1 hour → alert (potential runaway batch)
- Any 5xx on `/api/admin/*` → alert immediately

---

## 8. Error Handling and Resilience

### Merge/Split Atomicity
Both merge and split operations wrap all DB mutations (UPDATE, INSERT, DELETE, chunk_progress migration) in a single SQLAlchemy transaction (`async with db.begin()`). If any step fails, the transaction rolls back and the response returns HTTP 500 with the error detail. No partial state is committed.

### Embedding Regeneration Failure
If the OpenAI call fails during `regenerate-embedding`, the `embedding` column remains NULL and the endpoint returns HTTP 502. The admin can retry. The chunk continues to be served to students (text is unchanged) but is excluded from semantic search until regenerated.

### Graph Reload Failure
If `reload_graph_with_overrides()` fails (e.g., corrupted `graph.json`), the existing `_graph_cache` entry is NOT replaced. The function logs the error and raises. The endpoint returns HTTP 500. The graph continues serving from the previous cache until the issue is resolved.

### Retry Policy for Embedding Regeneration
Single-chunk: no retry (admin retries manually via UI).
Batch (concept): 3 attempts per chunk with 1-second sleep between attempts; on exhaustion, logs warning and continues to next chunk.

---

## 9. Testing Strategy

### Unit Tests (`backend/tests/test_admin_*.py`)

| Test File | Coverage |
|-----------|----------|
| `test_admin_registration.py` | No interests/style in RegisterRequest; age field; existing students unaffected |
| `test_admin_students.py` | CRUD endpoints; search/sort/paginate; access toggle; mastery mark/unmark |
| `test_admin_sessions.py` | List + filter by phase/book/date |
| `test_admin_analytics.py` | Dashboard stats; accuracy bands; daily mastery |
| `test_admin_chunks.py` | Edit; hide; exam gate; reorder |
| `test_admin_merge_split.py` | Merge validation; split validation; chunk_progress migration; M1/M8 guards |
| `test_admin_sections.py` | Rename; optional toggle; exam gate toggle |
| `test_admin_graph.py` | Add/remove edge; cycle detection; override persistence; reload |
| `test_admin_config.py` | Read; write allowlisted keys; reject unknown keys |
| `test_admin_thread_safety.py` | Concurrent graph reload does not corrupt cache |
| `test_admin_teaching_integration.py` | Hidden chunks excluded from student queries; exam_disabled auto-passes; all_study_complete with hidden/optional |

### Integration Tests
- `test_admin_embedding_regen.py` — mocked OpenAI call; verifies embedding column updated
- Merge/split with real session rows (chunk_progress JSONB migration verified in DB)

### Frontend Tests (when vitest is added per known tech debt)
- AdminStudentsPage renders table rows
- AdminStudentDetailPage mastery toggle triggers correct API calls
- AdminReviewPage chunk edit form calls PATCH correctly
- Graph editor cycle warning displayed on attempted cycle

---

## 10. Frontend Component Tree

```
App.jsx
├── /admin                    AdminPage.jsx (enhanced dashboard)
│   ├── /admin/students       AdminStudentsPage.jsx
│   │   └── /admin/students/:id  AdminStudentDetailPage.jsx
│   ├── /admin/sessions       AdminSessionsPage.jsx
│   ├── /admin/analytics      AdminAnalyticsPage.jsx
│   ├── /admin/settings       AdminSettingsPage.jsx
│   └── /admin/books/:slug/content  AdminBookContentPage.jsx
│
└── (existing)
    ├── /admin/review/:slug   AdminReviewPage.jsx (enhanced)
    └── /admin/books/:slug    AdminSubjectPage.jsx (links to /content)
```

### State Management
All admin pages use local `useState` / `useEffect` — no Zustand store needed. Each page fetches its own data on mount. Mutations trigger a local data refetch. No shared reactive state between admin pages.

---

## 11. API Client Wrappers (`frontend/src/api/admin.js`)

All new functions to add:

```javascript
// ── Dashboard ──────────────────────────────────────────────────────────────
export const getAdminDashboard = () => api.get("/api/admin/dashboard");

// ── Students ───────────────────────────────────────────────────────────────
export const getAdminStudents = (params) => api.get("/api/admin/students", { params });
export const getAdminStudent = (id) => api.get(`/api/admin/students/${id}`);
export const updateAdminStudent = (id, data) => api.patch(`/api/admin/students/${id}`, data);
export const toggleStudentAccess = (id, is_active) =>
  api.patch(`/api/admin/students/${id}/access`, { is_active });
export const deleteAdminStudent = (id) => api.delete(`/api/admin/students/${id}`);
export const resetStudentPassword = (id, new_password) =>
  api.post(`/api/admin/students/${id}/reset-password`, { new_password });
export const markMastery = (studentId, conceptId) =>
  api.post(`/api/admin/students/${studentId}/mastery/${encodeURIComponent(conceptId)}`);
export const unmarkMastery = (studentId, conceptId) =>
  api.delete(`/api/admin/students/${studentId}/mastery/${encodeURIComponent(conceptId)}`);

// ── Sessions ───────────────────────────────────────────────────────────────
export const getAdminSessions = (params) => api.get("/api/admin/sessions", { params });

// ── Analytics ──────────────────────────────────────────────────────────────
export const getAdminAnalytics = (book_slug) =>
  api.get("/api/admin/analytics", { params: book_slug ? { book_slug } : {} });

// ── Admin Users ────────────────────────────────────────────────────────────
export const getAdminUsers = (role = "admin") => api.get("/api/admin/users", { params: { role } });
export const createAdminUser = (data) => api.post("/api/admin/users/create-admin", data);
export const updateUserRole = (id, role) => api.patch(`/api/admin/users/${id}/role`, { role });

// ── Config ─────────────────────────────────────────────────────────────────
export const getAdminConfig = () => api.get("/api/admin/config");
export const updateAdminConfig = (updates) => api.patch("/api/admin/config", { updates });

// ── Chunks ─────────────────────────────────────────────────────────────────
export const updateChunk = (id, data) => api.patch(`/api/admin/chunks/${id}`, data);
export const toggleChunkVisibility = (id, is_hidden) =>
  api.patch(`/api/admin/chunks/${id}/visibility`, { is_hidden });
export const toggleChunkExamGate = (id, exam_disabled) =>
  api.patch(`/api/admin/chunks/${id}/exam-gate`, { exam_disabled });
export const mergeChunks = (chunk_id_a, chunk_id_b) =>
  api.post("/api/admin/chunks/merge", { chunk_id_a, chunk_id_b });
export const splitChunk = (id, split_after_paragraph) =>
  api.post(`/api/admin/chunks/${id}/split`, { split_after_paragraph });
export const reorderChunks = (concept_id, book_slug, chunk_order) =>
  api.put(`/api/admin/concepts/${concept_id}/reorder`, { book_slug, chunk_order });
export const regenerateChunkEmbedding = (id) =>
  api.post(`/api/admin/chunks/${id}/regenerate-embedding`);
export const regenerateConceptEmbeddings = (concept_id, book_slug) =>
  api.post(`/api/admin/concepts/${concept_id}/regenerate-embeddings`, { book_slug });

// ── Sections ───────────────────────────────────────────────────────────────
export const renameSection = (concept_id, book_slug, section, new_name) =>
  api.patch(`/api/admin/sections/${concept_id}/rename`, { book_slug, section, new_name });
export const toggleSectionOptional = (concept_id, book_slug, section, is_optional) =>
  api.patch(`/api/admin/sections/${concept_id}/optional`, { book_slug, section, is_optional });
export const toggleSectionExamGate = (concept_id, book_slug, section, exam_disabled) =>
  api.patch(`/api/admin/sections/${concept_id}/exam-gate`, { book_slug, section, exam_disabled });

// ── Graph ──────────────────────────────────────────────────────────────────
export const getGraphEdges = (book_slug) => api.get(`/api/admin/graph/${book_slug}/edges`);
export const getGraphOverrides = (book_slug) => api.get(`/api/admin/graph/${book_slug}/overrides`);
export const addOrRemoveGraphEdge = (book_slug, action, source_concept, target_concept) =>
  api.post(`/api/admin/graph/${book_slug}/edges`, { action, source_concept, target_concept });
export const deleteGraphOverride = (book_slug, override_id) =>
  api.delete(`/api/admin/graph/${book_slug}/overrides/${override_id}`);
```

---

## Key Decisions Requiring Stakeholder Input

1. **`is_active` column on `students`:** The plan implies soft-delete but doesn't explicitly add this column to migration 011 or 012. Confirm whether to add it in migration 012 or a new migration 013.
2. **Batch embedding regeneration — async or synchronous:** For concepts with 30+ chunks, synchronous response may time out. Confirm whether to use a background task with polling endpoint or accept synchronous with a 60-second timeout.
3. **Password reset notification:** When an admin resets a student's password, should the system send an email? The current auth system has email (OTP verification) infrastructure — this is feasible but out of scope unless explicitly requested.
4. **`MAX_CHUNK_TEXT_LENGTH` value:** Proposed 10,000 characters. Confirm this doesn't truncate any legitimate textbook chunk content.
5. **Admin config hot-reload for `MASTERY_THRESHOLD`:** In-flight sessions use the config value from session start. New sessions pick up the updated value. Confirm this eventual-consistency behaviour is acceptable.
