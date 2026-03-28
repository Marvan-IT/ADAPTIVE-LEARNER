---
name: test-file-registry
description: Per-test-file test counts, group names, and key implementation facts for all backend test files
type: project
---

## Test File Registry (backend/tests/)

### test_blending_analytics.py — 26 tests
- `TestNewStudentBlending`, `TestNormalVarianceBlending`, `TestAcuteDeviationBlending`, `TestSectionCountWeights`, `TestComputeNumericStateScore`, `TestBlendedScoreToGenerateAs`, `TestBlendedAnalyticsRobustness`
- `build_blended_analytics(current, history, concept_id, student_id)` → `(AnalyticsSummary, float, str)`
- Blend weights: new_student=1.0/0.0; section_count 0→80/20, 1→70/30, 2→65/35, 3+→60/40; acute=90/10

### test_section_order.py — 19 tests
- `TestParseSubSections`, `TestClassifySections`, `TestBuildTextbookBlueprint`
- ALLCAPS test fix: body text must NOT start with ALLCAPS keywords (Solution/Example/Try) or they get re-promoted to headers

### test_image_assignment.py — 13 tests
- `TestUsefulImagesFilter`, `TestMissedImageCleanup`
- Useful image filter: `is_educational is not False` AND description non-empty AND no checklist keywords; cap 16; sorted by `_IMAGE_TYPE_PRIORITY`
- Missed-image cleanup: word-overlap scoring; `best_score > 0` required for assignment

### test_mid_section_mode.py — 8 tests
- `TestMidSectionModeAdaptation`
- Tests `build_blended_analytics` + `blended_score_to_generate_as` with realistic session signals

### test_student_analytics.py — 18 tests
- `TestConstants`, `TestMasteryDetermination`, `TestBlendedScoreBoundaries`, `TestAnalyticsSummaryValidation`, `TestCardBehaviorSignalsDefaults`, `TestLearningProfileConstraints`

### test_content_coverage.py — 12 tests
- `TestSectionCountPreservation`, `TestContentPreservation`, `TestStarterPackQueueCoverage`

### test_api_integration.py — 24 tests
- `TestHealthAndBooks`, `TestStudentEndpoints`, `TestSessionEndpoints`, `TestAnalyticsEndpoints`, `TestPydanticSchemaValidation`
- Uses real FastAPI routing via `ASGITransport` with mocked DB and services
- `_FakeAggRow` pattern for DB aggregate mocks

### test_adaptive_engine.py
- See adaptive-engine-tests.md

### test_teaching_service.py — 27 tests
- SOCRATIC_MAX_ATTEMPTS=3; exhaustion at `attempt_count >= 3` (NOT `< 3`)
- Result dict has "mastered" key (NOT "passed")
- Patch targets: `"adaptive.adaptive_engine.load_student_history"`, `"adaptive.adaptive_engine.load_wrong_option_pattern"`
- `build_learning_profile`: patch as `"adaptive.profile_builder.build_learning_profile"`
- `generate_remediation_cards(session_id: UUID, db)` — session fetched via db.get
- CHECKIN insertion: `(i+1) % INTERVAL == 0 and (i+1) < len(raw_cards)` — needs N+1 cards (13 for interval=12)
- `begin_recheck`: db.get receives cls (not str); mock with `async def _db_get(cls, pk)` pattern

### test_platform_hardening.py — 32 tests
- Suite 1 (6): auth middleware (synthetic app, no real DB)
- Suite 2 (6): ProgressUpdate Pydantic schema validation
- Suite 3 (11): _nearest_concept() + Pillow image validation
- Suite 4 (5): vision annotator with mocked LLM
- Suite 5 (4): list_students N+1 fix structural inspection

### test_card_generation.py — 74 tests (12 groups)
- `_group_by_major_topic()` static method; support headings: EXAMPLE, Solution, TRY IT, HOW TO, Note, TIP, etc.
- Adaptive max_tokens: SLOW/STRUGGLING=`min(16000, max(8000, n*1800))`; FAST+STRONG=`min(8000, max(4000, n*900))`; else=`min(12000, max(6000, n*1200))`
- `build_cards_user_prompt()` sub-section dicts MUST have key `"text"` (not `"content"`)
- `build_socratic_system_prompt()`: `base_min=max(8, n_topics)`, `base_max=min(15, n_topics+4)`; MAX_SOCRATIC_EXCHANGES=30
- `_extract_failed_topics_from_messages`: dedup by `last_assistant_msg[:50]`; regex `[^.!?]*\?`

