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
APP_ACCESS_PASSWORD=your-private-password
BACKEND_API_URL=https://your-backend-url.example.com
NEXT_PUBLIC_APP_URL=https://your-vercel-app.vercel.app
```

`BACKEND_API_URL` is server-side only and is used by `frontend/next.config.ts`
to proxy `/api/*` requests to FastAPI. You may set `NEXT_PUBLIC_API_URL` if you
want the browser to call the backend directly, but the proxy is preferred.

Do not put backend API keys or OAuth secrets in the Vercel frontend project.
Keep `OPENAI_API_KEY`, `STRAVA_CLIENT_SECRET`, `HEVY_API_KEY`, and similar keys
on the backend host only.

### Backend on Railway or Render

Deploy the repository root as a Python web service.

Start command:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Set backend environment variables as needed:

```bash
OPENAI_API_KEY=...
USDA_FDC_API_KEY=...
STRAVA_CLIENT_ID=...
STRAVA_CLIENT_SECRET=...
STRAVA_ACCESS_TOKEN=...
HEVY_API_KEY=...
HEVY_WEBHOOK_SECRET=...
WITHINGS_CLIENT_ID=...
WITHINGS_CLIENT_SECRET=...
CORS_ALLOW_ORIGINS=https://your-vercel-app.vercel.app
FRONTEND_ORIGIN=https://your-vercel-app.vercel.app
PERFORMANCE_OS_DATA_DIR=/data
```

Railway can use `railway.json`. Render can use `render.yaml`. A `Procfile` is also included for platforms that support it.

### Storage And Database Note

The current backend uses CSV and JSON files instead of a SQL database. For
production, attach persistent storage and set `PERFORMANCE_OS_DATA_DIR` to the
mounted path. Examples:

```bash
PERFORMANCE_OS_DATA_DIR=/data
```

`DATABASE_URL` is documented in `.env.example` as a reserved future migration
target, but the current code does not require it. Until a database adapter is
added, durable hosted data depends on a Railway volume, Render disk, or another
persistent filesystem.

### Route And API Notes

- Next.js route handlers under `frontend/src/app/api/access/*` run on Vercel.
- Application data routes such as `/api/dashboard`, `/api/food/*`,
  `/api/training/*`, and `/api/recovery/*` are served by FastAPI.
- In production, the Vercel frontend proxies those data routes to
  `BACKEND_API_URL`, so the browser can use the same public Vercel origin.
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
