import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const frontendPort = Number(process.env.PLAYWRIGHT_FRONTEND_PORT ?? 3000);
const backendPort = Number(process.env.PLAYWRIGHT_BACKEND_PORT ?? 8001);
const appPassword = process.env.PLAYWRIGHT_APP_PASSWORD ?? "playwright-password";
const sessionSecret = process.env.PLAYWRIGHT_SESSION_SECRET ?? "playwright-session-secret-for-performance-os";
const repoRoot = path.resolve(process.cwd(), "..");
const backendUrl = `http://127.0.0.1:${backendPort}`;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const dataDir = process.env.PLAYWRIGHT_DATA_DIR ?? path.join(repoRoot, ".playwright-data");
const baseEnv = { ...process.env };
delete baseEnv.FORCE_COLOR;
const frontendCommand =
  process.env.PLAYWRIGHT_FRONTEND_COMMAND ??
  `npm run start -- --hostname 127.0.0.1 --port ${frontendPort}`;

const sharedEnv = {
  ...baseEnv,
  APP_PASSWORD: appPassword,
  SESSION_SECRET: sessionSecret,
  BACKEND_API_URL: backendUrl,
  NEXT_PUBLIC_API_URL: backendUrl,
  ALLOW_LOCAL_BACKEND_API_URL: "1",
  DATABASE_URL: process.env.PLAYWRIGHT_DATABASE_URL ?? "",
  PERFORMANCE_OS_DATA_DIR: dataDir,
  SENTRY_DSN: "",
  NEXT_PUBLIC_SENTRY_DSN: "",
  NO_COLOR: "1",
};

export default defineConfig({
  testDir: "../e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: frontendUrl,
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: `python3 -m uvicorn backend.main:app --host 127.0.0.1 --port ${backendPort}`,
      url: `${backendUrl}/health`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      cwd: repoRoot,
      env: sharedEnv,
    },
    {
      command: frontendCommand,
      url: frontendUrl,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      cwd: process.cwd(),
      env: sharedEnv,
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