### test_bug_regressions.py — 22 tests
- B-07: `UpdateLanguageRequest` pattern rejects invalid language codes
- B-02: `generate_recovery_card()` populates `card["images"]` from `concept_detail[:3]`
- B-03: `_call_llm()` passes `timeout=30.0`
- B-05: repair uses `json.loads(repair_json(raw))`, NOT `return_objects=True`
- B-01: `switch_style`/`update_session_interests` return 409 when phase != PRESENTING
- E2E test requires `TEST_API_KEY` env var + live backend

### test_bug_fixes.py — 96 tests (19 groups)
- Fix 1 (4): FUN/RECAP reorder removed; _section_index sort authoritative
- Fix 2A (9): image filter allows PHOTO/TABLE/FIGURE (`is not False`)
- Fix 2B (4): file-not-found path retains indexed filename
- Fix 3 (4): REPLACE_UPCOMING_CARD replaces targetIndex slot
- Fix 4A/4B (13): expected_time floor 90s; cap threshold 5→2
- Fix 5A (10): _batch_consecutive_properties merges consecutive CONCEPT sections
- Fix 6 (9): doubles non-safe-escape backslashes; `\t` IS safe so `\times` NOT doubled
- Fix 7 (4): image URLs include book_slug
- Fix 8 (2): blended_score forwarded; `db.flush = AsyncMock()`
- Fix 9 (5): `/api/v2/books` endpoint; `_install_rate_limiter_stub()` pattern
- Fix 10 (4): CardBehaviorSignals from adaptive.schemas
- Fix 11 (6): _sort_cards(): FUN first, difficulty-ascending middle, RECAP last
- Fix 12 (4): parse_card_image_ref strips [CARD:N]; out-of-bounds → None
- Fix 13 (3): base_url default is `""` not `localhost:8000`

### test_universal_cards.py — 40 tests (6 groups)
- `textwrap.dedent()` required before `ast.parse(inspect.getsource(...))`
- `_CARDS_CACHE_VERSION=21` (verify via source regex — local var, not importable)
- RECAP stamp: `_section_index=9999`; missed-image cleanup `_best_score > 0` guard
- `TestAdaptiveModeDerivation` (5): SLOW/low-comp → STRUGGLING; FAST+high-comp → FAST; else NORMAL

### test_per_card_adaptive.py — 20 tests (7 groups)
- generate_per_card() mode mapping: STRUGGLING→"SLOW", FAST→"FAST", NORMAL→"NORMAL"
- `STARTER_PACK_INITIAL_SECTIONS=2` (config.py); remainder goes to concepts_queue
- Endpoint guard tests use real Starlette Request scope dict
- Patch `adaptive.adaptive_engine.build_blended_analytics` → return `(analytics, score, mode_str)`
- Image assignment: first AVAILABLE index (not in assigned_image_indices)
- Fix 14: `_CARDS_CACHE_VERSION==15` (was 15 at write time; verify)
- Fix 15: blank card filter (empty/whitespace title or content)
- Fix 16: `CompleteCardRequest` has `wrong_question`/`wrong_answer_text`
- Fix 17: `/api/v1/books` in main.py; `graph_full` has `book_slug` param
- Fix 18: SLOW maps to STRUGGLING; `_CARD_MODE_DELIVERY` has no SLOW key

### test_real_students_e2e.py — 10 tests (5 journey classes, @pytest.mark.e2e)
- Uses synchronous `requests`, no mocks; backend at `http://localhost:8889`
- Skip pattern: 404 on _start_session → pytest.skip() when ChromaDB not loaded

### test_parse_sub_sections.py — 22 tests (7 classes)
- See parse-sub-sections-tests.md

### test_concept_enrichment.py — 17 tests (3 groups)
- `store_concept_blocks`, `annotate_image`, `KnowledgeService._get_latex`, `get_concept_images`
