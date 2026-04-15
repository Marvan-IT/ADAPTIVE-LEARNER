# High-Level Design — Admin Console + Simplified Registration

**Feature slug:** `admin-console`
**Date:** 2026-04-13
**Status:** Approved for implementation

---

## 1. Executive Summary

### Feature Name and Purpose
Comprehensive Admin Console for the ADA platform, together with a simplified student registration flow.

### Business Problem Being Solved
The existing admin console only manages subjects and books (upload, pipeline status, publish). It has no visibility into students, sessions, or learning analytics. Content errors discovered post-publish require a full re-extraction pipeline (expensive). Registration collects "interests" and "tutor style" fields that are never used and increase drop-off.

### Key Stakeholders
- Platform operators (admin users) — need full operational visibility and control
- Content editors — need to fix chunk text/structure post-publish without re-running the pipeline
- New student registrants — benefit from a simpler, faster onboarding form

### Scope

**Included:**
- Part A: Simplified registration — remove `interests` + `preferred_style`, add `age`
- Part B: Admin management — dashboard, student CRUD, session monitoring, analytics, admin user management, manual mastery, system config
- Part C: Content controls — chunk edit/hide/merge/split/reorder, section controls, prerequisite editing, embedding regeneration

**Excluded:**
- Full COPPA/FERPA per-student authorization (out of scope per CLAUDE.md deferred list)
- Multi-region pgvector scaling
- Bulk import/export of student data
- LMS integrations (Canvas, Moodle)

---

## 2. Functional Requirements

### Part A — Simplified Registration (Priority: High)

| ID | Requirement |
|----|-------------|
| A1 | Registration form collects: display name, email, password, age (optional integer) |
| A2 | Registration form no longer collects interests or preferred_style |
| A3 | Existing student rows retain their interests/preferred_style columns (backward compat — M7) |
| A4 | New students receive default values: `interests=[]`, `preferred_style="default"` |

### Part B — Admin Management (Priority: High)

| ID | Requirement |
|----|-------------|
| B1 | Dashboard: platform-level stats — total students, active sessions, mastery completions today, average accuracy |
| B2 | Students: searchable + sortable + paginated table with status filter |
| B3 | Student detail: view full profile, adaptive stats, mastery list, session history, engagement profile |
| B4 | Student edit: update display_name, preferred_language, preferred_style; toggle is_active; soft-delete |
| B5 | Student mastery: manually mark a concept mastered; manually unmark mastery |
| B6 | Sessions: list all sessions with filter by phase, book, date range |
| B7 | Analytics: concept difficulty heatmap, mastery rates by concept, student distribution by accuracy band |
| B8 | Admin users: create new admin user; promote/demote user role; list all admins |
| B9 | System config: read/write key-value config from `admin_config` table (mastery threshold, XP values, model name) |

### Part C — Content Controls (Priority: High)

| ID | Requirement |
|----|-------------|
| C1 | Chunk edit: update heading, text, chunk_type, is_optional, is_hidden, exam_disabled |
| C2 | Chunk hide: toggle is_hidden — hidden chunks are invisible to students but visible in admin |
| C3 | Chunk exam gate: toggle exam_disabled — disables exam/card generation for that chunk |
| C4 | Chunk merge: merge two adjacent chunks in same concept into one; migrate active session chunk_progress (M1) |
| C5 | Chunk split: split one chunk at a paragraph boundary into two; preserve progress in both halves (M1) |
| C6 | Chunk reorder: bulk reorder chunks within a concept by setting new order_index values |
| C7 | Embedding regeneration: regenerate vector embedding for a single chunk or all stale chunks in a concept |
| C8 | Section rename: set admin_section_name on all chunks belonging to a concept section |
| C9 | Section optional: toggle is_optional on all chunks in a section |
| C10 | Section exam gate: toggle exam_disabled on all chunks in a section |
| C11 | Prerequisite edit: add or remove a prerequisite edge in the dependency graph |
| C12 | Prerequisite cycle detection: reject edge additions that would create a cycle |
| C13 | Graph overrides persisted: all edge changes stored in `admin_graph_overrides` table and applied on graph load |

