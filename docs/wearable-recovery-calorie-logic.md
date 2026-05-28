# Performance OS Wearable, Recovery, and Calorie Logic

This document explains how Performance OS turns Google Health, recovery logs,
training history, nutrition logs, bodyweight trends, and workout markers into
dashboard signals. It is intended for internal review and external analysis of
the calculation logic.

The system is deterministic. The wearable/recovery/calorie logic does not use a
language model to create scores. It uses saved local data, Google Health daily
sync rows, and explicit thresholds.

Primary implementation files:

- `src/google_health_dashboard.py`
- `src/wearables.py`
- `src/analytics/recovery_engine.py`
- `src/nutrition_targets.py`
- `src/optimization/adaptive_nutrition_engine.py`
- `src/workout_nutrition.py`
- `src/analytics/training_workload.py`
- `backend_new/routes/integrations.py`
- `backend_new/routes/dashboard.py`
- `frontend/src/app/page.tsx`

## Data Flow

1. The user connects Google Health from Settings.
2. The frontend calls `/api/google-health/connect`.
3. The backend creates the OAuth URL server-side. The client secret never goes
   to the frontend.
4. Google redirects to `/api/google-health/callback`.
5. The backend exchanges the authorization code for tokens and saves token
   state in the app settings metadata and `google_health_connections`.
6. Manual sync calls `/api/google-health/sync`.
7. The backend refreshes the access token if needed.
8. The backend requests daily aggregate Google Fitness/Health data.
9. Normalized daily rows are saved to `wearable_metrics`.
10. Flexible raw category records are saved to:
    - `google_health_daily_summary`
    - `google_health_sleep`
    - `google_health_heart`
    - `google_health_activity`
    - `google_health_recovery_signals`
    - `google_health_sync_runs`
11. `/api/dashboard/core` loads nutrition, training, recovery, bodyweight, and
    wearable rows.
12. `build_google_health_dashboard_signals` creates dashboard-ready sleep,
    recovery, sickness, calorie, and activity payloads.
13. `frontend/src/app/page.tsx` renders the Google Health Signals card and the
    Calculation Details drawer.

Google Health sync is not part of startup. It runs only when the user clicks
Sync Now, so Google Health cannot freeze app boot. Dashboard startup reads
already-saved wearable rows only.

## Recovery Score Logic

There are two related recovery systems:

1. Classic recovery analytics from local recovery, sleep, training, and
   nutrition logs.
2. Google Health dashboard recovery readiness from same-day wearable data.

### Classic Recovery Analytics

Implemented in `src/analytics/recovery_engine.py`.

Inputs:

- Recovery check-ins:
  - sleep_hours
  - sleep_quality
  - fatigue
  - soreness
  - stress
  - motivation
- Training history:
  - sets
  - reps
  - weight
  - duration_minutes
  - RPE
  - run load extracted from notes when available
- Nutrition:
  - daily calories
  - target calories

Same-day base readiness is a 100 point score:

- Sleep duration: up to 20 points.
  - Formula: `min(sleep_hours / 8, 1) * 20`.
- Sleep quality: up to 15 points.
  - Formula: `(sleep_quality / 10) * 15`.
- Motivation: up to 15 points.
  - Formula: `(motivation / 10) * 15`.
- Fatigue: up to 18 points.
  - Formula: `((11 - fatigue) / 10) * 18`.
- Soreness: up to 16 points.
  - Formula: `((11 - soreness) / 10) * 16`.
- Stress: up to 16 points.
  - Formula: `((11 - stress) / 10) * 16`.

Rolling penalties:

- Sleep debt:
  - Target sleep is 8 hours.
  - Daily shortfall is `max(8 - sleep_hours, 0)`.
  - Sleep debt is the rolling 7-day sum of shortfall.
  - Penalty is `sleep_debt * 2.2`, capped at 25 points.
- Fatigue load:
  - Daily fatigue load is average of fatigue and soreness.
  - Rolling window is 3 days.
  - Penalty is `(fatigue_load - 5) * 5` when fatigue_load is above 5.
