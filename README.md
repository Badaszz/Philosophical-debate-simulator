# Philosophical Debate Simulator

A lightweight framework for generating and running multi-turn philosophical debates between synthetic "philosopher" agents. The project combines LLM-driven persona generation with external retrieval (Tavily search + Wikipedia enrichment) and a stateful graph orchestration using LangGraph.

## Overview
- Generate two opposing philosopher profiles for a given topic using an LLM.
- Retrieve relevant sources for each philosopher using Tavily, then enrich those sources with summaries from Wikipedia.
- Run a multi-turn (default 5-turn) debate where each philosopher responds to the previous philosopher's question.
- Stream every stage of the debate to the browser over Server-Sent Events (SSE), live as it happens.
- Sign in with Google; Supabase enforces a per-user 10-minute debate cooldown, with admin-managed user exemptions.

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
- Supabase validates bearer tokens for debate requests and stores allowed users and cooldown usage.
- Supabase also records per-user lifetime and UTC-daily accepted request counts without storing request topics or bodies. Non-exempt users may make five requests per UTC day; topics are limited to 100 `o200k_base` tokens.
- Admins listed in Supabase's private `admin_users` table can manage the allowlist and restrict sign-in from the frontend.
- Debate execution disables LangSmith tracing to avoid persisting prompts or transcripts through LangSmith.
- Streaming is driven by LangGraph's async streaming (`graph.astream(..., stream_mode="updates")`), so each event is flushed to the client as soon as the underlying stage completes.
- The pipeline lives in one place: `backend/philo_agent/graphs/main_graph.py`. `backend/philo_agent/app.py` re-exports the compiled graph for `langgraph dev`.

### Frontend
- React 18 + Vite + TypeScript, dev server on `http://localhost:5173` with proxies for `/debate`, `/auth`, and `/admin` → `http://localhost:8000`.
- Reads the SSE stream with `fetch` + `ReadableStream` (POST by design) and renders philosopher cards, live turns, progress, and a full-dialogue view.

### Evaluation

The repo includes an LLM-judged evaluation harness at
[`eval/evaluate_debates.py`](eval/evaluate_debates.py). It runs the debate agent
on a set of topics and scores every turn on logical validity, hallucination
control, adherence to the topic, adherence to the previous argument, coherence,
and use of philosophical knowledge. It also reports debate-level quality/depth,
strengths, weaknesses, and recommendations.

```powershell
# Five-topic smoke suite (uses the backend virtualenv)
.\backend\.venv\Scripts\python.exe eval\evaluate_debates.py --quick

# Custom topics with a README-ready markdown report
.\backend\.venv\Scripts\python.exe eval\evaluate_debates.py `
    --topics eval\topics.example.json `
    --output eval\results.json `
    --markdown eval\results.md
```

Scores and full transcripts are written to `eval/results.json`; `--markdown`
produces a section that can be pasted into this README. Use `--from-results`
to re-score saved dialogues without re-running the agent while tuning the judge.
Use `--update-readme README.md` to write the generated report into the block
below automatically (run it once results are acceptable).
See [`eval/README.md`](eval/README.md) for all options and the iteration workflow.

<!-- EVAL_RESULTS_START -->
## Evaluation Results

_Generated 2026-10-26 23:33 UTC with an LLM judge (`openai/gpt-oss-20b`)._

### Aggregate scores

| Metric | Score |
|---|---|
| Debates evaluated | 2 |
| Turns scored | 20 |
| Overall quality | 7.0/10 |
| Philosophical depth | 7.5/10 |
| Validity | 7.45/10 |
| Hallucination control (10 = none) | 9.4/10 |
| Adherence to topic | 10.0/10 |
| Adherence to previous argument | 10.0/10 |
| Coherence | 8.2/10 |
| Use of philosophical knowledge | 8.55/10 |
| Weakest dimension | Validity |

### Per-topic

| Topic | Quality | Depth | Turns |
|---|---|---|---|
| Is free will compatible with determinism? | 6.0/10 | 7.0/10 | 10 |
| Does morality require religion? | 8.0/10 | 8.0/10 | 10 |

### Notable strengths and weaknesses

**Is free will compatible with determinism?**
- Strengths: Accurate representation of Hume’s empiricist and compatibilist views.; Consistent adherence to the debate topic across all turns.; Clear, logical structure in most arguments.; No major factual inaccuracies or invented quotations.
- Weaknesses: Turn 2 is incomplete, weakening its overall persuasiveness.; Several arguments are somewhat repetitive and could be more concise.; Occasional lack of concrete examples to illustrate abstract points.
- Summary: The debate demonstrates a solid grasp of Hume’s empiricism and van Inwagen’s incompatibilism, with accurate attributions and coherent reasoning. The main shortcoming is the incomplete second turn, which disrupts the flow. Overall, the discussion remains on topic and showcases a respectable level of philosophical depth.

**Does morality require religion?**
- Strengths: Consistent engagement with the central question across all turns.; Accurate representation of Augustine’s and Kant’s core doctrines.; Logical structure and clear articulation of arguments.; Direct challenges to the opponent’s claims.
- Weaknesses: Repetitive content, especially in Augustine’s later turns.; Occasional lack of nuance in addressing the opponent’s specific questions.; Limited exploration of empirical evidence or contemporary moral developments.
- Summary: The debate demonstrates a solid grasp of Augustine’s and Kant’s positions, with clear, logically sound arguments. While Augustine’s repeated emphasis on divine illumination is coherent, it lacks novelty and could benefit from deeper engagement with Kant’s critiques. Kant’s responses are consistently rigorous and well‑grounded. Overall, the exchange is of high quality and philosophical depth, though it would be strengthened by greater diversity of content and more nuanced responses to the opponent’s questions.
<!-- EVAL_RESULTS_END -->


### Configuration recap
| Env var | Where | Purpose |
|---|---|---|
| `GROQ_API_KEY`, `TAVILY_API_KEY` | backend | LLM + search (required) |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | backend | Token validation, user allowlist, and usage tracking |
| `CORS_ORIGINS` | backend | Comma-separated origins allowed to call the API from a browser |
| `VITE_API_URL` | frontend (build-time) | Absolute URL of the deployed backend |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | frontend (build-time) | Supabase Google sign-in; the anon key is public |

Google OAuth, the admin-managed sign-in allowlist, and per-user usage limits
require the Supabase database setup in [`setup.md`](setup.md).
The service-role key must only be configured on the backend, never in the
frontend.

The signed-in frontend footer credits **Made by Badasz** and links to
https://badasz-portfolio.vercel.app.

### Render
A [`render.yaml`](render.yaml) blueprint defines two services: the Python **backend** web service and a **static-site** frontend. From the repo root:
```bash
render blueprint launch
```
After creation, open each service's dashboard and set the `sync: false` secrets. See [`setup.md`](setup.md) for all backend/frontend Supabase and OAuth configuration.

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
- enable user debate with philosophers
- enable user to request further explanation on philosopher response

---
*Note: `notebook.ipynb` and `example.txt`/`example.png` are scratch/demo artifacts kept at the repo root.*