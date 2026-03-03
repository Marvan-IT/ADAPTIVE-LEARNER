# High-Level Design: Platform Hardening

**Feature slug:** `platform-hardening`
**Date:** 2026-03-01
**Author:** Solution Architect

---

## 1. Executive Summary

### Feature Name and Purpose

Platform Hardening is a five-stream operational release that closes the most urgent security, performance, and reliability gaps in the ADA platform before it handles real student traffic. Each stream is independently deployable but ships together for operational efficiency.

### Business Problem Being Solved

ADA currently operates with no authentication on its API, no protection against abusive request patterns, no persistence of gamification state, unbounded database queries that will fail under load, and an image pipeline that injects corrupted or poorly-described visual content into LLM prompts. Any of these gaps can individually cause data loss, cost overruns, degraded learning quality, or complete service failure.

Concretely:

- **No API auth** — any party who knows the server address can read all student data, exhaust the OpenAI quota, or delete records. This is a pre-launch blocker.
- **No rate limiting** — a single misbehaving client or bot can saturate GPT-4o throughput (at ~$0.01–0.03 per card call), causing service unavailability and unbounded cost.
- **XP/Streak not persisted** — gamification state lives only in Zustand memory. Browser refresh or device switch silently resets progress, breaking the motivational loop designed in the AI-Native Learning OS.
- **N+1 and unbounded queries** — `list_students()` fires one extra query per student; `load_student_history()` has no row cap. Both will cause latency spikes and potential OOM at scale.
- **Image pipeline defects** — corrupted or all-black images pass into ChromaDB and LLM prompts unchecked. UNMAPPED images (no concept assignment) are silently dropped, losing educational content. Vision descriptions use a structured format that fragments the LLM's natural-language generation.

### Key Stakeholders

- **Platform/Product** — approve API key distribution strategy, XP schema, rate limit thresholds
- **Backend Engineering** — implement Streams 1, 2, 3, 4, 5 (backend portions)
- **Frontend Engineering** — implement Streams 1 and 3 (frontend portions)
- **DevOps** — Alembic migration for `students.xp`, `students.streak`; new DB indices; connection pool config
- **Operations** — rotate and distribute `API_SECRET_KEY` to all clients at launch

### Scope

**Included:**

- `X-API-Key` header middleware on all FastAPI routes except health/docs
- `slowapi` rate limiting: general (60/min), LLM-heavy (10/min), list/get (120/min)
- `students.xp` and `students.streak` columns + `PATCH /api/v2/students/{id}/progress` endpoint
- Frontend XP/streak load-on-start + sync-after-card-complete
- N+1 fix in `list_students()` via JOIN query
- `.limit(200)` guard on `load_student_history()`
- Connection pool tuning: `pool_size=20`, `max_overflow=80`
- 3 new DB indices: `teaching_sessions(student_id)`, `conversation_messages(session_id)`, `student_mastery(student_id, concept_id)`
- Pillow validation at image extraction time (reject corrupted/black images)
- UNMAPPED proximity resolver: assign to nearest concept within ±5 pages
- Vision annotator prompt replacement: single natural-language paragraph
- Vision description injection into presentation, Socratic, and card LLM prompts
- Frontend: remove "What it shows:" / "Why it helps:" label prefixes; render description as italic paragraph

**Excluded:**

- OAuth2, PKCE, or JWT-based user authentication (out of scope — this is a single-tenant platform key, not per-user auth)
- User registration or login flows
- CDN or object-storage migration for images
- Rate limit persistence across restarts (in-memory only, acceptable for this phase)
- Multi-tenant API key management

---

## 2. Functional Requirements

### Stream 1 — API Secret Key Authentication

- **FR-1.1** All API endpoints must reject requests that do not include a valid `X-API-Key` header with HTTP 401.
- **FR-1.2** The valid key is read from `API_SECRET_KEY` in `backend/.env` at startup; the app must fail fast if the variable is absent.
- **FR-1.3** Health check (`/health`), OpenAPI docs (`/docs`, `/openapi.json`, `/redoc`) must remain publicly accessible.
- **FR-1.4** The frontend must read `VITE_API_SECRET_KEY` from `frontend/.env` and attach it as `X-API-Key` on every Axios request via a global interceptor.
- **FR-1.5** A missing or incorrect key must return `{"detail": "Unauthorized"}` with status 401 — no other information disclosed.

### Stream 2 — Rate Limiting

