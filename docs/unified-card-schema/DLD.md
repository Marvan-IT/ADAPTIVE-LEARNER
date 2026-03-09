# Detailed Low-Level Design — Unified Card Schema

**Feature slug:** `unified-card-schema`
**Date:** 2026-03-06
**Status:** Approved for implementation

---

## 1. Component Breakdown

| Component | File | Responsibility |
|-----------|------|----------------|
| Card system prompt | `backend/src/api/prompts.py` — `build_cards_system_prompt()` | Instructs LLM to produce unified schema; removes card_type / quick_check / questions[] instructions |
| Card user prompt | `backend/src/api/prompts.py` — `build_cards_user_prompt()` | Adds available-images block listing descriptions and 0-based indices |
| CHECKIN card factory | `backend/src/api/prompts.py` — `build_mid_session_checkin_card()` | Update static dict to unified schema shape (remove `card_type`, `quick_check`, `questions`) |
| Card post-processor | `backend/src/api/teaching_service.py` — `generate_cards()` | Remove `pop("image_indices")` and round-robin; add index-resolution loop; remove sub-section cap; remove `ADAPTIVE_CARD_CEILING` import |
| Remediation prompt | `backend/src/api/teaching_service.py` — `_build_remediation_prompt()` | Update inline JSON example to unified schema |
| Config | `backend/src/config.py` | Remove `ADAPTIVE_CARD_CEILING` constant |
| Card schemas | `backend/src/api/teaching_schemas.py` — `LessonCard`, `CardsResponse` | Update Pydantic models to reflect unified card shape |
| Card view | `frontend/src/components/learning/CardLearningView.jsx` | Remove TF handlers; unify MCQ path to `card.question`; add `[IMAGE:N]` inline rendering; fix card counter |
| Image renderer | `frontend/src/components/learning/ConceptImage.jsx` | No changes — component is already correct |

---

## 2. Data Design

### 2.1 New Unified Card Schema (LLM Output Contract)

The LLM must return a single JSON object with a `cards` array. Each element of the array is a card object. Two card shapes exist.

#### Standard Card (all content cards)

```json
{
  "title": "String — concise card title",
  "content": "String — markdown. May contain [IMAGE:N] markers at contextually relevant positions.",
  "image_indices": [0, 2],
  "question": {
    "text": "String — the MCQ question stem",
    "options": ["String A", "String B", "String C", "String D"],
    "correct_index": 0,
    "explanation": "String — why the correct option is right"
  }
}
```

**Field specifications:**

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `title` | string | Yes | Non-empty. Concise (3–8 words). |
| `content` | string | Yes | Markdown. May embed `[IMAGE:N]` tokens. No HTML tags. Max ~600 words. |
| `image_indices` | int[] | Yes | 0-based indices into the concept's available images list. Empty array `[]` if no image. Each index used at most once per card. Must be within range `[0, len(available_images) - 1]`. |
| `question.text` | string | Yes | The MCQ question stem. Math notation with `$...$`. |
| `question.options` | string[] | Yes | Exactly 4 options. |
| `question.correct_index` | int | Yes | 0-based index into `options`. Value in `[0, 3]`. |
| `question.explanation` | string | Yes | 1–3 sentences explaining why the correct option is right. |

#### CHECKIN Card (backend-generated, no LLM involvement)

```json
{
  "title": "Quick Check-In",
  "content": "How are you feeling about the material so far?",
  "image_indices": [],
  "options": [
    "I'm getting it!",
    "It's a bit tricky",
    "I'm lost",
    "I need a break"
  ]
}
```

Note: CHECKIN cards have no `question` field. They have a top-level `options` array instead. The frontend detects CHECKIN by the absence of `question` combined with the presence of `options` at the card level.

**CHECKIN detection logic:**
```javascript
const isCheckin = !card.question && Array.isArray(card.options) && card.options.length > 0;
```

### 2.2 Backend-Resolved Card Shape (API Response)

After backend post-processing, each card delivered to the frontend has:

