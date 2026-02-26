# Backend Patterns — ADA Platform

## LearningProfile Classification (profile_builder.py)

### Speed (evaluated in order)
```
time_spent > expected * 1.5          → SLOW
time_spent < expected * 0.7 AND attempts <= 1  → FAST
else                                  → NORMAL
```
Brute-force guard: `attempts <= 1` prevents rapid-guesser from being labelled FAST.

### Comprehension (evaluated in order)
```
error_rate >= 0.5 OR quiz_score < 0.5  → STRUGGLING  (checked FIRST)
quiz_score >= 0.8 AND error_rate <= 0.2 AND hints_used <= 2  → STRONG
else  → OK
```

### Engagement (evaluated in order)
```
skip_rate > 0.35            → BORED        (checked FIRST)
hints_used >= 5 AND revisits >= 2  → OVERWHELMED
else                        → ENGAGED
```

### Confidence score
```
error_rate = wrong_attempts / attempts
error_penalty = error_rate * ADAPTIVE_ERROR_PENALTY_WEIGHT  (0.40)
hint_penalty  = (min(hints_used, 10) / 10) * ADAPTIVE_HINT_PENALTY_WEIGHT  (0.20)
confidence    = clamp(quiz_score - error_penalty - hint_penalty, 0.0, 1.0)
```

### Recommended next step (evaluated in order)
```
STRUGGLING AND has_unmet_prereq  → REMEDIATE_PREREQ
STRUGGLING                       → ADD_PRACTICE
FAST AND STRONG                  → CHALLENGE
else                             → CONTINUE
```

## GenerationProfile Lookup Table (generation_profile.py)

| Speed  | Comp.      | depth  | reading    | step  | analogy | fun | cards | practice | ckpt | lines | emoji   |
|--------|-----------|--------|------------|-------|---------|-----|-------|----------|------|-------|---------|
| SLOW   | STRUGGLING| HIGH   | KID_SIMPLE | True  | 0.8     | 0.4 | 12    | 7        | 2    | 2     | SPARING |
| SLOW   | OK        | HIGH   | SIMPLE     | True  | 0.6     | 0.3 | 11    | 6        | 2    | 3     | NONE    |
| SLOW   | STRONG    | MEDIUM | SIMPLE     | True  | 0.5     | 0.3 | 10    | 5        | 3    | 3     | NONE    |
| NORMAL | STRUGGLING| HIGH   | SIMPLE     | True  | 0.7     | 0.3 | 11    | 6        | 2    | 3     | SPARING |
| NORMAL | OK        | MEDIUM | STANDARD   | False | 0.5     | 0.2 | 9     | 4        | 3    | 4     | NONE    |
| NORMAL | STRONG    | LOW    | STANDARD   | False | 0.3     | 0.2 | 8     | 3        | 4    | 4     | NONE    |
| FAST   | STRUGGLING| HIGH   | SIMPLE     | True  | 0.6     | 0.3 | 10    | 6        | 2    | 3     | NONE    |
| FAST   | OK        | LOW    | STANDARD   | False | 0.3     | 0.2 | 8     | 3        | 4    | 5     | NONE    |
| FAST   | STRONG    | LOW    | STANDARD   | False | 0.2     | 0.2 | 7     | 3        | 5    | 5     | NONE    |

### Engagement modifiers (applied after base lookup)
- BORED:       fun_level += 0.3 (cap 1.0); emoji_policy = SPARING; card_count -= 1 (floor 7)
- OVERWHELMED: card_count -= 3 (floor 7); practice_count -= 1 (floor 3); step_by_step = True; analogy_level += 0.2 (cap 1.0)
- ENGAGED:     no change

## Adaptive Router Error Mapping
- `"Concept not found"` in ValueError message → HTTP 404
- Other ValueError (LLM failure) → HTTP 502
- Any other Exception → HTTP 500

## prompt_builder.py — Key Behaviour
- concept_text hard-truncated at 3000 chars
- latex expressions limited to first 10
- System prompt embeds full AdaptiveLessonContent JSON schema verbatim
- Mode-specific blocks: SLOW LEARNER, FAST/STRONG LEARNER, BORED LEARNER (conditional)
- Difficulty ramp: first card difficulty=1, last=5, space evenly
