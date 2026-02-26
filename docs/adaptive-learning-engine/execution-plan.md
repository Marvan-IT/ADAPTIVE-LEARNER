# Execution Plan: Adaptive Learning Generation Engine

**Feature slug:** `adaptive-learning-engine`
**Version:** 1.0.0
**Date:** 2026-02-25
**Author:** Solution Architect Agent

---

## 1. Work Breakdown Structure (WBS)

### Phase 1 — Foundation

| Task ID | Title | Description | Est. Effort | Dependencies | Component |
|---------|-------|-------------|-------------|--------------|-----------|
| P1-T01 | Create `adaptive/` package skeleton | Create `backend/src/adaptive/__init__.py`. Verify Python import works. | 0.1d | None | `adaptive/__init__.py` |
| P1-T02 | Define all Pydantic schemas | Implement `schemas.py` with all enums, `AnalyticsSummary`, `LearningProfile`, `GenerationProfile`, `LessonCard`, `LessonBody`, `RemediationInfo`, `AdaptiveLesson`, `AdaptiveLessonRequest`. Include `wrong_le_attempts` field validator. | 0.5d | P1-T01 | `adaptive/schemas.py` |
| P1-T03 | Implement `profile_builder.py` | Implement `classify_speed()`, `classify_comprehension()`, `classify_engagement()`, `compute_confidence_score()`, `determine_next_step()`, `build_learning_profile()`. Exact thresholds as specified in DLD Section 3. | 0.5d | P1-T02 | `adaptive/profile_builder.py` |
| P1-T04 | Implement `generation_profile.py` | Implement `BASE_PROFILES` lookup table (all 9 speed × comprehension combinations) and `build_generation_profile()` with engagement modifier application. | 0.5d | P1-T02 | `adaptive/generation_profile.py` |
| P1-T05 | Implement `remediation.py` | Implement `RemediationCandidate` dataclass, `resolve_remediation()` (async, DB + graph), `build_remediation_cards()` (template-based, no LLM). | 0.5d | P1-T02 | `adaptive/remediation.py` |
| P1-T06 | Add config constants | Add `ADAPTIVE_MAX_CONCEPT_TEXT_CHARS = 1200` and `ADAPTIVE_LLM_MAX_TOKENS = 2800` to `backend/src/config.py`. | 0.1d | None | `config.py` |
| P1-T07 | Add pytest to requirements | Add `pytest>=8.0.0` and `pytest-asyncio>=0.23.0` to `backend/requirements.txt` if not present. | 0.1d | None | `requirements.txt` |
| P1-T08 | Write unit tests — `profile_builder` | Implement all 12+ `profile_builder` test cases from DLD Section 14. Verify 100% branch coverage of all classification functions. | 0.5d | P1-T03 | `tests/test_adaptive_engine.py` |
| P1-T09 | Write unit tests — `generation_profile` | Implement all 5+ `generation_profile` test cases from DLD Section 14. Include edge cases: card_count floor at 7, analogy_level cap at 1.0. | 0.5d | P1-T04 | `tests/test_adaptive_engine.py` |
| P1-T10 | Write unit tests — `remediation` logic | Implement 3+ `remediation` unit tests using mock `AsyncSession` and mock `nx.DiGraph`. Verify no-remediation, all-mastered, and first-unmastered-prereq cases. | 0.5d | P1-T05 | `tests/test_adaptive_engine.py` |

**Phase 1 Total Estimated Effort: 3.8 days**

---

### Phase 2 — LLM Integration

