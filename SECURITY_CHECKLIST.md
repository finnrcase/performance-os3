# Performance OS Security Checklist

This is a conservative hardening checklist. Stability stays first: do not broadly lock routes or change cookie behavior until the Vercel frontend, Railway backend, and signed session cookie path are verified in production.

## Current Protections

- Backend private API guard: all `/api/*` routes require the signed `performance_os_access` session cookie unless the path is in the explicit public allowlist.
- Public API allowlist: `/api/auth/login`, `/api/auth/logout`, `/api/strava/callback`, `/api/integrations/strava/callback`, `/api/withings/callback`, `/api/hevy/webhook`.
- `/health` remains public for deployment probes.
- CORS keeps localhost development origins, the production Vercel app origin, configured origins, and Vercel preview domains, with `allow_credentials=True`.
- Login has a light in-memory rate limit only. Core app routes are not rate limited.
- Settings responses mask stored integration secrets.
- Debug/integration/export responses should redact secret-like keys such as API keys, OAuth tokens, client secrets, passwords, session secrets, and database URLs.
- Hevy webhook is public only because it verifies the shared webhook secret.

## Required Environment Variables

- `APP_PASSWORD`: private access gate password used by `/api/auth/login`.
- `SESSION_SECRET`: HMAC signing secret for `performance_os_access`.
- `BACKEND_API_URL`: preferred Next.js server/proxy target for the Railway backend.
- `NEXT_PUBLIC_API_URL`: frontend-visible backend URL fallback when needed.
- Integration secrets live on the backend only where possible: `HEVY_API_KEY`, `OPENAI_API_KEY`, `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_REDIRECT_URI`, `WITHINGS_CLIENT_ID`, `WITHINGS_CLIENT_SECRET`, `WITHINGS_REDIRECT_URI`.

## Safe Public Routes

| Method | Route | Classification | Notes |
|---|---|---|---|
| GET | `/health` | public | Deployment health probe. No personal data. |
| POST | `/api/auth/login` | public | Pre-login credential exchange. Login-only rate limit applies. |
| POST | `/api/auth/logout` | public | Session cleanup; safe when unauthenticated. |
| GET | `/api/integrations/strava/callback` | integration-callback | OAuth callback. |
| GET | `/api/strava/callback` | integration-callback | Lowercase Strava OAuth callback alias. |
| GET/POST/HEAD/OPTIONS | `/api/withings/callback` | integration-callback | OAuth callback and provider compatibility route. |
| POST | `/api/hevy/webhook` | webhook | Must keep verifying the Hevy webhook secret. |

## Route Audit

