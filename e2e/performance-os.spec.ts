import { expect, test, type Page } from "@playwright/test";

const appPassword = process.env.PLAYWRIGHT_APP_PASSWORD ?? "playwright-password";

async function loginWithPage(page: Page) {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Performance OS" })).toBeVisible();
  await page.getByLabel("Password").fill(appPassword);
  await page.getByRole("button", { name: /unlock/i }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible({ timeout: 120_000 });
}

test.describe("Performance OS startup and critical flows", () => {
  test("login unlocks the dashboard", async ({ page }) => {
    await loginWithPage(page);
    await expect(page.getByTestId("nav-food")).toBeVisible();
    await expect(page.getByText(/backend/i)).toBeVisible();
  });

  test("startup load renders without system failure", async ({ page }) => {
    await loginWithPage(page);
    await expect(page.getByText("System failed to load")).toHaveCount(0);
    await expect(page.getByTestId("nav-training")).toBeVisible();
  });

  test("core startup API endpoints return successfully", async ({ page }) => {
    await loginWithPage(page);

    for (const path of ["/api/settings", "/api/goals", "/api/dashboard/core"]) {
      const result = await page.evaluate(async (requestPath) => {
        const started = performance.now();
        const response = await fetch(requestPath, { credentials: "include" });
        const body = await response.text();
        return {
          ok: response.ok,
          status: response.status,
          body,
          durationMs: Math.round(performance.now() - started),
        };
      }, path);
      expect(result.ok, `${path} failed in ${result.durationMs}ms with ${result.status}: ${result.body.slice(0, 1000)}`).toBeTruthy();
    }
  });

  test("food manual add and delete updates today's list", async ({ page }) => {
    await loginWithPage(page);
    await page.getByTestId("nav-food").click();
    await expect(page.getByTestId("food-page")).toBeVisible();
    await expect(page.getByRole("button", { name: "Log Workout Marker" })).toBeVisible();

    const foodName = `Playwright Food ${Date.now()}`;
    const form = page.getByTestId("manual-food-form");
    await form.getByLabel("Food name").fill(foodName);
    await form.getByLabel("Calories").fill("123");
    await form.getByLabel("Protein").fill("12");
    await form.getByLabel("Carbs").fill("18");
    await form.getByLabel("Fat").fill("3");
    await form.getByRole("button", { name: "Add Food" }).click();

    const foodRow = page.getByTestId("food-log-row").filter({ hasText: foodName }).first();
    await expect(foodRow).toBeVisible();

    page.once("dialog", (dialog) => dialog.accept());
    await foodRow.getByRole("button", { name: `Remove ${foodName}` }).click();
    await expect(page.getByTestId("food-log-row").filter({ hasText: foodName })).toHaveCount(0);
  });

  test("training page loads and Hevy sync button reports a result", async ({ page }) => {
    await loginWithPage(page);

    await page.route("**/api/training/sync/hevy", async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ok",
          checked_hevy: true,
          sync_mode: "incremental_events",
          fallback_recent_import: false,
          events: 0,
          saved_workouts: 0,
          new_workouts: 0,
          updated_workouts: 0,
          deleted_rows: 0,
          failures: [],
          items: [],
          last_synced_at: new Date().toISOString(),
          hevy_rows: 0,
          hevy_workouts: 0,
        }),
      });
    });

    await page.getByTestId("nav-training").click();
    await expect(page.getByRole("heading", { name: "Training", exact: true })).toBeVisible();
    await expect(page.getByText("Hevy and Strava")).toBeVisible();

    await page.getByRole("button", { name: /refresh hevy now/i }).click();
    await expect(page.getByText(/Hevy checked:/)).toBeVisible();
  });

  test("exercise PRs render in Goals and not on Dashboard", async ({ page }) => {
    await loginWithPage(page);

    await page.route("**/api/training/prs*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ok",
          source: "training_history_fallback",
          items: [
            {
              pr_id: "exercise-pr:bench-press",
              exercise: "Bench Press",
              weight: 225,
              unit: "lb",
              reps: 3,
              estimated_1rm: 247.5,
              date: "2026-05-21",
              source: "hevy",
            },
          ],
          diagnostics: {
            source_reason: "exercise_prs table was missing or empty; PRs were computed from normalized workout_logs.",
          },
        }),
      });
    });

    await expect(page.getByRole("heading", { name: "PRs", exact: true })).toHaveCount(0);

    await page.getByTestId("nav-goals").click();
    await expect(page.getByRole("heading", { name: "Goals & Targets" })).toBeVisible();
    await expect(page.getByTestId("goals-pr-section")).toContainText("Bench Press");
    await expect(page.getByTestId("goals-pr-section")).toContainText("225 lb");

    await page.getByTestId("nav-dashboard").click();
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "PRs", exact: true })).toHaveCount(0);
  });
});