| Task ID | Title | Description | Est. Effort | Dependencies | Component |
|---------|-------|-------------|-------------|--------------|-----------|
| P2-T01 | Implement `prompt_builder.py` | Implement `build_adaptive_system_prompt()` and `build_adaptive_user_prompt()`. Include `ADAPTIVE_MAX_CONCEPT_TEXT_CHARS` truncation. Implement remediation context block injection. | 0.5d | P1-T02, P1-T06 | `adaptive/prompt_builder.py` |
| P2-T02 | Implement `adaptive_engine.py` — scaffolding | Create `AdaptiveEngine` class with `__init__` accepting `KnowledgeService`, `AsyncOpenAI`, and `model` string. Implement orchestration method stub with all steps (a–j) as comments. | 0.5d | P1-T03, P1-T04, P1-T05, P2-T01 | `adaptive/adaptive_engine.py` |
| P2-T03 | Implement `adaptive_engine.py` — LLM call | Implement `_call_llm_with_retry()` with 3-attempt exponential back-off (2s, 4s), JSON extraction (`_extract_json_block`), salvage pattern, and structured logging. | 0.5d | P2-T02 | `adaptive/adaptive_engine.py` |
| P2-T04 | Implement `adaptive_engine.py` — full orchestration | Complete `generate_lesson()` implementing all steps a–j: profile building, student DB fetch, concept retrieval, remediation resolution, prompt construction, LLM call, Pydantic validation, card prepending, return. | 1.0d | P2-T02, P2-T03 | `adaptive/adaptive_engine.py` |
| P2-T05 | Write integration tests — engine pipeline | Implement 3+ integration tests using a mock `AsyncOpenAI` client (returns a pre-canned valid JSON lesson) and a mock `KnowledgeService`. Verify full `AdaptiveLesson` structure, remediation prepending, and error cases (student not found, concept not found). | 1.0d | P2-T04 | `tests/test_adaptive_engine.py` |
| P2-T06 | Write integration test — LLM retry | Implement a test where the mock OpenAI client returns truncated JSON on attempt 1, valid JSON on attempt 2. Verify the engine returns a valid lesson and logs the retry. | 0.5d | P2-T03 | `tests/test_adaptive_engine.py` |
| P2-T07 | Write integration test — LLM total failure | Implement a test where all 3 LLM attempts fail. Verify the engine raises `HTTPException(502)`. | 0.25d | P2-T03 | `tests/test_adaptive_engine.py` |
| P2-T08 | Manual prompt validation | Run the prompt builder output against live `gpt-4o` API for 3 distinct learning profiles (SLOW+STRUGGLING, NORMAL+OK, FAST+STRONG). Verify JSON structure, card count accuracy, reading level compliance. Document pass/fail in a test log. | 0.5d | P2-T01, P2-T04 | Manual validation |

**Phase 2 Total Estimated Effort: 4.75 days**

---

### Phase 3 — API Layer

| Task ID | Title | Description | Est. Effort | Dependencies | Component |
|---------|-------|-------------|-------------|--------------|-----------|
| P3-T01 | Implement `adaptive_router.py` | Create `APIRouter` with prefix `/api/v3`. Implement `POST /adaptive/lesson` handler calling `adaptive_engine.generate_lesson()`. Follow the same module-level reference pattern as `teaching_router`. | 0.5d | P2-T04 | `adaptive/adaptive_router.py` |
| P3-T02 | Wire router into `main.py` | Add imports, instantiate `AdaptiveEngine` in `lifespan()`, register router. Follow exact wiring instructions from DLD Section 10.4. | 0.25d | P3-T01 | `api/main.py` |
| P3-T03 | Manual API smoke test | Start the backend locally. Invoke `POST /api/v3/adaptive/lesson` via curl or Postman with a real student UUID and a known concept_id. Verify HTTP 200 with valid `AdaptiveLesson` JSON. Verify HTTP 404 for unknown student. | 0.25d | P3-T02 | Manual |
| P3-T04 | Write E2E API test | Implement the FastAPI `TestClient` (or `AsyncClient`) E2E test from DLD Section 14. Seed a test student, POST a valid request, assert HTTP 200 and response shape. | 0.5d | P3-T02 | `tests/test_adaptive_engine.py` |
| P3-T05 | Write E2E validation error test | POST a request with `wrong_attempts > attempts`. Assert HTTP 422 and the validation error references the correct field. | 0.25d | P3-T02 | `tests/test_adaptive_engine.py` |
| P3-T06 | Verify `/docs` OpenAPI schema | Confirm `POST /api/v3/adaptive/lesson` appears correctly in the FastAPI auto-generated OpenAPI spec with all request/response schemas documented. | 0.1d | P3-T02 | Manual |

**Phase 3 Total Estimated Effort: 1.85 days**

---

### Phase 4 — Hardening