```json
{
  "index": 0,
  "title": "...",
  "content": "... [IMAGE:0] ...",
  "image_indices": [0],
  "images": [
    {
      "url": "/images/PREALG.C1.S1.INTRODUCTION/fig1.jpeg",
      "filename": "fig1.jpeg",
      "description": "A number line showing integers from -5 to 5.",
      "caption": "A number line showing integers from -5 to 5.",
      "image_type": "DIAGRAM",
      "width": 600,
      "height": 200
    }
  ],
  "question": {
    "text": "...",
    "options": ["A", "B", "C", "D"],
    "correct_index": 0,
    "explanation": "..."
  },
  "difficulty": 3
}
```

`images` is populated by the backend resolver. `image_indices` remains in the response as a reference. The frontend uses `images` (resolved objects) for `<ConceptImage>` rendering and `image_indices` only as fallback lookup keys when parsing `[IMAGE:N]` markers.

### 2.3 Removed Fields

The following fields **no longer appear** in any card:

| Field | Location in old schema | Removal notes |
|-------|------------------------|---------------|
| `card_type` | Card root | Removed from LLM prompt and post-processor. `setdefault("card_type", "TEACH")` line removed. |
| `quick_check` | Card root | Removed from LLM prompt. All cards use `question` instead. |
| `questions` | Card root | Removed. The QUESTION card type no longer exists. |

### 2.4 Caching

No change to caching strategy. Generated cards are cached in `session.presentation_text` as a JSON string (existing behaviour). The cache key is the session ID. Cache is invalidated by starting a new session.

### 2.5 Data Retention

No change. Card data lives in `session.presentation_text` (text column on `teaching_sessions`). Retention follows existing session lifecycle.

---

## 3. API Design

### 3.1 `GET /api/v2/sessions/{session_id}/cards`

No change to the endpoint path, method, or authentication. The **response shape** changes.

**Before (old schema — for reference):**

```json
{
  "session_id": "...",
  "concept_id": "...",
  "concept_title": "...",
  "style": "default",
  "phase": "CARDS",
  "cards": [
    {
      "index": 0,
      "card_type": "TEACH",
      "title": "...",
      "content": "...",
      "image_indices": [],
      "quick_check": { "question": "...", "options": [...], "correct_index": 0, "explanation": "..." },
      "questions": [],
      "images": []
    }
  ],
  "total_questions": 6
}
```

**After (new unified schema):**

```json
{
  "session_id": "...",
  "concept_id": "...",
  "concept_title": "...",
  "style": "default",
  "phase": "CARDS",
  "cards": [
    {
      "index": 0,
      "title": "...",
      "content": "The number line below [IMAGE:0] shows how integers are ordered.",
      "image_indices": [0],
      "images": [
        {
          "url": "/images/concept_id/fig1.jpeg",
          "filename": "fig1.jpeg",
          "description": "...",
          "caption": "...",
          "image_type": "DIAGRAM",
          "width": 600,
          "height": 200
        }
      ],
      "question": {
        "text": "...",
        "options": ["A", "B", "C", "D"],
        "correct_index": 2,
        "explanation": "..."
      },
      "difficulty": 2
    }
  ],
  "total_questions": 0
}
```

**Notes:**
- `total_questions` is set to `0` (field retained for backward compatibility with any client code that reads it, but no longer computed as a meaningful count).
- `card_type`, `quick_check`, and `questions` fields are absent.

### 3.2 Updated Pydantic Schemas (`teaching_schemas.py`)

```python
class CardMCQ(BaseModel):
    text: str
    options: list[str] = Field(..., min_length=4, max_length=4)
    correct_index: int = Field(..., ge=0, le=3)
    explanation: str = ""

class LessonCard(BaseModel):
    index: int
    title: str
    content: str = Field(..., description="Markdown content, may contain [IMAGE:N] markers")
    image_indices: list[int] = Field(default_factory=list)
    images: list[dict] = Field(default_factory=list)
    question: CardMCQ | None = Field(default=None, description="None for CHECKIN cards")
    options: list[str] | None = Field(default=None, description="Present only on CHECKIN cards")
    difficulty: int = Field(default=3, ge=1, le=5)

class CardsResponse(BaseModel):
    session_id: UUID
    concept_id: str
    concept_title: str
    style: str
    phase: str
    cards: list[LessonCard]
    total_questions: int = 0
```

**Removed Pydantic models:**
- `CardQuestion` — no longer needed (replaced by `CardMCQ`)

### 3.3 Versioning

No version bump. The card endpoint is `GET /api/v2/sessions/{id}/cards` and remains on v2. This is a schema change within an existing endpoint, not a new API surface.