- Training stress:
  - Daily stress is strength volume / 1000, plus duration / 30, plus average
    RPE, plus run load / 10.
  - Rolling window is 7 days.
  - Penalty is `training_stress * 0.7`, capped at 20 points.
- Calorie deficit:
  - Deficit is `max(target_calories - logged_calories, 0)`.
  - Penalty is `calorie_deficit / 100`, capped at 15 points.

Final score:

`base_readiness - sleep_debt_penalty - fatigue_penalty - training_penalty - calorie_deficit_penalty`

The result is clipped to 0-100.

Classification:

- 80 or higher: Optimal.
- 65 to 79.9: Moderate.
- 45 to 64.9: Fatigued.
- Below 45: High Risk.

### Recovery Signal Confidence

`analyze_recovery_signal` separates recovery into:

- measured recovery
- inferred recovery
- insufficient data

Measured recovery exists when subjective recovery fields or wearable fields
such as HRV/resting HR are present. If recovery rows are missing, the system can
infer a low-confidence recovery state from workload and performance, but it
does not present that as a precise high-confidence score.

Confidence:

- High: measured recovery with at least 14 rows.
- Medium: measured recovery with at least 7 rows.
- Low: sparse measured data, inferred data, or insufficient data.

### Google Health Recovery Readiness

Implemented in `src/google_health_dashboard.py`.

The Google Health dashboard readiness starts at 100 and subtracts penalties:

- Sleep quality:
  - poor: -20
  - fair: -8
  - good: no penalty
- Resting HR:
  - abnormal/elevated: -15
  - watch: -6
- HRV:
  - suppressed: -15
  - watch: -5
- Sickness warning signals:
  - `8 * abnormal_signal_count`, capped by the code path at the total readiness
    clipping behavior.
- High activity/training load: -10.
- Poor subjective recovery report: -12.

The result is clipped to 0-100.

Readiness status:

- 80 or higher: green, label Ready.
- 60 to 79.9: yellow, label Reduce intensity.
- Below 60: red, label Recovery priority.

This readiness score is a dashboard signal, not a medical score.

## Sleep Analysis Logic

Google Health sleep quality uses a weighted score when data exists:

- Sleep duration: 40 percent of the signal.
  - Normalized as `sleep_hours / 8`, capped at 1.
- Sleep efficiency: 25 percent.
  - Normalized as `sleep_efficiency / 92`, capped at 1.
- REM plus deep sleep: 20 percent.
  - Normalized as `(rem_minutes + deep_minutes) / 150`, capped at 1.
- Source sleep score: 15 percent.
  - Normalized as `sleep_score / 100`, capped at 1.

If only some fields exist, the available weights are rescaled over the fields
that are present. If no sleep fields are present, sleep status is
`insufficient_data`.

Sleep status:

- Score 82 or higher: good.
- Score 68 to 81.9: fair.
- Below 68: poor.
- Missing score: insufficient_data.

Poor sleep is also flagged when:

- sleep duration is below 6.5 hours, or
- sleep efficiency is below 80 percent.

Sleep consistency is not yet a direct dashboard tile. The broader recovery
engine uses rolling sleep debt and 7-day sleep averages, which indirectly
captures consistency.

## Resting HR and HRV Baseline Logic

### Resting HR

The dashboard uses same-day resting HR and a baseline.

Baseline source priority:

1. `resting_hr_baseline` stored on the wearable row.
2. Average of recent prior resting HR values from the previous 14 days, using
   the latest 7 available prior values.

Deviation:

- If `resting_hr_deviation` is present, use it.
- Otherwise calculate `resting_hr - baseline`.

Status:

- high: deviation is 5 bpm or more.
- normal: deviation is 2 bpm or less.
- watch: deviation is above 2 but below 5.
- insufficient_data: missing resting HR or baseline.

### HRV

The HRV baseline is the average of recent prior HRV values from the previous
14 days, using the latest 7 available prior values.

Status:

- suppressed: same-day HRV is below 90 percent of baseline.
- watch: same-day HRV is below 95 percent of baseline.
- normal: HRV exists and is not below those thresholds.
- insufficient_data: missing HRV or missing baseline.

## Sickness Warning Logic

The sickness warning is conservative and non-diagnostic.