| Task ID | Title | Description | Est. Effort | Dependencies | Component |
|---------|-------|-------------|-------------|--------------|-----------|
| P4-T01 | Structured logging — full coverage | Audit all log call sites in `adaptive_engine.py`. Confirm INFO, WARNING, ERROR events are emitted correctly with all required fields (student_id, concept_id, duration_ms, etc.). | 0.25d | P2-T04 | `adaptive/adaptive_engine.py` |
| P4-T02 | Edge case: concept text truncation | Write a unit test that supplies concept text longer than 1,200 characters to `build_adaptive_user_prompt()`. Assert the output prompt text is truncated to ≤ 1,200 characters. | 0.25d | P2-T01 | `tests/test_adaptive_engine.py` |
| P4-T03 | Edge case: no direct prerequisites | Write a unit test for `resolve_remediation()` where the concept has no predecessors in the graph. Verify `should_remediate = False`. | 0.1d | P1-T05 | `tests/test_adaptive_engine.py` |
| P4-T04 | Edge case: all prerequisites mastered | Write a unit test where the student is STRUGGLING but all direct prereqs are in `student_mastery`. Verify `should_remediate = False`. | 0.1d | P1-T05 | `tests/test_adaptive_engine.py` |
| P4-T05 | Edge case: `attempts == 0` | Verify `error_rate = 0.0` when `attempts == 0` (no division by zero). Verify `speed` classification handles zero attempts gracefully. | 0.1d | P1-T03 | `tests/test_adaptive_engine.py` |
| P4-T06 | DB failure graceful degradation | Write a test that mocks the `student_mastery` DB query to raise `SQLAlchemyError`. Verify the engine catches the error, logs a WARNING, and proceeds with `should_remediate = False` (no crash). | 0.25d | P2-T04 | `tests/test_adaptive_engine.py` |
| P4-T07 | Profile boundary value tests | Add boundary value tests for all classification thresholds (exactly at boundary, one below, one above). Key boundaries: `time > 1.5x`, `quiz_score = 0.5`, `error_rate = 0.5`, `skip_rate = 0.35`, `hints_used = 5`. | 0.5d | P1-T03 | `tests/test_adaptive_engine.py` |
| P4-T08 | Confidence score range validation | Write tests asserting `confidence_score` is always in [0.0, 1.0] across 20+ varied input combinations, including extreme inputs. | 0.25d | P1-T03 | `tests/test_adaptive_engine.py` |
| P4-T09 | Generation profile clamp tests | Write tests asserting `fun_level` and `analogy_level` never exceed 1.0 after engagement modifier addition. Assert `card_count` never falls below 7 after OVERWHELMED modifier. | 0.25d | P1-T04 | `tests/test_adaptive_engine.py` |
| P4-T10 | Latency baseline measurement | Run the engine with a live OpenAI call (real gpt-4o, 9-card lesson) 10 times and record P50/P95 latency. Confirm P95 ≤ 8s. Document results. | 0.5d | P3-T02 | Manual / benchmark |
| P4-T11 | Review and freeze all threshold constants | Product review of all classification thresholds in `profile_builder.py`. If any thresholds are adjusted, re-run all profile_builder unit tests. | 0.5d | P1-T08 | Product review |

**Phase 4 Total Estimated Effort: 3.05 days**

---

### Phase 5 — Release

| Task ID | Title | Description | Est. Effort | Dependencies | Component |
|---------|-------|-------------|-------------|--------------|-----------|
| P5-T01 | Code review — Phase 1 modules | Peer review of `schemas.py`, `profile_builder.py`, `generation_profile.py`, `remediation.py` against DLD specification. | 0.5d | Phase 1 complete | All Phase 1 files |
| P5-T02 | Code review — Phase 2 modules | Peer review of `prompt_builder.py`, `adaptive_engine.py` against DLD specification. | 0.5d | Phase 2 complete | All Phase 2 files |
| P5-T03 | Code review — Phase 3 wiring | Peer review of `adaptive_router.py` and `main.py` modifications. | 0.25d | Phase 3 complete | `adaptive_router.py`, `main.py` |
| P5-T04 | Frontend integration handoff | Share `AdaptiveLesson` Pydantic schema (as TypeScript interface) with the frontend team. Confirm the response contract aligns with UI requirements for displaying adaptive cards and remediation context. | 0.5d | P3-T02 | Coordination |
| P5-T05 | Feature flag / rollout decision | Decide rollout strategy: (a) direct deployment for all students, or (b) cohort-based rollout using PostHog feature flags. Configure accordingly. | 0.25d | P5-T04 | Infrastructure / Product |
| P5-T06 | Monitoring alert setup | Work with devops-engineer to configure alerts for: LLM retry rate > 5%, full failure rate > 0, P95 latency > 8s. Confirm alerts fire in staging environment. | 0.5d | P4-T10 | devops-engineer |
| P5-T07 | Staging deployment and smoke test | Deploy to staging. Run smoke test suite (P3-T04, P3-T05) against the staging DB. Verify lesson generation works with a real student record and real OpenAI key. | 0.5d | P5-T05, P5-T06 | DevOps |
| P5-T08 | Production deployment | Deploy to production. Confirm health endpoint responds, adaptive endpoint returns 200 for a sample request. | 0.25d | P5-T07 | DevOps |
| P5-T09 | Post-launch validation (day 1) | Monitor: LLM failure alerts, P95 latency, remediation rate % (expect 20–40% for early learners). Record first 50 lesson generations for qualitative review. | 0.5d | P5-T08 | On-call team |

