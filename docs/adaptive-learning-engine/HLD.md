# High-Level Design: Adaptive Learning Generation Engine

**Feature slug:** `adaptive-learning-engine`
**Version:** 1.0.0
**Date:** 2026-02-25
**Author:** Solution Architect Agent

---

## 1. Executive Summary

### Feature Name and Purpose
The **Adaptive Learning Generation Engine** transforms raw behavioral telemetry from student sessions into dynamically generated lesson content that is calibrated to each student's demonstrated learning pace, comprehension level, and engagement state.

### Business Problem Being Solved
The existing ADA platform delivers a uniform presentation experience: every student studying "Multiply and Divide Fractions" receives the same explanation depth, the same card count, and the same analogy density regardless of whether they breeezed through the prerequisite or took six attempts and asked for seven hints. This one-size-fits-all delivery reduces both learning efficiency and student retention. Students who are struggling become overwhelmed; students who are strong become bored.

The Adaptive Learning Engine closes this gap by:
1. Classifying each student's behavioral fingerprint (speed, comprehension, engagement) from measurable analytics signals.
2. Deriving a generation profile that controls every tunable dimension of LLM output.
3. Producing a fully bespoke `AdaptiveLesson` — including optional remediation cards for struggling students — in a single API call.

### Key Stakeholders
- **Product Team** — owns the pedagogical strategy and remediation policy decisions.
- **Backend Engineering** — implements the engine and API endpoint.
- **Frontend Engineering** — consumes `AdaptiveLesson` to render the adaptive UI.
- **Data / Analytics** — provides the PostHog-style `AnalyticsSummary` payload.
- **Students** — ultimate beneficiaries of calibrated content.

### Scope

**Included:**
- `AnalyticsSummary` ingestion and `LearningProfile` classification (deterministic, no ML).
- `GenerationProfile` derivation from the classified profile.
- Prerequisite-aware remediation card injection (graph traversal + mastery DB lookup).
- LLM-powered `AdaptiveLesson` generation (concept explanation + micro-cards).
- `POST /api/v3/adaptive/lesson` REST endpoint.
- Unit tests for all deterministic logic; integration test for the full engine pipeline.

