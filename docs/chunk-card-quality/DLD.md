# DLD — Chunk Card Quality Fix

## 1. Component Breakdown

| Component | Responsibility | Change |
|-----------|---------------|--------|
| `prompt_builder.py` — `build_chunk_card_prompt()` | Builds user prompt passed to LLM | Fix alternating-card instruction (Issue 1) |
| `teaching_service.py` — `generate_per_chunk()` | Orchestrates LLM call, parses cards, normalises output | Fix model selection (Issue 4) + add image fallback (Issue 2) |
| `config.py` — `CHUNK_MAX_TOKENS_NORMAL` | Token budget constant for NORMAL mode | Raise from 2000 → 5000 (Issue 3) |

No new modules. No new API endpoints. No DB changes.

---

## 2. Data Design

No schema changes. The card dict shape produced by `_normalise_per_card()` is unchanged:

```python
{
    "index": int,
    "title": str,
    "content": str,
    "image_url": str | None,   # populated by fallback if LLM omits
    "caption": str | None,
    "question": {
        "text": str,
        "options": list[str],  # exactly 4
        "correct_index": int,
        "explanation": str,
        "difficulty": str
    },
    "is_recovery": bool,
    "chunk_id": str            # stamped by _normalise_per_card
}
```

---

## 3. API Design

No API contract changes. `POST /api/v2/sessions/{id}/chunks/{chunk_id}/cards` signature and response shape are unchanged.

---

## 4. Sequence Diagrams

### Happy Path — chunk with images, NORMAL mode (after fix)

```
frontend
  |
  | GET /sessions/{id}/chunks/{chunk_id}/cards
  v
teaching_router.py
  |
  | generate_per_chunk(session, db, chunk_id)
  v
TeachingService
  |-- get_chunk(db, chunk_id)           → chunk dict
  |-- get_chunk_images(db, chunk_id)    → images list (e.g. [{image_url, caption}])
  |-- resolve _generate_as = "NORMAL"
  |-- max_tokens = CHUNK_MAX_TOKENS_NORMAL (5000 after fix)
  |-- build_chunk_card_prompt(...)      → user_prompt
  |      [user_prompt now says: "Generate COMBINED cards with both content and MCQ"]
  |
  |-- _chat(system_prompt, user_prompt, model="main", max_tokens=5000)
  |      → raw JSON array string from gpt-4o
  |
  |-- _parse_cards(raw)                 → cards_data list
  |
  |-- for each card_dict in cards_data:
  |       if card_dict["image_url"] is None and images:
  |           card_dict["image_url"] = images[0]["image_url"]   ← FALLBACK (new)
  |           card_dict["caption"]   = images[0].get("caption")
  |       _normalise_per_card(card_dict, chunk_id) → normalised card
  |
  └── return cards list
```

### Error Path — LLM returns empty on first call

```
TeachingService
  |-- _chat(primary prompt, model="main")  → empty / unparseable
  |-- _parse_cards → []
  |-- logger.warning(...)
  |-- _chat(retry_system, user_prompt, model="main")   ← FIXED: was "mini"
  |-- _parse_cards → cards_data (or [] → fallback synthetic card)
```

---

## 5. Integration Design

### Change 1 — `prompt_builder.py` lines 140–141

**Current:**
```python
"\nGenerate interleaved [content_card, mcq_card, content_card, mcq_card, ...] pairs "
"for this chunk. Return a JSON array of card objects matching the schema.\n"
```

**Fixed:**
```python
"\nGenerate COMBINED cards with both content and MCQ for this chunk. "
"Each card MUST have a content field (the explanation) AND a question field (the MCQ). "
"Return a JSON array of card objects matching the schema.\n"
```

**Why this location:** `build_chunk_card_prompt()` returns the user message. The system prompt already contains the correct COMBINED CARDS rule (line 1495 of `teaching_service.py`). The user prompt was overriding it with "interleaved" language. Aligning the user prompt with the system prompt removes the contradiction.

---

### Change 2 — `teaching_service.py` image fallback after normalisation loop

Insert after the existing `_normalise_per_card` loop, before the `if not cards:` fallback block:

```python
# Image fallback: if LLM omitted image_url but the chunk has images, assign first image.
if images:
    first_img_url = images[0].get("image_url") or images[0].get("url")
    first_img_caption = images[0].get("caption")
    for card in cards:
        if not card.get("image_url") and first_img_url:
            card["image_url"] = first_img_url
            card["caption"] = first_img_caption
```

**Placement:** After the normalisation loop, before the final fallback synthetic card block. This ensures the fallback only applies to successfully parsed cards, not the synthetic fallback.

---

### Change 3 — `config.py`

```python
# Before
CHUNK_MAX_TOKENS_NORMAL = 2000

# After
CHUNK_MAX_TOKENS_NORMAL = 5000
```

No other constants change. `CHUNK_MAX_TOKENS_STRUGGLING` (3000) and `CHUNK_MAX_TOKENS_FAST` (1200) are intentionally left unchanged pending separate review.

> Note: `CHUNK_MAX_TOKENS_STRUGGLING` at 3000 is lower than the new NORMAL value of 5000. This is inconsistent. It is left as a separate follow-up to avoid scope creep here; the STRUGGLING path is less commonly exercised in the current student population.

---

### Change 4 — `teaching_service.py` model parameter

**Primary call (line 1535):**
```python
# Before
model="mini",

# After
model="main",
```

**Retry call (line 1559):**
```python
# Before
model="mini",

# After
model="main",
```

Both the primary and retry `_chat()` calls must be updated. The retry uses the same model as the primary to ensure consistent instruction-following.

---

## 6. Security Design

No security surface changes. The image fallback injects URLs from `ChunkKnowledgeService.get_chunk_images()`, which only returns URLs stored by the pipeline — no user-controlled input reaches `image_url`.

---

## 7. Observability Design

No new logging added beyond what already exists. The existing `logger.warning` on retry failure and `logger.error` on both-attempts failure cover the degraded paths.

Recommended: after shipping, monitor the share of cards with `image_url != null` from chunks that have images. A rate below 80% indicates the LLM is still ignoring the image instruction and the fallback is carrying all the load. This can be measured from existing `card_interactions` logs if `image_url` is logged at normalisation time.

---

## 8. Error Handling and Resilience

| Scenario | Handling |
|----------|---------|
| LLM returns null `image_url` for all cards, images available | Backend fallback assigns `images[0]` to every card |
| LLM returns alternating cards despite fixed prompt | Backend normalisation does NOT split alternating pairs — this is expected to be resolved by the prompt fix; if it persists, a separate post-processing step will be required |
| gpt-4o timeout at 5000 tokens | `timeout = max(30.0, 5000/80.0 + 15.0)` = 77.5 s — already computed dynamically; no change needed |
| First call empty | Existing retry path, now using gpt-4o |
| Both calls empty | Existing synthetic fallback card — unchanged |

---

## 9. Testing Strategy

### Unit tests (new, in `backend/tests/test_chunk_card_quality.py`)

| Test | Assertion |
|------|-----------|
| `test_prompt_says_combined_not_interleaved` | `build_chunk_card_prompt(...)` return value does not contain the word "interleaved" |
| `test_prompt_says_combined` | Return value contains "COMBINED" |
| `test_image_fallback_assigns_first_image` | When cards have `image_url=None` and images list is non-empty, after fallback all cards have `image_url` set |
| `test_image_fallback_no_op_when_no_images` | When images list is empty, all cards retain `image_url=None` |
| `test_image_fallback_preserves_existing_url` | Card that already has `image_url` is not overwritten |
| `test_chunk_normal_token_budget` | `CHUNK_MAX_TOKENS_NORMAL == 5000` |

### Integration test

Run `generate_per_chunk` with a real chunk against a mocked `_chat` returning a valid cards array with all `image_url: null`. Verify the returned list has `image_url` populated for all cards when the chunk has images.

### Manual smoke test

1. Open a learning session on any concept with at least one chunk that has associated images.
2. Advance through cards and confirm: (a) each card has both explanation text and an MCQ question, (b) at least one card shows an image.