**Phase 5 Total Estimated Effort: 3.75 days**

---

## 2. Phased Delivery Plan

### Phase 1: Foundation (Days 1–4)
**Goal:** All deterministic, testable logic is complete and passing. Zero LLM or DB dependencies required to run tests.

**Deliverables:**
- `backend/src/adaptive/__init__.py`
- `backend/src/adaptive/schemas.py`
- `backend/src/adaptive/profile_builder.py`
- `backend/src/adaptive/generation_profile.py`
- `backend/src/adaptive/remediation.py`
- `backend/src/config.py` (2 constants added)
- `backend/requirements.txt` (pytest added)
- `backend/tests/test_adaptive_engine.py` (unit tests for above, all passing)

**Key milestone:** `pytest backend/tests/test_adaptive_engine.py` passes with 0 failures and ≥ 90% coverage of Phase 1 modules.

---

### Phase 2: LLM Integration (Days 4–9)
**Goal:** Full end-to-end lesson generation pipeline works with a mocked OpenAI client. Prompt quality validated against live gpt-4o.

**Deliverables:**
- `backend/src/adaptive/prompt_builder.py`
- `backend/src/adaptive/adaptive_engine.py`
- Integration tests for engine (mocked LLM)
- Manual prompt validation log (3 profiles × live gpt-4o)

**Key milestone:** `pytest backend/tests/test_adaptive_engine.py` passes all unit + integration tests. Manual prompt validation shows correct card counts and reading levels for all 3 tested profiles.

---

### Phase 3: API Layer (Days 9–11)
**Goal:** HTTP endpoint live on localhost, returning valid `AdaptiveLesson` JSON for a real student and concept.

**Deliverables:**
- `backend/src/adaptive/adaptive_router.py`
- `backend/src/api/main.py` (modified)
- E2E API tests passing
- OpenAPI docs show correct endpoint schema

**Key milestone:** `curl -X POST http://localhost:8000/api/v3/adaptive/lesson -d '{...}'` returns HTTP 200 with valid `AdaptiveLesson` JSON. All test suites pass.

---

### Phase 4: Hardening (Days 11–14)
**Goal:** All edge cases covered by tests. Latency baseline confirmed. Threshold constants reviewed and frozen.

**Deliverables:**
- All edge case and boundary value tests passing
- Latency measurement document (P50/P95 over 10 live calls)
- Product sign-off on classification thresholds

**Key milestone:** Full test suite passes with ≥ 90% line coverage across all `adaptive/` modules. P95 latency ≤ 8s confirmed.

---

### Phase 5: Release (Days 14–17)
**Goal:** Feature deployed to production, monitored, and validated post-launch.

**Deliverables:**
- All code reviews approved
- Frontend team has TypeScript contract
- Monitoring alerts configured and verified
- Production deployment complete
- Post-launch day-1 monitoring report

**Key milestone:** 50 successful adaptive lesson generations in production with zero LLM failure alerts triggered.

---

## 3. Dependencies and Critical Path

### Dependency Graph