---

## 3. Non-Functional Requirements

| Category | Requirement | Target |
|----------|-------------|--------|
| Performance | Admin dashboard load | < 500 ms (aggregation queries) |
| Performance | Student list (paginated, 50 per page) | < 200 ms |
| Performance | Chunk edit response | < 100 ms |
| Performance | Embedding regeneration (single chunk) | < 3 s (OpenAI embedding call) |
| Scalability | Student table | Up to 50,000 rows with pagination |
| Scalability | Chunk table | Up to 500,000 rows; admin queries add `book_slug` + `concept_id` index |
| Availability | Admin endpoints follow the same SLA as the rest of the platform (no separate infra) |
| Security | All admin endpoints gated by `require_admin` FastAPI dependency (JWT role check) |
| Security | Graph override write operations audit-logged with `created_by` FK to `users.id` |
| Security | Config write operations audit-logged with `updated_by` FK to `users.id` |
| Maintainability | All new constants in `config.py`; no magic strings in business logic |
| Observability | All admin mutation endpoints emit structured log entries at INFO level |
| Backward compat | `interests` + `preferred_style` columns remain in DB and in teaching pipeline fallback |
| Thread safety | Graph cache wrapped in `threading.Lock` for concurrent reload scenarios (M5) |

---

## 4. System Context Diagram

```
┌─────────────────────────────────────────────────────┐
│                   Browser Clients                   │
│                                                     │
│  ┌──────────────┐         ┌────────────────────┐   │
│  │ Student SPA  │         │   Admin SPA (same  │   │
│  │ (React 19)   │         │   React bundle)    │   │
│  └──────┬───────┘         └─────────┬──────────┘   │
└─────────┼───────────────────────────┼───────────────┘
          │  /api/v2                  │  /api/admin
          ▼                           ▼
┌─────────────────────────────────────────────────────┐
│                FastAPI (Uvicorn)                     │
│                                                     │
│  teaching_router  ◄──────────────────────────────  │
│  adaptive_router                                    │
│  admin_router  ◄── NEW endpoints (2c–2i)           │
│  auth_router                                        │
│                                                     │
│  ChunkKnowledgeService                              │
│    ├─ get_chunks_for_concept()  [is_hidden filter]  │
│    ├─ _apply_overrides()        [NEW]               │
│    └─ reload_graph_with_overrides()  [NEW]          │
│                                                     │
│  TeachingService                                    │
│    └─ exam gate check  [exam_disabled aware]        │
└──────────────┬──────────────────────────────────────┘
               │
     ┌─────────┴──────────┐
     │                    │
     ▼                    ▼
┌─────────────┐   ┌──────────────────┐
│ PostgreSQL  │   │ OpenAI API       │
│ (pgvector)  │   │ text-embedding-3 │
│             │   │ -small           │
│ students    │   │ (embedding regen)│
│ sessions    │   └──────────────────┘
│ concept_    │
│  chunks     │   ┌──────────────────┐
│ admin_graph │   │ graph.json       │
│  _overrides │   │ (NetworkX DAG,   │
│ admin_config│   │  per book_slug)  │
└─────────────┘   └──────────────────┘
```

**Data flow — content control:**
1. Admin edits chunk via `PATCH /api/admin/chunks/{id}` → `concept_chunks` row updated in PostgreSQL
2. Student session calls `get_chunks_for_concept()` → query filters `is_hidden=False`, returns updated text
3. Embedding NULL chunks are excluded from semantic search until regenerated via `POST /api/admin/chunks/{id}/regenerate-embedding`

