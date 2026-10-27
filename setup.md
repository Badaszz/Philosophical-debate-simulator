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
- A Supabase project for Google sign-in and per-user rate limiting.

> Secrets are stored in each platform's dashboard — **never** commit real keys
> to the repository.

---

## 2. Supabase and Google OAuth setup

1. Create a Supabase project at https://supabase.com/dashboard.
   Use this same Supabase project for local testing and production. That means
   both environments share the Google OAuth provider, Auth users, admin and
   allowlist entries, restriction setting, and usage counters. Do not create a
   second project or run a separate copy of the schema for production.
2. In **Project Settings → API**, copy the project URL, the publishable/anon
   key, and the secret/service-role key. Configure `SUPABASE_URL`,
   `SUPABASE_ANON_KEY`, and `SUPABASE_SERVICE_ROLE_KEY` on the backend only.
   The service-role key bypasses row-level security and must never be exposed to
   the browser.
3. Open **SQL Editor**, run the contents of [`supabase/schema.sql`](supabase/schema.sql).
   This creates the private admin and allowlist tables, restriction setting,
   user request-count table, and atomic cooldown/daily-limit functions. It also
   backfills existing Supabase Auth users and installs a trigger for future
   users. The usage table is `public.user_request_usage`; find it in **Table
   Editor**. It stores each user's ID/email, lifetime accepted request count,
   current UTC-day count, and timestamps; it does not store topics or request
   bodies. Sign-in restriction starts disabled.
4. Add your Google account to `public.admin_users` using the Supabase SQL
   Editor. Substitute the email address of the Google account you intend to
   use as the app administrator:
   ```sql
   insert into public.admin_users (email)
   values (lower('your-google-account@example.com'))
   on conflict (email) do nothing;
   ```
   You can also add it through **Table Editor → admin_users → Insert row**.
   This email exists in your private Supabase project, not in the application
   source. `admin_users` has row-level security enabled and is only queried by
   the backend using the server-only service-role key. Do not add a public API
   endpoint for changing this table.
5. In **Authentication → Hooks**, enable the **Before User Created** hook and
   select `public.before_user_created`. This prevents new, non-allowed Google
   accounts from being created when restriction is enabled. The API also
   enforces the setting for existing accounts. Addresses in `admin_users` are
   permitted by the hook. The backend grants admin privileges only to an
   address in that table whose Supabase user has a confirmed email and a Google
   identity; an email match alone is insufficient.
6. In **Authentication → Providers → Google**, enable Google and enter the
   Google OAuth client ID and secret:
   - In Google Cloud Console, create an OAuth 2.0 web client.
   - Add the Supabase callback URL shown by the Google provider setup page to
     Google's **Authorized redirect URIs**.
   - Add the local and deployed frontend origins to Supabase's **Authentication
     → URL Configuration → Redirect URLs**, for example
     `http://localhost:5173/**` and `https://your-frontend.example.com/**`.
7. Configure `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` for the
   frontend. The browser uses the anon/publishable key; no service-role key is
   used by the frontend.
8. Sign in with the Google account you added to `admin_users`. The admin panel
   lets that account manage allowed email addresses and toggle restricted
   sign-in. Allowed users can sign in when restriction is enabled and do not
   have a cooldown.

For the simplest setup, enable Google as the only sign-in provider in
**Authentication → Providers**. The backend also checks the admin user's
confirmed-email and Google-provider metadata before granting administrator
privileges.

The backend validates each bearer token against Supabase Auth. For regular
users, the backend enforces both a 10-minute per-user cooldown and a limit of
five accepted debate requests per UTC day. Both `/debate` and `/debate/stream`
share these limits. Reservations and request counters are updated atomically
in Postgres before processing. A rejected request is not counted; a debate
that fails or is cancelled after acceptance remains counted. The administrator
and allowlisted users are exempt from both limits, but their accepted calls
are still counted.

Debate topic text is limited to 100 tokens using the `o200k_base` encoding.
The topic and request body are not written to the Supabase usage table. API
debate execution also disables LangSmith tracing so prompts and transcripts
aren't sent to LangSmith by this application. The topic is still sent to the
configured LLM provider to generate the debate.

---

## 3. Local setup and testing

From the repository root, create the backend env file and fill in
`GROQ_API_KEY`, `TAVILY_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and
`SUPABASE_SERVICE_ROLE_KEY`:

```powershell
Copy-Item .envexample.generated .env
Set-Location backend
uv sync
uv run uvicorn app:app --reload
```

In a second terminal, from the repository root, set up and start the frontend:

```powershell
Set-Location frontend
Copy-Item .env.example .env
# Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in frontend/.env
# to the same Supabase project used in the root .env.
npm install
npm run dev
```

The backend runs at `http://127.0.0.1:8000` and the frontend at
`http://localhost:5173`. Local Vite proxies API requests to the backend, so
leave `VITE_API_URL` empty.

Open http://localhost:5173. Before testing sign-in, make sure you have already
run the schema, inserted your Google account into `public.admin_users`, enabled
Google sign-in, and allowed `http://localhost:5173/**` in Supabase's
**Authentication → URL Configuration → Redirect URLs**. The Google provider's
authorized redirect URI should be the Supabase callback URL, not the local
frontend URL.

Test in this order:

1. Sign in with the Google account registered in `admin_users`. Verify that the
   admin settings panel loads and that the footer displays the LLM-provider
   topic notice.
2. With sign-in restriction initially disabled, sign in with a separate Google
   account that is not in `admin_users` or `allowed_users`. Start a debate and
   verify that usage is recorded in `public.user_request_usage` without saving
   the topic or request body.