```
P1-T01 → P1-T02 → P1-T03 → P1-T08
                  P1-T03 → P4-T07
                  P1-T04 → P1-T09
                  P1-T04 → P4-T09
                  P1-T05 → P1-T10
                  P1-T05 → P4-T03, P4-T04, P4-T06
         P1-T02 → P2-T01 → P2-T02 → P2-T03 → P2-T04 → P2-T05
                                               P2-T04 → P3-T01 → P3-T02 → P3-T03
                                                                  P3-T02 → P3-T04
                                                                  P3-T02 → P3-T05
                                                                  P3-T02 → P3-T06
                                                                  P3-T02 → P4-T10
                                                                  P3-T02 → P5-T01..P5-T09
P1-T06 → P2-T01 (config constants available for prompt builder)
P1-T07 (pytest) → All test tasks
```

### Critical Path

```
P1-T01 → P1-T02 → P1-T03 → P2-T01 → P2-T02 → P2-T03 → P2-T04 → P3-T01 → P3-T02 → P5-T07 → P5-T08
```

Total critical path: ~9.5 working days.

### Blocking External Dependencies

| Dependency | Owner | Blocker For | Notes |
|------------|-------|-------------|-------|
| `get_db()` AsyncSession dependency in `db/connection.py` | devops-engineer | P3-T01, P3-T02 | Must be implemented before Phase 3. Confirm with devops-engineer at end of Phase 1. |
| `pytest.ini` and `conftest.py` for test DB provisioning | devops-engineer | All integration/E2E tests | Needed for P2-T05, P3-T04. Unit tests (P1-T08–P1-T10) can proceed with pure mocks. |
| `student_mastery` table accessibility in test DB | devops-engineer | P2-T05, P3-T04 | Must have a seeded test student with known UUIDs. |
| Product team threshold review | Product Manager | P4-T11 | Must be completed before P5-T01 code review or threshold changes will force re-test. |
| Frontend TypeScript contract review | Frontend developer | P5-T04 | Must be completed before P5-T05 rollout decision. |

---

## 4. Definition of Done

### Phase 1 DoD
- [ ] All 4 modules (`schemas.py`, `profile_builder.py`, `generation_profile.py`, `remediation.py`) implemented per DLD specifications.
- [ ] `pytest backend/tests/test_adaptive_engine.py -k "phase1"` passes with 0 failures.
- [ ] All 12 required unit test cases for `profile_builder` implemented and passing.
- [ ] All 5 required unit test cases for `generation_profile` implemented and passing.
- [ ] All 3 required unit test cases for `remediation` implemented and passing.
- [ ] `STRUGGLING` check runs before `STRONG` check in comprehension classification (order verified by test).
- [ ] `BORED` check runs before `OVERWHELMED` check in engagement classification (order verified by test).
- [ ] `card_count` never falls below 7 under any engagement modifier combination (test verified).
- [ ] `confidence_score` always in [0.0, 1.0] (test verified).
- [ ] No `print()` statements in any Phase 1 file (use `logging`).
- [ ] No hardcoded magic numbers in business logic (all thresholds reference named constants or are locally documented).

### Phase 2 DoD
- [ ] `prompt_builder.py` produces syntactically valid prompt strings for all 9 base profiles.
- [ ] `adaptive_engine.py` `generate_lesson()` runs end-to-end with a mocked OpenAI client (returns pre-canned JSON).
- [ ] `_call_llm_with_retry()` retries on `JSONDecodeError` and returns on valid JSON (test verified).
- [ ] `_call_llm_with_retry()` raises `HTTPException(502)` after 3 failures (test verified).
- [ ] Concept text is truncated to ≤ `ADAPTIVE_MAX_CONCEPT_TEXT_CHARS` characters in the user prompt (test verified).
- [ ] Manual prompt validation confirms: SLOW+STRUGGLING lesson has exactly 12 cards (or adjusted count); FAST+STRONG lesson has exactly 7 cards; reading level terminology is appropriate.
- [ ] `pytest backend/tests/test_adaptive_engine.py -k "integration"` passes with 0 failures.

### Phase 3 DoD
- [ ] `POST /api/v3/adaptive/lesson` returns HTTP 200 with valid `AdaptiveLesson` JSON for a real seeded student and known concept_id.
- [ ] `POST /api/v3/adaptive/lesson` returns HTTP 404 for an unknown `student_id`.
- [ ] `POST /api/v3/adaptive/lesson` returns HTTP 404 for an unknown `concept_id`.
- [ ] `POST /api/v3/adaptive/lesson` returns HTTP 422 for `wrong_attempts > attempts`.
- [ ] `/docs` (FastAPI OpenAPI) shows the endpoint with correct request/response schemas.
- [ ] No existing `/api/v1` or `/api/v2` endpoints are broken (regression check: run full test suite).
- [ ] `pytest backend/tests/test_adaptive_engine.py` (all tests) passes with 0 failures.