**Data flow — graph override:**
1. Admin adds edge via `POST /api/admin/graph/{slug}/edges` → row inserted in `admin_graph_overrides`
2. `reload_graph_with_overrides()` called → base `graph.json` loaded, overrides applied in memory, `_graph_cache` replaced atomically under `threading.Lock`
3. All subsequent prerequisite checks in teaching flow use the overridden graph

---

## 5. Architectural Style and Patterns

### Selected Style: Layered Monolith with Resource-Based REST

The platform is already a FastAPI monolith. The admin console extends this via a dedicated `admin_router.py` module (already existing for book/subject management). No new services are introduced.

**Rationale:** The team size, deployment constraints (no Kubernetes), and the tight coupling between admin content controls and the teaching pipeline all favour extending the existing router pattern over extracting a separate admin microservice.

**Alternatives considered:**

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| Separate admin microservice | Isolated deployments, separate scaling | Two services to deploy, shared DB still needed, adds ops burden | Rejected |
| Extend existing admin_router | Zero new infra, consistent auth pattern, same DB session | Admin and student traffic share process | Chosen |
| GraphQL admin API | Flexible querying | No existing GQL infrastructure, large migration | Rejected |

### Key Patterns

- **Soft delete / soft hide:** `is_hidden=True` keeps rows in DB; admin sees all, students see filtered subset
- **Overlay pattern for graph:** Base `graph.json` is never mutated; overrides are applied at cache-load time
- **Audit columns:** `created_by` / `updated_by` FKs on mutable admin tables for lightweight audit trail
- **Config as data:** `admin_config` key-value table avoids code deploys for threshold changes

---

## 6. Technology Stack

All new work uses the existing stack. No new dependencies are introduced.

| Concern | Technology | Rationale |
|---------|------------|-----------|
| Admin API endpoints | FastAPI (existing `admin_router.py`) | Consistent with all other endpoints |
| Database | PostgreSQL 15 + SQLAlchemy 2.0 async | Existing; new columns + tables via Alembic |
| Graph manipulation | NetworkX 3 (already installed) | `nx.has_path()` for cycle detection |
| Embedding regeneration | OpenAI `text-embedding-3-small` (existing `AsyncOpenAI` client) | Same model used during pipeline extraction |
| Admin frontend pages | React 19 + React Router DOM 7 + Tailwind CSS 4 | Existing frontend stack |
| State management | React Context + local component state (no new Zustand store needed) | Admin pages are independent navigation destinations; no cross-page reactive state |
| Auth gating | `require_admin` FastAPI dependency (existing `auth/dependencies.py`) | Already used in current admin endpoints |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-1: Graph overrides stored in DB, applied in memory at load time

**Decision:** `admin_graph_overrides` table stores the delta (add/remove edges). `reload_graph_with_overrides()` re-loads `graph.json` and applies all stored overrides, replacing the in-memory `_graph_cache` entry.

**Options considered:**
- Mutate `graph.json` on disk → simple but loses the base graph; hard to undo
- Store full serialized graph in DB → expensive for large graphs; DRY problem with `graph.json`
- Overlay in memory (chosen) → base file unchanged; overrides easily reversed by deleting the row; cache invalidation is a single function call

**Trade-off:** Graph cache is per-process; multi-worker deployments need a shared reload trigger (acceptable — current deployment is single-process Uvicorn with `--reload`).

### ADR-2: is_hidden filtered at query level, not application level

**Decision:** `get_chunks_for_concept()` in `chunk_knowledge_service.py` adds `.where(ConceptChunk.is_hidden == False)` for student-facing queries. Admin queries call a separate `get_all_chunks_for_concept()` that omits this filter.

**Options considered:**
- Filter in every caller → risk of caller forgetting the filter
- Filter once in service layer (chosen) → single enforcement point; admin gets separate method

### ADR-3: Merge/split migrates chunk_progress JSONB in-place

**Decision:** Merge and split operations iterate over all `teaching_sessions` with non-null `chunk_progress` for the affected `concept_id` and rewrite the JSONB key references atomically within the same transaction.