---

## 4. Sequence Diagrams

### 4.1 Happy Path — Card Generation

```
Frontend          Backend (teaching_service)        LLM (gpt-4o)
    |                        |                          |
    | GET /sessions/{id}/cards
    |----------------------->|                          |
    |                        | get_concept_detail()     |
    |                        | → concept, images[]      |
    |                        |                          |
    |                        | build_cards_user_prompt()|
    |                        | → includes:              |
    |                        |   "AVAILABLE IMAGES:     |
    |                        |    Index 0: {desc}       |
    |                        |    Index 1: {desc}"      |
    |                        |                          |
    |                        | build_cards_system_prompt
    |                        | → unified schema instructions
    |                        |                          |
    |                        |──── LLM call ───────────►|
    |                        |                          | generates:
    |                        |                          | cards[] with
    |                        |                          | image_indices
    |                        |                          | [IMAGE:N] in content
    |                        |◄─── cards JSON ──────────|
    |                        |                          |
    |                        | post_process():           |
    |                        |  for each card:           |
    |                        |   validate image_indices  |
    |                        |   resolve → images[]      |
    |                        |   drop invalid indices    |
    |                        |   ensure question or None |
    |                        |   set difficulty default  |
    |                        |                          |
    |◄── CardsResponse ──────|                          |
    |  (cards with images[]) |                          |
    |                        |                          |
    | render cards            |                          |
    | for [IMAGE:N] in content:
    | → split content         |                          |
    | → render <ConceptImage>  |                          |
    |   inline at marker pos  |                          |
```

### 4.2 Error Path — LLM Returns Out-of-Range Image Index

```
Backend post_process():
  for idx in card["image_indices"]:
    if idx < 0 or idx >= len(available_images):
      logger.warning("card %d: image_index %d out of range (max %d) — dropping",
                     ci, idx, len(available_images) - 1)
      continue  # skip invalid index, do not raise
    resolved = available_images[idx]
    card["images"].append({...resolved, "caption": resolved.get("description") or card["title"]})
```

No exception is raised. The card is served without the invalid image. A warning is written to the application log.

### 4.3 CHECKIN Card Insertion

CHECKIN cards are inserted by the backend after the LLM call, at every `CARDS_MID_SESSION_CHECK_INTERVAL` (= 12) position. They are never sent to the LLM.

```
generate_cards():
  raw_cards = llm_output["cards"]
  for i, card in enumerate(raw_cards):
    cards_with_checkins.append(card)
    if (i + 1) % CARDS_MID_SESSION_CHECK_INTERVAL == 0 and (i + 1) < len(raw_cards):
      checkin = build_mid_session_checkin_card()   # returns unified schema dict
      cards_with_checkins.append(checkin)
  re-index all cards
```

`build_mid_session_checkin_card()` returns:
```python
{
    "title": "Quick Check-In",
    "content": "How are you feeling about the material so far?",
    "image_indices": [],
    "images": [],
    "options": ["I'm getting it!", "It's a bit tricky", "I'm lost", "I need a break"],
    # no "question" key
}
```

---

## 5. Integration Design

### 5.1 `build_cards_system_prompt()` — New Instructions

Replace the entire CARD TYPES section and OUTPUT FORMAT section. The new system prompt instructs:

```
CARD SCHEMA — every card you generate must have exactly these fields:

{
  "title": "<concise card title>",
  "content": "<markdown. Embed [IMAGE:N] at the exact line where image N is contextually relevant.>",
  "image_indices": [<0-based indices of images used in this card>],
  "question": {
    "text": "<MCQ question stem>",
    "options": ["<A>", "<B>", "<C>", "<D>"],
    "correct_index": <0-based int>,
    "explanation": "<why the correct option is right>"
  }
}

RULES:
- No "card_type" field — all cards are the same type.
- Every card has exactly ONE question (the MCQ above). No True/False. No quick_check. No questions[].
- If you reference an image in your content, write [IMAGE:N] at the position in the text where the
  image should appear (N = 0-based index from the AVAILABLE IMAGES list). Also add N to image_indices.
- If no image is relevant to this card, set image_indices to [] and omit [IMAGE:N] from content.
- Generate AS MANY cards as the content requires. There is no upper limit.
- TEXTBOOK ACCURACY IS NON-NEGOTIABLE: every key definition, formula, theorem, and property must appear.
- WORKED EXAMPLES ARE MANDATORY — include every step of every worked example in the source.
```