### Phase 4 DoD
- [ ] All 11 hardening tasks complete (P4-T01 through P4-T11).
- [ ] Code coverage ≥ 90% for all files in `backend/src/adaptive/`.
- [ ] P95 latency ≤ 8s confirmed over 10 live gpt-4o calls (documented).
- [ ] Product team has signed off on classification thresholds.
- [ ] Zero `print()` or `console.log` statements in any committed file.

### Phase 5 DoD
- [ ] All code reviews approved with no unresolved comments.
- [ ] TypeScript interface generated from `AdaptiveLesson` schema and delivered to frontend team.
- [ ] Monitoring alerts configured and verified (tested in staging).
- [ ] Staging smoke test passes (HTTP 200, valid JSON, no LLM errors in logs).
- [ ] Production deployment successful.
- [ ] First 50 lesson generations in production logged with no LLM failure alerts.

---

## 5. Rollout Strategy

### Stage 1: Internal Testing (Days 1–14)
- Feature runs only on `localhost` / developer machines during Phases 1–4.
- Unit and integration tests must pass before any deployment.

### Stage 2: Staging Deployment (Day 14–15, P5-T07)
- Deploy to a staging environment with a copy of production DB (anonymized student data).
- Run the full E2E test suite against staging.
- Perform 10 manual lesson generation requests across different concepts and student profiles.
- Confirm monitoring dashboards show correct metrics.
- **Go/No-Go decision:** All smoke tests pass, P95 latency ≤ 8s in staging.

### Stage 3: Production Rollout (Day 15–16, P5-T08)
**Strategy: Direct deployment (no feature flag) for v1.**

Rationale: The adaptive endpoint is a new endpoint (`/api/v3`) that does not modify any existing endpoints. It cannot break existing functionality. No traffic is routed to it until the frontend is updated to call it. This makes a feature-flag unnecessary for the backend release.

**Deployment steps:**
1. Merge feature branch to `main` (or default branch).
2. Deploy via existing CI/CD pipeline (GitHub Actions, managed by devops-engineer).
3. Confirm `GET /health` returns 200 (existing health check).
4. Manually verify `POST /api/v3/adaptive/lesson` returns 200 for a known test request.
5. Monitor logs for 30 minutes post-deployment.

### Rollback Plan
If `POST /api/v3/adaptive/lesson` returns 5xx at a rate > 1% in the first 30 minutes:
1. Revert to the previous deployment (one command via CI/CD rollback).
2. The rollback has zero impact on existing `/api/v1` and `/api/v2` functionality (the adaptive router is additive).
3. Root-cause the issue against logs (LLM errors → check OpenAI API status; DB errors → check PostgreSQL connectivity).

### Post-Launch Validation (Day 16–17, P5-T09)
- Monitor for 24 hours: LLM retry rate, P95 latency, remediation trigger rate.
- Qualitatively review 10 generated lessons per profile type (STRUGGLING, OK, STRONG).
- Schedule a calibration review with the product team at 500 lesson generations.

---

## 6. Risk Register

