import Link from "next/link";

const sections = [
  {
    title: "Data Flow",
    body: [
      "Google Health OAuth runs on the FastAPI backend. The frontend requests an auth URL, but the client secret never leaves the server.",
      "Manual sync calls /api/google-health/sync. The backend refreshes the access token if needed, fetches daily aggregate metrics, normalizes rows into wearable_metrics, and stores flexible category records for sleep, heart, activity, recovery signals, and sync runs.",
      "Dashboard startup does not call Google Health. It reads already-saved wearable rows through /api/dashboard/core, so a slow or failed sync cannot freeze app boot.",
    ],
  },
  {
    title: "Recovery Score Logic",
    body: [
      "Classic recovery analytics use subjective recovery, sleep debt, fatigue/soreness, training stress, and calorie deficit. Base readiness is 100 points spread across sleep duration (20), sleep quality (15), motivation (15), fatigue (18), soreness (16), and stress (16).",
      "Rolling penalties subtract sleep debt times 2.2 capped at 25, fatigue load above 5 times 5, training stress times 0.7 capped at 20, and calorie deficit divided by 100 capped at 15.",
      "Google Health readiness starts at 100 and subtracts penalties for poor/fair sleep, elevated resting HR, suppressed HRV, abnormal sickness-warning signals, high activity load, and poor subjective recovery. The final value is clipped to 0-100.",
    ],
  },
  {
    title: "Sleep Analysis",
    body: [
      "Google Health sleep quality is weighted from available fields: sleep duration is 40 percent, efficiency is 25 percent, REM plus deep sleep is 20 percent, and source sleep score is 15 percent.",
      "Duration is normalized to 8 hours, efficiency to 92 percent, restorative sleep to 150 minutes, and source score to 100. Missing fields are skipped and the available weights are rescaled.",
      "Sleep is poor if the weighted score is below 68, duration is below 6.5 hours, or efficiency is below 80 percent. Sleep debt in the recovery engine uses a rolling 7-day shortfall from an 8-hour target.",
    ],
  },
  {
    title: "Resting HR and HRV Baselines",
    body: [
      "Resting HR baseline uses a stored Google Health baseline when available. Otherwise it averages prior resting HR values from the previous 14 days, using the latest 7 available values.",
      "Resting HR deviation is same-day resting HR minus baseline unless a saved deviation is present. A deviation of 5 bpm or more is high; 2 bpm or less is normal; the middle range is watch.",
      "HRV baseline averages prior HRV values from the previous 14 days, using the latest 7 available values. HRV below 95 percent of baseline is watch; below 90 percent is suppressed.",
    ],
  },
  {
    title: "Sickness Warning",
    body: [
      "The system flags abnormal signals from elevated resting HR, suppressed HRV, poor sleep, breathing rate at or above 22, SpO2 below 94, skin temperature delta between 1 and 5, body temperature at or above 37.8 C, or poor user-reported recovery.",
      "One abnormal signal creates a watch state. Two or more abnormal signals create the warning state: Possible sickness / elevated recovery risk.",
      "The app avoids diagnosis. The message is intentionally conservative: consider reducing intensity today, prioritize sleep, hydration, and easy movement, and this is not a diagnosis.",
    ],
  },
  {
    title: "Activity Load",
    body: [
      "Dashboard activity load combines steps / 1000, active minutes, active zone minutes times 1.5, distance miles times 2, and recent training minutes / 20.",
      "High load is flagged when active minutes are at least 90, active zone minutes are at least 45, recent 7-day training minutes are at least 240, or conservative hard sets are at least 35.",
      "Hard sets are conservative: RPE 7 or higher counts fully; weighted working sets with missing RPE count at 0.5; missing or unweighted work does not automatically become a hard set.",
    ],
  },
  {
    title: "Calorie Logic",
    body: [
      "Saved target calories remain the real target. Google Health calorie burn is shown as context and never directly overwrites the saved target.",
      "Maintenance starts from bodyweight times an activity multiplier, then adds small training and cardio frequency adjustments. Goal mode then adds a conservative lean-bulk surplus, cut deficit, recomposition hold, or performance support.",
      "Google Health context compares logged intake with total calories burned. Within plus or minus 150 kcal is likely near maintenance. More than 300 kcal below or above burn becomes below_estimated_burn or above_estimated_burn.",
      "The activity modifier is clamp((wearable burn - saved target) * 0.15, -150, +150). The recovery modifier is -100 for sickness warning, -50 for red recovery, +50 for high activity with green recovery, otherwise 0. These create a context target only.",
      "A saved-target adjustment stays at 0 unless enough bodyweight data confirms the direction. The Google Health dashboard path requires at least 7 weigh-ins in the last 14 days before suggesting a small 100 kcal change.",
    ],
  },
  {
    title: "Workout Marker Nutrition",
    body: [
      "Workout markers are manual sequence dividers. Foods logged before the marker are pre-workout, foods logged after are post-workout, and foods without stable ordering are unknown timing.",
      "When multiple markers exist on one day, each marker only considers food between the previous and next marker. Same-day totals are shown separately to avoid double-counting.",
      "Fueling flags look for low pre-workout carbs, high pre-workout fat near training, post-workout protein under 30g, repeated high-stress sessions, and recovery decline.",
    ],
  },
  {
    title: "Dashboard Tiles",
    body: [
      "Sleep Quality shows the weighted sleep score and sleep components. Recovery Readiness shows the wearable readiness penalty model. Sickness Warning shows multi-signal recovery-health risk.",
      "Resting HR vs Baseline shows same-day RHR, baseline, and deviation. Calories Burned vs Intake compares logged intake against wearable burn as context. Suggested Calorie Adjustment explains whether bodyweight confirmation supports any target change.",
      "Activity Load summarizes active minutes, active zone minutes, steps, and training load. Vitals shows optional SpO2, breathing rate, skin temperature, and body temperature when Google Health exposes them.",
    ],
  },
  {
    title: "Fallbacks and Transparency",
    body: [
      "Disconnected Google Health returns insufficient_data and the UI displays No wearable data connected. Partial syncs show missing metric warnings while preserving the rest of the dashboard.",
      "Expired tokens are refreshed server-side. Refresh failure marks reconnect required and records the sync error. Failed syncs do not run during startup and do not block the app.",
      "The dashboard Calculation Details drawer exposes current inputs, modifiers, baseline comparisons, reasoning messages, missing metric warnings, metric row count, and latest metric date.",
    ],
  },
];