**Removed instructions:**
- CARD TYPES 1–6 (TEACH, EXAMPLE, VISUAL, QUESTION, RECAP, FUN)
- Rules for `quick_check` and `questions` fields
- The IMAGE PLACEMENT RULE section (replaced by inline [IMAGE:N] instructions above)

**Retained instructions:**
- EXPLANATION RULES block (child-friendly language, markdown only, no HTML, etc.)
- CARD COUNT RULE (no upper limit)
- Adaptive student profile block (appended by `_build_card_profile_block()`)
- Interests, style, language instructions

### 5.2 `build_cards_user_prompt()` — Available Images Block

Replace the current `image_text` construction with an indexed format:

```python
if diagrams:
    desc_lines = []
    max_imgs = min(len(sub_sections) * 2, len(diagrams))
    for i, img in enumerate(diagrams[:max_imgs]):
        vision_desc = (img.get("description") or "")[:200]
        filename = img.get("filename", "unknown")
        if vision_desc:
            desc_lines.append(f"  Index {i}: {vision_desc} (filename: {filename})")
    image_text = (
        "\n\nAVAILABLE IMAGES (use 0-based index to assign to cards):\n"
        + "\n".join(desc_lines)
        + "\n\nFor each card: set image_indices to the index of the image that belongs here "
        "(if any). Embed [IMAGE:N] in the content text at the exact position where the image "
        "should appear inline."
    )
```

The critical change: images are now listed as `Index 0: ...`, `Index 1: ...` matching the 0-based `image_indices` the LLM must emit. The old text said "Image placement is handled automatically — you do NOT need to assign image_indices", which was incorrect and caused the LLM's assignments to be discarded.

### 5.3 `teaching_service.generate_cards()` — Post-Processor Changes

**Remove** (lines ~737–764 in current file):
```python
# OLD — to be removed entirely
card.pop("image_indices", None)
...
# Distribute any remaining images (not yet assigned) round-robin
remaining = [img for img in useful_images if img["filename"] not in assigned_filenames]
for i, img in enumerate(remaining):
    target_card = raw_cards[i % len(raw_cards)]
    ...
```

**Replace with:**
```python
# NEW — index-based resolution
available_images = useful_images  # already filtered list of image dicts

for ci, card in enumerate(raw_cards):
    raw_indices = card.get("image_indices") or []
    resolved = []
    for idx in raw_indices:
        if not isinstance(idx, int) or idx < 0 or idx >= len(available_images):
            logger.warning(
                "[image-resolve] session=%s card=%d: invalid index %s (available: %d) — dropping",
                str(session.id), ci, idx, len(available_images),
            )
            continue
        img = dict(available_images[idx])
        img["caption"] = img.get("description") or card.get("title", "")
        resolved.append(img)
    card["images"] = resolved
    # Keep image_indices in card dict for frontend reference — do NOT pop
```

**Remove sub-section cap** (lines ~547–556 in current file):
```python
# REMOVE this block:
elif len(sub_sections) > 10:
    sub_sections = self._group_by_major_topic(sub_sections)
    if len(sub_sections) > 10:
        sub_sections = self._group_sub_sections(sub_sections, max_chars=4000, max_cards=10)
```

**Remove ADAPTIVE_CARD_CEILING import** (line ~22):
```python
# REMOVE: ADAPTIVE_CARD_CEILING from import
from config import (
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_MODEL_MINI,
    MASTERY_THRESHOLD, MAX_SOCRATIC_EXCHANGES, SOCRATIC_MAX_ATTEMPTS,
    CARDS_MID_SESSION_CHECK_INTERVAL,
    # ADAPTIVE_CARD_CEILING removed
)
```

**Remove card_type post-processing** (in the per-card loop, lines ~684–708):
```python
# REMOVE:
card.setdefault("card_type", "TEACH")
card.setdefault("quick_check", None)
card_type = card["card_type"]
if card_type == "QUESTION":
    questions = card.get("questions", [])
    mcq_qs = [q for q in questions if q.get("type") == "mcq"][:2]
    tf_qs = [q for q in questions if q.get("type") == "true_false"][:2]
    ...
else:
    card["questions"] = []
    qc = card.get("quick_check")
    if qc and not isinstance(qc, dict):
        card["quick_check"] = None
```