- **FR-2.1** All endpoints are subject to a default limit of 60 requests/minute per client IP.
- **FR-2.2** LLM-heavy endpoints (`POST /api/v3/students/{id}/lessons`, `POST /api/v2/sessions`, `POST /api/v2/sessions/{id}/respond`, `POST /api/v2/sessions/{id}/complete-card`) are subject to a stricter 10 requests/minute limit.
- **FR-2.3** Read/list endpoints (`GET /api/v2/students`, `GET /api/v2/students/{id}`, `GET /api/v1/concepts`, `GET /api/v2/students/{id}/card-history`) are subject to a relaxed 120 requests/minute limit.
- **FR-2.4** Rate limit violations return HTTP 429 with a `Retry-After` header.
- **FR-2.5** Rate limit state is in-memory (per-process); reset on restart is acceptable.

### Stream 3 — XP/Streak Persistence

- **FR-3.1** The `students` table gains two new columns: `xp INTEGER NOT NULL DEFAULT 0` and `streak INTEGER NOT NULL DEFAULT 0`.
- **FR-3.2** A new endpoint `PATCH /api/v2/students/{id}/progress` accepts `{"xp_delta": int, "streak": int}` and atomically increments `xp` by the delta and sets `streak` to the new value.
- **FR-3.3** `GET /api/v2/students/{id}` must return `xp` and `streak` in its response schema.
- **FR-3.4** The frontend Zustand store must initialize `xp` and `streak` from the student record on app start.
- **FR-3.5** After each successful card completion the frontend must call `PATCH /api/v2/students/{id}/progress` to sync state.

### Stream 4 — Query Performance

- **FR-4.1** `list_students()` must return mastered-concept counts in a single query using a LEFT JOIN or subquery — no per-student follow-up queries.
- **FR-4.2** `load_student_history()` must apply `.limit(200)` before execution.
- **FR-4.3** The database connection pool must be configured with `pool_size=20` and `max_overflow=80`.
- **FR-4.4** Three indices must be created via Alembic migration: `ix_teaching_sessions_student_id`, `ix_conversation_messages_session_id`, `ix_student_mastery_student_concept` (composite on `student_id, concept_id`).

### Stream 5 — Image Pipeline

- **FR-5.1** At extraction time, each extracted image must be opened with Pillow; images that raise an exception or whose pixel mean is below a configurable `IMAGE_BLACK_THRESHOLD` must be logged and skipped.
- **FR-5.2** After concept assignment, images tagged `UNMAPPED` must be matched to the nearest concept within ±5 pages by scanning the image index; if no concept falls within range the image is discarded.
- **FR-5.3** The vision annotator must use an updated prompt that produces a single conversational paragraph describing the image (no labelled sections).
- **FR-5.4** Vision descriptions must be interpolated into the presentation LLM prompt, the Socratic check prompt, and the card generation prompt when images are associated with the target concept.
- **FR-5.5** The frontend image display must render the vision description as a single `<em>` paragraph; the "What it shows:" and "Why it helps:" heading prefixes must be removed.

---

## 3. Non-Functional Requirements

| Category | Target |
|---|---|
| Auth overhead | < 1 ms per request (middleware string compare) |
| Rate limit overhead | < 2 ms per request (in-memory counter lookup) |
| `list_students()` latency (p99) | < 200 ms for up to 500 students |
| `load_student_history()` latency (p99) | < 300 ms with `.limit(200)` applied |
| DB connection pool | Sustain 20 concurrent sessions; burst to 100 |
| XP sync latency | `PATCH /progress` completes < 100 ms (simple UPDATE, no LLM) |
| Image validation | < 50 ms per image (Pillow open + mean check) |
| Vision injection | Zero added LLM calls; descriptions already stored in ChromaDB metadata |
| API key rotation | New key takes effect on next deploy (restart required — acceptable) |
| Rate limit accuracy | Best-effort (in-memory, per-process); exact enforcement not required |
| Availability | No downtime change — all streams are additive to existing routes |

---