3. Try another debate immediately. The ordinary account should be told to wait
   for the 10-minute cooldown. Its daily count should be shared across the
   regular and streaming debate endpoints.
4. As the admin, add a test email to the allowlist and enable restricted
   sign-in. Verify an unlisted account is rejected, while an allowed account
   can sign in and is exempt from cooldown and daily limits.
5. Disable restriction when finished testing if you want sign-in to remain
   open. These changes affect the same Supabase project and users that
   production will use.

The admin account is exempt from limits, so use a separate regular account to
test cooldown and daily-limit behavior. The daily quota is five accepted
requests per UTC day; testing all five takes five accepted requests (subject
to the cooldown).

---

## 4. Option A — Frontend on Vercel, Backend on Render

Use the **same Supabase project, keys, Google provider, `admin_users` row, and
schema** as local testing. Do not rerun the schema or create another project
for production. Add the deployed frontend URL to Supabase's Redirect URLs
before testing Google sign-in in production.

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
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY` (secret; backend only)
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
   - `VITE_SUPABASE_URL`
   - `VITE_SUPABASE_ANON_KEY`
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

## 5. Option B — All on Render

Same as A1, but keep _both_ blueprint services and skip Vercel entirely.

1. Deploy the blueprint as in **Step A1**.
2. Open the **frontend** static site service → **Environment** and set:
   - `VITE_API_URL` = the backend service URL
     (e.g. `https://philosophical-debates-backend.onrender.com`)
   - `VITE_SUPABASE_URL`
   - `VITE_SUPABASE_ANON_KEY`
3. Save → frontend rebuilds and redeploys.
4. Set `CORS_ORIGINS` on the backend to include
   `https://philosophical-debates-frontend.onrender.com`.

Frontend URL: `https://philosophical-debates-frontend.onrender.com`

---

## 6. Option C — Docker Compose (local / self-hosted)

```bash
# 1. Env file at the repo root with backend and VITE_SUPABASE_* values
cp .envexample.generated .env     # then fill in keys

# 2. Build and run both services
docker compose up --build
```

- Frontend: http://localhost:8080 (nginx servers the SPA and proxies `/debate`
  to the backend — no CORS needed)
- Backend: http://localhost:8000

---

## 7. Env var reference

| Variable | Service | Required | Notes |
|---|---|---|---|
| `GROQ_API_KEY` | backend | yes | LLM inference |
| `TAVILY_API_KEY` | backend | yes | Web search |
| `SUPABASE_URL` | backend | yes | Supabase project URL |
| `SUPABASE_ANON_KEY` | backend | yes | Used to validate user access tokens |
| `SUPABASE_SERVICE_ROLE_KEY` | backend | yes | Server-only database access; keep secret |
| `CORS_ORIGINS` | backend | only cross-origin | Comma-separated origins allowed to call the API. Defaults to localhost origins when unset. |
| `VITE_API_URL` | frontend | cross-origin deploys | Absolute backend URL, baked in at *build* time. Leave empty when the frontend and backend share an origin/proxy. |
| `VITE_SUPABASE_URL` | frontend | yes | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | frontend | yes | Public browser key for Google OAuth; never use the service-role key |
| `PORT` | backend | Render supplies | Render binds this automatically via `$PORT`. |

> **Remember:** changing `VITE_API_URL` requires a frontend **rebuild** (it's a
> build-time value). Render/Vercel redeploy automatically when you save env vars.

---

## 8. Verifying a deployment

After everything is up:

1. **Health check** — open `https://<backend-url>/docs` in a browser. You
   should see the Swagger UI with `/debate` and `/debate/stream`.
2. **Direct API test**:
   ```bash
   curl -N -X POST https://<backend-url>/debate/stream \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <SUPABASE_ACCESS_TOKEN>" \
     -d '{"topic":"Free Will vs Determinism"}'
   ```
   Use a signed-in user's current access token. You should see `event: cooldown`,
   then `event: philosophers`, `event: turn`, and `event: done`.
3. **UI test** — open the frontend URL, submit a topic, and watch the debate
   stream in live as it happens.
4. **CORS sanity check** — open the browser DevTools console; a red
   `No 'Access-Control-Allow-Origin' header` error means `CORS_ORIGINS` on the
   backend does not include the frontend origin.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| First request is very slow / times out | Free-tier cold start | Wait ~60s and retry; consider a paid instance or keep-alive ping |
| `No 'Access-Control-Allow-Origin' header` | `CORS_ORIGINS` mismatch | Add the exact frontend origin (no trailing slash) to the backend env and redeploy |
| Frontend still points at an old API after changing `VITE_API_URL` | Env var is build-time only | Redeploy/rebuild the frontend, verify the setting in the build logs |
| `TAVILY_API_KEY not set in environment` on Render | Secret not configured | Set `TAVILY_API_KEY` on the backend service env and redeploy |
| Supabase API returns 503 | Supabase server env vars or SQL schema are missing | Set all three backend Supabase vars and run `supabase/schema.sql` |
| New Google sign-in is rejected | Before User Created hook is not configured, or restriction is enabled and the address is not allowed | Configure `public.before_user_created`; add admins in `public.admin_users` via Supabase SQL Editor/Table Editor, or add regular accounts in the admin panel |
| Backend restarts / 500 in logs | Missing `GROQ_API_KEY` | Set `GROQ_API_KEY` on the backend service env and redeploy |
| Debate streams but shows no philosophers | Tavily down / key invalid | Check backend logs; retrieval degrades gracefully to empty sources |