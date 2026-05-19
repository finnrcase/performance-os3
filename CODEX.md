Content:

# Codex Project Instructions

Use the tooling in DEV_TOOLING.md whenever debugging or improving this app.

For UI/browser issues:
- write or run Playwright tests
- capture screenshots/traces when possible

For API/backend issues:
- inspect endpoint status, response body, and timing
- add structured logs before guessing

For database/data issues:
- inspect row counts and data shapes
- avoid full-table scans in startup paths

For performance issues:
- profile first
- report slowest function/block
- include before/after timings

Prefer staged, safe commits.
Do not rewrite large systems blindly.

Acceptance:

DEV_TOOLING.md exists
CODEX.md or .codex/instructions.md exists
Future Codex sessions can read these files and know what tools to use
No app runtime code should break from this docs-only change