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

The frontend includes a simple password gate for private personal access. Set this environment variable in Vercel:

```bash
APP_ACCESS_PASSWORD=your-private-password
```

If `APP_ACCESS_PASSWORD` is not set, the gate is disabled. This keeps local development friction-free.

## Deploy to Vercel

Create a Vercel project with `frontend/` as the project root.

Set these frontend environment variables:

```bash
APP_ACCESS_PASSWORD=your-private-password
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