**Trade-off:** Slightly expensive for concepts with many active sessions. Acceptable because admin merges are infrequent and session counts per concept are bounded (typically < 20 active at any time).

### ADR-4: Registration fields removed from form, not from DB

**Decision:** `interests` and `preferred_style` columns remain in PostgreSQL and in the teaching pipeline fallback logic. The registration endpoint and frontend form simply stop collecting them.

**Rationale (M7):** Existing students have non-null values in these columns. Removing the columns would break backward compatibility and require a migration with data loss. The teaching pipeline already has fallback behaviour for empty arrays.

### ADR-5: Admin config read at request time, not startup

**Decision:** `admin_config` values (mastery threshold, XP per card, etc.) are queried from the DB at each request that needs them, rather than being cached at startup.

**Trade-off:** Slight per-request overhead (~1 ms extra DB round-trip for config reads). This is acceptable and avoids cache-invalidation complexity. High-frequency hot paths (card generation) continue to use `config.py` constants as defaults, with admin config applied as overrides.

---

## 8. Risks and Mitigations

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| M1 | Merge/split breaks active session `chunk_progress` UUIDs | Medium | High | Migrate JSONB in-place within the same transaction; return `active_sessions_affected` count in response |
| M2 | Merge/split leaves NULL embeddings → excluded from semantic search | High (certain) | Medium | Set `embedding=NULL`, return `embedding_stale: true` flag; admin must regenerate before search is fully effective |
| M3 | Hide chunk mid-session | Low | Low | `is_hidden` filter only applied to new `get_chunks_for_concept()` calls; active cached chunk lists are unaffected until next session |
| M4 | `is_optional` admin value conflicts with extraction heuristics | Low | Low | Admin DB value is authoritative; pipeline sets initial value; admin override wins |
| M5 | Graph cache race condition under concurrent requests | Low (single-process) | Medium | `threading.Lock` wraps `_graph_cache` reads and writes; atomic object replacement |
| M6 | Section rename produces inconsistent display if only some chunks updated | Medium | Low | `admin_section_name` set on ALL chunks sharing the same `section` + `concept_id` in a single query |
| M7 | Registration removal breaks existing students | None (by design) | High | Keep columns; fill with defaults for new students |
| M8 | Merge attempted across concepts | Low | High | Server validates `concept_id` equality before merge; returns HTTP 422 |
| R1 | Embedding regeneration rate-limited by OpenAI | Medium | Low | Batch regeneration runs chunks sequentially with 100 ms delay; single-chunk call is instant |
| R2 | Admin config write races with in-flight sessions | Low | Low | Sessions read config at start; in-flight sessions complete with the value they started with |
| R3 | Large `chunk_progress` JSONB migration times out | Low | Medium | Use `SELECT ... FOR UPDATE` + batch in groups of 50 sessions if needed |

---

## Key Decisions Requiring Stakeholder Input

1. **Age field validation range:** Should `age` have a min/max (e.g., 5–120)? Currently nullable with no range constraint.
2. **Soft-delete vs. hard-delete for students:** The plan specifies soft-delete (toggle `is_active`). Does student data need permanent deletion for GDPR right-to-erasure? If yes, a hard-delete with cascade is required alongside a data export feature.
3. **Admin config hot keys:** Which specific config keys should be editable from the admin console? (e.g., `MASTERY_THRESHOLD`, `XP_PER_CORRECT_MCQ`, `OPENAI_MODEL`). A fixed allowlist prevents accidental breakage.
4. **Embedding regeneration background vs. synchronous:** Single-chunk regeneration can be synchronous (< 3 s). Batch regeneration for a full concept (potentially 30+ chunks) should likely be async with a status endpoint. Confirm acceptable UX.
5. **Multi-worker deployment:** If Uvicorn is ever run with multiple workers, the in-memory graph cache and graph override reload will diverge between processes. Confirm whether a Redis-based cache invalidation signal is required before launch.
