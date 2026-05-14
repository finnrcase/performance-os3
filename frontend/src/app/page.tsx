"use client";

import {
  Activity,
  Apple,
  BarChart3,
  Check,
  ChevronDown,
  Dumbbell,
  Gauge,
  HeartPulse,
  Pencil,
  Plus,
  RefreshCw,
  Settings,
  Sparkles,
  Target,
  Utensils,
  Weight,
  X,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart as RechartsLineChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  (process.env.NODE_ENV === "development" ? "http://localhost:8001" : "");

function apiUrl(path: string) {
  return API_BASE ? `${API_BASE}${path}` : path;
}
let hevyAutoSyncStarted = false;

const navigation = [
  { id: "dashboard", label: "Dashboard", icon: Gauge },
  { id: "food", label: "Food", icon: Utensils },
  { id: "goals", label: "Goals & Targets", icon: Target },
  { id: "recovery", label: "Weight & Recovery", icon: HeartPulse },
  { id: "training", label: "Training", icon: Dumbbell },
  { id: "history", label: "Data & History", icon: BarChart3 },
  { id: "settings", label: "Integrations / Settings", icon: Settings },
] as const;

type PageId = (typeof navigation)[number]["id"];

type Goals = {
  current_bodyweight: number;
  goal_bodyweight: number;
  timeline_weeks: number;
  goal_type: string;
  training_frequency_per_week: number;
  cardio_frequency_per_week: number;
  estimated_body_fat: number | null;
  activity_level: string;
  aggressiveness: string;
};

type RecoverySignal = {
  status: "good" | "normal" | "strained" | "poor" | "insufficient data" | string;
  confidence: "low" | "medium" | "high" | string;
  score: number | null;
  summary: string;
  nutrition_implication: string;
  suggested_action: string;
  drivers: Array<{ name: string; severity: string; detail: string; value?: string | number | null }>;
  metrics?: Record<string, number | string | null>;
};

type Targets = {
  target_calories: number;
  maintenance_calories: number;
  calorie_adjustment: number;
  protein_grams: number;
  carb_grams: number;
  fat_grams: number;
  macro_calories?: number;
  calorie_macro_delta?: number;
  protein_per_lb?: number;
  fat_per_lb?: number;
  fat_floor_grams?: number;
  carb_emphasis?: string;
  historical_note?: string;
  historical_calorie_adjustment?: number;
  recovery_average?: number | null;
  recovery_signal?: RecoverySignal;
  weekly_weight_change_pct?: number | null;
  target_weekly_change_pct?: number;
  target_weekly_change_range?: { low: number | null; high: number | null };
  expected_weekly_weight_change: number;
  target_description: string;
  timeline_status: string;
  timeline_warning: string;
  updated_at?: string;
};

type WeightFeedback = {
  status: string;
  weekly_change_pct: number | null;
  weekly_change_lb: number | null;
  suggested_adjustment: string;
  reason: string;
  window_used: string;
  current_7_day_avg?: number | null;
  previous_7_day_avg?: number | null;
  fourteen_day_avg?: number | null;
  confidence?: string;
  calorie_adjustment?: number;
  target_weekly_change_low?: number | null;
  target_weekly_change_high?: number | null;
};

type NutritionEntry = {
  date: string;
  meal_type: string;
  food_name: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  serving_size_grams?: number | null;
  grams_consumed?: number | null;
  serving_multiplier?: number | null;
  calories_per_serving?: number | null;
  protein_per_serving?: number | null;
  carbs_per_serving?: number | null;
  fat_per_serving?: number | null;
  fiber?: number | null;
  sodium?: number | null;
  potassium?: number | null;
  source_label_file?: string;
};

type DailyNutritionSummary = {
  date: string;
  total_calories: number;
  total_protein: number;
  total_carbs: number;
  total_fat: number;
  fiber: number | null;
  sodium: number | null;
  potassium: number | null;
  magnesium: number | null;
  calcium: number | null;
  iron: number | null;
  zinc: number | null;
  vitamin_d: number | null;
  omega_3: number | null;
  target_calories: number | null;
  target_protein: number | null;
  target_carbs: number | null;
  target_fat: number | null;
  calories_delta: number | null;
  protein_delta: number | null;
  carbs_delta: number | null;
  fat_delta: number | null;
  adherence_score: number | null;
  notes: string;
};

type NutritionAdherence = {
  average_calories: number | null;
  average_target_calories: number | null;
  average_calories_delta: number | null;
  average_protein: number | null;
  average_target_protein: number | null;
  average_protein_delta: number | null;
  days_over_target: number;
  days_under_target: number;
  consistency_score: number | null;
};

type ParsedFood = {
  food_name: string;
  quantity: string;
  quantity_value?: number | null;
  unit?: string;
  serving_description?: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  fiber?: number | null;
  sugar?: number | null;
  sodium?: number | null;
  confidence: "low" | "medium" | "high" | string;
  verification_needed?: boolean;
  verification_reason?: string;
  source?: "ai_estimate" | "verified_online" | "saved_shortcut" | "manual" | string;
  source_id?: string | null;
  verification_status?: string;
  source_url?: string;
  original_text?: string;
  assumptions?: string[];
  needs_review?: boolean;
  notes: string;
};

type BodyMetricEntry = {
  date: string;
  bodyweight: number;
  waist: number | null;
  estimated_body_fat: number | null;
  notes: string;
};

type RecoveryEntry = {
  date: string;
  sleep_hours: number;
  sleep_quality: number;
  fatigue: number;
  soreness: number;
  stress: number;
  motivation: number;
  resting_hr: number | null;
  hrv: number | null;
  notes: string;
};

type SleepEntry = {
  id: string;
  userId: string;
  date: string;
  sleepStart: string;
  sleepEnd: string;
  durationMinutes: number | null;
  efficiencyPercent: number | null;
  deepSleepMinutes: number | null;
  remSleepMinutes: number | null;
  lightSleepMinutes: number | null;
  awakeMinutes: number | null;
  restingHeartRate: number | null;
  hrv: number | null;
  source: "manual" | "fitbit" | "google_fit" | "mock" | string;
  createdAt: string;
  updatedAt: string;
};

type TrainingEntry = {
  workout_id: string;
  date: string;
  workout_type: string;
  muscle_group: string;
  exercise: string;
  set_number: number;
  sets: number;
  reps: number;
  weight: number;
  rpe: number;
  duration_minutes: number;
  notes: string;
  source: string;
  external_id: string;
};

type WorkoutGroup = {
  date: string;
  workout_id: string;
  workout_type: string;
  muscle_groups: string[];
  exercise_names: string[];
  total_sets: number;
  total_volume: number;
  duration_minutes: number;
  source: string;
  details: TrainingEntry[];
};

type StrengthTrend = {
  exercise: string;
  label: string;
  change_pct?: number;
  history: Array<{
    date: string;
    best_set_weight: number;
    estimated_1rm: number;
    total_volume: number;
    average_working_weight: number;
    average_rpe: number;
    total_reps: number;
  }>;
  best_set: { date: string; weight: number; reps: number; estimated_1rm: number; rpe: number } | null;
  recent_pr: boolean | null;
  summary: string;
};

type StrengthTrendResponse = {
  exercise_options: string[];
  selected_exercise: string;
  trend: StrengthTrend;
  volume_by_exercise: Array<{ exercise: string; volume: number; sets: number }>;
  muscle_group_trends: MuscleGroupTrendResponse;
};

type MuscleGroupTrendSummary = {
  muscle_group: string;
  strength_change_pct: number;
  volume_change_pct: number;
  strength_index: number;
  weekly_volume: number;
  hard_sets: number;
  total_reps: number;
  workout_frequency: number;
  average_working_weight: number;
  best_estimated_1rm: number;
  recent_best_exercise: string;
};

type MuscleGroupTrendHistory = {
  week: string;
  muscle_group: string;
  weekly_volume: number;
  hard_sets: number;
  total_reps: number;
  average_working_weight: number;
  best_estimated_1rm: number;
  workout_frequency: number;
  strength_index: number;
};

type MuscleGroupTrendResponse = {
  date_range: string;
  muscle_group_options: string[];
  selected_muscle_group: string;
  summary: MuscleGroupTrendSummary[];
  history: MuscleGroupTrendHistory[];
  unmapped_exercises: string[];
};

type TrainingInsight = {
  success: boolean;
  message: string;
  error_code: string | null;
  model: string;
  top_insights: string[];
  possible_issues: string[];
  recommended_adjustments: string[];
  confidence_level: string;
  evidence: string[];
};

type PersonalRecords = {
  bench_press: {
    value: number;
    unit: string;
    reps: number;
    date: string;
    source: string;
    estimated_1rm: number;
    notes?: string;
    manual_override?: boolean;
    updated_at?: string;
  } | null;
  mile_time: {
    value_seconds: number;
    display: string;
    date: string;
    source: string;
    estimated: boolean;
    notes?: string;
    manual_override?: boolean;
    updated_at?: string;
  } | null;
  history: {
    bench_press: Array<Record<string, unknown>>;
    mile_time: Array<Record<string, unknown>>;
  };
};

type LeanBulkDecision = {
  recommendation: "increase" | "decrease" | "maintain";
  calorie_change: number;
  new_target_calories: number;
  confidence: "low" | "medium" | "high";
  weekly_weight_change_pct: number | null;
  fat_gain_risk_score: number;
  reasoning: string[];
  next_check_in_days: number;
  details: {
    seven_day_avg_weight: number | null;
    fourteen_day_avg_weight: number | null;
    calorie_average: number | null;
    protein_average: number | null;
    protein_target: number | null;
    training_trend: string;
    recovery_trend: string;
    recovery_average?: number | null;
    target_weekly_gain_pct: number | null;
    calorie_target_delta_average?: number | null;
    protein_consistency?: number | null;
    days_over_calorie_target?: number | null;
    days_under_calorie_target?: number | null;
    key_lift_trends?: Record<string, { exercise: string | null; label: string }>;
    performance_signal?: {
      label: string;
      confidence: "low" | "medium" | "high";
      summary: string;
      recommendation: string;
      drivers: Array<{
        name: string;
        muscle_group?: string;
        signal: string;
        estimated_1rm_change_pct?: number | null;
        volume_change_pct?: number | null;
        reps_at_same_weight_delta?: number | null;
      }>;
      muscle_group_drivers?: Array<{
        muscle_group: string;
        signal: string;
        estimated_1rm_change_pct?: number | null;
        exercise_count?: number;
      }>;
    };
    recovery_signal?: RecoverySignal;
  };
};

type AdaptiveNutritionRecommendation = {
  caloriesTarget: number;
  proteinTarget: number;
  carbsTarget: number;
  fatTarget: number;
  calorieAdjustment: number;
  macroChanges: { calories: number; protein: number; carbs: number; fat: number };
  confidence: "low" | "medium" | "high" | string;
  reasoning: string[];
  warnings: string[];
  strategy: string;
  currentTarget: { calories: number; protein: number; carbs: number; fat: number };
  recommendedTargets: Targets;
  signals: {
    weight: {
      status: string;
      weekly_change_pct?: number | null;
      weekly_change_lb?: number | null;
      calorie_adjustment?: number;
      confidence?: string;
      reason?: string;
    };
    performance: NonNullable<LeanBulkDecision["details"]["performance_signal"]>;
    recovery: RecoverySignal;
    trainingLoad: { status: string; summary: string; hard_sets_per_week?: number; weekly_training_minutes?: number };
    runningLoad: { status: string; summary: string; runs_per_week?: number; weekly_mileage?: number };
    nutrition: { days: number; calories: number | null; protein: number | null; carbs: number | null; fat: number | null };
  };
};

type PersonalLearningInsight = {
  title: string;
  explanation: string;
  confidence: "low" | "medium" | "high" | string;
  window: string;
  impact?: number;
};

type PersonalLearning = {
  status: "ready" | "learning" | "insufficient data" | string;
  confidence: "low" | "medium" | "high" | string;
  summary: string;
  window: string;
  data_points: number;
  insights: PersonalLearningInsight[];
};

type WeeklyReport = {
  status: "ready" | "learning" | string;
  period_label: string;
  summary: string;
  rows: Array<{ label: string; value: string; detail: string }>;
  best_trend: string;
  watch: string;
  recommendation: string;
};

type HevyPreviewWorkout = {
  workout_id: string;
  title: string;
  date: string;
  exercise_names: string[];
  estimated_rows: number;
  duplicate: boolean;
  duplicate_rows: number;
  new_rows: number;
};

type HevyPreview = {
  status: string;
  message?: string;
  workouts: HevyPreviewWorkout[];
  estimated_rows: number;
  duplicates_detected: number;
  debug_file?: string;
  warnings: string[];
};

type HevySyncStatus = {
  last_synced_at: string;
  last_error: string;
  last_result: Record<string, unknown>;
};

type HevySyncResult = {
  status: string;
  message?: string;
  events: number;
  saved_workouts: number;
  deleted_rows: number;
  failures?: string[];
  items: TrainingEntry[];
  last_synced_at: string;
};

type DashboardData = {
  date: string;
  food: {
    calories: { eaten: number; target: number | null; left: number | null; over: number | null; percent: number };
    protein: { eaten: number; target: number | null; left: number | null; over: number | null; percent: number };
    carbs: { eaten: number; target: number | null; left: number | null; over: number | null; percent: number };
    fat: { eaten: number; target: number | null; left: number | null; over: number | null; percent: number };
    has_targets: boolean;
    has_food_logged: boolean;
  };
  weight: {
    today_weight: number | null;
    latest_weight: number | null;
    seven_day_average: number | null;
    trend_label: string;
    history: BodyMetricEntry[];
    message: string;
  };
  lift_performance: {
    status: string;
    summary: string;
    comparison: string | null;
    today_volume: number | null;
    percent_vs_average: number | null;
  };
  workout_quality: {
    status: string;
    score: number | null;
    score_label: string;
    confidence: string;
    color: "gray" | "red" | "orange" | "green" | "bright_green" | string;
    explanation: string;
    comparison: string | null;
    source: string;
  };
  todays_action: {
    status: string;
    color: "green" | "yellow" | "red" | "gray" | string;
    headline: string;
    reason: string;
  };
  recovery: {
    connected: boolean;
    source: string;
    latest_score: number | null;
    trend: Array<{ date: string; recovery_score: number }>;
    sleep: Array<{ date: string; sleep_hours: number }>;
    hrv: Array<{ date: string; hrv: number }>;
    resting_hr: Array<{ date: string; resting_hr: number }>;
    status: string;
    classification: string;
    message: string;
    extra_run_readiness: {
      status: "green" | "yellow" | "red" | "insufficient_data";
      message: string;
      recommended_run: string;
      reasoning: string[];
    };
  };
  prs: Pick<PersonalRecords, "bench_press" | "mile_time">;
  goals: Goals;
  targets: Targets;
  nutrition_today: { calories: number; protein: number; carbs: number; fat: number };
  latest_bodyweight: number | null;
  bodyweight_trend: BodyMetricEntry[];
  weight_feedback: WeightFeedback;
  latest_recovery: { recovery_score: number; classification: string; explanation?: string } | null;
  recovery_trend: Array<{ date: string; recovery_score: number; classification: string }>;
  latest_workout: TrainingEntry | null;
  strength_trend_summary: { exercise: string; label: string; summary: string };
  muscle_balance_warning: string | null;
  ai_insight_preview: string | null;
  training_volume: Array<{ date: string; volume: number }>;
  personal_records: PersonalRecords;
  lean_bulk_decision: LeanBulkDecision;
  adaptive_recommendation: AdaptiveNutritionRecommendation;
  personal_learning: PersonalLearning;
  weekly_report: WeeklyReport;
  recommendation: { recommendation_summary: string; reasoning_explanation: string };
  counts: { nutrition: number; body_metrics: number; recovery: number; training: number };
};

type SettingsData = {
  integrations: Record<string, string>;
  statuses: Record<string, string>;
};

type FormState = {
  nutrition: NutritionEntry;
  body: BodyMetricEntry;
  recovery: RecoveryEntry;
  training: TrainingEntry;
  goals: Goals;
  settings: Record<string, string>;
  benchPr: { weight: number; reps: number; date: string; notes: string; editing: boolean };
  milePr: { minutes: number; seconds: number; date: string; notes: string; editing: boolean };
};

type ServingScaleForm = {
  food_name: string;
  serving_size_grams: number;
  calories_per_serving: number;
  protein_per_serving: number;
  carbs_per_serving: number;
  fat_per_serving: number;
  fiber_per_serving: number | "";
  sodium_per_serving: number | "";
  potassium_per_serving: number | "";
  grams_consumed: number;
  source_label_file: string;
};

type LabelUploadResult = {
  uploaded_filename: string;
  path: string;
  extraction_status: "not_implemented" | "uploaded" | string;
  message: string;
};

type FoodParseResponse = {
  foods: ParsedFood[];
  total: { calories: number; protein: number; carbs: number; fat: number };
  source: string;
  cached: boolean;
  success: boolean;
  error_code: string | null;
  message: string;
  debug: {
    backend_endpoint_reached?: boolean;
    openai_key_configured?: boolean;
    model?: string;
    parsing_status?: string;
  };
};

type FoodAnalyzeResponse = {
  items: Array<{
    name: string;
    original_text: string;
    quantity: number | null;
    unit: string;
    serving_description: string;
    calories: number;
    protein_g: number;
    carbs_g: number;
    fat_g: number;
    fiber_g: number | null;
    sugar_g: number | null;
    sodium_mg: number | null;
    confidence: "low" | "medium" | "high" | string;
    source: "usda_fdc" | "existing_database" | "openai_estimate" | "web_source" | string;
    source_id: string | null;
    source_url: string | null;
    assumptions: string[];
    needs_review: boolean;
  }>;
  totals: {
    calories: number;
    protein_g: number;
    carbs_g: number;
    fat_g: number;
    fiber_g: number | null;
    sugar_g: number | null;
    sodium_mg: number | null;
  };
  warnings: string[];
  message: string;
  success: boolean;
  error_code: string | null;
  debug: FoodParseResponse["debug"];
};

type FoodShortcut = {
  shortcut_id: string;
  shortcut_name: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  fiber: number | null;
  sodium: number | null;
  potassium: number | null;
  serving_size_grams?: number | null;
  default_grams_consumed?: number | null;
  calories_per_serving?: number | null;
  protein_per_serving?: number | null;
  carbs_per_serving?: number | null;
  fat_per_serving?: number | null;
  notes: string;
  created_at: string;
  source: string;
};

type MealTemplate = {
  template_name: string;
  default_meal_type: string;
  food_name: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
};

type NutritionShortcutData = {
  items: FoodShortcut[];
  frequent_foods: Array<{ food_name: string; calories: number; protein: number; carbs: number; fat: number; default_meal_type: string; is_favorite?: boolean }>;
  meal_templates: MealTemplate[];
};

const DEFAULT_MEAL_TYPE = "Food";
const integrationLabels: Record<string, string> = {
  hevy_api_key: "Hevy API key",
  strava_client_id: "Strava client ID",
  strava_client_secret: "Strava client secret",
  fitbit_client_id: "Fitbit client ID",
  fitbit_client_secret: "Fitbit client secret",
  withings_client_id: "Withings client ID",
  withings_client_secret: "Withings client secret",
  openai_api_key: "OpenAI API key",
  apple_health_export_file: "Apple Health upload placeholder",
};

function todayString() {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  return new Date(now.getTime() - offset * 60_000).toISOString().slice(0, 10);
}

const defaultGoals: Goals = {
  current_bodyweight: 180,
  goal_bodyweight: 185,
  timeline_weeks: 16,
  goal_type: "Lean Bulk",
  training_frequency_per_week: 4,
  cardio_frequency_per_week: 2,
  estimated_body_fat: null,
  activity_level: "Moderate",
  aggressiveness: "Conservative",
};

const initialForms: FormState = {
  nutrition: {
    date: todayString(),
    meal_type: DEFAULT_MEAL_TYPE,
    food_name: "",
    calories: 0,
    protein: 0,
    carbs: 0,
    fat: 0,
  },
  body: {
    date: todayString(),
    bodyweight: 0,
    waist: null,
    estimated_body_fat: null,
    notes: "",
  },
  recovery: {
    date: todayString(),
    sleep_hours: 7,
    sleep_quality: 5,
    fatigue: 5,
    soreness: 5,
    stress: 5,
    motivation: 5,
    resting_hr: null,
    hrv: null,
    notes: "",
  },
  training: {
    workout_id: "",
    date: todayString(),
    workout_type: "Strength",
    muscle_group: "",
    exercise: "",
    set_number: 1,
    sets: 0,
    reps: 0,
    weight: 0,
    rpe: 0,
    duration_minutes: 0,
    notes: "",
    source: "manual",
    external_id: "",
  },
  goals: defaultGoals,
  settings: {},
  benchPr: {
    weight: 0,
    reps: 1,
    date: todayString(),
    notes: "",
    editing: false,
  },
  milePr: {
    minutes: 0,
    seconds: 0,
    date: todayString(),
    notes: "",
    editing: false,
  },
};

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(apiUrl(path), { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function apiSend<T>(path: string, method: "POST" | "PUT", body: unknown): Promise<T> {
  const response = await fetch(apiUrl(path), {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${path} returned ${response.status}: ${text}`);
  }
  return response.json() as Promise<T>;
}

async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(apiUrl(path), { method: "DELETE" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${path} returned ${response.status}: ${text}`);
  }
  return response.json() as Promise<T>;
}

async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(apiUrl(path), {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${path} returned ${response.status}: ${text}`);
  }
  return response.json() as Promise<T>;
}

function Card({ children, className }: Readonly<{ children: React.ReactNode; className?: string }>) {
  return (
    <section className={cx("rounded-lg border border-white/10 bg-zinc-950/70 p-5 shadow-2xl shadow-black/20 backdrop-blur", className)}>
      {children}
    </section>
  );
}

function SectionHeader({ eyebrow, title, action }: Readonly<{ eyebrow?: string; title: string; action?: React.ReactNode }>) {
  return (
    <div className="mb-4 flex items-start justify-between gap-4">
      <div>
        {eyebrow ? <p className="mb-1 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300/80">{eyebrow}</p> : null}
        <h2 className="text-lg font-semibold text-white">{title}</h2>
      </div>
      {action ? <div>{action}</div> : null}
    </div>
  );
}

function MetricCard({
  title,
  value,
  detail,
  icon: Icon,
  accent,
}: Readonly<{
  title: string;
  value: string;
  detail: string;
  icon: React.ElementType;
  accent: string;
}>) {
  return (
    <Card className="min-h-[150px]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm text-zinc-400">{title}</p>
          <p className="mt-3 text-2xl font-semibold text-white">{value}</p>
          <p className="mt-2 text-sm text-zinc-400">{detail}</p>
        </div>
        <div className={cx("rounded-lg border p-2", accent)}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </Card>
  );
}

function TargetDetailCard({
  title,
  value,
  subvalue,
  note,
  icon: Icon,
  accent,
}: Readonly<{
  title: string;
  value: string;
  subvalue: string;
  note: string;
  icon: React.ElementType;
  accent: string;
}>) {
  return (
    <Card className="min-h-[172px] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-zinc-400">{title}</p>
          <p className="mt-2 text-2xl font-semibold text-white">{value}</p>
          <p className="mt-1 text-sm text-zinc-300">{subvalue}</p>
        </div>
        <div className={cx("shrink-0 rounded-lg border p-2", accent)}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
      <p className="mt-4 text-xs leading-5 text-zinc-500">{note}</p>
    </Card>
  );
}

type MacroMoleculeKind = "protein" | "carbs" | "fat";

function MacroMoleculeIcon({
  kind,
  className = "h-5 w-5",
}: Readonly<{
  kind: MacroMoleculeKind;
  className?: string;
}>) {
  const nodes = {
    protein: (
      <>
        <path d="M7 12h4.5l3.2-4.8H20" />
        <path d="M11.5 12l3.2 4.8H20" />
        <path d="M7 12l-2 3.5" />
        <circle cx="5" cy="12" r="2" />
        <circle cx="15.2" cy="6" r="2" />
        <circle cx="15.2" cy="18" r="2" />
        <circle cx="21" cy="6" r="1.5" />
        <circle cx="21" cy="18" r="1.5" />
      </>
    ),
    carbs: (
      <>
        <path d="M8 5.5h8l4 6.5-4 6.5H8L4 12l4-6.5Z" />
        <path d="M8 5.5 12 12l-4 6.5" />
        <path d="M16 5.5 12 12l4 6.5" />
        <circle cx="12" cy="12" r="1.8" />
        <circle cx="4" cy="12" r="1.4" />
        <circle cx="20" cy="12" r="1.4" />
      </>
    ),
    fat: (
      <>
        <path d="M3.5 14.5c2.2-4.3 5.1-6.5 8.5-6.5 3.2 0 5.8 1.8 8.5 5.5" />
        <path d="M6.5 17c1.9-2.4 3.9-3.6 6-3.6 2.2 0 4.1 1.1 5.9 3.3" />
        <circle cx="4" cy="14.5" r="1.5" />
        <circle cx="12" cy="8" r="1.8" />
        <circle cx="20" cy="13.5" r="1.5" />
        <circle cx="6.5" cy="17" r="1.2" />
        <circle cx="18.5" cy="16.7" r="1.2" />
      </>
    ),
  };

  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.7"
      viewBox="0 0 24 24"
    >
      {nodes[kind]}
    </svg>
  );
}

function macroMoleculeKind(label: string): MacroMoleculeKind | null {
  const normalized = label.toLowerCase();
  if (normalized.includes("protein")) return "protein";
  if (normalized.includes("carb")) return "carbs";
  if (normalized.includes("fat")) return "fat";
  return null;
}

function ProteinMoleculeIcon({ className }: Readonly<{ className?: string }>) {
  return <MacroMoleculeIcon kind="protein" className={className} />;
}

function CarbsMoleculeIcon({ className }: Readonly<{ className?: string }>) {
  return <MacroMoleculeIcon kind="carbs" className={className} />;
}

function FatMoleculeIcon({ className }: Readonly<{ className?: string }>) {
  return <MacroMoleculeIcon kind="fat" className={className} />;
}

function macroIconAccent(label: string) {
  const kind = macroMoleculeKind(label);
  if (kind === "protein") return "border-teal-300/20 bg-teal-300/10 text-teal-300";
  if (kind === "carbs") return "border-blue-300/20 bg-blue-300/10 text-blue-300";
  if (kind === "fat") return "border-amber-300/20 bg-amber-300/10 text-amber-300";
  return "border-cyan-300/20 bg-cyan-300/10 text-cyan-300";
}

type MacroProgress = {
  label: string;
  unit: string;
  eaten: number;
  target: number;
  left: number;
  over: number;
  percent: number;
  accent: string;
};

function buildMacroProgress(label: string, unit: string, eaten: number, target: number, accent: string): MacroProgress {
  const safeEaten = Math.max(0, Number(eaten) || 0);
  const safeTarget = Math.max(0, Number(target) || 0);
  return {
    label,
    unit,
    eaten: safeEaten,
    target: safeTarget,
    left: Math.max(safeTarget - safeEaten, 0),
    over: Math.max(safeEaten - safeTarget, 0),
    percent: safeTarget > 0 ? Math.min((safeEaten / safeTarget) * 100, 100) : 0,
    accent,
  };
}

function MacroProgressCard({ macro }: Readonly<{ macro: MacroProgress }>) {
  const moleculeKind = macroMoleculeKind(macro.label);
  return (
    <div className="group rounded-lg border border-white/10 bg-white/[0.035] p-4 transition hover:border-white/15">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          {moleculeKind ? (
            <div className={cx("rounded-lg border p-2 transition group-hover:bg-white/[0.045]", macroIconAccent(macro.label))}>
              <MacroMoleculeIcon kind={moleculeKind} />
            </div>
          ) : null}
          <div>
            <p className="text-sm text-zinc-400">{macro.label}</p>
            <p className="mt-2 text-2xl font-semibold text-white">
              {Math.round(macro.eaten)}
              <span className="text-sm font-medium text-zinc-500"> / {Math.round(macro.target)}{macro.unit}</span>
            </p>
          </div>
        </div>
        <span className={cx("rounded-full px-2.5 py-1 text-xs font-medium", macro.over > 0 ? "bg-amber-300/10 text-amber-200" : "bg-emerald-300/10 text-emerald-200")}>
          {macro.over > 0 ? `+${Math.round(macro.over)}${macro.unit} over` : `${Math.round(macro.left)}${macro.unit} left`}
        </span>
      </div>
      <div className="mt-4 h-2 rounded-full bg-white/10">
        <div className={cx("h-2 rounded-full", macro.accent)} style={{ width: `${macro.percent}%` }} />
      </div>
      <p className="mt-2 text-xs text-zinc-500">{Math.round(macro.percent)}% complete</p>
    </div>
  );
}

function MacroDonut({ macro }: Readonly<{ macro: MacroProgress }>) {
  const moleculeKind = macroMoleculeKind(macro.label);
  const chartData = [
    { name: `${macro.label} complete`, value: Math.min(macro.eaten, macro.target) },
    { name: `${macro.label} left`, value: macro.left },
  ];
  const safeChartData = chartData.every((item) => item.value <= 0)
    ? [{ name: `${macro.label} left`, value: 1 }]
    : chartData;
  const colors = [macro.accent.includes("teal") ? "#2dd4bf" : macro.accent.includes("blue") ? "#60a5fa" : "#f59e0b", "#27272a"];

  return (
    <div className="group rounded-lg border border-white/10 bg-white/[0.035] p-4 transition hover:border-white/15">
      <div className="relative h-36">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={safeChartData} dataKey="value" nameKey="name" innerRadius={42} outerRadius={62} stroke="none">
              {safeChartData.map((entry, index) => (
                <Cell key={entry.name} fill={colors[index] ?? "#27272a"} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8, color: "#fff" }}
              formatter={(value) => [`${Math.round(Number(value ?? 0))}${macro.unit}`, macro.label]}
            />
          </PieChart>
        </ResponsiveContainer>
        {moleculeKind ? (
          <div className={cx("pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border p-2 transition group-hover:bg-white/[0.045]", macroIconAccent(macro.label))}>
            <MacroMoleculeIcon kind={moleculeKind} className="h-5 w-5" />
          </div>
        ) : null}
      </div>
      <p className="text-center text-sm font-medium text-white">{macro.label}</p>
      <p className="mt-1 text-center text-xs text-zinc-500">
        {macro.over > 0 ? `Over by ${Math.round(macro.over)}${macro.unit}` : `${Math.round(macro.left)}${macro.unit} remaining`}
      </p>
    </div>
  );
}

function EmptyState({
  title,
  description,
  action,
  onAction,
}: Readonly<{ title: string; description: string; action: string; onAction: () => void }>) {
  return (
    <div className="rounded-lg border border-dashed border-white/15 bg-white/[0.03] p-6">
      <p className="font-medium text-white">{title}</p>
      <p className="mt-2 text-sm text-zinc-400">{description}</p>
      <button onClick={onAction} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-cyan-300 px-3 py-2 text-sm font-semibold text-zinc-950">
        <Plus className="h-4 w-4" />
        {action}
      </button>
    </div>
  );
}

function TextInput({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  required = false,
  min,
  step,
  disabled = false,
}: Readonly<{
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
  required?: boolean;
  min?: number;
  step?: number | string;
  disabled?: boolean;
}>) {
  return (
    <label className="space-y-2 text-sm text-zinc-400">
      <span>{label}</span>
      <input
        className="h-11 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 text-zinc-100 outline-none transition placeholder:text-zinc-600 focus:border-cyan-300/60"
        value={value}
        type={type}
        placeholder={placeholder}
        required={required}
        min={min}
        step={step}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function SelectInput({
  label,
  value,
  options,
  onChange,
}: Readonly<{ label: string; value: string; options: string[]; onChange: (value: string) => void }>) {
  return (
    <label className="space-y-2 text-sm text-zinc-400">
      <span>{label}</span>
      <select
        className="h-11 w-full rounded-lg border border-white/10 bg-zinc-950 px-3 text-zinc-100 outline-none transition focus:border-cyan-300/60"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option || "All"}
          </option>
        ))}
      </select>
    </label>
  );
}

function ChartFrame({ children, className }: Readonly<{ children: React.ReactNode; className: string }>) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => setMounted(true));
    return () => window.cancelAnimationFrame(frame);
  }, []);
  return <div className={className}>{mounted ? children : <div className="h-full w-full animate-pulse rounded-lg bg-white/[0.04]" />}</div>;
}

function compactDate(date: string) {
  return date?.slice(5) || "";
}

function aggregateNutrition(logs: NutritionEntry[]) {
  const totals = new Map<string, { date: string; calories: number; protein: number }>();
  logs.forEach((entry) => {
    const current = totals.get(entry.date) ?? { date: entry.date, calories: 0, protein: 0 };
    current.calories += Number(entry.calories) || 0;
    current.protein += Number(entry.protein) || 0;
    totals.set(entry.date, current);
  });
  return Array.from(totals.values()).sort((a, b) => a.date.localeCompare(b.date));
}

function deltaText(value: number | null | undefined, unit = "") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "No target";
  }
  const rounded = Math.round(Number(value));
  if (rounded === 0) {
    return `On target${unit ? ` ${unit}` : ""}`;
  }
  return `${rounded > 0 ? "+" : ""}${rounded}${unit}`;
}

function stateSafeMileSeconds(value: { minutes: number; seconds: number }) {
  return Math.max(Number(value.minutes) || 0, 0) * 60 + Math.max(Number(value.seconds) || 0, 0);
}

function normalizeSearchText(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
}

function findSavedFoodMatch(text: string, shortcuts: FoodShortcut[], templates: MealTemplate[], frequentFoods: NutritionShortcutData["frequent_foods"] = []) {
  const query = normalizeSearchText(text);
  if (!query) {
    return null;
  }
  const shortcut = shortcuts.find((item) => {
    const name = normalizeSearchText(item.shortcut_name);
    return name && (query.includes(name) || name.includes(query));
  });
  if (shortcut) {
    return { type: "shortcut" as const, label: shortcut.shortcut_name, id: shortcut.shortcut_id };
  }
  const frequent = frequentFoods.find((item) => {
    const name = normalizeSearchText(item.food_name);
    return name && (query.includes(name) || name.includes(query));
  });
  if (frequent) {
    return { type: "frequent" as const, label: frequent.food_name, id: frequent.food_name };
  }
  const templateNames = Array.from(new Set(templates.map((item) => item.template_name)));
  const templateName = templateNames.find((name) => {
    const normalized = normalizeSearchText(name);
    return normalized && (query.includes(normalized) || normalized.includes(query));
  });
  return templateName ? { type: "template" as const, label: templateName, id: templateName } : null;
}

function calculateServingPreview(form: ServingScaleForm) {
  const servingSize = Number(form.serving_size_grams) || 0;
  const grams = Number(form.grams_consumed) || 0;
  const multiplier = servingSize > 0 ? grams / servingSize : 0;
  const scale = (value: number | "") => Number(value || 0) * multiplier;
  return {
    multiplier,
    calories: scale(form.calories_per_serving),
    protein: scale(form.protein_per_serving),
    carbs: scale(form.carbs_per_serving),
    fat: scale(form.fat_per_serving),
    fiber: form.fiber_per_serving === "" ? null : scale(form.fiber_per_serving),
    sodium: form.sodium_per_serving === "" ? null : scale(form.sodium_per_serving),
    potassium: form.potassium_per_serving === "" ? null : scale(form.potassium_per_serving),
  };
}

function DashboardProgressLine({ label, value, target, left, over, percent, unit = "g" }: Readonly<{
  label: string;
  value: number;
  target: number | null;
  left: number | null;
  over: number | null;
  percent: number;
  unit?: string;
}>) {
  const moleculeKind = macroMoleculeKind(label);
  return (
    <div>
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="inline-flex items-center gap-2 text-zinc-400">
          {moleculeKind ? <MacroMoleculeIcon kind={moleculeKind} className="h-4 w-4" /> : null}
          {label}
        </span>
        <span className="font-medium text-zinc-100">
          {Math.round(value)}{unit === "kcal" ? "" : unit} / {target ? `${Math.round(target)}${unit === "kcal" ? "" : unit}` : "No target"}
        </span>
      </div>
      <div className="mt-2 h-2 rounded-full bg-white/10">
        <div className="h-2 rounded-full bg-cyan-300" style={{ width: `${target ? percent : 0}%` }} />
      </div>
      <p className="mt-1 text-xs text-zinc-500">
        {!target ? "Set macro targets." : over && over > 0 ? `+${Math.round(over)}${unit === "kcal" ? " kcal" : unit} over` : `${Math.round(left ?? 0)}${unit === "kcal" ? " kcal" : unit} left`}
      </p>
    </div>
  );
}

function WearableMiniChart({
  title,
  data,
  dataKey,
  stroke,
}: Readonly<{
  title: string;
  data: Array<Record<string, string | number>>;
  dataKey: string;
  stroke: string;
}>) {
  if (!data.length) {
    return null;
  }
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.025] p-3">
      <p className="text-xs font-medium text-zinc-400">{title}</p>
      <ChartFrame className="mt-2 h-20">
        <ResponsiveContainer width="100%" height="100%">
          <RechartsLineChart data={data}>
            <Line dataKey={dataKey} stroke={stroke} strokeWidth={2} dot={false} />
          </RechartsLineChart>
        </ResponsiveContainer>
      </ChartFrame>
    </div>
  );
}

function statusBadgeClass(status: string) {
  if (status === "green") {
    return "border-emerald-300/25 bg-emerald-300/10 text-emerald-100";
  }
  if (status === "yellow") {
    return "border-amber-300/25 bg-amber-300/10 text-amber-100";
  }
  if (status === "red") {
    return "border-rose-300/25 bg-rose-300/10 text-rose-100";
  }
  return "border-zinc-300/20 bg-zinc-300/10 text-zinc-200";
}

function workoutQualityStyles(color: string) {
  if (color === "red") {
    return { ring: "border-rose-400/40 text-rose-100", bar: "bg-rose-400", badge: "border-rose-300/25 bg-rose-300/10 text-rose-100" };
  }
  if (color === "orange") {
    return { ring: "border-amber-400/40 text-amber-100", bar: "bg-amber-300", badge: "border-amber-300/25 bg-amber-300/10 text-amber-100" };
  }
  if (color === "green") {
    return { ring: "border-emerald-400/35 text-emerald-100", bar: "bg-emerald-400", badge: "border-emerald-300/25 bg-emerald-300/10 text-emerald-100" };
  }
  if (color === "bright_green") {
    return { ring: "border-lime-300/45 text-lime-100", bar: "bg-lime-300", badge: "border-lime-300/25 bg-lime-300/10 text-lime-100" };
  }
  return { ring: "border-zinc-500/30 text-zinc-100", bar: "bg-zinc-400", badge: "border-zinc-300/20 bg-zinc-300/10 text-zinc-200" };
}

function todaysActionStyles(color: string) {
  if (color === "green") {
    return {
      panel: "border-emerald-300/20 bg-emerald-300/[0.08]",
      label: "text-emerald-100",
      badge: "border-emerald-300/25 bg-emerald-300/10 text-emerald-100",
    };
  }
  if (color === "yellow") {
    return {
      panel: "border-amber-300/20 bg-amber-300/[0.08]",
      label: "text-amber-100",
      badge: "border-amber-300/25 bg-amber-300/10 text-amber-100",
    };
  }
  if (color === "red") {
    return {
      panel: "border-rose-300/20 bg-rose-300/[0.08]",
      label: "text-rose-100",
      badge: "border-rose-300/25 bg-rose-300/10 text-rose-100",
    };
  }
  return {
    panel: "border-zinc-300/15 bg-white/[0.035]",
    label: "text-zinc-100",
    badge: "border-zinc-300/20 bg-zinc-300/10 text-zinc-200",
  };
}

function relativeSyncTime(value: string) {
  if (!value) return "Never synced";
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "Sync time unknown";
  const minutes = Math.max(0, Math.round((Date.now() - timestamp) / 60000));
  if (minutes < 1) return "Last synced just now";
  if (minutes === 1) return "Last synced 1 minute ago";
  if (minutes < 60) return `Last synced ${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  return `Last synced ${hours} hour${hours === 1 ? "" : "s"} ago`;
}

function WeeklyPerformanceReportCard({ report, onViewDetails }: Readonly<{ report?: WeeklyReport; onViewDetails: () => void }>) {
  const [expanded, setExpanded] = useState(false);
  const statusClass = report?.status === "ready"
    ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-100"
    : "border-zinc-300/20 bg-zinc-300/10 text-zinc-200";
  const rows = report?.rows?.length ? report.rows : [
    { label: "Weight", value: "Need data", detail: "Daily weigh-ins unlock weekly change." },
    { label: "Nutrition", value: "Need data", detail: "Food logs unlock macro averages." },
    { label: "Training", value: "Need data", detail: "Hevy and Strava sessions unlock trends." },
  ];

  return (
    <Card className="overflow-hidden p-0 xl:col-span-5">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition hover:bg-white/[0.035]"
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300/80">Weekly</p>
            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${statusClass}`}>{report?.status ?? "learning"}</span>
          </div>
          <h2 className="mt-1 text-lg font-semibold text-white">Weekly Performance Report</h2>
          <p className="mt-1 truncate text-sm text-zinc-400">{report?.summary ?? "Weekly nutrition, training, running, weight, and recovery summary will appear here."}</p>
        </div>
        <ChevronDown className={cx("h-5 w-5 shrink-0 text-zinc-400 transition-transform duration-200", expanded && "rotate-180")} />
      </button>
      <div className={cx("grid transition-[grid-template-rows] duration-300 ease-out", expanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
        <div className="min-h-0 overflow-hidden">
          <div className="border-t border-white/10 p-5">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <p className="text-sm font-semibold text-white">{report?.period_label ?? "Last 7 days"}</p>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-400">{report?.summary ?? "Keep logging this week to make the report more specific."}</p>
              </div>
              <button onClick={onViewDetails} className="w-fit rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">
                View details
              </button>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
              {rows.map((row) => (
                <div key={`${row.label}-${row.value}`} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                  <p className="text-xs font-medium uppercase tracking-[0.12em] text-zinc-500">{row.label}</p>
                  <p className="mt-2 text-sm font-semibold text-white">{row.value}</p>
                  <p className="mt-1 text-xs leading-5 text-zinc-400">{row.detail}</p>
                </div>
              ))}
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <div className="rounded-lg border border-emerald-300/15 bg-emerald-300/[0.06] p-3">
                <p className="text-xs font-medium uppercase tracking-[0.12em] text-emerald-200/80">Best trend</p>
                <p className="mt-2 text-sm leading-6 text-emerald-50">{report?.best_trend ?? "Need more comparable lifting history."}</p>
              </div>
              <div className="rounded-lg border border-amber-300/15 bg-amber-300/[0.06] p-3">
                <p className="text-xs font-medium uppercase tracking-[0.12em] text-amber-200/80">Watch</p>
                <p className="mt-2 text-sm leading-6 text-amber-50">{report?.watch ?? "No clear weak signal yet."}</p>
              </div>
              <div className="rounded-lg border border-cyan-300/15 bg-cyan-300/[0.06] p-3">
                <p className="text-xs font-medium uppercase tracking-[0.12em] text-cyan-200/80">Next week</p>
                <p className="mt-2 text-sm leading-6 text-cyan-50">{report?.recommendation ?? "Keep targets stable and build another week of clean logs."}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}

function Dashboard({
  data,
  setActivePage,
  forms,
  setForms,
  onEditBenchPr,
  onEditMilePr,
  onSaveBenchPr,
  onSaveMilePr,
  onRecalculatePrs,
}: Readonly<{
  data: DashboardData | null;
  setActivePage: (page: PageId) => void;
  forms: FormState;
  setForms: React.Dispatch<React.SetStateAction<FormState>>;
  onEditBenchPr: () => void;
  onEditMilePr: () => void;
  onSaveBenchPr: (event: FormEvent) => void;
  onSaveMilePr: (event: FormEvent) => void;
  onRecalculatePrs: () => void;
}>) {
  const food = data?.food;
  const weight = data?.weight;
  const recovery = data?.recovery;
  const lift = data?.lift_performance;
  const workoutQuality = data?.workout_quality;
  const qualityStyles = workoutQualityStyles(workoutQuality?.color ?? "gray");
  const todaysAction = data?.todays_action;
  const actionStyles = todaysActionStyles(todaysAction?.color ?? "gray");
  const personalLearning = data?.personal_learning;
  const weeklyReport = data?.weekly_report;
  const prs = data?.prs;

  return (
    <div className="grid gap-4 xl:grid-cols-5">
      <Card className="xl:col-span-2">
        <SectionHeader eyebrow="Today" title="Food" action={<button onClick={() => setActivePage("food")} className="rounded-lg bg-cyan-300 px-3 py-2 text-sm font-semibold text-zinc-950">Log food</button>} />
        {food?.has_targets ? (
          <div className="space-y-4">
            <DashboardProgressLine label="Calories" value={food.calories.eaten} target={food.calories.target} left={food.calories.left} over={food.calories.over} percent={food.calories.percent} unit="kcal" />
            <DashboardProgressLine label="Protein" value={food.protein.eaten} target={food.protein.target} left={food.protein.left} over={food.protein.over} percent={food.protein.percent} />
            <DashboardProgressLine label="Carbs" value={food.carbs.eaten} target={food.carbs.target} left={food.carbs.left} over={food.carbs.over} percent={food.carbs.percent} />
            <DashboardProgressLine label="Fat" value={food.fat.eaten} target={food.fat.target} left={food.fat.left} over={food.fat.over} percent={food.fat.percent} />
            {!food.has_food_logged ? <p className="rounded-lg border border-white/10 bg-white/[0.035] p-3 text-sm text-zinc-400">No food logged yet. Start at 0 progress.</p> : null}
          </div>
        ) : (
          <EmptyState title="Set macro targets." description="Goals & Targets powers calorie and macro progress." action="Set targets" onAction={() => setActivePage("goals")} />
        )}
      </Card>

      <Card>
        <SectionHeader eyebrow="Today" title="Today's Action" />
        <div className={`rounded-lg border p-4 ${actionStyles.panel}`}>
          <p className={`text-xl font-semibold ${actionStyles.label}`}>{todaysAction?.headline ?? "Log today's basics"}</p>
          <p className="mt-3 text-sm leading-6 text-zinc-400">
            {todaysAction?.reason ?? "Workout, recovery, nutrition, and weight signals will shape one daily action."}
          </p>
          <span className={`mt-4 inline-flex rounded-full border px-2.5 py-1 text-xs font-medium capitalize ${actionStyles.badge}`}>
            {todaysAction?.status ?? "missing"}
          </span>
        </div>
      </Card>

      <Card>
        <SectionHeader eyebrow="Check-in" title="Weight" action={<button onClick={() => setActivePage("recovery")} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Enter weight</button>} />
        <p className="text-3xl font-semibold text-white">{weight?.today_weight ? `${weight.today_weight.toFixed(1)} lb` : "Enter today's weight"}</p>
        <p className="mt-2 text-sm text-zinc-400">7-day avg: {weight?.seven_day_average ? `${weight.seven_day_average.toFixed(1)} lb` : "Need data"}</p>
        <p className="mt-2 inline-flex rounded-full border border-blue-300/20 bg-blue-300/10 px-3 py-1 text-xs text-blue-100">{weight?.trend_label ?? "insufficient data"}</p>
        {weight?.history?.length ? (
          <ChartFrame className="mt-4 h-28">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={weight.history}>
                <Area dataKey="bodyweight" stroke="#60a5fa" fill="#60a5fa" fillOpacity={0.2} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </ChartFrame>
        ) : <p className="mt-4 text-sm text-zinc-500">{weight?.message ?? "No bodyweight data yet."}</p>}
      </Card>

      <Card>
        <SectionHeader eyebrow="Training" title="Today's Lift" action={<button onClick={() => setActivePage("training")} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Training</button>} />
        <p className="text-xl font-semibold text-white">{lift?.status ?? "No lift logged today"}</p>
        <p className="mt-3 text-sm leading-6 text-zinc-400">{lift?.summary ?? "Log a workout or import from Hevy."}</p>
        {lift?.today_volume ? <p className="mt-4 text-sm text-amber-200">Volume: {Math.round(lift.today_volume).toLocaleString()}</p> : null}
        {lift?.comparison ? <p className="mt-2 text-xs text-zinc-500">{lift.comparison}</p> : null}
      </Card>

      <Card>
        <SectionHeader eyebrow="Today" title="Workout Quality" />
        <div className="flex items-center gap-4">
          <div className={`grid h-20 w-20 shrink-0 place-items-center rounded-full border-4 bg-white/[0.035] ${qualityStyles.ring}`}>
            <span className="text-xl font-semibold">{workoutQuality?.score !== null && workoutQuality?.score !== undefined ? workoutQuality.score.toFixed(1) : "--"}</span>
          </div>
          <div className="min-w-0">
            <p className="text-xl font-semibold text-white">{workoutQuality?.score_label ?? "Missing workout"}</p>
            <p className="mt-2 text-sm leading-6 text-zinc-400">{workoutQuality?.explanation ?? "No Hevy or Strava activity logged today."}</p>
          </div>
        </div>
        <div className="mt-4 h-2 rounded-full bg-white/10">
          <div className={`h-2 rounded-full ${qualityStyles.bar}`} style={{ width: `${Math.min(100, Math.max(0, (workoutQuality?.score ?? 0) * 10))}%` }} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className={`rounded-full border px-2.5 py-1 text-xs font-medium capitalize ${qualityStyles.badge}`}>
            {workoutQuality?.confidence ?? "low"} confidence
          </span>
          {workoutQuality?.comparison ? <span className="text-xs text-zinc-500">{workoutQuality.comparison}</span> : null}
        </div>
      </Card>

      <Card>
        <SectionHeader eyebrow="Wearables" title="Recovery" action={<button onClick={() => setActivePage("settings")} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Connect wearable</button>} />
        {recovery?.connected ? (
          <div className="space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-3xl font-semibold text-white">{recovery.latest_score !== null && recovery.latest_score !== undefined ? Math.round(recovery.latest_score) : "Sync pending"}</p>
                <p className="mt-2 inline-flex rounded-full border border-emerald-300/20 bg-emerald-300/10 px-3 py-1 text-xs text-emerald-100">{recovery.classification}</p>
              </div>
              <p className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs uppercase tracking-[0.14em] text-zinc-400">{recovery.source}</p>
            </div>
            <WearableMiniChart title="Recovery trend" data={recovery.trend} dataKey="recovery_score" stroke="#34d399" />
            <WearableMiniChart title="Sleep trend" data={recovery.sleep} dataKey="sleep_hours" stroke="#60a5fa" />
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
              <WearableMiniChart title="HRV trend" data={recovery.hrv} dataKey="hrv" stroke="#a78bfa" />
              <WearableMiniChart title="Resting HR trend" data={recovery.resting_hr} dataKey="resting_hr" stroke="#fb7185" />
            </div>
            <p className="text-sm text-zinc-500">{recovery.message}</p>
          </div>
        ) : (
          <EmptyState title="Connect Fitbit/Google Health to enable recovery tracking." description="Recovery will show wearable sleep, HRV, resting HR, and readiness trends once connected." action="Connect wearable" onAction={() => setActivePage("settings")} />
        )}
        <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.035] p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-semibold text-white">Extra Run Today?</p>
            <span className={`rounded-full border px-3 py-1 text-xs font-medium capitalize ${statusBadgeClass(recovery?.extra_run_readiness?.status ?? "insufficient_data")}`}>
              {(recovery?.extra_run_readiness?.status ?? "insufficient data").replace("_", " ")}
            </span>
          </div>
          <p className="mt-3 text-sm leading-6 text-zinc-300">{recovery?.extra_run_readiness?.message ?? "Connect wearable data for run readiness."}</p>
          <p className="mt-2 text-sm font-semibold text-cyan-200">{recovery?.extra_run_readiness?.recommended_run ?? "Connect wearable data"}</p>
          {recovery?.extra_run_readiness?.reasoning?.length ? (
            <p className="mt-2 text-xs leading-5 text-zinc-500">{recovery.extra_run_readiness.reasoning[0]}</p>
          ) : null}
        </div>
      </Card>

      <Card className="xl:col-span-2">
        <SectionHeader eyebrow="Adaptive" title="Personal Learning" action={<button onClick={() => setActivePage("history")} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Data</button>} />
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <p className="text-sm leading-6 text-zinc-400">{personalLearning?.summary ?? "Learning from your history. More weekly data is needed before pattern detection is useful."}</p>
          <span className="inline-flex w-fit shrink-0 rounded-full border border-cyan-300/20 bg-cyan-300/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-100">
            {personalLearning?.confidence ?? "low"} confidence
          </span>
        </div>
        {personalLearning?.insights?.length ? (
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {personalLearning.insights.slice(0, 3).map((insight) => (
              <div key={insight.title} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                <p className="text-sm font-semibold text-white">{insight.title}</p>
                <p className="mt-2 text-xs leading-5 text-zinc-400">{insight.explanation}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <span className="rounded-full border border-white/10 px-2 py-1 text-[11px] capitalize text-zinc-300">{insight.confidence}</span>
                  <span className="rounded-full border border-white/10 px-2 py-1 text-[11px] text-zinc-300">{insight.window}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-4 rounded-lg border border-dashed border-white/10 bg-black/10 p-4 text-sm text-zinc-400">
            Personal patterns will appear after enough overlapping nutrition, training, bodyweight, sleep, and recovery history is logged.
          </div>
        )}
      </Card>

      <WeeklyPerformanceReportCard report={weeklyReport} onViewDetails={() => setActivePage("history")} />

      <Card className="xl:col-span-5">
        <SectionHeader
          eyebrow="Records"
          title="PRs"
          action={<button onClick={onRecalculatePrs} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Recalculate from Logs</button>}
        />
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
            <p className="text-sm text-zinc-400">Bench Press PR</p>
            {prs?.bench_press ? (
              <>
                <p className="mt-2 text-2xl font-semibold text-white">{prs.bench_press.value} {prs.bench_press.unit}</p>
                <p className="mt-1 text-sm text-zinc-400">{prs.bench_press.reps} rep{prs.bench_press.reps === 1 ? "" : "s"} · {prs.bench_press.date} · {prs.bench_press.source}</p>
                {prs.bench_press.reps > 1 ? <p className="mt-2 text-sm text-emerald-200">Est. 1RM {prs.bench_press.estimated_1rm} lb</p> : null}
                {prs.bench_press.notes ? <p className="mt-2 text-sm text-zinc-500">{prs.bench_press.notes}</p> : null}
                {prs.bench_press.manual_override ? <p className="mt-2 inline-flex rounded-full border border-cyan-300/20 bg-cyan-300/10 px-2.5 py-1 text-xs text-cyan-100">Manual override</p> : null}
              </>
            ) : (
              <p className="mt-3 text-sm text-zinc-500">Add bench PR</p>
            )}
            <button onClick={onEditBenchPr} className="mt-4 rounded-lg bg-cyan-300 px-3 py-2 text-sm font-semibold text-zinc-950">
              {prs?.bench_press ? "Edit Bench PR" : "Add Bench PR"}
            </button>
            {forms.benchPr.editing ? (
              <form onSubmit={onSaveBenchPr} className="mt-4 grid gap-3 sm:grid-cols-2">
                <TextInput label="Weight" type="number" min={0} step="any" value={forms.benchPr.weight} onChange={(value) => setForms((state) => ({ ...state, benchPr: { ...state.benchPr, weight: Number(value) } }))} />
                <TextInput label="Reps" type="number" min={1} value={forms.benchPr.reps} onChange={(value) => setForms((state) => ({ ...state, benchPr: { ...state.benchPr, reps: Number(value) } }))} />
                <TextInput label="Date" type="date" value={forms.benchPr.date} onChange={(value) => setForms((state) => ({ ...state, benchPr: { ...state.benchPr, date: value } }))} />
                <TextInput label="Notes" value={forms.benchPr.notes} onChange={(value) => setForms((state) => ({ ...state, benchPr: { ...state.benchPr, notes: value } }))} />
                <button className="h-11 rounded-lg bg-emerald-300 text-sm font-semibold text-zinc-950 sm:col-span-2">Save Bench PR</button>
              </form>
            ) : null}
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
            <p className="text-sm text-zinc-400">Mile Time PR</p>
            {prs?.mile_time ? (
              <>
                <p className="mt-2 text-2xl font-semibold text-white">{prs.mile_time.display}</p>
                <p className="mt-1 text-sm text-zinc-400">{prs.mile_time.date} · {prs.mile_time.source}{prs.mile_time.estimated ? " · estimated" : ""}</p>
                {prs.mile_time.notes ? <p className="mt-2 text-sm text-zinc-500">{prs.mile_time.notes}</p> : null}
                {prs.mile_time.manual_override ? <p className="mt-2 inline-flex rounded-full border border-cyan-300/20 bg-cyan-300/10 px-2.5 py-1 text-xs text-cyan-100">Manual override</p> : null}
              </>
            ) : (
              <p className="mt-3 text-sm text-zinc-500">Add mile PR</p>
            )}
            <button onClick={onEditMilePr} className="mt-4 rounded-lg bg-cyan-300 px-3 py-2 text-sm font-semibold text-zinc-950">
              {prs?.mile_time ? "Edit Mile PR" : "Add Mile PR"}
            </button>
            {forms.milePr.editing ? (
              <form onSubmit={onSaveMilePr} className="mt-4 grid gap-3 sm:grid-cols-2">
                <TextInput label="Minutes" type="number" min={0} value={forms.milePr.minutes} onChange={(value) => setForms((state) => ({ ...state, milePr: { ...state.milePr, minutes: Number(value) } }))} />
                <TextInput label="Seconds" type="number" min={0} value={forms.milePr.seconds} onChange={(value) => setForms((state) => ({ ...state, milePr: { ...state.milePr, seconds: Number(value) } }))} />
                <TextInput label="Date" type="date" value={forms.milePr.date} onChange={(value) => setForms((state) => ({ ...state, milePr: { ...state.milePr, date: value } }))} />
                <TextInput label="Notes" value={forms.milePr.notes} onChange={(value) => setForms((state) => ({ ...state, milePr: { ...state.milePr, notes: value } }))} />
                <button className="h-11 rounded-lg bg-emerald-300 text-sm font-semibold text-zinc-950 sm:col-span-2">Save Mile PR</button>
              </form>
            ) : null}
          </div>
        </div>
      </Card>
    </div>
  );
}

function GoalsPage({
  goals,
  targets,
  weightFeedback,
  leanBulkDecision,
  adaptiveRecommendation,
  onApplySuggestedMacros,
}: Readonly<{
  goals: Goals | null;
  targets: Targets | null;
  weightFeedback: WeightFeedback | null;
  leanBulkDecision: LeanBulkDecision | null;
  adaptiveRecommendation: AdaptiveNutritionRecommendation | null;
  onApplySuggestedMacros: () => void;
}>) {
  const calorieDelta = targets ? targets.target_calories - targets.maintenance_calories : 0;
  const calorieDeltaLabel = calorieDelta === 0 ? "at maintenance" : `${calorieDelta > 0 ? "+" : ""}${calorieDelta} kcal ${calorieDelta > 0 ? "surplus" : "deficit"}`;
  const leanBulkRange = weightFeedback?.target_weekly_change_low != null && weightFeedback?.target_weekly_change_high != null
    ? `${weightFeedback.target_weekly_change_low.toFixed(2)}% to ${weightFeedback.target_weekly_change_high.toFixed(2)}%/week target`
    : "Trend target unlocks with goals";
  const weeklyTrend = weightFeedback?.weekly_change_lb != null && weightFeedback?.weekly_change_pct != null
    ? `${weightFeedback.weekly_change_lb > 0 ? "+" : ""}${weightFeedback.weekly_change_lb} lb/week (${weightFeedback.weekly_change_pct > 0 ? "+" : ""}${weightFeedback.weekly_change_pct}%)`
    : "Need bodyweight trend";
  const lastUpdated = targets?.updated_at ? new Date(targets.updated_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "Not applied yet";
  const performanceSignal = leanBulkDecision?.details.performance_signal;
  const performanceDrivers = performanceSignal?.drivers?.slice(0, 3) ?? [];
  const recoverySignal = leanBulkDecision?.details.recovery_signal ?? targets?.recovery_signal;
  const recoveryDrivers = recoverySignal?.drivers?.slice(0, 3) ?? [];
  const adaptiveReasons = adaptiveRecommendation?.reasoning?.slice(0, 4) ?? [];
  return (
    <div className="space-y-6">
      <Card>
        <SectionHeader
          eyebrow="Strategy"
          title="Nutrition Strategy"
          action={
            <button type="button" onClick={onApplySuggestedMacros} className="rounded-lg bg-emerald-300 px-3 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-200">
              Apply latest recommendation
            </button>
          }
        />
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
          <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-300/80">Strategy</p>
            <h3 className="mt-2 text-2xl font-semibold text-white">Conservative Lean Bulk</h3>
            <div className="mt-4 grid gap-3 text-sm leading-6 text-zinc-300">
              <p><span className="text-zinc-500">Goal:</span> Slow muscle gain while minimizing fat gain.</p>
              <p><span className="text-zinc-500">Method:</span> Dynamic calorie and macro adjustment based on bodyweight, training, running, food logs, and recovery.</p>
              <p><span className="text-zinc-500">Mode:</span> Performance-focused, high-carb support for strength progression and recovery.</p>
            </div>
          </div>
          <div className="rounded-lg border border-cyan-300/15 bg-cyan-300/[0.045] p-4">
            <p className="text-sm text-zinc-400">Current active targets</p>
            <p className="mt-2 text-3xl font-semibold text-white">{targets ? `${targets.target_calories} kcal` : "No target"}</p>
            <p className="mt-3 text-sm text-zinc-300">
              {targets ? `${targets.protein_grams}g protein · ${targets.carb_grams}g carbs · ${targets.fat_grams}g fat` : "Apply the latest recommendation to set targets."}
            </p>
            <p className="mt-4 text-xs text-zinc-500">Last updated: {lastUpdated}</p>
          </div>
        </div>
      </Card>

      <Card>
        <SectionHeader
          eyebrow="Adaptive Engine"
          title="Unified Nutrition Recommendation"
          action={
            <button type="button" onClick={onApplySuggestedMacros} className="rounded-lg bg-emerald-300 px-3 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-200">
              Apply recommendation
            </button>
          }
        />
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.55fr)]">
          <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <p className="text-sm text-zinc-400">Recommended target</p>
                <p className="mt-2 text-3xl font-semibold text-white">
                  {adaptiveRecommendation ? `${adaptiveRecommendation.caloriesTarget} kcal` : "Need data"}
                </p>
                <p className="mt-2 text-sm text-zinc-300">
                  {adaptiveRecommendation
                    ? `${adaptiveRecommendation.proteinTarget}g protein · ${adaptiveRecommendation.carbsTarget}g carbs · ${adaptiveRecommendation.fatTarget}g fat`
                    : "The engine will combine weight, food, Hevy, Strava, performance, and recovery signals."}
                </p>
              </div>
              <span className="inline-flex w-fit rounded-full border border-cyan-300/20 bg-cyan-300/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-100">
                {adaptiveRecommendation?.confidence ?? "low"} confidence
              </span>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-white/10 bg-black/15 p-3">
                <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Current</p>
                <p className="mt-2 text-sm font-semibold text-white">
                  {adaptiveRecommendation ? `${adaptiveRecommendation.currentTarget.calories} kcal · P ${adaptiveRecommendation.currentTarget.protein} C ${adaptiveRecommendation.currentTarget.carbs} F ${adaptiveRecommendation.currentTarget.fat}` : "No active target"}
                </p>
              </div>
              <div className="rounded-lg border border-white/10 bg-black/15 p-3">
                <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Change</p>
                <p className="mt-2 text-sm font-semibold text-white">
                  {adaptiveRecommendation
                    ? `${adaptiveRecommendation.macroChanges.calories > 0 ? "+" : ""}${adaptiveRecommendation.macroChanges.calories} kcal · P ${adaptiveRecommendation.macroChanges.protein > 0 ? "+" : ""}${adaptiveRecommendation.macroChanges.protein}g · C ${adaptiveRecommendation.macroChanges.carbs > 0 ? "+" : ""}${adaptiveRecommendation.macroChanges.carbs}g · F ${adaptiveRecommendation.macroChanges.fat > 0 ? "+" : ""}${adaptiveRecommendation.macroChanges.fat}g`
                    : "No change yet"}
                </p>
              </div>
            </div>
            <ul className="mt-4 space-y-2 text-sm text-zinc-300">
              {(adaptiveReasons.length ? adaptiveReasons : ["Need more data before making adaptive macro changes."]).map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
            {adaptiveRecommendation?.warnings?.length ? (
              <p className="mt-3 text-xs leading-5 text-amber-200">{adaptiveRecommendation.warnings[0]}</p>
            ) : null}
          </div>
          <div className="grid gap-2">
            {[
              ["Weight", adaptiveRecommendation?.signals.weight.status ?? "insufficient data"],
              ["Performance", adaptiveRecommendation?.signals.performance.label ?? "insufficient data"],
              ["Recovery", adaptiveRecommendation?.signals.recovery.status ?? "insufficient data"],
              ["Training Load", adaptiveRecommendation?.signals.trainingLoad.status ?? "low"],
              ["Running Load", adaptiveRecommendation?.signals.runningLoad.status ?? "low"],
            ].map(([label, value]) => (
              <div key={label} className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.035] px-3 py-2">
                <span className="text-sm text-zinc-400">{label}</span>
                <span className="text-sm font-semibold capitalize text-white">{value}</span>
              </div>
            ))}
          </div>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <TargetDetailCard
          title="Calories"
          value={targets ? `${targets.target_calories} kcal` : "No target"}
          subvalue={targets ? `Maintenance ${targets.maintenance_calories} - ${calorieDeltaLabel}` : "Save goals to calculate"}
          note={targets ? `Dynamic adjustment: ${targets.calorie_adjustment > 0 ? "+" : ""}${targets.calorie_adjustment} kcal/day. Macro math: ${targets.macro_calories ?? targets.target_calories} kcal (${targets.calorie_macro_delta ?? 0} delta).` : "Calories update from weight trend, training load, cardio, and recovery."}
          icon={Apple}
          accent="border-cyan-400/20 bg-cyan-400/10 text-cyan-300"
        />
        <TargetDetailCard
          title="Protein"
          value={targets ? `${targets.protein_grams}g` : "No target"}
          subvalue={targets?.protein_per_lb ? `${targets.protein_per_lb}g/lb bodyweight` : "Protein-first allocation"}
          note="Lean bulk targets a higher protein floor for muscle retention, growth, and consistency."
          icon={ProteinMoleculeIcon}
          accent="border-teal-400/20 bg-teal-400/10 text-teal-300"
        />
        <TargetDetailCard
          title="Carbs"
          value={targets ? `${targets.carb_grams}g` : "No target"}
          subvalue="Remaining calories after protein and fats"
          note={targets?.carb_emphasis ?? "Carbs scale with lifting frequency, cardio, surplus size, and recovery demand."}
          icon={CarbsMoleculeIcon}
          accent="border-blue-400/20 bg-blue-400/10 text-blue-300"
        />
        <TargetDetailCard
          title="Fat"
          value={targets ? `${targets.fat_grams}g` : "No target"}
          subvalue={targets?.fat_per_lb ? `${targets.fat_per_lb}g/lb - floor ${targets.fat_floor_grams ?? 0}g` : "Minimum recovery threshold"}
          note="Moderate fats are protected before carbs get the remaining calories."
          icon={FatMoleculeIcon}
          accent="border-amber-400/20 bg-amber-400/10 text-amber-300"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionHeader eyebrow="Timeline" title="Feasibility" />
          <p className="text-lg font-semibold text-white">{targets?.timeline_status ?? "No target yet"}</p>
          <p className="mt-3 text-sm leading-6 text-zinc-400">{targets?.timeline_warning ?? "Save goals to calculate timeline feedback."}</p>
          <p className="mt-4 text-sm text-zinc-300">{targets?.target_description ?? goals?.goal_type ?? "Conservative Lean Bulk"}</p>
          <p className="mt-4 rounded-lg border border-emerald-300/15 bg-emerald-300/10 p-3 text-sm text-emerald-100">
            Lean bulk mode targets slow muscle gain while minimizing unnecessary fat gain.
          </p>
        </Card>
        <Card>
          <SectionHeader
            eyebrow="Trend"
            title="Suggested calorie adjustment"
            action={<button type="button" onClick={onApplySuggestedMacros} className="rounded-lg border border-emerald-300/30 bg-emerald-300/10 px-3 py-2 text-sm font-semibold text-emerald-100 transition hover:bg-emerald-300/15">Apply suggested macros</button>}
          />
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
              <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Weekly change</p>
              <p className="mt-2 text-sm font-semibold text-white">{weeklyTrend}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
              <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">7-day averages</p>
              <p className="mt-2 text-sm font-semibold text-white">
                {weightFeedback?.current_7_day_avg ? `${weightFeedback.current_7_day_avg} now` : "Need data"}
                {weightFeedback?.previous_7_day_avg ? ` / ${weightFeedback.previous_7_day_avg} prev` : ""}
              </p>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
              <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Action</p>
              <p className="mt-2 text-sm font-semibold text-cyan-100">{weightFeedback?.suggested_adjustment ?? "No bodyweight trend yet"}</p>
            </div>
          </div>
          <p className="mt-4 text-sm leading-6 text-zinc-400">{weightFeedback?.reason ?? "Enter at least two bodyweight entries to unlock trend feedback."}</p>
          <p className="mt-3 text-xs text-zinc-500">
            Target: {leanBulkRange} · Window: {weightFeedback?.window_used ?? "none"} · Confidence: {weightFeedback?.confidence ?? "low"}
            {weightFeedback?.fourteen_day_avg ? ` · 14-day avg ${weightFeedback.fourteen_day_avg}` : ""} · {targets?.historical_note ?? "Historical nutrition bias appears after enough logs."}
          </p>
        </Card>
      </div>

      <Card>
        <SectionHeader eyebrow="Lean Bulk" title="Calorie optimization details" />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard title="7-Day Avg Weight" value={leanBulkDecision?.details.seven_day_avg_weight ? `${leanBulkDecision.details.seven_day_avg_weight}` : "Need data"} detail="Smooths water spikes" icon={Weight} accent="border-blue-400/20 bg-blue-400/10 text-blue-300" />
          <MetricCard title="14-Day Avg Weight" value={leanBulkDecision?.details.fourteen_day_avg_weight ? `${leanBulkDecision.details.fourteen_day_avg_weight}` : "Need data"} detail="Primary trend context" icon={Weight} accent="border-cyan-400/20 bg-cyan-400/10 text-cyan-300" />
          <MetricCard title="Calorie Avg" value={leanBulkDecision?.details.calorie_average ? `${leanBulkDecision.details.calorie_average}` : "Need logs"} detail="Recent daily average" icon={Apple} accent="border-emerald-400/20 bg-emerald-400/10 text-emerald-300" />
          <MetricCard title="Protein Avg" value={leanBulkDecision?.details.protein_average ? `${leanBulkDecision.details.protein_average}g` : "Need logs"} detail={leanBulkDecision?.details.protein_target ? `Target ~${leanBulkDecision.details.protein_target}g` : "0.8-1.0g/lb guardrail"} icon={ProteinMoleculeIcon} accent="border-teal-400/20 bg-teal-400/10 text-teal-300" />
          <MetricCard title="Training Trend" value={leanBulkDecision?.details.training_trend ?? "Need data"} detail="Key lift direction" icon={Dumbbell} accent="border-violet-400/20 bg-violet-400/10 text-violet-300" />
          <MetricCard title="Recovery Trend" value={leanBulkDecision?.details.recovery_trend ?? "Need data"} detail={leanBulkDecision?.details.recovery_average ? `${leanBulkDecision.details.recovery_average}/100 avg` : "Recent readiness"} icon={HeartPulse} accent="border-rose-400/20 bg-rose-400/10 text-rose-300" />
          <MetricCard title="Decision" value={leanBulkDecision?.recommendation ?? "maintain"} detail={leanBulkDecision ? `${leanBulkDecision.calorie_change > 0 ? "+" : ""}${leanBulkDecision.calorie_change} kcal/day` : "Need data"} icon={Sparkles} accent="border-amber-400/20 bg-amber-400/10 text-amber-300" />
          <MetricCard title="Risk Score" value={`${leanBulkDecision?.fat_gain_risk_score ?? 0}/100`} detail="Fat-gain risk estimate" icon={Gauge} accent="border-orange-400/20 bg-orange-400/10 text-orange-300" />
        </div>
        <div className="mt-4 rounded-xl border border-white/10 bg-white/[0.035] p-4">
          <div className="mb-4 rounded-lg border border-violet-300/15 bg-violet-300/[0.045] p-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <p className="text-sm font-semibold text-white">Hevy performance signal</p>
                <p className="mt-1 text-sm leading-6 text-zinc-300">
                  {performanceSignal?.summary ?? "Need more comparable Hevy lifting history."}
                </p>
              </div>
              <span className="inline-flex w-fit rounded-full border border-white/10 bg-black/20 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-violet-100">
                {performanceSignal?.label ?? "insufficient data"} · {performanceSignal?.confidence ?? "low"}
              </span>
            </div>
            <p className="mt-3 text-sm text-violet-100">
              {performanceSignal?.recommendation ?? "Keep macros stable until the app has enough matching Hevy sessions."}
            </p>
            {performanceDrivers.length ? (
              <div className="mt-3 grid gap-2 md:grid-cols-3">
                {performanceDrivers.map((driver) => (
                  <div key={`${driver.name}-${driver.signal}`} className="rounded-lg border border-white/10 bg-black/15 p-3">
                    <p className="truncate text-sm font-semibold text-white">{driver.name}</p>
                    <p className="mt-1 text-xs text-zinc-500">{driver.muscle_group ?? "Training"} · {driver.signal}</p>
                    <p className="mt-2 text-xs text-zinc-300">
                      1RM {driver.estimated_1rm_change_pct != null ? `${driver.estimated_1rm_change_pct > 0 ? "+" : ""}${driver.estimated_1rm_change_pct}%` : "n/a"}
                      {driver.volume_change_pct != null ? ` · Vol ${driver.volume_change_pct > 0 ? "+" : ""}${driver.volume_change_pct}%` : ""}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
          <div className="mb-4 rounded-lg border border-rose-300/15 bg-rose-300/[0.045] p-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <p className="text-sm font-semibold text-white">Recovery nutrition signal</p>
                <p className="mt-1 text-sm leading-6 text-zinc-300">
                  {recoverySignal?.summary ?? "Log recovery or connect wearable data to personalize nutrition recovery adjustments."}
                </p>
              </div>
              <span className="inline-flex w-fit rounded-full border border-white/10 bg-black/20 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-rose-100">
                {recoverySignal?.status ?? "insufficient data"} · {recoverySignal?.confidence ?? "low"}
                {recoverySignal?.score != null ? ` · ${Math.round(recoverySignal.score)}/100` : ""}
              </span>
            </div>
            <p className="mt-3 text-sm text-rose-100">{recoverySignal?.nutrition_implication ?? "Keep targets stable until recovery data is available."}</p>
            <p className="mt-1 text-xs leading-5 text-zinc-500">{recoverySignal?.suggested_action ?? "Log sleep, fatigue, soreness, HRV, or resting heart rate."}</p>
            {recoveryDrivers.length ? (
              <div className="mt-3 grid gap-2 md:grid-cols-3">
                {recoveryDrivers.map((driver) => (
                  <div key={`${driver.name}-${driver.detail}`} className="rounded-lg border border-white/10 bg-black/15 p-3">
                    <p className="text-sm font-semibold text-white">{driver.name}</p>
                    <p className="mt-1 text-xs capitalize text-zinc-500">{driver.severity}</p>
                    <p className="mt-2 text-xs leading-5 text-zinc-300">{driver.detail}</p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm font-semibold text-white">Calorie recommendation</p>
            <button type="button" onClick={onApplySuggestedMacros} className="rounded-lg bg-emerald-300 px-3 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-200">
              Apply suggested macros
            </button>
          </div>
          <p className="mt-2 text-lg font-semibold text-cyan-100">
            {leanBulkDecision ? `${leanBulkDecision.recommendation} calories (${leanBulkDecision.calorie_change > 0 ? "+" : ""}${leanBulkDecision.calorie_change}/day) -> ${leanBulkDecision.new_target_calories} kcal` : "Need more data before adjusting calories."}
          </p>
          <ul className="mt-3 space-y-2 text-sm text-zinc-300">
            {(leanBulkDecision?.reasoning ?? ["Need more data before adjusting calories."]).map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </div>
      </Card>
    </div>
  );
}

function FoodPage({
  logs,
  targets,
  nutritionHistory,
  nutritionAdherence,
  shortcuts,
  mealTemplates,
  forms,
  setForms,
  manualFoodMode,
  setManualFoodMode,
  servingForm,
  setServingForm,
  servingPreview,
  labelUploadResult,
  onLabelUpload,
  onSaveServingShortcut,
  onSubmit,
  aiText,
  setAiText,
  parsedFoods,
  setParsedFoods,
  onParseFood,
  onSaveParsedFoods,
  onSaveShortcut,
  onSaveMealTemplate,
  onSaveAndLogToday,
  onLogShortcut,
  onUpdateShortcut,
  onDeleteShortcut,
  onLogMealTemplate,
  onRenameMealTemplate,
  shortcutSuggestion,
  onUseSuggestion,
  onParseAnyway,
  parseLoading,
  parseResult,
  manualSaving,
  manualError,
}: Readonly<{
  logs: NutritionEntry[];
  targets: Targets | null;
  nutritionHistory: DailyNutritionSummary[];
  nutritionAdherence: NutritionAdherence | null;
  shortcuts: FoodShortcut[];
  mealTemplates: MealTemplate[];
  forms: FormState;
  setForms: React.Dispatch<React.SetStateAction<FormState>>;
  manualFoodMode: "direct" | "serving";
  setManualFoodMode: (mode: "direct" | "serving") => void;
  servingForm: ServingScaleForm;
  setServingForm: React.Dispatch<React.SetStateAction<ServingScaleForm>>;
  servingPreview: ReturnType<typeof calculateServingPreview>;
  labelUploadResult: LabelUploadResult | null;
  onLabelUpload: (file: File) => void;
  onSaveServingShortcut: () => void;
  onSubmit: (event: FormEvent) => void;
  aiText: string;
  setAiText: (value: string) => void;
  parsedFoods: ParsedFood[];
  setParsedFoods: React.Dispatch<React.SetStateAction<ParsedFood[]>>;
  onParseFood: (event: FormEvent) => void;
  onSaveParsedFoods: (event: FormEvent) => void;
  onSaveShortcut: (event: FormEvent) => void;
  onSaveMealTemplate: (event: FormEvent) => void;
  onSaveAndLogToday: (event: FormEvent) => void;
  onLogShortcut: (shortcutId: string) => void;
  onUpdateShortcut: (shortcut: FoodShortcut) => void;
  onDeleteShortcut: (shortcutId: string) => void;
  onLogMealTemplate: (templateName: string) => Promise<void>;
  onRenameMealTemplate: (templateName: string, nextName: string) => Promise<void>;
  shortcutSuggestion: { type: "shortcut" | "template" | "frequent"; label: string; id: string } | null;
  onUseSuggestion: () => void;
  onParseAnyway: () => void;
  parseLoading: boolean;
  parseResult: FoodParseResponse | null;
  manualSaving: boolean;
  manualError: string | null;
}>) {
  const [showFoodHistory, setShowFoodHistory] = useState(false);
  const [shortcutQuery, setShortcutQuery] = useState("");
  const [editingShortcut, setEditingShortcut] = useState<FoodShortcut | null>(null);
  const [editingTemplateName, setEditingTemplateName] = useState<string | null>(null);
  const [templateRenameValue, setTemplateRenameValue] = useState("");
  const [pendingTemplateAction, setPendingTemplateAction] = useState<string | null>(null);
  const selectedDateEntries = logs.filter((entry) => entry.date === forms.nutrition.date);
  const selectedDateTotals = selectedDateEntries.reduce(
    (totals, entry) => ({
      calories: totals.calories + (Number(entry.calories) || 0),
      protein: totals.protein + (Number(entry.protein) || 0),
      carbs: totals.carbs + (Number(entry.carbs) || 0),
      fat: totals.fat + (Number(entry.fat) || 0),
    }),
    { calories: 0, protein: 0, carbs: 0, fat: 0 },
  );
  const hasMacroTargets = Boolean(targets && targets.target_calories > 0 && targets.protein_grams > 0 && targets.carb_grams > 0 && targets.fat_grams > 0);
  const calorieProgress = buildMacroProgress("Calories", " kcal", selectedDateTotals.calories, targets?.target_calories ?? 0, "bg-cyan-300");
  const macroProgress = [
    buildMacroProgress("Protein", "g", selectedDateTotals.protein, targets?.protein_grams ?? 0, "bg-teal-300"),
    buildMacroProgress("Carbs", "g", selectedDateTotals.carbs, targets?.carb_grams ?? 0, "bg-blue-300"),
    buildMacroProgress("Fat", "g", selectedDateTotals.fat, targets?.fat_grams ?? 0, "bg-amber-300"),
  ];
  const recentHistory = nutritionHistory.slice(-30);
  const filteredShortcuts = shortcuts.filter((shortcut) => normalizeSearchText(shortcut.shortcut_name).includes(normalizeSearchText(shortcutQuery)));
  const templateSummaries = Array.from(
    mealTemplates.reduce((templates, item) => {
      const name = item.template_name;
      const current = templates.get(name) ?? { template_name: name, calories: 0, protein: 0, carbs: 0, fat: 0, foods: 0 };
      current.calories += Number(item.calories) || 0;
      current.protein += Number(item.protein) || 0;
      current.carbs += Number(item.carbs) || 0;
      current.fat += Number(item.fat) || 0;
      current.foods += 1;
      templates.set(name, current);
      return templates;
    }, new Map<string, { template_name: string; calories: number; protein: number; carbs: number; fat: number; foods: number }>())
      .values(),
  ).sort((a, b) => a.template_name.localeCompare(b.template_name));
  const beginTemplateRename = (templateName: string) => {
    setEditingTemplateName(templateName);
    setTemplateRenameValue(templateName);
  };
  const cancelTemplateRename = () => {
    setEditingTemplateName(null);
    setTemplateRenameValue("");
  };
  const saveTemplateRename = async (templateName: string) => {
    const nextName = templateRenameValue.trim();
    if (!nextName) return;
    setPendingTemplateAction(`rename:${templateName}`);
    try {
      await onRenameMealTemplate(templateName, nextName);
      cancelTemplateRename();
    } finally {
      setPendingTemplateAction(null);
    }
  };
  const logTemplate = async (templateName: string) => {
    setPendingTemplateAction(`log:${templateName}`);
    try {
      await onLogMealTemplate(templateName);
    } finally {
      setPendingTemplateAction(null);
    }
  };

  return (
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(300px,340px)_minmax(0,1fr)]">
      <Card className="min-w-0 xl:self-start">
        <SectionHeader eyebrow="Food" title="Manual food entry" />
        <div className="mb-4 grid grid-cols-2 rounded-lg border border-white/10 bg-white/[0.035] p-1 text-sm">
          {(["direct", "serving"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setManualFoodMode(mode)}
              className={cx("rounded-md px-3 py-2 font-semibold transition", manualFoodMode === mode ? "bg-cyan-300 text-zinc-950" : "text-zinc-300 hover:bg-white/[0.04]")}
            >
              {mode === "direct" ? "Direct macros" : "Serving-size scaling"}
            </button>
          ))}
        </div>
        <form onSubmit={onSubmit} className="grid min-w-0 gap-4">
          <TextInput label="Date" type="date" value={forms.nutrition.date} onChange={(value) => setForms((state) => ({ ...state, nutrition: { ...state.nutrition, date: value } }))} />
          {manualFoodMode === "direct" ? (
            <>
              <TextInput label="Food name" required value={forms.nutrition.food_name} onChange={(value) => setForms((state) => ({ ...state, nutrition: { ...state.nutrition, food_name: value } }))} />
              <TextInput label="Calories" type="number" min={0} step="any" value={forms.nutrition.calories} onChange={(value) => setForms((state) => ({ ...state, nutrition: { ...state.nutrition, calories: Number(value) } }))} />
              <TextInput label="Protein" type="number" min={0} step="any" value={forms.nutrition.protein} onChange={(value) => setForms((state) => ({ ...state, nutrition: { ...state.nutrition, protein: Number(value) } }))} />
              <TextInput label="Carbs" type="number" min={0} step="any" value={forms.nutrition.carbs} onChange={(value) => setForms((state) => ({ ...state, nutrition: { ...state.nutrition, carbs: Number(value) } }))} />
              <TextInput label="Fat" type="number" min={0} step="any" value={forms.nutrition.fat} onChange={(value) => setForms((state) => ({ ...state, nutrition: { ...state.nutrition, fat: Number(value) } }))} />
            </>
          ) : (
            <>
              <TextInput label="Food name" required value={servingForm.food_name} onChange={(value) => setServingForm((state) => ({ ...state, food_name: value }))} />
              <TextInput label="Serving size in grams" type="number" min={0} step="any" value={servingForm.serving_size_grams} onChange={(value) => setServingForm((state) => ({ ...state, serving_size_grams: Number(value) }))} />
              <TextInput label="Calories per serving" type="number" min={0} step="any" value={servingForm.calories_per_serving} onChange={(value) => setServingForm((state) => ({ ...state, calories_per_serving: Number(value) }))} />
              <TextInput label="Protein per serving" type="number" min={0} step="any" value={servingForm.protein_per_serving} onChange={(value) => setServingForm((state) => ({ ...state, protein_per_serving: Number(value) }))} />
              <TextInput label="Carbs per serving" type="number" min={0} step="any" value={servingForm.carbs_per_serving} onChange={(value) => setServingForm((state) => ({ ...state, carbs_per_serving: Number(value) }))} />
              <TextInput label="Fat per serving" type="number" min={0} step="any" value={servingForm.fat_per_serving} onChange={(value) => setServingForm((state) => ({ ...state, fat_per_serving: Number(value) }))} />
              <TextInput label="Fiber per serving optional" type="number" min={0} step="any" value={servingForm.fiber_per_serving} onChange={(value) => setServingForm((state) => ({ ...state, fiber_per_serving: value === "" ? "" : Number(value) }))} />
              <TextInput label="Sodium per serving optional" type="number" min={0} step="any" value={servingForm.sodium_per_serving} onChange={(value) => setServingForm((state) => ({ ...state, sodium_per_serving: value === "" ? "" : Number(value) }))} />
              <TextInput label="Potassium per serving optional" type="number" min={0} step="any" value={servingForm.potassium_per_serving} onChange={(value) => setServingForm((state) => ({ ...state, potassium_per_serving: value === "" ? "" : Number(value) }))} />
              <TextInput label="Grams consumed" type="number" min={0} step="any" value={servingForm.grams_consumed} onChange={(value) => setServingForm((state) => ({ ...state, grams_consumed: Number(value) }))} />
              <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
                <p className="text-sm font-semibold text-white">Live preview</p>
                <p className="mt-2 text-sm text-zinc-400">Multiplier: {servingPreview.multiplier.toFixed(2)}x</p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {[
                    ["Calories", `${Math.round(servingPreview.calories)}`],
                    ["Protein", `${Number(servingPreview.protein.toFixed(1))}g`],
                    ["Carbs", `${Number(servingPreview.carbs.toFixed(1))}g`],
                    ["Fat", `${Number(servingPreview.fat.toFixed(1))}g`],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-lg border border-white/10 bg-zinc-950/50 p-3">
                      <p className="text-xs text-zinc-500">{label}</p>
                      <p className="mt-1 text-lg font-semibold text-white">{value}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-lg border border-dashed border-white/15 bg-white/[0.03] p-4">
                <p className="text-sm font-semibold text-white">Upload nutrition label</p>
                <p className="mt-1 text-sm text-zinc-400">PDF, PNG, JPG, or JPEG. Extraction is a placeholder for now; manual fields stay editable.</p>
                <input
                  className="mt-3 block w-full text-sm text-zinc-300 file:mr-3 file:rounded-lg file:border-0 file:bg-cyan-300 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-zinc-950"
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) onLabelUpload(file);
                  }}
                />
                <button type="button" className="mt-3 rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-300">Extract with AI/OCR (placeholder)</button>
                {labelUploadResult ? (
                  <p className="mt-3 rounded-lg border border-emerald-300/20 bg-emerald-300/10 p-3 text-sm text-emerald-100">
                    {labelUploadResult.message} Saved as {labelUploadResult.path}.
                  </p>
                ) : null}
              </div>
            </>
          )}
          {manualError ? <p className="rounded-lg border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-100">{manualError}</p> : null}
          <button disabled={manualSaving} className="h-11 rounded-lg bg-cyan-300 text-sm font-semibold text-zinc-950 disabled:cursor-not-allowed disabled:opacity-60">
            {manualSaving ? "Saving food..." : manualFoodMode === "serving" ? "Save scaled food entry" : "Save food entry"}
          </button>
          {manualFoodMode === "serving" ? (
            <button type="button" onClick={onSaveServingShortcut} className="h-11 rounded-lg border border-emerald-300/30 bg-emerald-300/10 text-sm font-semibold text-emerald-100">
              Save scaled food as shortcut
            </button>
          ) : null}
        </form>
      </Card>
      <div className="min-w-0 space-y-4">
        <Card>
          <SectionHeader eyebrow="Targets" title="Macro progress" />
          {hasMacroTargets ? (
            <div className="space-y-4">
              <MacroProgressCard macro={calorieProgress} />
              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
                {macroProgress.map((macro) => (
                  <MacroProgressCard key={macro.label} macro={macro} />
                ))}
              </div>
              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
                {macroProgress.map((macro) => (
                  <MacroDonut key={macro.label} macro={macro} />
                ))}
              </div>
              {!selectedDateEntries.length ? (
                <p className="rounded-lg border border-white/10 bg-white/[0.035] p-3 text-sm text-zinc-400">
                  No food logged for this date yet. Progress starts at 0 and updates as entries are saved.
                </p>
              ) : null}
            </div>
          ) : (
            <EmptyState
              title="Set macro targets in Goals & Targets to enable progress tracking."
              description="Saved calorie, protein, carb, and fat targets power these progress cards."
              action="Open Goals & Targets"
              onAction={() => undefined}
            />
          )}
        </Card>
        <Card>
          <SectionHeader
            eyebrow="Today"
            title={`Food logged for ${forms.nutrition.date}`}
            action={
              <button onClick={() => setShowFoodHistory((value) => !value)} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">
                {showFoodHistory ? "Hide Food History" : "Food History"}
              </button>
            }
          />
          <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
            <MetricCard title="Calories" value={`${Math.round(selectedDateTotals.calories)}`} detail="selected day" icon={Apple} accent="border-cyan-400/20 bg-cyan-400/10 text-cyan-300" />
            <MetricCard title="Protein" value={`${Math.round(selectedDateTotals.protein)}g`} detail="selected day" icon={ProteinMoleculeIcon} accent="border-teal-400/20 bg-teal-400/10 text-teal-300" />
            <MetricCard title="Carbs" value={`${Math.round(selectedDateTotals.carbs)}g`} detail="selected day" icon={CarbsMoleculeIcon} accent="border-blue-400/20 bg-blue-400/10 text-blue-300" />
            <MetricCard title="Fat" value={`${Math.round(selectedDateTotals.fat)}g`} detail="selected day" icon={FatMoleculeIcon} accent="border-amber-400/20 bg-amber-400/10 text-amber-300" />
          </div>
          <div className="mt-4">
            {selectedDateEntries.length ? <DataTable rows={selectedDateEntries.slice().reverse()} /> : <EmptyState title="No food logged yet" description="Manual entries for this date will appear here immediately after saving." action="Use manual entry" onAction={() => undefined} />}
          </div>
        </Card>
        {showFoodHistory ? (
          <Card>
            <SectionHeader eyebrow="History" title="Daily nutrition summary" />
            {nutritionHistory.length ? (
              <div className="space-y-4">
                <div className="grid gap-3 md:grid-cols-4">
                  <MetricCard title="7-day calories" value={nutritionAdherence?.average_calories ? `${Math.round(nutritionAdherence.average_calories)}` : "No data"} detail={nutritionAdherence?.average_calories_delta !== null && nutritionAdherence?.average_calories_delta !== undefined ? `${deltaText(nutritionAdherence.average_calories_delta, " kcal")} avg` : "Target comparison pending"} icon={Apple} accent="border-cyan-400/20 bg-cyan-400/10 text-cyan-300" />
                  <MetricCard title="7-day protein" value={nutritionAdherence?.average_protein ? `${Math.round(nutritionAdherence.average_protein)}g` : "No data"} detail={nutritionAdherence?.average_protein_delta !== null && nutritionAdherence?.average_protein_delta !== undefined ? `${deltaText(nutritionAdherence.average_protein_delta, "g")} avg` : "Target comparison pending"} icon={Utensils} accent="border-teal-400/20 bg-teal-400/10 text-teal-300" />
                  <MetricCard title="Days over target" value={`${nutritionAdherence?.days_over_target ?? 0}`} detail="Recent 7 logged days" icon={Gauge} accent="border-amber-400/20 bg-amber-400/10 text-amber-300" />
                  <MetricCard title="Consistency" value={nutritionAdherence?.consistency_score ? `${Math.round(nutritionAdherence.consistency_score)}%` : "No target"} detail="Calories and macro adherence" icon={Sparkles} accent="border-violet-400/20 bg-violet-400/10 text-violet-300" />
                </div>
                <ChartFrame className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <RechartsLineChart data={recentHistory}>
                      <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                      <YAxis stroke="#71717a" tickLine={false} axisLine={false} />
                      <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                      <Line dataKey="total_calories" name="Calories" stroke="#60a5fa" strokeWidth={3} dot={false} />
                      <Line dataKey="target_calories" name="Target" stroke="#a78bfa" strokeWidth={2} strokeDasharray="4 4" dot={false} />
                    </RechartsLineChart>
                  </ResponsiveContainer>
                </ChartFrame>
                <ChartFrame className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={recentHistory}>
                      <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                      <YAxis stroke="#71717a" tickLine={false} axisLine={false} />
                      <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                      <Area type="monotone" dataKey="total_protein" name="Protein" stroke="#2dd4bf" fill="#2dd4bf33" strokeWidth={2} />
                      <Area type="monotone" dataKey="total_carbs" name="Carbs" stroke="#60a5fa" fill="#60a5fa22" strokeWidth={2} />
                      <Area type="monotone" dataKey="total_fat" name="Fat" stroke="#f59e0b" fill="#f59e0b22" strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                </ChartFrame>
                <DataTable rows={nutritionHistory.slice().reverse()} />
              </div>
            ) : (
              <EmptyState title="No daily nutrition summaries yet" description="Daily totals are built automatically after food is logged." action="Log food" onAction={() => undefined} />
            )}
          </Card>
        ) : null}
        <Card>
          <SectionHeader eyebrow="Food" title="Quick Add from Text" />
          <form onSubmit={onParseFood} className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <TextInput label="Date" type="date" value={forms.nutrition.date} onChange={(value) => setForms((state) => ({ ...state, nutrition: { ...state.nutrition, date: value } }))} />
            </div>
            <label className="block space-y-2 text-sm text-zinc-400">
              <span>Food list</span>
              <textarea
                className="min-h-32 w-full resize-y rounded-lg border border-white/10 bg-white/[0.04] px-3 py-3 text-zinc-100 outline-none transition placeholder:text-zinc-600 focus:border-cyan-300/60"
                value={aiText}
                maxLength={4000}
                placeholder="Example: 3 eggs, 2 slices sourdough toast with butter, chicken burrito bowl, protein shake with banana"
                onChange={(event) => setAiText(event.target.value)}
              />
              <span className="block text-xs text-zinc-600">{aiText.length}/4000</span>
            </label>
            <button disabled={parseLoading || !aiText.trim()} className="h-11 rounded-lg bg-violet-300 px-4 text-sm font-semibold text-zinc-950 disabled:cursor-not-allowed disabled:opacity-60">
              {parseLoading ? "Analyzing..." : "Analyze Food"}
            </button>
          </form>
          {shortcutSuggestion ? (
            <div className="mt-4 rounded-lg border border-cyan-300/20 bg-cyan-300/10 p-4">
              <p className="text-sm font-semibold text-cyan-100">Use saved {shortcutSuggestion.type} instead?</p>
              <p className="mt-1 text-sm text-zinc-300">{shortcutSuggestion.label} looks close to what you typed. Logging it avoids another OpenAI call.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button onClick={onUseSuggestion} className="rounded-lg bg-cyan-300 px-3 py-2 text-sm font-semibold text-zinc-950">Use saved shortcut</button>
                <button onClick={onParseAnyway} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Parse new anyway</button>
              </div>
            </div>
          ) : null}
          {parseResult ? (
            <div className={cx("mt-4 rounded-lg border p-3 text-sm", parseResult.success ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-100" : "border-amber-300/20 bg-amber-300/10 text-amber-100")}>
              <p>{parseResult.message}</p>
              <p className="mt-2 text-xs opacity-80">
                Debug: endpoint reached {parseResult.debug?.backend_endpoint_reached ? "yes" : "no"} · OpenAI key configured {parseResult.debug?.openai_key_configured ? "yes" : "no"} · model {parseResult.debug?.model ?? "unknown"} · status {parseResult.debug?.parsing_status ?? "unknown"}
              </p>
            </div>
          ) : null}
          {parsedFoods.length ? (
            <form onSubmit={onSaveParsedFoods} className="mt-5 space-y-4">
              <p className="text-sm text-zinc-400">Review and edit before saving. Nothing is saved until you confirm these draft items.</p>
              {parsedFoods.map((food, index) => (
                <div key={index} className="grid gap-3 rounded-lg border border-white/10 bg-white/[0.035] p-3 sm:grid-cols-2">
                  <div className="flex items-center justify-between gap-3 sm:col-span-2">
                    <p className="text-sm font-semibold text-white">Draft item {index + 1}</p>
                    <div className="flex gap-2">
                      <button type="button" onClick={() => setParsedFoods((items) => [...items.slice(0, index + 1), { ...food }, ...items.slice(index + 1)])} className="rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-zinc-200">
                        Duplicate
                      </button>
                      <button type="button" onClick={() => setParsedFoods((items) => items.filter((_, itemIndex) => itemIndex !== index))} className="rounded-lg border border-red-300/20 bg-red-300/10 px-3 py-1.5 text-xs font-semibold text-red-100">
                        Remove
                      </button>
                    </div>
                  </div>
                  <TextInput label="Food name" value={food.food_name} onChange={(value) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, food_name: value } : item))} />
                  <TextInput label="Quantity" type="number" min={0} step="any" value={food.quantity_value ?? ""} onChange={(value) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, quantity_value: value === "" ? null : Number(value), quantity: value } : item))} />
                  <TextInput label="Unit" value={food.unit ?? ""} onChange={(value) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, unit: value } : item))} />
                  <TextInput label="Serving description" value={food.serving_description ?? food.quantity} onChange={(value) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, serving_description: value } : item))} />
                  <TextInput label="Calories" type="number" min={0} step="any" value={food.calories} onChange={(value) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, calories: Number(value) } : item))} />
                  <TextInput label="Protein grams" type="number" min={0} step="any" value={food.protein} onChange={(value) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, protein: Number(value) } : item))} />
                  <TextInput label="Carbs grams" type="number" min={0} step="any" value={food.carbs} onChange={(value) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, carbs: Number(value) } : item))} />
                  <TextInput label="Fat grams" type="number" min={0} step="any" value={food.fat} onChange={(value) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, fat: Number(value) } : item))} />
                  <TextInput label="Fiber optional" type="number" min={0} step="any" value={food.fiber ?? ""} onChange={(value) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, fiber: value === "" ? null : Number(value) } : item))} />
                  <TextInput label="Sugar optional" type="number" min={0} step="any" value={food.sugar ?? ""} onChange={(value) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, sugar: value === "" ? null : Number(value) } : item))} />
                  <TextInput label="Sodium optional mg" type="number" min={0} step="any" value={food.sodium ?? ""} onChange={(value) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, sodium: value === "" ? null : Number(value) } : item))} />
                  <div className="space-y-2 text-sm text-zinc-400">
                    <span>Confidence</span>
                    <select className="h-11 w-full rounded-lg border border-white/10 bg-zinc-950 px-3 text-zinc-100 outline-none transition focus:border-cyan-300/60" value={food.confidence || "medium"} onChange={(event) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, confidence: event.target.value } : item))}>
                      <option value="high">high</option>
                      <option value="medium">medium</option>
                      <option value="low">low</option>
                    </select>
                  </div>
                  <div className="space-y-2 text-sm text-zinc-400">
                    <span>Source</span>
                    <select className="h-11 w-full rounded-lg border border-white/10 bg-zinc-950 px-3 text-zinc-100 outline-none transition focus:border-cyan-300/60" value={food.source || "openai_estimate"} onChange={(event) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, source: event.target.value } : item))}>
                      <option value="usda_fdc">USDA</option>
                      <option value="existing_database">Existing database</option>
                      <option value="openai_estimate">OpenAI estimate</option>
                      <option value="web_source">Web source</option>
                    </select>
                  </div>
                  <div className={cx("sm:col-span-2 rounded-lg border p-3 text-sm", food.confidence === "low" || food.verification_status?.includes("unavailable") || food.verification_status?.includes("conflict") ? "border-amber-300/25 bg-amber-300/10 text-amber-100" : "border-white/10 bg-white/[0.035] text-zinc-300")}>
                    <p className="font-medium text-white">Review notes</p>
                    <p className="mt-1">Original: {food.original_text || food.food_name}</p>
                    {food.assumptions?.length ? (
                      <ul className="mt-2 list-disc space-y-1 pl-5">
                        {food.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}
                      </ul>
                    ) : (
                      <p className="mt-1">{food.verification_reason || (food.source === "usda_fdc" ? "Matched nutrition database source context." : "Estimate only. Please review.")}</p>
                    )}
                    {food.source_url ? (
                      <a className="mt-2 inline-flex text-cyan-200 underline decoration-cyan-200/40" href={food.source_url} target="_blank" rel="noreferrer">
                        Source link
                      </a>
                    ) : null}
                    <p className="mt-2 text-zinc-400">{food.notes || "Review before saving."}</p>
                  </div>
                </div>
              ))}
              {parsedFoods.length ? (
                <p className="text-sm text-zinc-300">
                  Preview total: {Math.round(parsedFoods.reduce((sum, food) => sum + (Number(food.calories) || 0), 0))} cal · {Number(parsedFoods.reduce((sum, food) => sum + (Number(food.protein) || 0), 0).toFixed(1))}g protein · {Number(parsedFoods.reduce((sum, food) => sum + (Number(food.carbs) || 0), 0).toFixed(1))}g carbs · {Number(parsedFoods.reduce((sum, food) => sum + (Number(food.fat) || 0), 0).toFixed(1))}g fat
                </p>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <button className="h-11 rounded-lg bg-cyan-300 px-4 text-sm font-semibold text-zinc-950">
                  Save all confirmed items
                </button>
                <button type="button" onClick={(event) => onSaveShortcut(event as unknown as FormEvent)} className="h-11 rounded-lg border border-emerald-300/30 bg-emerald-300/10 px-4 text-sm font-semibold text-emerald-100">
                  Save as Food Shortcut
                </button>
                <button type="button" onClick={(event) => onSaveMealTemplate(event as unknown as FormEvent)} className="h-11 rounded-lg border border-violet-300/30 bg-violet-300/10 px-4 text-sm font-semibold text-violet-100">
                  Save as Meal Template
                </button>
                <button type="button" onClick={(event) => onSaveAndLogToday(event as unknown as FormEvent)} className="h-11 rounded-lg bg-amber-300 px-4 text-sm font-semibold text-zinc-950">
                  Save and Log Today
                </button>
              </div>
            </form>
          ) : null}
        </Card>
        <Card>
          <SectionHeader eyebrow="Log" title="Saved food entries" />
          {logs.length ? <DataTable rows={logs.slice(-8).reverse()} /> : <EmptyState title="No food logged yet" description="Manual food entries will appear here after saving." action="Log food" onAction={() => undefined} />}
        </Card>
        <Card>
          <SectionHeader eyebrow="Shortcuts" title="Food shortcuts & meal templates" />
          <div className="space-y-4">
            <TextInput label="Search shortcuts" value={shortcutQuery} placeholder="Finn shake" onChange={setShortcutQuery} />
            {filteredShortcuts.length ? (
              <div className="space-y-3">
                {filteredShortcuts.map((shortcut) => (
                  <div key={shortcut.shortcut_id} className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
                    {editingShortcut?.shortcut_id === shortcut.shortcut_id ? (
                      <div className="grid gap-3 sm:grid-cols-2">
                        <TextInput label="Shortcut name" value={editingShortcut.shortcut_name} onChange={(value) => setEditingShortcut((item) => item ? { ...item, shortcut_name: value } : item)} />
                        <TextInput label="Calories" type="number" min={0} step="any" value={editingShortcut.calories} onChange={(value) => setEditingShortcut((item) => item ? { ...item, calories: Number(value) } : item)} />
                        <TextInput label="Protein" type="number" min={0} step="any" value={editingShortcut.protein} onChange={(value) => setEditingShortcut((item) => item ? { ...item, protein: Number(value) } : item)} />
                        <TextInput label="Carbs" type="number" min={0} step="any" value={editingShortcut.carbs} onChange={(value) => setEditingShortcut((item) => item ? { ...item, carbs: Number(value) } : item)} />
                        <TextInput label="Fat" type="number" min={0} step="any" value={editingShortcut.fat} onChange={(value) => setEditingShortcut((item) => item ? { ...item, fat: Number(value) } : item)} />
                        <TextInput label="Notes" value={editingShortcut.notes ?? ""} onChange={(value) => setEditingShortcut((item) => item ? { ...item, notes: value } : item)} />
                        <div className="flex gap-2 sm:col-span-2">
                          <button type="button" onClick={() => { if (editingShortcut) onUpdateShortcut(editingShortcut); setEditingShortcut(null); }} className="rounded-lg bg-cyan-300 px-3 py-2 text-sm font-semibold text-zinc-950">Save edits</button>
                          <button type="button" onClick={() => setEditingShortcut(null)} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Cancel</button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <p className="font-semibold text-white">{shortcut.shortcut_name}</p>
                          <p className="mt-1 text-sm text-zinc-400">{Math.round(shortcut.calories)} cal · {Math.round(shortcut.protein)}g protein · {Math.round(shortcut.carbs)}g carbs · {Math.round(shortcut.fat)}g fat</p>
                          <p className="mt-2 inline-flex rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs text-zinc-300">Source: {shortcut.source || "manual"}</p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <button type="button" onClick={() => onLogShortcut(shortcut.shortcut_id)} className="rounded-lg bg-cyan-300 px-3 py-2 text-sm font-semibold text-zinc-950">Log today</button>
                          <button type="button" onClick={() => setEditingShortcut(shortcut)} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Edit</button>
                          <button type="button" onClick={() => onDeleteShortcut(shortcut.shortcut_id)} className="rounded-lg border border-red-300/30 px-3 py-2 text-sm font-semibold text-red-100">Delete</button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="No food shortcuts yet" description="Parse food with AI, then save it as a reusable shortcut for one-click logging." action="Use AI parser" onAction={() => undefined} />
            )}
            {templateSummaries.length ? (
              <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
                <p className="text-sm font-semibold text-white">Meal templates</p>
                <div className="mt-3 grid gap-3">
                  {templateSummaries.map((template) => (
                    <div key={template.template_name} className="grid gap-3 rounded-lg border border-violet-300/15 bg-violet-300/[0.045] p-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                      <div className="min-w-0">
                        {editingTemplateName === template.template_name ? (
                          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
                            <div className="min-w-0 flex-1">
                              <TextInput label="Template name" value={templateRenameValue} onChange={setTemplateRenameValue} />
                            </div>
                            <div className="flex gap-2 sm:pt-6">
                              <button
                                type="button"
                                onClick={() => void saveTemplateRename(template.template_name)}
                                disabled={!templateRenameValue.trim() || pendingTemplateAction === `rename:${template.template_name}`}
                                className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-cyan-300 text-zinc-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
                                aria-label="Save template name"
                              >
                                <Check className="h-4 w-4" />
                              </button>
                              <button
                                type="button"
                                onClick={cancelTemplateRename}
                                disabled={pendingTemplateAction === `rename:${template.template_name}`}
                                className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-zinc-300 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-50"
                                aria-label="Cancel template rename"
                              >
                                <X className="h-4 w-4" />
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="flex min-w-0 items-start gap-2">
                            <p className="line-clamp-2 min-w-0 text-sm font-semibold leading-5 text-white">{template.template_name}</p>
                            <button
                              type="button"
                              onClick={() => beginTemplateRename(template.template_name)}
                              className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-white/10 text-zinc-400 transition hover:border-cyan-300/30 hover:bg-cyan-300/10 hover:text-cyan-100"
                              aria-label={`Rename ${template.template_name}`}
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        )}
                        <p className="mt-1 text-xs text-zinc-500">{template.foods} item{template.foods === 1 ? "" : "s"} saved</p>
                      </div>
                      <div className="grid gap-3 sm:w-64">
                        <div className="grid grid-cols-4 gap-2 text-right">
                          <div>
                            <p className="text-[10px] uppercase tracking-[0.12em] text-zinc-500">Calories</p>
                            <p className="mt-1 text-xs font-semibold text-violet-100">{Math.round(template.calories)} kcal</p>
                          </div>
                          <div>
                            <p className="text-[10px] uppercase tracking-[0.12em] text-zinc-500">P</p>
                            <p className="mt-1 text-xs font-semibold text-violet-100">{Math.round(template.protein)}g</p>
                          </div>
                          <div>
                            <p className="text-[10px] uppercase tracking-[0.12em] text-zinc-500">C</p>
                            <p className="mt-1 text-xs font-semibold text-violet-100">{Math.round(template.carbs)}g</p>
                          </div>
                          <div>
                            <p className="text-[10px] uppercase tracking-[0.12em] text-zinc-500">F</p>
                            <p className="mt-1 text-xs font-semibold text-violet-100">{Math.round(template.fat)}g</p>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => void logTemplate(template.template_name)}
                          disabled={pendingTemplateAction === `log:${template.template_name}`}
                          className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-violet-200 px-3 py-2 text-xs font-semibold text-zinc-950 transition hover:bg-violet-100 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <Plus className="h-3.5 w-3.5" />
                          {pendingTemplateAction === `log:${template.template_name}` ? "Adding..." : "Add to log"}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </Card>
      </div>
    </div>
  );
}

function RecoveryPage({
  bodyMetrics,
  recoveryLogs,
  sleepEntries,
  forms,
  setForms,
  onBodySubmit,
  onRecoverySubmit,
}: Readonly<{
  bodyMetrics: BodyMetricEntry[];
  recoveryLogs: RecoveryEntry[];
  sleepEntries: SleepEntry[];
  forms: FormState;
  setForms: React.Dispatch<React.SetStateAction<FormState>>;
  onBodySubmit: (event: FormEvent) => void;
  onRecoverySubmit: (event: FormEvent) => void;
}>) {
  const sleepChartData = useMemo(() => {
    return sleepEntries
      .slice(-30)
      .map((entry) => {
        const bedtime = sleepClockHour(entry.sleepStart);
        const wake = sleepClockHour(entry.sleepEnd);
        return {
          date: entry.date,
          hours: Number(((entry.durationMinutes ?? 0) / 60).toFixed(2)),
          target: 8,
          efficiency: entry.efficiencyPercent ?? null,
          bedtime,
          wake,
        };
      })
      .filter((entry) => entry.hours > 0);
  }, [sleepEntries]);
  const sleepWindow = sleepChartData.slice(-7);
  const lastSleep = sleepEntries.length ? sleepEntries[sleepEntries.length - 1] : null;
  const sevenDaySleepAverage = sleepWindow.length ? sleepWindow.reduce((sum, entry) => sum + entry.hours, 0) / sleepWindow.length : null;
  const efficiencyEntries = sleepWindow.filter((entry) => entry.efficiency !== null);
  const averageEfficiency = efficiencyEntries.length ? efficiencyEntries.reduce((sum, entry) => sum + (Number(entry.efficiency) || 0), 0) / efficiencyEntries.length : null;
  const consistencyValues = sleepWindow.flatMap((entry) => [entry.bedtime, entry.wake].filter((value): value is number => value !== null));
  const consistencySpread = consistencyValues.length >= 4 ? Math.max(...consistencyValues) - Math.min(...consistencyValues) : null;
  const consistencyLabel = consistencySpread === null ? "Learning" : consistencySpread <= 1 ? "Good" : consistencySpread <= 2 ? "Normal" : "Irregular";
  const sleepQualityScore = sleepWindow.length
    ? Math.round(Math.min(100, ((Math.min(sevenDaySleepAverage ?? 0, 8) / 8) * 70) + (((averageEfficiency ?? 80) / 100) * 30)))
    : null;
  const recoveryImpact = sleepQualityScore === null
    ? "Sleep tracking will appear here once Fitbit / Google Fit is connected."
    : sleepQualityScore >= 82
      ? "Positive - sleep is supporting recovery."
      : sleepQualityScore >= 68
        ? "Neutral - sleep is adequate but still worth watching."
        : "Negative - sleep may be limiting readiness.";
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card className="xl:col-span-2">
        <SectionHeader eyebrow="Recovery" title="Sleep" />
        {sleepChartData.length ? (
          <div className="space-y-4">
            <div className="grid gap-3 md:grid-cols-4">
              <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Last night</p>
                <p className="mt-2 text-lg font-semibold text-white">{formatSleepDuration(lastSleep?.durationMinutes)}</p>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">7-day average</p>
                <p className="mt-2 text-lg font-semibold text-white">{sevenDaySleepAverage ? formatSleepDuration(sevenDaySleepAverage * 60) : "Need data"}</p>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Sleep quality</p>
                <p className="mt-2 text-lg font-semibold text-white">{sleepQualityScore ?? "--"}/100</p>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Consistency</p>
                <p className="mt-2 text-lg font-semibold text-white">{consistencyLabel}</p>
              </div>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-lg border border-white/10 bg-white/[0.025] p-4">
                <p className="text-sm font-semibold text-white">Sleep duration</p>
                <ChartFrame className="mt-3 h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <RechartsLineChart data={sleepChartData}>
                      <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                      <XAxis dataKey="date" hide />
                      <YAxis domain={[0, 10]} tick={{ fill: "#a1a1aa", fontSize: 12 }} />
                      <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", color: "#fff" }} />
                      <Line dataKey="target" stroke="#71717a" strokeDasharray="4 4" dot={false} strokeWidth={2} />
                      <Line dataKey="hours" stroke="#60a5fa" dot={false} strokeWidth={3} />
                    </RechartsLineChart>
                  </ResponsiveContainer>
                </ChartFrame>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/[0.025] p-4">
                <p className="text-sm font-semibold text-white">Sleep consistency</p>
                {sleepChartData.some((entry) => entry.bedtime !== null || entry.wake !== null) ? (
                  <ChartFrame className="mt-3 h-56">
                    <ResponsiveContainer width="100%" height="100%">
                      <RechartsLineChart data={sleepChartData}>
                        <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                        <XAxis dataKey="date" hide />
                        <YAxis domain={[0, 24]} tick={{ fill: "#a1a1aa", fontSize: 12 }} />
                        <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", color: "#fff" }} />
                        <Line dataKey="bedtime" stroke="#a78bfa" dot={false} strokeWidth={3} />
                        <Line dataKey="wake" stroke="#34d399" dot={false} strokeWidth={3} />
                      </RechartsLineChart>
                    </ResponsiveContainer>
                  </ChartFrame>
                ) : (
                  <div className="mt-3 flex h-56 items-center rounded-lg border border-dashed border-white/10 bg-black/10 p-4 text-sm leading-6 text-zinc-400">
                    Bedtime and wake-time trends will appear once Fitbit / Google Fit provides sleep start and end times.
                  </div>
                )}
              </div>
            </div>
            <div className="rounded-lg border border-blue-300/15 bg-blue-300/[0.045] p-4">
              <p className="text-sm font-semibold text-blue-100">Recovery impact</p>
              <p className="mt-2 text-sm leading-6 text-zinc-300">{recoveryImpact}</p>
            </div>
          </div>
        ) : (
          <EmptyState title="Sleep tracking will appear here once Fitbit / Google Fit is connected." description="Manual recovery sleep entries and future wearable sleep stages will power duration, consistency, and quality trends." action="Connect wearable" onAction={() => undefined} />
        )}
      </Card>

      <Card>
        <SectionHeader eyebrow="Body" title="Bodyweight entry" />
        <form onSubmit={onBodySubmit} className="grid gap-4 sm:grid-cols-2">
          <TextInput label="Date" type="date" value={forms.body.date} onChange={(value) => setForms((state) => ({ ...state, body: { ...state.body, date: value } }))} />
          <TextInput label="Bodyweight" type="number" value={forms.body.bodyweight} onChange={(value) => setForms((state) => ({ ...state, body: { ...state.body, bodyweight: Number(value) } }))} />
          <TextInput label="Waist optional" type="number" value={forms.body.waist ?? ""} onChange={(value) => setForms((state) => ({ ...state, body: { ...state.body, waist: value ? Number(value) : null } }))} />
          <TextInput label="Body fat % optional" type="number" value={forms.body.estimated_body_fat ?? ""} onChange={(value) => setForms((state) => ({ ...state, body: { ...state.body, estimated_body_fat: value ? Number(value) : null } }))} />
          <TextInput label="Notes" value={forms.body.notes} onChange={(value) => setForms((state) => ({ ...state, body: { ...state.body, notes: value } }))} />
          <button className="h-11 rounded-lg bg-blue-300 text-sm font-semibold text-zinc-950">Save bodyweight</button>
        </form>
        <div className="mt-4">
          {bodyMetrics.length ? <DataTable rows={bodyMetrics.slice(-5).reverse()} /> : <EmptyState title="Enter your first bodyweight entry" description="Trend feedback needs at least two saved bodyweight entries." action="Use form above" onAction={() => undefined} />}
        </div>
      </Card>

      <Card>
        <SectionHeader eyebrow="Recovery" title="Daily check-in" />
        <form onSubmit={onRecoverySubmit} className="grid gap-4 sm:grid-cols-2">
          <TextInput label="Date" type="date" value={forms.recovery.date} onChange={(value) => setForms((state) => ({ ...state, recovery: { ...state.recovery, date: value } }))} />
          <TextInput label="Sleep hours" type="number" value={forms.recovery.sleep_hours} onChange={(value) => setForms((state) => ({ ...state, recovery: { ...state.recovery, sleep_hours: Number(value) } }))} />
          {(["sleep_quality", "fatigue", "soreness", "stress", "motivation"] as const).map((key) => (
            <TextInput key={key} label={`${key.replace("_", " ")} (1-10)`} type="number" value={forms.recovery[key]} onChange={(value) => setForms((state) => ({ ...state, recovery: { ...state.recovery, [key]: Number(value) } }))} />
          ))}
          <TextInput label="Resting HR optional" type="number" value={forms.recovery.resting_hr ?? ""} onChange={(value) => setForms((state) => ({ ...state, recovery: { ...state.recovery, resting_hr: value ? Number(value) : null } }))} />
          <TextInput label="HRV optional" type="number" value={forms.recovery.hrv ?? ""} onChange={(value) => setForms((state) => ({ ...state, recovery: { ...state.recovery, hrv: value ? Number(value) : null } }))} />
          <TextInput label="Notes" value={forms.recovery.notes} onChange={(value) => setForms((state) => ({ ...state, recovery: { ...state.recovery, notes: value } }))} />
          <button className="h-11 rounded-lg bg-emerald-300 text-sm font-semibold text-zinc-950">Save check-in</button>
        </form>
        <div className="mt-4">
          {recoveryLogs.length ? <DataTable rows={recoveryLogs.slice(-5).reverse()} /> : <EmptyState title="No recovery check-in yet" description="Submit sleep, fatigue, soreness, stress, and motivation to generate readiness trends." action="Use form above" onAction={() => undefined} />}
        </div>
      </Card>
    </div>
  );
}

function WorkoutHistory({
  workouts,
  onImportHevy,
  defaultExpanded = false,
  metadata = "Synced from Hevy",
}: Readonly<{
  workouts: WorkoutGroup[];
  onImportHevy: () => void;
  defaultExpanded?: boolean;
  metadata?: string;
}>) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const thisMonth = new Date().toISOString().slice(0, 7);
  const monthlyCount = workouts.filter((workout) => workout.date.startsWith(thisMonth)).length;
  const subtitle = [metadata, monthlyCount ? `${monthlyCount} workouts this month` : ""].filter(Boolean).join(" · ");

  const content = !workouts.length ? (
    <EmptyState title="No workouts logged yet" description="Hevy-synced sessions will appear here by day." action="Import from Hevy" onAction={onImportHevy} />
  ) : (
    <div className="space-y-3">
      {workouts.map((workout) => (
        <details key={`${workout.date}-${workout.workout_id}`} className="rounded-xl border border-white/10 bg-white/[0.035] p-4">
          <summary className="cursor-pointer list-none">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-base font-semibold text-white">{workout.date}</p>
                <p className="mt-1 text-sm text-zinc-400">{workout.workout_type || "Workout"} - {workout.exercise_names.slice(0, 5).join(", ") || "No exercises"}</p>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs sm:flex sm:flex-wrap">
                <span className="rounded-full border border-white/10 px-2 py-1 text-zinc-300">{workout.total_sets} sets</span>
                <span className="rounded-full border border-white/10 px-2 py-1 text-zinc-300">{Math.round(workout.total_volume).toLocaleString()} volume</span>
                <span className="rounded-full border border-white/10 px-2 py-1 text-zinc-300">{workout.duration_minutes ? `${Math.round(workout.duration_minutes)} min` : "No duration"}</span>
                <span className="rounded-full border border-white/10 px-2 py-1 text-zinc-300">{workout.source || "manual"}</span>
              </div>
            </div>
          </summary>
          <div className="mt-4 overflow-x-auto rounded-lg border border-white/10">
            <table className="min-w-full divide-y divide-white/10 text-sm">
              <thead className="bg-white/[0.04] text-left text-zinc-400">
                <tr>
                  {["exercise", "set", "sets", "reps", "weight", "RPE", "notes"].map((label) => (
                    <th key={label} className="px-3 py-2 font-medium">{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {workout.details.map((row, index) => (
                  <tr key={`${row.external_id || row.exercise}-${index}`} className="text-zinc-200">
                    <td className="px-3 py-2">{row.exercise || "-"}</td>
                    <td className="px-3 py-2">{row.set_number || index + 1}</td>
                    <td className="px-3 py-2">{row.sets}</td>
                    <td className="px-3 py-2">{row.reps}</td>
                    <td className="px-3 py-2">{row.weight}</td>
                    <td className="px-3 py-2">{row.rpe || "-"}</td>
                    <td className="px-3 py-2 max-w-xs truncate">{row.notes || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details className="mt-3 rounded-lg border border-white/10 bg-zinc-950/40 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-zinc-400">Advanced/debug source IDs</summary>
            <div className="mt-3 space-y-1 text-xs text-zinc-500">
              <p>workout_id: {workout.workout_id}</p>
              {workout.details.slice(0, 8).map((row, index) => (
                <p key={index}>{row.exercise}: {row.source || "manual"} / {row.external_id || "no external id"}</p>
              ))}
            </div>
          </details>
        </details>
      ))}
    </div>
  );

  return (
    <Card className="overflow-hidden p-0">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition hover:bg-white/[0.035]"
      >
        <div className="min-w-0">
          <p className="text-sm uppercase tracking-[0.14em] text-zinc-500">History</p>
          <h2 className="mt-1 text-xl font-semibold text-white">Workout History</h2>
          <p className="mt-1 truncate text-sm text-zinc-400">{subtitle}</p>
        </div>
        <ChevronDown className={cx("h-5 w-5 shrink-0 text-zinc-400 transition-transform duration-200", expanded && "rotate-180")} />
      </button>
      <div className={cx("grid transition-[grid-template-rows] duration-300 ease-out", expanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
        <div className="min-h-0 overflow-hidden">
          <div className="border-t border-white/10 p-5">
            {content}
          </div>
        </div>
      </div>
    </Card>
  );
}

function StrengthTrendsSection({
  strength,
  selectedExercise,
  setSelectedExercise,
  trendView,
  setTrendView,
  selectedMuscleGroup,
  setSelectedMuscleGroup,
  trendDateRange,
  setTrendDateRange,
  muscleTrendMetric,
  setMuscleTrendMetric,
}: Readonly<{
  strength: StrengthTrendResponse | null;
  selectedExercise: string;
  setSelectedExercise: (value: string) => void;
  trendView: "exercise" | "muscle_group";
  setTrendView: (value: "exercise" | "muscle_group") => void;
  selectedMuscleGroup: string;
  setSelectedMuscleGroup: (value: string) => void;
  trendDateRange: string;
  setTrendDateRange: (value: string) => void;
  muscleTrendMetric: keyof Pick<MuscleGroupTrendHistory, "strength_index" | "weekly_volume" | "hard_sets" | "total_reps" | "best_estimated_1rm">;
  setMuscleTrendMetric: (value: keyof Pick<MuscleGroupTrendHistory, "strength_index" | "weekly_volume" | "hard_sets" | "total_reps" | "best_estimated_1rm">) => void;
}>) {
  const trend = strength?.trend;
  const muscleTrends = strength?.muscle_group_trends;
  const selectedGroups = selectedMuscleGroup ? [selectedMuscleGroup] : muscleTrends?.summary.slice(0, 6).map((item) => item.muscle_group) ?? [];
  const muscleChartData = muscleTrends?.history
    .filter((item) => !selectedGroups.length || selectedGroups.includes(item.muscle_group))
    .reduce<Array<Record<string, string | number>>>((rows, item) => {
      let row = rows.find((entry) => entry.week === item.week);
      if (!row) {
        row = { week: item.week };
        rows.push(row);
      }
      row[item.muscle_group] = Number(item[muscleTrendMetric]) || 0;
      return rows;
    }, []) ?? [];
  const metricLabels: Record<typeof muscleTrendMetric, string> = {
    strength_index: "Strength Index",
    weekly_volume: "Weekly Volume",
    hard_sets: "Hard Sets",
    total_reps: "Total Reps",
    best_estimated_1rm: "Estimated 1RM Index",
  };
  const lineColors = ["#a78bfa", "#38bdf8", "#34d399", "#f59e0b", "#fb7185", "#2dd4bf"];
  return (
    <Card>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <SectionHeader eyebrow="Strength" title="Exercise trends" />
        <div className="inline-flex rounded-lg border border-white/10 bg-white/[0.04] p-1">
          <button type="button" onClick={() => setTrendView("exercise")} className={cx("rounded-md px-3 py-2 text-sm font-semibold transition", trendView === "exercise" ? "bg-cyan-300 text-zinc-950" : "text-zinc-300 hover:bg-white/[0.06]")}>
            Exercise View
          </button>
          <button type="button" onClick={() => setTrendView("muscle_group")} className={cx("rounded-md px-3 py-2 text-sm font-semibold transition", trendView === "muscle_group" ? "bg-cyan-300 text-zinc-950" : "text-zinc-300 hover:bg-white/[0.06]")}>
            Muscle Group View
          </button>
        </div>
      </div>
      {strength?.exercise_options.length ? (
        <div className="space-y-4">
          {trendView === "exercise" ? (
            <>
              <SelectInput label="Exercise" value={selectedExercise || strength.selected_exercise} options={strength.exercise_options} onChange={setSelectedExercise} />
              <div className="grid gap-3 md:grid-cols-3">
                <MetricCard title="Trend" value={trend?.label ?? "insufficient data"} detail={trend?.summary ?? "Select an exercise"} icon={Gauge} accent="border-violet-400/20 bg-violet-400/10 text-violet-300" />
                <MetricCard title="Best Set" value={trend?.best_set ? `${trend.best_set.weight} x ${trend.best_set.reps}` : "No best set"} detail={trend?.best_set ? `${trend.best_set.estimated_1rm} est. 1RM` : "Log weighted sets"} icon={Dumbbell} accent="border-amber-400/20 bg-amber-400/10 text-amber-300" />
                <MetricCard title="Recent PR" value={trend?.recent_pr ? "Yes" : "No"} detail={trend?.best_set?.date ?? "Needs history"} icon={Sparkles} accent="border-emerald-400/20 bg-emerald-400/10 text-emerald-300" />
              </div>
              {trend?.history.length ? (
                <div className="grid gap-4 lg:grid-cols-2">
                  <ChartFrame className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <RechartsLineChart data={trend.history}>
                        <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                        <XAxis dataKey="date" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                        <YAxis stroke="#71717a" tickLine={false} axisLine={false} />
                        <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                        <Line dataKey="estimated_1rm" stroke="#a78bfa" strokeWidth={3} dot={false} />
                      </RechartsLineChart>
                    </ResponsiveContainer>
                  </ChartFrame>
                  <ChartFrame className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={trend.history}>
                        <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                        <XAxis dataKey="date" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                        <YAxis stroke="#71717a" tickLine={false} axisLine={false} />
                        <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                        <Bar dataKey="total_volume" fill="#f59e0b" radius={[6, 6, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </ChartFrame>
                </div>
              ) : (
                <EmptyState title="Insufficient trend data" description="Log the same weighted exercise multiple times to see estimated 1RM and volume trends." action="Log training" onAction={() => undefined} />
              )}
            </>
          ) : (
            <div className="space-y-4">
              <div className="grid gap-3 md:grid-cols-3">
                <SelectInput label="Date range" value={trendDateRange} options={["4w", "8w", "12w", "6m", "all"]} onChange={setTrendDateRange} />
                <SelectInput label="Muscle group" value={selectedMuscleGroup} options={["", ...(muscleTrends?.muscle_group_options ?? [])]} onChange={setSelectedMuscleGroup} />
                <SelectInput label="Metric" value={muscleTrendMetric} options={["strength_index", "weekly_volume", "hard_sets", "total_reps", "best_estimated_1rm"]} onChange={(value) => setMuscleTrendMetric(value as typeof muscleTrendMetric)} />
              </div>
              {muscleTrends?.summary.length ? (
                <>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {muscleTrends.summary.map((item) => (
                      <div key={item.muscle_group} className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="font-semibold text-white">{item.muscle_group}</p>
                            <p className={cx("mt-1 text-lg font-semibold", item.strength_change_pct >= 0 ? "text-emerald-200" : "text-red-200")}>
                              {item.strength_change_pct >= 0 ? "+" : ""}{item.strength_change_pct}%
                            </p>
                          </div>
                          <span className="rounded-full border border-white/10 px-2 py-1 text-xs text-zinc-300">Index {item.strength_index}</span>
                        </div>
                        <p className="mt-3 text-sm text-zinc-400">Weekly volume {item.volume_change_pct >= 0 ? "+" : ""}{item.volume_change_pct}% · {item.hard_sets} sets · {item.total_reps} reps</p>
                        <p className="mt-2 text-sm text-zinc-300">Best contributor: {item.recent_best_exercise || "No clear contributor"}</p>
                      </div>
                    ))}
                  </div>
                  <ChartFrame className="h-72">
                    <ResponsiveContainer width="100%" height="100%">
                      <RechartsLineChart data={muscleChartData}>
                        <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                        <XAxis dataKey="week" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                        <YAxis stroke="#71717a" tickLine={false} axisLine={false} />
                        <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                        {selectedGroups.map((group, index) => (
                          <Line key={group} dataKey={group} name={`${group} ${metricLabels[muscleTrendMetric]}`} stroke={lineColors[index % lineColors.length]} strokeWidth={3} dot={false} />
                        ))}
                      </RechartsLineChart>
                    </ResponsiveContainer>
                  </ChartFrame>
                  {muscleTrends.unmapped_exercises.length ? (
                    <div className="rounded-lg border border-amber-300/20 bg-amber-300/10 p-3 text-sm text-amber-100">
                      Unmapped exercises: {muscleTrends.unmapped_exercises.join(", ")}
                    </div>
                  ) : null}
                </>
              ) : (
                <EmptyState title="No muscle group trend yet" description="Muscle group trends need weighted Hevy or manual strength rows in the selected range." action="Change filters" onAction={() => setSelectedMuscleGroup("")} />
              )}
            </div>
          )}
        </div>
      ) : (
        <EmptyState title="No exercises yet" description="Strength trends need saved strength training rows." action="Log training" onAction={() => undefined} />
      )}
    </Card>
  );
}

function AITrainingInsightsSection({
  insight,
  onAnalyze,
}: Readonly<{
  insight: TrainingInsight | null;
  onAnalyze: () => void;
}>) {
  return (
    <Card>
      <SectionHeader eyebrow="OpenAI" title="AI training insights" />
      <button onClick={onAnalyze} className="inline-flex h-11 items-center gap-2 rounded-lg bg-violet-300 px-4 text-sm font-semibold text-zinc-950">
        <Sparkles className="h-4 w-4" />
        Analyze Training with AI
      </button>
      {insight ? (
        <div className="mt-5 grid gap-4 lg:grid-cols-3">
          <div className="rounded-xl border border-white/10 bg-white/[0.035] p-4">
            <p className="text-sm font-semibold text-white">Top insights</p>
            <ul className="mt-3 space-y-2 text-sm text-zinc-300">
              {(insight.top_insights.length ? insight.top_insights : [insight.message]).map((item) => <li key={item}>{item}</li>)}
            </ul>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.035] p-4">
            <p className="text-sm font-semibold text-white">Possible issues</p>
            <ul className="mt-3 space-y-2 text-sm text-zinc-300">
              {(insight.possible_issues.length ? insight.possible_issues : ["No issues identified from supplied data."]).map((item) => <li key={item}>{item}</li>)}
            </ul>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.035] p-4">
            <p className="text-sm font-semibold text-white">Next actions</p>
            <ul className="mt-3 space-y-2 text-sm text-zinc-300">
              {(insight.recommended_adjustments.length ? insight.recommended_adjustments : ["Keep logging training to improve confidence."]).map((item) => <li key={item}>{item}</li>)}
            </ul>
          </div>
          <div className="lg:col-span-3 rounded-xl border border-white/10 bg-zinc-950/50 p-4">
            <p className="text-sm text-zinc-400">Confidence: <span className="text-violet-200">{insight.confidence_level}</span> · Model: {insight.model}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {insight.evidence.map((item) => <span key={item} className="rounded-full border border-white/10 px-3 py-1 text-xs text-zinc-300">{item}</span>)}
            </div>
          </div>
        </div>
      ) : (
        <p className="mt-3 text-sm text-zinc-400">AI will analyze only the supplied training, strength, muscle balance, recovery, and nutrition summaries.</p>
      )}
    </Card>
  );
}

function TrainingPage({
  workoutHistory,
  strength,
  selectedExercise,
  setSelectedExercise,
  trainingInsight,
  onImportStrava,
  onPreviewHevy,
  onConfirmHevy,
  onCancelHevy,
  onSyncHevy,
  onAnalyzeTraining,
  hevyPreview,
  hevySync,
  hevySyncing,
  trendView,
  setTrendView,
  selectedMuscleGroup,
  setSelectedMuscleGroup,
  trendDateRange,
  setTrendDateRange,
  muscleTrendMetric,
  setMuscleTrendMetric,
}: Readonly<{
  workoutHistory: WorkoutGroup[];
  strength: StrengthTrendResponse | null;
  selectedExercise: string;
  setSelectedExercise: (value: string) => void;
  trainingInsight: TrainingInsight | null;
  onImportStrava: () => void;
  onPreviewHevy: () => void;
  onConfirmHevy: () => void;
  onCancelHevy: () => void;
  onSyncHevy: () => void;
  onAnalyzeTraining: () => void;
  hevyPreview: HevyPreview | null;
  hevySync: HevySyncStatus | null;
  hevySyncing: boolean;
  trendView: "exercise" | "muscle_group";
  setTrendView: (value: "exercise" | "muscle_group") => void;
  selectedMuscleGroup: string;
  setSelectedMuscleGroup: (value: string) => void;
  trendDateRange: string;
  setTrendDateRange: (value: string) => void;
  muscleTrendMetric: keyof Pick<MuscleGroupTrendHistory, "strength_index" | "weekly_volume" | "hard_sets" | "total_reps" | "best_estimated_1rm">;
  setMuscleTrendMetric: (value: keyof Pick<MuscleGroupTrendHistory, "strength_index" | "weekly_volume" | "hard_sets" | "total_reps" | "best_estimated_1rm">) => void;
}>) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4">
        <Card>
          <SectionHeader eyebrow="Imports" title="Hevy and Strava" />
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-dashed border-white/15 bg-white/[0.03] p-6">
              <p className="font-medium text-white">Import Hevy workouts</p>
              <p className="mt-2 text-sm text-zinc-400">Uses webhooks plus a polling fallback. Manual refresh polls Hevy events immediately and upserts changed workouts.</p>
              <p className={cx("mt-3 text-xs", hevySync?.last_error ? "text-amber-200" : "text-zinc-500")}>
                {relativeSyncTime(hevySync?.last_synced_at ?? "")}
                {hevySync?.last_error ? ` - ${hevySync.last_error}` : ""}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button onClick={onSyncHevy} disabled={hevySyncing} className="inline-flex items-center gap-2 rounded-lg bg-emerald-300 px-3 py-2 text-sm font-semibold text-zinc-950 disabled:cursor-not-allowed disabled:opacity-60">
                  <RefreshCw className={cx("h-4 w-4", hevySyncing && "animate-spin")} />
                  {hevySyncing ? "Syncing..." : "Refresh Hevy Now"}
                </button>
                <button onClick={onPreviewHevy} className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">
                  Preview recent
                </button>
              </div>
            </div>
            <div className="rounded-lg border border-dashed border-white/15 bg-white/[0.03] p-6">
              <p className="font-medium text-white">Import Strava activities</p>
              <p className="mt-2 text-sm text-zinc-400">After connecting Strava, import recent runs into the local training log. Duplicate Strava activity IDs are skipped.</p>
              <button onClick={onImportStrava} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-orange-300 px-3 py-2 text-sm font-semibold text-zinc-950">
                <RefreshCw className="h-4 w-4" />
                Import Strava runs
              </button>
            </div>
          </div>
          {hevyPreview ? (
            <div className="mt-5 rounded-xl border border-emerald-300/20 bg-emerald-300/[0.04] p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <p className="text-sm font-semibold text-white">Hevy import preview</p>
                  <p className="mt-1 text-sm text-zinc-400">
                    {hevyPreview.estimated_rows} estimated rows, {hevyPreview.duplicates_detected} duplicate rows detected.
                  </p>
                  {hevyPreview.debug_file ? <p className="mt-1 text-xs text-zinc-500">Raw response saved to {hevyPreview.debug_file}</p> : null}
                </div>
                <div className="flex gap-2">
                  <button onClick={onConfirmHevy} className="rounded-lg bg-emerald-300 px-3 py-2 text-sm font-semibold text-zinc-950">Confirm Import</button>
                  <button onClick={onCancelHevy} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Cancel</button>
                </div>
              </div>
              {hevyPreview.warnings?.length ? (
                <div className="mt-3 rounded-lg border border-amber-300/20 bg-amber-300/10 p-3 text-sm text-amber-100">
                  {hevyPreview.warnings.join(" ")}
                </div>
              ) : null}
              <div className="mt-4 grid gap-3">
                {hevyPreview.workouts.length ? hevyPreview.workouts.map((workout) => (
                  <div key={workout.workout_id || `${workout.date}-${workout.title}`} className="rounded-lg border border-white/10 bg-zinc-950/50 p-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <p className="font-medium text-white">{workout.title}</p>
                        <p className="text-sm text-zinc-400">{workout.date} - {workout.exercise_names.slice(0, 6).join(", ") || "No exercises returned"}</p>
                      </div>
                      <div className="flex flex-wrap gap-2 text-xs">
                        <span className="rounded-full border border-white/10 px-2 py-1 text-zinc-300">{workout.estimated_rows} rows</span>
                        <span className={cx("rounded-full border px-2 py-1", workout.duplicate ? "border-amber-300/30 bg-amber-300/10 text-amber-200" : "border-emerald-300/30 bg-emerald-300/10 text-emerald-200")}>
                          {workout.duplicate ? "Duplicate workout" : `${workout.new_rows} new rows`}
                        </span>
                      </div>
                    </div>
                  </div>
                )) : (
                  <EmptyState title="No Hevy workouts found" description="The preview did not return recent workouts from Hevy." action="Try again" onAction={onPreviewHevy} />
                )}
              </div>
            </div>
          ) : null}
        </Card>
      </div>
      <WorkoutHistory workouts={workoutHistory} onImportHevy={onPreviewHevy} metadata={relativeSyncTime(hevySync?.last_synced_at ?? "")} />
      <StrengthTrendsSection
        strength={strength}
        selectedExercise={selectedExercise}
        setSelectedExercise={setSelectedExercise}
        trendView={trendView}
        setTrendView={setTrendView}
        selectedMuscleGroup={selectedMuscleGroup}
        setSelectedMuscleGroup={setSelectedMuscleGroup}
        trendDateRange={trendDateRange}
        setTrendDateRange={setTrendDateRange}
        muscleTrendMetric={muscleTrendMetric}
        setMuscleTrendMetric={setMuscleTrendMetric}
      />
      <AITrainingInsightsSection insight={trainingInsight} onAnalyze={onAnalyzeTraining} />
    </div>
  );
}

function HistoryPage({
  nutritionLogs,
  nutritionHistory,
  nutritionAdherence,
  bodyMetrics,
  recoveryTrend,
  trainingVolume,
  workoutHistory,
  strength,
  selectedExercise,
  setSelectedExercise,
  trendView,
  setTrendView,
  selectedMuscleGroup,
  setSelectedMuscleGroup,
  trendDateRange,
  setTrendDateRange,
  muscleTrendMetric,
  setMuscleTrendMetric,
}: Readonly<{
  nutritionLogs: NutritionEntry[];
  nutritionHistory: DailyNutritionSummary[];
  nutritionAdherence: NutritionAdherence | null;
  bodyMetrics: BodyMetricEntry[];
  recoveryTrend: DashboardData["recovery_trend"];
  trainingVolume: DashboardData["training_volume"];
  workoutHistory: WorkoutGroup[];
  strength: StrengthTrendResponse | null;
  selectedExercise: string;
  setSelectedExercise: (value: string) => void;
  trendView: "exercise" | "muscle_group";
  setTrendView: (value: "exercise" | "muscle_group") => void;
  selectedMuscleGroup: string;
  setSelectedMuscleGroup: (value: string) => void;
  trendDateRange: string;
  setTrendDateRange: (value: string) => void;
  muscleTrendMetric: keyof Pick<MuscleGroupTrendHistory, "strength_index" | "weekly_volume" | "hard_sets" | "total_reps" | "best_estimated_1rm">;
  setMuscleTrendMetric: (value: keyof Pick<MuscleGroupTrendHistory, "strength_index" | "weekly_volume" | "hard_sets" | "total_reps" | "best_estimated_1rm">) => void;
}>) {
  const nutritionTrend = useMemo(() => aggregateNutrition(nutritionLogs), [nutritionLogs]);
  const dailyNutritionTrend = nutritionHistory.length ? nutritionHistory : nutritionTrend.map((entry) => ({
    date: entry.date,
    total_calories: entry.calories,
    total_protein: entry.protein,
    total_carbs: 0,
    total_fat: 0,
    fiber: null,
    sodium: null,
    potassium: null,
    magnesium: null,
    calcium: null,
    iron: null,
    zinc: null,
    vitamin_d: null,
    omega_3: null,
    target_calories: null,
    target_protein: null,
    target_carbs: null,
    target_fat: null,
    calories_delta: null,
    protein_delta: null,
    carbs_delta: null,
    fat_delta: null,
    adherence_score: null,
    notes: "",
  }));
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionHeader eyebrow="Nutrition" title="Daily nutrition history" />
          {dailyNutritionTrend.length ? (
            <div className="space-y-4">
              <div className="grid gap-3 md:grid-cols-4">
                <MetricCard title="7-day Calories" value={nutritionAdherence?.average_calories ? `${Math.round(nutritionAdherence.average_calories)}` : "No data"} detail={nutritionAdherence?.average_calories_delta !== null && nutritionAdherence?.average_calories_delta !== undefined ? `${deltaText(nutritionAdherence.average_calories_delta, " kcal")} avg` : "Totals only"} icon={Apple} accent="border-cyan-400/20 bg-cyan-400/10 text-cyan-300" />
                <MetricCard title="7-day Protein" value={nutritionAdherence?.average_protein ? `${Math.round(nutritionAdherence.average_protein)}g` : "No data"} detail={nutritionAdherence?.average_protein_delta !== null && nutritionAdherence?.average_protein_delta !== undefined ? `${deltaText(nutritionAdherence.average_protein_delta, "g")} avg` : "Totals only"} icon={ProteinMoleculeIcon} accent="border-teal-400/20 bg-teal-400/10 text-teal-300" />
                <MetricCard title="Over Target" value={`${nutritionAdherence?.days_over_target ?? 0}`} detail="Recent logged days" icon={Gauge} accent="border-amber-400/20 bg-amber-400/10 text-amber-300" />
                <MetricCard title="Adherence" value={nutritionAdherence?.consistency_score ? `${Math.round(nutritionAdherence.consistency_score)}%` : "No target"} detail="Calories/macros vs targets" icon={Sparkles} accent="border-violet-400/20 bg-violet-400/10 text-violet-300" />
              </div>
            <ChartFrame className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <RechartsLineChart data={dailyNutritionTrend}>
                  <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                  <YAxis stroke="#71717a" tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                  <Line dataKey="total_calories" name="Calories" stroke="#60a5fa" strokeWidth={3} dot={false} />
                  <Line dataKey="target_calories" name="Calorie target" stroke="#a78bfa" strokeWidth={2} strokeDasharray="4 4" dot={false} />
                  <Line dataKey="total_protein" name="Protein" stroke="#2dd4bf" strokeWidth={3} dot={false} />
                </RechartsLineChart>
              </ResponsiveContainer>
            </ChartFrame>
              <DataTable rows={nutritionHistory.slice().reverse()} />
            </div>
          ) : (
            <EmptyState title="No food logged yet" description="Nutrition charts will appear once you save food entries." action="Open Food" onAction={() => undefined} />
          )}
        </Card>
        <Card>
          <SectionHeader eyebrow="Body" title="Bodyweight history" />
          {bodyMetrics.length ? (
            <ChartFrame className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={bodyMetrics}>
                  <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                  <YAxis stroke="#71717a" tickLine={false} axisLine={false} domain={["dataMin - 1", "dataMax + 1"]} />
                  <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                  <Area dataKey="bodyweight" stroke="#60a5fa" fill="#60a5fa" fillOpacity={0.18} strokeWidth={3} />
                </AreaChart>
              </ResponsiveContainer>
            </ChartFrame>
          ) : (
            <EmptyState title="Enter your first bodyweight entry" description="Bodyweight history will render here." action="Open Weight" onAction={() => undefined} />
          )}
        </Card>
        <Card>
          <SectionHeader eyebrow="Recovery" title="Recovery trend" />
          {recoveryTrend.length ? (
            <ChartFrame className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <RechartsLineChart data={recoveryTrend}>
                  <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                  <YAxis stroke="#71717a" tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                  <Line dataKey="recovery_score" stroke="#34d399" strokeWidth={3} dot={false} />
                </RechartsLineChart>
              </ResponsiveContainer>
            </ChartFrame>
          ) : (
            <EmptyState title="No recovery check-in yet" description="Recovery charts need saved check-ins." action="Open Recovery" onAction={() => undefined} />
          )}
        </Card>
        <Card>
          <SectionHeader eyebrow="Training" title="Strength volume" />
          {trainingVolume.length ? (
            <ChartFrame className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={trainingVolume}>
                  <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                  <YAxis stroke="#71717a" tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                  <Bar dataKey="volume" fill="#f59e0b" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartFrame>
          ) : (
            <EmptyState title="No strength volume yet" description="Strength entries with sets, reps, and weight will populate this chart." action="Open Training" onAction={() => undefined} />
          )}
        </Card>
      </div>
      <WorkoutHistory workouts={workoutHistory} onImportHevy={() => undefined} defaultExpanded metadata="Training history" />
      <StrengthTrendsSection
        strength={strength}
        selectedExercise={selectedExercise}
        setSelectedExercise={setSelectedExercise}
        trendView={trendView}
        setTrendView={setTrendView}
        selectedMuscleGroup={selectedMuscleGroup}
        setSelectedMuscleGroup={setSelectedMuscleGroup}
        trendDateRange={trendDateRange}
        setTrendDateRange={setTrendDateRange}
        muscleTrendMetric={muscleTrendMetric}
        setMuscleTrendMetric={setMuscleTrendMetric}
      />
    </div>
  );
}

function SettingsPage({
  settings,
  forms,
  setForms,
  onSubmit,
  onConnectStrava,
  onTestOpenAI,
}: Readonly<{
  settings: SettingsData | null;
  forms: FormState;
  setForms: React.Dispatch<React.SetStateAction<FormState>>;
  onSubmit: (event: FormEvent) => void;
  onConnectStrava: () => void;
  onTestOpenAI: () => void;
}>) {
  return (
    <div className="space-y-4">
      <Card>
        <SectionHeader eyebrow="Integrations" title="API keys and local connection info" />
        <form onSubmit={onSubmit} className="grid gap-4 md:grid-cols-2">
          {Object.entries(integrationLabels).map(([key, label]) => (
            <TextInput
              key={key}
              label={`${label} (${settings?.statuses[key] ?? "Not configured"})`}
              type={key.includes("secret") || key.includes("key") ? "password" : "text"}
              value={forms.settings[key] ?? ""}
              placeholder={settings?.integrations[key] ?? "Leave blank if not configured"}
              onChange={(value) => setForms((state) => ({ ...state, settings: { ...state.settings, [key]: value } }))}
            />
          ))}
          <button className="h-11 rounded-lg bg-cyan-300 text-sm font-semibold text-zinc-950 md:col-span-2">Save settings locally</button>
        </form>
      </Card>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <SectionHeader eyebrow="Strava" title="OAuth connection" />
          <p className="text-sm text-zinc-400">Status: <span className="text-cyan-200">{settings?.statuses.strava ?? "Not configured"}</span></p>
          <button onClick={onConnectStrava} className="mt-4 h-11 rounded-lg bg-orange-300 px-4 text-sm font-semibold text-zinc-950">
            Connect Strava
          </button>
          <p className="mt-3 text-xs text-zinc-500">Uses OAuth2 scopes: read and activity:read_all. Tokens are stored locally and never displayed.</p>
        </Card>
        <Card>
          <SectionHeader eyebrow="OpenAI" title="Food parser" />
          <p className="text-sm text-zinc-400">Status: <span className="text-cyan-200">{settings?.statuses.openai_api_key ?? "Not configured"}</span></p>
          <button onClick={onTestOpenAI} className="mt-4 h-11 rounded-lg bg-violet-300 px-4 text-sm font-semibold text-zinc-950">
            Test OpenAI Food Parser
          </button>
          <p className="mt-3 text-xs text-zinc-500">Uses OPENAI_API_KEY from settings, environment, or `.env`.</p>
        </Card>
        <Card>
          <SectionHeader eyebrow="Fitbit / Google Health" title="Wearable recovery" />
          <p className="text-sm text-zinc-400">Status: <span className="text-cyan-200">{settings?.statuses.fitbit_google_health ?? "Not configured"}</span></p>
          <p className="mt-3 text-xs leading-5 text-zinc-500">Prepared for sleep, HRV, resting HR, and recovery trend ingestion. Full OAuth sync is not implemented yet.</p>
        </Card>
        <Card>
          <SectionHeader eyebrow="Apple Health" title="Local upload only" />
          <p className="text-sm leading-6 text-zinc-400">
            Apple Health stays file-upload based for the web MVP. HealthKit requires an iOS app and explicit user permissions; future web support should parse exported ZIP/XML data first.
          </p>
        </Card>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Object.entries(integrationLabels).map(([key, label]) => (
          <Card key={key}>
            <p className="font-semibold text-white">{label}</p>
            <p className="mt-2 text-sm text-zinc-400">Saved value: {settings?.integrations[key] ?? "Not configured"}</p>
            <p className="mt-3 inline-flex rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-cyan-200">{settings?.statuses[key] ?? "Not configured"}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}

function DataTable({ rows }: Readonly<{ rows: Array<Record<string, unknown>> }>) {
  const columns = Object.keys(rows[0] ?? {});
  return (
    <div className="min-w-0 overflow-x-auto rounded-lg border border-white/10">
      <table className="min-w-full divide-y divide-white/10 text-sm">
        <thead className="sticky top-0 bg-white/[0.04] text-left text-zinc-400">
          <tr>
            {columns.map((column) => (
              <th key={column} className="px-3 py-2 font-medium">
                {column.replaceAll("_", " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-white/10">
          {rows.map((row, index) => (
            <tr key={index} className="text-zinc-200">
              {columns.map((column) => (
                <td key={column} className="px-3 py-2">
                  {row[column] === null || row[column] === undefined || row[column] === "" ? "—" : String(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatSleepDuration(minutes?: number | null) {
  if (!minutes || minutes <= 0) return "No data";
  const hours = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);
  return `${hours}h ${mins.toString().padStart(2, "0")}m`;
}

function sleepClockHour(value: string) {
  if (!value) return null;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return null;
  return date.getHours() + date.getMinutes() / 60;
}

export default function Home() {
  const [activePage, setActivePage] = useState<PageId>("dashboard");
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [nutritionLogs, setNutritionLogs] = useState<NutritionEntry[]>([]);
  const [nutritionHistory, setNutritionHistory] = useState<DailyNutritionSummary[]>([]);
  const [nutritionAdherence, setNutritionAdherence] = useState<NutritionAdherence | null>(null);
  const [shortcutData, setShortcutData] = useState<NutritionShortcutData>({ items: [], frequent_foods: [], meal_templates: [] });
  const [shortcutSuggestion, setShortcutSuggestion] = useState<{ type: "shortcut" | "template" | "frequent"; label: string; id: string } | null>(null);
  const [forceAiParse, setForceAiParse] = useState(false);
  const [bodyMetrics, setBodyMetrics] = useState<BodyMetricEntry[]>([]);
  const [recoveryLogs, setRecoveryLogs] = useState<RecoveryEntry[]>([]);
  const [sleepEntries, setSleepEntries] = useState<SleepEntry[]>([]);
  const [workoutHistory, setWorkoutHistory] = useState<WorkoutGroup[]>([]);
  const [strengthTrends, setStrengthTrends] = useState<StrengthTrendResponse | null>(null);
  const [selectedExercise, setSelectedExercise] = useState("");
  const [trendView, setTrendView] = useState<"exercise" | "muscle_group">("exercise");
  const [selectedMuscleGroup, setSelectedMuscleGroup] = useState("");
  const [trendDateRange, setTrendDateRange] = useState("12w");
  const [muscleTrendMetric, setMuscleTrendMetric] = useState<keyof Pick<MuscleGroupTrendHistory, "strength_index" | "weekly_volume" | "hard_sets" | "total_reps" | "best_estimated_1rm">>("strength_index");
  const [trainingInsight, setTrainingInsight] = useState<TrainingInsight | null>(null);
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [forms, setForms] = useState<FormState>(initialForms);
  const [aiText, setAiText] = useState("");
  const [parsedFoods, setParsedFoods] = useState<ParsedFood[]>([]);
  const [parseResult, setParseResult] = useState<FoodParseResponse | null>(null);
  const [parseLoading, setParseLoading] = useState(false);
  const [manualFoodMode, setManualFoodMode] = useState<"direct" | "serving">("direct");
  const [servingForm, setServingForm] = useState<ServingScaleForm>({
    food_name: "",
    serving_size_grams: 56,
    calories_per_serving: 0,
    protein_per_serving: 0,
    carbs_per_serving: 0,
    fat_per_serving: 0,
    fiber_per_serving: "",
    sodium_per_serving: "",
    potassium_per_serving: "",
    grams_consumed: 56,
    source_label_file: "",
  });
  const [labelUploadResult, setLabelUploadResult] = useState<LabelUploadResult | null>(null);
  const [manualFoodSaving, setManualFoodSaving] = useState(false);
  const [manualFoodError, setManualFoodError] = useState<string | null>(null);
  const [hevyPreview, setHevyPreview] = useState<HevyPreview | null>(null);
  const [hevySync, setHevySync] = useState<HevySyncStatus | null>(null);
  const [hevySyncing, setHevySyncing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const hevyAutoSyncRef = useRef(false);

  const currentPage = navigation.find((item) => item.id === activePage) ?? navigation[0];
  const strengthTrendPath = useCallback((exercise = selectedExercise) => {
    const params = new URLSearchParams();
    if (exercise) {
      params.set("exercise_name", exercise);
    }
    params.set("date_range", trendDateRange);
    if (selectedMuscleGroup) {
      params.set("muscle_group", selectedMuscleGroup);
    }
    return `/api/training/strength-trends?${params.toString()}`;
  }, [selectedExercise, selectedMuscleGroup, trendDateRange]);

  const refreshAll = useCallback(async () => {
    try {
      setApiError(null);
      const [dashboardData, goalsData, nutritionData, nutritionHistoryData, shortcutResponse, bodyData, recoveryData, sleepData, historyData, strengthData, settingsData, hevySyncData] = await Promise.all([
        apiGet<DashboardData>("/api/dashboard"),
        apiGet<{ goals: Goals; targets: Targets; weight_feedback: WeightFeedback; lean_bulk_decision: LeanBulkDecision; adaptive_recommendation: AdaptiveNutritionRecommendation }>("/api/goals"),
        apiGet<{ items: NutritionEntry[] }>("/api/nutrition/logs"),
        apiGet<{ items: DailyNutritionSummary[]; adherence: NutritionAdherence }>("/api/nutrition/history"),
        apiGet<NutritionShortcutData>("/api/nutrition/shortcuts"),
        apiGet<{ items: BodyMetricEntry[] }>("/api/body-metrics"),
        apiGet<{ items: RecoveryEntry[] }>("/api/recovery/logs"),
        apiGet<{ items: SleepEntry[] }>("/api/recovery/sleep"),
        apiGet<{ items: WorkoutGroup[] }>("/api/training/history"),
        apiGet<StrengthTrendResponse>(strengthTrendPath()),
        apiGet<SettingsData>("/api/settings"),
        apiGet<HevySyncStatus>("/api/training/sync/hevy/status"),
      ]);
      setDashboard(dashboardData);
      setNutritionLogs(nutritionData.items);
      setNutritionHistory(nutritionHistoryData.items);
      setNutritionAdherence(nutritionHistoryData.adherence);
      setShortcutData(shortcutResponse);
      setBodyMetrics(bodyData.items);
      setRecoveryLogs(recoveryData.items);
      setSleepEntries(sleepData.items);
      setWorkoutHistory(historyData.items);
      setStrengthTrends(strengthData);
      setSelectedExercise((current) => current || strengthData.selected_exercise || strengthData.exercise_options[0] || "");
      setSettings(settingsData);
      setHevySync(hevySyncData);
      setForms((state) => ({ ...state, goals: goalsData.goals }));
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Unable to reach FastAPI backend.");
    } finally {
      setLoading(false);
    }
  }, [strengthTrendPath]);

  useEffect(() => {
    const id = window.setTimeout(() => {
      void refreshAll();
    }, 0);
    return () => window.clearTimeout(id);
  }, [refreshAll]);

  const submitAndRefresh = async (event: FormEvent, action: () => Promise<void>, success: string) => {
    event.preventDefault();
    setMessage(null);
    setApiError(null);
    try {
      await action();
      setMessage(success);
      await refreshAll();
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Save failed.");
    }
  };

  const updateSelectedExercise = (exercise: string) => {
    setSelectedExercise(exercise);
    void apiGet<StrengthTrendResponse>(strengthTrendPath(exercise))
      .then(setStrengthTrends)
      .catch((error) => setApiError(error instanceof Error ? error.message : "Unable to load strength trend."));
  };

  const syncHevyNow = useCallback(async (showMessage = true) => {
    setHevySyncing(true);
    setApiError(null);
    if (showMessage) {
      setMessage(null);
    }
    try {
      const result = await apiSend<HevySyncResult>("/api/training/sync/hevy", "POST", {});
      if (result.status === "error") {
        throw new Error(result.message ?? "Hevy sync failed.");
      }
      setHevySync({
        last_synced_at: result.last_synced_at,
        last_error: result.failures?.join(" ") ?? "",
        last_result: result as unknown as Record<string, unknown>,
      });
      if (showMessage) {
        const failureText = result.failures?.length ? ` ${result.failures.length} failures.` : "";
        setMessage(`Hevy sync complete: ${result.saved_workouts} workouts updated, ${result.deleted_rows} rows deleted.${failureText}`);
      }
      await refreshAll();
    } catch (error) {
      const messageText = error instanceof Error ? error.message : "Hevy sync failed.";
      setApiError(messageText);
      setHevySync((state) => ({
        last_synced_at: state?.last_synced_at ?? "",
        last_error: messageText,
        last_result: state?.last_result ?? {},
      }));
    } finally {
      setHevySyncing(false);
    }
  }, [refreshAll]);

  useEffect(() => {
    if (hevyAutoSyncStarted || hevyAutoSyncRef.current || (activePage !== "dashboard" && activePage !== "training")) {
      return;
    }
    hevyAutoSyncStarted = true;
    hevyAutoSyncRef.current = true;
    void syncHevyNow(false);
  }, [activePage, syncHevyNow]);

  const validateNutritionForm = () => {
    const entry = forms.nutrition;
    if (!entry.food_name.trim()) {
      return "Food name is required.";
    }
    for (const key of ["calories", "protein", "carbs", "fat"] as const) {
      const value = Number(entry[key]);
      if (!Number.isFinite(value) || value < 0) {
        return `${key.replace("_", " ")} must be a number greater than or equal to 0.`;
      }
    }
    return null;
  };

  const validateServingForm = () => {
    if (!servingForm.food_name.trim()) {
      return "Food name is required.";
    }
    if (!Number.isFinite(Number(servingForm.serving_size_grams)) || Number(servingForm.serving_size_grams) <= 0) {
      return "Serving size in grams must be greater than 0.";
    }
    if (!Number.isFinite(Number(servingForm.grams_consumed)) || Number(servingForm.grams_consumed) <= 0) {
      return "Grams consumed must be greater than 0.";
    }
    for (const key of ["calories_per_serving", "protein_per_serving", "carbs_per_serving", "fat_per_serving"] as const) {
      const value = Number(servingForm[key]);
      if (!Number.isFinite(value) || value < 0) {
        return `${key.replaceAll("_", " ")} must be a number greater than or equal to 0.`;
      }
    }
    for (const key of ["fiber_per_serving", "sodium_per_serving", "potassium_per_serving"] as const) {
      if (servingForm[key] !== "" && (!Number.isFinite(Number(servingForm[key])) || Number(servingForm[key]) < 0)) {
        return `${key.replaceAll("_", " ")} must be blank or greater than or equal to 0.`;
      }
    }
    return null;
  };

  const parsedFoodTotals = () => parsedFoods.reduce(
    (totals, food) => ({
      calories: totals.calories + (Number(food.calories) || 0),
      protein: totals.protein + (Number(food.protein) || 0),
      carbs: totals.carbs + (Number(food.carbs) || 0),
      fat: totals.fat + (Number(food.fat) || 0),
    }),
    { calories: 0, protein: 0, carbs: 0, fat: 0 },
  );

  const draftFromAnalyzeItem = (item: FoodAnalyzeResponse["items"][number]): ParsedFood => ({
    food_name: item.name,
    original_text: item.original_text,
    quantity: item.quantity === null || item.quantity === undefined ? "" : String(item.quantity),
    quantity_value: item.quantity,
    unit: item.unit,
    serving_description: item.serving_description,
    calories: item.calories,
    protein: item.protein_g,
    carbs: item.carbs_g,
    fat: item.fat_g,
    fiber: item.fiber_g,
    sugar: item.sugar_g,
    sodium: item.sodium_mg,
    confidence: item.confidence,
    source: item.source,
    source_id: item.source_id,
    source_url: item.source_url ?? "",
    assumptions: item.assumptions,
    needs_review: item.needs_review,
    verification_needed: item.needs_review,
    verification_reason: item.assumptions.join(" "),
    verification_status: item.needs_review ? "review_required" : "ready",
    notes: item.assumptions.join(" ") || "Review before saving.",
  });

  const parsedShortcutName = () => {
    const cleanText = aiText.trim();
    if (cleanText) {
      return cleanText.length > 80 ? cleanText.slice(0, 80) : cleanText;
    }
    return parsedFoods.length === 1 ? parsedFoods[0].food_name : "AI parsed meal";
  };

  const saveParsedShortcut = async () => {
    if (!parsedFoods.length) {
      throw new Error("Parse food before saving a shortcut.");
    }
    const totals = parsedFoodTotals();
    await apiSend("/api/nutrition/shortcuts", "POST", {
      shortcut_name: parsedShortcutName(),
      ...totals,
      notes: parsedFoods.map((food) => food.quantity ? `${food.quantity} ${food.food_name}` : food.food_name).join(", "),
      source: "ai_parse",
    });
  };

  const saveParsedMealTemplate = async () => {
    if (!parsedFoods.length) {
      throw new Error("Parse food before saving a meal template.");
    }
    await apiSend("/api/nutrition/meal-templates", "POST", {
      template_name: parsedShortcutName(),
      default_meal_type: DEFAULT_MEAL_TYPE,
      foods: parsedFoods.map((food) => ({
        food_name: food.quantity ? `${food.quantity} ${food.food_name}` : food.food_name,
        calories: Number(food.calories) || 0,
        protein: Number(food.protein) || 0,
        carbs: Number(food.carbs) || 0,
        fat: Number(food.fat) || 0,
        notes: food.notes || "",
        source: "ai_parse",
      })),
    });
  };

  const saveParsedFoodsToToday = async () => {
    await apiSend("/api/food/log-bulk", "POST", {
      date: forms.nutrition.date,
      meal_type: DEFAULT_MEAL_TYPE,
      items: parsedFoods.map((food) => ({
        name: food.food_name,
        original_text: food.original_text ?? food.food_name,
        quantity: food.quantity_value ?? null,
        unit: food.unit ?? "",
        serving_description: food.serving_description ?? food.quantity ?? "",
        calories: Number(food.calories) || 0,
        protein_g: Number(food.protein) || 0,
        carbs_g: Number(food.carbs) || 0,
        fat_g: Number(food.fat) || 0,
        fiber_g: food.fiber ?? null,
        sugar_g: food.sugar ?? null,
        sodium_mg: food.sodium ?? null,
        confidence: food.confidence || "medium",
        source: food.source || "openai_estimate",
        source_id: food.source_id ?? null,
        source_url: food.source_url || null,
        assumptions: food.assumptions ?? [],
        needs_review: false,
      })),
    });
  };

  const editBenchPr = () => {
    const bench = dashboard?.prs.bench_press;
    setForms((state) => ({
      ...state,
      benchPr: {
        weight: bench?.value ?? state.benchPr.weight,
        reps: bench?.reps ?? state.benchPr.reps,
        date: bench?.date ?? state.benchPr.date,
        notes: bench?.notes ?? "",
        editing: true,
      },
    }));
  };

  const editMilePr = () => {
    const mile = dashboard?.prs.mile_time;
    const valueSeconds = mile?.value_seconds ?? stateSafeMileSeconds(forms.milePr);
    setForms((state) => ({
      ...state,
      milePr: {
        minutes: Math.floor(valueSeconds / 60),
        seconds: valueSeconds % 60,
        date: mile?.date ?? state.milePr.date,
        notes: mile?.notes ?? "",
        editing: true,
      },
    }));
  };

  const pageContent = {
    dashboard: (
      <Dashboard
        data={dashboard}
        setActivePage={setActivePage}
        forms={forms}
        setForms={setForms}
        onEditBenchPr={editBenchPr}
        onEditMilePr={editMilePr}
        onSaveBenchPr={(event) =>
          submitAndRefresh(event, async () => {
            if (!forms.benchPr.weight || forms.benchPr.weight <= 0) throw new Error("Bench weight must be greater than 0.");
            if (!forms.benchPr.reps || forms.benchPr.reps <= 0) throw new Error("Bench reps must be greater than 0.");
            await apiSend("/api/personal-records/bench", "PUT", {
              weight: Number(forms.benchPr.weight),
              reps: Number(forms.benchPr.reps),
              date: forms.benchPr.date,
              notes: forms.benchPr.notes,
            });
            setForms((state) => ({ ...state, benchPr: { ...state.benchPr, editing: false } }));
          }, "Bench PR saved.")
        }
        onSaveMilePr={(event) =>
          submitAndRefresh(event, async () => {
            const totalSeconds = stateSafeMileSeconds(forms.milePr);
            if (totalSeconds <= 0) throw new Error("Mile time must be greater than 0.");
            await apiSend("/api/personal-records/mile", "PUT", {
              minutes: Number(forms.milePr.minutes) || 0,
              seconds: Number(forms.milePr.seconds) || 0,
              date: forms.milePr.date,
              notes: forms.milePr.notes,
            });
            setForms((state) => ({ ...state, milePr: { ...state.milePr, editing: false } }));
          }, "Mile PR saved.")
        }
        onRecalculatePrs={() =>
          void submitAndRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            await apiSend("/api/personal-records/recalculate", "POST", {});
          }, "PRs recalculated from logs.")
        }
      />
    ),
    food: (
      <FoodPage
        logs={nutritionLogs}
        targets={dashboard?.targets ?? null}
        nutritionHistory={nutritionHistory}
        nutritionAdherence={nutritionAdherence}
        shortcuts={shortcutData.items}
        mealTemplates={shortcutData.meal_templates}
        forms={forms}
        setForms={setForms}
        manualFoodMode={manualFoodMode}
        setManualFoodMode={setManualFoodMode}
        servingForm={servingForm}
        setServingForm={setServingForm}
        servingPreview={calculateServingPreview(servingForm)}
        labelUploadResult={labelUploadResult}
        onLabelUpload={(file) => {
          void submitAndRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            const formData = new FormData();
            formData.append("file", file);
            const result = await apiUpload<LabelUploadResult>("/api/nutrition/label-upload", formData);
            setLabelUploadResult(result);
            setServingForm((state) => ({ ...state, source_label_file: result.path }));
          }, "Nutrition label uploaded.")
        }}
        onSaveServingShortcut={() =>
          void submitAndRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            const validationError = validateServingForm();
            if (validationError) throw new Error(validationError);
            const preview = calculateServingPreview(servingForm);
            await apiSend("/api/nutrition/shortcuts", "POST", {
              shortcut_name: servingForm.food_name.trim(),
              calories: preview.calories,
              protein: preview.protein,
              carbs: preview.carbs,
              fat: preview.fat,
              fiber: preview.fiber,
              sodium: preview.sodium,
              potassium: preview.potassium,
              serving_size_grams: servingForm.serving_size_grams,
              default_grams_consumed: servingForm.grams_consumed,
              calories_per_serving: servingForm.calories_per_serving,
              protein_per_serving: servingForm.protein_per_serving,
              carbs_per_serving: servingForm.carbs_per_serving,
              fat_per_serving: servingForm.fat_per_serving,
              notes: servingForm.source_label_file ? `Label: ${servingForm.source_label_file}` : "Serving-scaled shortcut",
              source: "manual_serving_scale",
            });
          }, "Serving-scaled food saved as shortcut.")
        }
        aiText={aiText}
        setAiText={setAiText}
        parsedFoods={parsedFoods}
        setParsedFoods={setParsedFoods}
        parseLoading={parseLoading}
        parseResult={parseResult}
        manualSaving={manualFoodSaving}
        manualError={manualFoodError}
        shortcutSuggestion={shortcutSuggestion}
        onUseSuggestion={() => {
          if (!shortcutSuggestion) return;
          void submitAndRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            const path = shortcutSuggestion.type === "shortcut"
              ? `/api/nutrition/shortcuts/${shortcutSuggestion.id}/log`
              : shortcutSuggestion.type === "frequent"
                ? `/api/nutrition/frequent-foods/${encodeURIComponent(shortcutSuggestion.id)}/log`
                : `/api/nutrition/meal-templates/${encodeURIComponent(shortcutSuggestion.id)}/log`;
            await apiSend(path, "POST", {
              date: forms.nutrition.date,
              meal_type: DEFAULT_MEAL_TYPE,
            });
            setShortcutSuggestion(null);
          }, `Saved ${shortcutSuggestion.type} logged.`);
        }}
        onParseAnyway={() => {
          setForceAiParse(true);
          setShortcutSuggestion(null);
        }}
        onParseFood={(event) =>
          submitAndRefresh(event, async () => {
            const savedMatch = findSavedFoodMatch(aiText, shortcutData.items, shortcutData.meal_templates, shortcutData.frequent_foods);
            if (savedMatch && !forceAiParse) {
              setShortcutSuggestion(savedMatch);
              throw new Error("Saved shortcut found. Use it or choose Parse new anyway.");
            }
            setForceAiParse(false);
            setShortcutSuggestion(null);
            setParseLoading(true);
            if (aiText.trim().length > 4000) {
              throw new Error("Food text must be 4,000 characters or fewer.");
            }
            const analyzed = await apiSend<FoodAnalyzeResponse>("/api/food/analyze-text", "POST", { date: forms.nutrition.date, text: aiText });
            setParseResult({
              foods: analyzed.items.map(draftFromAnalyzeItem),
              total: {
                calories: analyzed.totals.calories,
                protein: analyzed.totals.protein_g,
                carbs: analyzed.totals.carbs_g,
                fat: analyzed.totals.fat_g,
              },
              source: "food_analyze_text",
              cached: false,
              success: analyzed.success,
              error_code: analyzed.error_code,
              message: [analyzed.message, ...analyzed.warnings].filter(Boolean).join(" "),
              debug: analyzed.debug,
            });
            setParsedFoods(analyzed.items.map(draftFromAnalyzeItem));
            if (!analyzed.success) {
              throw new Error(analyzed.message || "Food analysis failed.");
            }
          }, "Food text parsed. Review before saving.").finally(() => setParseLoading(false))
        }
        onSaveParsedFoods={(event) =>
          submitAndRefresh(event, async () => {
            await saveParsedFoodsToToday();
            setParsedFoods([]);
            setParseResult(null);
            setAiText("");
          }, "Confirmed parsed food entries saved.")
        }
        onSaveShortcut={(event) =>
          submitAndRefresh(event, async () => {
            await saveParsedShortcut();
          }, "Saved AI parse as a food shortcut.")
        }
        onSaveMealTemplate={(event) =>
          submitAndRefresh(event, async () => {
            await saveParsedMealTemplate();
          }, "Saved AI parse as a meal template.")
        }
        onSaveAndLogToday={(event) =>
          submitAndRefresh(event, async () => {
            await saveParsedShortcut();
            await saveParsedMealTemplate();
            await saveParsedFoodsToToday();
            setParsedFoods([]);
            setParseResult(null);
            setAiText("");
          }, "Saved shortcut/template and logged food today.")
        }
        onLogShortcut={(shortcutId) =>
          void submitAndRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            await apiSend(`/api/nutrition/shortcuts/${shortcutId}/log`, "POST", {
              date: forms.nutrition.date,
              meal_type: DEFAULT_MEAL_TYPE,
            });
          }, "Shortcut logged.")
        }
        onUpdateShortcut={(shortcut) =>
          void submitAndRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            await apiSend(`/api/nutrition/shortcuts/${shortcut.shortcut_id}`, "PUT", {
              shortcut_name: shortcut.shortcut_name,
              calories: Number(shortcut.calories) || 0,
              protein: Number(shortcut.protein) || 0,
              carbs: Number(shortcut.carbs) || 0,
              fat: Number(shortcut.fat) || 0,
              fiber: shortcut.fiber,
              sodium: shortcut.sodium,
              potassium: shortcut.potassium,
              notes: shortcut.notes,
              source: shortcut.source || "manual",
            });
          }, "Shortcut updated.")
        }
        onDeleteShortcut={(shortcutId) =>
          void submitAndRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            await apiDelete(`/api/nutrition/shortcuts/${shortcutId}`);
          }, "Shortcut deleted.")
        }
        onLogMealTemplate={(templateName) =>
          submitAndRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            await apiSend(`/api/nutrition/meal-templates/${encodeURIComponent(templateName)}/log`, "POST", {
              date: forms.nutrition.date || todayString(),
              meal_type: DEFAULT_MEAL_TYPE,
            });
          }, "Meal template added to log.")
        }
        onRenameMealTemplate={(templateName, nextName) =>
          submitAndRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            await apiSend(`/api/nutrition/meal-templates/${encodeURIComponent(templateName)}`, "PUT", {
              template_name: nextName,
            });
          }, "Meal template renamed.")
        }
        onSubmit={(event) =>
          submitAndRefresh(event, async () => {
            setManualFoodError(null);
            if (manualFoodMode === "serving") {
              const validationError = validateServingForm();
              if (validationError) {
                setManualFoodError(validationError);
                throw new Error(validationError);
              }
              const preview = calculateServingPreview(servingForm);
              setManualFoodSaving(true);
              try {
                await apiSend("/api/nutrition/logs", "POST", {
                  date: forms.nutrition.date,
                  meal_type: DEFAULT_MEAL_TYPE,
                  food_name: servingForm.food_name.trim(),
                  calories: preview.calories,
                  protein: preview.protein,
                  carbs: preview.carbs,
                  fat: preview.fat,
                  serving_size_grams: servingForm.serving_size_grams,
                  grams_consumed: servingForm.grams_consumed,
                  serving_multiplier: preview.multiplier,
                  calories_per_serving: servingForm.calories_per_serving,
                  protein_per_serving: servingForm.protein_per_serving,
                  carbs_per_serving: servingForm.carbs_per_serving,
                  fat_per_serving: servingForm.fat_per_serving,
                  fiber: preview.fiber,
                  sodium: preview.sodium,
                  potassium: preview.potassium,
                  source_label_file: servingForm.source_label_file,
                });
                setServingForm((state) => ({
                  ...state,
                  food_name: "",
                  calories_per_serving: 0,
                  protein_per_serving: 0,
                  carbs_per_serving: 0,
                  fat_per_serving: 0,
                  fiber_per_serving: "",
                  sodium_per_serving: "",
                  potassium_per_serving: "",
                  source_label_file: "",
                }));
                setLabelUploadResult(null);
              } finally {
                setManualFoodSaving(false);
              }
              return;
            }
            const validationError = validateNutritionForm();
            if (validationError) {
              setManualFoodError(validationError);
              throw new Error(validationError);
            }
            setManualFoodSaving(true);
            try {
              await apiSend("/api/nutrition/logs", "POST", {
                ...forms.nutrition,
                meal_type: DEFAULT_MEAL_TYPE,
                food_name: forms.nutrition.food_name.trim(),
                calories: Number(forms.nutrition.calories),
                protein: Number(forms.nutrition.protein),
                carbs: Number(forms.nutrition.carbs),
                fat: Number(forms.nutrition.fat),
              });
              setForms((state) => ({
                ...state,
                nutrition: {
                  ...state.nutrition,
                  food_name: "",
                  calories: 0,
                  protein: 0,
                  carbs: 0,
                  fat: 0,
                },
              }));
            } finally {
              setManualFoodSaving(false);
            }
          }, "Food entry saved.")
        }
      />
    ),
    goals: (
      <GoalsPage
        goals={dashboard?.goals ?? null}
        targets={dashboard?.targets ?? null}
        weightFeedback={dashboard?.weight_feedback ?? null}
        leanBulkDecision={dashboard?.lean_bulk_decision ?? null}
        adaptiveRecommendation={dashboard?.adaptive_recommendation ?? null}
        onApplySuggestedMacros={() =>
          void submitAndRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            await apiSend("/api/goals/apply-suggested-macros", "POST", {});
          }, "Suggested macros applied.")
        }
      />
    ),
    recovery: (
      <RecoveryPage
        bodyMetrics={bodyMetrics}
        recoveryLogs={recoveryLogs}
        sleepEntries={sleepEntries}
        forms={forms}
        setForms={setForms}
        onBodySubmit={(event) =>
          submitAndRefresh(event, async () => {
            await apiSend("/api/body-metrics", "POST", forms.body);
            setForms((state) => ({ ...state, body: { ...initialForms.body, date: todayString() } }));
          }, "Bodyweight entry saved.")
        }
        onRecoverySubmit={(event) =>
          submitAndRefresh(event, async () => {
            await apiSend("/api/recovery/logs", "POST", forms.recovery);
            setForms((state) => ({ ...state, recovery: { ...initialForms.recovery, date: todayString() } }));
          }, "Recovery check-in saved.")
        }
      />
    ),
    training: (
      <TrainingPage
        workoutHistory={workoutHistory}
        strength={strengthTrends}
        selectedExercise={selectedExercise}
        setSelectedExercise={updateSelectedExercise}
        trainingInsight={trainingInsight}
        hevyPreview={hevyPreview}
        hevySync={hevySync}
        hevySyncing={hevySyncing}
        trendView={trendView}
        setTrendView={setTrendView}
        selectedMuscleGroup={selectedMuscleGroup}
        setSelectedMuscleGroup={setSelectedMuscleGroup}
        trendDateRange={trendDateRange}
        setTrendDateRange={setTrendDateRange}
        muscleTrendMetric={muscleTrendMetric}
        setMuscleTrendMetric={setMuscleTrendMetric}
        onSyncHevy={() => {
          void syncHevyNow(true);
        }}
        onPreviewHevy={() => {
          void submitAndRefresh(
            { preventDefault: () => undefined } as FormEvent,
            async () => {
              const result = await apiSend<{
                status: string;
                message?: string;
                workouts: HevyPreviewWorkout[];
                estimated_rows: number;
                duplicates_detected: number;
                debug_file?: string;
                warnings: string[];
              }>("/api/training/import/hevy/preview", "POST", { page_size: 10, pages: 1 });
              if (result.status === "error") {
                throw new Error(result.message ?? "Hevy preview failed.");
              }
              setHevyPreview(result);
            },
            "Hevy preview loaded. Confirm to save rows.",
          );
        }}
        onConfirmHevy={() => {
          void submitAndRefresh(
            { preventDefault: () => undefined } as FormEvent,
            async () => {
              const result = await apiSend<{
                status: string;
                message?: string;
                imported_workouts: number;
                imported_rows: number;
                skipped_duplicates: number;
                failures?: string[];
                last_synced_at?: string;
              }>("/api/training/import/hevy", "POST", { page_size: 10, pages: 1 });
              if (result.status === "error") {
                throw new Error(result.message ?? "Hevy import failed.");
              }
              setHevyPreview(null);
              setHevySync({
                last_synced_at: result.last_synced_at ?? "",
                last_error: result.failures?.join(" ") ?? "",
                last_result: result as unknown as Record<string, unknown>,
              });
              const failureText = result.failures?.length ? ` ${result.failures.length} failures.` : "";
              setMessage(`Imported ${result.imported_workouts} Hevy workouts (${result.imported_rows} rows). Skipped ${result.skipped_duplicates} duplicates.${failureText}`);
            },
            "Hevy import complete.",
          );
        }}
        onCancelHevy={() => setHevyPreview(null)}
        onAnalyzeTraining={() => {
          void submitAndRefresh(
            { preventDefault: () => undefined } as FormEvent,
            async () => {
              const result = await apiSend<TrainingInsight>("/api/training/ai/insights", "POST", { exercise_name: selectedExercise });
              setTrainingInsight(result);
              if (!result.success) {
                throw new Error(result.message || "AI training analysis failed.");
              }
            },
            "AI training analysis complete.",
          );
        }}
        onImportStrava={() => {
          void submitAndRefresh(
            { preventDefault: () => undefined } as FormEvent,
            async () => {
              const result = await apiSend<{ status: string; message?: string; imported_runs: number; skipped_duplicates: number }>("/api/training/import/strava", "POST", { per_page: 30 });
              if (result.status === "error") {
                throw new Error(result.message ?? "Strava import failed.");
              }
              setMessage(`Imported ${result.imported_runs} Strava runs. Skipped ${result.skipped_duplicates} duplicates.`);
            },
            "Strava import complete.",
          );
        }}
      />
    ),
    history: (
      <HistoryPage
        nutritionLogs={nutritionLogs}
        nutritionHistory={nutritionHistory}
        nutritionAdherence={nutritionAdherence}
        bodyMetrics={bodyMetrics}
        recoveryTrend={dashboard?.recovery_trend ?? []}
        trainingVolume={dashboard?.training_volume ?? []}
        workoutHistory={workoutHistory}
        strength={strengthTrends}
        selectedExercise={selectedExercise}
        setSelectedExercise={updateSelectedExercise}
        trendView={trendView}
        setTrendView={setTrendView}
        selectedMuscleGroup={selectedMuscleGroup}
        setSelectedMuscleGroup={setSelectedMuscleGroup}
        trendDateRange={trendDateRange}
        setTrendDateRange={setTrendDateRange}
        muscleTrendMetric={muscleTrendMetric}
        setMuscleTrendMetric={setMuscleTrendMetric}
      />
    ),
    settings: (
      <SettingsPage
        settings={settings}
        forms={forms}
        setForms={setForms}
        onConnectStrava={async () => {
          setApiError(null);
          setMessage(null);
          try {
            const result = await apiGet<{ status: string; message?: string; auth_url: string }>("/api/integrations/strava/auth-url");
            if (result.status !== "ok" || !result.auth_url) {
              throw new Error(result.message ?? "Unable to generate Strava authorization URL.");
            }
            window.location.href = result.auth_url;
          } catch (error) {
            setApiError(error instanceof Error ? error.message : "Unable to connect Strava.");
          }
        }}
        onTestOpenAI={async () => {
          setApiError(null);
          setMessage(null);
          try {
            const parsed = await apiSend<FoodParseResponse>("/api/nutrition/ai/parse", "POST", { text: "3 eggs, protein shake, banana" });
            if (!parsed.foods.length) {
              throw new Error(parsed.message || "Parser returned no foods.");
            }
            setMessage(`OpenAI parser returned ${parsed.foods.length} editable food item(s). Source: ${parsed.source}.`);
          } catch (error) {
            setApiError(error instanceof Error ? error.message : "OpenAI parser test failed.");
          }
        }}
        onSubmit={(event) =>
          submitAndRefresh(event, async () => {
            const updated = await apiSend<SettingsData>("/api/settings", "PUT", { integrations: forms.settings });
            setSettings(updated);
            setForms((state) => ({ ...state, settings: {} }));
          }, "Settings saved locally.")
        }
      />
    ),
  };

  return (
    <main className="min-h-screen bg-[#07080b] text-zinc-100">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_top_left,rgba(45,212,191,0.16),transparent_30%),radial-gradient(circle_at_top_right,rgba(96,165,250,0.11),transparent_28%),linear-gradient(180deg,rgba(255,255,255,0.04),transparent_40%)]" />
      <div className="relative flex min-h-screen">
        <aside className="sticky top-0 hidden h-screen w-72 shrink-0 border-r border-white/10 bg-black/35 p-5 backdrop-blur-xl lg:block">
          <div className="mb-8 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-300 text-zinc-950">
              <Activity className="h-5 w-5" />
            </div>
            <div>
              <p className="font-semibold text-white">Performance OS</p>
              <p className="text-xs text-zinc-500">Local-first dashboard</p>
            </div>
          </div>
          <nav className="space-y-2">
            {navigation.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.id}
                  onClick={() => setActivePage(item.id)}
                  className={cx("flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition", activePage === item.id ? "bg-cyan-300 text-zinc-950" : "text-zinc-400 hover:bg-white/[0.06] hover:text-white")}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </button>
              );
            })}
          </nav>
          <div className="absolute bottom-5 left-5 right-5 rounded-lg border border-white/10 bg-white/[0.04] p-4">
            <p className="text-sm font-medium text-white">Backend</p>
            <p className="mt-1 text-sm text-zinc-400">{API_BASE || "Vercel proxy /api"}</p>
          </div>
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 border-b border-white/10 bg-[#07080b]/80 px-4 py-4 backdrop-blur-xl sm:px-6 lg:px-8">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-sm text-zinc-500">Performance optimization dashboard</p>
                <h1 className="mt-2 text-2xl font-semibold text-white sm:text-3xl">{currentPage.label}</h1>
              </div>
              <button onClick={refreshAll} className="inline-flex h-10 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-zinc-200">
                <RefreshCw className="h-4 w-4" />
                Refresh
              </button>
            </div>
            <div className="mt-4 flex gap-2 overflow-x-auto pb-1 lg:hidden">
              {navigation.map((item) => (
                <button key={item.id} onClick={() => setActivePage(item.id)} className={cx("whitespace-nowrap rounded-lg px-3 py-2 text-sm transition", activePage === item.id ? "bg-cyan-300 text-zinc-950" : "bg-white/[0.06] text-zinc-300")}>
                  {item.label}
                </button>
              ))}
            </div>
          </header>

          <div className="p-4 sm:p-6 lg:p-8">
            {apiError ? (
              <Card className="mb-4 border-red-400/30 bg-red-400/10">
                <p className="font-medium text-red-100">Action needs attention</p>
                <p className="mt-2 text-sm text-red-100/80">{apiError}</p>
                <p className="mt-2 text-sm text-red-100/70">If this is a connection issue, start FastAPI with: uvicorn backend.main:app --reload</p>
              </Card>
            ) : null}
            {message ? (
              <Card className="mb-4 border-emerald-400/30 bg-emerald-400/10">
                <p className="text-sm text-emerald-100">{message}</p>
              </Card>
            ) : null}
            {loading ? <Card>Loading local data...</Card> : pageContent[activePage]}
          </div>
        </section>
      </div>
    </main>
  );
}