| Risk ID | Risk | Likelihood | Impact | Phase Affected | Mitigation |
|---------|------|-----------|--------|----------------|------------|
| R-01 | LLM returns JSON missing `cards` array or with wrong card count | Medium | High | Phase 2 | Pydantic validation catches structural errors; retry mechanism handles transient failures; prompt explicitly states `EXACTLY {card_count} cards` |
| R-02 | Token budget exceeded — gpt-4o truncates the JSON response mid-card | Medium | High | Phase 2 | `max_tokens=2800` allows ~14 cards; concept text truncated to 1,200 chars; salvage algorithm recovers partial arrays; verified in manual prompt testing (P2-T08) |
| R-03 | OpenAI API cost increases significantly with adaptive lesson volume | Low | Medium | Phase 5 | `gpt-4o` averages ~$0.01–0.02 per lesson call at current token budgets; monitor via OpenAI usage dashboard; if cost becomes material, investigate `gpt-4o-mini` with structured output mode for v2 |
| R-04 | Cold-start latency: KnowledgeService + NetworkX graph not loaded before first adaptive request | Low | Medium | Phase 3 | Engine is instantiated in the existing `lifespan()` context manager (same as `KnowledgeService`); the graph is in memory before the first request is accepted |
| R-05 | Classification thresholds poorly calibrated → most students classified as STRUGGLING | Medium | Medium | Phase 4 | P4-T11 product review before release; post-launch monitoring of profile distribution; thresholds are in `profile_builder.py` as named constants (1-line change to adjust) |
| R-06 | `get_db()` not yet implemented by devops-engineer | Medium | High | Phase 3 | Identify this dependency at end of Phase 1; devops-engineer must deliver `get_db()` before Phase 3 begins (P3-T01 blocker) |
| R-07 | Remediation cards have low quality (template-based) and confuse students | Low | Medium | Phase 5 | Template cards are clearly marked `[Review]` with difficulty 1–2; product team can evaluate qualitative impact at 500 lesson threshold and upgrade to LLM-generated cards in v2 |
| R-08 | Concurrent requests share `KnowledgeService.graph` — potential race condition | Low | Low | Phase 3 | NetworkX `DiGraph.predecessors()` is a read-only operation; Python GIL protects against data corruption on concurrent reads; no writes to the graph from the adaptive engine |
| R-09 | `student_id` in `analytics_summary` diverges from `student_id` in request body | Low | Low | Phase 1 | Pydantic `AdaptiveLessonRequest` uses `request.student_id` as the authoritative ID; `analytics_summary.student_id` is informational; engine uses `request.student_id` exclusively for DB queries |

---

## 7. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 1 — Foundation | Schemas, LearningProfile, GenerationProfile, Remediation logic, Unit tests | 3.8 days | 1 backend developer |
| Phase 2 — LLM Integration | PromptBuilder, AdaptiveEngine, Integration tests, Manual prompt QA | 4.75 days | 1 backend developer + 1 product reviewer (0.5d for threshold review) |
| Phase 3 — API Layer | Router, main.py wiring, E2E tests, OpenAPI docs | 1.85 days | 1 backend developer |
| Phase 4 — Hardening | Edge case tests, latency benchmarking, threshold freeze, code coverage | 3.05 days | 1 backend developer + 1 product manager (0.5d threshold review) |
| Phase 5 — Release | Code reviews, frontend handoff, monitoring setup, deployment, post-launch | 3.75 days | 1 backend developer + 1 devops engineer (1d) + 1 frontend developer (0.5d) |
| **TOTAL** | | **~17.2 developer-days** | **Backend dev (primary), Devops (1d), Product (1d), Frontend (0.5d)** |

**Calendar estimate:** With 1 dedicated backend developer, all phases can be completed in **3–4 calendar weeks**, accounting for code review turnaround and external dependency (devops-engineer `get_db()` availability).

---

## Key Decisions Requiring Stakeholder Input

1. **Go/No-Go on direct vs. canary rollout:** The plan recommends direct deployment (the endpoint is additive and cannot break existing functionality). If the product team prefers a canary rollout gated by a PostHog feature flag at the frontend, the devops-engineer must provision the flag before Phase 5 begins (adds ~0.5d to Phase 5).

2. **`get_db()` readiness:** The existing backend has `Base.metadata.create_all()` as a known technical debt item. Before Phase 3 begins, confirm with the devops-engineer whether `get_db()` as an async FastAPI dependency is already implemented in `db/connection.py`. If not, this must be prioritized.

3. **Test database provisioning:** Integration and E2E tests (Phases 2–3) require a running PostgreSQL test database with the `students` and `student_mastery` tables. Confirm `conftest.py` and test DB setup will be provided by the devops-engineer before Phase 2 integration tests begin.

4. **Threshold calibration review timing:** The product review of classification thresholds (P4-T11) is on the critical path for Phase 5 code review. Schedule this review no later than end of Phase 3 to avoid blocking the release.

5. **Frontend integration timeline:** Phase 5 includes a TypeScript contract handoff to the frontend team. Confirm whether the frontend team can integrate the adaptive lesson UI in parallel with Phase 4 hardening, or whether the backend must be fully released first. Parallelization would shorten calendar time by ~1 week.
