# Performance OS Frontend

This is the first polished Next.js frontend for Performance OS. It is separate from the Streamlit MVP in `../app/main.py` and reads/writes local data through the FastAPI backend.

## Stack

- Next.js App Router
- TypeScript
- Tailwind CSS
- Recharts
- lucide-react icons

## Run Locally

From this directory:

```bash
npm install
npm run dev
```

Then open the local URL printed by Next.js, usually:

```text
http://localhost:3000
```

The frontend expects the local FastAPI backend at:

```text
http://localhost:8001
```

You can override this with `NEXT_PUBLIC_API_BASE_URL`.

For current builds, prefer:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8001
```

`NEXT_PUBLIC_API_BASE_URL` is still supported as a local fallback.

In production, prefer the server-side proxy:

```bash
BACKEND_API_URL=https://your-performance-os-api.example.com
```

When `BACKEND_API_URL` is set on Vercel, `next.config.ts` proxies `/api/*`
requests to the FastAPI backend. That keeps the browser on the Vercel origin
and avoids exposing the backend URL unless you choose to set
`NEXT_PUBLIC_API_URL`.

## Private Access Gate

The frontend includes a simple password gate for private personal access. The login password is controlled by:

```bash
APP_PASSWORD=your-private-password
SESSION_SECRET=your-long-random-session-secret
```

`APP_PASSWORD` is the value you type into the Performance OS login page.
`SESSION_SECRET` signs the private access cookie after a successful login. Both
variables are read server-side only by the Next.js login API/proxy and must not
be prefixed with `NEXT_PUBLIC_`.

For local development, create `frontend/.env.local`:

```bash
APP_PASSWORD=your-private-password
SESSION_SECRET=your-long-random-session-secret
NEXT_PUBLIC_API_URL=http://localhost:8001
```

If either `APP_PASSWORD` or `SESSION_SECRET` is missing, the login page shows a
setup error so the gate does not fail silently.

Restart `npm run dev` after editing `frontend/.env.local`; Next.js loads these
server-side variables at server startup.

## Deploy to Vercel

Create a Vercel project with `frontend/` as the project root.

Set these frontend environment variables:

```bash
APP_PASSWORD=your-private-password
SESSION_SECRET=your-long-random-session-secret
BACKEND_API_URL=https://your-performance-os-api.example.com
NEXT_PUBLIC_APP_URL=https://your-vercel-app.vercel.app
```

Optional:

```bash
NEXT_PUBLIC_API_URL=https://your-performance-os-api.example.com
```

Only use `NEXT_PUBLIC_API_URL` when you want direct browser-to-backend calls.
Do not add backend secrets such as `OPENAI_API_KEY`, `STRAVA_CLIENT_SECRET`, or
`HEVY_API_KEY` to Vercel. Those belong on the FastAPI backend host.

The FastAPI backend must have its own production env vars, including:

```bash
DATABASE_URL=postgres://...
OPENAI_API_KEY=...
HEVY_API_KEY=...
STRAVA_CLIENT_ID=...
STRAVA_CLIENT_SECRET=...
STRAVA_REDIRECT_URI=https://your-vercel-app.vercel.app/api/strava/callback
NEXT_PUBLIC_APP_URL=https://your-vercel-app.vercel.app
CORS_ALLOW_ORIGINS=https://your-vercel-app.vercel.app
FRONTEND_ORIGIN=https://your-vercel-app.vercel.app
```

For local Strava testing, use this exact callback in the Strava developer app
and backend env:

```bash
STRAVA_REDIRECT_URI=http://localhost:3000/api/strava/callback
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

The callback URL is intentionally on the frontend origin; Next.js forwards it
to FastAPI so the token exchange and saved refresh token stay server-side.

Use `python scripts/export_local_data.py` locally, then run
`DATABASE_URL=postgres://... python scripts/import_production_data.py` from the
repo root to seed production with your local history.

Build settings:

```text
Install command: npm install
Build command: npm run build
Development command: npm run dev
```

## Product Scope

The prototype includes:

- Dashboard
- Food
- Weight & Recovery
- Training
- Data & History
- Integrations / Settings

The Dashboard includes cards for recovery score, calories today, protein today, bodyweight trend, latest workout, and recommendation summary.

## Notes

- External API keys stay on the FastAPI backend, never in the browser.
- FastAPI reads/writes the existing local CSV and JSON files.
- Hosted FastAPI deployments should set `PERFORMANCE_OS_DATA_DIR` to a
  persistent disk or volume.
- Streamlit remains the working MVP interface.
- The product design plan lives in `PRODUCT_PLAN.md`.
