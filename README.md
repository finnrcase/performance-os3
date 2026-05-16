# Performance OS

Performance OS is a local-first fitness recovery and performance optimization platform. It brings training, nutrition, recovery, body metrics, and integrations into one workspace for understanding what is helping performance and what is getting in the way.

## Current App

The current production-facing UI is the Next.js app in `frontend/`, backed by
the FastAPI service in `backend/`. The older Streamlit app in `app/main.py`
remains available for local experiments.

The platform supports CSV/JSON-backed workflows for:

- Food logging, frequent foods, meal templates, and optional AI food parsing
- Bodyweight and body metrics tracking
- Recovery check-ins and deterministic recovery scoring
- Manual training logs and placeholder integration flows
- Recommendation and performance optimization engines
- Local integrations/settings configuration

Run the Streamlit app locally if needed:

```bash
streamlit run app/main.py
```

## Architecture

The project is structured as a split production web app while keeping Streamlit intact:

- `frontend/`: Next.js + Tailwind frontend, deployable on Vercel
- `backend/`: FastAPI service for the production frontend
- `src/`: shared Python business logic, analytics, integrations, and optimization engines
- `app/`: local Streamlit MVP/utility interface

The intended long-term shape is:

```text
Next.js frontend -> FastAPI backend -> shared Python modeling engine in src/
```

Run the FastAPI backend:

```bash
uvicorn backend.main:app --reload --port 8001
```

Health check:

```bash
curl http://localhost:8001/health
```

Expected response:

```json
{"status":"ok","service":"performance-os-api"}
```

## Private Online Deployment

Performance OS is prepared for a split deployment:

- Frontend: Vercel, using the Next.js app in `frontend/`
- Backend: Railway or Render, using the FastAPI app in `backend/`
- Streamlit: remains available locally as the MVP interface

The Python API is not currently packaged as Vercel serverless functions because
it writes CSV/JSON data, handles uploads, and runs Hevy polling. Deploy it as a
long-running Python service with persistent storage, then point the Vercel
frontend at it.

### Frontend on Vercel

Create a Vercel project with `frontend/` as the project root.

Recommended Vercel build settings:

```text
Framework preset: Next.js
Install command: npm install
Build command: npm run build
Development command: npm run dev
```

Set these Vercel environment variables:

```bash
APP_PASSWORD=your-private-password
SESSION_SECRET=your-long-random-session-secret
NEXT_PUBLIC_API_URL=https://api-production-b3ff.up.railway.app
NEXT_PUBLIC_APP_URL=https://performance-os-rho.vercel.app
```

`APP_PASSWORD` is the password entered on the Performance OS login page.
`SESSION_SECRET` signs the private access cookie after a successful login. Both
are server-side only and must not use the `NEXT_PUBLIC_` prefix.

`NEXT_PUBLIC_API_URL` is the public Railway backend URL used by the browser and
by OAuth callback forwarding routes. `BACKEND_API_URL` is still accepted as a
server-side rewrite fallback, but production should set `NEXT_PUBLIC_API_URL`.

Do not put backend API keys or OAuth secrets in the Vercel frontend project.
Keep `OPENAI_API_KEY`, `STRAVA_CLIENT_SECRET`, `HEVY_API_KEY`, and similar keys
on the backend host only.

### Local Frontend Password

The Next.js login gate reads `APP_PASSWORD` and `SESSION_SECRET` server-side from
the frontend environment. For local development, create `frontend/.env.local`:

```bash
APP_PASSWORD=your-private-password
SESSION_SECRET=your-long-random-session-secret
NEXT_PUBLIC_API_URL=http://localhost:8001
```

Then run the frontend from `frontend/`:

```bash
npm run dev
```

If either `APP_PASSWORD` or `SESSION_SECRET` is missing, the login page shows a
setup error instead of silently accepting or rejecting access.

After editing `frontend/.env.local`, restart `npm run dev` so Next.js reloads
the password. `APP_PASSWORD` is read only by server-side code and should never
be prefixed with `NEXT_PUBLIC_`.

### Backend on Railway or Render

Deploy the repository root as a Python web service.

Start command:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Set backend environment variables as needed:

```bash
DATABASE_URL=postgres://...
APP_PASSWORD=your-private-password
OPENAI_API_KEY=...
USDA_FDC_API_KEY=...
STRAVA_CLIENT_ID=...
STRAVA_CLIENT_SECRET=...
# Optional bootstrap tokens. OAuth tokens are stored server-side after reconnect.
STRAVA_ACCESS_TOKEN=
STRAVA_REFRESH_TOKEN=
STRAVA_EXPIRES_AT=
STRAVA_REDIRECT_URI=https://api-production-b3ff.up.railway.app/api/strava/callback
NEXT_PUBLIC_APP_URL=https://performance-os-rho.vercel.app
HEVY_API_KEY=...
HEVY_WEBHOOK_SECRET=...
WITHINGS_CLIENT_ID=...
WITHINGS_CLIENT_SECRET=...
WITHINGS_REDIRECT_URI=https://api-production-b3ff.up.railway.app/api/withings/callback
CORS_ALLOW_ORIGINS=https://performance-os-rho.vercel.app
FRONTEND_ORIGIN=https://performance-os-rho.vercel.app
```