**Replace with:**
```python
# NEW — validate and normalise unified question
q = card.get("question")
if isinstance(q, dict):
    # Ensure options is a list of 4 strings
    opts = q.get("options", [])
    if not isinstance(opts, list) or len(opts) != 4:
        logger.warning(
            "[card-schema] session=%s card=%d: question.options invalid — nullifying question",
            str(session.id), ci,
        )
        card["question"] = None
    else:
        # Clamp correct_index to valid range
        ci_val = q.get("correct_index", 0)
        if not isinstance(ci_val, int) or ci_val < 0 or ci_val >= len(opts):
            q["correct_index"] = 0
        card["question"] = {
            "text": str(q.get("text", "")),
            "options": [str(o) for o in opts],
            "correct_index": q["correct_index"],
            "explanation": str(q.get("explanation", "")),
        }
else:
    card["question"] = None
```

### 5.4 `_build_remediation_prompt()` — Schema Alignment

The inline JSON example string must be updated. Replace:

```python
# OLD
f'{{"cards": [{{"card_type": "TEACH", "title": "...", "content": "...", '
f'"image_indices": [], "quick_check": {{"question": "...", "options": ["A","B","C","D"], '
f'"correct_index": 0, "explanation": "..."}}, "questions": []}}]}}\n'
```

With:

```python
# NEW
f'{{"cards": [{{"title": "...", "content": "...", "image_indices": [], '
f'"question": {{"text": "...", "options": ["A","B","C","D"], "correct_index": 0, '
f'"explanation": "..."}}}}]}}\n'
```

Also update the inline instruction text:

```python
# REMOVE:
f"Each TEACH card MUST have a quick_check MCQ.\n"
f"Each EXAMPLE card MUST have a quick_check MCQ.\n"
f"RECAP card: quick_check is null, questions is [].\n"

# REPLACE WITH:
f"Every card MUST have a question (MCQ). No card_type, no quick_check, no questions[].\n"
```

---

## 6. Security Design

No changes to authentication or authorization. All card endpoints remain protected by `APIKeyMiddleware` (existing platform hardening).

**Input validation additions:**

- Backend post-processor validates all `image_indices` values as non-negative integers within range — prevents a maliciously crafted LLM response from causing an array out-of-bounds error.
- `correct_index` is clamped to `[0, 3]` — prevents a negative or out-of-range index from causing silent wrong-answer scoring in the frontend.

---

## 7. Observability Design

### 7.1 New Log Points

| Location | Level | Message format |
|----------|-------|----------------|
| `generate_cards()` — invalid image index | WARNING | `[image-resolve] session={id} card={N}: invalid index {idx} (available: {count}) — dropping` |
| `generate_cards()` — invalid question | WARNING | `[card-schema] session={id} card={N}: question.options invalid — nullifying question` |
| `generate_cards()` — card count | INFO | `[cards-generated] session={id} concept={id} cards={N} with_images={M}` |

### 7.2 Existing Metrics

No new metrics. The existing `[cards]` log line in `generate_cards()` is retained and updated to log the new field names.

---

## 8. Error Handling and Resilience

### 8.1 LLM Returns Non-JSON or Malformed Cards

Existing `_generate_cards_single()` error handling is unchanged. It attempts JSON parse, then `_salvage_truncated_json()`, then raises `ValueError` after 3 retries.

### 8.2 LLM Returns Cards Missing `question`

The post-processor checks `isinstance(card.get("question"), dict)`. If missing or malformed, `card["question"]` is set to `None`. The card is still served. The frontend handles `question === null` by not rendering the MCQ block and setting `canProceed = true` immediately.

### 8.3 LLM Returns Invalid `image_indices`

Validated per card. Each invalid index is logged and dropped. The card is served with whatever valid images remain.

### 8.4 Frontend Parses Unrecognised `[IMAGE:N]` Token

If N is not a valid integer or N is out of range of `card.images`, the marker is rendered as an empty `<span>` (no visible effect, no error). Safe fallback.

---

## 9. Testing Strategy

### 9.1 Unit Tests (`backend/tests/`)