| Method | Route | Classification | Current posture |
|---|---|---|---|
| GET | `/api/auth/session` | private-read | Protected by global session middleware. |
| GET | `/api/debug/db` | debug/export | Protected; response is secret-redacted. |
| GET | `/api/debug/startup` | debug/export | Protected; response is secret-redacted. |
| GET | `/api/dashboard/core` | private-read | Protected; response is secret-redacted. |
| GET | `/api/debug/dashboard-core` | debug/export | Protected; response is secret-redacted. |
| GET | `/api/dashboard` | private-read | Protected; response is secret-redacted. |
| GET | `/api/dashboard/debug` | debug/export | Protected; response is secret-redacted. |
| POST | `/api/recommendations/run` | private-write | Protected. Explicit heavy engine run. |
| GET | `/api/nutrition/logs` | private-read | Protected. |
| GET | `/api/nutrition/today` | private-read | Protected. |
| POST | `/api/nutrition/logs` | private-write | Protected. |
| DELETE | `/api/nutrition/logs/{food_log_id}` | private-write | Protected. |
| PUT | `/api/nutrition/logs/{food_log_id}` | private-write | Protected. |
| POST | `/api/nutrition/label-upload` | private-write | Protected. |
| GET | `/api/nutrition/history` | private-read | Protected. |
| POST | `/api/nutrition/finalize-day` | private-write | Protected. |
| POST | `/api/nutrition/ai/parse` | private-write | Protected. |
| POST | `/api/food/analyze-text` | private-write | Protected. |
| POST | `/api/food/log-bulk` | private-write | Protected. |
| GET | `/api/nutrition/shortcuts` | private-read | Protected. |
| POST | `/api/nutrition/shortcuts` | private-write | Protected. |
| PUT | `/api/nutrition/shortcuts/{shortcut_id}` | private-write | Protected. |
| DELETE | `/api/nutrition/shortcuts/{shortcut_id}` | private-write | Protected. |
| POST | `/api/nutrition/shortcuts/{shortcut_id}/log` | private-write | Protected. |
| POST | `/api/nutrition/meal-templates` | private-write | Protected. |
| PUT | `/api/nutrition/meal-templates/{template_name}` | private-write | Protected. |
| POST | `/api/nutrition/meal-templates/{template_name}/log` | private-write | Protected. |
| POST | `/api/nutrition/frequent-foods/{food_name}/log` | private-write | Protected. |
| GET | `/api/training/logs` | private-read | Protected. |
| GET | `/api/training/history` | private-read | Protected. |
| GET | `/api/training/summary` | private-read | Protected. |
| GET | `/api/training/pr-history` | private-read | Protected. |
| POST | `/api/training/consolidate-history` | private-write | Protected. |
| GET | `/api/training/summary/status` | private-read | Protected. |
| GET | `/api/training/export/hevy-raw` | debug/export | Protected. |
| GET | `/api/training/schedule` | private-read | Protected. |
| PUT | `/api/training/schedule` | private-write | Protected. |
| GET | `/api/training/exercises` | private-read | Protected. |
| GET | `/api/training/strength-trends` | private-read | Protected. |
| GET | `/api/training/muscle-balance` | private-read | Protected. |
| POST | `/api/training/logs` | private-write | Protected. |
| POST | `/api/training/workout-date` | private-write | Protected. |
| POST | `/api/training/ai/insights` | private-write | Protected. |
| POST | `/api/training/import/strava` | private-write | Protected. |
| POST | `/api/training/sync/hevy` | private-write | Protected. |
| GET | `/api/training/sync/hevy/status` | private-read | Protected. |
| POST | `/api/training/import/hevy/preview` | private-write | Protected. |
| POST | `/api/training/import/hevy` | private-write | Protected. |
| GET | `/api/personal-records` | private-read | Protected. |
| POST | `/api/personal-records/manual` | private-write | Protected. |
| PUT | `/api/personal-records/bench` | private-write | Protected. |
| PUT | `/api/personal-records/mile` | private-write | Protected. |
| POST | `/api/personal-records/recalculate` | private-write | Protected. |
| GET | `/api/recovery/logs` | private-read | Protected. |
| GET | `/api/recovery/sleep` | private-read | Protected. |
| POST | `/api/recovery/logs` | private-write | Protected. |
| GET | `/api/body-metrics` | private-read | Protected. |
| POST | `/api/body-metrics` | private-write | Protected. |
| GET | `/api/settings` | private-read | Protected. Secrets masked. |
| PUT | `/api/settings` | private-write | Protected. Masked values preserve existing secrets. |
| GET | `/api/integrations/status` | private-read | Protected. Secret-redacted. |
| GET | `/api/integrations/test` | private-read | Protected. Explicit external check. Secret-redacted. |
| GET | `/api/integrations/strava/auth-url` | private-read | Protected. Starts OAuth flow. |
| POST | `/api/strava/refresh-token` | private-write | Protected. |
| POST | `/api/integrations/strava/disconnect` | private-write | Protected. |
| GET | `/api/withings/connect` | private-read | Protected. Starts OAuth flow. |
| GET | `/api/integrations/withings/auth-url` | private-read | Protected. Starts OAuth flow. |
| GET | `/api/withings/status` | private-read | Protected. |
| POST | `/api/withings/sync` | private-write | Protected. |
| GET | `/api/goals` | private-read | Protected. |
| POST | `/api/goals` | private-write | Protected. |
| POST | `/api/goals/apply-suggested-macros` | private-write | Protected. |
| GET | `/api/export/daily-csv` | debug/export | Protected. |
| GET | `/api/export/full-backup` | debug/export | Protected; secrets redacted from document exports. |
| POST | `/api/export/full-backup/import` | private-write | Protected. |
| POST | `/api/import/full-backup` | private-write | Protected. |

## Routes To Revisit Later

- Add route-level auth dependencies in addition to the global middleware after production session behavior is stable.
- Decide whether debug routes should require an extra admin flag or only appear in development.
- Consider CSRF protection for mutating routes if the app keeps using cross-site cookies directly instead of a same-origin proxy.
- Consider persistent or distributed login rate limiting if there will be more users or multiple backend replicas.
- Keep validating that raw exports are protected before exposing more export types.
- Rotate any secrets that were ever downloaded in older full backups before secret-redaction was added.

## Manual Verification Checklist

- Login succeeds through the deployed Vercel frontend.
- `/api/settings`, `/api/goals`, and `/api/dashboard/core` load after login.
- Food add, edit, delete, preset logging, and AI save still work.
- Hevy manual sync and Hevy webhook still work.
- Strava and Withings OAuth callbacks still complete.
- Debug panel works after login and does not display raw secrets.
- Export downloads data but does not include raw API keys, OAuth tokens, passwords, session secrets, client secrets, or database URLs.