Production ownership rules:

- Vercel gets only frontend/session config: `APP_PASSWORD`,
  `SESSION_SECRET`, `NEXT_PUBLIC_API_URL`, and `NEXT_PUBLIC_APP_URL`.
- Railway gets all backend secrets and integrations: `DATABASE_URL`,
  `OPENAI_API_KEY`, `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`,
  `STRAVA_ACCESS_TOKEN`, `STRAVA_REFRESH_TOKEN`, `HEVY_API_KEY`, and webhook or
  OAuth secrets.
- Do not put `OPENAI_API_KEY`, `STRAVA_CLIENT_SECRET`, `STRAVA_REFRESH_TOKEN`,
  `HEVY_API_KEY`, or database credentials in Vercel.
- After changing Railway or Vercel environment variables, redeploy both
  services so the running processes pick up the new config.

For local Strava OAuth, set the Strava app callback and backend env to:

```bash
STRAVA_REDIRECT_URI=http://localhost:8001/api/strava/callback
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

The FastAPI backend owns Strava OAuth code exchange, token refresh, and token
storage. In production, use the Railway callback URL above and add
`api-production-b3ff.up.railway.app` as the Strava authorization callback domain
in the Strava developer dashboard.

For Withings OAuth, set the Withings app callback and backend env to:

```bash
WITHINGS_REDIRECT_URI=https://api-production-b3ff.up.railway.app/api/withings/callback
```

Withings rejects normal `localhost` and IP callback URLs, so local OAuth testing
needs either the deployed Railway callback above or a public HTTPS tunnel whose
callback URL is configured in the Withings developer console. The frontend asks
FastAPI for a Withings authorization URL and never receives the client secret.
After connecting, use `POST /api/withings/sync` or the Settings button to import
Withings scale measurements into the body metrics table.

Railway can use `railway.json`. Render can use `render.yaml`. A `Procfile` is also included for platforms that support it.

### Production Database

Local development uses gitignored CSV/JSON files under `data/`. Production must
set `DATABASE_URL` to a hosted Postgres database such as Neon, Supabase
Postgres, or another managed Postgres provider. When `DATABASE_URL` is present,
Performance OS stores food logs, meal templates, body metrics, recovery/sleep,
training history, integration tokens, macro targets, and PR/settings documents
in Postgres tables instead of local files.

Initialize the schema:

```bash
python scripts/init_database.py
```

### Integration Diagnostics

The backend exposes a secret-safe diagnostic report:

```bash
curl https://api-production-b3ff.up.railway.app/api/integrations/status
```

The response includes `overall_status`, `environment`, `backend`, `database`,
`frontend`, `openai`, `strava`, `hevy`, `withings`, `other_integrations`,
`required_user_actions`, and `checked_at`. It reports whether required env vars
exist but never returns API keys, OAuth tokens, refresh tokens, client secrets,
or database URLs.

Local CLI check:

```bash
python backend/scripts/check_integrations.py
```

Deployed backend check:

```bash
python backend/scripts/check_integrations.py --base-url https://api-production-b3ff.up.railway.app
```

Use `--no-external-checks` locally to skip live OpenAI and Hevy calls while still
checking config, database, OAuth token state, storage, and source-code routing.

Move local history into production:

```bash
python scripts/export_local_data.py
DATABASE_URL=postgres://... python scripts/import_production_data.py outputs/performance-os-local-export.json
```

The Vercel/serverless filesystem is not durable. Do not use local JSON, CSV,
browser storage, or mock data for important production records.

### Route And API Notes

- Next.js route handlers under `frontend/src/app/api/access/*` run on Vercel.
- Application data routes such as `/api/dashboard`, `/api/food/*`,
  `/api/training/*`, and `/api/recovery/*` are served by FastAPI.
- In production, the browser calls the Railway backend from
  `NEXT_PUBLIC_API_URL`. `BACKEND_API_URL` remains only as a rewrite fallback.
- The FastAPI backend allows Vercel preview URLs via CORS and should also be
  configured with `CORS_ALLOW_ORIGINS` for your production domain.

## Project Structure

```text
performance-os/
├── app/                         # current Streamlit MVP
├── backend/
│   ├── main.py                   # FastAPI app
│   ├── routes/
│   │   ├── nutrition.py
│   │   ├── training.py
│   │   ├── recovery.py
│   │   ├── body_metrics.py
│   │   └── integrations.py
│   └── __init__.py
├── frontend/
│   └── README.md                 # Next.js deployment notes
├── src/                          # core business logic
├── data/
├── outputs/
├── tests/
├── requirements.txt
├── README.md
└── .gitignore
```

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Roadmap

Phase 1: Streamlit MVP with local CSV persistence and deterministic recommendations

Phase 2: FastAPI endpoints for core data models and analytics

Phase 3: Next.js frontend with polished dashboard, logging, history, and settings flows

Phase 4: Production-grade OAuth integrations and durable storage
