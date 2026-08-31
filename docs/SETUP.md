# Setup & Quickstart

## Requirements

- **Python 3.11** (recommended). The pinned `pydantic==2.8.2` in `requirements.txt` ships a `pydantic-core` wheel that does not build on Python 3.14 — use 3.11 (or another 3.11/3.12 environment) to avoid a source build failure.
- Node.js (for the frontend build)

## Quickstart

1. **Environment variables**
   - Copy `.env.example` to `.env` and configure any LLM provider keys (OpenRouter, OpenAI, and/or Gemini). Without keys configured, fallback responses are used.

2. **Install backend dependencies**
   ```
   pip install -r requirements.txt
   ```

3. **Build the frontend and run the server**
   ```
   cd frontend && npm install && npm run build && cd ..
   uvicorn backend.main:app --port 8000
   ```
   Open http://localhost:8000.

   For development with hot reloading (separate backend and frontend dev servers):
   - Terminal 1: `uvicorn backend.main:app --reload --port 8000`
   - Terminal 2: `cd frontend && npm run dev`

4. **Optional: run tests**
   ```
   pytest -q
   cd frontend && npm test
   ```

## Environment flags

See `.env.example` for the full list. Key ones:

- `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` — OpenRouter provider (default model `z-ai/glm-4.5-air:free`)
- `OPENAI_API_KEY` / `OPENAI_MODEL` — OpenAI provider (default model `gpt-4o-mini`)
- `GEMINI_API_KEY` (`_2`, `_3` for extra fallback keys) / `GEMINI_FLASH_MODEL` / `GEMINI_PRO_MODEL` — Gemini provider
- `DEBUG_LLM` — verbose logging inside the LLM client
- `SOUND_NOTIFICATIONS` — UI completion beep

See the main [README](../README.md) for architecture and the demo flow.
