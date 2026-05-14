# Performance OS Product Design Plan

This document defines the future production frontend direction for Performance OS. The current Streamlit app remains the working MVP; this plan prepares the repo for a later Next.js frontend without starting that migration yet.

## Product Goal

Performance OS should feel like a focused command center for recovery, nutrition, training, bodyweight trends, and daily performance decisions. The production UI should preserve the local-first MVP workflows while making the experience faster, more polished, and easier to use on desktop and mobile.

## App Layout

The future web app should use a persistent shell with a left navigation rail on desktop and a bottom or drawer navigation pattern on mobile.

- Dashboard
- Food
- Weight & Recovery
- Training
- Data & History
- Integrations / Settings

### Dashboard

The Dashboard is the command center. It should give the user a fast read on today's state and the next useful action.

Primary content:

- Recovery score and classification
- Calories and protein progress for today
- Bodyweight trend
- Latest workout summary
- Recommendation summary
- Small trend previews for recovery, nutrition, and training load

### Food

The Food area should make logging low-friction while keeping macros transparent.

Primary content:

- Manual macro entry
- Frequent foods
- Favorite foods
- Meal templates
- One-click meal logging
- Optional AI-assisted food entry when configured
- Today's food list and macro totals

### Weight & Recovery

This area should combine bodyweight tracking with daily readiness inputs.

Primary content:

- Bodyweight entry
- Waist, estimated body fat, and notes
- Sleep, fatigue, soreness, stress, and motivation check-in
- Latest recovery score
- Recovery, fatigue, sleep, and training stress trends
- Fitbit / Google Health placeholder for future automatic sync

### Training

Training should support manual logging first, then future imports.

Primary content:

- Manual workout entry
- Strength training volume
- Latest workout
- Run/cardio summaries
- Hevy import placeholder
- Strava import placeholder
- Future imported workout review flow

### Data & History

This area should be the user's historical record and analysis workspace.

Primary content:

- Nutrition history table and charts
- Bodyweight history table and trend chart
- Workout history and volume charts
- Recovery history and score trends
- Running history once Strava import is enabled
- Export/download options in a later phase

### Integrations / Settings

Settings should make configuration understandable without exposing secrets.

Primary content:

- Hevy API key status
- Strava client ID and secret status
- Fitbit client ID and secret status
- OpenAI API key status
- Apple Health export upload placeholder
- Clear labels for configured, not configured, OAuth required, and local upload only

## Dashboard Card Design

Dashboard cards should be compact, scannable, and action-oriented. Each card should show the most important number, a short status label, and a small visual cue.

### Recovery Score

- Primary value: score from 0-100
- Secondary value: Optimal, Moderate, Fatigued, or High Risk
- Visual: circular progress or compact gauge
- Action cue: training readiness guidance

### Calories Today

- Primary value: calories logged today
- Secondary value: target calories and remaining calories
- Visual: progress bar
- Action cue: suggested adjustment when under or over target

### Protein Today

- Primary value: protein grams logged today
- Secondary value: target protein and remaining grams
- Visual: progress bar
- Action cue: short prompt when protein is behind target

### Bodyweight Trend

- Primary value: latest bodyweight
- Secondary value: 7-day trend direction
- Visual: small line chart
- Action cue: whether current trend matches goal

### Latest Workout

- Primary value: workout type or exercise name
- Secondary value: date, volume, duration, or RPE
- Visual: small strength/cardio indicator
- Action cue: note if training load is rising quickly

### Recommendation Summary

- Primary value: today's top recommendation
- Secondary value: confidence level
- Visual: status badge
- Action cue: calories, training intensity, cardio, recovery, or deload suggestion

## Visual Style

The UI should feel like a professional performance analytics product, not a generic admin panel.

Design direction:

- Dark professional dashboard
- Clean fintech and performance analytics aesthetic
- High-contrast text with restrained accent colors
- Subtle gradients for emphasis, not decoration
- Rounded cards with consistent radius
- Clear spacing and section hierarchy
- Responsive layout from desktop dashboard to mobile logging flows
- Charts that prioritize trend readability over ornament
- Minimal copy; labels and states should do most of the work

Suggested visual language:

- Background: near-black or deep charcoal
- Surfaces: slightly elevated charcoal panels
- Accent colors: green for readiness, amber for caution, red for risk, blue or cyan for neutral analytics
- Typography: modern sans serif with strong numeric readability
- Cards: 8-12px radius, soft borders, subtle shadow or glow only where useful

## User Flows

### Log Food Manually

1. User opens Food.
2. User selects date and meal type.
3. User enters food name, calories, protein, carbs, and fat.
4. User saves entry.
5. Food appears in today's log and dashboard totals update.

### Log Frequent Food

1. User opens Food.
2. User selects a saved frequent or favorite food.
3. User optionally overrides meal type.
4. User logs it with one click.
5. Entry is saved and reflected in today's totals.

### Enter Weight

1. User opens Weight & Recovery.
2. User enters bodyweight and optional waist, body fat estimate, or note.
3. User saves entry.
4. Trend chart and dashboard bodyweight card update.

### Submit Recovery Check-In

1. User opens Weight & Recovery.
2. User enters sleep hours, sleep quality, fatigue, soreness, stress, motivation, and optional HR metrics.
3. User saves check-in.
4. Recovery score, explanation, and trend charts update.

### Import Workouts Later

1. User configures Hevy or Strava credentials in Integrations / Settings.
2. User opens Training.
3. User starts an import.
4. App previews imported workouts and flags duplicates.
5. User confirms import.
6. Training log, recovery engine, and recommendations update.

### View Recommendation Summary

1. User opens Dashboard.
2. User reviews the recommendation summary card.
3. User opens details to see reasoning.
4. User can adjust goals or targets from Settings or a future goals panel.

## Future Frontend Stack

The planned production frontend stack is:

- Next.js for application routing and rendering
- TypeScript for safer UI and API contracts
- Tailwind CSS for styling and responsive layout
- Recharts for dashboard and history charts
- shadcn/ui for accessible primitives and polished controls
- FastAPI backend for local and future hosted API endpoints

The frontend should call FastAPI endpoints and avoid duplicating core analytics logic. Business logic should stay in `src/` and be exposed through backend routes.

## FastAPI Routes Needed

The current backend only has placeholders. A future production UI will need these API routes.

### System

- `GET /health`
- `GET /api/summary/today`
- `GET /api/dashboard`

### Nutrition

- `GET /api/nutrition/logs`
- `POST /api/nutrition/logs`
- `GET /api/nutrition/totals/today`
- `GET /api/nutrition/frequent-foods`
- `POST /api/nutrition/frequent-foods`
- `POST /api/nutrition/frequent-foods/{food_id}/log`
- `GET /api/nutrition/meal-templates`
- `POST /api/nutrition/meal-templates`
- `POST /api/nutrition/meal-templates/{template_id}/log`
- `GET /api/nutrition/analytics`
- `POST /api/nutrition/ai/parse`

### Body Metrics

- `GET /api/body-metrics`
- `POST /api/body-metrics`
- `GET /api/body-metrics/trends`

### Recovery

- `GET /api/recovery/logs`
- `POST /api/recovery/logs`
- `GET /api/recovery/latest`
- `GET /api/recovery/trends`
- `GET /api/recovery/explanation`

### Training

- `GET /api/training/logs`
- `POST /api/training/logs`
- `GET /api/training/volume`
- `GET /api/training/latest`
- `POST /api/training/import/hevy`
- `POST /api/training/import/strava`
- `GET /api/training/running/analytics`

### Recommendations

- `GET /api/recommendations/daily`
- `GET /api/recommendations/performance`
- `POST /api/recommendations/targets`

### Integrations / Settings

- `GET /api/settings`
- `PUT /api/settings`
- `GET /api/integrations/status`
- `POST /api/integrations/apple-health/upload`

## Migration Notes

- Keep Streamlit as the MVP until the Next.js app can cover the same workflows.
- Build FastAPI route coverage before building interactive frontend screens.
- Keep local CSV persistence in the near term.
- Do not expose API keys in client responses.
- Add durable storage only after the product flows stabilize.
- Treat `src/` as the shared modeling engine used by both Streamlit and FastAPI.
