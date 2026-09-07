# Philosophical Debate Simulator

A lightweight framework for generating and running multi-turn philosophical debates between synthetic "philosopher" agents. The project combines LLM-driven persona generation with external retrieval (Tavily search + Wikipedia enrichment) and a stateful graph orchestration using LangGraph.

## Overview
- Generate two opposing philosopher profiles for a given topic using an LLM.
- Retrieve relevant sources for each philosopher using Tavily, then enrich those sources with summaries from Wikipedia.
- Run a multi-turn (default 5-turn) debate where each philosopher responds to the previous philosopher's question.
- Stream every stage of the debate to the browser over Server-Sent Events (SSE), live as it happens.

## Architecture

This is a monorepo with two decoupled services:

```
Philosophical_debates/
├── backend/                  # FastAPI service exposing the debate pipeline
│   ├── app.py                # POST /debate and POST /debate/stream (SSE)
│   ├── pyproject.toml        # Python deps (uv), own .venv
│   └── philo_agent/          # LangGraph pipeline package
│       ├── graphs/main_graph.py   # single source of truth for the graph
│       ├── graphs/create_philosophers.py
│       ├── retrieval/            # Tavily client + Wikipedia enrichment
│       └── schemas/philosopher.py
├── frontend/                 # React + Vite + TypeScript SPA
│   ├── src/api/streamDebate.ts   # SSE streaming client
│   └── src/App.tsx               # debate UI
├── Dockerfile                # backend image
├── frontend/Dockerfile       # frontend image (nginx static + /debate proxy)
├── docker-compose.yml        # runs both services
└── langgraph.json            # LangGraph Dev config (philo_agent.app:app)
```

### Backend
- FastAPI exposes two endpoints:
  - `POST /debate` — runs the full debate and returns `{"dialogue": ...}` (legacy, blocking).
  - `POST /debate/stream` — streams the debate as Server-Sent Events: `philosophers`, `status`, `turn`, `done`, `error`.
- Streaming is driven by LangGraph's async streaming (`graph.astream(..., stream_mode="updates")`), so each event is flushed to the client as soon as the underlying stage completes.
- The pipeline lives in one place: `backend/philo_agent/graphs/main_graph.py`. `backend/philo_agent/app.py` re-exports the compiled graph for `langgraph dev`.

### Frontend
- React 18 + Vite + TypeScript, dev server on `http://localhost:5173` with a proxy for `/debate` → `http://localhost:8000`.
- Reads the SSE stream with `fetch` + `ReadableStream` (POST by design) and renders philosopher cards, live turns, progress, and a full-dialogue view.

## Deploying
The same codebase deploys natively to **Render** and **Vercel**, or as a container with **Docker Compose**. The frontend talks to the backend through a configurable `VITE_API_URL`, so the two services can live on different hosts.

### Configuration recap
| Env var | Where | Purpose |
|---|---|---|
| `GROQ_API_KEY`, `TAVILY_API_KEY` | backend | LLM + search (required) |
| `CORS_ORIGINS` | backend | Comma-separated origins allowed to call the API from a browser |
| `VITE_API_URL` | frontend (build-time) | Absolute URL of the deployed backend |

### Render
A [`render.yaml`](render.yaml) blueprint defines two services: the Python **backend** web service and a **static-site** frontend. From the repo root:
```bash
render blueprint launch
```
After creation, open each service's dashboard and set the `sync: false` secrets (`TAVILY_API_KEY`, `GROQ_API_KEY`, `CORS_ORIGINS`, `VITE_API_URL`).

### Vercel
- **Frontend:** import `frontend/` as a Vercel project. `vercel.json` provides an SPA rewrite. Set the `VITE_API_URL` environment variable to your deployed backend URL before building.
- **Backend:** Vercel supports FastAPI via a Serverless Function, but the ASTREAM-driven engine isn't serverless-friendly. For a standalone UI/API on Vercel, deploy the frontend there and the backend on Render (or `docker compose up` locally). The `VITE_API_URL` value points the SPA at whichever backend you run.

### Docker
```bash
docker compose up --build
```
- Backend: http://localhost:8000 · Frontend: http://localhost:8080 (nginx proxies `/debate` → backend).

## Requirements
- Python >= 3.11 (project uses 3.13).
- Node.js >= 18 (tested with Node 22/25).
- API keys in a root `.env` file:

```
TAVILY_API_KEY=your_tavily_api_key
GROQ_API_KEY=your_groq_api_key_or_equivalent
```

## Environment
- Backend dependencies are managed with `uv`:
  ```
  cd backend
  uv sync
  ```
- Frontend dependencies with npm:
  ```
  cd frontend
  npm install
  ```

## Run Locally

You need **two terminals**.

### 1. Start the FastAPI backend
```bash
cd backend
uv run uvicorn app:app --reload
```
API is at http://127.0.0.1:8000. Streaming endpoint: `POST /debate/stream`.

### 2. Start the React frontend
```bash
cd frontend
npm run dev
```
Open http://localhost:5173, enter a topic (e.g. "Is free will compatible with determinism?"), and hit **Start Debate**. Turns and progress appear live as the LLM works.

### LangGraph Dev
```bash
langgraph dev
```
Uses `langgraph.json` (entrypoint `philo_agent.app:app`, `python_path: backend`).

### Docker
```bash
docker compose up --build
```
- Backend: http://localhost:8000
- Frontend: http://localhost:8080 (nginx serves the SPA and proxies `/debate` to the backend)

## Next steps (ideas)
- Add unit tests for parsing and retrieval modules.
- Add logging and retry/backoff on external calls (Tavily, Wikipedia, LLM).
- Stream individual turns at the token level instead of per-node events.
- Persist debates for later review.

---
*Note: `notebook.ipynb` and `example.txt`/`example.png` are scratch/demo artifacts kept at the repo root.*