| Test | File | Coverage |
|------|------|----------|
| `test_build_cards_system_prompt_no_card_type` | `test_prompts.py` | Assert `"card_type"` does not appear in prompt; assert `"question"` schema appears |
| `test_build_cards_user_prompt_image_index_format` | `test_prompts.py` | Assert `"Index 0:"` format in prompt when images present |
| `test_image_index_resolution_valid` | `test_teaching_service.py` | Given raw cards with `image_indices: [0]` and one available image, assert resolved card has `images[0].url` set |
| `test_image_index_resolution_out_of_range` | `test_teaching_service.py` | Given `image_indices: [99]` and 2 available images, assert `card.images == []` and warning is logged |
| `test_question_validation_valid` | `test_teaching_service.py` | Valid question dict passes through unchanged |
| `test_question_validation_wrong_options_count` | `test_teaching_service.py` | Question with 3 options is nullified |
| `test_question_validation_correct_index_clamp` | `test_teaching_service.py` | `correct_index: 5` is clamped to 0 |
| `test_checkin_card_shape` | `test_prompts.py` | `build_mid_session_checkin_card()` returns dict with `options` list and no `question` key |
| `test_config_no_adaptive_card_ceiling` | `test_config.py` | `ADAPTIVE_CARD_CEILING` is not importable from `config` |

### 9.2 Integration Test

```
test_generate_cards_end_to_end:
  Given: mocked LLM that returns 3 unified-schema cards with image_indices
  Given: 2 available images in knowledge_service
  When: generate_cards() is called
  Then: response has 3 cards, each with images[] populated correctly
  Then: no card has card_type, quick_check, or questions fields
```

### 9.3 Frontend Unit Tests (Jest / Vitest)

| Test | Coverage |
|------|----------|
| `parseInlineImages splits content at [IMAGE:0]` | Split algorithm: returns array of alternating text and image elements |
| `parseInlineImages ignores invalid indices` | Index 99 with 2 images returns empty span |
| `parseInlineImages case insensitive` | `[image:0]` and `[IMAGE:0]` both parse |
| `canProceed true when question is null` | CHECKIN-like card (no question) — canProceed is always true |
| `canProceed false until MCQ answered` | Standard card — canProceed false until correct answer |

### 9.4 End-to-End Test

Manual smoke test on Section 1.1 (Prealgebra) after pipeline re-run:
1. Start a new session for concept `PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS`
2. Fetch cards — assert no `card_type` field, no `quick_check` field
3. Assert at least one card has `images` list populated with a valid image object
4. Verify `[IMAGE:N]` markers in content render as inline `<ConceptImage>` components in the browser

---

## Frontend Specification — `CardLearningView.jsx`

### 9.5 `[IMAGE:N]` Parsing Algorithm

Add a pure utility function:

```javascript
/**
 * parseInlineImages(content, images)
 *
 * Splits a card content string at [IMAGE:N] markers.
 * Returns an array of segments: string segments and image objects.
 *
 * @param {string} content  - Card content markdown string
 * @param {object[]} images - Resolved image objects (card.images)
 * @returns {Array<{type: 'text', value: string} | {type: 'image', img: object}>}
 */
function parseInlineImages(content, images) {
  if (!content) return [{ type: "text", value: "" }];
  const parts = [];
  // Case-insensitive match for [IMAGE:N] or [image:N]
  const regex = /\[IMAGE:(\d+)\]/gi;
  let lastIndex = 0;
  let match;
  while ((match = regex.exec(content)) !== null) {
    const idx = parseInt(match[1], 10);
    // Push preceding text segment (may be empty string — ReactMarkdown handles it)
    if (match.index > lastIndex) {
      parts.push({ type: "text", value: content.slice(lastIndex, match.index) });
    }
    // Push image segment if index is valid
    if (Number.isInteger(idx) && idx >= 0 && idx < (images?.length ?? 0)) {
      parts.push({ type: "image", img: images[idx] });
    }
    // If invalid index, push nothing — marker disappears silently
    lastIndex = regex.lastIndex;
  }
  // Push trailing text
  if (lastIndex < content.length) {
    parts.push({ type: "text", value: content.slice(lastIndex) });
  }
  return parts.length > 0 ? parts : [{ type: "text", value: content }];
}
```

### 9.6 Inline Rendering in `CardLearningView.jsx`

Replace the current content rendering block:

