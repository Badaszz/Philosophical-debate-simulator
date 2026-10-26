# Setup Guide — Deploying the Philosophical Debate Simulator

This guide walks you through taking the project from a local repo to a live
deployment. You have three deployment options:

| Option | Frontend | Backend | Best for |
|---|---|---|---|
| **A. Vercel + Render** | Vercel (SPA) | Render (FastAPI) | Recommended |
| **B. All on Render** | Render static site | Render web service | Single platform |
| **C. Docker Compose** | nginx container | FastAPI container | Local / self-hosted |

The app needs two pieces:

- **Backend (FastAPI + LangGraph)** — runs the LLM debate pipeline, streams SSE.
- **Frontend (React/Vite)** — browser UI that calls the backend via `VITE_API_URL`.

---

## 1. Prerequisites

- GitHub account with this repository pushed to it.
- A **Render** account (free tier is fine) for the backend.
- A **Vercel** account (free tier is fine) for the frontend.
- Two API keys:
  - `GROQ_API_KEY` — LLM inference (https://console.groq.com)
  - `TAVILY_API_KEY` — web search for philosopher sources (https://tavily.com)

> Secrets are stored in each platform's dashboard — **never** commit real keys
> to the repository.

---

## 2. Local setup (optional, for testing first)

```bash
# 1. Create your env file from the template and fill in the keys
cp .envexample.generated .env     # Windows (PowerShell): Copy-Item .envexample.generated .env

# 2. Backend
cd backend
uv sync
uv run uvicorn app:app --reload    # API at http://127.0.0.1:8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev                        # UI at http://localhost:5173
```

The Vite dev server proxies `/debate` to the local API, so no `VITE_API_URL`
is needed locally. Enter a topic and hit **Start Debate** to confirm it works.

---

## 3. Option A — Frontend on Vercel, Backend on Render

### Step A1. Deploy the backend to Render

1. Go to https://dashboard.render.com → **New +** → **Blueprint**.
2. Select the GitHub repo, connect it if prompted.
3. Render reads `render.yaml` and shows the two services:
   - `philosophical-debates-backend` (Python web service)
   - `philosophical-debates-frontend` (static site)
4. Click **Apply** / **Create Blueprint Resources** and wait for creation.
5. Open the **backend** service → **Environment** and set:
   - `GROQ_API_KEY`
   - `TAVILY_API_KEY`
   - `CORS_ORIGINS` → the frontend's URL once it exists
     (e.g. `https://my-app.vercel.app,https://philosophical-debates-frontend.onrender.com`)
   - Saving the env vars triggers a redeploy automatically.
6. Note the backend URL. It looks like `https://philosophical-debates-backend.onrender.com`.

> Free-tier Render services **sleep** after ~15 minutes of inactivity and take
> ~30–60s to wake on the first request. That's normal.

### Step A2. Deploy the frontend to Vercel

1. Go to https://vercel.com → **Add New → Project**.
2. Import the GitHub repo.
3. Set **Root Directory** to `frontend`.
4. Vercel auto-detects Vite; leave build command/output defaults
   (`npm run build` / `dist`).
5. Under **Environment Variables**, add:
   - `VITE_API_URL` = your Render backend URL from Step A1
     (e.g. `https://philosophical-debates-backend.onrender.com`)
6. Click **Deploy**.

Vercel builds the app with `VITE_API_URL` baked into the bundle. `vercel.json`
in the repo provides the SPA rewrite.

### Step A3. Finish wiring (once)

1. Go back to the Render **backend** service → **Environment** and add your
   deployed frontend URL (from Vercel) to `CORS_ORIGINS` if it isn't already
   there. Use a comma-separated list:
   ```
   https://my-app.vercel.app,https://philosophical-debates-frontend.onrender.com
   ```
2. Save → backend redeploys.
3. Open the Vercel site and run a debate end-to-end.

### What happens at runtime

```
Browser (Vercel)  --VITE_API_URL-->  https://philosophical-debates-backend.onrender.com
                                      (POST /debate/stream, SSE)
```
Because the SPA calls the backend cross-origin, the backend must allow the
frontend's origin in `CORS_ORIGINS`.

---

## 4. Option B — All on Render

Same as A1, but keep _both_ blueprint services and skip Vercel entirely.

1. Deploy the blueprint as in **Step A1**.
2. Open the **frontend** static site service → **Environment** and set:
   - `VITE_API_URL` = the backend service URL
     (e.g. `https://philosophical-debates-backend.onrender.com`)
3. Save → frontend rebuilds and redeploys.
4. Set `CORS_ORIGINS` on the backend to include
   `https://philosophical-debates-frontend.onrender.com`.

Frontend URL: `https://philosophical-debates-frontend.onrender.com`

---

## 5. Option C — Docker Compose (local / self-hosted)

```bash
# 1. Env file at the repo root with real keys
cp .envexample.generated .env     # then fill in keys

# 2. Build and run both services
docker compose up --build
```

- Frontend: http://localhost:8080 (nginx servers the SPA and proxies `/debate`
  to the backend — no CORS needed)
- Backend: http://localhost:8000

---

## 6. Env var reference

| Variable | Service | Required | Notes |
|---|---|---|---|
| `GROQ_API_KEY` | backend | yes | LLM inference |
| `TAVILY_API_KEY` | backend | yes | Web search |
| `CORS_ORIGINS` | backend | only cross-origin | Comma-separated origins allowed to call the API. Defaults to localhost origins when unset. |
| `VITE_API_URL` | frontend | cross-origin deploys | Absolute backend URL, baked in at *build* time. Leave empty when the frontend and backend share an origin/proxy. |
| `PORT` | backend | Render supplies | Render binds this automatically via `$PORT`. |

> **Remember:** changing `VITE_API_URL` requires a frontend **rebuild** (it's a
> build-time value). Render/Vercel redeploy automatically when you save env vars.

---

## 7. Verifying a deployment

After everything is up:

1. **Health check** — open `https://<backend-url>/docs` in a browser. You
   should see the Swagger UI with `/debate` and `/debate/stream`.
2. **Direct API test**:
   ```bash
   curl -N -X POST https://<backend-url>/debate/stream \
     -H "Content-Type: application/json" \
     -d '{"topic":"Free Will vs Determinism"}'
   ```
   You should see `event: philosophers`, then `event: turn`, then `event: done`.
3. **UI test** — open the frontend URL, submit a topic, and watch the debate
   stream in live as it happens.
4. **CORS sanity check** — open the browser DevTools console; a red
   `No 'Access-Control-Allow-Origin' header` error means `CORS_ORIGINS` on the
   backend does not include the frontend origin.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| First request is very slow / times out | Free-tier cold start | Wait ~60s and retry; consider a paid instance or keep-alive ping |
| `No 'Access-Control-Allow-Origin' header` | `CORS_ORIGINS` mismatch | Add the exact frontend origin (no trailing slash) to the backend env and redeploy |
| Frontend still points at an old API after changing `VITE_API_URL` | Env var is build-time only | Redeploy/rebuild the frontend, verify the setting in the build logs |
| `TAVILY_API_KEY not set in environment` on Render | Secret not configured | Set `TAVILY_API_KEY` on the backend service env and redeploy |
| Backend restarts / 500 in logs | Missing `GROQ_API_KEY` | Set `GROQ_API_KEY` on the backend service env and redeploy |
| Debate streams but shows no philosophers | Tavily down / key invalid | Check backend logs; retrieval degrades gracefully to empty sources |