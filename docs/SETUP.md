# Setup & Quickstart

## Requirements

- **Python 3.11** (recommended). The pinned `pydantic==2.8.2` in `requirements.txt` ships a `pydantic-core` wheel that does not build on Python 3.14 — use 3.11 (or another 3.11/3.12 environment) to avoid a source build failure.
- Node.js (for the frontend build)

## Option 1: Easy start (Windows)

Double-click `run_app.bat` in the project root. It checks the Python installation, installs dependencies if needed, finds an available port (8000/8001/8002), and starts the server.

## Option 2: Manual setup

1. **Environment variables**
   - Copy `.env.example` to `.env` and fill in whichever LLM provider keys you have (OpenRouter, OpenAI, and/or Gemini). None are required — without any key configured, the chat still responds with a non-LLM fallback message.

2. **Install backend dependencies**
   ```
   pip install -r requirements.txt
   ```

3. **Build the frontend and run the server**
   ```
   cd frontend && npm install && npm run build && cd ..
   uvicorn backend.main:app --reload --port 8000
   ```
   Open http://localhost:8000.

   For hot-reload development (separate backend + frontend dev server), use `run_full_app.bat` on Windows or run the equivalent two commands (`uvicorn backend.main:app --reload` and `npm run dev` inside `frontend/`) manually on other platforms.

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