Potential abnormal signals:

- Resting HR elevated above baseline.
- HRV suppressed below baseline.
- Poor sleep quality.
- Breathing rate elevated:
  - threshold: breathing_rate >= 22.
- SpO2 lower than normal:
  - threshold: SpO2 < 94.
- Skin temperature elevated versus baseline:
  - threshold: absolute skin temperature delta between 1 and 5.
  - Values outside that range are not trusted as a delta.
- Body temperature elevated:
  - threshold: body_temperature >= 37.8 Celsius.
- User reports poor recovery:
  - recovery_score below 60, or
  - fatigue at least 7, or
  - sleep_quality 5 or lower.

Dashboard status:

- warning: 2 or more abnormal signals.
- watch: 1 abnormal signal.
- clear: 0 abnormal signals.

Displayed warning language:

- "Possible sickness / elevated recovery risk"
- "Consider reducing intensity today"
- "Prioritize sleep, hydration, and easy movement"
- "This is not a diagnosis."

The system does not diagnose illness. It only flags a recovery risk pattern.

## Activity Load Logic

Google Health dashboard activity load combines:

- steps / 1000
- active minutes
- active zone minutes * 1.5
- distance miles * 2
- recent training minutes / 20

High activity load is flagged when any of these are true:

- active minutes >= 90
- active zone minutes >= 45
- recent training minutes over the last 7 days >= 240
- conservative recent hard sets >= 35

Training hard sets are conservative:

- RPE 7 or higher: full hard set count.
- RPE missing with weighted working sets: 0.5 multiplier.
- Missing or unweighted work does not automatically become a full hard set.

Wearable readiness in `src/wearables.py` also computes a broader activity load:

- steps / 1000
- active minutes
- active zone minutes * 1.5
- distance meters / 1000
- workout minutes
- cardio load
- calories burned / 150

Recent activity is compared against baseline with `_recent_vs_baseline`.
Activity is considered unusually high when recent average is more than 25
percent above baseline, or steps are more than 3000 over baseline.

## Calorie Adjustment Logic

There are two calorie concepts:

1. Saved target calories.
2. Google Health calorie burn context.

The saved target is the actual calorie target used by the app. Google Health
burn is not used directly as the final target.

### Why Wearable Burn Is Not Directly Trusted

Wearable calorie burn can drift because of sensor accuracy, device model,
algorithm changes, missing wear time, workout type, and user-specific energy
economy. Performance OS uses it as context and an activity modifier, while the
actual target changes require bodyweight trend confirmation.

### Base Maintenance Estimate

Implemented in `src/nutrition_targets.py`.

Maintenance estimate:

`bodyweight * activity_multiplier + training_adjustment + cardio_adjustment`

Activity multipliers:

- Low: 13.0
- Moderate: 14.2
- High: 14.8
- Very High: 15.5

Training/cardio adjustments:

- strength training frequency: up to 6 sessions * 35 kcal
- cardio frequency: up to 6 sessions * 25 kcal

### Goal Adjustment

Lean bulk:

- Conservative: +150 to +225 kcal, midpoint used.
- Moderate: +225 to +350 kcal, midpoint used.
- Aggressive: +325 to +450 kcal, midpoint used.
- Add 50 kcal if training frequency is at least 5.
- Add 50 kcal if cardio frequency is at least 3 or weekly mileage is at least
  12.

Cut:

- Conservative: -250 kcal.
- Moderate: -400 kcal.
- Aggressive: -550 kcal.

Recomposition:

- Usually 0 kcal adjustment.
- Aggressive recomposition can use -100 kcal.

Performance / mile time:

- +100 kcal if activity level is High or Very High.

### Bodyweight Trend Adjustment

Bodyweight trend uses canonical daily bodyweights.

Minimum data:

- At least 7 recent weigh-ins.

Trend windows:

- Current 7-day average.
- Previous 7-day average when at least 3 previous-window entries exist.
- Otherwise partial 7-day trend from first to latest recent point.
- 14-day average is used when 14 points exist.

Lean bulk target rate:

- Conservative: +0.2 percent to +0.4 percent bodyweight per week.
- Moderate: +0.4 percent to +0.7 percent per week.
- Aggressive: +0.5 percent to +0.8 percent per week.

Adjustments:

- Gaining too slowly:
  - +75 kcal normally.
  - +150 kcal when confidence is high and the rate is less than half the lower
    target.
- Gaining in target range:
  - 0 kcal.
- Gaining too fast:
  - -100 kcal normally.
  - -200 kcal when confidence is high and rate is more than 1.5x the upper
    target.
- Noisy data:
  - 0 kcal until trend clears.

Cut and maintenance/recomposition/performance have separate target ranges in
`adaptive_nutrition_engine.py`.

### Google Health Calorie Context

Dashboard Google Health calorie logic:

- `calories_burned` comes from total Google Health burn.
- `logged_intake` comes from same-day food totals.
- `intake_vs_burned = logged_intake - calories_burned`.

Maintenance detection:

- If absolute delta is <= 150 kcal:
  - status: likely_near_maintenance.
- If intake is more than 300 kcal below burn:
  - status: below_estimated_burn.
- If intake is more than 300 kcal above burn:
  - status: above_estimated_burn.
- Otherwise:
  - status: near_estimated_burn.

Activity modifier:

If saved baseline target and Google Health burn exist:

`activity_modifier = clamp((calories_burned - saved_target) * 0.15, -150, +150)`

This is context only. It is not automatically saved.

Recovery modifier:

- sickness warning: -100 kcal context modifier.
- red recovery readiness: -50 kcal context modifier.
- high activity load with green recovery readiness: +50 kcal context modifier.
- otherwise: 0.

Context target:

`saved_target + activity_modifier + recovery_modifier`

Suggested saved-target adjustment:

- Default is 0.
- Requires at least 7 bodyweight points in the last 14 days.
- If weekly bodyweight change is below -0.35 lb/week and intake is more than
  150 kcal below wearable burn:
  - suggest +100 kcal.
- If weekly bodyweight change is above +0.6 lb/week and intake is more than
  150 kcal above wearable burn:
  - suggest -100 kcal.

The app holds the saved target when bodyweight trend confirmation is missing.

## Workout Nutrition Marker Logic

Workout markers are manual sequence dividers. They do not rely primarily on
actual workout time.

Food timing classification:

- Food rows with sequence before marker: pre-workout.
- Food rows with sequence after marker: post-workout.
- Food rows without stable order: unknown timing.

Multiple markers:

- Each marker only considers foods between the previous marker and the next
  marker on the same date.
- Same-day totals are shown separately.
- This avoids double-counting when multiple markers exist in one day.

Fueling flags:

- Pre-workout carbs below 40g on a high-stress session:
  - suggest 40-60g carbs before similar workouts.
- Pre-workout carbs below 20g:
  - suggest adding a simple carb source if workouts feel flat.
- Pre-workout fat around 25g or more:
  - warning that digestion may be slower.
- Post-workout protein below 30g:
  - reminder to add protein after training.

Deload/fueling risk:

- High-stress sessions are training volume >= 12000 or average RPE >= 8.
- Recent 5-marker window is checked for:
  - repeated high-stress sessions
  - repeated low-carb sessions
  - poor recent recovery
  - declining recovery

## Baseline Systems

### Resting HR Baseline

- Preferred: baseline stored on the wearable row.
- Fallback: average of prior available resting HR values in the previous 14
  days, using the latest 7 values.
- Elevated threshold: +5 bpm.

### HRV Baseline

- Average of prior available HRV values in the previous 14 days, using the
  latest 7 values.
- Watch threshold: below 95 percent of baseline.
- Suppressed threshold: below 90 percent of baseline.

### Sleep Baseline

The dashboard uses same-day Google Health sleep quality. The broader recovery
engine uses:

- rolling 7-day sleep debt
- recent 7-day sleep average
- sleep trend delta versus prior window when enough rows exist

### Activity Baseline

Wearable readiness compares recent average against baseline average through
`_recent_vs_baseline`. It requires at least 3 baseline samples before treating
activity as unusually high.

Activity-high thresholds:

- recent activity load > baseline * 1.25
- or recent steps > baseline + 3000