## 4. System Context Diagram

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                   ADA Platform                          │
                    │                                                         │
  Student Browser ──┤──► React 19 SPA                                        │
  (VITE_API_SECRET  │     • Axios interceptor adds X-API-Key header           │
   _KEY in .env)    │     • Zustand loads xp/streak from GET /students/{id}   │
                    │     • Syncs xp/streak via PATCH /students/{id}/progress │
                    │              │                                           │
                    │              ▼                                           │
                    │   ┌─────────────────────┐                               │
                    │   │   FastAPI Backend    │                               │
                    │   │                     │                               │
                    │   │ [1] APIKeyMiddleware │ ← checks X-API-Key           │
                    │   │     (skip: /health,  │   returns 401 if wrong       │
                    │   │      /docs, /redoc,  │                               │
                    │   │      /openapi.json)  │                               │
                    │   │                     │                               │
                    │   │ [2] slowapi Limiter  │ ← per-IP counters            │
                    │   │     60/min general   │   429 + Retry-After          │
                    │   │     10/min LLM heavy │                               │
                    │   │    120/min read/list │                               │
                    │   │                     │                               │
                    │   │ [3] API Routers      │                               │
                    │   │     v1 / v2 / v3     │                               │
                    │   └────────┬────────────┘                               │
                    │            │                                             │
                    │     ┌──────┴──────────────────────────┐                 │
                    │     │                                 │                 │
                    │     ▼                                 ▼                 │
                    │ ┌───────────────┐          ┌──────────────────────┐     │
                    │ │  PostgreSQL   │          │  OpenAI GPT-4o       │     │
                    │ │  (pool 20/80) │          │  (rate-limited at    │     │
                    │ │  + 3 new idx  │          │   10/min per IP)     │     │
                    │ │  xp, streak   │          └──────────────────────┘     │
                    │ │  columns      │                                       │
                    │ └───────────────┘          ┌──────────────────────┐     │
                    │                            │  ChromaDB            │     │
                    │                            │  (vision descriptions│     │
                    │                            │   in metadata)       │     │
                    │                            └──────────────────────┘     │
                    │                                                         │
                    │  Image Extraction Pipeline (offline)                    │
                    │  PDF → PyMuPDF → Pillow validation → Mathpix OCR        │
                    │       → UNMAPPED resolver → vision annotator            │
                    │       → image_index.json + ChromaDB metadata            │
                    └─────────────────────────────────────────────────────────┘