**Excluded:**
- Real-time streaming of lesson content (synchronous JSON response only, v1).
- Storing generated lessons in the database (lessons are generated on demand; caching is out of scope for v1).
- Analytics ingestion infrastructure (PostHog → backend pipeline). The caller supplies the pre-computed `AnalyticsSummary` in the request body.
- Multi-language lesson generation (adaptive engine uses the student's `preferred_language` from the DB; the prompt will respect it, but translation quality is not independently validated in v1).
- A/B testing framework for generation profiles.

---

## 2. Functional Requirements

| ID   | Priority | Requirement |
|------|----------|-------------|
| FR-1 | Must     | Accept an `AnalyticsSummary` payload (student_id, concept_id, behavioral metrics) and return an `AdaptiveLesson`. |
| FR-2 | Must     | Classify the student into a deterministic `LearningProfile` (speed × comprehension × engagement) using the exact threshold rules specified. |
| FR-3 | Must     | Map the `LearningProfile` to a `GenerationProfile` that controls all LLM generation parameters. |
| FR-4 | Must     | Retrieve concept knowledge-base text via the existing `KnowledgeService.get_concept_detail()`. |
| FR-5 | Must     | Load the student's mastered concepts from `student_mastery` PostgreSQL table. |
| FR-6 | Must     | When the student's profile is STRUGGLING and an unmastered direct prerequisite exists in the NetworkX graph, prepend three `[Review]` remediation cards (difficulty 1–2) before the main lesson cards. |
| FR-7 | Must     | Build a structured LLM prompt that encodes all `GenerationProfile` parameters and returns a valid `AdaptiveLesson` JSON object. |
| FR-8 | Must     | Parse and validate the LLM response against the `AdaptiveLesson` Pydantic schema; retry up to 3 times on malformed JSON. |
| FR-9 | Should   | Expose a `recommended_next_step` field in the `LearningProfile` (CONTINUE / REMEDIATE_PREREQ / ADD_PRACTICE / CHALLENGE). |
| FR-10| Should   | Return a `confidence_score` (0.0–1.0) derived from quiz_score, error_rate, and hint usage. |
| FR-11| Could    | Include a `fun_element` string on cards when `fun_level > 0.5` (emoji-free by default per `emoji_policy`). |

---

## 3. Non-Functional Requirements

### Performance
- **P95 end-to-end latency:** ≤ 8 seconds for a full lesson generation call (inclusive of DB lookup, graph traversal, and LLM round-trip).
- **LLM token budget:** Target ≤ 3,500 prompt tokens + ≤ 2,500 completion tokens per request. Prompt builder must truncate concept text to 1,200 characters if needed.

### Scalability
- **Concurrent requests:** The endpoint must handle 50 concurrent adaptive lesson requests without degradation (consistent with the existing FastAPI + Uvicorn deployment baseline).
- **LLM throughput:** The engine is stateless per request; horizontal scaling of the API server directly scales throughput. No shared mutable state is introduced.

### Reliability
- **LLM retry:** 3 attempts with exponential back-off (2s, 4s) before returning HTTP 502.
- **JSON parsing resilience:** If the LLM returns truncated JSON, the salvage algorithm (already established in `TeachingService`) is applied before declaring failure.
- **Graceful degradation:** If the mastery DB query fails, the engine falls back to treating no concepts as mastered (worst-case: unnecessary remediation cards, not a hard failure).

### Determinism and Testability
- `LearningProfile` classification must be 100% deterministic given the same `AnalyticsSummary` inputs. No randomness is introduced at the classification or profile-mapping stage.
- `GenerationProfile` derivation must be a pure function of `LearningProfile`. Unit tests must be able to assert exact output for any input without mocking.

### Cost Efficiency
- The engine uses `gpt-4o` for lesson generation (quality required) and `gpt-4o-mini` is NOT used here because structured JSON with 14 cards requires the larger model's instruction following.
- Token usage is constrained by the `GenerationProfile.card_count` and `max_paragraph_lines` parameters — the prompt explicitly encodes these limits.

### Security
- The `student_id` in the request must be validated as a UUID; the corresponding student must exist in the DB (HTTP 404 if not).
- The `concept_id` must be present in the knowledge base (HTTP 404 if not found in `KnowledgeService`).
- No raw LLM output is returned without Pydantic validation; all fields are type-checked before being serialized to the caller.

### Observability
- Structured log entry at INFO level for every lesson generated: student_id, concept_id, profile summary, token usage, latency.
- Log at WARNING level when LLM JSON parsing fails and a retry is triggered.
- Log at ERROR level when all 3 LLM attempts fail.

---

## 4. System Context Diagram

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                        ADA Backend (FastAPI)                    │
  │                                                                 │
  │  ┌──────────────────────────────────────────────────────────┐   │
  │  │           POST /api/v3/adaptive/lesson                   │   │
  │  │                  adaptive_router.py                      │   │
  │  └──────────────────────┬───────────────────────────────────┘   │
  │                         │                                       │
  │                         ▼                                       │
  │  ┌────────────────────────────────────────────────────────┐     │
  │  │              AdaptiveEngine (adaptive_engine.py)        │     │
  │  │                                                        │     │
  │  │  ┌─────────────────┐   ┌──────────────────────────┐   │     │
  │  │  │ profile_builder │   │  generation_profile.py   │   │     │
  │  │  │  (deterministic)│──▶│  (pure mapping function) │   │     │
  │  │  └─────────────────┘   └──────────────────────────┘   │     │
  │  │                                    │                   │     │
  │  │  ┌─────────────────┐               │                   │     │
  │  │  │ remediation.py  │               │                   │     │
  │  │  │ (graph + DB)    │               ▼                   │     │
  │  │  └─────────────────┘   ┌──────────────────────────┐   │     │
  │  │         │              │   prompt_builder.py       │   │     │
  │  │         └─────────────▶│  (assembles LLM prompt)   │   │     │
  │  │                        └──────────────┬───────────┘   │     │
  │  └───────────────────────────────────────┼───────────────┘     │
  │                                          │                       │
  │          ┌───────────────────────────────▼──────┐               │
  │          │  External: OpenAI API (gpt-4o)        │               │
  │          └───────────────────────────────────────┘               │
  │                                                                 │
  │  ┌──────────────────┐   ┌───────────────────────┐               │
  │  │  KnowledgeService│   │  PostgreSQL            │               │
  │  │  (ChromaDB +     │   │  student_mastery table │               │
  │  │   NetworkX DAG)  │   │  (SQLAlchemy async)    │               │
  │  └──────────────────┘   └───────────────────────┘               │
  └─────────────────────────────────────────────────────────────────┘

  External callers:
  ┌──────────────────────────────┐
  │  Frontend SPA (React 19)     │──── POST /api/v3/adaptive/lesson ──▶
  │  PostHog Analytics Pipeline  │     (AnalyticsSummaryRequest)
  └──────────────────────────────┘
```

---

## 5. Architectural Style and Patterns

### Selected Style: Layered Stateless Service Within the Existing FastAPI Monolith

The Adaptive Learning Engine is implemented as a new **vertical slice** within the existing FastAPI backend, following the same structural convention as the teaching loop (`backend/src/api/teaching_*.py` → `backend/src/adaptive/`).

**Justification:**
- The existing system is a FastAPI monolith with a clean service-layer pattern. Introducing a standalone microservice would add infrastructure overhead (service discovery, inter-process communication, deployment complexity) that is not justified at the current scale.
- All required dependencies (KnowledgeService, DB session, OpenAI client) are already in-process. A service extraction can be deferred to when the engine needs independent scaling.
- The vertical slice pattern keeps all adaptive logic co-located and independently testable without modifying existing modules.

**Patterns Used:**
- **Strategy pattern (implicit):** `GenerationProfile` acts as a strategy object that parameterizes the prompt builder and ultimately the LLM output style.
- **Pipeline pattern:** The engine orchestrates a deterministic sequence of steps: classify → map → retrieve → build-prompt → call-LLM → validate → return.
- **Pure function classification:** `LearningProfile` and `GenerationProfile` derivation are pure functions with no side effects, enabling exhaustive unit testing without mocking.
- **Retry with back-off:** Follows the pattern already established in `TeachingService._chat()`.

**Alternatives Considered:**

| Alternative | Why Rejected |
|-------------|--------------|
| Separate FastAPI microservice | Unjustified infrastructure overhead at current scale; same DB and ChromaDB instance required regardless |
| ML-based profile classification (e.g., scikit-learn) | Adds model training, versioning, and drift concerns; deterministic rule-based classification is auditable, debuggable, and requires no training data |
| Streaming response (SSE) | Materially complicates the JSON schema contract and frontend consumption; defer to v2 |
| Caching generated lessons in DB | Generated lessons are tightly bound to the analytics snapshot; stale cache invalidation is non-trivial; adds schema complexity without clear latency benefit given LLM is the bottleneck |

---

## 6. Technology Stack

| Concern | Technology | Rationale |
|---------|-----------|-----------|
| API Framework | FastAPI 0.128+ (async) | Existing project standard; `async def` handlers with `AsyncSession` DB access |
| LLM | OpenAI `gpt-4o` | Existing project standard; required for reliable structured JSON output with card_count up to 14 |
| LLM Client | `openai` Python SDK (AsyncOpenAI) | Existing project standard |
| Data Validation | Pydantic v2 | Existing project standard; all schemas defined in `schemas.py` files |
| Database | PostgreSQL 15 via SQLAlchemy 2.0 async + asyncpg | Existing project standard; `student_mastery` table already exists |
| Graph Engine | NetworkX 3+ | Existing project standard; prerequisite graph already loaded in `KnowledgeService` |
| Vector Store | ChromaDB 0.5 | Existing project standard; `KnowledgeService.get_concept_detail()` already abstracts it |
| Testing | pytest + pytest-asyncio | Existing project standard; aligns with backend test conventions |
| Logging | Python `logging` module | Existing project standard; structured format aligned with CLAUDE.md convention |

No new dependencies are introduced. The only `requirements.txt` change is adding `pytest` and `pytest-asyncio` if they are not already present.

---

## 7. Key Architectural Decisions (ADRs)

### ADR-1: Deterministic Rule-Based Classification Over ML

**Decision:** Use explicit if/elif threshold rules for `LearningProfile` classification.

**Options Considered:**
1. Rule-based classification (chosen)
2. Logistic regression or gradient-boosted classifier
3. LLM-based classification (pass analytics summary to GPT and ask it to classify)

**Rationale:** Rule-based classification is fully deterministic, requires zero training data, is auditable by product managers, and can be unit tested exhaustively. Option 2 requires labeled training data and model governance. Option 3 introduces non-determinism and adds a second LLM call (cost and latency penalty).

**Trade-off:** The threshold values (e.g., STRUGGLING if error_rate ≥ 0.5) are heuristics set by the product team. If they prove suboptimal, updating them is a 1-line code change with clear auditability.

---

### ADR-2: Single LLM Call Per Lesson Generation

**Decision:** Generate the entire `AdaptiveLesson` (explanation + all cards) in one OpenAI API call.

**Options Considered:**
1. Single call for full lesson (chosen)
2. Separate call for explanation + separate call per card batch
3. Parallel calls for explanation and cards

**Rationale:** A single structured JSON call minimizes latency and cost. The `TeachingService` precedent (`_generate_cards_single`) validates this pattern. Option 2 doubles latency and cost. Option 3 adds implementation complexity and the explanation and cards must share context anyway.

**Trade-off:** A single call with up to 14 cards requires `gpt-4o` (not mini) and a `max_tokens` budget of ~2,500 to ensure complete JSON output. This is an acceptable cost given the personalization value.

---

### ADR-3: In-Process Sharing of KnowledgeService

**Decision:** The `AdaptiveEngine` receives a reference to the singleton `KnowledgeService` loaded at app startup.

**Options Considered:**
1. Pass KnowledgeService reference (chosen)
2. Re-instantiate KnowledgeService per request
3. Duplicate graph access via a separate NetworkX load

**Rationale:** `KnowledgeService.__init__` loads ChromaDB, a NetworkX graph JSON, and a LaTeX map — a cold-start operation taking ~2 seconds. The existing pattern (see `main.py` lifespan) instantiates it once and shares the reference. The adaptive engine follows the same pattern.

**Trade-off:** A single shared `KnowledgeService` instance means concurrent requests share read-only graph access. NetworkX DAG traversal (`graph.predecessors()`) is read-only and thread-safe for concurrent reads.

---

### ADR-4: No Persistence of Generated Lessons

**Decision:** `AdaptiveLesson` responses are not stored in the database.

**Options Considered:**
1. Generate on demand (chosen)
2. Cache in PostgreSQL with TTL
3. Cache in Redis

**Rationale:** An `AdaptiveLesson` is a function of `(concept_id, analytics_snapshot)`. The analytics snapshot changes after each session interaction, so a cached lesson becomes stale quickly. Storing lessons adds a new table, schema migration complexity, and invalidation logic — none of which is required for v1 correctness. The LLM is the latency bottleneck regardless; caching the DB query alone (mastery lookup) provides marginal benefit.

---

### ADR-5: API Versioned Under `/api/v3`

**Decision:** Register the adaptive router under `/api/v3/adaptive/` rather than extending `/api/v2`.

**Options Considered:**
1. New `/api/v3` prefix (chosen)
2. Extend `/api/v2` with a new `/adaptive` group

**Rationale:** The existing versioning convention (`/api/v1` = RAG+Graph, `/api/v2` = Teaching Loop + Translation) maps each major capability to a version prefix. The adaptive engine is a distinct capability layer on top of both. Using `/api/v3` preserves this convention and avoids coupling the new endpoint to the v2 teaching session lifecycle.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LLM returns malformed JSON (missing closing brace, truncated card array) | Medium | High | Apply existing `_salvage_truncated_json` pattern; retry up to 3× with explicit JSON instruction reinforcement in prompt |
| Token budget exceeded causing truncated output | Medium | High | `GenerationProfile.card_count` caps at 14; prompt explicitly states card count limit; `max_tokens=2800` leaves headroom |
| `gpt-4o` rate limiting under burst load | Low | Medium | FastAPI async I/O handles concurrent requests naturally; OpenAI retry with back-off handles transient 429s; alert on sustained 429s |
| Graph traversal finds no unmastered prerequisite (empty remediation) | Low | Low | Remediation logic explicitly handles the empty case: `remediation.included = False, prereq_concept_id = null` |
| Mastery DB query latency spike | Low | Low | Query is a simple `WHERE student_id = ? AND concept_id IN (direct_prereqs)` with index on `(student_id, concept_id)`; covered by existing `uq_student_concept` unique constraint |
| Classification thresholds poorly calibrated | Medium | Medium | Thresholds are constants in `config.py` and documented in DLD; product team can adjust without touching business logic; schedule a calibration review after 500 lesson generations |
| Concept text too long for token budget | Medium | Low | Prompt builder truncates concept text to 1,200 characters (same pattern as `TeachingService.generate_cards`) |
| Student not found in DB | Low | Low | Return HTTP 404 with clear error message before any LLM call |

---

## Key Decisions Requiring Stakeholder Input

1. **Remediation threshold:** The current design triggers remediation for ANY STRUGGLING student with an unmastered direct prerequisite. Should there be a session-count guard (e.g., only trigger remediation if `last_7d_sessions < 3` to avoid remediating a student who is actively engaged but slow)?

2. **Lesson caching:** Should generated lessons be cached (e.g., in Redis with a 24-hour TTL keyed on `(student_id, concept_id, profile_hash)`) once the analytics signal stabilizes between sessions? This would improve response time from ~6s to ~50ms on repeat requests.

3. **`emoji_policy` default:** The spec says `NONE` for STANDARD students and `SPARING` for OVERWHELMED/STRUGGLING. Should BORED students always get `SPARING` (fun cards with light emoji) or remain `NONE`? Product should confirm.

4. **Analytics summary ownership:** Who computes the `AnalyticsSummary`? Does the frontend compute it from PostHog event data and pass it directly, or does the backend compute it from stored session records? The current design assumes the frontend (or a PostHog webhook) provides the pre-computed summary.

5. **Multi-language support:** The engine passes the student's `preferred_language` to the prompt. Has the multi-language prompt strategy (already implemented in `prompts.py`) been validated for adaptive content? Confirm whether adaptive lessons require the same or a different language system prompt.