### Calorie Expenditure Baseline

Wearable readiness compares recent wearable calorie burn against baseline.
High burn is flagged when recent average is more than 15 percent above baseline
with at least 3 baseline samples.

This affects hydration/electrolyte risk and activity context, not the saved
calorie target.

## Dashboard Tile Explanations

### Sleep Quality

Meaning:

- How supportive last night's sleep appears for recovery.

Inputs:

- sleep duration
- REM minutes
- deep sleep minutes
- light sleep minutes
- awake minutes
- sleep efficiency
- source sleep score if available

Calculation:

- Weighted 0-100 score from duration, efficiency, restorative sleep, and source
  score.

### Recovery Readiness

Meaning:

- Whether wearable/recovery context supports normal training today.

Inputs:

- sleep quality status
- resting HR deviation
- HRV suppression
- sickness abnormal signal count
- activity load
- subjective recovery report

Calculation:

- Starts at 100 and subtracts penalties for poor/watched signals.

### Sickness Warning

Meaning:

- A conservative warning that multiple recovery-health signals are abnormal.

Inputs:

- resting HR
- HRV
- sleep
- breathing rate
- SpO2
- skin temperature
- body temperature
- subjective recovery

Calculation:

- 2 or more abnormal signals creates a warning.
- 1 abnormal signal creates watch.

### Resting HR vs Baseline

Meaning:

- Whether resting HR is elevated relative to the user's recent norm.

Inputs:

- same-day resting HR
- saved or computed baseline

Calculation:

- deviation = same-day RHR - baseline.
- high at +5 bpm or more.

### Calories Burned vs Intake

Meaning:

- Whether logged intake is near wearable-estimated burn for context.

Inputs:

- Google Health total calories burned
- same-day logged intake

Calculation:

- intake minus burn.
- within +/-150 kcal is labeled likely near maintenance.

Important:

- This tile does not set the saved calorie target.

### Suggested Calorie Adjustment

Meaning:

- Whether the app sees enough evidence to consider a small target change.

Inputs:

- saved calorie target
- Google Health burn
- activity modifier
- recovery modifier
- bodyweight trend confirmation

Calculation:

- Holds at 0 unless bodyweight trend and intake/burn relationship both support
  a change.

### Activity Load

Meaning:

- Whether today's activity and recent training are likely adding fatigue.

Inputs:

- active minutes
- active zone minutes
- steps
- distance
- recent training minutes
- conservative hard sets

Calculation:

- Weighted activity load score plus hard threshold flags.

### Vitals

Meaning:

- Optional recovery-health context.

Inputs:

- SpO2
- breathing rate
- skin temperature
- body temperature

Calculation:

- These feed the sickness-warning abnormal signal count if present.

## Debug and Transparency

The dashboard has a Calculation Details / Why drawer in the Google Health
Signals card. It exposes:

- current sleep, HR, HRV, activity, calorie, and bodyweight-confirmation inputs
- baseline comparisons
- calorie modifiers
- current reasoning messages
- missing metric warnings
- latest metric date
- wearable row count

The Settings integration card also exposes:

- connection status
- token status
- last sync result
- last sync timestamp
- warning count
- storage error count
- last sync error when present

## Safety and Fallbacks

Disconnected or missing Google Health:

- dashboard returns `insufficient_data`
- UI displays "No wearable data connected"
- recovery section remains usable
- no NaN/null values are shown as real scores

Partial sync:

- missing metrics become warnings
- available metrics still render
- optional metric failures do not fail the full sync

Expired token:

- token refresh is attempted server-side
- refresh failure marks reconnect required
- sync returns an error response without crashing startup

Failed sync:

- sync run is recorded in `google_health_sync_runs`
- status, error, warning, and timestamp are saved
- dashboard startup is unaffected because sync is user-triggered

## Known Limitations

- Sleep consistency is only indirectly represented through rolling sleep debt
  and sleep averages.
- Google Health calorie burn is treated as context because it can be inaccurate.
- HRV and recovery-health signals depend on whether the connected device/source
  exposes those fields.
- The sickness warning is a recovery-risk signal only. It is not medical advice.