```

---

## 5. Architectural Style and Patterns

**Selected style:** Layered monolith with middleware chain for cross-cutting concerns.

ADA is currently a well-structured monolith. The cross-cutting concerns introduced by this release (auth, rate limiting) are best handled as ASGI middleware, which keeps them orthogonal to business logic and composable in a defined order: authentication fires before rate limiting, rate limiting fires before routing.

**Patterns used:**

- **Middleware chain** (Starlette/FastAPI) — `APIKeyMiddleware` + `SlowAPI` limiter sit at the ASGI layer; zero changes to route handlers.
- **Global Axios interceptor** — a single request interceptor in the frontend's Axios instance attaches the key to every call, avoiding per-call changes across 10+ API wrapper files.
- **Atomic increment** — `UPDATE students SET xp = xp + :delta, streak = :streak WHERE id = :id` executed in a single statement; no read-modify-write race.
- **Proximity resolver** — page-sorted scan of `image_index.json` at extraction time (offline, not hot path); assigns UNMAPPED images to nearest concept by absolute page-distance.

**Alternatives considered:**

| Option | Rejected Because |
|---|---|
| JWT per-user auth | Over-engineered for single-tenant platform; requires login flow, token refresh, session management. Not in scope. |
| Redis-backed rate limiting | Requires Redis deploy; in-memory is sufficient for single-process single-server phase. Can be upgraded when horizontal scaling is needed. |
| FastAPI dependency for auth | Middleware is preferred — dependency injection requires adding `Depends()` to every route individually; middleware is one central location. |
| Eager image re-validation at serve time | Images are served as static files; re-validation on every request is wasteful. Validation at extraction time is the correct gate. |

---

## 6. Technology Stack

All additions are minimal and aligned with the existing stack.

| Concern | Technology | Rationale |
|---|---|---|
| Rate limiting | `slowapi` 0.1.x (wraps `limits`) | De-facto FastAPI rate limiting library; decorator-based, integrates cleanly with Starlette middleware |
| Image validation | `Pillow` (already in requirements via PyMuPDF) | Standard image library; pixel mean check is O(1) via `.getbbox()` heuristic |
| Auth middleware | Custom Starlette `BaseHTTPMiddleware` | 10-line implementation; no new dependency |
| XP persistence | Existing PostgreSQL + SQLAlchemy | New columns on existing `students` table; no new storage system |
| Frontend key injection | Existing Axios interceptor pattern | `frontend/src/api/` already has a configured Axios instance |

No new npm packages or pip packages beyond `slowapi` are required.

---

## 7. Key Architectural Decisions (ADRs)

### ADR-PH-01: API Key over JWT

**Decision:** Protect all API endpoints with a single shared `X-API-Key` header rather than per-user JWT tokens.

**Options considered:**
1. Shared API key (`X-API-Key` header)
2. JWT with per-student tokens issued at login
3. No authentication (status quo)

**Chosen:** Option 1 — Shared API key.

**Rationale:** ADA is a single-tenant platform delivered as a managed web app. There is no multi-tenant isolation requirement at the API layer. Per-user JWT auth requires a login page, a token issuance endpoint, token refresh logic, password management or OAuth2 provider integration — all of which are out of scope and would add weeks of engineering. The shared key closes the primary risk (unauthenticated public access) with a one-day implementation. The key can be rotated by updating `.env` and redeploying. When ADA moves to multi-tenant SaaS, this decision is revisited in favour of OAuth2/PKCE.

**Trade-offs:** The shared key does not provide per-user audit trails or revocation granularity. Acceptable for current deployment model.

---

### ADR-PH-02: In-Memory Rate Limiting (no Redis)

**Decision:** Use `slowapi` with in-memory storage for rate limit counters.

**Rationale:** ADA runs as a single Uvicorn process. In-memory counters are accurate within that process boundary. Adding Redis for rate limit persistence would require infra provisioning, connection management, and failure handling — disproportionate to the risk being mitigated. If ADA scales to multiple workers, Redis backend is a one-line config change in `slowapi`.

**Trade-off:** Counters reset on process restart. Workers running in multi-process mode (e.g., `--workers 4`) will not share counters. Acceptable until horizontal scaling is required.

---

### ADR-PH-03: Atomic XP Increment (no read-modify-write)

**Decision:** `PATCH /api/v2/students/{id}/progress` uses `UPDATE students SET xp = xp + :delta` rather than fetching the row and writing back.

**Rationale:** Students may have multiple browser tabs open or rapid card completions. A read-modify-write cycle creates a race condition where concurrent requests can lose XP increments. The atomic SQL increment eliminates this without requiring application-level locking or optimistic concurrency control.

---

### ADR-PH-04: Vision Description as Single Prose Paragraph

**Decision:** Replace the structured "What it shows: / Why it helps:" vision prompt format with a prompt that produces a single conversational paragraph.

**Rationale:** Structured labels in vision descriptions disrupt the LLM's narrative flow when those descriptions are interpolated into explanation prompts. The model treats the labels as formatting instructions, producing stilted output. A single prose paragraph blends naturally into the surrounding explanation context. The frontend label removal is a matching cleanup — the raw description is the display value.

---

## 8. Risks and Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-01 | `API_SECRET_KEY` committed to version control by mistake | Medium | High | Add `API_SECRET_KEY` to `.gitignore` check; fail fast at startup if absent; document in `.env.example` |
| R-02 | Legitimate high-frequency clients (automated test suite) hit rate limits | Medium | Medium | Test suite sets a known IP or uses a bypass header; document in `CLAUDE.md`; consider `RATE_LIMIT_BYPASS_KEY` env var |
| R-03 | XP sync fails silently on network error after card completion | Medium | Low | Frontend catches error, retains Zustand state, retries on next successful interaction; log warning |
| R-04 | Alembic migration for `xp`/`streak` columns runs against live DB with active sessions | Low | Medium | Migration is `NOT NULL DEFAULT 0` — instant backfill; no table lock beyond milliseconds in PostgreSQL 15 |
| R-05 | Pillow validation rejects valid images (false positive on dark illustrations) | Low | Medium | `IMAGE_BLACK_THRESHOLD` is configurable in `config.py`; default set conservatively (mean < 5); re-run pipeline to recover |
| R-06 | UNMAPPED proximity resolver misassigns an image to the wrong concept | Low | Low | Assignment is logged with page distance; images are supplementary (not primary content); worst case = irrelevant image shown |
| R-07 | Vision description injection increases prompt token count → higher cost | Medium | Low | Descriptions are capped at ~150 tokens by prompt instruction; existing `max_tokens` caps on LLM calls bound output; net cost increase < 5% |
| R-08 | Rate limit middleware incompatible with future multi-worker deploy | High | Medium | `slowapi` supports Redis backend as a one-line swap; document in CLAUDE.md technical debt |
| R-09 | Connection pool overflow under burst load with `max_overflow=80` | Low | Medium | `max_overflow=80` allows up to 100 total connections; PostgreSQL default `max_connections=100` — set PostgreSQL `max_connections=150` in infra config simultaneously |

---

## Key Decisions Requiring Stakeholder Input

1. **Rate limit thresholds** — The proposed limits (60/10/120 per minute per IP) are reasonable defaults. Confirm these do not impact planned automated integration tests or batch operations.
2. **API key distribution** — Confirm that a single shared key is acceptable for the current deployment model, and that a secure channel exists for distributing it to all frontend deployments (e.g., CI secret, not email).
3. **PostgreSQL `max_connections`** — With `pool_size=20, max_overflow=80`, the pool can open up to 100 connections. If the PostgreSQL instance has `max_connections=100` (default), there is no headroom for `psql` admin access or migration connections. Confirm infra can set `max_connections=150` before this ships.
4. **`IMAGE_BLACK_THRESHOLD` default** — Confirm that a Pillow pixel mean threshold of 5 (out of 255) is appropriate for the textbook image corpus. Dark diagrams with genuine content could be affected.
5. **XP delta semantics** — The `xp_delta` field allows negative values (e.g., for corrections). Confirm whether the platform intends XP to be monotonically increasing or can decrease.
