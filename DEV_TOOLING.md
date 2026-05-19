Preferred Dev Tooling Stack
Browser/UI QA
Playwright
Agent Browser when available

Use for:

startup checks
login flow tests
visual screenshots
regression tests
UI bug reproduction
screenshot/video/trace capture
Database Inspection
TablePlus
Supabase dashboard/Postgres dashboard

Use for:

inspecting tables
validating sync/imports
checking row counts
debugging data shape issues
verifying migrations
Error Tracking
Sentry

Use for:

frontend crashes
backend exceptions
slow endpoints
production error tracing
failed dashboard blocks
API Testing
HTTPie/curl

Use for:

health checks
endpoint debugging
auth/session verification
API response inspection
Backend Profiling
pyinstrument
line-profiler
memory-profiler

Use for:

slow endpoint diagnosis
pandas/data bottlenecks
memory-heavy flows
backend CPU profiling
Frontend Quality
TypeScript
ESLint
Prettier
Playwright visual tests

Use for:

build safety
clean code
regression protection
UI consistency
Design/UI
Figma
v0
Cursor visual editing
Framer/Relume when useful

Use for:

design references
component mockups
premium dashboard layouts
responsive UI polish
Codex Operating Instructions

When debugging:

Do not guess if tooling can verify the issue.
Use Playwright for browser/UI problems.
Use API checks for endpoint failures.
Use Postgres/TablePlus inspection for data problems.
Use Sentry/logs for crashes.
Use pyinstrument/profilers for slow backend endpoints.
Capture before/after timings when fixing performance.
Add screenshots/traces for UI regressions.
Prefer small staged fixes over giant rewrites.
Output a short debugging report after major fixes:
issue
evidence
root cause
fix
tests run
before/after behavior
Install Commands
npm install -D playwright
npx playwright install
npm install -g agent-browser
agent-browser install
npm install @sentry/nextjs
python3 -m pip install sentry-sdk
python3 -m pip install pyinstrument line-profiler memory-profiler
brew install httpie
brew install --cask tableplus
npm install -D typescript eslint prettier