export const metadata = {
  title: "Calculation Logic | Performance OS",
};

export default function CalculationLogicPage() {
  return (
    <main className="min-h-screen bg-[#07080b] px-5 py-8 text-zinc-100 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-5xl">
        <Link href="/" className="text-sm font-semibold text-emerald-200 hover:text-emerald-100">
          Back to Performance OS
        </Link>
        <header className="mt-8 border-b border-white/10 pb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-emerald-300/80">Internal Documentation</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight text-white">Wearable, Recovery, and Calorie Logic</h1>
          <p className="mt-4 max-w-3xl text-base leading-7 text-zinc-400">
            A transparent reference for how Performance OS turns Google Health, recovery logs, training history,
            nutrition, bodyweight trends, and workout markers into dashboard signals. The logic is deterministic
            and designed to be reviewed rather than treated as a black box.
          </p>
        </header>

        <section className="mt-8 grid gap-3 md:grid-cols-3">
          {[
            ["Primary source", "Google Health daily aggregates plus local logs"],
            ["Target safety", "Wearable burn is context, not the saved calorie target"],
            ["Medical safety", "Sickness warning is recovery risk, not diagnosis"],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">{label}</p>
              <p className="mt-2 text-sm font-semibold leading-6 text-zinc-100">{value}</p>
            </div>
          ))}
        </section>

        <div className="mt-8 space-y-4">
          {sections.map((section) => (
            <section key={section.title} className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
              <h2 className="text-xl font-semibold text-white">{section.title}</h2>
              <div className="mt-4 space-y-3 text-sm leading-7 text-zinc-400">
                {section.body.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
              </div>
            </section>
          ))}
        </div>

        <section className="mt-4 rounded-xl border border-emerald-300/20 bg-emerald-300/[0.06] p-5">
          <h2 className="text-xl font-semibold text-white">Implementation Map</h2>
          <div className="mt-4 grid gap-2 text-sm leading-6 text-zinc-300 md:grid-cols-2">
            {[
              "src/google_health_dashboard.py",
              "src/wearables.py",
              "src/analytics/recovery_engine.py",
              "src/nutrition_targets.py",
              "src/optimization/adaptive_nutrition_engine.py",
              "src/workout_nutrition.py",
              "backend_new/routes/integrations.py",
              "backend_new/routes/dashboard.py",
              "frontend/src/app/page.tsx",
              "docs/wearable-recovery-calorie-logic.md",
            ].map((path) => (
              <code key={path} className="rounded-md border border-white/10 bg-black/20 px-2 py-1 text-xs text-emerald-100">{path}</code>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
