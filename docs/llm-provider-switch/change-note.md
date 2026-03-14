# LLM Provider Switch: LibertAI → OpenAI

## Date
2026-03-14

## Summary
Switched the LLM provider from LibertAI (Qwen3-coder-next) to the official OpenAI API (GPT-4o / GPT-4o-mini).

## Motivation
User added OpenAI credits. LibertAI/Qwen3 is no longer used.

## Change Made
Single file edit: `backend/.env`

| Variable | Before | After |
|----------|--------|-------|
| `OPENAI_API_KEY` | LibertAI token (`0ed288ae...`) | OpenAI key (`sk-proj-...`) |
| `OPENAI_BASE_URL` | `https://api.libertai.io/v1` | *(deleted — defaults to `https://api.openai.com/v1`)* |
| `OPENAI_MODEL` | `qwen3-coder-next` | `gpt-4o` |
| `OPENAI_MODEL_MINI` | `qwen3-coder-next` | `gpt-4o-mini` |

## No Code Changes
The codebase is 100% environment-variable-driven for LLM routing. All model names and the base URL are read from `config.py` which reads from `.env`. Zero hardcoded LibertAI or Qwen references exist in any production file.

## Scope of Impact
Every LLM call in the system now routes to OpenAI:
- Batch card generation (`api/teaching_service.py`)
- Single adaptive card generation (`adaptive/adaptive_engine.py`)
- Socratic chat and hints
- MCQ regeneration
- Translation (`api/main.py`)
- Image annotation (`images/extract_images.py`)
- PDF extraction pipeline (`extraction/llm_extractor.py`)

## Rollback
Restore `backend/.env` lines:
```
OPENAI_BASE_URL=https://api.libertai.io/v1
OPENAI_MODEL=qwen3-coder-next
OPENAI_MODEL_MINI=qwen3-coder-next
OPENAI_API_KEY=<LibertAI key>
```
And restart uvicorn.