```jsx
// OLD
<div className="markdown-content">
  <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
    {card.content}
  </ReactMarkdown>
</div>

// NEW — inline image support
{parseInlineImages(card.content, card.images).map((segment, i) =>
  segment.type === "image" ? (
    <ConceptImage key={i} img={segment.img} maxWidth="560px" />
  ) : (
    <div key={i} className="markdown-content">
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
        {segment.value}
      </ReactMarkdown>
    </div>
  )
)}
```

This applies to the main card body. The VISUAL card variant (currently renders images at top) is replaced by this same inline rendering — the VISUAL card type no longer exists.

### 9.7 Question Rendering — Remove TF, Unify MCQ

Replace the dual-schema question state machine.

**Remove:**
- `mcqPool`, `tfPool`, `currentMcq`, `currentTf` variables
- `handleTfAnswer()` callback
- `tfIdx`, `tfCorrect`, `tfFeedback` from `cardStates`
- True/False render block
- `tfPool.length === 0 || cs.tfCorrect` in `canProceed`

**Replace with:**

```javascript
// Single MCQ per card
const question = card?.question ?? null;

const canProceed = useMemo(() => {
  if (!card) return false;
  if (isCheckin(card)) return cs.checkinDone;
  // No question — advance freely
  if (!question) return true;
  // Has question — must answer correctly
  return cs.mcqCorrect;
}, [card, question, cs]);

// MCQ answer handler
const handleMcqAnswer = useCallback((optionIndex) => {
  if (cs.mcqCorrect || cs.mcqFeedback) return;
  const correct = optionIndex === question.correct_index;
  // ... XP, analytics, sendAssistMessage on wrong — same as before ...
  updateCardState(currentCardIndex, {
    mcqFeedback: { correct, explanation: question.explanation, answer: optionIndex },
    ...(correct ? { mcqCorrect: true } : {}),
  });
}, [cs, question, currentCardIndex, updateCardState, sendAssistMessage]);
```

MCQ render block accesses `card.question` directly:

```jsx
{question && (
  <MCQBlock
    question={question}
    cardState={cs}
    onAnswer={handleMcqAnswer}
  />
)}
```

`MCQBlock` is the existing `QuickCheckBlock` component, renamed and updated to accept `question.text` instead of `quickCheck.question`:

```jsx
// QuickCheckBlock renamed to MCQBlock; prop shape changes:
// OLD: quickCheck.question  →  NEW: question.text
// OLD: quickCheck.correct_index  →  NEW: question.correct_index
// OLD: quickCheck.explanation  →  NEW: question.explanation
```

### 9.8 Card Counter Fix

Replace the subtitle line in the card header:

```jsx
// OLD
{conceptTitle} — {t("learning.cardProgress", { current: currentCardIndex + 1, total: cards.length })}

// NEW
{conceptTitle} — {t("learning.cardN", { n: currentCardIndex + 1 })}
```

Add i18n key `learning.cardN` to all 13 locale files:
```json
"cardN": "Card {{n}}"
```

The existing `learning.cardProgress` key (`"Card {{current}} of {{total}}"`) can be retained for backward compatibility but should not be used in new rendering.

---

## Key Decisions Requiring Stakeholder Input

1. **`VISUAL` card removal in remediation:** Remediation cards are TEACH + EXAMPLE + one RECAP. No VISUAL-type cards were ever generated there. Confirm this is still the intended remediation mix after schema unification (TEACH → standard cards with question; RECAP → standard card with question or no question?).

2. **`difficulty` field retention:** The unified schema does not include `difficulty` in the LLM-output contract shown above. The adaptive engine and frontend currently read `card.difficulty` for the star-badge display and for the adaptive blending algorithm. Confirm: should `difficulty` be added back to the unified LLM JSON schema, or should the backend assign a default of 3 for all cards?

3. **`QuickCheckBlock` rename vs keep:** `QuickCheckBlock` can be renamed to `MCQBlock` for clarity. This is a safe internal refactor. Confirm whether this rename should happen now or be deferred.

4. **i18n key `learning.cardN` in all 13 locales:** The implementation must add this key to all 13 locale JSON files (`en`, `ar`, `de`, `es`, `fr`, `hi`, `ja`, `ko`, `ml`, `pt`, `si`, `ta`, `zh`). Confirm whether machine-translated values are acceptable for the initial release, or whether native speaker review is required before shipping.
