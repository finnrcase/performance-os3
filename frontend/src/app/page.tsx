"use client";

import * as Sentry from "@sentry/nextjs";
import {
  Apple,
  AlertTriangle,
  BarChart3,
  Check,
  ChevronDown,
  Copy,
  Download,
  Dumbbell,
  ExternalLink,
  Gauge,
  HeartPulse,
  Pencil,
  Plus,
  RefreshCw,
  Settings,
  Sparkles,
  Target,
  Trash2,
  Utensils,
  Weight,
  X,
  CircleMinus,
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
import { Component, FormEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ErrorInfo } from "react";
import { publicApiBaseLabel, publicApiUrl } from "@/lib/api-base";

function apiUrl(path: string) {
  return publicApiUrl(path);
}
const navigation = [
  { id: "dashboard", label: "Dashboard", icon: Gauge },
  { id: "food", label: "Food", icon: Utensils },
  { id: "training", label: "Training", icon: Dumbbell },
  { id: "recovery", label: "Weight & Recovery", icon: HeartPulse },
  { id: "goals", label: "Goals & Targets", icon: Target },
  { id: "history", label: "Data & History", icon: BarChart3 },
  { id: "settings", label: "Integrations / Settings", icon: Settings },
  { id: "debug", label: "Startup Debug", icon: AlertTriangle },
] as const;

const primaryNavigation = navigation.filter((item) => item.id !== "debug");
const debugNavigationItem = navigation.find((item) => item.id === "debug") ?? navigation[navigation.length - 1];
const mobileBottomNavigation = primaryNavigation;

type PageId = (typeof navigation)[number]["id"];
type MobileNavHighlight = { left: number; top: number; width: number; height: number; ready: boolean };
type FoodIconType = "bagel" | "protein_bar" | "oats" | "protein_shake" | "chicken";
type AccentTheme = "lime" | "pink" | "purple" | "orange" | "blue" | "rainbow";

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
  food_log_id?: string;
  date: string;
  logged_sequence?: number | null;
  created_order?: number | null;
  meal_type: string;
  food_name: string;
  iconType?: FoodIconType | null;
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
  quantity?: number | null;
  unit?: string;
  serving_description?: string;
  sugar?: number | null;
  source?: string;
  source_id?: string | null;
  source_url?: string;
  confidence?: string;
  assumptions?: string;
  original_text?: string;
  needs_review?: boolean;
  reviewed_at?: string;
  created_via?: string;
  created_at?: string;
  updated_at?: string;
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
  nutrition_logged?: boolean;
  logged_day?: boolean;
  finalized?: boolean;
  excluded_from_analytics?: boolean;
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
  logged_days?: number;
  missing_days?: number;
  confidence?: "high" | "medium" | "low" | string;
  data_quality_note?: string;
};

type NutritionTodayResponse = {
  date: string;
  items: NutritionEntry[];
  totals: { calories: number; protein: number; carbs: number; fat: number; fiber?: number };
  targets?: { calories?: number | null; protein?: number | null; carbs?: number | null; fat?: number | null };
  finalized?: boolean;
  status?: string;
};

type RecommendationRunResponse = {
  status: string;
  message?: string;
  finalized_summary?: { summary?: DailyNutritionSummary | null } | null;
  dashboard?: DashboardData;
  duration_ms?: number;
};

type ParsedFood = {
  food_name: string;
  display_name?: string;
  normalized_name?: string;
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
  confidence_score?: number | null;
  verification_needed?: boolean;
  verification_reason?: string;
  source?: "ai_estimate" | "verified_online" | "saved_shortcut" | "manual" | string;
  source_id?: string | null;
  verification_status?: string;
  source_url?: string;
  original_text?: string;
  assumptions?: string[];
  needs_review?: boolean;
  needs_confirmation?: boolean;
  notes: string;
};

type BodyMetricEntry = {
  date: string;
  bodyweight: number;
  waist: number | null;
  estimated_body_fat: number | null;
  body_fat_percent?: number | null;
  lean_mass?: number | null;
  fat_mass?: number | null;
  muscle_mass?: number | null;
  hydration?: number | null;
  bmi?: number | null;
  source?: string | null;
  source_id?: string | null;
  notes: string;
};

type BodyMetricFreshnessDebug = {
  withings_connected?: boolean;
  last_withings_sync_at?: string;
  raw_body_metric_rows?: number;
  latest_raw_measurement_at?: string;
  latest_raw_weight?: number | null;
  canonical_daily_rows?: number;
  latest_canonical_date?: string;
  latest_canonical_weight?: number | null;
  dates_with_multiple_weighins?: number;
  dropped_invalid_rows?: number;
  cache_invalidated?: boolean;
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

type WorkoutMarker = {
  marker_id: string;
  date: string;
  marker_sequence?: number | null;
  created_order?: number | null;
  workout_time: string;
  workout_type: string;
  notes: string;
  created_at?: string;
};

type WearableMetricEntry = {
  metric_id: string;
  date: string;
  source: "manual" | "fitbit" | "google_health" | "mock" | string;
  sleep_hours: number | null;
  sleep_score: number | null;
  resting_hr: number | null;
  hrv: number | null;
  steps: number | null;
  active_minutes: number | null;
  calories_burned: number | null;
  workout_minutes?: number | null;
  created_at?: string;
  updated_at?: string;
};

type WearableTrendMetric = {
  latest?: number | null;
  rolling_7_day_average?: number | null;
  recent_7_day_average?: number | null;
  previous_7_day_average?: number | null;
  trend?: string;
};

type WearableSignals = {
  status: string;
  message?: string;
  latest?: Partial<WearableMetricEntry> & { date?: string };
  sleep?: WearableTrendMetric;
  resting_hr?: WearableTrendMetric;
  hrv?: WearableTrendMetric;
  activity?: Record<string, unknown>;
  flags?: string[];
};

type TrainingReadinessSignals = {
  status: string;
  message?: string;
  run_recommendation?: { color?: string; label?: string; reason?: string };
  lift_recommendation?: { label?: string; reason?: string };
  fueling_recommendation?: { label?: string; reason?: string };
  hydration_recommendation?: { label?: string; reason?: string };
  signals?: string[];
  diagnostics?: Record<string, unknown>;
};

type MuscleCoverageItem = {
  muscle_group: string;
  hard_sets?: number;
  sets?: number;
  volume?: number;
  target_sets?: number;
  coverage_pct?: number;
  status?: string;
  color?: string;
  color_hex?: string;
};

type MuscleCoverageResponse = {
  status: string;
  items: MuscleCoverageItem[];
  source?: string;
  diagnostics?: Record<string, unknown>;
  message?: string;
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
  classification?: "lift" | "run" | "cardio" | "lift_cardio" | "unknown" | string;
  classification_label?: string;
  classification_debug?: {
    has_lift?: boolean;
    has_cardio?: boolean;
    matched_lift_terms?: string[];
    matched_cardio_terms?: string[];
    reason?: string;
  };
  muscle_groups: string[];
  exercise_names: string[];
  total_sets: number;
  total_reps?: number;
  total_volume: number;
  duration_minutes: number;
  source: string;
  details: TrainingEntry[];
};

type RunSummary = {
  run_count: number;
  distance_miles: number;
  duration_minutes: number;
  average_pace_min_per_mile: number | null;
  calories_burned?: number | null;
  average_heart_rate?: number | null;
};

type StrengthTrendPoint = {
  date?: string;
  week?: string;
  exercise?: string;
  best_set_weight?: number | string | null;
  estimated_1rm?: number | string | null;
  total_volume?: number | string | null;
  average_working_weight?: number | string | null;
  average_rpe?: number | string | null;
  total_reps?: number | string | null;
  sets?: number | string | null;
  reps?: number | string | null;
  volume?: number | string | null;
  top_weight?: number | string | null;
};

type StrengthTrend = {
  exercise?: string;
  label?: string;
  change_pct?: number | string | null;
  history?: StrengthTrendPoint[] | null;
  best_set?: { date?: string; weight?: number | string | null; reps?: number | string | null; estimated_1rm?: number | string | null; rpe?: number | string | null } | null;
  recent_pr?: boolean | null;
  summary?: string | null;
};

type StrengthTrendItem = {
  exercise?: string;
  sets?: number | string | null;
  reps?: number | string | null;
  volume?: number | string | null;
  top_weight?: number | string | null;
  last_date?: string | null;
};

type StrengthTrendResponse = {
  status?: string;
  exercise_options?: string[];
  selected_exercise?: string;
  trend?: StrengthTrend | StrengthTrendPoint[] | null;
  items?: StrengthTrendItem[];
  weeks?: number;
  summary?: string | Record<string, unknown> | null;
  volume_by_exercise?: Array<{ exercise: string; volume: number; sets: number }>;
  muscle_group_trends?: MuscleGroupTrendResponse | null;
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

type AdaptiveDayTypeAdjustment = {
  type: string;
  reason: string;
  calorie_delta: number;
  carb_delta: number;
  fat_delta: number;
  confidence: string;
  applied_delta?: { calories: number; protein: number; carbs: number; fat: number };
  adjusted_targets?: { calories: number; protein: number; carbs: number; fat: number };
};

type RecommendationConfidence = {
  nutrition: "low" | "medium" | "high" | string;
  body: "low" | "medium" | "high" | string;
  training: "low" | "medium" | "high" | string;
  recovery: "low" | "medium" | "high" | string;
  overall: "low" | "medium" | "high" | string;
  missing_data: string[];
};

type AdaptiveNutritionRecommendation = {
  recommendedCalories?: number;
  recommendedProtein?: number;
  recommendedCarbs?: number;
  recommendedFat?: number;
  caloriesTarget: number;
  proteinTarget: number;
  carbsTarget: number;
  fatTarget: number;
  calorieAdjustment: number;
  macroAdjustment?: { calories: number; protein: number; carbs: number; fat: number };
  macroChanges: { calories: number; protein: number; carbs: number; fat: number };
  dayType?: string;
  dayTypeAdjustment?: AdaptiveDayTypeAdjustment;
  dayOfWeekAdjustment?: {
    weekday: string;
    calorie_delta: number;
    carb_delta: number;
    confidence: string;
    reason: string;
    comparable_weeks: number;
  };
  carbTimingRecommendation?: string;
  confidence: RecommendationConfidence | "low" | "medium" | "high" | string;
  confidenceLevel?: "low" | "medium" | "high" | string;
  dataQualityScore?: number;
  reasoning: string[];
  warnings: string[];
  detectedTrends?: string[];
  missingDataWarnings?: string[];
  nextReviewDate?: string;
  strategy: string;
  currentTarget: { calories: number; protein: number; carbs: number; fat: number };
  recommendedTargets: Targets;
  baselineRecommendedTargets?: Targets;
  dayTypeAdjustedTargets?: Targets;
  signals: {
    weight: {
      status: string;
      weekly_change_pct?: number | null;
      weekly_change_lb?: number | null;
      calorie_adjustment?: number;
      confidence?: string;
      reason?: string;
    };
    bodyComposition?: {
      status: string;
      lean_gain_quality: string;
      latest_bodyweight?: number | null;
      latest_body_fat_percent?: number | null;
      latest_lean_mass?: number | null;
      latest_fat_mass?: number | null;
      weight_7_day_average?: number | null;
      weight_14_day_average?: number | null;
      weight_28_day_average?: number | null;
      weight_gain_rate_lb_per_week?: number | null;
      weight_gain_rate_pct_per_week?: number | null;
      lean_mass_trend_7?: number | null;
      lean_mass_trend_14?: number | null;
      lean_mass_trend_28?: number | null;
      fat_mass_trend_7?: number | null;
      fat_mass_trend_14?: number | null;
      fat_mass_trend_28?: number | null;
      body_fat_percent_trend_14?: number | null;
      body_fat_percent_trend_28?: number | null;
      data_points?: number;
      body_fat_data_points?: number;
    };
    performance: NonNullable<LeanBulkDecision["details"]["performance_signal"]>;
    recovery: RecoverySignal;
    trainingLoad: { status: string; summary: string; hard_sets_per_week?: number; weekly_training_minutes?: number };
    runningLoad: { status: string; summary: string; runs_per_week?: number; weekly_mileage?: number; interference_risk?: string };
    nutrition: {
      days?: number;
      logged_days_14?: number;
      missing_days_14?: number;
      calories?: number | null;
      protein?: number | null;
      carbs?: number | null;
      fat?: number | null;
      average_calories?: number | null;
      average_protein?: number | null;
      average_carbs?: number | null;
      average_fat?: number | null;
      adherence?: string;
      source?: string;
    };
    dataQuality?: { score: number; confidence: string; missingDataWarnings: string[] };
    dayType?: AdaptiveDayTypeAdjustment;
    historicalLearning?: { detectedTrends: string[] };
  };
  recommendation_trace?: {
    decision: "hold" | "increase" | "decrease" | string;
    calorie_change: number;
    main_reasons: string[];
    what_would_change_decision: string[];
  };
  structured_suggestions?: Array<{ type: string; priority: string; title: string; detail: string }>;
  workout_recovery_suggestions?: Array<{ type: string; priority: string; title: string; detail: string }>;
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

type OptimizationTargets = {
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
};

type OptimizationData = {
  day_type_macros: {
    day_type: string;
    confidence: string;
    reason: string;
    baseline_targets: OptimizationTargets;
    adjusted_targets: OptimizationTargets;
    delta: OptimizationTargets;
    signals: string[];
  };
  plateau_detection: {
    status: string;
    summary: string;
    top_alerts: Array<{
      type: string;
      name: string;
      muscle_group: string;
      signal: string;
      severity: string;
      duration_weeks: number;
      message: string;
      estimated_1rm_change_pct?: number | null;
      volume_change_pct?: number | null;
      reps_at_same_weight_delta?: number | null;
    }>;
    details: Array<{
      type: string;
      name: string;
      muscle_group: string;
      signal: string;
      severity: string;
      duration_weeks: number;
      message: string;
      estimated_1rm_change_pct?: number | null;
      volume_change_pct?: number | null;
      reps_at_same_weight_delta?: number | null;
    }>;
  };
  macro_adherence: {
    weekly_score: number | null;
    status: string;
    summary: string;
    components: Record<string, number | null>;
    daily: Array<{ date: string; score: number; calories?: number; protein?: number; carbs?: number; fat?: number }>;
    correlations: Array<{ label: string; summary: string; correlation?: number; confidence: string }>;
  };
  personal_baseline: {
    status: string;
    confidence: string;
    summary: string;
    dashboard_insight: { title: string; summary: string; confidence: string; metric: string } | null;
    insights: Array<{ title: string; summary: string; confidence: string; metric: string }>;
  };
};

type OptimizationSignals = {
  nutrition_recommendation: {
    status: string;
    decision: string;
    title: string;
    calorie_adjustment: number;
    confidence: string;
    data_quality_score?: number | null;
    primary_reason: string;
    source: string;
    engine_snapshot_available?: boolean;
  };
  macro_adherence: OptimizationData["macro_adherence"] & {
    adherence_percent?: number | null;
    confidence?: string;
    consistency?: string;
    logged_days?: number;
    missing_days?: number;
  };
  plateau_watch: OptimizationData["plateau_detection"];
  personal_baseline: OptimizationData["personal_baseline"] & {
    data_points?: number;
    counts?: Record<string, number>;
  };
  confidence: {
    overall: string;
    score: number;
    missing_data: string[];
  };
};

type SettingsHealthCard = {
  id: string;
  title: string;
  status: "connected" | "syncing" | "warning" | "error" | string;
  label: string;
  detail: string;
  last_synced_at?: string;
  action?: string;
  metadata?: {
    connected?: boolean;
    athlete_id?: string;
    userid?: string;
    token_status?: string;
    scopes?: string;
    last_imported_count?: number;
    last_updated_count?: number;
    last_fetched_count?: number;
    latest_activity_date?: string;
    latest_measurement_date?: string;
    last_error?: string;
  };
};

type DiagnosticStatus = "green" | "yellow" | "red" | "gray" | string;

type DiagnosticComponent = {
  configured: boolean;
  status: DiagnosticStatus;
  message: string;
  required_env_vars: string[];
  missing_env_vars: string[];
  last_successful_sync?: string;
  latest_record?: string;
  reconnect_required?: boolean;
  user_action_required?: boolean;
  user_action_message?: string;
  details?: Record<string, unknown>;
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
  status?: string;
  configured?: boolean;
  last_synced_at: string;
  last_error: string;
  last_result: Record<string, unknown>;
  safe_mode?: boolean;
  hevy_rows?: number;
  hevy_workouts?: number;
  latest_workout_date?: string;
  latest_workout_title?: string;
};

type HevySyncResult = {
  status: string;
  message?: string;
  checked_hevy?: boolean;
  sync_mode?: string;
  fallback_recent_import?: boolean;
  events: number;
  saved_workouts: number;
  new_workouts?: number;
  updated_workouts?: number;
  event_saved_workouts?: number;
  imported_workouts?: number;
  imported_rows?: number;
  replaced_rows?: number;
  deleted_rows: number;
  failures?: string[];
  items: TrainingEntry[];
  last_synced_at: string;
  hevy_rows?: number;
  hevy_workouts?: number;
  latest_workout_date?: string;
  latest_workout_title?: string;
};

type TrainingHistoryResponse = {
  items: WorkoutGroup[];
  limit?: number;
  days?: number;
  raw_window_days?: number;
  has_more_recent?: boolean;
  message?: string;
  debug?: {
    hevy_rows?: number;
    hevy_workouts?: number;
    latest_workout_date?: string;
    latest_workout_title?: string;
    message?: string;
  };
};

type TrainingSummaryItem = {
  period_start: string;
  period_end?: string;
  period_label?: string;
  workout_count: number;
  total_sets: number;
  total_reps: number;
  total_volume: number;
  duration_minutes: number;
  latest_workout_date?: string;
};

type MuscleGroupVolumeSummary = {
  period_type: string;
  period_start: string;
  period_label?: string;
  muscle_group: string;
  workout_count: number;
  total_sets: number;
  hard_sets: number;
  total_reps: number;
  total_volume: number;
};

type TrainingSummaryResponse = {
  window: "weekly" | "monthly" | string;
  period: string;
  items: TrainingSummaryItem[];
  muscle_groups: MuscleGroupVolumeSummary[];
  raw_window_days?: number;
  message?: string;
};

type TrainingSummaryStatusResponse = {
  raw_window_days: number;
  total_raw_rows: number;
  recent_raw_rows: number;
  older_raw_rows: number;
  last_hevy_sync?: string;
  last_hevy_check?: string;
  last_hevy_error?: string;
  last_hevy_result?: Record<string, unknown>;
  last_hevy_new_workouts?: number;
  last_hevy_updated_workouts?: number;
  last_hevy_deleted_rows?: number;
  last_hevy_failures?: string[];
  latest_hevy_workout_date?: string;
  latest_hevy_workout_title?: string;
  last_cache_refresh?: string;
  raw_hevy_workouts?: number;
  raw_hevy_sets?: number;
  normalized_workouts?: number;
  normalized_sets?: number;
  cache_health?: string;
  weekly_summaries: number;
  monthly_summaries: number;
  exercise_prs: number;
  muscle_group_periods: number;
  last_summary_rebuild_date?: string;
  latest_weekly_period?: string;
  latest_monthly_period?: string;
  coaching_contract?: {
    plateau_detection?: string;
    calorie_changes?: string;
    long_term_context?: string;
    raw_features_preserved?: string[];
  };
  architecture?: {
    hevy_role?: string;
    hevy_sync_mode?: string;
    startup_source?: string;
    live_raw_window_days?: number;
    historical_source?: string;
  };
};

type TrainingPrItem = {
  pr_id?: string;
  exercise: string;
  weight: number;
  unit?: string;
  reps: number;
  estimated_1rm?: number;
  date: string;
  source: string;
  record_source?: string;
  workout_id?: string;
  workout_type?: string;
};

type TrainingPrResponse = {
  status: "ok" | "empty" | "error" | string;
  items: TrainingPrItem[];
  source: string;
  diagnostics?: Record<string, unknown>;
  message?: string;
};

type WithingsSyncResult = {
  status: string;
  message?: string;
  imported_measurements: number;
  created_measurements?: number;
  updated_measurements?: number;
  fetched_groups: number;
  withings_measurement_groups?: number;
  imported_rows?: number;
  updated_rows?: number;
  skipped_rows?: number;
  earliest_date?: string;
  latest_date?: string;
  pages_fetched?: number;
  pagination_complete?: boolean;
  latest_measure_date: string;
  last_synced_at: string;
  freshness?: BodyMetricFreshnessDebug;
  items?: BodyMetricEntry[];
  canonical_items?: BodyMetricEntry[];
  raw_items?: BodyMetricEntry[];
};

type DashboardData = {
  ok?: boolean;
  core_ready?: boolean;
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
    planned_workout?: string;
    completed_workouts?: string[];
    completed_summary?: string;
    schedule_match?: string;
    match_label?: string;
    sources?: string[];
    has_run?: boolean;
    has_lift?: boolean;
    cardio_indicator?: string | null;
    extra_run_added?: boolean;
    recovery_status_relative_to_plan?: string;
    run_summary?: RunSummary | null;
  };
  workout_quality: {
    status: string;
    date?: string;
    workout_id?: string;
    title?: string;
    workout_type?: string;
    classification?: string;
    classification_label?: string;
    rating?: string;
    score: number | null;
    score_label: string;
    confidence: string;
    color: "gray" | "red" | "orange" | "green" | "bright_green" | string;
    summary?: string;
    explanation: string;
    total_sets?: number;
    total_reps?: number;
    total_volume?: number;
    duration_minutes?: number;
    muscle_groups?: string[];
    comparison_basis?: string;
    similar_workouts_used?: number;
    exercise_breakdown?: Array<{
      exercise: string;
      sets_compared: number;
      avg_set_volume_pct_change?: number | null;
      top_set_pct_change?: number | null;
      reps_at_same_weight_delta?: number | null;
      rating: string;
    }>;
    comparison: string | {
      basis?: string;
      avg_set_volume_pct_change?: number | null;
      volume_vs_average_pct?: number | null;
      sets_vs_average_pct?: number | null;
      sample_size?: number;
      summary?: string;
    } | null;
    debug?: {
      source?: string;
      latest_lift_found?: boolean;
      matched_by?: string;
      excluded_cardio?: boolean;
    };
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
  base_targets?: Targets;
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
  optimization: OptimizationData;
  recommendation: { recommendation_summary: string; reasoning_explanation: string };
  optimization_signals?: OptimizationSignals;
  counts: { nutrition: number; body_metrics: number; recovery: number; sleep?: number; training: number };
  errors?: DashboardDebugBlock[];
  debug?: {
    dashboard_status?: "ok" | "degraded" | "failed" | "error" | string;
    required_blocks?: string[];
    required_blocks_failed?: string[];
    errors?: DashboardDebugBlock[];
    blocks?: DashboardDebugBlock[];
    generated_at?: string;
    total_duration_ms?: number;
    status?: Record<string, boolean>;
    timings_ms?: Record<string, number>;
  };
};

type DashboardDebugBlock = {
  block?: string;
  name?: string;
  status?: "ok" | "error" | "timeout" | "skipped" | string;
  error_type?: string;
  message?: string;
  duration_ms?: number;
  endpoint?: string;
  function?: string;
  trace_excerpt?: string;
};

type StartupDebugEntry = {
  key: string;
  label: string;
  path: string;
  required: boolean;
  status: "pending" | "ok" | "error" | "timeout" | "canceled";
  httpStatus?: number | null;
  durationMs?: number;
  errorMessage?: string;
  responseText?: string;
  backendLabel?: string;
  timestamp: string;
};

type SystemFailureReport = {
  dashboard: DashboardData | null;
  failedBlocks: DashboardDebugBlock[];
  requiredBlocksFailed: string[];
  reason: string;
  timestamp: string;
};

type SettingsData = {
  overall_status?: "ok" | "degraded" | "error" | string;
  environment?: string;
  checked_at?: string;
  backend?: DiagnosticComponent;
  database?: DiagnosticComponent;
  openai?: DiagnosticComponent;
  strava?: DiagnosticComponent;
  hevy?: DiagnosticComponent;
  withings?: DiagnosticComponent;
  frontend?: DiagnosticComponent;
  other_integrations?: Record<string, DiagnosticComponent>;
  required_user_actions?: string[];
  integrations: Record<string, string>;
  appearance?: { accent_color?: AccentTheme | string };
  statuses: Record<string, string>;
  health?: SettingsHealthCard[];
  services?: Record<string, { configured: boolean; status: string; label?: string; message: string; model?: string; api_key_source?: string; response_ms?: number; last_synced_at?: string; latest_record?: string; reconnect_required?: boolean }>;
};

type ApiConnectionLayer = {
  status: string;
  message: string;
};

type ApiConnectionTestItem = {
  status: string;
  message: string;
  lastCheckedAt: string;
  layers?: Record<string, ApiConnectionLayer>;
};

type ApiConnectionTestResponse = {
  checkedAt?: string;
  hevy: ApiConnectionTestItem;
  openai: ApiConnectionTestItem;
  withings: ApiConnectionTestItem;
};

type FormState = {
  nutrition: NutritionEntry;
  body: BodyMetricEntry;
  recovery: RecoveryEntry;
  training: TrainingEntry;
  workoutMarker: Pick<WorkoutMarker, "date" | "workout_time" | "workout_type" | "notes">;
  wearable: {
    date: string;
    source: string;
    sleep_hours: number | "";
    sleep_score: number | "";
    resting_hr: number | "";
    hrv: number | "";
    steps: number | "";
    active_minutes: number | "";
    calories_burned: number | "";
  };
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
  parser?: FoodParserMeta;
  debug: {
    backend_endpoint_reached?: boolean;
    openai_key_configured?: boolean;
    model?: string;
    parsing_status?: string;
    failed_step?: string | null;
    error_type?: string;
    message?: string;
    duration_ms?: number;
    openai_called?: boolean;
    parser_source?: string;
    parser_cached?: boolean;
    external_lookup_status?: string;
    external_lookup_statuses?: string[];
    parser?: FoodParserMeta;
    escalated?: boolean;
    escalation_reason?: string;
    final_model?: string;
    estimated_input_tokens?: number;
    estimated_output_tokens?: number;
    estimated_cost_usd?: number;
  };
};

type FoodParserMeta = {
  default_model_used?: boolean;
  escalated?: boolean;
  escalation_reason?: string;
  final_model?: string;
  model_used?: string;
  estimated_input_tokens?: number;
  estimated_output_tokens?: number;
  estimated_cost_usd?: number;
  calls?: Array<Record<string, unknown>>;
};

type FoodAiFlowStep = {
  step: string;
  status: "pending" | "ok" | "error";
  message: string;
};

type FoodAiDebugState = {
  endpoint_called?: string;
  request_body_received?: Record<string, unknown>;
  diagnostic_force_openai?: boolean;
  openai_called?: boolean;
  model_used?: string;
  parser_source?: string;
  external_lookup_status?: string;
  raw_items_count?: number;
  normalized_items_count?: number;
  response_shape?: Record<string, unknown>;
  frontend_received_items?: boolean;
  log_insert_attempted?: boolean;
  log_insert_success?: boolean;
  analyzeEndpoint?: string;
  analyzeRequestBody?: Record<string, unknown>;
  analyzeResponseStatus?: string;
  analyzeResponseMs?: number;
  parsedItemCount?: number;
  logEndpoint?: string;
  logRequestBody?: Record<string, unknown>;
  logInsertStatus?: string;
  logCreated?: number;
  logRequested?: number;
  refreshEndpoint?: string;
  refreshStatus?: string;
  refreshCalories?: number;
  default_model_used?: boolean;
  escalated?: boolean;
  escalation_reason?: string;
  final_model?: string;
  estimated_input_tokens?: number;
  estimated_output_tokens?: number;
  estimated_cost_usd?: number;
  exactError?: string;
  updatedAt?: string;
};

type FoodParserDiagnosticResponse = {
  status: "ok" | "error" | string;
  endpoint_called: string;
  request_body_received: Record<string, unknown>;
  diagnostic_force_openai?: boolean;
  openai_called: boolean;
  model_used: string;
  parser_source?: string;
  external_lookup_status?: string;
  raw_items_count: number;
  normalized_items_count: number;
  response_shape: Record<string, unknown>;
  frontend_received_items: boolean;
  log_insert_attempted: boolean;
  log_insert_success: boolean;
  items: FoodAnalyzeItem[];
  foods?: FoodAnalyzeItem[];
  totals?: FoodAnalyzeTotals;
  message?: string;
  error_code?: string | null;
  steps?: Record<string, unknown>;
  debug?: FoodParseResponse["debug"] & Record<string, unknown>;
};

type FoodAnalyzeItem = {
  name: string;
  display_name?: string;
  normalized_name?: string;
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
  confidence_score?: number | null;
  source: "usda_fdc" | "existing_database" | "openai_estimate" | "web_source" | string;
  source_id: string | null;
  source_url: string | null;
  assumptions: string[];
  needs_review: boolean;
  needs_confirmation?: boolean;
};

type FoodAnalyzeTotals = {
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number | null;
  sugar_g: number | null;
  sodium_mg: number | null;
};

type FoodAnalyzeResponse = {
  status?: "ok" | "error" | string;
  items?: FoodAnalyzeItem[];
  foods?: FoodAnalyzeItem[];
  totals: FoodAnalyzeTotals;
  total?: FoodAnalyzeTotals;
  warnings: string[];
  message: string;
  success: boolean;
  error_code: string | null;
  source?: string;
  parser_source?: string;
  external_lookup_status?: string;
  parser?: FoodParserMeta;
  debug: FoodParseResponse["debug"];
  steps?: Record<string, unknown>;
};

type FoodBulkLogResponse = {
  status: string;
  created: number;
  requested?: number;
  items?: NutritionEntry[];
  message?: string;
};

type FoodShortcut = {
  shortcut_id: string;
  shortcut_name: string;
  icon_type?: FoodPresetIconType | string | null;
  iconType?: FoodPresetIconType | string | null;
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

type FoodPresetIconType =
  | "oats"
  | "smoothie"
  | "bagel"
  | "chicken"
  | "meal_bowl"
  | "protein_bar"
  | "protein_shake"
  | "rice_crispy_treat"
  | "eggs"
  | "banana"
  | "rice"
  | "tuna"
  | "yogurt"
  | "avocado"
  | "salmon"
  | "peanut_butter";

type MealTemplate = {
  template_name: string;
  default_meal_type: string;
  food_name: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
};

type MealTemplateSummary = {
  template_name: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  foods: number;
};

type NutritionShortcutData = {
  items: FoodShortcut[];
  frequent_foods: Array<{ food_name: string; calories: number; protein: number; carbs: number; fat: number; default_meal_type: string; is_favorite?: boolean }>;
  meal_templates: MealTemplate[];
};

type QuickFoodLogStatus = {
  pending: number;
  added?: boolean;
  error?: string | null;
};

type QuickFoodLogJob = {
  id: string;
  statusKey: string;
  date: string;
  label: string;
  optimisticEntry: NutritionEntry;
  refreshShortcuts?: boolean;
  run: () => Promise<NutritionEntry | null>;
};

const DEFAULT_MEAL_TYPE = "Food";
const APP_TIMEZONE = process.env.NEXT_PUBLIC_APP_TIMEZONE || "America/Los_Angeles";
const integrationLabels: Record<string, string> = {
  hevy_api_key: "Hevy API key",
  strava_client_id: "Strava client ID",
  strava_client_secret: "Strava client secret",
  fitbit_client_id: "Fitbit client ID",
  fitbit_client_secret: "Fitbit client secret",
  google_health_client_id: "Google Health client ID",
  google_health_client_secret: "Google Health client secret",
  withings_client_id: "Withings client ID",
  withings_client_secret: "Withings client secret",
  openai_api_key: "OpenAI API key",
  apple_health_export_file: "Apple Health upload placeholder",
};

function todayString() {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: APP_TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function headerDateString(date = new Date()) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: APP_TIMEZONE,
    month: "numeric",
    day: "numeric",
    year: "2-digit",
  }).format(date);
}

function dashboardCorePath(date = todayString()) {
  return `/api/dashboard/core?date=${encodeURIComponent(date)}`;
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
    serving_description: "",
    calories: 0,
    protein: 0,
    carbs: 0,
    fat: 0,
    fiber: null,
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
  workoutMarker: {
    date: todayString(),
    workout_time: "",
    workout_type: "Strength",
    notes: "",
  },
  wearable: {
    date: todayString(),
    source: "manual",
    sleep_hours: "",
    sleep_score: "",
    resting_hr: "",
    hrv: "",
    steps: "",
    active_minutes: "",
    calories_burned: "",
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

function recommendationConfidenceLabel(confidence?: AdaptiveNutritionRecommendation["confidence"], fallback?: string) {
  if (!confidence) return fallback ?? "low";
  if (typeof confidence === "string") return confidence;
  return confidence.overall || fallback || "low";
}

function finiteNumberOrNull(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

const DEFAULT_BASELINE_CALORIES = 2650;

function recordOrEmpty(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function arrayOrEmpty<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function stringOrFallback(value: unknown, fallback = "") {
  return typeof value === "string" && value.trim().length > 0 ? value : fallback;
}

function formatWholeNumber(value: unknown, fallback = "--") {
  const parsed = finiteNumberOrNull(value);
  return parsed === null ? fallback : `${Math.round(parsed)}`;
}

function formatCompactNumber(value: unknown, fallback = "--") {
  const parsed = finiteNumberOrNull(value);
  if (parsed === null) return fallback;
  return Math.round(parsed).toLocaleString();
}

function formatSignedWholeNumber(value: unknown, suffix = "", fallback = "--") {
  const parsed = finiteNumberOrNull(value);
  if (parsed === null) return fallback;
  return `${parsed > 0 ? "+" : ""}${Math.round(parsed)}${suffix}`;
}

function formatSignedPercentValue(value: unknown, digits = 0, fallback = "--") {
  const parsed = finiteNumberOrNull(value);
  if (parsed === null) return fallback;
  return `${parsed >= 0 ? "+" : ""}${parsed.toFixed(digits)}%`;
}

function stringList(value: unknown, fallback: string[] = []) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : fallback;
}

const ACCENT_THEME_STORAGE_KEY = "performance-os-accent-theme";
const DAILY_NUTRITION_HISTORY_EXPANDED_KEY = "performance-os-daily-nutrition-history-expanded";

const accentThemeOptions: Array<{ id: AccentTheme; label: string; swatch: string }> = [
  { id: "lime", label: "Lime", swatch: "bg-lime-300" },
  { id: "pink", label: "Pink", swatch: "bg-pink-300" },
  { id: "purple", label: "Purple", swatch: "bg-violet-300" },
  { id: "orange", label: "Orange", swatch: "bg-orange-300" },
  { id: "blue", label: "Blue", swatch: "bg-blue-300" },
  { id: "rainbow", label: "Rainbow", swatch: "bg-[linear-gradient(120deg,#bef264,#67e8f9,#c4b5fd,#f9a8d4,#fdba74)]" },
];

function sanitizeAccentTheme(value: unknown): AccentTheme {
  const normalized = String(value || "lime").toLowerCase();
  return accentThemeOptions.some((option) => option.id === normalized) ? normalized as AccentTheme : "lime";
}

function readStoredAccentTheme(): AccentTheme {
  if (typeof window === "undefined") return "lime";
  return sanitizeAccentTheme(window.localStorage.getItem(ACCENT_THEME_STORAGE_KEY));
}

const DEFAULT_API_TIMEOUT_MS = 120_000;
const STARTUP_API_TIMEOUT_MS = 120_000;
const SETTINGS_API_TIMEOUT_MS = 45_000;
const UPLOAD_API_TIMEOUT_MS = 120_000;
const COLD_START_RETRY_DELAY_MS = 6_000;
// Exponential backoff for HTTP 429 (server-side rate limiting): 1s, 3s, 8s,
// then give up. A server 429 means the request was rejected, not processed,
// so retrying it — including POSTs — is safe.
const RATE_LIMIT_BACKOFF_MS = [1_000, 3_000, 8_000];

// Lets the module-level fetch layer tell React when requests are being
// retried because of rate limiting, without a global store.
type RateLimitListener = (active: boolean) => void;
const rateLimitListeners = new Set<RateLimitListener>();
let activeRateLimitedRequests = 0;

function subscribeRateLimit(listener: RateLimitListener): () => void {
  rateLimitListeners.add(listener);
  return () => {
    rateLimitListeners.delete(listener);
  };
}

function adjustRateLimited(delta: number) {
  activeRateLimitedRequests = Math.max(0, activeRateLimitedRequests + delta);
  const active = activeRateLimitedRequests > 0;
  rateLimitListeners.forEach((listener) => listener(active));
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function retryAfterMs(header: string | null): number | null {
  if (!header) return null;
  const seconds = Number(header.trim());
  if (Number.isFinite(seconds) && seconds >= 0) {
    return Math.min(seconds * 1000, 15_000); // cap so a huge Retry-After can't hang the UI
  }
  return null;
}

class ApiRequestError extends Error {
  readonly status: number;
  readonly path: string;

  constructor(path: string, status: number, detail: string) {
    super(`${path} returned ${status}: ${detail}`);
    this.name = "ApiRequestError";
    this.status = status;
    this.path = path;
  }
}

function isAuthFailureReason(reason: string) {
  const lowered = reason.toLowerCase();
  return (
    lowered.includes("returned 401")
    || lowered.includes("returned 403")
    || lowered.includes("authentication required")
    || lowered.includes("session expired")
    || lowered.includes("invalid session")
    || lowered.includes("unauthor")
    || lowered.includes("forbidden")
  );
}

export default function Home() {
  return (
    <AppRootErrorBoundary>
      <HomeContent />
    </AppRootErrorBoundary>
  );
}

type StartupFailureKind = "auth" | "timeout" | "server" | "network" | "rate_limit" | "invalid_response" | "other";

function classifyStartupFailure(reasons: string[]): StartupFailureKind {
  const joined = reasons.join(" | ").toLowerCase();
  if (reasons.some(isAuthFailureReason)) return "auth";
  if (joined.includes("429") || joined.includes("rate limit") || joined.includes("too many requests")) return "rate_limit";
  if (joined.includes("invalid json") || joined.includes("unexpected token")) return "invalid_response";
  if (joined.includes("timed out") || joined.includes("timeout") || joined.includes("abort")) return "timeout";
  if (joined.includes("returned 500") || joined.includes("returned 502") || joined.includes("returned 503") || joined.includes("returned 504")) return "server";
  if (joined.includes("failed to fetch") || joined.includes("networkerror") || joined.includes("load failed")) return "network";
  return "other";
}

function isColdStartRetryable(kind: StartupFailureKind) {
  return kind === "timeout" || kind === "network";
}

function startupFailureHint(kind: StartupFailureKind) {
  switch (kind) {
    case "auth":
      return "Session expired / please log in again.";
    case "timeout":
      return "The backend took too long to respond. It may still be waking up; click Retry if it does not recover.";
    case "server":
      return "The backend responded with a server error. This usually means the backend crashed while building the response.";
    case "network":
      return "Could not reach the backend (network or CORS error).";
    case "rate_limit":
      return "The server is temporarily rate limiting requests (not your account). Wait a moment and click Retry.";
    case "invalid_response":
      return "The backend responded but the data could not be read (invalid response). Click Retry.";
    default:
      return "The backend may be offline or unreachable.";
  }
}

function scheduleLoginRedirect() {
  window.setTimeout(() => {
    const loginUrl = new URL("/login", window.location.origin);
    loginUrl.searchParams.set("next", window.location.pathname);
    void fetch("/api/access/logout", { method: "POST", credentials: "include" })
      .catch(() => undefined)
      .finally(() => window.location.assign(loginUrl.toString()));
  }, 250);
}

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs: number = DEFAULT_API_TIMEOUT_MS,
): Promise<Response> {
  const target = typeof input === "string" ? input : input instanceof URL ? input.toString() : "request";
  let flaggedRateLimited = false;
  try {
    for (let attempt = 0; ; attempt += 1) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      let response: Response;
      try {
        response = await fetch(input, { ...init, signal: controller.signal });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          throw new Error(`${target} timed out after ${timeoutMs}ms`);
        }
        throw error;
      } finally {
        clearTimeout(timer);
      }

      // Retry only on 429 (server temporarily rate limiting), with backoff.
      if (response.status !== 429 || attempt >= RATE_LIMIT_BACKOFF_MS.length) {
        return response;
      }
      if (!flaggedRateLimited) {
        flaggedRateLimited = true;
        adjustRateLimited(1);
      }
      const delay = retryAfterMs(response.headers.get("Retry-After")) ?? RATE_LIMIT_BACKOFF_MS[attempt];
      console.warn(`[rate-limit] ${target} -> HTTP 429; retrying in ${delay}ms (attempt ${attempt + 1}/${RATE_LIMIT_BACKOFF_MS.length})`);
      await sleep(delay);
    }
  } finally {
    if (flaggedRateLimited) {
      adjustRateLimited(-1);
    }
  }
}

async function apiGet<T>(path: string, timeoutMs: number = DEFAULT_API_TIMEOUT_MS): Promise<T> {
  const url = apiUrl(path);
  const response = await fetchWithTimeout(url, { cache: "no-store", credentials: "include" }, timeoutMs);
  if (!response.ok) {
    console.warn(`[apiGet] ${url} -> HTTP ${response.status}`);
    throw new ApiRequestError(path, response.status, await apiErrorMessage(response));
  }
  const text = await response.text();
  try {
    return JSON.parse(text) as T;
  } catch {
    console.warn(`[apiGet] ${url} -> HTTP ${response.status} but body is not valid JSON (${text.length} chars)`);
    throw new Error(`${path} returned invalid JSON (HTTP ${response.status})`);
  }
}

type StartupDebugMeta = {
  key: string;
  label: string;
  path: string;
  required: boolean;
};

function captureStartupRequestFailure(
  meta: StartupDebugMeta,
  status: StartupDebugEntry["status"],
  errorMessage: string,
  durationMs: number,
  responseText?: string,
  httpStatus?: number | null,
) {
  Sentry.captureMessage("Performance OS startup request failed", {
    level: status === "timeout" || status === "canceled" ? "warning" : "error",
    tags: {
      request_key: meta.key,
      endpoint: meta.path,
      required: String(meta.required),
      status,
      http_status: String(httpStatus ?? ""),
    },
    extra: {
      label: meta.label,
      durationMs,
      errorMessage,
      responseText: responseText?.slice(0, 1200),
      backendLabel: publicApiBaseLabel(),
    },
  });
}

function classifyRequestDebugStatus(error: unknown): StartupDebugEntry["status"] {
  if (error instanceof Error) {
    const message = error.message.toLowerCase();
    if (message.includes("timed out") || message.includes("timeout") || message.includes("abort")) return "timeout";
    if (message.includes("cancel")) return "canceled";
  }
  return "error";
}

async function trackedApiGet<T>(
  meta: StartupDebugMeta,
  timeoutMs: number,
  record: (entry: StartupDebugEntry) => void,
): Promise<T> {
  const timestamp = new Date().toISOString();
  const started = performance.now();
  record({
    ...meta,
    status: "pending",
    httpStatus: null,
    backendLabel: publicApiBaseLabel(),
    timestamp,
  });

  try {
    const url = apiUrl(meta.path);
    if (meta.key === "dashboard_core") {
      console.info("[startup] dashboard_core url", url);
    }
    const response = await fetchWithTimeout(url, { cache: "no-store", credentials: "include" }, timeoutMs);
    const responseText = await response.text();
    const durationMs = Math.round(performance.now() - started);
    if (meta.key === "dashboard_core") {
      console.info(`[startup] /api/dashboard/core returned ${response.status} in ${durationMs}ms`, responseText.slice(0, 2000));
    }
    if (!response.ok) {
      const message = apiErrorMessageFromText(responseText, response.statusText);
      record({
        ...meta,
        status: "error",
        httpStatus: response.status,
        durationMs,
        errorMessage: message,
        responseText: responseText.slice(0, 2000),
        backendLabel: publicApiBaseLabel(),
        timestamp: new Date().toISOString(),
      });
      captureStartupRequestFailure(meta, "error", message, durationMs, responseText, response.status);
      throw new ApiRequestError(meta.path, response.status, message);
    }
    try {
      const parsed = JSON.parse(responseText) as T;
      record({
        ...meta,
        status: "ok",
        httpStatus: response.status,
        durationMs,
        responseText: responseText.slice(0, 1000),
        backendLabel: publicApiBaseLabel(),
        timestamp: new Date().toISOString(),
      });
      return parsed;
    } catch (error) {
      const message = `${meta.path} returned invalid JSON (HTTP ${response.status})`;
      record({
        ...meta,
        status: "error",
        httpStatus: response.status,
        durationMs,
        errorMessage: message,
        responseText: responseText.slice(0, 2000),
        backendLabel: publicApiBaseLabel(),
        timestamp: new Date().toISOString(),
      });
      captureStartupRequestFailure(meta, "error", message, durationMs, responseText, response.status);
      throw error instanceof Error ? new Error(message) : new Error(message);
    }
  } catch (error) {
    if (error instanceof ApiRequestError) throw error;
    const durationMs = Math.round(performance.now() - started);
    const status = classifyRequestDebugStatus(error);
    const errorMessage = error instanceof Error ? error.message : String(error);
    if (meta.key === "dashboard_core") {
      console.error(`[startup] /api/dashboard/core ${status} after ${durationMs}ms: ${errorMessage}`);
    }
    record({
      ...meta,
      status,
      httpStatus: null,
      durationMs,
      errorMessage,
      backendLabel: publicApiBaseLabel(),
      timestamp: new Date().toISOString(),
    });
    captureStartupRequestFailure(meta, status, errorMessage, durationMs);
    throw error;
  }
}

function apiErrorMessageFromText(text: string, statusText: string) {
  if (!text) return statusText || "Request failed.";
  try {
    const parsed = JSON.parse(text);
    const detail = parsed?.detail;
    if (typeof detail === "string") return detail;
    if (detail?.message) return String(detail.message);
    if (parsed?.message) return String(parsed.message);
  } catch {
    return text;
  }
  return text;
}

async function apiErrorMessage(response: Response) {
  const text = await response.text();
  return apiErrorMessageFromText(text, response.statusText);
}

async function apiSend<T>(path: string, method: "POST" | "PUT", body: unknown): Promise<T> {
  const response = await fetchWithTimeout(apiUrl(path), {
    method,
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  if (!response.ok) {
    throw new ApiRequestError(path, response.status, apiErrorMessageFromText(text, response.statusText));
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`${path} returned invalid JSON (HTTP ${response.status}): ${text.slice(0, 300) || "empty response"}`);
  }
}

async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetchWithTimeout(apiUrl(path), { method: "DELETE", credentials: "include" });
  if (!response.ok) {
    throw new ApiRequestError(path, response.status, await apiErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetchWithTimeout(
    apiUrl(path),
    {
      method: "POST",
      body: formData,
      credentials: "include",
    },
    UPLOAD_API_TIMEOUT_MS,
  );
  if (!response.ok) {
    throw new ApiRequestError(path, response.status, await apiErrorMessage(response));
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
        {eyebrow ? <p className="accent-text mb-1 text-xs font-semibold uppercase tracking-[0.18em]">{eyebrow}</p> : null}
        <h2 className="text-lg font-semibold text-white">{title}</h2>
      </div>
      {action ? <div>{action}</div> : null}
    </div>
  );
}

class TargetSectionErrorBoundary extends Component<
  Readonly<{ children: React.ReactNode; title: string; description?: string; resetKey?: string }>,
  { hasError: boolean; message: string }
> {
  state = { hasError: false, message: "" };

  static getDerivedStateFromError(error: unknown) {
    return {
      hasError: true,
      message: error instanceof Error ? error.message : "Insufficient data.",
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    Sentry.captureException(error, { extra: { componentStack: info.componentStack } });
  }

  componentDidUpdate(previousProps: Readonly<{ children: React.ReactNode; title: string; description?: string; resetKey?: string }>) {
    if (this.state.hasError && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false, message: "" });
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <Card className="border-amber-300/25 bg-amber-300/[0.06]">
          <p className="font-medium text-amber-100">{this.props.title}</p>
          <p className="mt-2 text-sm leading-6 text-amber-100/75">{this.props.description ?? "Insufficient data to render this section."}</p>
          {this.state.message ? <p className="mt-2 text-xs leading-5 text-amber-100/55">{this.state.message}</p> : null}
        </Card>
      );
    }
    return this.props.children;
  }
}

class AppRootErrorBoundary extends Component<
  Readonly<{ children: React.ReactNode }>,
  { hasError: boolean; message: string }
> {
  state = { hasError: false, message: "" };

  static getDerivedStateFromError(error: unknown) {
    return {
      hasError: true,
      message: error instanceof Error ? error.message : "Adaptive data temporarily unavailable.",
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    Sentry.captureException(error, { extra: { componentStack: info.componentStack } });
  }

  render() {
    if (this.state.hasError) {
      return (
        <main data-accent-theme="lime" className="min-h-screen bg-[#07080b] p-4 text-zinc-100 sm:p-6 lg:p-8">
          <Card className="border-amber-300/25 bg-amber-300/[0.06]">
            <SectionHeader eyebrow="Performance OS" title="Adaptive data temporarily unavailable" />
            <p className="text-sm leading-6 text-amber-100/80">The app shell is still available, but one top-level dashboard payload could not render safely.</p>
            {this.state.message ? <p className="mt-2 text-xs leading-5 text-amber-100/55">{this.state.message}</p> : null}
          </Card>
        </main>
      );
    }
    return this.props.children;
  }
}

class GoalsPageErrorBoundary extends Component<
  Readonly<{ children: React.ReactNode; resetKey?: string }>,
  { hasError: boolean; message: string }
> {
  state = { hasError: false, message: "" };

  static getDerivedStateFromError(error: unknown) {
    return {
      hasError: true,
      message: error instanceof Error ? error.message : "Goals & Targets could not render.",
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    Sentry.captureException(error, { extra: { componentStack: info.componentStack } });
  }

  componentDidUpdate(previousProps: Readonly<{ children: React.ReactNode; resetKey?: string }>) {
    if (this.state.hasError && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false, message: "" });
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="space-y-6">
          <Card>
            <SectionHeader eyebrow="Goals" title="Goals & Targets" />
            <p className="text-sm leading-6 text-zinc-300">Insufficient data to render one Goals & Targets tile.</p>
            <p className="mt-2 text-xs leading-5 text-zinc-500">{this.state.message || "Missing recommendation data."}</p>
          </Card>
        </div>
      );
    }
    return this.props.children;
  }
}

class ExerciseViewErrorBoundary extends Component<
  Readonly<{ children: React.ReactNode; resetKey?: string }>,
  { hasError: boolean; message: string }
> {
  state = { hasError: false, message: "" };

  static getDerivedStateFromError(error: unknown) {
    return {
      hasError: true,
      message: error instanceof Error ? error.message : "Exercise view could not render.",
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    Sentry.captureException(error, { extra: { componentStack: info.componentStack } });
  }

  componentDidUpdate(previousProps: Readonly<{ children: React.ReactNode; resetKey?: string }>) {
    if (this.state.hasError && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false, message: "" });
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-lg border border-dashed border-white/15 bg-white/[0.03] p-6">
          <p className="font-medium text-white">Exercise view unavailable</p>
          <p className="mt-2 text-sm text-zinc-400">No exercise trend data available yet.</p>
          <p className="mt-2 text-xs text-zinc-500">{this.state.message || "Missing exercise trend data."}</p>
        </div>
      );
    }
    return this.props.children;
  }
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
  return "accent-outline";
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

function formatFoodAmount(value: unknown, digits = 0) {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) return digits > 0 ? "0.0" : "0";
  return digits > 0 ? numberValue.toFixed(digits).replace(/\.0$/, "") : `${Math.round(numberValue)}`;
}

function formatRunDuration(minutes?: number | null) {
  if (!minutes || minutes <= 0) return "--:--";
  const totalSeconds = Math.round(minutes * 60);
  const hours = Math.floor(totalSeconds / 3600);
  const mins = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${mins.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  }
  return `${mins}:${seconds.toString().padStart(2, "0")}`;
}

function formatRunPace(minutes?: number | null) {
  if (!minutes || minutes <= 0) return "--/mi";
  return `${formatRunDuration(minutes)}/mi`;
}

function hasFoodDetail(value: unknown) {
  return value !== null && value !== undefined && value !== "" && String(value) !== "NaN";
}

function foodMacroSummary(entry: Pick<NutritionEntry, "calories" | "protein" | "carbs" | "fat">) {
  return `${formatFoodAmount(entry.calories)} kcal · P ${formatFoodAmount(entry.protein)}g · C ${formatFoodAmount(entry.carbs)}g · F ${formatFoodAmount(entry.fat)}g`;
}

function foodAmountLabel(entry: NutritionEntry) {
  const details = [
    entry.serving_description,
    hasFoodDetail(entry.quantity) ? `${formatFoodAmount(entry.quantity, 1)} ${entry.unit ?? ""}`.trim() : "",
    hasFoodDetail(entry.grams_consumed) ? `${formatFoodAmount(entry.grams_consumed, 1)}g` : "",
  ].filter((value) => hasFoodDetail(value));
  return details[0] ? String(details[0]) : "";
}

type FoodIconProps = { className?: string };

const FOOD_ICON_TYPES: FoodIconType[] = ["bagel", "protein_bar", "oats", "protein_shake", "chicken"];

function BagelIcon({ className }: FoodIconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="none">
      <circle cx="12" cy="12" r="7.5" fill="currentColor" opacity="0.14" />
      <circle cx="12" cy="12" r="7.5" stroke="currentColor" strokeWidth="1.7" />
      <ellipse cx="12" cy="12.2" rx="3.1" ry="2.4" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8.2 8.1h.01M15.6 8.5h.01M16 15.5h.01M7.8 14.9h.01" stroke="currentColor" strokeLinecap="round" strokeWidth="1.9" />
    </svg>
  );
}

function ProteinBarIcon({ className }: FoodIconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="none">
      <rect x="4.2" y="7" width="15.6" height="10" rx="2.4" fill="currentColor" opacity="0.12" />
      <rect x="4.2" y="7" width="15.6" height="10" rx="2.4" stroke="currentColor" strokeWidth="1.7" />
      <path d="M7.1 9.6h5.2M7.1 12h3.6M14 10l2.9 4.2M17 9.7l-2.9 4.2" stroke="currentColor" strokeLinecap="round" strokeWidth="1.45" />
      <path d="M5.5 7.9l1.2-1.5M17.3 17.6l1.2-1.5" stroke="currentColor" strokeLinecap="round" strokeWidth="1.2" opacity="0.75" />
    </svg>
  );
}

function OatsIcon({ className }: FoodIconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="none">
      <path d="M5.2 11.2h13.6l-1.1 4.1a4 4 0 0 1-3.9 3H10.2a4 4 0 0 1-3.9-3z" fill="currentColor" opacity="0.12" />
      <path d="M5.2 11.2h13.6l-1.1 4.1a4 4 0 0 1-3.9 3H10.2a4 4 0 0 1-3.9-3z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.7" />
      <path d="M8.1 11.1c.3-1.5 1.5-2.6 2.9-2.6s2.1.8 2.8.8 1.2-.5 2.1-.5c1.1 0 2 .8 2.4 2.3" stroke="currentColor" strokeLinecap="round" strokeWidth="1.45" />
      <path d="M9.5 14.2h.01M12.2 13.5h.01M14.8 14.5h.01" stroke="currentColor" strokeLinecap="round" strokeWidth="1.9" />
      <path d="M16.4 7.2l2.8-2" stroke="currentColor" strokeLinecap="round" strokeWidth="1.4" opacity="0.8" />
    </svg>
  );
}

function ProteinShakeIcon({ className }: FoodIconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="none">
      <path d="M8 8h8l-.8 10.1a2.2 2.2 0 0 1-2.2 2H11a2.2 2.2 0 0 1-2.2-2z" fill="currentColor" opacity="0.12" />
      <path d="M8 8h8l-.8 10.1a2.2 2.2 0 0 1-2.2 2H11a2.2 2.2 0 0 1-2.2-2zM7.6 5.1h8.8M9 3.6h6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
      <path d="M9.1 13.4h6.2M9.4 10.2h6.2M10.4 16.3h3.3" stroke="currentColor" strokeLinecap="round" strokeWidth="1.25" opacity="0.82" />
    </svg>
  );
}

function ChickenIcon({ className }: FoodIconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="none">
      <path d="M13.8 5.5c2.9.4 5 2.5 5 5.2 0 2.9-2.4 5.3-5.7 5.3-3.6 0-6.4-2.5-6.4-5.6 0-2.8 2.6-5.4 7.1-4.9z" fill="currentColor" opacity="0.12" />
      <path d="M13.8 5.5c2.9.4 5 2.5 5 5.2 0 2.9-2.4 5.3-5.7 5.3-3.6 0-6.4-2.5-6.4-5.6 0-2.8 2.6-5.4 7.1-4.9z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.7" />
      <path d="M7.7 14.5 5.8 16.4M5.8 16.4l-1.6-1.2M5.8 16.4l1.1 1.7" stroke="currentColor" strokeLinecap="round" strokeWidth="1.7" />
      <path d="M13.1 8.5c1.2.2 2.1.9 2.6 1.9" stroke="currentColor" strokeLinecap="round" strokeWidth="1.25" opacity="0.82" />
    </svg>
  );
}

function FoodIcon({ type, className }: Readonly<{ type: FoodIconType; className?: string }>) {
  switch (type) {
    case "bagel":
      return <BagelIcon className={className} />;
    case "protein_bar":
      return <ProteinBarIcon className={className} />;
    case "oats":
      return <OatsIcon className={className} />;
    case "protein_shake":
      return <ProteinShakeIcon className={className} />;
    case "chicken":
      return <ChickenIcon className={className} />;
    default:
      return null;
  }
}

const FOOD_ICON_OPTIONS: Array<{ type: FoodIconType; label: string }> = [
  { type: "bagel", label: "Bagel" },
  { type: "protein_bar", label: "Protein bar" },
  { type: "oats", label: "Oats" },
  { type: "protein_shake", label: "Protein shake" },
  { type: "chicken", label: "Chicken" },
];

function normalizeFoodIconType(value: string | null | undefined): FoodIconType | null {
  const selected = String(value ?? "").trim() as FoodIconType;
  return FOOD_ICON_TYPES.includes(selected) ? selected : null;
}

function suggestFoodIconType(foodName: string | null | undefined): FoodIconType | null {
  const normalizedName = String(foodName ?? "").toLowerCase();
  if (normalizedName.includes("bagel")) return "bagel";
  if (normalizedName.includes("built bar") || normalizedName.includes("protein bar") || (normalizedName.includes("protein") && normalizedName.includes("bar"))) return "protein_bar";
  if (normalizedName.includes("oat") || normalizedName.includes("oatmeal")) return "oats";
  if (normalizedName.includes("protein shake") || normalizedName.includes("shake")) return "protein_shake";
  if (normalizedName.includes("chicken")) return "chicken";
  return null;
}

function FoodIconPicker({
  value,
  onChange,
}: Readonly<{
  value: FoodIconType | null;
  onChange: (value: FoodIconType | null) => void;
}>) {
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">Icon</p>
        <button
          type="button"
          onClick={() => onChange(null)}
          disabled={!value}
          className="rounded-md border border-white/10 px-2 py-1 text-xs font-semibold text-zinc-300 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-40"
        >
          Clear
        </button>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
        {FOOD_ICON_OPTIONS.map((option) => {
          const selected = value === option.type;
          return (
            <button
              key={option.type}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange(option.type)}
              className={cx(
                "flex min-h-16 flex-col items-center justify-center gap-1 rounded-lg border px-2 py-2 text-center text-xs font-semibold transition",
                selected
                  ? "accent-outline"
                  : "accent-hover border-white/10 bg-zinc-950/45 text-zinc-300",
              )}
            >
              <FoodIcon type={option.type} className="accent-text-strong h-5 w-5" />
              <span>{option.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function FoodLogList({
  entries,
  emptyDescription,
  onRemove,
  removingId,
  onEdit,
  editingId,
  editingIcon,
  onEditingIconChange,
  onCancelEdit,
  onSaveIcon,
  savingId,
}: Readonly<{
  entries: NutritionEntry[];
  emptyDescription: string;
  onRemove?: (entry: NutritionEntry) => void;
  removingId?: string | null;
  onEdit?: (entry: NutritionEntry) => void;
  editingId?: string | null;
  editingIcon?: FoodIconType | null;
  onEditingIconChange?: (iconType: FoodIconType | null) => void;
  onCancelEdit?: () => void;
  onSaveIcon?: (entry: NutritionEntry) => void;
  savingId?: string | null;
}>) {
  if (!entries.length) {
    return (
      <EmptyState
        title="No food logged yet"
        description={emptyDescription}
        action="Use manual entry"
        onAction={() => undefined}
      />
    );
  }

  return (
    <div className="space-y-2" data-testid="food-log-list">
      {entries.map((entry, index) => {
        const entryId = entry.food_log_id || `${entry.date}-${entry.food_name}-${index}`;
        const selectedIcon = normalizeFoodIconType(entry.iconType);
        const isOptimistic = String(entry.food_log_id ?? "").startsWith("optimistic:");
        const isEditing = Boolean(entry.food_log_id && editingId === entry.food_log_id);
        const isSaving = Boolean(entry.food_log_id && savingId === entry.food_log_id);
        const amountLabel = foodAmountLabel(entry);
        return (
          <div key={entryId} className="rounded-lg border border-white/10 bg-white/[0.035] p-3" data-testid="food-log-row">
            <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
              <div className="flex min-w-0 items-start gap-3">
                {selectedIcon ? (
                  <span className="accent-outline mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border">
                    <FoodIcon type={selectedIcon} className="h-5 w-5" />
                  </span>
                ) : null}
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="break-words font-semibold text-white">{entry.food_name || "Unnamed food"}</p>
                    {entry.meal_type ? <span className="rounded-full bg-white/[0.06] px-2 py-1 text-xs font-medium text-zinc-400">{entry.meal_type}</span> : null}
                    {isOptimistic ? <span className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-2 py-1 text-xs font-medium text-emerald-100">Queued</span> : null}
                  </div>
                  {amountLabel ? <p className="mt-1 text-xs text-zinc-500">{amountLabel}</p> : null}
                </div>
              </div>
              <div className="grid gap-2 sm:justify-items-end">
                <div className="flex flex-wrap gap-1.5 text-xs text-zinc-300 sm:justify-end">
                  <span className="accent-outline rounded-full border px-2 py-1">{formatFoodAmount(entry.calories)} kcal</span>
                  <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">P {formatFoodAmount(entry.protein)}g</span>
                  <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">C {formatFoodAmount(entry.carbs)}g</span>
                  <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">F {formatFoodAmount(entry.fat)}g</span>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
                  {onEdit ? (
                    <button
                      type="button"
                      onClick={() => onEdit(entry)}
                      disabled={!entry.food_log_id || isOptimistic || isSaving}
                      className="inline-flex w-fit items-center gap-2 rounded-lg border border-white/10 bg-white/[0.035] px-3 py-2 text-xs font-semibold text-zinc-200 transition hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-50"
                      aria-label={`Edit ${entry.food_name || "food entry"}`}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      Edit
                    </button>
                  ) : null}
                  {onRemove ? (
                    <button
                      type="button"
                      onClick={() => onRemove(entry)}
                      disabled={!entry.food_log_id || isOptimistic || removingId === entry.food_log_id || isSaving}
                      className="inline-flex w-fit items-center gap-2 rounded-lg border border-red-300/20 bg-red-300/5 px-3 py-2 text-xs font-semibold text-red-100 transition hover:bg-red-300/10 disabled:cursor-not-allowed disabled:opacity-50"
                      aria-label={`Remove ${entry.food_name || "food entry"}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      {removingId === entry.food_log_id ? "Removing..." : "Delete"}
                    </button>
                  ) : null}
                </div>
              </div>
            </div>

            {isEditing && onEditingIconChange && onCancelEdit && onSaveIcon ? (
              <div className="mt-4 border-t border-white/10 pt-4">
                <FoodIconPicker value={editingIcon ?? null} onChange={onEditingIconChange} />
                <div className="mt-3 flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    onClick={onCancelEdit}
                    disabled={isSaving}
                    className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-zinc-300 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <X className="h-3.5 w-3.5" />
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => onSaveIcon(entry)}
                    disabled={isSaving}
                    className="accent-bg inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Check className="h-3.5 w-3.5" />
                    {isSaving ? "Saving..." : "Save"}
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function FoodEntryDetails({ entry }: Readonly<{ entry: NutritionEntry }>) {
  const details = [
    ["Serving", entry.serving_description],
    ["Quantity", hasFoodDetail(entry.quantity) ? `${formatFoodAmount(entry.quantity, 1)} ${entry.unit ?? ""}`.trim() : ""],
    ["Grams", hasFoodDetail(entry.grams_consumed) ? `${formatFoodAmount(entry.grams_consumed, 1)}g` : ""],
    ["Serving size", hasFoodDetail(entry.serving_size_grams) ? `${formatFoodAmount(entry.serving_size_grams, 1)}g` : ""],
    ["Fiber", hasFoodDetail(entry.fiber) ? `${formatFoodAmount(entry.fiber, 1)}g` : ""],
    ["Sugar", hasFoodDetail(entry.sugar) ? `${formatFoodAmount(entry.sugar, 1)}g` : ""],
    ["Sodium", hasFoodDetail(entry.sodium) ? `${formatFoodAmount(entry.sodium)}mg` : ""],
    ["Potassium", hasFoodDetail(entry.potassium) ? `${formatFoodAmount(entry.potassium)}mg` : ""],
    ["Source", entry.source],
    ["Confidence", entry.confidence],
    ["Source ID", entry.source_id],
    ["Source URL", entry.source_url],
    ["Original text", entry.original_text],
    ["Assumptions", entry.assumptions],
    ["Created via", entry.created_via],
  ].filter(([, value]) => hasFoodDetail(value));

  if (!details.length) {
    return <p className="text-sm text-zinc-500">No extra details saved for this entry.</p>;
  }

  return (
    <dl className="grid gap-3 text-sm sm:grid-cols-2">
      {details.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <dt className="text-xs font-medium uppercase tracking-[0.14em] text-zinc-500">{label}</dt>
          <dd className="mt-1 break-words text-zinc-300">{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function FoodHistoryList({ logs, nutritionHistory }: Readonly<{ logs: NutritionEntry[]; nutritionHistory: DailyNutritionSummary[] }>) {
  const summaryByDate = new Map(nutritionHistory.map((day) => [day.date, day]));
  const groupedLogs = Array.from(
    logs.reduce((groups, entry) => {
      const entries = groups.get(entry.date) ?? [];
      entries.push(entry);
      groups.set(entry.date, entries);
      return groups;
    }, new Map<string, NutritionEntry[]>()),
  ).sort(([dateA], [dateB]) => dateB.localeCompare(dateA));

  if (!groupedLogs.length) {
    return <EmptyState title="No food history yet" description="Daily history will appear after food entries are saved." action="Log food" onAction={() => undefined} />;
  }

  return (
    <div className="space-y-3">
      {groupedLogs.map(([date, entries]) => {
        const summary = summaryByDate.get(date);
        const totals = summary
          ? { calories: summary.total_calories, protein: summary.total_protein, carbs: summary.total_carbs, fat: summary.total_fat }
          : entries.reduce(
              (dayTotals, entry) => ({
                calories: dayTotals.calories + (Number(entry.calories) || 0),
                protein: dayTotals.protein + (Number(entry.protein) || 0),
                carbs: dayTotals.carbs + (Number(entry.carbs) || 0),
                fat: dayTotals.fat + (Number(entry.fat) || 0),
              }),
              { calories: 0, protein: 0, carbs: 0, fat: 0 },
            );

        const isMissingLog = summary
          ? summary.nutrition_logged === false || (Number(summary.total_calories) || 0) <= 0
          : totals.calories <= 0;

        return (
          <div key={date} className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between">
              <h3 className="font-semibold text-white">{date}</h3>
              <p className={cx("text-sm", isMissingLog ? "text-amber-300/80" : "text-zinc-400")}>
                {isMissingLog ? "Missing food log" : foodMacroSummary(totals)}
              </p>
            </div>
            <div className="mt-3 space-y-2">
              {entries.slice().reverse().map((entry, index) => (
                <details key={`${date}-${entry.food_name}-${index}`} className="group rounded-lg border border-white/10 bg-zinc-950/45 p-3">
                  <summary className="flex cursor-pointer list-none items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="break-words font-semibold text-white">{entry.food_name || "Unnamed food"}</p>
                        {entry.meal_type ? <span className="rounded-full bg-white/[0.06] px-2 py-1 text-xs font-medium text-zinc-400">{entry.meal_type}</span> : null}
                      </div>
                      <p className="mt-1 text-sm text-zinc-400">{foodMacroSummary(entry)}</p>
                    </div>
                    <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-zinc-500 transition group-open:rotate-180" />
                  </summary>
                  <div className="mt-3 border-t border-white/10 pt-3">
                    <FoodEntryDetails entry={entry} />
                  </div>
                </details>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

type DailyMacroTotals = { calories: number; protein: number; carbs: number; fat: number; fiber: number };
type DailyMacroTargets = { target_calories: number; protein_grams: number; carb_grams: number; fat_grams: number };
type CompactMacroRow = { label: string; unit: string; consumed: number; target: number; bar: string };
type PresetFoodShortcut = FoodShortcut & { isDefaultPreset?: boolean };

const FOOD_PRESET_ICON_OPTIONS: Array<{ type: FoodPresetIconType; label: string }> = [
  { type: "oats", label: "Oats" },
  { type: "smoothie", label: "Smoothie" },
  { type: "bagel", label: "Bagel" },
  { type: "chicken", label: "Chicken" },
  { type: "meal_bowl", label: "Meal bowl" },
  { type: "protein_bar", label: "Protein bar" },
  { type: "protein_shake", label: "Protein shake" },
  { type: "rice_crispy_treat", label: "Rice treat" },
  { type: "eggs", label: "Eggs" },
  { type: "banana", label: "Banana" },
  { type: "rice", label: "Rice" },
  { type: "tuna", label: "Tuna" },
  { type: "yogurt", label: "Yogurt" },
  { type: "avocado", label: "Avocado" },
  { type: "salmon", label: "Salmon" },
  { type: "peanut_butter", label: "Peanut butter" },
];

const FOOD_PRESET_ICON_TYPES = new Set<FoodPresetIconType>(FOOD_PRESET_ICON_OPTIONS.map((option) => option.type));

function foodPresetIconType(shortcut: Pick<FoodShortcut, "icon_type" | "iconType" | "shortcut_name">): FoodPresetIconType {
  const selected = String(shortcut.icon_type || shortcut.iconType || "").trim() as FoodPresetIconType;
  if (FOOD_PRESET_ICON_TYPES.has(selected)) return selected;
  return "meal_bowl";
}

const DEFAULT_PRESET_FOODS: PresetFoodShortcut[] = [
  { shortcut_id: "default-preset-kirkland-bagel", shortcut_name: "Kirkland Bagel", icon_type: "bagel", calories: 260, protein: 11, carbs: 54, fat: 2, fiber: 2, sodium: 450, potassium: null, notes: "Seed preset. Edit to match your label.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-built-puff-bar", shortcut_name: "Built Puff Bar", icon_type: "protein_bar", calories: 140, protein: 17, carbs: 15, fat: 3, fiber: 0, sodium: null, potassium: null, notes: "Seed preset. Edit to match your label.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-nurri-shake", shortcut_name: "Nurri Shake", icon_type: "protein_shake", calories: 150, protein: 30, carbs: 3, fat: 3, fiber: 0, sodium: null, potassium: null, notes: "Seed preset. Edit to match your label.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-oats-overnight", shortcut_name: "Oats Overnight", icon_type: "oats", calories: 280, protein: 20, carbs: 35, fat: 7, fiber: 6, sodium: null, potassium: null, notes: "Seed preset. Edit to match your label.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-chicken-bowl", shortcut_name: "Chicken Bowl", icon_type: "meal_bowl", calories: 650, protein: 45, carbs: 70, fat: 20, fiber: 8, sodium: null, potassium: null, notes: "Seed preset. Edit to match your usual bowl.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-bibigo-rice", shortcut_name: "Bibigo Rice", icon_type: "rice", calories: 310, protein: 6, carbs: 68, fat: 1, fiber: 2, sodium: null, potassium: null, notes: "Seed preset. Edit to match your label.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-tuna", shortcut_name: "Tuna", icon_type: "tuna", calories: 120, protein: 26, carbs: 0, fat: 1, fiber: 0, sodium: null, potassium: null, notes: "Seed preset. Edit to match your label.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-fairlife-milk", shortcut_name: "Fairlife Milk", icon_type: "protein_shake", calories: 80, protein: 13, carbs: 6, fat: 0, fiber: 0, sodium: null, potassium: null, notes: "Seed preset. Edit to match your label.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-kirkland-chicken", shortcut_name: "Kirkland Chicken", icon_type: "chicken", calories: 140, protein: 22, carbs: 2, fat: 5, fiber: 0, sodium: null, potassium: null, notes: "Seed preset. Edit to match your label.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-eggs", shortcut_name: "Eggs", icon_type: "eggs", calories: 140, protein: 12, carbs: 1, fat: 10, fiber: 0, sodium: null, potassium: null, notes: "Seed preset. Edit to match your label.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-banana", shortcut_name: "Banana", icon_type: "banana", calories: 105, protein: 1, carbs: 27, fat: 0, fiber: 3, sodium: null, potassium: null, notes: "Seed preset. Edit to match your label.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-greek-yogurt", shortcut_name: "Greek Yogurt", icon_type: "yogurt", calories: 100, protein: 17, carbs: 6, fat: 0, fiber: 0, sodium: null, potassium: null, notes: "Seed preset. Edit to match your label.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-chipotle-bowl", shortcut_name: "Chipotle Bowl", icon_type: "meal_bowl", calories: 650, protein: 45, carbs: 70, fat: 20, fiber: 8, sodium: null, potassium: null, notes: "Seed preset. Edit to match your usual bowl.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-protein-shake", shortcut_name: "Protein Shake", icon_type: "protein_shake", calories: 160, protein: 30, carbs: 5, fat: 3, fiber: 0, sodium: null, potassium: null, notes: "Seed preset. Edit to match your label.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-peanut-butter", shortcut_name: "Peanut Butter", icon_type: "peanut_butter", calories: 190, protein: 7, carbs: 7, fat: 16, fiber: 2, sodium: null, potassium: null, notes: "Seed preset. Edit to match your label.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-chicken-breast", shortcut_name: "Chicken Breast", icon_type: "chicken", calories: 165, protein: 31, carbs: 0, fat: 4, fiber: 0, sodium: null, potassium: null, notes: "Seed preset.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-sweet-potato", shortcut_name: "Sweet Potato", icon_type: "meal_bowl", calories: 115, protein: 2, carbs: 27, fat: 0, fiber: 4, sodium: null, potassium: null, notes: "Seed preset.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-salmon", shortcut_name: "Salmon", icon_type: "salmon", calories: 240, protein: 34, carbs: 0, fat: 12, fiber: 0, sodium: null, potassium: null, notes: "Seed preset.", created_at: "", source: "default_preset", isDefaultPreset: true },
  { shortcut_id: "default-preset-avocado", shortcut_name: "Avocado", icon_type: "avocado", calories: 240, protein: 3, carbs: 12, fat: 22, fiber: 10, sodium: null, potassium: null, notes: "Seed preset.", created_at: "", source: "default_preset", isDefaultPreset: true },
];

function isDefaultPresetShortcut(shortcut: Pick<PresetFoodShortcut, "shortcut_id" | "isDefaultPreset">) {
  return Boolean(shortcut.isDefaultPreset || shortcut.shortcut_id.startsWith("default-preset-"));
}

function shortcutMutationPayload(shortcut: FoodShortcut) {
  return {
    shortcut_name: shortcut.shortcut_name,
    calories: Number(shortcut.calories) || 0,
    protein: Number(shortcut.protein) || 0,
    carbs: Number(shortcut.carbs) || 0,
    fat: Number(shortcut.fat) || 0,
    fiber: shortcut.fiber ?? null,
    sodium: shortcut.sodium ?? null,
    potassium: shortcut.potassium ?? null,
    serving_size_grams: shortcut.serving_size_grams ?? null,
    default_grams_consumed: shortcut.default_grams_consumed ?? null,
    calories_per_serving: shortcut.calories_per_serving ?? null,
    protein_per_serving: shortcut.protein_per_serving ?? null,
    carbs_per_serving: shortcut.carbs_per_serving ?? null,
    fat_per_serving: shortcut.fat_per_serving ?? null,
    notes: shortcut.notes ?? "",
    source: shortcut.source || "manual",
    icon_type: foodPresetIconType(shortcut),
  };
}

function shortcutQuickLogKey(shortcut: Pick<FoodShortcut, "shortcut_id">) {
  return `shortcut:${shortcut.shortcut_id}`;
}

function frequentFoodQuickLogKey(foodName: string) {
  return `frequent:${foodName}`;
}

function mealTemplateQuickLogKey(templateName: string) {
  return `template:${templateName}`;
}

function optimisticFoodEntry(
  id: string,
  date: string,
  foodName: string,
  macros: Pick<NutritionEntry, "calories" | "protein" | "carbs" | "fat"> & Partial<Pick<NutritionEntry, "fiber" | "sodium" | "potassium" | "iconType" | "serving_description" | "source">>,
): NutritionEntry {
  return {
    food_log_id: id,
    date,
    meal_type: DEFAULT_MEAL_TYPE,
    food_name: foodName,
    calories: finiteNumberOrNull(macros.calories) ?? 0,
    protein: finiteNumberOrNull(macros.protein) ?? 0,
    carbs: finiteNumberOrNull(macros.carbs) ?? 0,
    fat: finiteNumberOrNull(macros.fat) ?? 0,
    fiber: macros.fiber ?? null,
    sodium: macros.sodium ?? null,
    potassium: macros.potassium ?? null,
    iconType: macros.iconType ?? null,
    serving_description: macros.serving_description ?? "Queued preset",
    source: macros.source ?? "optimistic",
  };
}

function MacroDonutCard({
  totals,
  targets,
  rows,
  dateLabel,
  dayTypeMacros,
}: Readonly<{
  totals: DailyMacroTotals;
  targets: DailyMacroTargets | null;
  rows: CompactMacroRow[];
  dateLabel: string;
  dayTypeMacros?: OptimizationData["day_type_macros"] | null;
}>) {
  if (!targets) {
    return (
      <Card className="min-w-0">
        <SectionHeader eyebrow="Today" title={`Daily summary · ${dateLabel}`} />
        <p className="text-sm text-zinc-400">Set macro targets in Goals to see today&apos;s progress here.</p>
      </Card>
    );
  }

  const macroRings = rows.filter((row) => ["Protein", "Carbs", "Fat"].includes(row.label));
  const caloriePercent = targets.target_calories > 0 ? Math.min(100, (totals.calories / targets.target_calories) * 100) : 0;
  const calorieRadius = 48;
  const calorieCircumference = 2 * Math.PI * calorieRadius;
  const strokeColors: Record<string, string> = {
    Protein: "#5eead4",
    Carbs: "#93c5fd",
    Fat: "#fbbf24",
  };
  const caloriesLeft = Math.max(0, Math.round(targets.target_calories - totals.calories));
  const caloriesOver = Math.max(0, Math.round(totals.calories - targets.target_calories));

  return (
    <Card className="min-w-0 overflow-hidden">
      <SectionHeader eyebrow="Today" title={`Daily summary · ${dateLabel}`} />
      <div className="grid gap-5 lg:grid-cols-[180px_minmax(0,1fr)] lg:items-center">
        <div className="flex items-center gap-5 lg:block">
          <div className="relative h-36 w-36 shrink-0 lg:mx-auto">
            <svg className="-rotate-90" viewBox="0 0 112 112" aria-label="Daily nutrition completion">
              <circle cx="56" cy="56" r={calorieRadius} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="7" />
              <circle
                cx="56"
                cy="56"
                r={calorieRadius}
                fill="none"
                stroke="var(--accent-primary)"
                strokeLinecap="round"
                strokeWidth="7"
                strokeDasharray={calorieCircumference}
                strokeDashoffset={calorieCircumference - (calorieCircumference * caloriePercent) / 100}
                className="transition-[stroke-dashoffset] duration-700 ease-out"
              />
              {macroRings.map((row, index) => {
                const radius = 36 - index * 8;
                const ringCircumference = 2 * Math.PI * radius;
                const percent = row.target > 0 ? Math.min(100, (row.consumed / row.target) * 100) : 0;
                return (
                  <g key={row.label}>
                    <circle cx="56" cy="56" r={radius} fill="none" stroke="rgba(255,255,255,0.035)" strokeWidth="3.5" />
                    <circle
                      cx="56"
                      cy="56"
                      r={radius}
                      fill="none"
                      stroke={strokeColors[row.label] ?? "var(--accent-primary)"}
                      strokeOpacity="0.78"
                      strokeLinecap="round"
                      strokeWidth="3.5"
                      strokeDasharray={ringCircumference}
                      strokeDashoffset={ringCircumference - (ringCircumference * percent) / 100}
                      className="transition-[stroke-dashoffset] duration-700 ease-out"
                    />
                  </g>
                );
              })}
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
              <p className="text-2xl font-semibold text-white">{Math.round(targets.target_calories > 0 ? Math.min((totals.calories / targets.target_calories) * 100, 999) : 0)}%</p>
              <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-zinc-500">Daily</p>
            </div>
          </div>
          <div className="min-w-0 lg:mt-4 lg:text-center">
            <p className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">
              {Math.round(totals.calories).toLocaleString()} <span className="text-zinc-500">/</span> {Math.round(targets.target_calories).toLocaleString()}
            </p>
            <p className="mt-1 text-sm font-medium uppercase tracking-[0.18em] text-zinc-500">Calories</p>
            <p className={cx("mt-2 text-xs", caloriesOver > 0 ? "text-amber-300" : "text-zinc-400")}>
              {caloriesOver > 0 ? `${caloriesOver.toLocaleString()} over` : `${caloriesLeft.toLocaleString()} remaining`}
            </p>
          </div>
        </div>
        <div className="min-w-0 space-y-3">
          {rows.map((row) => {
            const consumed = Math.round(row.consumed);
            const target = Math.round(row.target);
            const remaining = Math.max(0, target - consumed);
            const over = Math.max(0, consumed - target);
            const percent = target > 0 ? Math.min(100, (consumed / target) * 100) : 0;
            return (
              <div key={row.label} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                <div className="flex min-w-0 items-baseline justify-between gap-3 text-sm">
                  <span className="font-medium text-zinc-200">{row.label}</span>
                  <span className="shrink-0 text-zinc-400">{consumed}{row.unit} / {target}{row.unit}</span>
                </div>
                <div className="mt-2 h-1.5 rounded-full bg-white/10">
                  <div className={cx("h-1.5 rounded-full transition-all duration-700 ease-out", row.bar)} style={{ width: `${percent}%` }} />
                </div>
                <div className="mt-1 flex items-center justify-between gap-3 text-xs text-zinc-500">
                  <span>{over > 0 ? `${over}${row.unit} over` : `${remaining}${row.unit} remaining`}</span>
                  <span>{Math.round(percent)}%</span>
                </div>
              </div>
            );
          })}
          {dayTypeMacros ? (
            <p className="accent-outline rounded-lg border px-3 py-2 text-xs leading-5">
              {dayTypeMacros.day_type}: {dayTypeMacros.reason}
            </p>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

function FoodPresetIcon({ type, className = "h-7 w-7" }: Readonly<{ type: FoodPresetIconType | string | null | undefined; className?: string }>) {
  const iconType = FOOD_PRESET_ICON_TYPES.has(type as FoodPresetIconType) ? type as FoodPresetIconType : "meal_bowl";
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    strokeWidth: 1.8,
  };
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={className}>
      {iconType === "oats" ? (
        <>
          <path {...common} d="M7 16h18l-2 6.5a5 5 0 0 1-4.8 3.5h-4.4A5 5 0 0 1 9 22.5L7 16Z" />
          <path {...common} d="M9 16c.5-2.8 3-5 7-5s6.5 2.2 7 5" />
          <path {...common} d="M13 14l2-3M17 14l2-3M12.5 20h.1M16 21h.1M19.5 20h.1" />
        </>
      ) : iconType === "smoothie" ? (
        <>
          <path {...common} d="M11 10h12l-1.4 15H12.4L11 10Z" />
          <path {...common} d="M10 10h14M18 10l4-5M14 15h6M14.5 20h5" />
        </>
      ) : iconType === "bagel" ? (
        <>
          <circle {...common} cx="16" cy="16" r="9" />
          <circle {...common} cx="16" cy="16" r="3.4" />
          <path {...common} d="M10.5 13.5c1.8-2 4.2-3 7.2-2.7M21.5 18.5c-1.8 2-4.2 3-7.2 2.7" />
        </>
      ) : iconType === "chicken" ? (
        <>
          <path {...common} d="M10 19c-2.2-3 .2-7 4.3-8.7 4.2-1.7 8.6-.5 9.8 2.8 1.2 3.2-1.2 7-5.4 8.7-3.5 1.4-7.1.8-8.7-2.8Z" />
          <path {...common} d="M9.5 19.5 6 23M6 23l-1.8-1.8M6 23l1.8 1.8" />
        </>
      ) : iconType === "protein_bar" ? (
        <>
          <rect {...common} x="7" y="11" width="18" height="10" rx="3" />
          <path {...common} d="M11 15h10M11 18h6" />
        </>
      ) : iconType === "protein_shake" ? (
        <>
          <path {...common} d="M11 9h10l-1.2 17h-7.6L11 9Z" />
          <path {...common} d="M10 9h12M13 6h6l2 3M13 15h7M13.5 20h6" />
        </>
      ) : iconType === "rice_crispy_treat" ? (
        <>
          <rect {...common} x="8" y="9" width="16" height="14" rx="3" />
          <path {...common} d="M12 13h.1M16 13h.1M20 13h.1M13.5 17h.1M18.5 17h.1M12 21h.1M20 21h.1" />
        </>
      ) : iconType === "eggs" ? (
        <>
          <ellipse {...common} cx="13" cy="17" rx="5" ry="7" />
          <ellipse {...common} cx="20" cy="16" rx="4.5" ry="6.5" />
        </>
      ) : iconType === "banana" ? (
        <>
          <path {...common} d="M8 10c5 8 10 10 17 7-3.2 5-9.3 7.8-14.5 4.4C7.1 19.2 6.2 14.6 8 10Z" />
          <path {...common} d="M8 10 6 8M25 17l1.8-1.2" />
        </>
      ) : iconType === "rice" ? (
        <>
          <path {...common} d="M8 15h16l-1.6 7.5a4 4 0 0 1-3.9 3.2h-5a4 4 0 0 1-3.9-3.2L8 15Z" />
          <path {...common} d="M11 15c1-3 2.8-5 5-5s4 2 5 5M14 13l1.2-3M18 13l-1.2-3" />
        </>
      ) : iconType === "tuna" ? (
        <>
          <path {...common} d="M7 18c3.5-5 9.6-6.5 16-2-6.4 4.5-12.5 3-16 2Z" />
          <path {...common} d="M23 16l3-3v6l-3-3ZM12 17h.1M16 14.5c1.2 1.1 1.2 2.1 0 3.2" />
        </>
      ) : iconType === "yogurt" ? (
        <>
          <path {...common} d="M10 11h12l-1.2 14h-9.6L10 11Z" />
          <path {...common} d="M9 11h14M12 7h8l1 4M13.5 16h5" />
        </>
      ) : iconType === "avocado" ? (
        <>
          <path {...common} d="M16 6c5.5 4.3 8 9 6 14.2-1.5 3.7-5.7 5.7-9.4 4.1-3.6-1.5-5.2-5.8-3.4-9.4C10.7 12 13.2 9.4 16 6Z" />
          <circle {...common} cx="16" cy="18" r="3.2" />
        </>
      ) : iconType === "salmon" ? (
        <>
          <path {...common} d="M8 18c3.7-4.4 9.2-6.2 16-2-2.5 4.9-9.1 6.5-16 2Z" />
          <path {...common} d="M12 20c1.2-2.8 4.2-4.8 9-5M24 16l2.5-2.5M13 16h.1" />
        </>
      ) : iconType === "peanut_butter" ? (
        <>
          <path {...common} d="M11 10h10l-1 16h-8l-1-16Z" />
          <path {...common} d="M12 6h8v4h-8zM13 16h6M13.5 20h5" />
        </>
      ) : (
        <>
          <path {...common} d="M7 15h18l-2 7a5 5 0 0 1-4.8 3.6h-4.4A5 5 0 0 1 9 22l-2-7Z" />
          <path {...common} d="M10 15c.9-3.2 3-5 6-5s5.1 1.8 6 5M13 10l-2-3M17 10l2-3" />
        </>
      )}
    </svg>
  );
}

function FoodPresetIconPicker({
  value,
  onChange,
}: Readonly<{
  value: FoodPresetIconType;
  onChange: (value: FoodPresetIconType) => void;
}>) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">Icon</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {FOOD_PRESET_ICON_OPTIONS.map((option) => {
          const selected = value === option.type;
          return (
            <button
              key={option.type}
              type="button"
              onClick={() => onChange(option.type)}
              className={cx(
                "group relative rounded-lg border p-2 text-left transition hover:bg-white/[0.05]",
                selected ? "accent-outline bg-white/[0.05]" : "border-white/10 bg-white/[0.025]",
              )}
            >
              <span className="flex items-center gap-2">
                <span className={cx("grid h-8 w-8 place-items-center rounded-md border", selected ? "border-[var(--accent-border)] text-[var(--accent-primary)]" : "border-white/10 text-zinc-400")}>
                  <FoodPresetIcon type={option.type} className="h-5 w-5" />
                </span>
                <span className="min-w-0 truncate text-xs font-semibold text-zinc-200">{option.label}</span>
              </span>
              {selected ? <Check className="absolute right-2 top-2 h-3.5 w-3.5 text-[var(--accent-primary)]" /> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function PresetFoodTile({
  shortcut,
  toneIndex,
  status,
  disabled,
  editing,
  editMode,
  onClick,
}: Readonly<{
  shortcut: PresetFoodShortcut;
  toneIndex: number;
  status?: QuickFoodLogStatus;
  disabled?: boolean;
  editing: boolean;
  editMode: boolean;
  onClick: () => void;
}>) {
  const tone = FOOD_PRESET_TILE_TONES[toneIndex % FOOD_PRESET_TILE_TONES.length];
  const pendingCount = status?.pending ?? 0;
  const label = status?.error
    ? "Retry"
    : pendingCount > 1
      ? `Adding ${pendingCount}`
      : pendingCount === 1
        ? "Adding..."
        : status?.added
          ? "Added"
          : shortcut.shortcut_name;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cx(
        "group relative aspect-square min-w-0 rounded-lg border p-2 text-center text-xs font-semibold text-white transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60",
        editing ? "accent-outline" : "border-white/10",
      )}
      style={{ backgroundColor: tone.backgroundColor, borderColor: tone.borderColor }}
      title={editMode ? `Edit ${shortcut.shortcut_name}` : `Add ${shortcut.shortcut_name} to today`}
    >
      {editMode ? <Pencil className="absolute right-2 top-2 h-3.5 w-3.5 text-zinc-500" /> : null}
      {status?.added ? <Check className="absolute right-2 top-2 h-3.5 w-3.5 text-emerald-200" /> : null}
      {pendingCount > 1 ? <span className="absolute left-2 top-2 rounded-full border border-white/10 bg-black/30 px-1.5 py-0.5 text-[10px] text-zinc-100">{pendingCount}</span> : null}
      <span className="flex h-full flex-col items-center justify-center gap-2">
        <span className="grid h-10 w-10 place-items-center rounded-lg border border-white/10 bg-black/20 text-zinc-300 transition group-hover:border-[var(--accent-border)] group-hover:text-[var(--accent-primary)]">
          <FoodPresetIcon type={foodPresetIconType(shortcut)} className="h-6 w-6" />
        </span>
        <span className={cx("line-clamp-2 break-words leading-4", status?.error ? "text-red-100" : "")}>{label}</span>
      </span>
    </button>
  );
}

const FOOD_PRESET_TILE_TONES = [
  { backgroundColor: "rgba(74, 222, 128, 0.08)", borderColor: "rgba(74, 222, 128, 0.28)" },
  { backgroundColor: "rgba(56, 189, 248, 0.08)", borderColor: "rgba(56, 189, 248, 0.28)" },
  { backgroundColor: "rgba(168, 85, 247, 0.08)", borderColor: "rgba(168, 85, 247, 0.28)" },
  { backgroundColor: "rgba(251, 146, 60, 0.08)", borderColor: "rgba(251, 146, 60, 0.28)" },
  { backgroundColor: "rgba(244, 114, 182, 0.08)", borderColor: "rgba(244, 114, 182, 0.28)" },
  { backgroundColor: "rgba(45, 212, 191, 0.08)", borderColor: "rgba(45, 212, 191, 0.28)" },
] as const;

function PresetFoodEditor({
  shortcut,
  saving,
  onChange,
  onSave,
  onCancel,
}: Readonly<{
  shortcut: PresetFoodShortcut;
  saving: boolean;
  onChange: (shortcut: PresetFoodShortcut) => void;
  onSave: () => void;
  onCancel: () => void;
}>) {
  return (
    <div className="rounded-lg border border-white/10 bg-zinc-950/50 p-4">
      <FoodPresetIconPicker value={foodPresetIconType(shortcut)} onChange={(icon_type) => onChange({ ...shortcut, icon_type })} />
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <TextInput label="Name" value={shortcut.shortcut_name} onChange={(value) => onChange({ ...shortcut, shortcut_name: value })} />
        <TextInput label="Notes optional" value={shortcut.notes ?? ""} onChange={(value) => onChange({ ...shortcut, notes: value })} />
        <TextInput label="Calories" type="number" min={0} step="any" value={shortcut.calories} onChange={(value) => onChange({ ...shortcut, calories: Number(value) })} />
        <TextInput label="Protein" type="number" min={0} step="any" value={shortcut.protein} onChange={(value) => onChange({ ...shortcut, protein: Number(value) })} />
        <TextInput label="Carbs" type="number" min={0} step="any" value={shortcut.carbs} onChange={(value) => onChange({ ...shortcut, carbs: Number(value) })} />
        <TextInput label="Fat" type="number" min={0} step="any" value={shortcut.fat} onChange={(value) => onChange({ ...shortcut, fat: Number(value) })} />
        <TextInput label="Serving grams optional" type="number" min={0} step="any" value={shortcut.serving_size_grams ?? ""} onChange={(value) => onChange({ ...shortcut, serving_size_grams: value === "" ? null : Number(value) })} />
        <TextInput label="Amount grams optional" type="number" min={0} step="any" value={shortcut.default_grams_consumed ?? ""} onChange={(value) => onChange({ ...shortcut, default_grams_consumed: value === "" ? null : Number(value) })} />
        <TextInput label="Fiber optional" type="number" min={0} step="any" value={shortcut.fiber ?? ""} onChange={(value) => onChange({ ...shortcut, fiber: value === "" ? null : Number(value) })} />
        <TextInput label="Sodium optional mg" type="number" min={0} step="any" value={shortcut.sodium ?? ""} onChange={(value) => onChange({ ...shortcut, sodium: value === "" ? null : Number(value) })} />
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={onSave} disabled={saving || !shortcut.shortcut_name.trim()} className="accent-bg rounded-lg px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60">
          {saving ? "Saving..." : isDefaultPresetShortcut(shortcut) ? "Save preset" : "Save edits"}
        </button>
        <button type="button" onClick={onCancel} disabled={saving} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-50">
          Cancel
        </button>
      </div>
    </div>
  );
}

function SupplementsTile({
  date,
}: Readonly<{
  date: string;
}>) {
  const storageKey = `performance-os-supplements-taken-${date}`;
  const [takenByKey, setTakenByKey] = useState<Record<string, boolean>>({});
  const storedTaken = typeof window !== "undefined" && window.localStorage.getItem(storageKey) === "true";
  const taken = takenByKey[storageKey] ?? storedTaken;

  const toggleTaken = () => {
    setTakenByKey((currentByKey) => {
      const current = currentByKey[storageKey] ?? storedTaken;
      const next = !current;
      if (typeof window !== "undefined") {
        window.localStorage.setItem(storageKey, String(next));
      }
      return { ...currentByKey, [storageKey]: next };
    });
  };

  return (
    <button
      type="button"
      onClick={toggleTaken}
      aria-pressed={taken}
      className={cx(
        "group w-full rounded-xl border p-4 text-left transition duration-300",
        taken
          ? "border-cyan-300/30 bg-cyan-300/[0.08] shadow-[0_0_28px_rgba(34,211,238,0.10)]"
          : "border-white/10 bg-white/[0.035] hover:border-white/15 hover:bg-white/[0.055]",
      )}
    >
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-white">Supplements</p>
          <p className={cx("mt-1 text-sm transition", taken ? "text-cyan-100" : "text-zinc-400")}>
            {taken ? "Taken today" : "Mark today’s supplements as taken"}
          </p>
        </div>
        <span
          className={cx(
            "grid h-11 w-11 shrink-0 place-items-center rounded-full border transition duration-300",
            taken
              ? "border-cyan-200/50 bg-cyan-200/15 text-cyan-100 shadow-[0_0_18px_rgba(34,211,238,0.18)]"
              : "border-white/15 bg-black/20 text-zinc-500 group-hover:text-zinc-300",
          )}
        >
          <Check className={cx("h-5 w-5 transition duration-300", taken ? "scale-100 opacity-100" : "scale-75 opacity-0")} />
          {!taken ? <span className="absolute h-4 w-4 rounded-sm border border-current" /> : null}
        </span>
      </div>
    </button>
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
      <button onClick={onAction} className="accent-bg mt-4 inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold">
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
  const isNumeric = type === "number";
  const [focusedNumericValue, setFocusedNumericValue] = useState<string | null>(null);
  const displayValue = isNumeric && focusedNumericValue !== null ? focusedNumericValue : value;
  const clearZeroOnFocus = () => {
    if (!isNumeric) return;
    if (value === 0 || value === "0") {
      setFocusedNumericValue("");
    }
  };
  const handleChange = (nextValue: string) => {
    if (isNumeric) {
      setFocusedNumericValue(nextValue);
    }
    onChange(nextValue);
  };
  const handleBlur = () => {
    if (isNumeric) {
      setFocusedNumericValue(null);
    }
  };

  return (
    <label className="space-y-2 text-sm text-zinc-400">
      <span>{label}</span>
      <input
        className="accent-focus h-11 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 text-zinc-100 outline-none transition placeholder:text-zinc-600"
        value={displayValue}
        type={type}
        placeholder={placeholder}
        required={required}
        min={min}
        step={step}
        disabled={disabled}
        onFocus={clearZeroOnFocus}
        onBlur={handleBlur}
        onChange={(event) => handleChange(event.target.value)}
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
        className="accent-focus h-11 w-full rounded-lg border border-white/10 bg-zinc-950 px-3 text-zinc-100 outline-none transition"
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

function normalizeSearchText(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
}

function looksLikeMultiFoodQuery(value: string) {
  return /,|\/|\+|&|\n|\b(and|plus|with)\b/i.test(value);
}

function savedFoodMatchesQuery(query: string, name: string) {
  if (!query || !name) return false;
  if (query === name) return true;
  if (looksLikeMultiFoodQuery(query)) return false;
  return name.includes(query);
}

type SavedFoodMatch =
  | { type: "shortcut"; label: string; id: string; item: FoodShortcut | PresetFoodShortcut }
  | { type: "frequent"; label: string; id: string; item: NutritionShortcutData["frequent_foods"][number] }
  | { type: "template"; label: string; id: string };

function findSavedFoodMatch(text: string, shortcuts: Array<FoodShortcut | PresetFoodShortcut>, templates: MealTemplate[], frequentFoods: NutritionShortcutData["frequent_foods"] = []): SavedFoodMatch | null {
  const query = normalizeSearchText(text);
  if (!query) {
    return null;
  }
  const shortcut = shortcuts.find((item) => {
    const name = normalizeSearchText(item.shortcut_name);
    return savedFoodMatchesQuery(query, name);
  });
  if (shortcut) {
    return { type: "shortcut" as const, label: shortcut.shortcut_name, id: shortcut.shortcut_id, item: shortcut };
  }
  const frequent = frequentFoods.find((item) => {
    const name = normalizeSearchText(item.food_name);
    return savedFoodMatchesQuery(query, name);
  });
  if (frequent) {
    return { type: "frequent" as const, label: frequent.food_name, id: frequent.food_name, item: frequent };
  }
  const templateNames = Array.from(new Set(templates.map((item) => item.template_name)));
  const templateName = templateNames.find((name) => {
    const normalized = normalizeSearchText(name);
    return savedFoodMatchesQuery(query, normalized);
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

function calculateMacroCalories(protein: unknown, carbs: unknown, fat: unknown) {
  const proteinGrams = finiteNumberOrNull(protein) ?? 0;
  const carbGrams = finiteNumberOrNull(carbs) ?? 0;
  const fatGrams = finiteNumberOrNull(fat) ?? 0;
  const calories = proteinGrams * 4 + carbGrams * 4 + fatGrams * 9;
  return Math.round(calories * 10) / 10;
}

const FOOD_PROGRESS_COLOR_STOPS = [
  { percent: 0, color: [248, 113, 113] },
  { percent: 35, color: [251, 146, 60] },
  { percent: 70, color: [234, 179, 8] },
  { percent: 100, color: [34, 197, 94] },
  { percent: 125, color: [74, 222, 128] },
] as const;

function dashboardFoodProgressColor(percent: number) {
  const safePercent = Math.min(Math.max(Number(percent) || 0, 0), 125);
  const upperIndex = FOOD_PROGRESS_COLOR_STOPS.findIndex((stop) => safePercent <= stop.percent);
  const upper = FOOD_PROGRESS_COLOR_STOPS[upperIndex === -1 ? FOOD_PROGRESS_COLOR_STOPS.length - 1 : upperIndex];
  const lower = FOOD_PROGRESS_COLOR_STOPS[Math.max((upperIndex === -1 ? FOOD_PROGRESS_COLOR_STOPS.length - 1 : upperIndex) - 1, 0)];
  const range = Math.max(upper.percent - lower.percent, 1);
  const amount = (safePercent - lower.percent) / range;
  const [red, green, blue] = upper.color.map((channel, index) => Math.round(lower.color[index] + (channel - lower.color[index]) * amount));
  return `rgb(${red}, ${green}, ${blue})`;
}

function DashboardProgressLine({ label, value, target, left, over, percent, unit = "g" }: Readonly<{
  label: string;
  value: unknown;
  target: unknown;
  left: unknown;
  over: unknown;
  percent: unknown;
  unit?: string;
}>) {
  const moleculeKind = macroMoleculeKind(label);
  const safeValue = finiteNumberOrNull(value) ?? 0;
  const safeTarget = finiteNumberOrNull(target);
  const safeLeft = finiteNumberOrNull(left) ?? (safeTarget !== null ? Math.max(safeTarget - safeValue, 0) : null);
  const safeOver = finiteNumberOrNull(over) ?? (safeTarget !== null ? Math.max(safeValue - safeTarget, 0) : null);
  const rawPercent = finiteNumberOrNull(percent) ?? (safeTarget && safeTarget > 0 ? (safeValue / safeTarget) * 100 : 0);
  const progressPercent = safeTarget && safeTarget > 0 ? Math.max(0, Math.min(100, rawPercent)) : 0;
  return (
    <div>
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="inline-flex items-center gap-2 text-zinc-400">
          {moleculeKind ? <MacroMoleculeIcon kind={moleculeKind} className="h-4 w-4" /> : null}
          {label}
        </span>
        <span className="font-medium text-zinc-100">
          {Math.round(safeValue)}{unit === "kcal" ? "" : unit} / {safeTarget ? `${Math.round(safeTarget)}${unit === "kcal" ? "" : unit}` : "No target"}
        </span>
      </div>
      <div className="mt-2 h-2 rounded-full bg-white/10">
        <div
          className="h-2 rounded-full"
          style={{
            width: `${progressPercent}%`,
            backgroundColor: dashboardFoodProgressColor(progressPercent),
            transition: "width 200ms ease, background-color 250ms ease",
          }}
        />
      </div>
      <p className="mt-1 text-xs text-zinc-500">
        {!safeTarget ? "Set macro targets." : safeOver && safeOver > 0 ? `+${Math.round(safeOver)}${unit === "kcal" ? " kcal" : unit} over` : `${Math.round(safeLeft ?? 0)}${unit === "kcal" ? " kcal" : unit} left`}
      </p>
    </div>
  );
}

function normalizeDashboardMacroProgress(raw: unknown, fallbackTarget?: unknown): DashboardData["food"]["calories"] {
  const record = recordOrEmpty(raw);
  const eaten = finiteNumberOrNull(record.eaten) ?? 0;
  const target = finiteNumberOrNull(record.target) ?? finiteNumberOrNull(fallbackTarget);
  const left = finiteNumberOrNull(record.left) ?? (target !== null ? Math.max(target - eaten, 0) : null);
  const over = finiteNumberOrNull(record.over) ?? (target !== null ? Math.max(eaten - target, 0) : null);
  const percent = finiteNumberOrNull(record.percent) ?? (target && target > 0 ? (eaten / target) * 100 : 0);
  return {
    eaten,
    target,
    left,
    over,
    percent: Math.max(0, Math.min(100, percent)),
  };
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

function workoutQualityScorePercent(score?: unknown) {
  const parsed = finiteNumberOrNull(score);
  if (parsed === null) return 0;
  return Math.min(100, Math.max(0, parsed <= 10 ? parsed * 10 : parsed));
}

function workoutQualityScoreText(score?: unknown) {
  const parsed = finiteNumberOrNull(score);
  if (parsed === null) return "--";
  return parsed <= 10 ? parsed.toFixed(1) : `${Math.round(parsed)}`;
}

function formatWorkoutQualityPct(value?: unknown) {
  const parsed = finiteNumberOrNull(value);
  if (parsed === null) return "";
  return `${parsed >= 0 ? "+" : ""}${Math.round(parsed * 100)}%`;
}

function workoutQualityComparisonText(comparison?: unknown) {
  if (!comparison) return "";
  if (typeof comparison === "string") return comparison;
  const comparisonRecord = recordOrEmpty(comparison);
  const summary = stringOrFallback(comparisonRecord.summary);
  if (summary) return summary;
  const avgSetChange = finiteNumberOrNull(comparisonRecord.avg_set_volume_pct_change);
  const volumeChange = finiteNumberOrNull(comparisonRecord.volume_vs_average_pct);
  const setsChange = finiteNumberOrNull(comparisonRecord.sets_vs_average_pct);
  const sampleSize = finiteNumberOrNull(comparisonRecord.sample_size);
  const pieces = [
    avgSetChange !== null ? `avg set ${formatWorkoutQualityPct(avgSetChange)}` : "",
    volumeChange !== null ? `volume ${volumeChange > 0 ? "+" : ""}${volumeChange}%` : "",
    setsChange !== null ? `sets ${setsChange > 0 ? "+" : ""}${setsChange}%` : "",
    sampleSize !== null ? `${Math.round(sampleSize)} similar` : "",
  ].filter(Boolean);
  return pieces.join(" · ");
}

type TargetDecisionNotice = {
  message: string;
  confidence: string;
  tone: "emerald" | "amber";
};

function usefulTargetDecisionNotice(
  nutritionRecommendation?: OptimizationSignals["nutrition_recommendation"] | null,
  adaptiveRecommendation?: AdaptiveNutritionRecommendation | null,
): TargetDecisionNotice | null {
  const confidence = stringOrFallback(
    nutritionRecommendation?.confidence,
    recommendationConfidenceLabel(adaptiveRecommendation?.confidence, adaptiveRecommendation?.confidenceLevel),
  );
  const normalizedConfidence = confidence.toLowerCase();
  const normalizedDecision = String(nutritionRecommendation?.decision ?? adaptiveRecommendation?.recommendation_trace?.decision ?? "").toLowerCase();
  const normalizedStatus = String(nutritionRecommendation?.status ?? "").toLowerCase().replace(/[_-]/g, " ");
  const macroChanges = recordOrEmpty(adaptiveRecommendation?.macroChanges ?? adaptiveRecommendation?.macroAdjustment);
  const calorieAdjustment = finiteNumberOrNull(nutritionRecommendation?.calorie_adjustment)
    ?? finiteNumberOrNull(adaptiveRecommendation?.calorieAdjustment)
    ?? finiteNumberOrNull(macroChanges.calories)
    ?? 0;
  const reason = stringOrFallback(nutritionRecommendation?.primary_reason, stringList(adaptiveRecommendation?.reasoning)[0] ?? "").trim();
  const reasonSentence = reason ? ` ${reason}` : "";
  const changedMacros = (["protein", "carbs", "fat"] as const).filter((key) => Math.abs(finiteNumberOrNull(macroChanges[key]) ?? 0) >= 1);

  if (Math.abs(calorieAdjustment) >= 1) {
    return {
      message: `Targets updated: ${calorieAdjustment > 0 ? "+" : ""}${Math.round(calorieAdjustment)} calories today.${reasonSentence}`,
      confidence,
      tone: "emerald",
    };
  }

  if (changedMacros.length > 0) {
    return {
      message: `Targets updated: ${changedMacros.join(", ")} adjusted today.${reasonSentence}`,
      confidence,
      tone: "emerald",
    };
  }

  const holdingForLowConfidence = normalizedConfidence.includes("low")
    && (normalizedDecision === "hold" || normalizedStatus.includes("insufficient") || normalizedStatus.includes("low confidence"));

  if (holdingForLowConfidence) {
    return {
      message: "Targets held: confidence is low, continuing baseline targets.",
      confidence,
      tone: "amber",
    };
  }

  return null;
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

function Dashboard({
  data,
  setActivePage,
}: Readonly<{
  data: DashboardData | null;
  setActivePage: (page: PageId) => void;
}>) {
  const [signalsExpanded, setSignalsExpanded] = useState(false);
  const food = data?.food;
  const weight = data?.weight;
  const recovery = data?.recovery;
  const lift = data?.lift_performance;
  const workoutQuality = data?.workout_quality;
  const targetRecord = recordOrEmpty(data?.targets);
  const calorieTarget = finiteNumberOrNull(targetRecord.target_calories) ?? finiteNumberOrNull(food?.calories?.target) ?? DEFAULT_BASELINE_CALORIES;
  const safeFood = {
    calories: normalizeDashboardMacroProgress(food?.calories, calorieTarget),
    protein: normalizeDashboardMacroProgress(food?.protein, finiteNumberOrNull(targetRecord.protein_grams)),
    carbs: normalizeDashboardMacroProgress(food?.carbs, finiteNumberOrNull(targetRecord.carb_grams)),
    fat: normalizeDashboardMacroProgress(food?.fat, finiteNumberOrNull(targetRecord.fat_grams)),
  };
  const hasFoodTargets = Boolean(food?.has_targets) || safeFood.calories.target !== null;
  const hasFoodLogged = Boolean(food?.has_food_logged);
  const todayWeight = finiteNumberOrNull(weight?.today_weight);
  const sevenDayWeight = finiteNumberOrNull(weight?.seven_day_average);
  const weightHistory = arrayOrEmpty<BodyMetricEntry>(weight?.history);
  const qualityStyles = workoutQualityStyles(workoutQuality?.color ?? "gray");
  const qualityScorePercent = workoutQualityScorePercent(workoutQuality?.score);
  const qualityComparison = workoutQualityComparisonText(workoutQuality?.comparison);
  const workoutQualityTitle = stringOrFallback(workoutQuality?.title, stringOrFallback(workoutQuality?.workout_type));
  const workoutQualityMeta = [
    stringOrFallback(workoutQuality?.date),
    stringOrFallback(workoutQuality?.classification_label, stringOrFallback(workoutQuality?.classification)),
  ].filter(Boolean).join(" · ");
  const qualityExerciseChanges = arrayOrEmpty<NonNullable<DashboardData["workout_quality"]["exercise_breakdown"]>[number]>(workoutQuality?.exercise_breakdown)
    .filter((item) => finiteNumberOrNull(item.avg_set_volume_pct_change) !== null)
    .slice(0, 3)
    .map((item) => `${item.exercise} ${formatWorkoutQualityPct(item.avg_set_volume_pct_change)}`)
    .join(", ");
  const workoutMuscleGroups = stringList(workoutQuality?.muscle_groups).slice(0, 3);
  const personalLearning = data?.personal_learning;
  const weeklyReport = data?.weekly_report;
  const optimization = data?.optimization;
  const optimizationSignals = data?.optimization_signals;
  const nutritionRecommendation = optimizationSignals?.nutrition_recommendation;
  const macroAdherence = optimizationSignals?.macro_adherence ?? optimization?.macro_adherence;
  const plateauWatch = optimizationSignals?.plateau_watch ?? optimization?.plateau_detection;
  const baselineSignal = optimizationSignals?.personal_baseline ?? optimization?.personal_baseline;
  const dashboardInsight = baselineSignal?.dashboard_insight;
  const topPlateauAlerts = arrayOrEmpty<OptimizationData["plateau_detection"]["top_alerts"][number]>(plateauWatch?.top_alerts);
  const adaptiveRecommendation = data?.adaptive_recommendation;
  const targetDecisionNotice = usefulTargetDecisionNotice(nutritionRecommendation, adaptiveRecommendation);
  const topAdaptiveWarning = stringList(optimizationSignals?.confidence?.missing_data)[0] ?? stringList(adaptiveRecommendation?.warnings)[0] ?? stringList(adaptiveRecommendation?.missingDataWarnings)[0] ?? null;
  const recommendationConfidence = stringOrFallback(nutritionRecommendation?.confidence, recommendationConfidenceLabel(adaptiveRecommendation?.confidence, adaptiveRecommendation?.confidenceLevel));
  const recommendationDataQualityScore = finiteNumberOrNull(nutritionRecommendation?.data_quality_score) ?? finiteNumberOrNull(adaptiveRecommendation?.dataQualityScore) ?? 0;
  const recommendationTitle = stringOrFallback(
    nutritionRecommendation?.title,
    adaptiveRecommendation?.calorieAdjustment === 0 ? "Hold targets" : `${adaptiveRecommendation?.calorieAdjustment && adaptiveRecommendation.calorieAdjustment > 0 ? "+" : ""}${adaptiveRecommendation?.calorieAdjustment ?? 0} kcal adjustment`,
  );
  const recommendationReason = stringOrFallback(nutritionRecommendation?.primary_reason, stringList(adaptiveRecommendation?.reasoning)[0] ?? "Insufficient data for a nutrition recommendation.");
  const personalLearningInsights = arrayOrEmpty<PersonalLearning["insights"][number]>(personalLearning?.insights);
  const baselineTitle = stringOrFallback(dashboardInsight?.title, stringOrFallback(personalLearningInsights[0]?.title, "Building baseline"));
  const baselineSummary = stringOrFallback(dashboardInsight?.summary, stringOrFallback(personalLearningInsights[0]?.explanation, "Insufficient overlapping data for a stable personal baseline."));
  const plannedWorkout = stringOrFallback(lift?.planned_workout, "Training");
  const completedTraining = stringOrFallback(lift?.completed_summary);
  const trainingSources = stringList(lift?.sources);
  const runSummary = recordOrEmpty(lift?.run_summary);
  const runDistanceMiles = finiteNumberOrNull(runSummary.distance_miles);
  const runCount = finiteNumberOrNull(runSummary.run_count) ?? 0;
  const runDurationMinutes = finiteNumberOrNull(runSummary.duration_minutes);
  const runPace = finiteNumberOrNull(runSummary.average_pace_min_per_mile);
  const runCalories = finiteNumberOrNull(runSummary.calories_burned);
  const runHeartRate = finiteNumberOrNull(runSummary.average_heart_rate);
  const todayVolume = finiteNumberOrNull(lift?.today_volume);
  const recoveryScore = finiteNumberOrNull(recovery?.latest_score);
  const extraRunReasoning = stringList(recovery?.extra_run_readiness?.reasoning);
  const macroWeeklyScore = finiteNumberOrNull(macroAdherence?.weekly_score);
  const failedDashboardBlocks = arrayOrEmpty<DashboardDebugBlock>(data?.debug?.errors ?? data?.errors).filter((block) => block.status === "error" || block.error_type);
  const dashboardDegraded = data?.debug?.dashboard_status === "degraded" && failedDashboardBlocks.length > 0;

  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,280px),1fr))] gap-4">
      {dashboardDegraded ? (
        <Card className="col-span-full border-amber-400/30 bg-amber-400/10">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-200" />
                <p className="font-medium text-amber-100">Dashboard loaded in degraded mode</p>
              </div>
              <p className="mt-2 text-sm text-amber-100/75">Core tiles are available. Advanced backend blocks failed and are using fallback data.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {failedDashboardBlocks.slice(0, 5).map((block) => (
                  <span key={`${block.block ?? block.name}-${block.error_type ?? block.message}`} className="rounded-full border border-amber-300/25 bg-amber-300/10 px-2.5 py-1 text-xs text-amber-50">
                    {block.block ?? block.name}: {block.error_type ?? "error"}
                  </span>
                ))}
              </div>
            </div>
            {data?.debug?.generated_at ? <p className="text-xs text-amber-100/60">Generated {data.debug.generated_at}</p> : null}
          </div>
        </Card>
      ) : null}
      {targetDecisionNotice ? (
        <div className={cx(
          "col-span-full rounded-lg border px-4 py-3 text-sm shadow-[0_12px_40px_rgba(0,0,0,0.18)] backdrop-blur",
          targetDecisionNotice.tone === "amber"
            ? "border-amber-300/20 bg-amber-300/[0.07] text-amber-50"
            : "border-emerald-300/20 bg-emerald-300/[0.07] text-emerald-50",
        )}>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="leading-6">{targetDecisionNotice.message}</p>
            <span className={cx(
              "w-fit rounded-full border px-2.5 py-1 text-xs font-semibold capitalize",
              targetDecisionNotice.tone === "amber"
                ? "border-amber-300/25 bg-amber-300/10 text-amber-100"
                : "border-emerald-300/25 bg-emerald-300/10 text-emerald-100",
            )}>
              {targetDecisionNotice.confidence} confidence
            </span>
          </div>
        </div>
      ) : null}
      <TargetSectionErrorBoundary title="Food tile unavailable" description="Insufficient target data for today's food tile." resetKey={`${data?.date ?? ""}-${calorieTarget}`}>
        <Card className="xl:col-span-2">
          <SectionHeader eyebrow="Today" title="Food" action={<button onClick={() => setActivePage("food")} className="accent-bg rounded-lg px-3 py-2 text-sm font-semibold">Log food</button>} />
          {hasFoodTargets ? (
            <div className="space-y-4">
              <DashboardProgressLine label="Calories" value={safeFood.calories.eaten} target={safeFood.calories.target} left={safeFood.calories.left} over={safeFood.calories.over} percent={safeFood.calories.percent} unit="kcal" />
              <DashboardProgressLine label="Protein" value={safeFood.protein.eaten} target={safeFood.protein.target} left={safeFood.protein.left} over={safeFood.protein.over} percent={safeFood.protein.percent} />
              <DashboardProgressLine label="Carbs" value={safeFood.carbs.eaten} target={safeFood.carbs.target} left={safeFood.carbs.left} over={safeFood.carbs.over} percent={safeFood.carbs.percent} />
              <DashboardProgressLine label="Fat" value={safeFood.fat.eaten} target={safeFood.fat.target} left={safeFood.fat.left} over={safeFood.fat.over} percent={safeFood.fat.percent} />
              {!hasFoodLogged ? <p className="rounded-lg border border-white/10 bg-white/[0.035] p-3 text-sm text-zinc-400">No food logged yet. Start at 0 progress.</p> : null}
            </div>
          ) : (
            <EmptyState title="Set macro targets." description="Goals & Targets powers calorie and macro progress." action="Set targets" onAction={() => setActivePage("goals")} />
          )}
        </Card>
      </TargetSectionErrorBoundary>

      <Card>
        <SectionHeader eyebrow="Check-in" title="Weight" action={<button onClick={() => setActivePage("recovery")} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Enter weight</button>} />
        <p className="text-3xl font-semibold text-white">{todayWeight !== null ? `${todayWeight.toFixed(1)} lb` : "Enter today's weight"}</p>
        <p className="mt-2 text-sm text-zinc-400">7-day avg: {sevenDayWeight !== null ? `${sevenDayWeight.toFixed(1)} lb` : "Need data"}</p>
        <p className="mt-2 inline-flex rounded-full border border-blue-300/20 bg-blue-300/10 px-3 py-1 text-xs text-blue-100">{weight?.trend_label ?? "insufficient data"}</p>
        {weightHistory.length ? (
          <ChartFrame className="mt-4 h-28">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={weightHistory}>
                <Area dataKey="bodyweight" stroke="#60a5fa" fill="#60a5fa" fillOpacity={0.2} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </ChartFrame>
        ) : <p className="mt-4 text-sm text-zinc-500">{weight?.message ?? "No bodyweight data yet."}</p>}
      </Card>

      <TargetSectionErrorBoundary title="Training tile unavailable" description="Training and workout-quality data could not render safely." resetKey={`${data?.date ?? ""}-${workoutQuality?.score ?? ""}`}>
        <Card className="xl:col-span-2">
          <SectionHeader eyebrow="Training" title="Today's Training" action={<button onClick={() => setActivePage("training")} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Training</button>} />
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(240px,0.7fr)]">
            <div className="space-y-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">Planned</p>
                <p className="mt-1 text-xl font-semibold text-white">Today: {plannedWorkout}</p>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">Completed</p>
                <p className="mt-1 text-sm font-semibold text-zinc-100">{completedTraining ? `Completed: ${completedTraining}` : "Workout not logged yet"}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <span className={cx("rounded-full border px-2.5 py-1 text-xs font-medium", lift?.schedule_match === "matched" || lift?.schedule_match === "matched_plus_extra_run" ? "border-emerald-300/25 bg-emerald-300/10 text-emerald-100" : lift?.schedule_match === "different" ? "border-amber-300/25 bg-amber-300/10 text-amber-100" : "border-white/10 bg-white/[0.04] text-zinc-400")}>
                    {stringOrFallback(lift?.match_label, "Workout not logged yet")}
                  </span>
                  {stringOrFallback(lift?.cardio_indicator) ? <span className="rounded-full border border-sky-300/25 bg-sky-300/10 px-2.5 py-1 text-xs font-medium text-sky-100">{stringOrFallback(lift?.cardio_indicator)}</span> : null}
                  {trainingSources.map((source) => (
                    <span key={source} className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs text-zinc-300">{source}</span>
                  ))}
                </div>
                {stringOrFallback(lift?.recovery_status_relative_to_plan) ? <p className="mt-2 text-xs text-zinc-500">Recovery context: {stringOrFallback(lift?.recovery_status_relative_to_plan)}</p> : null}
              </div>
              {lift?.extra_run_added ? <p className="accent-outline rounded-lg border p-3 text-sm font-semibold">Recovery run added</p> : null}
              {todayVolume !== null ? <p className="text-sm text-amber-200">Lift volume: {Math.round(todayVolume).toLocaleString()}</p> : null}
              {stringOrFallback(lift?.comparison) ? <p className="text-xs text-zinc-500">{stringOrFallback(lift?.comparison)}</p> : null}
              {runDistanceMiles !== null ? (
                <div className="border-t border-white/10 pt-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">Run</p>
                  <p className="accent-text-strong mt-1 text-sm font-semibold">
                    {runDistanceMiles.toFixed(2)} mi{runCount > 1 ? " total" : ""} · {formatRunDuration(runDurationMinutes)} · {formatRunPace(runPace)}{runCount > 1 ? " avg" : ""}
                  </p>
                  {(runCalories || runHeartRate) ? (
                    <p className="mt-1 text-xs text-zinc-500">
                      {[runCalories ? `${Math.round(runCalories)} kcal` : "", runHeartRate ? `${Math.round(runHeartRate)} bpm avg` : ""].filter(Boolean).join(" · ")}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
              <div className="flex items-center gap-4">
                <div className={`grid h-20 w-20 shrink-0 place-items-center rounded-full border-4 bg-white/[0.035] ${qualityStyles.ring}`}>
                  <span className="text-xl font-semibold">{workoutQualityScoreText(workoutQuality?.score)}</span>
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">Workout quality</p>
                  <p className="mt-1 text-xl font-semibold text-white">{stringOrFallback(workoutQuality?.rating, stringOrFallback(workoutQuality?.score_label, "No recent lift"))}</p>
                  <p className="mt-2 text-sm font-semibold text-zinc-100">{workoutQualityTitle || "Latest lift pending"}</p>
                  <p className="mt-1 text-xs uppercase tracking-[0.12em] text-zinc-500">{workoutQualityMeta || "Lift summary"}</p>
                </div>
              </div>
              <p className="mt-4 text-sm leading-6 text-zinc-400">{stringOrFallback(workoutQuality?.summary, stringOrFallback(workoutQuality?.explanation, "No recent lifting workout found."))}</p>
              {qualityExerciseChanges ? <p className="mt-2 text-xs leading-5 text-zinc-500">{qualityExerciseChanges}</p> : null}
              <div className="mt-4 h-2 rounded-full bg-white/10">
                <div className={`h-2 rounded-full ${qualityStyles.bar}`} style={{ width: `${qualityScorePercent}%` }} />
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className={`rounded-full border px-2.5 py-1 text-xs font-medium capitalize ${qualityStyles.badge}`}>
                  {stringOrFallback(workoutQuality?.confidence, "low")} confidence
                </span>
                {workoutMuscleGroups.map((group) => (
                  <span key={group} className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs text-zinc-300">{group}</span>
                ))}
                {qualityComparison ? <span className="text-xs text-zinc-500">{qualityComparison}</span> : null}
              </div>
            </div>
          </div>
        </Card>
      </TargetSectionErrorBoundary>

      <TargetSectionErrorBoundary title="Recovery tile unavailable" description="Recovery data could not render safely." resetKey={`${data?.date ?? ""}-${recoveryScore ?? ""}`}>
        <Card>
          <SectionHeader
            eyebrow="Recovery"
            title="Readiness"
            action={!recovery?.connected ? <button onClick={() => setActivePage("settings")} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Connect</button> : <button onClick={() => setActivePage("recovery")} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Open</button>}
          />
          {recoveryScore !== null || recovery?.connected ? (
            <div>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-3xl font-semibold text-white">{recoveryScore !== null ? Math.round(recoveryScore) : "--"}</p>
                  <p className="mt-2 inline-flex rounded-full border border-emerald-300/20 bg-emerald-300/10 px-3 py-1 text-xs text-emerald-100">{stringOrFallback(recovery?.classification, "sync pending")}</p>
                </div>
                <p className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs uppercase tracking-[0.14em] text-zinc-400">{stringOrFallback(recovery?.source, "recovery")}</p>
              </div>
              <p className="mt-4 text-sm leading-6 text-zinc-400">{stringOrFallback(recovery?.message, "Recovery data sync pending.")}</p>
            </div>
          ) : (
            <p className="text-sm leading-6 text-zinc-400">No recovery data yet</p>
          )}
          <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.035] p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-semibold text-white">Extra run</p>
              <span className={`rounded-full border px-2.5 py-1 text-xs font-medium capitalize ${statusBadgeClass(String(recovery?.extra_run_readiness?.status ?? "insufficient_data"))}`}>
                {String(recovery?.extra_run_readiness?.status ?? "insufficient data").replace("_", " ")}
              </span>
            </div>
            <p className="mt-2 text-sm leading-6 text-zinc-300">{stringOrFallback(recovery?.extra_run_readiness?.message, "Connect wearable data for run readiness.")}</p>
            {extraRunReasoning.length ? (
              <p className="mt-1 text-xs leading-5 text-zinc-500">{extraRunReasoning[0]}</p>
            ) : null}
          </div>
        </Card>
      </TargetSectionErrorBoundary>

      <TargetSectionErrorBoundary title="Optimization signals unavailable" description="Insufficient recommendation data for this dashboard tile." resetKey={`${data?.date ?? ""}-${recommendationConfidence}`}>
        <Card className="xl:col-span-2">
          <button
            type="button"
            aria-expanded={signalsExpanded}
            onClick={() => setSignalsExpanded((value) => !value)}
            className="flex w-full items-center justify-between gap-4 text-left"
          >
            <div className="min-w-0">
              <p className="accent-text text-xs font-semibold uppercase tracking-[0.18em]">Adaptive</p>
              <h2 className="mt-1 text-lg font-semibold text-white">Signals</h2>
              <p className="mt-1 truncate text-sm text-zinc-400">{recommendationReason}</p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs font-semibold capitalize text-zinc-200">
                {recommendationConfidence}
              </span>
              <ChevronDown className={cx("h-5 w-5 text-zinc-400 transition-transform duration-200", signalsExpanded && "rotate-180")} />
            </div>
          </button>
          {signalsExpanded ? (
            <div className="mt-4 border-t border-white/10 pt-4">
              <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-semibold text-white">Optimization Signals</p>
                  <p className="mt-1 text-xs leading-5 text-zinc-500">{weeklyReport?.summary ?? "Weekly report details live in Data & History."}</p>
                </div>
                <button onClick={() => setActivePage("history")} className="w-fit rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">
                  Weekly Report
                </button>
              </div>
              {nutritionRecommendation || adaptiveRecommendation ? (
                <button
                  type="button"
                  onClick={() => setActivePage("goals")}
                  className="mb-3 w-full rounded-lg border border-emerald-300/15 bg-emerald-300/[0.055] p-3 text-left transition hover:bg-emerald-300/[0.08]"
                >
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-emerald-200/80">Nutrition recommendation</p>
                      <p className="mt-1 text-sm font-semibold text-white">
                        {recommendationTitle}
                      </p>
                      <p className="mt-1 text-xs leading-5 text-zinc-400">{recommendationReason}</p>
                    </div>
                    <span className="w-fit rounded-full border border-white/10 bg-black/15 px-2.5 py-1 text-xs font-semibold capitalize text-emerald-100">
                      {recommendationConfidence} · {Math.round(recommendationDataQualityScore)}/100
                    </span>
                  </div>
                  {topAdaptiveWarning ? <p className="mt-2 text-xs leading-5 text-amber-100">{topAdaptiveWarning}</p> : null}
                </button>
              ) : null}
              <div className="grid gap-3 xl:grid-cols-3">
                <div className="accent-outline rounded-lg border p-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.14em]">Macro adherence</p>
                  <p className="mt-2 text-2xl font-semibold text-white">{macroWeeklyScore !== null ? `${Math.round(macroWeeklyScore)}%` : "--"}</p>
                  <p className="mt-1 text-xs leading-5 text-zinc-400">{stringOrFallback(macroAdherence?.summary, "Insufficient finalized nutrition data.")}</p>
                </div>
                <div className="rounded-lg border border-amber-300/15 bg-amber-300/[0.06] p-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-amber-200/80">Plateau watch</p>
                  {topPlateauAlerts.length ? (
                    <div className="mt-2 space-y-2">
                      {topPlateauAlerts.slice(0, 2).map((alert) => (
                        <p key={`${alert.type}-${alert.name}-${alert.signal}`} className="text-sm leading-5 text-amber-50">{stringOrFallback(alert.message, "Possible plateau signal needs more data.")}</p>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-2 text-sm leading-5 text-zinc-400">{stringOrFallback(plateauWatch?.summary, "Insufficient data for plateau detection.")}</p>
                  )}
                </div>
                <div className="rounded-lg border border-violet-300/15 bg-violet-300/[0.06] p-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-violet-200/80">Personal baseline</p>
                  <p className="mt-2 text-sm font-semibold text-white">{baselineTitle}</p>
                  <p className="mt-1 text-xs leading-5 text-zinc-400">{baselineSummary}</p>
                </div>
              </div>
            </div>
          ) : null}
        </Card>
      </TargetSectionErrorBoundary>

    </div>
  );
}

function GoalsPage({
  goals,
  targets,
  weightFeedback,
  leanBulkDecision,
  adaptiveRecommendation,
  trainingPrs,
  trainingPrsLoading,
  onApplySuggestedMacros,
  onRefreshTrainingPrs,
}: Readonly<{
  goals: Goals | null;
  targets: Targets | null;
  weightFeedback: WeightFeedback | null;
  leanBulkDecision: LeanBulkDecision | null;
  adaptiveRecommendation: AdaptiveNutritionRecommendation | null;
  trainingPrs: TrainingPrResponse | null;
  trainingPrsLoading: boolean;
  onApplySuggestedMacros: () => void;
  onRefreshTrainingPrs: () => void;
}>) {
  const targetCalories = finiteNumberOrNull(targets?.target_calories) ?? finiteNumberOrNull(adaptiveRecommendation?.currentTarget?.calories) ?? DEFAULT_BASELINE_CALORIES;
  const targetProtein = finiteNumberOrNull(targets?.protein_grams) ?? finiteNumberOrNull(adaptiveRecommendation?.currentTarget?.protein);
  const targetCarbs = finiteNumberOrNull(targets?.carb_grams) ?? finiteNumberOrNull(adaptiveRecommendation?.currentTarget?.carbs);
  const targetFat = finiteNumberOrNull(targets?.fat_grams) ?? finiteNumberOrNull(adaptiveRecommendation?.currentTarget?.fat);
  const maintenanceCalories = finiteNumberOrNull(targets?.maintenance_calories);
  const calorieDelta = targetCalories - (maintenanceCalories ?? targetCalories);
  const calorieDeltaLabel = calorieDelta === 0 ? "at maintenance" : `${calorieDelta > 0 ? "+" : ""}${calorieDelta} kcal ${calorieDelta > 0 ? "surplus" : "deficit"}`;
  const targetWeeklyChangeLow = finiteNumberOrNull(weightFeedback?.target_weekly_change_low);
  const targetWeeklyChangeHigh = finiteNumberOrNull(weightFeedback?.target_weekly_change_high);
  const leanBulkRange = targetWeeklyChangeLow !== null && targetWeeklyChangeHigh !== null
    ? `${targetWeeklyChangeLow.toFixed(2)}% to ${targetWeeklyChangeHigh.toFixed(2)}%/week target`
    : "Trend target unlocks with goals";
  const weeklyChangeLb = finiteNumberOrNull(weightFeedback?.weekly_change_lb);
  const weeklyChangePct = finiteNumberOrNull(weightFeedback?.weekly_change_pct);
  const weeklyTrend = weeklyChangeLb !== null && weeklyChangePct !== null
    ? `${weeklyChangeLb > 0 ? "+" : ""}${weeklyChangeLb} lb/week (${weeklyChangePct > 0 ? "+" : ""}${weeklyChangePct}%)`
    : "Need bodyweight trend";
  const updatedAtTimestamp = targets?.updated_at ? new Date(targets.updated_at).getTime() : NaN;
  const lastUpdated = Number.isFinite(updatedAtTimestamp) ? new Date(updatedAtTimestamp).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "Not applied yet";
  const leanBulkDetails = leanBulkDecision?.details ?? null;
  const performanceSignal = leanBulkDetails?.performance_signal ?? null;
  const performanceDrivers = Array.isArray(performanceSignal?.drivers) ? performanceSignal.drivers.slice(0, 3) : [];
  const recoverySignal = leanBulkDetails?.recovery_signal ?? targets?.recovery_signal ?? null;
  const recoveryDrivers = Array.isArray(recoverySignal?.drivers) ? recoverySignal.drivers.slice(0, 3) : [];
  const adaptiveReasons = stringList(adaptiveRecommendation?.reasoning).slice(0, 4);
  const adaptiveTrends = stringList(adaptiveRecommendation?.detectedTrends).slice(0, 4);
  const missingDataWarnings = stringList(adaptiveRecommendation?.missingDataWarnings).slice(0, 3);
  const dayTypeAdjustment = recordOrEmpty(adaptiveRecommendation?.dayTypeAdjustment);
  const adaptiveSignalRecord = recordOrEmpty(adaptiveRecommendation?.signals);
  const bodyComposition = recordOrEmpty(adaptiveSignalRecord.bodyComposition);
  const currentTarget = recordOrEmpty(adaptiveRecommendation?.currentTarget);
  const currentTargetCalories = finiteNumberOrNull(currentTarget.calories) ?? finiteNumberOrNull(currentTarget.target_calories) ?? targetCalories;
  const currentTargetProtein = finiteNumberOrNull(currentTarget.protein) ?? finiteNumberOrNull(currentTarget.protein_grams) ?? targetProtein;
  const currentTargetCarbs = finiteNumberOrNull(currentTarget.carbs) ?? finiteNumberOrNull(currentTarget.carb_grams) ?? targetCarbs;
  const currentTargetFat = finiteNumberOrNull(currentTarget.fat) ?? finiteNumberOrNull(currentTarget.fat_grams) ?? targetFat;
  const macroChanges = recordOrEmpty(adaptiveRecommendation?.macroChanges ?? adaptiveRecommendation?.macroAdjustment);
  const hasRecommendedTargets = ["caloriesTarget", "proteinTarget", "carbsTarget", "fatTarget"].every((key) => finiteNumberOrNull(adaptiveRecommendation?.[key as keyof AdaptiveNutritionRecommendation]) !== null);
  const currentTargetSummary = `${formatWholeNumber(currentTargetCalories)} kcal · P ${formatWholeNumber(currentTargetProtein)} C ${formatWholeNumber(currentTargetCarbs)} F ${formatWholeNumber(currentTargetFat)}`;
  const hasMacroChanges = ["calories", "protein", "carbs", "fat"].some((key) => finiteNumberOrNull(macroChanges[key]) !== null);
  const macroChangeSummary = hasMacroChanges
    ? `${formatSignedWholeNumber(macroChanges.calories, " kcal")} · P ${formatSignedWholeNumber(macroChanges.protein, "g")} · C ${formatSignedWholeNumber(macroChanges.carbs, "g")} · F ${formatSignedWholeNumber(macroChanges.fat, "g")}`
    : "Insufficient data";
  const leanGainQuality = stringOrFallback(bodyComposition.lean_gain_quality, "unknown");
  const latestLeanMass = finiteNumberOrNull(bodyComposition.latest_lean_mass);
  const latestFatMass = finiteNumberOrNull(bodyComposition.latest_fat_mass);
  const signalRows = [
    ["Weight", stringOrFallback(recordOrEmpty(adaptiveSignalRecord.weight).status, "insufficient data")],
    ["Performance", stringOrFallback(recordOrEmpty(adaptiveSignalRecord.performance).label, "insufficient data")],
    ["Recovery", stringOrFallback(recordOrEmpty(adaptiveSignalRecord.recovery).status, "insufficient data")],
    ["Training Load", stringOrFallback(recordOrEmpty(adaptiveSignalRecord.trainingLoad).status, "low")],
    ["Running Load", stringOrFallback(recordOrEmpty(adaptiveSignalRecord.runningLoad).status, "low")],
  ];
  const prItems = arrayOrEmpty<TrainingPrItem>(trainingPrs?.items);
  const prDiagnostics = recordOrEmpty(trainingPrs?.diagnostics);
  const prSourceReason = stringOrFallback(prDiagnostics.source_reason, trainingPrs?.message ?? "");
  const prStatus = stringOrFallback(trainingPrs?.status, trainingPrsLoading ? "loading" : "not loaded");
  return (
    <div className="space-y-6">
      <TargetSectionErrorBoundary title="Targets unavailable" description="Insufficient target data for this section." resetKey={`${targetCalories}-${lastUpdated}`}>
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
              <p><span className="text-zinc-500">Mode:</span> Adaptive maintenance baseline with conservative training-day carb support when workload and recovery justify it.</p>
            </div>
          </div>
          <div className="accent-outline rounded-lg border p-4">
            <p className="text-sm text-zinc-400">Current active targets</p>
            <p className="mt-2 text-3xl font-semibold text-white">{formatWholeNumber(targetCalories)} kcal</p>
            <p className="mt-3 text-sm text-zinc-300">
              {targetProtein !== null || targetCarbs !== null || targetFat !== null
                ? `${formatWholeNumber(targetProtein)}g protein · ${formatWholeNumber(targetCarbs)}g carbs · ${formatWholeNumber(targetFat)}g fat`
                : "Apply the latest recommendation to set targets."}
            </p>
            <p className="mt-4 text-xs text-zinc-500">Last updated: {lastUpdated}</p>
          </div>
        </div>
        </Card>
      </TargetSectionErrorBoundary>

      <TargetSectionErrorBoundary title="Recommendation unavailable" description="Insufficient recommendation data for this section." resetKey={`${targetCalories}-${adaptiveRecommendation?.nextReviewDate ?? ""}`}>
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
                  {hasRecommendedTargets ? `${formatWholeNumber(adaptiveRecommendation?.caloriesTarget)} kcal` : "Need data"}
                </p>
                <p className="mt-2 text-sm text-zinc-300">
                  {hasRecommendedTargets
                    ? `${formatWholeNumber(adaptiveRecommendation?.proteinTarget)}g protein · ${formatWholeNumber(adaptiveRecommendation?.carbsTarget)}g carbs · ${formatWholeNumber(adaptiveRecommendation?.fatTarget)}g fat`
                    : "The engine will combine weight, food, Hevy, Strava, performance, and recovery signals."}
                </p>
              </div>
              <span className="accent-outline inline-flex w-fit rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em]">
                {recommendationConfidenceLabel(adaptiveRecommendation?.confidence, adaptiveRecommendation?.confidenceLevel)} confidence
              </span>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-white/10 bg-black/15 p-3">
                <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Current</p>
                <p className="mt-2 text-sm font-semibold text-white">
                  {currentTargetSummary}
                </p>
              </div>
              <div className="rounded-lg border border-white/10 bg-black/15 p-3">
                <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Change</p>
                <p className="mt-2 text-sm font-semibold text-white">
                  {macroChangeSummary}
                </p>
              </div>
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <div className="accent-outline rounded-lg border p-3">
                <p className="text-xs uppercase tracking-[0.12em]">Day type</p>
                <p className="mt-2 text-sm font-semibold text-white">{stringOrFallback(adaptiveRecommendation?.dayType, "Learning")}</p>
                <p className="mt-1 text-xs leading-5 text-zinc-400">{stringOrFallback(dayTypeAdjustment.reason, "Workout and run context will tune daily carbs.")}</p>
              </div>
              <div className="rounded-lg border border-emerald-300/15 bg-emerald-300/[0.045] p-3">
                <p className="text-xs uppercase tracking-[0.12em] text-emerald-200/70">Data quality</p>
                <p className="mt-2 text-sm font-semibold text-white">{adaptiveRecommendation?.dataQualityScore ?? 0}/100</p>
                <p className="mt-1 text-xs leading-5 text-zinc-400">Next review: {adaptiveRecommendation?.nextReviewDate ?? "after more logs"}</p>
              </div>
              <div className="rounded-lg border border-violet-300/15 bg-violet-300/[0.045] p-3">
                <p className="text-xs uppercase tracking-[0.12em] text-violet-200/70">Lean gain quality</p>
                <p className="mt-2 text-sm font-semibold capitalize text-white">{leanGainQuality}</p>
                <p className="mt-1 text-xs leading-5 text-zinc-400">
                  {latestLeanMass !== null ? `Lean ${latestLeanMass} lb` : "Body fat data improves this read."}
                  {latestFatMass !== null ? ` · Fat ${latestFatMass} lb` : ""}
                </p>
              </div>
            </div>
            <ul className="mt-4 space-y-2 text-sm text-zinc-300">
              {(adaptiveReasons.length ? adaptiveReasons : ["Need more data before making adaptive macro changes."]).map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
            {adaptiveRecommendation?.carbTimingRecommendation ? (
              <p className="mt-3 rounded-lg border border-blue-300/15 bg-blue-300/[0.045] p-3 text-sm leading-6 text-blue-100">{adaptiveRecommendation.carbTimingRecommendation}</p>
            ) : null}
            {adaptiveTrends.length ? (
              <div className="mt-3 rounded-lg border border-white/10 bg-black/10 p-3">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Detected trends</p>
                <ul className="mt-2 space-y-1 text-xs leading-5 text-zinc-400">
                  {adaptiveTrends.map((trend) => <li key={trend}>{trend}</li>)}
                </ul>
              </div>
            ) : null}
            {missingDataWarnings.length ? (
              <div className="mt-3 rounded-lg border border-amber-300/20 bg-amber-300/10 p-3">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-amber-200/80">Data gaps</p>
                <p className="mt-1 text-xs leading-5 text-amber-100">{missingDataWarnings.join(" ")}</p>
              </div>
            ) : null}
            {adaptiveRecommendation?.warnings?.length ? (
              <p className="mt-3 text-xs leading-5 text-amber-200">{adaptiveRecommendation.warnings[0]}</p>
            ) : null}
          </div>
          <div className="grid gap-2">
            {signalRows.map(([label, value]) => (
              <div key={label} className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.035] px-3 py-2">
                <span className="text-sm text-zinc-400">{label}</span>
                <span className="text-sm font-semibold capitalize text-white">{value}</span>
              </div>
            ))}
          </div>
        </div>
        </Card>
      </TargetSectionErrorBoundary>

      <TargetSectionErrorBoundary title="Exercise PRs unavailable" description="Training PR data could not render safely." resetKey={`${trainingPrs?.source ?? ""}-${prItems.length}`}>
        <div data-testid="goals-pr-section">
          <Card>
            <SectionHeader
              eyebrow="Training"
              title="Exercise PRs"
              action={
                <button type="button" onClick={onRefreshTrainingPrs} disabled={trainingPrsLoading} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-50">
                  {trainingPrsLoading ? "Loading..." : "Refresh PRs"}
                </button>
              }
            />
            {trainingPrsLoading && !prItems.length ? (
              <p className="rounded-lg border border-white/10 bg-white/[0.035] p-4 text-sm text-zinc-400">Loading exercise PRs from training history.</p>
            ) : prItems.length ? (
              <div className="overflow-x-auto rounded-lg border border-white/10">
                <table className="min-w-full divide-y divide-white/10 text-sm">
                  <thead className="bg-white/[0.04] text-left text-zinc-400">
                    <tr>
                      <th className="px-3 py-2 font-medium">Exercise</th>
                      <th className="px-3 py-2 font-medium">PR weight</th>
                      <th className="px-3 py-2 font-medium">Reps</th>
                      <th className="px-3 py-2 font-medium">Date</th>
                      <th className="px-3 py-2 font-medium">Source</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/10">
                    {prItems.map((item) => (
                      <tr key={item.pr_id || `${item.exercise}-${item.date}-${item.weight}-${item.reps}`} className="text-zinc-200">
                        <td className="px-3 py-2 font-semibold text-white">{stringOrFallback(item.exercise, "Unknown exercise")}</td>
                        <td className="px-3 py-2">{formatCompactNumber(item.weight)} {stringOrFallback(item.unit, "lb")}</td>
                        <td className="px-3 py-2">{formatWholeNumber(item.reps)}</td>
                        <td className="px-3 py-2">{stringOrFallback(item.date, "--")}</td>
                        <td className="px-3 py-2 capitalize text-zinc-400">{stringOrFallback(item.source, stringOrFallback(item.record_source, "--")).replaceAll("_", " ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState
                title={trainingPrs?.status === "error" ? "Exercise PRs unavailable" : "No lifting PRs yet"}
                description={prSourceReason || "Weighted lifting rows from Hevy or training history will populate this section."}
                action="Refresh PRs"
                onAction={onRefreshTrainingPrs}
              />
            )}
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-zinc-500">
              <span className="rounded-full border border-white/10 bg-white/[0.035] px-2.5 py-1 capitalize">Status: {prStatus.replaceAll("_", " ")}</span>
              <span className="rounded-full border border-white/10 bg-white/[0.035] px-2.5 py-1 capitalize">Source: {stringOrFallback(trainingPrs?.source, "not loaded").replaceAll("_", " ")}</span>
              {prSourceReason ? <span className="rounded-full border border-white/10 bg-white/[0.035] px-2.5 py-1">{prSourceReason}</span> : null}
            </div>
          </Card>
        </div>
      </TargetSectionErrorBoundary>

      <TargetSectionErrorBoundary title="Macro targets unavailable" description="Insufficient target data for macro target cards." resetKey={`${targetCalories}-${targetProtein ?? ""}-${targetCarbs ?? ""}-${targetFat ?? ""}`}>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <TargetDetailCard
            title="Calories"
            value={`${formatWholeNumber(targetCalories)} kcal`}
            subvalue={maintenanceCalories !== null ? `Maintenance ${formatWholeNumber(maintenanceCalories)} - ${calorieDeltaLabel}` : "Save goals to calculate"}
            note={targets ? `Dynamic adjustment: ${formatSignedWholeNumber(targets.calorie_adjustment, " kcal/day")}. Macro math: ${formatWholeNumber(targets.macro_calories ?? targetCalories)} kcal (${formatSignedWholeNumber(targets.calorie_macro_delta ?? 0, " delta")}).` : "Calories update from weight trend, training load, cardio, and recovery."}
            icon={Apple}
            accent="accent-outline"
          />
        <TargetDetailCard
          title="Protein"
          value={targetProtein !== null ? `${formatWholeNumber(targetProtein)}g` : "No target"}
          subvalue={targets?.protein_per_lb ? `${targets.protein_per_lb}g/lb bodyweight` : "Protein-first allocation"}
          note="Lean bulk targets a higher protein floor for muscle retention, growth, and consistency."
          icon={ProteinMoleculeIcon}
          accent="border-teal-400/20 bg-teal-400/10 text-teal-300"
        />
        <TargetDetailCard
          title="Carbs"
          value={targetCarbs !== null ? `${formatWholeNumber(targetCarbs)}g` : "No target"}
          subvalue="Remaining calories after protein and fats"
          note={targets?.carb_emphasis ?? "Carbs scale with lifting frequency, cardio, surplus size, and recovery demand."}
          icon={CarbsMoleculeIcon}
          accent="border-blue-400/20 bg-blue-400/10 text-blue-300"
        />
        <TargetDetailCard
          title="Fat"
          value={targetFat !== null ? `${formatWholeNumber(targetFat)}g` : "No target"}
          subvalue={targets?.fat_per_lb ? `${targets.fat_per_lb}g/lb - floor ${targets.fat_floor_grams ?? 0}g` : "Minimum recovery threshold"}
          note="Moderate fats are protected before carbs get the remaining calories."
          icon={FatMoleculeIcon}
          accent="border-amber-400/20 bg-amber-400/10 text-amber-300"
        />
      </div>
      </TargetSectionErrorBoundary>

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
              <p className="accent-text-strong mt-2 text-sm font-semibold">{weightFeedback?.suggested_adjustment ?? "No bodyweight trend yet"}</p>
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
          <MetricCard title="7-Day Avg Weight" value={leanBulkDetails?.seven_day_avg_weight ? `${leanBulkDetails.seven_day_avg_weight}` : "Need data"} detail="Smooths water spikes" icon={Weight} accent="border-blue-400/20 bg-blue-400/10 text-blue-300" />
          <MetricCard title="14-Day Avg Weight" value={leanBulkDetails?.fourteen_day_avg_weight ? `${leanBulkDetails.fourteen_day_avg_weight}` : "Need data"} detail="Primary trend context" icon={Weight} accent="accent-outline" />
          <MetricCard title="Calorie Avg" value={leanBulkDetails?.calorie_average ? `${leanBulkDetails.calorie_average}` : "Need logs"} detail="Recent daily average" icon={Apple} accent="border-emerald-400/20 bg-emerald-400/10 text-emerald-300" />
          <MetricCard title="Protein Avg" value={leanBulkDetails?.protein_average ? `${leanBulkDetails.protein_average}g` : "Need logs"} detail={leanBulkDetails?.protein_target ? `Target ~${leanBulkDetails.protein_target}g` : "0.8-1.0g/lb guardrail"} icon={ProteinMoleculeIcon} accent="border-teal-400/20 bg-teal-400/10 text-teal-300" />
          <MetricCard title="Training Trend" value={leanBulkDetails?.training_trend ?? "Need data"} detail="Key lift direction" icon={Dumbbell} accent="border-violet-400/20 bg-violet-400/10 text-violet-300" />
          <MetricCard title="Recovery Trend" value={leanBulkDetails?.recovery_trend ?? "Need data"} detail={leanBulkDetails?.recovery_average ? `${leanBulkDetails.recovery_average}/100 avg` : "Recent readiness"} icon={HeartPulse} accent="border-rose-400/20 bg-rose-400/10 text-rose-300" />
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
          <p className="accent-text-strong mt-2 text-lg font-semibold">
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
  dayTypeMacros,
  adaptiveRecommendation,
  onApplySuggestedMacros,
  onRunNutritionEngine,
  nutritionHistory,
  nutritionAdherence,
  shortcuts,
  frequentFoods,
  mealTemplates,
  workoutMarkers,
  forms,
  setForms,
  onWorkoutMarkerSubmit,
  manualCaloriesOverridden,
  setManualCaloriesOverridden,
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
  onCreateShortcut,
  onCreateAndLogPreset,
  onLogFrequentFood,
  onDeleteFoodLog,
  onUpdateFoodLog,
  onUpdateShortcut,
  onDeleteShortcut,
  onLogMealTemplate,
  onRenameMealTemplate,
  shortcutSuggestion,
  onUseSuggestion,
  onParseAnyway,
  parseLoading,
  parseResult,
  foodAiFlow,
  foodAiDebug,
  manualSaving,
  manualError,
  aiParsingConfigured,
  quickFoodLogStatuses,
  quickFoodPendingCount,
}: Readonly<{
  logs: NutritionEntry[];
  targets: Targets | null;
  dayTypeMacros?: OptimizationData["day_type_macros"] | null;
  adaptiveRecommendation?: AdaptiveNutritionRecommendation | null;
  onApplySuggestedMacros: () => void;
  onRunNutritionEngine: () => void;
  nutritionHistory: DailyNutritionSummary[];
  nutritionAdherence: NutritionAdherence | null;
  shortcuts: FoodShortcut[];
  frequentFoods: NutritionShortcutData["frequent_foods"];
  mealTemplates: MealTemplate[];
  workoutMarkers: WorkoutMarker[];
  forms: FormState;
  setForms: React.Dispatch<React.SetStateAction<FormState>>;
  onWorkoutMarkerSubmit: (event: FormEvent) => void;
  manualCaloriesOverridden: boolean;
  setManualCaloriesOverridden: React.Dispatch<React.SetStateAction<boolean>>;
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
  onLogShortcut: (shortcut: PresetFoodShortcut) => Promise<void> | void;
  onCreateShortcut: (shortcut: FoodShortcut) => Promise<void> | void;
  onCreateAndLogPreset: (shortcut: FoodShortcut) => Promise<void> | void;
  onLogFrequentFood: (food: NutritionShortcutData["frequent_foods"][number]) => Promise<void> | void;
  onDeleteFoodLog: (entry: NutritionEntry) => Promise<void>;
  onUpdateFoodLog: (entry: NutritionEntry, updates: { iconType: FoodIconType | null }) => Promise<void>;
  onUpdateShortcut: (shortcut: FoodShortcut) => Promise<void> | void;
  onDeleteShortcut: (shortcutId: string) => Promise<void> | void;
  onLogMealTemplate: (template: MealTemplateSummary) => Promise<void> | void;
  onRenameMealTemplate: (templateName: string, nextName: string) => Promise<void>;
  shortcutSuggestion: { type: "shortcut" | "template" | "frequent"; label: string; id: string } | null;
  onUseSuggestion: () => void;
  onParseAnyway: () => void;
  parseLoading: boolean;
  parseResult: FoodParseResponse | null;
  foodAiFlow: FoodAiFlowStep[];
  foodAiDebug: FoodAiDebugState | null;
  manualSaving: boolean;
  manualError: string | null;
  aiParsingConfigured: boolean;
  quickFoodLogStatuses: Record<string, QuickFoodLogStatus>;
  quickFoodPendingCount: number;
}>) {
  const [showFoodHistory, setShowFoodHistory] = useState(false);
  const [shortcutQuery, setShortcutQuery] = useState("");
  const [shortcutTab, setShortcutTab] = useState<"saved" | "meals" | "frequent">("saved");
  const [presetEditMode, setPresetEditMode] = useState(false);
  const [editingShortcut, setEditingShortcut] = useState<PresetFoodShortcut | null>(null);
  const [pendingPresetAction, setPendingPresetAction] = useState<string | null>(null);
  const [editingTemplateName, setEditingTemplateName] = useState<string | null>(null);
  const [templateRenameValue, setTemplateRenameValue] = useState("");
  const [pendingTemplateAction, setPendingTemplateAction] = useState<string | null>(null);
  const [deletingFoodLogId, setDeletingFoodLogId] = useState<string | null>(null);
  const [editingFoodLogId, setEditingFoodLogId] = useState<string | null>(null);
  const [editingFoodLogIcon, setEditingFoodLogIcon] = useState<FoodIconType | null>(null);
  const [savingFoodLogId, setSavingFoodLogId] = useState<string | null>(null);
  const selectedDateEntries = logs.filter((entry) => entry.date === forms.nutrition.date);
  const selectedDateMarkers = workoutMarkers
    .filter((marker) => (marker.date || "").slice(0, 10) === forms.nutrition.date)
    .sort((a, b) => {
      const bOrder = finiteNumberOrNull(b.marker_sequence ?? b.created_order);
      const aOrder = finiteNumberOrNull(a.marker_sequence ?? a.created_order);
      if (bOrder !== null && aOrder !== null && bOrder !== aOrder) return bOrder - aOrder;
      if (bOrder !== null && aOrder === null) return -1;
      if (bOrder === null && aOrder !== null) return 1;
      return `${b.date} ${b.created_at ?? ""} ${b.workout_time}`.localeCompare(`${a.date} ${a.created_at ?? ""} ${a.workout_time}`);
    });
  const latestSelectedMarker = selectedDateMarkers[0] ?? null;
  const latestMarkerOrder = latestSelectedMarker ? finiteNumberOrNull(latestSelectedMarker.marker_sequence ?? latestSelectedMarker.created_order) : null;
  const markerLoggedItemCount = latestMarkerOrder === null
    ? null
    : selectedDateEntries.filter((entry) => {
      const entryOrder = finiteNumberOrNull(entry.logged_sequence ?? entry.created_order);
      return entryOrder !== null && entryOrder < latestMarkerOrder;
    }).length;
  const markerStatusText = latestSelectedMarker
    ? markerLoggedItemCount === null
      ? "Workout marker placed. Food order is unavailable for at least one item, so timing may be unknown."
      : `Workout marker placed after ${markerLoggedItemCount} logged item${markerLoggedItemCount === 1 ? "" : "s"}.`
    : "No workout marker logged for this date yet.";
  const selectedDateLabel = forms.nutrition.date === todayString() ? "today" : forms.nutrition.date;
  const selectedDateTotals = selectedDateEntries.reduce(
    (totals, entry) => ({
      calories: totals.calories + (Number(entry.calories) || 0),
      protein: totals.protein + (Number(entry.protein) || 0),
      carbs: totals.carbs + (Number(entry.carbs) || 0),
      fat: totals.fat + (Number(entry.fat) || 0),
      fiber: totals.fiber + (Number(entry.fiber) || 0),
    }),
    { calories: 0, protein: 0, carbs: 0, fat: 0, fiber: 0 },
  );
  const adjustedTargets = recordOrEmpty(dayTypeMacros?.adjusted_targets);
  const displayTargets = {
    target_calories: finiteNumberOrNull(adjustedTargets.calories) ?? finiteNumberOrNull(targets?.target_calories) ?? DEFAULT_BASELINE_CALORIES,
    protein_grams: finiteNumberOrNull(adjustedTargets.protein) ?? finiteNumberOrNull(targets?.protein_grams) ?? 0,
    carb_grams: finiteNumberOrNull(adjustedTargets.carbs) ?? finiteNumberOrNull(targets?.carb_grams) ?? 0,
    fat_grams: finiteNumberOrNull(adjustedTargets.fat) ?? finiteNumberOrNull(targets?.fat_grams) ?? 0,
  };
  const hasMacroTargets = displayTargets.target_calories > 0 && displayTargets.protein_grams > 0 && displayTargets.carb_grams > 0 && displayTargets.fat_grams > 0;
  const calorieProgress = buildMacroProgress("Calories", " kcal", selectedDateTotals.calories, displayTargets?.target_calories ?? 0, "accent-progress");
  const macroProgress = [
    buildMacroProgress("Protein", "g", selectedDateTotals.protein, displayTargets?.protein_grams ?? 0, "bg-teal-300"),
    buildMacroProgress("Carbs", "g", selectedDateTotals.carbs, displayTargets?.carb_grams ?? 0, "bg-blue-300"),
    buildMacroProgress("Fat", "g", selectedDateTotals.fat, displayTargets?.fat_grams ?? 0, "bg-amber-300"),
  ];
  const recentHistory = nutritionHistory.slice(-30);
  const normalizedShortcutQuery = normalizeSearchText(shortcutQuery);
  const savedShortcutNames = new Set(shortcuts.map((shortcut) => normalizeSearchText(shortcut.shortcut_name)));
  const defaultPresetFill = DEFAULT_PRESET_FOODS.filter((preset) => !savedShortcutNames.has(normalizeSearchText(preset.shortcut_name))).slice(0, Math.max(0, 18 - shortcuts.length));
  const presetShortcuts: PresetFoodShortcut[] = [...shortcuts, ...defaultPresetFill];
  const filteredShortcuts = presetShortcuts.filter((shortcut) => normalizeSearchText(shortcut.shortcut_name).includes(normalizedShortcutQuery));
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
    }, new Map<string, MealTemplateSummary>())
      .values(),
  ).sort((a, b) => a.template_name.localeCompare(b.template_name));
  const filteredTemplateSummaries = templateSummaries.filter((template) => normalizeSearchText(template.template_name).includes(normalizedShortcutQuery));
  const filteredFrequentFoods = frequentFoods.filter((food) => normalizeSearchText(food.food_name).includes(normalizedShortcutQuery));
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
  const logTemplate = async (template: MealTemplateSummary) => {
    await onLogMealTemplate(template);
  };
  const beginFoodLogEdit = (entry: NutritionEntry) => {
    if (!entry.food_log_id) return;
    setEditingFoodLogId(entry.food_log_id);
    setEditingFoodLogIcon(normalizeFoodIconType(entry.iconType) ?? suggestFoodIconType(entry.food_name));
  };
  const cancelFoodLogEdit = () => {
    setEditingFoodLogId(null);
    setEditingFoodLogIcon(null);
  };
  const saveFoodLogIcon = async (entry: NutritionEntry) => {
    if (!entry.food_log_id) return;
    setSavingFoodLogId(entry.food_log_id);
    try {
      await onUpdateFoodLog(entry, { iconType: editingFoodLogIcon });
      cancelFoodLogEdit();
    } finally {
      setSavingFoodLogId(null);
    }
  };
  const removeFoodLogEntry = async (entry: NutritionEntry) => {
    if (!entry.food_log_id) return;
    const confirmed = window.confirm(`Remove ${entry.food_name || "this food entry"} from ${entry.date}?`);
    if (!confirmed) return;
    setDeletingFoodLogId(entry.food_log_id);
    try {
      await onDeleteFoodLog(entry);
      if (editingFoodLogId === entry.food_log_id) cancelFoodLogEdit();
    } finally {
      setDeletingFoodLogId(null);
    }
  };

  const compactMacroRows: CompactMacroRow[] = [
    { label: "Calories", unit: "", consumed: selectedDateTotals.calories, target: displayTargets?.target_calories ?? 0, bar: "accent-progress" },
    { label: "Protein", unit: "g", consumed: selectedDateTotals.protein, target: displayTargets?.protein_grams ?? 0, bar: "bg-teal-300" },
    { label: "Carbs", unit: "g", consumed: selectedDateTotals.carbs, target: displayTargets?.carb_grams ?? 0, bar: "bg-blue-300" },
    { label: "Fat", unit: "g", consumed: selectedDateTotals.fat, target: displayTargets?.fat_grams ?? 0, bar: "bg-amber-300" },
    ...(selectedDateTotals.fiber > 0 ? [{ label: "Fiber", unit: "g", consumed: selectedDateTotals.fiber, target: 30, bar: "bg-emerald-300" }] : []),
  ];
  const shortcutTabs: Array<{ id: "saved" | "meals" | "frequent"; label: string; count: number }> = [
    { id: "saved", label: "Saved foods", count: presetShortcuts.length },
    { id: "meals", label: "Meals", count: templateSummaries.length },
    { id: "frequent", label: "Frequent", count: frequentFoods.length },
  ];
  const handleShortcutTileClick = async (shortcut: PresetFoodShortcut) => {
    if (presetEditMode) {
      setEditingShortcut({ ...shortcut });
      return;
    }
    if (isDefaultPresetShortcut(shortcut)) {
      await onCreateAndLogPreset(shortcut);
    } else {
      await onLogShortcut(shortcut);
    }
  };
  const handleFrequentTileClick = async (food: NutritionShortcutData["frequent_foods"][number]) => {
    if (presetEditMode) return;
    await onLogFrequentFood(food);
  };
  const handleSaveShortcutEdit = async () => {
    if (!editingShortcut) return;
    const shortcut = { ...editingShortcut, shortcut_name: editingShortcut.shortcut_name.trim() };
    if (!shortcut.shortcut_name) return;
    setPendingPresetAction(`edit:${editingShortcut.shortcut_id}`);
    try {
      if (isDefaultPresetShortcut(shortcut)) {
        await onCreateShortcut(shortcut);
      } else {
        await onUpdateShortcut(shortcut);
      }
      setEditingShortcut(null);
    } finally {
      setPendingPresetAction(null);
    }
  };
  const handleDeleteShortcut = async (shortcut: FoodShortcut) => {
    const confirmed = window.confirm(`Delete ${shortcut.shortcut_name || "this preset"}?`);
    if (!confirmed) return;
    setPendingPresetAction(`delete:${shortcut.shortcut_id}`);
    try {
      await onDeleteShortcut(shortcut.shortcut_id);
      if (editingShortcut?.shortcut_id === shortcut.shortcut_id) setEditingShortcut(null);
    } finally {
      setPendingPresetAction(null);
    }
  };
  const showFoodAiDebugDetails = Boolean(
    foodAiDebug?.exactError ||
    foodAiFlow.some((item) => item.status === "error") ||
    foodAiDebug?.analyzeResponseStatus === "error" ||
    foodAiDebug?.logInsertStatus === "error" ||
    foodAiDebug?.refreshStatus === "error",
  );
  const calculatedDirectCalories = calculateMacroCalories(forms.nutrition.protein, forms.nutrition.carbs, forms.nutrition.fat);
  const hasDirectMacroCalories = calculatedDirectCalories > 0;
  const updateDirectMacro = (key: keyof Pick<NutritionEntry, "protein" | "carbs" | "fat">, value: string) => {
    const nextValue = value === "" ? 0 : Number(value);
    setForms((state) => {
      const nextNutrition = {
        ...state.nutrition,
        [key]: Number.isFinite(nextValue) ? nextValue : 0,
      };
      return {
        ...state,
        nutrition: {
          ...nextNutrition,
          calories: manualCaloriesOverridden
            ? nextNutrition.calories
            : calculateMacroCalories(nextNutrition.protein, nextNutrition.carbs, nextNutrition.fat),
        },
      };
    });
  };
  const applyCalculatedCalories = () => {
    setManualCaloriesOverridden(false);
    setForms((state) => ({
      ...state,
      nutrition: {
        ...state.nutrition,
        calories: calculateMacroCalories(state.nutrition.protein, state.nutrition.carbs, state.nutrition.fat),
      },
    }));
  };
  const updateDirectCalories = (value: string) => {
    if (value === "") {
      applyCalculatedCalories();
      return;
    }
    setManualCaloriesOverridden(true);
    setForms((state) => ({ ...state, nutrition: { ...state.nutrition, calories: Number(value) } }));
  };

  return (
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.85fr)] xl:items-start" data-testid="food-page">
      <div className="min-w-0 space-y-4 xl:self-start">
        <MacroDonutCard
          totals={selectedDateTotals}
          targets={hasMacroTargets ? displayTargets : null}
          rows={compactMacroRows}
          dateLabel={selectedDateLabel}
          dayTypeMacros={dayTypeMacros}
        />
        <Card className="min-w-0">
          <SectionHeader
            eyebrow="Logged foods"
            title={`Food logged for ${selectedDateLabel}`}
            action={
              <button onClick={() => setShowFoodHistory((value) => !value)} className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04]">
                {showFoodHistory ? "Hide details" : "View full history/details"}
                <ChevronDown className={cx("h-4 w-4 transition", showFoodHistory ? "rotate-180" : "")} />
              </button>
            }
          />
          <FoodLogList
            entries={selectedDateEntries.slice().reverse()}
            emptyDescription="Entries for this date will appear here immediately after saving."
            onRemove={(entry) => void removeFoodLogEntry(entry)}
            removingId={deletingFoodLogId}
            onEdit={beginFoodLogEdit}
            editingId={editingFoodLogId}
            editingIcon={editingFoodLogIcon}
            onEditingIconChange={setEditingFoodLogIcon}
            onCancelEdit={cancelFoodLogEdit}
            onSaveIcon={(entry) => void saveFoodLogIcon(entry)}
            savingId={savingFoodLogId}
          />
          {selectedDateEntries.length ? (
            <div className="mt-3 grid gap-3 rounded-lg border border-white/10 bg-zinc-950/50 p-3 text-sm sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
              <p className="font-semibold text-white">Daily total</p>
              <div className="flex flex-wrap gap-1.5 text-xs text-zinc-300 sm:justify-end">
                <span className="accent-outline rounded-full border px-2 py-1">{formatFoodAmount(selectedDateTotals.calories)} kcal</span>
                <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">P {formatFoodAmount(selectedDateTotals.protein)}g</span>
                <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">C {formatFoodAmount(selectedDateTotals.carbs)}g</span>
                <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">F {formatFoodAmount(selectedDateTotals.fat)}g</span>
              </div>
            </div>
          ) : null}
        </Card>
        <SupplementsTile date={forms.nutrition.date} />
        {showFoodHistory ? (
          <Card className="min-w-0">
            <SectionHeader
              eyebrow="Details"
              title="Food history and targets"
              action={
                <button
                  type="button"
                  onClick={onRunNutritionEngine}
                  className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04]"
                >
                  <RefreshCw className="h-4 w-4" />
                  Run nutrition engine
                </button>
              }
            />
            <div className="space-y-4">
              <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3 text-xs leading-5 text-zinc-400">
                Today is live and updates instantly from food rows. Long-term recommendations use finalized daily summaries unless you run the engine manually.
              </div>
              {hasMacroTargets ? (
                <div className="space-y-3">
                  {adaptiveRecommendation ? (
                    <div className="rounded-lg border border-emerald-300/15 bg-emerald-300/[0.055] p-4">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <p className="text-sm font-semibold text-white">Adaptive baseline recommendation</p>
                          <p className="mt-1 text-sm leading-6 text-zinc-400">
                            {adaptiveRecommendation.caloriesTarget} kcal · P {adaptiveRecommendation.proteinTarget}g · C {adaptiveRecommendation.carbsTarget}g · F {adaptiveRecommendation.fatTarget}g
                          </p>
                          <p className="mt-1 text-xs leading-5 text-zinc-500">{adaptiveRecommendation.reasoning?.[0] ?? "Recommendation updates with body, food, training, runs, and recovery data."}</p>
                        </div>
                        <button
                          type="button"
                          onClick={onApplySuggestedMacros}
                          className="w-fit rounded-lg bg-emerald-300 px-3 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-200"
                        >
                          Apply
                        </button>
                      </div>
                    </div>
                  ) : null}
                  <MacroProgressCard macro={calorieProgress} />
                  <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
                    {macroProgress.map((macro) => (
                      <MacroProgressCard key={macro.label} macro={macro} />
                    ))}
                  </div>
                </div>
              ) : null}
              {nutritionHistory.length ? (
                <>
                  <div className="grid gap-3 md:grid-cols-4">
                    <MetricCard title="7-day calories" value={nutritionAdherence?.average_calories ? `${Math.round(nutritionAdherence.average_calories)}` : "No data"} detail={nutritionAdherence?.average_calories_delta !== null && nutritionAdherence?.average_calories_delta !== undefined ? `${deltaText(nutritionAdherence.average_calories_delta, " kcal")} avg` : "Target comparison pending"} icon={Apple} accent="accent-outline" />
                    <MetricCard title="7-day protein" value={nutritionAdherence?.average_protein ? `${Math.round(nutritionAdherence.average_protein)}g` : "No data"} detail={nutritionAdherence?.average_protein_delta !== null && nutritionAdherence?.average_protein_delta !== undefined ? `${deltaText(nutritionAdherence.average_protein_delta, "g")} avg` : "Target comparison pending"} icon={Utensils} accent="border-teal-400/20 bg-teal-400/10 text-teal-300" />
                    <MetricCard title="Days over target" value={`${nutritionAdherence?.days_over_target ?? 0}`} detail="Recent 7 logged days" icon={Gauge} accent="border-amber-400/20 bg-amber-400/10 text-amber-300" />
                    <MetricCard title="Consistency" value={nutritionAdherence?.consistency_score ? `${Math.round(nutritionAdherence.consistency_score)}%` : "No target"} detail="Calories and macro adherence" icon={Sparkles} accent="border-violet-400/20 bg-violet-400/10 text-violet-300" />
                  </div>
                  {nutritionAdherence?.data_quality_note ? (
                    <p className={cx("text-xs", (nutritionAdherence.missing_days ?? 0) > 0 ? "text-amber-300/90" : "text-zinc-500")}>
                      Nutrition confidence: {(nutritionAdherence.confidence ?? "low").replace(/^./, (c) => c.toUpperCase())} - {nutritionAdherence.data_quality_note}
                    </p>
                  ) : null}
                  <ChartFrame className="h-72">
                    <ResponsiveContainer width="100%" height="100%">
                      <RechartsLineChart data={recentHistory}>
                        <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                        <XAxis dataKey="date" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                        <YAxis stroke="#71717a" tickLine={false} axisLine={false} />
                        <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                        <Line dataKey="total_calories" name="Calories" stroke="#60a5fa" strokeWidth={3} dot={false} />
                        <Line dataKey="target_calories" name="Target" stroke="var(--accent-primary)" strokeWidth={2} strokeDasharray="4 4" dot={false} />
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
                </>
              ) : null}
              <FoodHistoryList logs={logs} nutritionHistory={nutritionHistory} />
            </div>
          </Card>
        ) : null}
      </div>
      <div className="order-first flex min-w-0 flex-col gap-4 xl:order-none">
      <Card className="order-3 min-w-0">
        <SectionHeader eyebrow="Food" title="Manual food entry" />
        <div className="mb-4 rounded-lg border border-emerald-300/25 bg-emerald-300/[0.07] p-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-emerald-50">Gym Marker</p>
              <p className="mt-1 text-xs leading-5 text-emerald-100/75">
                Place this after logging pre-workout foods. Foods logged after it are post-workout for {selectedDateLabel}.
              </p>
              <p className="mt-2 text-xs font-medium text-emerald-100">{markerStatusText}</p>
            </div>
            {latestSelectedMarker ? (
              <span className="w-fit shrink-0 rounded-full border border-emerald-300/25 bg-emerald-300/10 px-3 py-1 text-xs font-semibold text-emerald-100">
                {selectedDateMarkers.length} marker{selectedDateMarkers.length === 1 ? "" : "s"}
              </span>
            ) : null}
          </div>
          <form onSubmit={onWorkoutMarkerSubmit} className="mt-3 grid gap-3 md:grid-cols-[minmax(130px,0.8fr)_minmax(110px,0.65fr)_minmax(0,1fr)_auto] md:items-end">
            <SelectInput label="Type" value={forms.workoutMarker.workout_type} options={["Strength", "Run", "Cardio", "Mobility", "Other"]} onChange={(value) => setForms((state) => ({ ...state, workoutMarker: { ...state.workoutMarker, workout_type: value } }))} />
            <TextInput label="Time optional" type="time" value={forms.workoutMarker.workout_time} onChange={(value) => setForms((state) => ({ ...state, workoutMarker: { ...state.workoutMarker, workout_time: value } }))} />
            <TextInput label="Notes optional" value={forms.workoutMarker.notes} placeholder="Pull day, legs, gym, etc." onChange={(value) => setForms((state) => ({ ...state, workoutMarker: { ...state.workoutMarker, notes: value } }))} />
            <button className="accent-bg h-11 rounded-lg px-4 text-sm font-semibold">
              Log Workout Marker
            </button>
          </form>
        </div>
        <div className="mb-4 grid grid-cols-2 rounded-lg border border-white/10 bg-white/[0.035] p-1 text-sm">
          {(["direct", "serving"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setManualFoodMode(mode)}
              className={cx("rounded-md px-3 py-2 font-semibold transition", manualFoodMode === mode ? "accent-active" : "text-zinc-300 hover:bg-white/[0.04]")}
            >
              {mode === "direct" ? "Direct macros" : "Serving-size scaling"}
            </button>
          ))}
        </div>
        <form onSubmit={onSubmit} className="grid min-w-0 gap-4" data-testid="manual-food-form">
          <TextInput label="Date" type="date" value={forms.nutrition.date} onChange={(value) => setForms((state) => ({ ...state, nutrition: { ...state.nutrition, date: value } }))} />
          {manualFoodMode === "direct" ? (
            <>
              <TextInput label="Food name" required value={forms.nutrition.food_name} onChange={(value) => setForms((state) => ({ ...state, nutrition: { ...state.nutrition, food_name: value } }))} />
              <TextInput label="Amount / serving optional" value={forms.nutrition.serving_description ?? ""} onChange={(value) => setForms((state) => ({ ...state, nutrition: { ...state.nutrition, serving_description: value } }))} />
              <TextInput label="Calories" type="number" min={0} step="any" value={forms.nutrition.calories} onChange={updateDirectCalories} />
              {(hasDirectMacroCalories || manualCaloriesOverridden) ? (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-white/[0.035] px-3 py-2 text-xs text-zinc-400">
                  <span>{manualCaloriesOverridden ? "Calories manually overridden" : "Calories calculated from macros"}</span>
                  {manualCaloriesOverridden ? (
                    <button type="button" onClick={applyCalculatedCalories} className="accent-text font-semibold">
                      Use macro calories
                    </button>
                  ) : null}
                </div>
              ) : null}
              <TextInput label="Protein" type="number" min={0} step="any" value={forms.nutrition.protein} onChange={(value) => updateDirectMacro("protein", value)} />
              <TextInput label="Carbs" type="number" min={0} step="any" value={forms.nutrition.carbs} onChange={(value) => updateDirectMacro("carbs", value)} />
              <TextInput label="Fat" type="number" min={0} step="any" value={forms.nutrition.fat} onChange={(value) => updateDirectMacro("fat", value)} />
              <TextInput label="Fiber optional" type="number" min={0} step="any" value={forms.nutrition.fiber ?? ""} onChange={(value) => setForms((state) => ({ ...state, nutrition: { ...state.nutrition, fiber: value === "" ? null : Number(value) } }))} />
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
                  className="accent-file mt-3 block w-full text-sm text-zinc-300 file:mr-3 file:px-3 file:py-2 file:text-sm"
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
          <button disabled={manualSaving} className="accent-bg h-11 rounded-lg text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60">
            {manualSaving ? "Saving food..." : manualFoodMode === "serving" ? "Save scaled food entry" : "Add Food"}
          </button>
          {manualFoodMode === "serving" ? (
            <button type="button" onClick={onSaveServingShortcut} className="h-11 rounded-lg border border-emerald-300/30 bg-emerald-300/10 text-sm font-semibold text-emerald-100">
              Save scaled food as shortcut
            </button>
          ) : null}
        </form>
      </Card>
      <div className="contents">
        <Card className="hidden">
          <SectionHeader eyebrow="Targets" title="Macro progress" />
          {hasMacroTargets ? (
            <div className="space-y-4">
              {dayTypeMacros ? (
                <div className="accent-outline rounded-lg border p-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <p className="text-sm font-semibold text-white">{dayTypeMacros.day_type}</p>
                      <p className="mt-1 text-sm leading-6 text-zinc-400">{dayTypeMacros.reason}</p>
                    </div>
                    <span className="accent-outline w-fit rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em]">
                      {dayTypeMacros.confidence} confidence
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    <span className="rounded-full border border-white/10 px-2.5 py-1 text-zinc-300">{dayTypeMacros.delta.calories >= 0 ? "+" : ""}{dayTypeMacros.delta.calories} kcal</span>
                    <span className="rounded-full border border-white/10 px-2.5 py-1 text-zinc-300">P {dayTypeMacros.delta.protein >= 0 ? "+" : ""}{dayTypeMacros.delta.protein}g</span>
                    <span className="rounded-full border border-white/10 px-2.5 py-1 text-zinc-300">C {dayTypeMacros.delta.carbs >= 0 ? "+" : ""}{dayTypeMacros.delta.carbs}g</span>
                    <span className="rounded-full border border-white/10 px-2.5 py-1 text-zinc-300">F {dayTypeMacros.delta.fat >= 0 ? "+" : ""}{dayTypeMacros.delta.fat}g</span>
                  </div>
                  {dayTypeMacros.signals.length ? <p className="mt-3 text-xs leading-5 text-zinc-500">{dayTypeMacros.signals[0]}</p> : null}
                </div>
              ) : null}
              {adaptiveRecommendation ? (
                <div className="rounded-lg border border-emerald-300/15 bg-emerald-300/[0.055] p-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <p className="text-sm font-semibold text-white">Adaptive baseline recommendation</p>
                      <p className="mt-1 text-sm leading-6 text-zinc-400">
                        {adaptiveRecommendation.caloriesTarget} kcal · P {adaptiveRecommendation.proteinTarget}g · C {adaptiveRecommendation.carbsTarget}g · F {adaptiveRecommendation.fatTarget}g
                      </p>
                      <p className="mt-1 text-xs leading-5 text-zinc-500">{adaptiveRecommendation.reasoning?.[0] ?? "Recommendation updates with body, food, training, runs, and recovery data."}</p>
                    </div>
                    <button
                      type="button"
                      onClick={onApplySuggestedMacros}
                      className="w-fit rounded-lg bg-emerald-300 px-3 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-200"
                    >
                      Apply
                    </button>
                  </div>
                </div>
              ) : null}
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
        <Card className="hidden">
          <SectionHeader
            eyebrow="Today"
            title={`Food logged for ${selectedDateLabel}`}
            action={
              <button onClick={() => setShowFoodHistory((value) => !value)} className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04]">
                {showFoodHistory ? "Hide Food History" : "View Food History"}
                <ChevronDown className={cx("h-4 w-4 transition", showFoodHistory ? "rotate-180" : "")} />
              </button>
            }
          />
          <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
            <MetricCard title="Calories" value={`${Math.round(selectedDateTotals.calories)}`} detail="selected day" icon={Apple} accent="accent-outline" />
            <MetricCard title="Protein" value={`${Math.round(selectedDateTotals.protein)}g`} detail="selected day" icon={ProteinMoleculeIcon} accent="border-teal-400/20 bg-teal-400/10 text-teal-300" />
            <MetricCard title="Carbs" value={`${Math.round(selectedDateTotals.carbs)}g`} detail="selected day" icon={CarbsMoleculeIcon} accent="border-blue-400/20 bg-blue-400/10 text-blue-300" />
            <MetricCard title="Fat" value={`${Math.round(selectedDateTotals.fat)}g`} detail="selected day" icon={FatMoleculeIcon} accent="border-amber-400/20 bg-amber-400/10 text-amber-300" />
          </div>
          <div className="mt-4">
            <FoodLogList
              entries={selectedDateEntries.slice().reverse()}
              emptyDescription="Manual entries for this date will appear here immediately after saving."
              onRemove={(entry) => void removeFoodLogEntry(entry)}
              removingId={deletingFoodLogId}
              onEdit={beginFoodLogEdit}
              editingId={editingFoodLogId}
              editingIcon={editingFoodLogIcon}
              onEditingIconChange={setEditingFoodLogIcon}
              onCancelEdit={cancelFoodLogEdit}
              onSaveIcon={(entry) => void saveFoodLogIcon(entry)}
              savingId={savingFoodLogId}
            />
          </div>
        </Card>
        {showFoodHistory ? (
          <Card className="hidden">
            <SectionHeader eyebrow="History" title="Food history" />
            {nutritionHistory.length ? (
              <div className="space-y-4">
                <div className="grid gap-3 md:grid-cols-4">
                  <MetricCard title="7-day calories" value={nutritionAdherence?.average_calories ? `${Math.round(nutritionAdherence.average_calories)}` : "No data"} detail={nutritionAdherence?.average_calories_delta !== null && nutritionAdherence?.average_calories_delta !== undefined ? `${deltaText(nutritionAdherence.average_calories_delta, " kcal")} avg` : "Target comparison pending"} icon={Apple} accent="accent-outline" />
                  <MetricCard title="7-day protein" value={nutritionAdherence?.average_protein ? `${Math.round(nutritionAdherence.average_protein)}g` : "No data"} detail={nutritionAdherence?.average_protein_delta !== null && nutritionAdherence?.average_protein_delta !== undefined ? `${deltaText(nutritionAdherence.average_protein_delta, "g")} avg` : "Target comparison pending"} icon={Utensils} accent="border-teal-400/20 bg-teal-400/10 text-teal-300" />
                  <MetricCard title="Days over target" value={`${nutritionAdherence?.days_over_target ?? 0}`} detail="Recent 7 logged days" icon={Gauge} accent="border-amber-400/20 bg-amber-400/10 text-amber-300" />
                  <MetricCard title="Consistency" value={nutritionAdherence?.consistency_score ? `${Math.round(nutritionAdherence.consistency_score)}%` : "No target"} detail="Calories and macro adherence" icon={Sparkles} accent="border-violet-400/20 bg-violet-400/10 text-violet-300" />
                </div>
                {nutritionAdherence?.data_quality_note ? (
                  <p className={cx("text-xs", (nutritionAdherence.missing_days ?? 0) > 0 ? "text-amber-300/90" : "text-zinc-500")}>
                    Nutrition confidence: {(nutritionAdherence.confidence ?? "low").replace(/^./, (c) => c.toUpperCase())} — {nutritionAdherence.data_quality_note}
                  </p>
                ) : null}
                <ChartFrame className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <RechartsLineChart data={recentHistory}>
                      <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                      <YAxis stroke="#71717a" tickLine={false} axisLine={false} />
                      <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                      <Line dataKey="total_calories" name="Calories" stroke="#60a5fa" strokeWidth={3} dot={false} />
                      <Line dataKey="target_calories" name="Target" stroke="var(--accent-primary)" strokeWidth={2} strokeDasharray="4 4" dot={false} />
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
                <FoodHistoryList logs={logs} nutritionHistory={nutritionHistory} />
              </div>
            ) : (
              <FoodHistoryList logs={logs} nutritionHistory={nutritionHistory} />
            )}
          </Card>
        ) : null}
        <Card className="order-2 min-w-0">
          <SectionHeader eyebrow="AI text entry" title="Analyze food text" />
          <form onSubmit={onParseFood} className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <TextInput label="Date" type="date" value={forms.nutrition.date} onChange={(value) => setForms((state) => ({ ...state, nutrition: { ...state.nutrition, date: value } }))} />
            </div>
            <label className="block space-y-2 text-sm text-zinc-400">
              <span>Food list</span>
              <textarea
                className="accent-focus min-h-32 w-full resize-y rounded-lg border border-white/10 bg-white/[0.04] px-3 py-3 text-zinc-100 outline-none transition placeholder:text-zinc-600"
                value={aiText}
                maxLength={4000}
                placeholder="Example: 2 Kirkland bagels, Built Puff Bar, Fairlife milk"
                onChange={(event) => setAiText(event.target.value)}
              />
              <span className="block text-xs text-zinc-600">{aiText.length}/4000</span>
            </label>
            <button disabled={parseLoading || !aiText.trim() || !aiParsingConfigured} className="h-11 rounded-lg bg-violet-300 px-4 text-sm font-semibold text-zinc-950 disabled:cursor-not-allowed disabled:opacity-60">
              {parseLoading ? "Analyzing..." : "Analyze"}
            </button>
          </form>
          {!aiParsingConfigured ? (
            <p className="mt-3 text-sm text-zinc-400">AI food parsing is not configured yet. You can still log foods manually.</p>
          ) : null}
          {shortcutSuggestion ? (
            <div className="accent-outline mt-4 rounded-lg border p-4">
              <p className="text-sm font-semibold">Use saved {shortcutSuggestion.type} instead?</p>
              <p className="mt-1 text-sm text-zinc-300">{shortcutSuggestion.label} looks close to what you typed. Logging it avoids another OpenAI call.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button onClick={onUseSuggestion} className="accent-bg rounded-lg px-3 py-2 text-sm font-semibold">Use saved shortcut</button>
                <button onClick={onParseAnyway} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200">Parse new anyway</button>
              </div>
            </div>
          ) : null}
          {parseResult ? (
            <div className={cx("mt-4 rounded-lg border p-3 text-sm", parseResult.success ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-100" : "border-amber-300/20 bg-amber-300/10 text-amber-100")}>
              <p>{parseResult.message}</p>
            </div>
          ) : null}
          {showFoodAiDebugDetails && foodAiFlow.length ? (
            <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.035] p-3">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">AI food flow</p>
              <div className="mt-3 space-y-2">
                {foodAiFlow.map((item) => (
                  <div key={`${item.step}-${item.status}-${item.message}`} className="flex items-start gap-2 text-xs leading-5">
                    <span className={cx(
                      "mt-0.5 inline-flex rounded-full border px-2 py-0.5 font-semibold uppercase tracking-[0.12em]",
                      item.status === "ok" ? "border-emerald-300/25 bg-emerald-300/10 text-emerald-100" : item.status === "pending" ? "border-amber-300/25 bg-amber-300/10 text-amber-100" : "border-red-300/25 bg-red-300/10 text-red-100",
                    )}>
                      {item.status}
                    </span>
                    <p className="break-words text-zinc-300"><span className="font-semibold text-white">{item.step}:</span> {item.message}</p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {showFoodAiDebugDetails && foodAiDebug ? (
            <div className="mt-4 rounded-lg border border-violet-300/20 bg-violet-300/[0.07] p-3">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-violet-200">Temporary parser debug</p>
              <div className="mt-3 grid gap-2 text-xs leading-5 text-zinc-300 sm:grid-cols-2">
                <p><span className="font-semibold text-white">endpoint_called:</span> {foodAiDebug.endpoint_called || foodAiDebug.analyzeEndpoint || "not called"}</p>
                <p><span className="font-semibold text-white">diagnostic_force_openai:</span> {foodAiDebug.diagnostic_force_openai === undefined ? "false" : String(foodAiDebug.diagnostic_force_openai)}</p>
                <p><span className="font-semibold text-white">openai_called:</span> {foodAiDebug.openai_called === undefined ? "unknown" : String(foodAiDebug.openai_called)}</p>
                <p><span className="font-semibold text-white">model_used:</span> {foodAiDebug.model_used || "unknown"}</p>
                <p><span className="font-semibold text-white">escalated:</span> {foodAiDebug.escalated === undefined ? "false" : String(foodAiDebug.escalated)}</p>
                <p><span className="font-semibold text-white">final_model:</span> {foodAiDebug.final_model || foodAiDebug.model_used || "unknown"}</p>
                <p><span className="font-semibold text-white">parser_source:</span> {foodAiDebug.parser_source || "unknown"}</p>
                <p><span className="font-semibold text-white">external_lookup_status:</span> {foodAiDebug.external_lookup_status || "unknown"}</p>
                <p><span className="font-semibold text-white">estimated_cost_usd:</span> {Number.isFinite(foodAiDebug.estimated_cost_usd) ? `$${Number(foodAiDebug.estimated_cost_usd).toFixed(4)}` : "unknown"}</p>
                <p><span className="font-semibold text-white">raw_items_count:</span> {foodAiDebug.raw_items_count ?? "unknown"}</p>
                <p><span className="font-semibold text-white">normalized_items_count:</span> {foodAiDebug.normalized_items_count ?? foodAiDebug.parsedItemCount ?? 0}</p>
                <p><span className="font-semibold text-white">frontend_received_items:</span> {foodAiDebug.frontend_received_items === undefined ? "unknown" : String(foodAiDebug.frontend_received_items)}</p>
                <p><span className="font-semibold text-white">log_insert_attempted:</span> {foodAiDebug.log_insert_attempted === undefined ? "false" : String(foodAiDebug.log_insert_attempted)}</p>
                <p><span className="font-semibold text-white">log_insert_success:</span> {foodAiDebug.log_insert_success === undefined ? "false" : String(foodAiDebug.log_insert_success)}</p>
                <p><span className="font-semibold text-white">Response:</span> {foodAiDebug.analyzeResponseStatus || "pending"}</p>
                <p><span className="font-semibold text-white">Parsed items:</span> {foodAiDebug.parsedItemCount ?? 0}</p>
                <p><span className="font-semibold text-white">Log insert:</span> {foodAiDebug.logInsertStatus || "not started"}</p>
                <p><span className="font-semibold text-white">Saved rows:</span> {foodAiDebug.logCreated ?? 0}{foodAiDebug.logRequested !== undefined ? ` / ${foodAiDebug.logRequested}` : ""}</p>
                <p><span className="font-semibold text-white">Refresh:</span> {foodAiDebug.refreshStatus || "not started"}</p>
              </div>
              {foodAiDebug.escalation_reason ? (
                <p className="mt-3 rounded-lg border border-amber-300/25 bg-amber-300/10 p-2 text-xs text-amber-100">
                  Escalation reason: {foodAiDebug.escalation_reason}
                </p>
              ) : null}
              {foodAiDebug.exactError ? (
                <p className="mt-3 rounded-lg border border-red-300/25 bg-red-300/10 p-2 text-xs text-red-100">
                  {foodAiDebug.exactError}
                </p>
              ) : null}
              <details className="mt-3">
                <summary className="cursor-pointer text-xs font-semibold text-violet-100">Request/response details</summary>
                <pre className="mt-2 max-h-72 overflow-auto rounded-lg border border-white/10 bg-zinc-950/70 p-3 text-xs leading-5 text-zinc-300">
                  {JSON.stringify(foodAiDebug, null, 2)}
                </pre>
              </details>
            </div>
          ) : null}
          {parsedFoods.length ? (
            <form onSubmit={onSaveParsedFoods} className="mt-5 space-y-4">
              <p className="text-sm text-zinc-400">Review and edit before saving. Nothing is saved until you confirm these draft items.</p>
              {parsedFoods.map((food, index) => (
                <div key={index} className="grid gap-3 rounded-lg border border-white/10 bg-white/[0.035] p-3 sm:grid-cols-2">
                  <div className="flex items-start justify-between gap-3 sm:col-span-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-white">{food.food_name?.trim() || `Draft item ${index + 1}`}</p>
                      {food.original_text && food.original_text.trim() && food.original_text.trim() !== food.food_name?.trim() ? (
                        <p className="mt-0.5 truncate text-xs text-zinc-500">Original: &ldquo;{food.original_text}&rdquo;</p>
                      ) : null}
                      <p className="mt-1 text-xs text-zinc-400">
                        {Math.round(Number(food.calories) || 0)} kcal · P {Number(food.protein) || 0}g · C {Number(food.carbs) || 0}g · F {Number(food.fat) || 0}g
                        <span className="ml-1 text-zinc-500">· {food.source || "openai_estimate"} · {food.confidence || "medium"} confidence</span>
                      </p>
                    </div>
                    <div className="flex shrink-0 gap-2">
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
                    <select className="accent-focus h-11 w-full rounded-lg border border-white/10 bg-zinc-950 px-3 text-zinc-100 outline-none transition" value={food.confidence || "medium"} onChange={(event) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, confidence: event.target.value } : item))}>
                      <option value="high">high</option>
                      <option value="medium">medium</option>
                      <option value="low">low</option>
                    </select>
                  </div>
                  <div className="space-y-2 text-sm text-zinc-400">
                    <span>Source</span>
                    <select className="accent-focus h-11 w-full rounded-lg border border-white/10 bg-zinc-950 px-3 text-zinc-100 outline-none transition" value={food.source || "openai_estimate"} onChange={(event) => setParsedFoods((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, source: event.target.value } : item))}>
                      <option value="saved_shortcut">Saved shortcut</option>
                      <option value="usda_fdc">USDA</option>
                      <option value="existing_database">Existing database</option>
                      <option value="openai_estimate">OpenAI estimate</option>
                      <option value="web_source">Web source</option>
                    </select>
                  </div>
                  <div className={cx("sm:col-span-2 rounded-lg border p-3 text-sm", food.confidence === "low" || food.verification_status?.includes("unavailable") || food.verification_status?.includes("conflict") ? "border-amber-300/25 bg-amber-300/10 text-amber-100" : "border-white/10 bg-white/[0.035] text-zinc-300")}>
                    <p className="font-medium text-white">Review notes</p>
                    {food.needs_confirmation || food.confidence === "low" ? (
                      <p className="mt-1 font-medium text-amber-100">Needs confirmation before logging.</p>
                    ) : null}
                    <p className="mt-1">Original: {food.original_text || food.food_name}</p>
                    {food.assumptions?.length ? (
                      <ul className="mt-2 list-disc space-y-1 pl-5">
                        {food.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}
                      </ul>
                    ) : (
                      <p className="mt-1">{food.verification_reason || (food.source === "usda_fdc" ? "Matched nutrition database source context." : "Estimate only. Please review.")}</p>
                    )}
                    {food.source_url ? (
                      <a className="accent-link mt-2 inline-flex underline" href={food.source_url} target="_blank" rel="noreferrer">
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
                <button className="accent-bg h-11 rounded-lg px-4 text-sm font-semibold">
                  Save to today
                </button>
                <button type="button" onClick={(event) => onSaveShortcut(event as unknown as FormEvent)} className="h-11 rounded-lg border border-emerald-300/30 bg-emerald-300/10 px-4 text-sm font-semibold text-emerald-100">
                  Save as Food Shortcut
                </button>
                <button type="button" onClick={(event) => onSaveMealTemplate(event as unknown as FormEvent)} className="h-11 rounded-lg border border-violet-300/30 bg-violet-300/10 px-4 text-sm font-semibold text-violet-100">
                  Save as Meal Template
                </button>
                <button type="button" onClick={(event) => onSaveAndLogToday(event as unknown as FormEvent)} className="h-11 rounded-lg bg-amber-300 px-4 text-sm font-semibold text-zinc-950">
                  Save shortcut, meal, and log
                </button>
              </div>
            </form>
          ) : null}
        </Card>
        <Card className="hidden">
          <SectionHeader eyebrow="Log" title="Recent saved foods" />
          <FoodLogList entries={logs.slice(-5).reverse()} emptyDescription="Manual food entries will appear here after saving." />
        </Card>
        <Card className="order-1 min-w-0">
          <SectionHeader
            eyebrow="Fast log"
            title="Preset foods & meals"
            action={
              <div className="flex flex-wrap items-center justify-end gap-2">
                {quickFoodPendingCount ? (
                  <span className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-2.5 py-1 text-xs font-semibold text-emerald-100">
                    {quickFoodPendingCount} queued
                  </span>
                ) : null}
                <button
                  type="button"
                  onClick={() => {
                    setPresetEditMode((value) => !value);
                    setEditingShortcut(null);
                    cancelTemplateRename();
                  }}
                  className={cx("inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition", presetEditMode ? "accent-outline" : "border-white/10 text-zinc-200 hover:bg-white/[0.04]")}
                >
                  <Pencil className="h-4 w-4" />
                  {presetEditMode ? "Done editing" : "Edit Presets"}
                </button>
              </div>
            }
          />
          <div className="space-y-4">
            <div className="grid grid-cols-3 rounded-lg border border-white/10 bg-white/[0.035] p-1 text-sm">
              {shortcutTabs.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setShortcutTab(tab.id)}
                  className={cx("rounded-md px-2 py-2 font-semibold transition", shortcutTab === tab.id ? "accent-active" : "text-zinc-300 hover:bg-white/[0.04]")}
                >
                  <span className="block truncate">{tab.label}</span>
                  <span className={cx("mt-0.5 block text-[11px]", shortcutTab === tab.id ? "text-zinc-900" : "text-zinc-500")}>{tab.count}</span>
                </button>
              ))}
            </div>
            <TextInput label="Search saved items" value={shortcutQuery} placeholder="Bagel, shake, burrito" onChange={setShortcutQuery} />
            {shortcutTab === "saved" ? (
              filteredShortcuts.length ? (
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 xl:grid-cols-6">
                  {filteredShortcuts.map((shortcut, index) => {
                    const editing = presetEditMode && editingShortcut?.shortcut_id === shortcut.shortcut_id;
                    const status = quickFoodLogStatuses[shortcutQuickLogKey(shortcut)];
                    return (
                      <PresetFoodTile
                        key={shortcut.shortcut_id}
                        shortcut={shortcut}
                        toneIndex={index}
                        status={status}
                        disabled={Boolean(pendingPresetAction?.startsWith("edit:"))}
                        editing={editing}
                        editMode={presetEditMode}
                        onClick={() => void handleShortcutTileClick(shortcut)}
                      />
                    );
                  })}
                </div>
                {editingShortcut ? (
                  <div className="space-y-3">
                    <PresetFoodEditor
                      shortcut={editingShortcut}
                      saving={pendingPresetAction === `edit:${editingShortcut.shortcut_id}`}
                      onChange={setEditingShortcut}
                      onSave={() => void handleSaveShortcutEdit()}
                      onCancel={() => setEditingShortcut(null)}
                    />
                    {!isDefaultPresetShortcut(editingShortcut) ? (
                      <button
                        type="button"
                        onClick={() => void handleDeleteShortcut(editingShortcut)}
                        disabled={pendingPresetAction === `delete:${editingShortcut.shortcut_id}`}
                        className="inline-flex items-center gap-2 rounded-lg border border-red-300/25 bg-red-300/10 px-3 py-2 text-sm font-semibold text-red-100 transition hover:bg-red-300/15 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Trash2 className="h-4 w-4" />
                        {pendingPresetAction === `delete:${editingShortcut.shortcut_id}` ? "Deleting..." : "Delete preset"}
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : (
              <EmptyState title="No matching presets" description="Clear the search or save a new shortcut from the AI review flow." action="Use AI parser" onAction={() => undefined} />
            )
            ) : null}
            {shortcutTab === "meals" ? (
              filteredTemplateSummaries.length ? (
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 xl:grid-cols-6">
                  {filteredTemplateSummaries.map((template) => {
                    const status = quickFoodLogStatuses[mealTemplateQuickLogKey(template.template_name)];
                    const pendingCount = status?.pending ?? 0;
                    const label = status?.error
                      ? "Retry"
                      : pendingCount > 1
                        ? `Adding ${pendingCount}`
                        : pendingCount === 1
                          ? "Adding..."
                          : status?.added
                            ? "Added"
                            : template.template_name;
                    return (
                      <button
                        key={template.template_name}
                        type="button"
                        onClick={() => presetEditMode ? beginTemplateRename(template.template_name) : void logTemplate(template)}
                        disabled={pendingTemplateAction === `rename:${template.template_name}`}
                        className={cx(
                          "group relative aspect-square min-w-0 rounded-lg border bg-violet-300/[0.045] p-2 text-center text-xs font-semibold text-white transition hover:-translate-y-0.5 hover:bg-violet-300/[0.075] disabled:cursor-not-allowed disabled:opacity-60",
                          editingTemplateName === template.template_name ? "border-violet-200/60 shadow-[0_0_22px_rgba(196,181,253,0.12)]" : "border-violet-300/15",
                        )}
                        title={presetEditMode ? `Rename ${template.template_name}` : `Add ${template.template_name} to today`}
                      >
                        {presetEditMode ? <Pencil className="absolute right-2 top-2 h-3.5 w-3.5 text-violet-200/70" /> : null}
                        {status?.added ? <Check className="absolute right-2 top-2 h-3.5 w-3.5 text-emerald-200" /> : null}
                        {pendingCount > 1 ? <span className="absolute left-2 top-2 rounded-full border border-white/10 bg-black/30 px-1.5 py-0.5 text-[10px] text-zinc-100">{pendingCount}</span> : null}
                        <span className={cx("flex h-full items-center justify-center break-words leading-4", status?.error ? "text-red-100" : "")}>
                          {label}
                        </span>
                      </button>
                    );
                  })}
                </div>
                {editingTemplateName ? (
                  <div className="rounded-lg border border-white/10 bg-zinc-950/50 p-4">
                    <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                      <TextInput label="Template name" value={templateRenameValue} onChange={setTemplateRenameValue} />
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => void saveTemplateRename(editingTemplateName)}
                          disabled={!templateRenameValue.trim() || pendingTemplateAction === `rename:${editingTemplateName}`}
                          className="accent-bg inline-flex h-11 w-11 items-center justify-center rounded-lg transition disabled:cursor-not-allowed disabled:opacity-50"
                          aria-label="Save template name"
                        >
                          <Check className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={cancelTemplateRename}
                          disabled={pendingTemplateAction === `rename:${editingTemplateName}`}
                          className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-white/10 text-zinc-300 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-50"
                          aria-label="Cancel template rename"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : (
              <EmptyState title="No meal templates yet" description="Save an AI parse as a meal template to reuse it here." action="Use AI parser" onAction={() => undefined} />
            )
            ) : null}
            {shortcutTab === "frequent" ? (
              filteredFrequentFoods.length ? (
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 xl:grid-cols-6">
                  {filteredFrequentFoods.map((food) => {
                    const status = quickFoodLogStatuses[frequentFoodQuickLogKey(food.food_name)];
                    const pendingCount = status?.pending ?? 0;
                    const label = status?.error
                      ? "Retry"
                      : pendingCount > 1
                        ? `Adding ${pendingCount}`
                        : pendingCount === 1
                          ? "Adding..."
                          : status?.added
                            ? "Added"
                            : food.food_name;
                    return (
                      <button
                        key={food.food_name}
                        type="button"
                        onClick={() => void handleFrequentTileClick(food)}
                        disabled={presetEditMode}
                        className="relative aspect-square min-w-0 rounded-lg border border-white/10 bg-white/[0.035] p-2 text-center text-xs font-semibold text-white transition hover:-translate-y-0.5 hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-60"
                        title={`Add ${food.food_name} to today`}
                      >
                        {food.is_favorite ? <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-amber-300" /> : null}
                        {status?.added ? <Check className="absolute right-2 top-2 h-3.5 w-3.5 text-emerald-200" /> : null}
                        {pendingCount > 1 ? <span className="absolute left-2 top-2 rounded-full border border-white/10 bg-black/30 px-1.5 py-0.5 text-[10px] text-zinc-100">{pendingCount}</span> : null}
                        <span className={cx("flex h-full items-center justify-center break-words leading-4", status?.error ? "text-red-100" : "")}>
                          {label}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : (
                <EmptyState title="No frequent foods yet" description="Frequent foods appear after repeated logging." action="Log food" onAction={() => undefined} />
              )
            ) : null}
          </div>
        </Card>
      </div>
      </div>
    </div>
  );
}

type WeightChartPoint = {
  date: string;
  timestamp: number;
  bodyweight: number;
  movingAverage7: number | null;
  dailyChange: number | null;
  bodyFat: number | null;
  leanMass: number | null;
  fatMass: number | null;
  muscleMass: number | null;
  hydration: number | null;
  bmi: number | null;
  source: string;
};

type CaloriesBodyTrendPoint = {
  date: string;
  calories: number | null;
  calories7DayAverage: number | null;
  targetCalories: number | null;
  bodyweight: number | null;
  bodyweight7DayAverage: number | null;
  bodyFatPercent: number | null;
  bodyFat7PointAverage: number | null;
};

type BodyCompositionTab = "weight" | "body_fat" | "mass" | "muscle" | "hydration_bmi";

const bodyCompositionTabs: Array<{ id: BodyCompositionTab; label: string }> = [
  { id: "weight", label: "Weight" },
  { id: "body_fat", label: "Body Fat %" },
  { id: "mass", label: "Lean/Fat Mass" },
  { id: "muscle", label: "Muscle Mass" },
  { id: "hydration_bmi", label: "Hydration/BMI" },
];

function formatWeight(value?: number | null, digits = 1) {
  return Number.isFinite(Number(value)) ? `${Number(value).toFixed(digits)} lb` : "--";
}

function formatMetricValue(value: number | null | undefined, unit = "", digits = 1) {
  if (!Number.isFinite(Number(value))) return "--";
  if (!unit) return Number(value).toFixed(digits);
  return `${Number(value).toFixed(digits)}${unit === "%" ? "%" : ` ${unit}`}`;
}

function formatWeightDelta(value?: number | null) {
  if (!Number.isFinite(Number(value))) return "--";
  const amount = Number(value);
  return `${amount >= 0 ? "+" : ""}${amount.toFixed(1)} lb`;
}

function formatPercentDelta(value?: number | null) {
  if (!Number.isFinite(Number(value))) return "--";
  const amount = Number(value);
  return `${amount >= 0 ? "+" : ""}${amount.toFixed(2)}%`;
}

function valueOrNull(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function bodyFatValue(entry: BodyMetricEntry): number | null {
  return valueOrNull(entry.estimated_body_fat ?? entry.body_fat_percent);
}

function isWithingsMetric(entry: Pick<BodyMetricEntry, "source" | "notes">) {
  const source = String(entry.source ?? "").toLowerCase();
  const notes = String(entry.notes ?? "").toLowerCase();
  return source.includes("withings") || notes.includes("source=withings");
}

function sourceLabel(source?: string | null) {
  return String(source ?? "").toLowerCase().includes("withings") ? "Withings" : source ? String(source) : "Manual";
}

function closestSameDayMetric(values: WeightChartPoint[], selected: WeightChartPoint, key: keyof WeightChartPoint): number | null {
  const candidates = values
    .filter((item) => Number.isFinite(Number(item[key])))
    .sort((a, b) => {
      const sourceRank = Number(!String(a.source).toLowerCase().includes("withings")) - Number(!String(b.source).toLowerCase().includes("withings"));
      if (sourceRank !== 0) return sourceRank;
      return Math.abs(a.timestamp - selected.timestamp) - Math.abs(b.timestamp - selected.timestamp);
    });
  return candidates.length ? Number(candidates[0][key]) : null;
}

function cleanWeightHistory(entries: BodyMetricEntry[]): WeightChartPoint[] {
  const grouped = new Map<string, WeightChartPoint[]>();
  entries.forEach((entry) => {
    const parsedDate = new Date(entry.date);
    const bodyweight = Number(entry.bodyweight);
    if (!entry.date || !Number.isFinite(parsedDate.getTime()) || !Number.isFinite(bodyweight) || bodyweight <= 0) {
      return;
    }
    const date = parsedDate.toISOString().slice(0, 10);
    const item: WeightChartPoint = {
      date,
      timestamp: parsedDate.getTime(),
      bodyweight,
      movingAverage7: null,
      dailyChange: null,
      bodyFat: bodyFatValue(entry),
      leanMass: valueOrNull(entry.lean_mass),
      fatMass: valueOrNull(entry.fat_mass),
      muscleMass: valueOrNull(entry.muscle_mass),
      hydration: valueOrNull(entry.hydration),
      bmi: valueOrNull(entry.bmi),
      source: isWithingsMetric(entry) ? "withings" : String(entry.source || "manual"),
    };
    grouped.set(date, [...(grouped.get(date) ?? []), item]);
  });

  const daily = Array.from(grouped.entries()).map(([date, values]) => {
    const sorted = values.slice().sort((a, b) => a.bodyweight - b.bodyweight || a.timestamp - b.timestamp);
    const selected = sorted[0]!;
    const source = values.some((item) => item.source.toLowerCase().includes("withings")) ? "withings" : selected.source;
    return {
      ...selected,
      date,
      bodyweight: Number(selected.bodyweight.toFixed(2)),
      bodyFat: selected.bodyFat ?? closestSameDayMetric(values, selected, "bodyFat"),
      leanMass: selected.leanMass ?? closestSameDayMetric(values, selected, "leanMass"),
      fatMass: selected.fatMass ?? closestSameDayMetric(values, selected, "fatMass"),
      muscleMass: selected.muscleMass ?? closestSameDayMetric(values, selected, "muscleMass"),
      hydration: selected.hydration ?? closestSameDayMetric(values, selected, "hydration"),
      bmi: selected.bmi ?? closestSameDayMetric(values, selected, "bmi"),
      source,
    };
  });

  return daily
    .sort((a, b) => a.timestamp - b.timestamp)
    .map((entry, index, all) => {
      const window = all.slice(Math.max(0, index - 6), index + 1);
      const movingAverage7 = window.reduce((sum, item) => sum + item.bodyweight, 0) / window.length;
      const previous = all[index - 1];
      const dailyChange = previous ? entry.bodyweight - previous.bodyweight : null;
      return { ...entry, movingAverage7: Number(movingAverage7.toFixed(2)), dailyChange: dailyChange === null ? null : Number(dailyChange.toFixed(2)) };
    });
}

function buildCaloriesBodyTrendData(
  nutritionRows: DailyNutritionSummary[],
  bodyMetricRows: BodyMetricEntry[],
): CaloriesBodyTrendPoint[] {
  const nutrition = nutritionRows
    .map((entry) => {
      const date = String(entry.date || "").slice(0, 10);
      const calories = finiteNumberOrNull(entry.total_calories);
      const targetCalories = finiteNumberOrNull(entry.target_calories);
      return date && calories !== null ? { date, calories, targetCalories } : null;
    })
    .filter((entry): entry is { date: string; calories: number; targetCalories: number | null } => entry !== null)
    .sort((a, b) => a.date.localeCompare(b.date));
  const body = cleanWeightHistory(bodyMetricRows);
  const nutritionByDate = new Map(nutrition.map((entry) => [entry.date, entry]));
  const bodyByDate = new Map(body.map((entry) => [entry.date, entry]));
  const dates = Array.from(new Set([...nutritionByDate.keys(), ...bodyByDate.keys()])).sort();
  const bodyFatAverageByDate = new Map<string, number | null>();

  body.forEach((entry, index, all) => {
    const bodyFatWindow = all
      .slice(0, index + 1)
      .filter((item) => item.bodyFat !== null)
      .slice(-7)
      .map((item) => Number(item.bodyFat));
    bodyFatAverageByDate.set(
      entry.date,
      bodyFatWindow.length ? Number((bodyFatWindow.reduce((sum, value) => sum + value, 0) / bodyFatWindow.length).toFixed(2)) : null,
    );
  });

  const dayMs = 24 * 60 * 60 * 1000;
  const dateToTime = (date: string) => new Date(`${date}T00:00:00Z`).getTime();
  return dates.map((date) => {
    const nutritionEntry = nutritionByDate.get(date) ?? null;
    const bodyEntry = bodyByDate.get(date) ?? null;
    const timestamp = dateToTime(date);
    const caloriesWindow = nutrition
      .filter((entry) => {
        const entryTime = dateToTime(entry.date);
        return entryTime <= timestamp && entryTime >= timestamp - (6 * dayMs);
      })
      .map((entry) => entry.calories);
    const calories7DayAverage = caloriesWindow.length
      ? Math.round(caloriesWindow.reduce((sum, value) => sum + value, 0) / caloriesWindow.length)
      : null;
    return {
      date,
      calories: nutritionEntry?.calories ?? null,
      calories7DayAverage,
      targetCalories: nutritionEntry?.targetCalories ?? null,
      bodyweight: bodyEntry?.bodyweight ?? null,
      bodyweight7DayAverage: bodyEntry?.movingAverage7 ?? null,
      bodyFatPercent: bodyEntry?.bodyFat ?? null,
      bodyFat7PointAverage: bodyFatAverageByDate.get(date) ?? null,
    };
  });
}

function buildWeightTrend(history: WeightChartPoint[]) {
  const latest = history.at(-1) ?? null;
  const cutoff = new Date();
  cutoff.setHours(0, 0, 0, 0);
  cutoff.setDate(cutoff.getDate() - 6);
  const recent = history.filter((entry) => entry.timestamp >= cutoff.getTime());
  const sevenDayAverage = recent.length ? recent.reduce((sum, entry) => sum + entry.bodyweight, 0) / recent.length : null;
  const fourteen = history.slice(-14);
  const twentyEight = history.slice(-28);
  const fourteenDayAverage = fourteen.length ? fourteen.reduce((sum, entry) => sum + entry.bodyweight, 0) / fourteen.length : null;
  const twentyEightDayAverage = twentyEight.length ? twentyEight.reduce((sum, entry) => sum + entry.bodyweight, 0) / twentyEight.length : null;
  const firstRecent = recent[0] ?? null;
  const latestRecent = recent.at(-1) ?? null;
  const change = firstRecent && latestRecent && recent.length >= 2 ? latestRecent.bodyweight - firstRecent.bodyweight : null;
  const percentChange = change !== null && firstRecent && firstRecent.bodyweight > 0 ? (change / firstRecent.bodyweight) * 100 : null;
  const byDate = new Map(history.map((entry) => [entry.date, entry]));
  const latestDate = latest ? new Date(`${latest.date}T00:00:00Z`) : null;
  const yesterdayDate = latestDate ? new Date(latestDate) : null;
  if (yesterdayDate) yesterdayDate.setUTCDate(yesterdayDate.getUTCDate() - 1);
  const sevenDaysAgoDate = latestDate ? new Date(latestDate) : null;
  if (sevenDaysAgoDate) sevenDaysAgoDate.setUTCDate(sevenDaysAgoDate.getUTCDate() - 7);
  const yesterday = yesterdayDate ? byDate.get(yesterdayDate.toISOString().slice(0, 10)) ?? null : null;
  const sevenDaysAgo = sevenDaysAgoDate ? byDate.get(sevenDaysAgoDate.toISOString().slice(0, 10)) ?? null : null;
  const changeVsYesterday = latest && yesterday ? latest.bodyweight - yesterday.bodyweight : null;
  const changeVsSevenDaysAgo = latest && sevenDaysAgo ? latest.bodyweight - sevenDaysAgo.bodyweight : change;
  const recentBodyFat = recent.filter((entry) => entry.bodyFat !== null);
  const bodyFatChange = recentBodyFat.length >= 2 ? Number((Number(recentBodyFat.at(-1)?.bodyFat) - Number(recentBodyFat[0].bodyFat)).toFixed(2)) : null;
  const trendLabel = change === null ? "Need more weigh-ins" : Math.abs(change) < 0.3 ? "stable" : change > 0 ? "gaining" : "losing";
  const dataQualityReason = history.length < 7 ? `Only ${history.length} canonical weigh-in day${history.length === 1 ? "" : "s"} found` : "";
  return { latest, recent, sevenDayAverage, fourteenDayAverage, twentyEightDayAverage, change, changeVsYesterday, changeVsSevenDaysAgo, percentChange, bodyFatChange, trendLabel, dataQualityReason };
}

function WeightTooltip({ active, payload, label }: Readonly<{ active?: boolean; payload?: Array<{ payload?: WeightChartPoint }>; label?: string }>) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload;
  return (
    <div className="rounded-lg border border-white/10 bg-zinc-950/95 p-3 text-sm shadow-xl">
      <p className="font-semibold text-white">{label}</p>
      <p className="mt-1 text-xs text-zinc-500">Source: {sourceLabel(point?.source)}</p>
      <p className="mt-2 text-zinc-200">Weight: {formatWeight(point?.bodyweight)}</p>
      {point?.dailyChange !== null && point?.dailyChange !== undefined ? <p className="text-zinc-400">Daily change: {formatWeightDelta(point.dailyChange)}</p> : null}
      {point?.movingAverage7 ? <p className="text-zinc-400">7-day avg: {formatWeight(point.movingAverage7)}</p> : null}
      {point?.bodyFat !== null && point?.bodyFat !== undefined ? <p className="text-zinc-400">Body fat: {point.bodyFat.toFixed(1)}%</p> : null}
      {point?.leanMass !== null && point?.leanMass !== undefined ? <p className="text-zinc-400">Lean mass: {formatWeight(point.leanMass)}</p> : null}
      {point?.fatMass !== null && point?.fatMass !== undefined ? <p className="text-zinc-400">Fat mass: {formatWeight(point.fatMass)}</p> : null}
      {point?.muscleMass !== null && point?.muscleMass !== undefined ? <p className="text-zinc-400">Muscle mass: {formatWeight(point.muscleMass)}</p> : null}
      {point?.hydration !== null && point?.hydration !== undefined ? <p className="text-zinc-400">Hydration: {formatWeight(point.hydration)}</p> : null}
      {point?.bmi !== null && point?.bmi !== undefined ? <p className="text-zinc-400">BMI: {point.bmi.toFixed(1)}</p> : null}
    </div>
  );
}

function hasCompositionData(history: WeightChartPoint[], tab: BodyCompositionTab) {
  if (tab === "weight") return history.some((entry) => Number.isFinite(entry.bodyweight));
  if (tab === "body_fat") return history.some((entry) => entry.bodyFat !== null);
  if (tab === "mass") return history.some((entry) => entry.leanMass !== null || entry.fatMass !== null);
  if (tab === "muscle") return history.some((entry) => entry.muscleMass !== null);
  return history.some((entry) => entry.hydration !== null || entry.bmi !== null);
}

function metricCardValue(point: WeightChartPoint | null | undefined, key: keyof WeightChartPoint, unit = "lb", digits = 1) {
  return formatMetricValue(point?.[key] as number | null | undefined, unit, digits);
}

function BodyCompositionChart({ history, tab }: Readonly<{ history: WeightChartPoint[]; tab: BodyCompositionTab }>) {
  if (!hasCompositionData(history, tab)) {
    return (
      <div className="flex h-80 items-center rounded-lg border border-dashed border-white/10 bg-black/10 p-4">
        <EmptyState title="No Withings body composition data yet" description="Sync Withings scale measurements to populate this chart." action="Sync from Settings" onAction={() => undefined} />
      </div>
    );
  }

  if (tab === "weight") {
    return (
      <ChartFrame className="h-96">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={history}>
            <defs>
              <linearGradient id="weightCompositionFill" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="#a3e635" stopOpacity={0.28} />
                <stop offset="100%" stopColor="#a3e635" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: "#a1a1aa", fontSize: 12 }} minTickGap={28} tickFormatter={compactDate} />
            <YAxis domain={["dataMin - 3", "dataMax + 3"]} tick={{ fill: "#a1a1aa", fontSize: 12 }} width={46} />
            <Tooltip content={<WeightTooltip />} />
            <Area type="monotone" dataKey="bodyweight" name="Weight" stroke="#a3e635" strokeWidth={3} fill="url(#weightCompositionFill)" dot={false} activeDot={{ r: 5 }} />
            <Line type="monotone" dataKey="movingAverage7" name="7-day average" stroke="#60a5fa" strokeWidth={2} dot={false} strokeDasharray="5 5" />
          </AreaChart>
        </ResponsiveContainer>
      </ChartFrame>
    );
  }

  const lines: Array<{ key: keyof WeightChartPoint; name: string; color: string; dash?: string }> = tab === "body_fat"
    ? [{ key: "bodyFat", name: "Body Fat %", color: "#f472b6" }]
    : tab === "mass"
      ? [
          { key: "leanMass", name: "Lean Mass", color: "#34d399" },
          { key: "fatMass", name: "Fat Mass", color: "#fb7185" },
        ]
      : tab === "muscle"
        ? [{ key: "muscleMass", name: "Muscle Mass", color: "#a78bfa" }]
        : [
            { key: "hydration", name: "Hydration", color: "#38bdf8" },
            { key: "bmi", name: "BMI", color: "#fbbf24", dash: "5 5" },
          ];

  return (
    <div className="space-y-3">
      <ChartFrame className="h-96">
        <ResponsiveContainer width="100%" height="100%">
          <RechartsLineChart data={history}>
            <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: "#a1a1aa", fontSize: 12 }} minTickGap={28} tickFormatter={compactDate} />
            <YAxis tick={{ fill: "#a1a1aa", fontSize: 12 }} width={46} />
            <Tooltip content={<WeightTooltip />} />
            {lines.map((line) => (
              <Line key={line.key} type="monotone" dataKey={line.key} name={line.name} stroke={line.color} strokeWidth={3} dot={false} activeDot={{ r: 5 }} strokeDasharray={line.dash} connectNulls />
            ))}
          </RechartsLineChart>
        </ResponsiveContainer>
      </ChartFrame>
      <div className="flex flex-wrap gap-3">
        {lines.map((line) => (
          <span key={line.key} className="inline-flex items-center gap-2 text-xs font-medium text-zinc-300">
            <span className="h-2 w-5 rounded-full" style={{ background: line.color }} />
            {line.name}
          </span>
        ))}
      </div>
    </div>
  );
}

function RecoveryPage({
  bodyMetrics,
  recoveryLogs,
  sleepEntries,
  wearableMetrics,
  wearableSignals,
  trainingReadiness,
  adaptiveRecommendation,
  withingsLastSyncedAt,
  forms,
  setForms,
  onBodySubmit,
  onRecoverySubmit,
  onWearableSubmit,
  onSyncWeightNow,
  onSyncWithingsHistory,
}: Readonly<{
  bodyMetrics: BodyMetricEntry[];
  recoveryLogs: RecoveryEntry[];
  sleepEntries: SleepEntry[];
  wearableMetrics: WearableMetricEntry[];
  wearableSignals: WearableSignals | null;
  trainingReadiness: TrainingReadinessSignals | null;
  adaptiveRecommendation?: AdaptiveNutritionRecommendation | null;
  withingsLastSyncedAt?: string;
  forms: FormState;
  setForms: React.Dispatch<React.SetStateAction<FormState>>;
  onBodySubmit: (event: FormEvent) => void;
  onRecoverySubmit: (event: FormEvent) => void;
  onWearableSubmit: (event: FormEvent) => void;
  onSyncWeightNow: () => void;
  onSyncWithingsHistory: () => void;
}>) {
  const [bodyCompositionTab, setBodyCompositionTab] = useState<BodyCompositionTab>("weight");
  const weightHistory = useMemo(() => cleanWeightHistory(bodyMetrics), [bodyMetrics]);
  const weightTrend = useMemo(() => buildWeightTrend(weightHistory), [weightHistory]);
  const highestWeight = weightHistory.length ? Math.max(...weightHistory.map((entry) => entry.bodyweight)) : null;
  const lowestWeight = weightHistory.length ? Math.min(...weightHistory.map((entry) => entry.bodyweight)) : null;
  const firstWeight = weightHistory[0] ?? null;
  const totalWeightChange = firstWeight && weightTrend.latest ? weightTrend.latest.bodyweight - firstWeight.bodyweight : null;
  const latestBodyFat = [...weightHistory].reverse().find((entry) => entry.bodyFat !== null)?.bodyFat ?? null;
  const withingsHistory = useMemo(() => weightHistory.filter((entry) => entry.source.toLowerCase().includes("withings")), [weightHistory]);
  const latestWithings = withingsHistory.at(-1) ?? null;
  const latestWithingsBodyFat = [...withingsHistory].reverse().find((entry) => entry.bodyFat !== null) ?? null;
  const latestWithingsLeanMass = [...withingsHistory].reverse().find((entry) => entry.leanMass !== null) ?? null;
  const latestWithingsFatMass = [...withingsHistory].reverse().find((entry) => entry.fatMass !== null) ?? null;
  const latestWithingsMuscleMass = [...withingsHistory].reverse().find((entry) => entry.muscleMass !== null) ?? null;
  const hasWithingsComposition = withingsHistory.some((entry) => (
    entry.bodyFat !== null
    || entry.leanMass !== null
    || entry.fatMass !== null
    || entry.muscleMass !== null
  ));
  const withingsCards = [
    { label: "Body Fat %", value: formatMetricValue(latestWithingsBodyFat?.bodyFat, "%", 1), detail: latestWithingsBodyFat ? `Withings body composition · ${latestWithingsBodyFat.date}` : "No Withings body fat yet" },
    { label: "Lean Mass", value: metricCardValue(latestWithingsLeanMass, "leanMass"), detail: latestWithingsLeanMass ? `Fat-free scale estimate · ${latestWithingsLeanMass.date}` : "No Withings lean mass yet" },
    { label: "Fat Mass", value: metricCardValue(latestWithingsFatMass, "fatMass"), detail: latestWithingsFatMass ? `Scale-derived fat mass · ${latestWithingsFatMass.date}` : "No Withings fat mass yet" },
    { label: "Muscle Mass", value: metricCardValue(latestWithingsMuscleMass, "muscleMass"), detail: latestWithingsMuscleMass ? `Withings muscle mass · ${latestWithingsMuscleMass.date}` : "No Withings muscle mass yet" },
  ];
  const withingsStatusText = [
    withingsLastSyncedAt ? relativeSyncTime(withingsLastSyncedAt) : "Last sync unknown",
    latestWithings?.date ? `Latest measurement: ${latestWithings.date}` : "Latest measurement: --",
  ].join(" · ");
  const trendColor = weightTrend.trendLabel === "gaining"
    ? "text-emerald-200"
    : weightTrend.trendLabel === "losing"
      ? "text-sky-200"
      : weightTrend.trendLabel === "stable"
        ? "text-zinc-100"
        : "text-amber-200";
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
  const adaptiveSignals = recordOrEmpty(adaptiveRecommendation?.signals);
  const adaptiveRecoverySignal = recordOrEmpty(adaptiveSignals.recovery);
  const adaptiveRecoveryStatus = stringOrFallback(adaptiveRecoverySignal.status);
  const adaptiveRecoveryImplication = stringOrFallback(adaptiveRecoverySignal.nutrition_implication);
  const recoveryImpact = sleepQualityScore === null
    ? "Sleep tracking will appear here once Fitbit / Google Fit is connected."
    : sleepQualityScore >= 82
      ? "Positive - sleep is supporting recovery."
      : sleepQualityScore >= 68
        ? "Neutral - sleep is adequate but still worth watching."
        : "Negative - sleep may be limiting readiness.";
  const sortedWearableMetrics = [...wearableMetrics].sort((a, b) => `${a.date} ${a.created_at ?? ""}`.localeCompare(`${b.date} ${b.created_at ?? ""}`));
  const latestWearable = sortedWearableMetrics.at(-1) ?? null;
  const wearableFlags = Array.isArray(wearableSignals?.flags) ? wearableSignals.flags : [];
  const readinessMessages = Array.isArray(trainingReadiness?.signals) ? trainingReadiness.signals : [];
  const wearableNumber = (value: unknown, suffix = "") => {
    const number = finiteNumberOrNull(value);
    return number === null ? "--" : `${Number.isInteger(number) ? number.toLocaleString() : number.toFixed(1)}${suffix}`;
  };
  const trendText = (trend?: string) => {
    if (!trend || trend === "insufficient_data") return "Need more data";
    return trend.replaceAll("_", " ");
  };
  return (
    <div className="space-y-4">
      <Card>
        <SectionHeader
          eyebrow="Bodyweight"
          title="Weight Overview"
          action={(
            <div className="flex flex-col items-end gap-2">
              <div className="flex flex-wrap justify-end gap-2">
                <button onClick={onSyncWeightNow} className="h-10 rounded-lg border border-white/10 px-3 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04]">
                  Sync Weight Now
                </button>
                <button onClick={onSyncWithingsHistory} className="h-10 rounded-lg border border-white/10 px-3 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04]">
                  Sync Withings History
                </button>
              </div>
              <p className="max-w-sm text-right text-xs leading-5 text-zinc-500">{withingsStatusText}</p>
            </div>
          )}
        />
        {weightHistory.length ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
              <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Latest</p>
              <p className="mt-2 text-2xl font-semibold text-white">{formatWeight(weightTrend.latest?.bodyweight)}</p>
              <p className="mt-1 text-xs text-zinc-500">{weightTrend.latest?.date}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
              <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Highest</p>
              <p className="mt-2 text-2xl font-semibold text-white">{formatWeight(highestWeight)}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
              <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Lowest</p>
              <p className="mt-2 text-2xl font-semibold text-white">{formatWeight(lowestWeight)}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
              <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Total change</p>
              <p className={cx("mt-2 text-2xl font-semibold", Number(totalWeightChange) > 0 ? "text-emerald-200" : Number(totalWeightChange) < 0 ? "text-sky-200" : "text-white")}>{formatWeightDelta(totalWeightChange)}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
              <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Body fat</p>
              <p className="mt-2 text-2xl font-semibold text-white">{latestBodyFat !== null ? `${latestBodyFat.toFixed(1)}%` : "--"}</p>
            </div>
          </div>
        ) : (
          <EmptyState title="No bodyweight data yet" description="Log bodyweight manually or import Withings measurements to start the trend." action="Use form below" onAction={() => undefined} />
        )}
      </Card>

      <Card>
        <SectionHeader eyebrow="Withings" title="Body Composition Snapshot" />
        {withingsHistory.length ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {withingsCards.map((card) => (
                <div key={card.label} className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
                  <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">{card.label}</p>
                  <p className="mt-2 text-2xl font-semibold text-white">{card.value}</p>
                  <p className="mt-1 text-xs leading-5 text-zinc-500">{card.detail}</p>
                </div>
              ))}
            </div>
            {!hasWithingsComposition ? (
              <div className="rounded-lg border border-amber-300/20 bg-amber-300/[0.07] p-4 text-sm text-amber-50">
                No Withings body composition data yet
              </div>
            ) : null}
          </div>
        ) : (
          <EmptyState title="No Withings body composition data yet" description="Connect and sync Withings to show body fat, lean mass, fat mass, and muscle mass." action="Open Settings" onAction={() => undefined} />
        )}
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.9fr)]">
        <Card>
          <SectionHeader
            eyebrow="Wearables"
            title="Wearables"
            action={latestWearable ? (
              <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs font-semibold text-zinc-300">
                Latest {latestWearable.date}
              </span>
            ) : null}
          />
          <div className="space-y-4">
            {latestWearable ? (
              <div className="grid gap-3 sm:grid-cols-4">
                <MetricCard title="Sleep" value={wearableNumber(latestWearable.sleep_hours, "h")} detail={trendText(wearableSignals?.sleep?.trend)} icon={HeartPulse} accent="border-sky-300/20 bg-sky-300/10 text-sky-200" />
                <MetricCard title="Resting HR" value={wearableNumber(latestWearable.resting_hr, " bpm")} detail={trendText(wearableSignals?.resting_hr?.trend)} icon={HeartPulse} accent="border-rose-300/20 bg-rose-300/10 text-rose-200" />
                <MetricCard title="HRV" value={wearableNumber(latestWearable.hrv)} detail={trendText(wearableSignals?.hrv?.trend)} icon={Gauge} accent="border-violet-300/20 bg-violet-300/10 text-violet-200" />
                <MetricCard title="Steps" value={wearableNumber(latestWearable.steps)} detail={trendText(String(recordOrEmpty(wearableSignals?.activity).trend || ""))} icon={BarChart3} accent="border-emerald-300/20 bg-emerald-300/10 text-emerald-200" />
              </div>
            ) : (
              <p className="rounded-lg border border-dashed border-white/10 bg-white/[0.025] p-4 text-sm text-zinc-400">
                No wearable data logged yet.
              </p>
            )}
            {wearableFlags.length ? (
              <p className="rounded-lg border border-white/10 bg-white/[0.035] p-3 text-sm leading-6 text-zinc-300">{wearableFlags[0]}</p>
            ) : null}
            <form onSubmit={onWearableSubmit} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <TextInput label="Date" type="date" value={forms.wearable.date} onChange={(value) => setForms((state) => ({ ...state, wearable: { ...state.wearable, date: value } }))} />
              <SelectInput label="Source" value={forms.wearable.source} options={["manual", "fitbit", "google_health", "mock"]} onChange={(value) => setForms((state) => ({ ...state, wearable: { ...state.wearable, source: value } }))} />
              <TextInput label="Sleep hours" type="number" min={0} step="any" value={forms.wearable.sleep_hours} onChange={(value) => setForms((state) => ({ ...state, wearable: { ...state.wearable, sleep_hours: value === "" ? "" : Number(value) } }))} />
              <TextInput label="Sleep score" type="number" min={0} step="any" value={forms.wearable.sleep_score} onChange={(value) => setForms((state) => ({ ...state, wearable: { ...state.wearable, sleep_score: value === "" ? "" : Number(value) } }))} />
              <TextInput label="Resting HR" type="number" min={0} step="any" value={forms.wearable.resting_hr} onChange={(value) => setForms((state) => ({ ...state, wearable: { ...state.wearable, resting_hr: value === "" ? "" : Number(value) } }))} />
              <TextInput label="HRV" type="number" min={0} step="any" value={forms.wearable.hrv} onChange={(value) => setForms((state) => ({ ...state, wearable: { ...state.wearable, hrv: value === "" ? "" : Number(value) } }))} />
              <TextInput label="Steps" type="number" min={0} step="any" value={forms.wearable.steps} onChange={(value) => setForms((state) => ({ ...state, wearable: { ...state.wearable, steps: value === "" ? "" : Number(value) } }))} />
              <TextInput label="Active minutes" type="number" min={0} step="any" value={forms.wearable.active_minutes} onChange={(value) => setForms((state) => ({ ...state, wearable: { ...state.wearable, active_minutes: value === "" ? "" : Number(value) } }))} />
              <TextInput label="Calories burned" type="number" min={0} step="any" value={forms.wearable.calories_burned} onChange={(value) => setForms((state) => ({ ...state, wearable: { ...state.wearable, calories_burned: value === "" ? "" : Number(value) } }))} />
              <button className="accent-bg h-11 rounded-lg text-sm font-semibold sm:self-end xl:col-span-3">
                Save Wearable Metric
              </button>
            </form>
          </div>
        </Card>

        <Card>
          <SectionHeader eyebrow="Readiness" title="Training Readiness Signals" />
          {trainingReadiness?.status === "ok" ? (
            <div className="space-y-3">
              {[
                ["Run", trainingReadiness.run_recommendation?.label, trainingReadiness.run_recommendation?.reason],
                ["Lift", trainingReadiness.lift_recommendation?.label, trainingReadiness.lift_recommendation?.reason],
                ["Fueling", trainingReadiness.fueling_recommendation?.label, trainingReadiness.fueling_recommendation?.reason],
                ["Hydration/electrolyte risk", trainingReadiness.hydration_recommendation?.label, trainingReadiness.hydration_recommendation?.reason],
              ].map(([label, value, reason]) => (
                <div key={label} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                  <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">{label}</p>
                  <p className="mt-1 text-sm font-semibold text-white">{value || "Need more data"}</p>
                  <p className="mt-1 text-xs leading-5 text-zinc-500">{reason || "Need more wearable history."}</p>
                </div>
              ))}
              {readinessMessages.length ? <p className="text-xs leading-5 text-zinc-500">{readinessMessages[0]}</p> : null}
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-white/10 bg-white/[0.025] p-4 text-sm leading-6 text-zinc-400">
              {trainingReadiness?.message || "Need more wearable history."}
            </p>
          )}
        </Card>

        <Card>
          <SectionHeader eyebrow="Fueling" title="Fueling & Deload Signals" />
          {trainingReadiness?.status === "ok" ? (
            <div className="space-y-3">
              <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Fueling</p>
                <p className="mt-1 text-sm font-semibold text-white">{trainingReadiness.fueling_recommendation?.label || "Normal fueling"}</p>
                <p className="mt-1 text-xs leading-5 text-zinc-500">{trainingReadiness.fueling_recommendation?.reason || "No low-carb or post-workout protein flag from current data."}</p>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Deload</p>
                <p className="mt-1 text-sm font-semibold text-white">{trainingReadiness.lift_recommendation?.label || "Push normal"}</p>
                <p className="mt-1 text-xs leading-5 text-zinc-500">{trainingReadiness.lift_recommendation?.reason || "No major wearable readiness flags for lifting intensity."}</p>
              </div>
              {readinessMessages.length ? (
                <div className="rounded-lg border border-white/10 bg-black/10 p-3">
                  <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Signal</p>
                  <p className="mt-1 text-xs leading-5 text-zinc-400">{readinessMessages[0]}</p>
                </div>
              ) : null}
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-white/10 bg-white/[0.025] p-4 text-sm leading-6 text-zinc-400">
              {trainingReadiness?.message || "Need more wearable history before fueling and deload signals are available."}
            </p>
          )}
        </Card>
      </div>

      <Card>
        <SectionHeader eyebrow="Past 7 Days" title="Weight Trend" />
        {weightHistory.length ? (
          <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
            <div className="rounded-lg border border-white/10 bg-white/[0.035] p-5">
              <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Trend</p>
              <p className={cx("mt-3 text-3xl font-semibold capitalize", trendColor)}>{weightTrend.trendLabel}</p>
              <div className="mt-5 grid gap-3 sm:grid-cols-2">
                <div>
                  <p className="text-xs text-zinc-500">7-day average</p>
                  <p className="mt-1 text-lg font-semibold text-white">{formatWeight(weightTrend.sevenDayAverage)}</p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">Weigh-ins</p>
                  <p className="mt-1 text-lg font-semibold text-white">{weightTrend.recent.length} / 7</p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">Vs yesterday</p>
                  <p className="mt-1 text-lg font-semibold text-white">{formatWeightDelta(weightTrend.changeVsYesterday)}</p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">Vs 7 days ago</p>
                  <p className="mt-1 text-lg font-semibold text-white">{formatWeightDelta(weightTrend.changeVsSevenDaysAgo)}</p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">7-day span</p>
                  <p className="mt-1 text-lg font-semibold text-white">{formatWeightDelta(weightTrend.change)}</p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">Percent</p>
                  <p className="mt-1 text-lg font-semibold text-white">{formatPercentDelta(weightTrend.percentChange)}</p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">14-day average</p>
                  <p className="mt-1 text-lg font-semibold text-white">{formatWeight(weightTrend.fourteenDayAverage)}</p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">28-day average</p>
                  <p className="mt-1 text-lg font-semibold text-white">{formatWeight(weightTrend.twentyEightDayAverage)}</p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">Body fat change</p>
                  <p className="mt-1 text-lg font-semibold text-white">{formatPercentDelta(weightTrend.bodyFatChange)}</p>
                </div>
              </div>
              {weightTrend.dataQualityReason ? <p className="mt-4 text-sm text-amber-200">{weightTrend.dataQualityReason}</p> : null}
            </div>
            <ChartFrame className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <RechartsLineChart data={weightHistory.slice(-14)}>
                  <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: "#a1a1aa", fontSize: 12 }} tickFormatter={compactDate} />
                  <YAxis domain={["dataMin - 2", "dataMax + 2"]} tick={{ fill: "#a1a1aa", fontSize: 12 }} width={42} />
                  <Tooltip content={<WeightTooltip />} />
                  <Line type="monotone" dataKey="bodyweight" name="Weight" stroke="#a3e635" strokeWidth={3} dot={{ r: 3, fill: "#a3e635" }} activeDot={{ r: 5 }} />
                  <Line type="monotone" dataKey="movingAverage7" name="7-day average" stroke="#60a5fa" strokeWidth={2} dot={false} strokeDasharray="5 5" />
                </RechartsLineChart>
              </ResponsiveContainer>
            </ChartFrame>
          </div>
        ) : (
          <EmptyState title="No bodyweight data yet" description="Past-week trend appears after bodyweight entries are logged." action="Use form below" onAction={() => undefined} />
        )}
      </Card>

      <Card>
            <SectionHeader eyebrow="History" title="Body Composition Trends" />
        {weightHistory.length ? (
          <div className="space-y-4">
            <p className="text-xs text-zinc-500">Using lowest weigh-in per day to reduce night-weight noise.</p>
            <div className="flex flex-wrap gap-2">
              {bodyCompositionTabs.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setBodyCompositionTab(tab.id)}
                  className={cx(
                    "rounded-lg border px-3 py-2 text-sm font-semibold transition",
                    bodyCompositionTab === tab.id
                      ? "accent-active"
                      : "border-white/10 bg-white/[0.04] text-zinc-300 hover:bg-white/[0.07]",
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <BodyCompositionChart history={weightHistory} tab={bodyCompositionTab} />
          </div>
        ) : (
          <EmptyState title="No bodyweight data yet" description="The full historical graph updates automatically after manual logs or Withings imports." action="Use form below" onAction={() => undefined} />
        )}
      </Card>

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
            {adaptiveRecoveryStatus || adaptiveRecoveryImplication ? (
              <div className="rounded-lg border border-emerald-300/15 bg-emerald-300/[0.045] p-4">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="text-sm font-semibold text-emerald-100">Nutrition impact</p>
                    <p className="mt-2 text-sm leading-6 text-zinc-300">{adaptiveRecoveryImplication || "Adaptive data temporarily unavailable."}</p>
                  </div>
                  <span className="w-fit rounded-full border border-emerald-300/20 bg-emerald-300/10 px-3 py-1 text-xs font-semibold capitalize text-emerald-100">
                    {adaptiveRecoveryStatus || "insufficient data"}
                  </span>
                </div>
              </div>
            ) : null}
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

function previousDayISO(dateStr: string): string {
  const base = new Date(`${(dateStr || "").slice(0, 10)}T00:00:00`);
  if (Number.isNaN(base.getTime())) return "";
  base.setDate(base.getDate() - 1);
  return base.toISOString().slice(0, 10);
}

type MislogSuggestion = {
  date: string;
  previousDay: string;
  earlier: WorkoutGroup;
};

type WorkoutKind = "run" | "cardio" | "lift" | "lift_cardio" | "unknown";

const RUN_KEYWORDS = ["run", "running", "jog", "easy run", "tempo run", "interval run", "outdoor run", "treadmill run", "5k", "10k"];
const CARDIO_KEYWORDS = ["cardio", "bike", "cycling", "spin", "elliptical", "swim", "stairmaster", "stair master", "rowing machine", "rower", "treadmill walk"];
const LIFT_KEYWORDS = [
  "bench press", "squat", "deadlift", "overhead press", "shoulder press", "curl", "skullcrusher", "skull crusher",
  "triceps", "pushdown", "leg extension", "leg curl", "calf raise", "row", "rows", "pulldown", "lateral raise",
  "dumbbell", "barbell", "machine", "shrug", "press",
];

function textHasTerm(text: string, term: string): boolean {
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
  return new RegExp(`(^|[^a-z0-9])${escaped}([^a-z0-9]|$)`, "i").test(text);
}

function classifyWorkout(group: WorkoutGroup): WorkoutKind {
  const backendKind = String(group.classification || "").toLowerCase();
  if (["run", "cardio", "lift", "lift_cardio", "unknown"].includes(backendKind)) return backendKind as WorkoutKind;
  const titleText = group.workout_type || "";
  const exerciseText = [...(group.exercise_names || [])].join(" ").toLowerCase();
  const liftText = [exerciseText, ...(group.muscle_groups || [])].join(" ").toLowerCase();
  const source = (group.source || "").toLowerCase();
  const notes = (group.details || []).map((row) => row.notes || "").join(" ").toLowerCase();
  const hasRunMetadata = notes.includes("distance_miles=") || notes.includes("pace_min_per_mile=") || notes.includes("strava_activity_id=");
  const isLift = (Number(group.total_volume) || 0) > 0 || (Number(group.total_sets) || 0) > 0 || LIFT_KEYWORDS.some((keyword) => textHasTerm(liftText, keyword));
  const ignoreHevyTitleCardio = source.includes("hevy") && isLift && !hasRunMetadata;
  const isRun = source.includes("strava") || hasRunMetadata || RUN_KEYWORDS.some((keyword) => textHasTerm(exerciseText, keyword) || (!ignoreHevyTitleCardio && textHasTerm(titleText, keyword)));
  const isCardio = CARDIO_KEYWORDS.some((keyword) => textHasTerm(exerciseText, keyword) || (!ignoreHevyTitleCardio && textHasTerm(titleText, keyword)));
  if (isRun && isLift) return "lift_cardio";
  if (isRun) return "run";
  if (isCardio && isLift) return "lift_cardio";
  if (isCardio) return "cardio";
  if (isLift) return "lift";
  return "unknown";
}

function workoutKindLabel(group: WorkoutGroup): string {
  const kind = classifyWorkout(group);
  if (kind === "run") return "Run";
  if (kind === "cardio") return "Cardio";
  if (kind === "lift_cardio") return "Lift + cardio";
  if (kind === "lift") return "Lift";
  return "Unknown";
}

function workoutStartMillis(workout: WorkoutGroup): number {
  const candidates = (workout.details || []).flatMap((row) => {
    const notes = String(row.notes || "");
    const noteTimes = [...notes.matchAll(/(?:start_time|started_at)=([^|]+)/gi)]
      .map((match) => match[1]?.trim())
      .filter(Boolean) as string[];
    return [...noteTimes, (row as TrainingEntry & { updated_at?: string }).updated_at, workout.date].filter(Boolean).map(String);
  });
  for (const value of [...candidates, `${(workout.date || "").slice(0, 10)}T12:00:00`]) {
    const parsed = new Date(value).getTime();
    if (!Number.isNaN(parsed)) return parsed;
  }
  return 0;
}

function isLiftOnlyWorkout(workout: WorkoutGroup): boolean {
  return classifyWorkout(workout) === "lift";
}

function hasLiftComponent(workout: WorkoutGroup): boolean {
  const kind = classifyWorkout(workout);
  return kind === "lift" || kind === "lift_cardio";
}

function isHevyOrLocalWorkout(workout: WorkoutGroup): boolean {
  const source = String(workout.source || "").toLowerCase();
  return source.includes("hevy") || source.includes("manual") || source.includes("local") || (workout.details || []).some((row) => {
    const rowSource = String(row.source || "").toLowerCase();
    return rowSource === "hevy" || rowSource === "manual" || Boolean((row as TrainingEntry & { hevy_workout_id?: string }).hevy_workout_id);
  });
}

function estimatedOneRepMax(weight: number, reps: number): number {
  if (!weight || !reps) return 0;
  return weight * (1 + reps / 30);
}

function exerciseTopSets(workout: WorkoutGroup): Record<string, TrainingEntry> {
  const output: Record<string, TrainingEntry> = {};
  for (const row of workout.details || []) {
    const exercise = (row.exercise || "").trim();
    if (!exercise || Number(row.weight) <= 0 || Number(row.reps) <= 0) continue;
    const current = output[exercise];
    if (!current || estimatedOneRepMax(Number(row.weight), Number(row.reps)) > estimatedOneRepMax(Number(current.weight), Number(current.reps))) {
      output[exercise] = row;
    }
  }
  return output;
}

function splitToken(workout: WorkoutGroup): string {
  const text = `${workout.workout_type || ""} ${(workout.exercise_names || []).join(" ")}`.toLowerCase();
  for (const token of ["push", "pull", "legs", "leg", "upper", "lower", "chest"]) {
    if (textHasTerm(text, token)) return token === "leg" ? "legs" : token;
  }
  return "";
}

function similarLiftWorkouts(todayLift: WorkoutGroup, workouts: WorkoutGroup[]): WorkoutGroup[] {
  const todayDate = (todayLift.date || "").slice(0, 10);
  const todaySplit = splitToken(todayLift);
  const todayExercises = new Set((todayLift.exercise_names || []).map((name) => name.toLowerCase()));
  return workouts
    .filter((workout) => workout.workout_id !== todayLift.workout_id && workout.date < todayDate && classifyWorkout(workout) === "lift")
    .map((workout) => {
      const titleMatch = todaySplit && splitToken(workout) === todaySplit ? 3 : 0;
      const overlap = (workout.exercise_names || []).filter((name) => todayExercises.has(name.toLowerCase())).length;
      return { workout, score: titleMatch + overlap };
    })
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || b.workout.date.localeCompare(a.workout.date))
    .slice(0, 8)
    .map((item) => item.workout);
}

function todayLiftPerformance(todayLift: WorkoutGroup, workouts: WorkoutGroup[]) {
  const similar = similarLiftWorkouts(todayLift, workouts);
  if (!similar.length) {
    return {
      rating: "Average",
      explanation: "Average session: not enough similar recent lifts yet, so this becomes the comparison baseline.",
      suggestions: ["Keep loads steady until there are a few comparable sessions."],
    };
  }
  const avg = (values: number[]) => values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length);
  const avgVolume = avg(similar.map((workout) => Number(workout.total_volume) || 0));
  const avgSets = avg(similar.map((workout) => Number(workout.total_sets) || 0));
  const avgDuration = avg(similar.map((workout) => Number(workout.duration_minutes) || 0).filter(Boolean));
  const volumeDelta = avgVolume ? ((Number(todayLift.total_volume) - avgVolume) / avgVolume) * 100 : 0;
  const setsDelta = avgSets ? ((Number(todayLift.total_sets) - avgSets) / avgSets) * 100 : 0;
  const durationDelta = avgDuration && todayLift.duration_minutes ? ((Number(todayLift.duration_minutes) - avgDuration) / avgDuration) * 100 : 0;
  const todayTops = exerciseTopSets(todayLift);
  let prs = 0;
  let matchedTopSet = "";
  for (const [exercise, topSet] of Object.entries(todayTops)) {
    const bestPast = Math.max(
      0,
      ...similar.flatMap((workout) => Object.entries(exerciseTopSets(workout)).filter(([name]) => name.toLowerCase() === exercise.toLowerCase()).map(([, row]) => estimatedOneRepMax(Number(row.weight), Number(row.reps)))),
    );
    const todayOneRm = estimatedOneRepMax(Number(topSet.weight), Number(topSet.reps));
    if (bestPast > 0 && todayOneRm >= bestPast * 0.995) {
      prs += 1;
      if (!matchedTopSet) matchedTopSet = exercise;
    }
  }
  let score = 0;
  if (volumeDelta >= 20) score += 2;
  else if (volumeDelta >= 6) score += 1;
  else if (volumeDelta <= -25) score -= 2;
  else if (volumeDelta <= -12) score -= 1;
  if (setsDelta >= 10) score += 1;
  if (setsDelta <= -20) score -= 1;
  if (prs >= 2) score += 2;
  else if (prs === 1) score += 1;
  if (durationDelta > 35 && volumeDelta < 0) score -= 1;
  const rating = score >= 3 ? "Great" : score >= 1 ? "Solid" : score <= -2 ? "Needs review" : score <= -1 ? "Light" : "Average";
  const split = splitToken(todayLift);
  const comparisonName = split ? `${split[0].toUpperCase()}${split.slice(1)}` : "similar";
  const explanationParts = [
    `${rating} session: volume was ${Math.abs(Math.round(volumeDelta))}% ${volumeDelta >= 0 ? "above" : "below"} your recent ${comparisonName} average`,
    prs ? `${prs} lift${prs > 1 ? "s" : ""} matched or beat recent top-set levels${matchedTopSet ? `, led by ${matchedTopSet}` : ""}` : "",
  ].filter(Boolean);
  return {
    rating,
    explanation: `${explanationParts.join(" and ")}.`,
    suggestions: heavierSuggestions(todayLift, similar, volumeDelta),
  };
}

function heavierSuggestions(todayLift: WorkoutGroup, similar: WorkoutGroup[], volumeDelta: number): string[] {
  if (volumeDelta > 35) return ["Hold loads next time; today's volume jumped enough that recovery should prove itself first."];
  const suggestions: string[] = [];
  const todayTops = Object.entries(exerciseTopSets(todayLift)).slice(0, 5);
  for (const [exercise, topSet] of todayTops) {
    const pastRows = similar.flatMap((workout) => workout.details || []).filter((row) => (row.exercise || "").toLowerCase() === exercise.toLowerCase() && Number(row.weight) > 0 && Number(row.reps) > 0);
    const bestPast = Math.max(0, ...pastRows.map((row) => estimatedOneRepMax(Number(row.weight), Number(row.reps))));
    const todayOneRm = estimatedOneRepMax(Number(topSet.weight), Number(topSet.reps));
    const rpe = Number(topSet.rpe) || 0;
    const comfortable = !rpe || rpe <= 8.5;
    if (bestPast > 0 && todayOneRm < bestPast * 0.97) {
      suggestions.push(`${exercise}: hold weight; reps are not yet consistently improving.`);
    } else if (Number(topSet.reps) >= 8 && comfortable) {
      suggestions.push(`${exercise}: consider +5 lb next time if warmups feel good.`);
    } else if (bestPast > 0 && todayOneRm >= bestPast * 0.995 && comfortable) {
      suggestions.push(`${exercise}: add 5 lb or 1-2 reps next session.`);
    }
    if (suggestions.length >= 3) break;
  }
  return suggestions.length ? suggestions : ["No obvious load jump yet; keep the main lifts steady and chase cleaner reps."];
}

function TodaysLiftTile({ workouts }: Readonly<{ workouts: WorkoutGroup[] }>) {
  const today = todayString();
  const lifts = workouts.filter((workout) => classifyWorkout(workout) === "lift" || classifyWorkout(workout) === "lift_cardio");
  const todayLift = lifts.find((workout) => (workout.date || "").slice(0, 10) === today);
  const latestLift = lifts[0];
  const performance = todayLift ? todayLiftPerformance(todayLift, workouts) : null;
  return (
    <Card>
      <SectionHeader eyebrow="Training" title="Today’s Lift" />
      {todayLift ? (
        <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-emerald-300/30 bg-emerald-300/10 px-3 py-1 text-xs font-semibold text-emerald-200">{workoutKindLabel(todayLift)}</span>
              <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-zinc-300">{todayLift.source || "manual"}</span>
            </div>
            <p className="mt-3 text-2xl font-semibold text-white">{todayLift.workout_type || "Lift"}</p>
            <p className="mt-1 text-sm text-zinc-400">{todayLift.date} · {todayLift.duration_minutes ? `${Math.round(todayLift.duration_minutes)} min` : "No duration"}</p>
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ["Sets", todayLift.total_sets.toLocaleString(), "Logged today"],
                ["Volume", Math.round(todayLift.total_volume).toLocaleString(), "lb total"],
                ["Rating", performance?.rating ?? "Average", "Vs similar lifts"],
                ["Exercises", todayLift.exercise_names.length.toString(), "Main movements"],
              ].map(([title, value, detail]) => (
                <div key={title} className="rounded-lg border border-white/10 bg-zinc-950/45 p-3">
                  <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">{title}</p>
                  <p className="mt-2 text-xl font-semibold text-white">{value}</p>
                  <p className="mt-1 text-xs text-zinc-500">{detail}</p>
                </div>
              ))}
            </div>
            <p className="mt-4 text-sm leading-6 text-zinc-300">{performance?.explanation}</p>
            <p className="mt-3 text-sm text-zinc-400">{todayLift.exercise_names.slice(0, 8).join(", ") || "No exercises listed"}</p>
          </div>
          <div className="rounded-lg border border-white/10 bg-zinc-950/45 p-4">
            <p className="text-sm font-semibold text-white">Go heavier?</p>
            <ul className="mt-3 space-y-2 text-sm leading-6 text-zinc-300">
              {(performance?.suggestions || []).map((suggestion) => <li key={suggestion}>{suggestion}</li>)}
            </ul>
            {todayLift.classification_debug ? (
              <p className="mt-4 text-xs leading-5 text-zinc-500">{todayLift.classification_debug.reason}</p>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-white/10 bg-white/[0.035] p-5">
          <p className="text-xl font-semibold text-white">No lift logged today</p>
          <p className="mt-2 text-sm text-zinc-400">{latestLift ? `Latest lift: ${latestLift.date} · ${latestLift.workout_type || "Lift"}` : "Hevy-synced lifting sessions will appear here after import."}</p>
        </div>
      )}
    </Card>
  );
}

// Detect a likely date mis-log: a day with 2+ *lifting* sessions whose previous
// day has none. A run logged alongside a lift is a valid two-a-day and is not a
// candidate. A repeated identical lifting session is also not flagged.
function detectMisloggedWorkout(workouts: WorkoutGroup[]): MislogSuggestion | null {
  const byDate = new Map<string, WorkoutGroup[]>();
  for (const workout of workouts) {
    const key = (workout.date || "").slice(0, 10);
    if (!key) continue;
    const existing = byDate.get(key);
    if (existing) existing.push(workout);
    else byDate.set(key, [workout]);
  }
  for (const date of [...byDate.keys()].sort().reverse()) {
    const group = byDate.get(date) ?? [];
    if (group.length < 2) continue;
    const previousDay = previousDayISO(date);
    if (!previousDay) continue;
    const previousLifts = (byDate.get(previousDay) ?? []).filter(hasLiftComponent);
    if (previousLifts.length > 0) continue;
    // Only same-day lifting sessions are mis-log candidates — a run + lift is
    // legitimate two-a-day training, not an accidental duplicate.
    const lifts = group.filter((workout) => isLiftOnlyWorkout(workout) && isHevyOrLocalWorkout(workout)).sort((a, b) => workoutStartMillis(a) - workoutStartMillis(b));
    if (lifts.length < 2) continue;
    const earlier = lifts[0];
    const later = lifts[1];
    const sameType = (earlier.workout_type || "").trim().toLowerCase() === (later.workout_type || "").trim().toLowerCase();
    const sameMuscles = [...earlier.muscle_groups].sort().join("|") === [...later.muscle_groups].sort().join("|");
    if (sameType && sameMuscles) continue;
    return { date, previousDay, earlier };
  }
  return null;
}

function WorkoutHistory({
  workouts,
  onImportHevy,
  onMoveWorkout,
  defaultExpanded = false,
  metadata = "Synced from Hevy",
}: Readonly<{
  workouts: WorkoutGroup[];
  onImportHevy: () => void;
  onMoveWorkout?: (workoutId: string, newDate: string) => void | Promise<void>;
  defaultExpanded?: boolean;
  metadata?: string;
}>) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [dismissedDate, setDismissedDate] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [moveError, setMoveError] = useState<string | null>(null);
  const thisMonth = new Date().toISOString().slice(0, 7);
  const monthlyCount = workouts.filter((workout) => workout.date.startsWith(thisMonth)).length;
  const subtitle = [metadata, monthlyCount ? `${monthlyCount} workouts this month` : ""].filter(Boolean).join(" · ");
  const suggestion = useMemo(() => detectMisloggedWorkout(workouts), [workouts]);

  const handleMove = async (workoutId: string, newDate: string) => {
    if (!onMoveWorkout || !newDate || busy) return;
    setBusy(true);
    setMoveError(null);
    try {
      await onMoveWorkout(workoutId, newDate);
      setEditingId(null);
    } catch (error) {
      setMoveError(`Could not move workout: ${error instanceof Error ? error.message : "Unknown error"}`);
    } finally {
      setBusy(false);
    }
  };

  const content = !workouts.length ? (
    <EmptyState title="No workouts logged yet" description="Hevy-synced sessions will appear here by day." action="Import from Hevy" onAction={onImportHevy} />
  ) : (
    <div className="space-y-3">
      {onMoveWorkout && suggestion && dismissedDate !== suggestion.date ? (
        <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 p-4">
          <p className="text-sm font-semibold text-amber-100">Possible missed-day lift</p>
          <p className="mt-1 text-sm text-amber-100/80">
            Two lifting workouts were logged on {suggestion.date} and no lift was logged on {suggestion.previousDay}. Move the earlier
            lift{suggestion.earlier.workout_type ? ` (${suggestion.earlier.workout_type})` : ""} to {suggestion.previousDay}?
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => handleMove(suggestion.earlier.workout_id, suggestion.previousDay)}
              disabled={busy}
              className="rounded-lg border border-amber-300/40 bg-amber-300/15 px-3 py-2 text-sm font-semibold text-amber-50 transition hover:bg-amber-300/25 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy ? "Moving…" : `Move earlier workout to ${suggestion.previousDay}`}
            </button>
            <button
              type="button"
              onClick={() => { setMoveError(null); setDismissedDate(suggestion.date); }}
              disabled={busy}
              className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04] disabled:opacity-60"
            >
              Keep both on same day
            </button>
            <button
              type="button"
              onClick={() => { setMoveError(null); setDismissedDate(suggestion.date); setExpanded(true); }}
              disabled={busy}
              className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-300 transition hover:bg-white/[0.04] disabled:opacity-60"
            >
              Review manually
            </button>
          </div>
          {moveError ? (
            <p className="mt-3 rounded-lg border border-red-300/25 bg-red-300/10 p-3 text-sm text-red-100">{moveError}</p>
          ) : null}
        </div>
      ) : null}
      {workouts.map((workout) => (
        <details key={`${workout.date}-${workout.workout_id}`} className="rounded-xl border border-white/10 bg-white/[0.035] p-4">
          <summary className="cursor-pointer list-none">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-base font-semibold text-white">{workout.date}</p>
                <p className="mt-1 text-sm text-zinc-400">{workout.workout_type || "Workout"} - {workout.exercise_names.slice(0, 5).join(", ") || "No exercises"}</p>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs sm:flex sm:flex-wrap">
                {(() => {
                  const kind = classifyWorkout(workout);
                  const isRunLike = kind === "run" || kind === "cardio";
                  return (
                    <span className={cx(
                      "rounded-full border px-2 py-1 font-semibold",
                      isRunLike ? "border-sky-300/30 bg-sky-300/10 text-sky-200" : "accent-outline",
                    )}>
                      {workoutKindLabel(workout)}
                    </span>
                  );
                })()}
                <span className="rounded-full border border-white/10 px-2 py-1 text-zinc-300">{workout.total_sets} sets</span>
                <span className="rounded-full border border-white/10 px-2 py-1 text-zinc-300">{Math.round(workout.total_volume).toLocaleString()} volume</span>
                <span className="rounded-full border border-white/10 px-2 py-1 text-zinc-300">{workout.duration_minutes ? `${Math.round(workout.duration_minutes)} min` : "No duration"}</span>
                <span className="rounded-full border border-white/10 px-2 py-1 text-zinc-300">{workout.source || "manual"}</span>
              </div>
            </div>
          </summary>
          {workout.classification_debug ? (
            <div className="mt-4 rounded-lg border border-white/10 bg-zinc-950/45 p-3 text-xs leading-5 text-zinc-400">
              <span className="font-semibold text-zinc-300">Classification debug:</span> {workout.classification_debug.reason}
              {workout.classification_debug.matched_lift_terms?.length ? ` Lift: ${workout.classification_debug.matched_lift_terms.join(", ")}.` : ""}
              {workout.classification_debug.matched_cardio_terms?.length ? ` Cardio: ${workout.classification_debug.matched_cardio_terms.join(", ")}.` : ""}
            </div>
          ) : null}
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
          {onMoveWorkout ? (
            <div className="mt-3">
              {editingId === workout.workout_id ? (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-zinc-400">Move this workout to:</span>
                  <input
                    type="date"
                    value={editValue}
                    onChange={(event) => setEditValue(event.target.value)}
                    className="rounded-lg border border-white/10 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
                  />
                  <button
                    type="button"
                    onClick={() => handleMove(workout.workout_id, editValue)}
                    disabled={busy || !editValue || editValue === workout.date.slice(0, 10)}
                    className="accent-outline rounded-lg border px-3 py-1.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {busy ? "Saving…" : "Save date"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditingId(null)}
                    disabled={busy}
                    className="rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-zinc-300 transition hover:bg-white/[0.04] disabled:opacity-60"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => { setEditingId(workout.workout_id); setEditValue(workout.date.slice(0, 10)); }}
                  className="rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-zinc-300 transition hover:bg-white/[0.04]"
                >
                  Edit date
                </button>
              )}
            </div>
          ) : null}
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
  const exerciseOptions = Array.isArray(strength?.exercise_options) ? strength.exercise_options : [];
  const exerciseItems = Array.isArray(strength?.items) ? strength.items : [];
  const selectedExerciseValue = selectedExercise || (typeof strength?.selected_exercise === "string" ? strength.selected_exercise : "") || exerciseOptions[0] || "";
  const rawTrend = strength?.trend;
  const legacyTrend = rawTrend && !Array.isArray(rawTrend) ? rawTrend : null;
  const trendPoints = Array.isArray(rawTrend) ? rawTrend : Array.isArray(legacyTrend?.history) ? legacyTrend.history : [];
  const trendChartData = trendPoints
    .map((item) => {
      const date = String(item.date ?? item.week ?? "");
      if (!date) return null;
      return {
        date,
        estimated_1rm: finiteNumberOrNull(item.estimated_1rm ?? item.best_set_weight ?? item.top_weight ?? item.average_working_weight) ?? 0,
        total_volume: finiteNumberOrNull(item.total_volume ?? item.volume) ?? 0,
        total_reps: finiteNumberOrNull(item.total_reps ?? item.reps) ?? 0,
        top_weight: finiteNumberOrNull(item.best_set_weight ?? item.top_weight) ?? 0,
      };
    })
    .filter((item): item is { date: string; estimated_1rm: number; total_volume: number; total_reps: number; top_weight: number } => Boolean(item));
  const firstVolume = trendChartData[0]?.total_volume ?? null;
  const latestVolume = trendChartData[trendChartData.length - 1]?.total_volume ?? null;
  const volumeTrendPct = firstVolume !== null && firstVolume > 0 && latestVolume !== null && trendChartData.length > 1 ? ((latestVolume - firstVolume) / firstVolume) * 100 : null;
  const currentExerciseItem = exerciseItems.find((item) => typeof item.exercise === "string" && item.exercise === selectedExerciseValue) ?? exerciseItems[0] ?? null;
  const bestSet = legacyTrend?.best_set && typeof legacyTrend.best_set === "object" ? legacyTrend.best_set : null;
  const latestPoint = trendPoints[trendPoints.length - 1] ?? null;
  const trendLabel = legacyTrend?.label?.trim()
    || (volumeTrendPct === null
      ? "Insufficient data"
      : volumeTrendPct > 5
        ? "Improving"
        : volumeTrendPct < -5
          ? "Down"
          : "Stable");
  const trendSummary = legacyTrend?.summary?.trim()
    || (volumeTrendPct !== null
      ? `${formatSignedPercentValue(volumeTrendPct, 1)} volume over ${trendChartData.length} logged points.`
      : selectedExerciseValue
        ? "Log this exercise multiple times to build a trend."
        : "Select an exercise.");
  const bestSetValue = bestSet
    ? `${formatCompactNumber(bestSet.weight)} x ${formatCompactNumber(bestSet.reps)}`
    : finiteNumberOrNull(currentExerciseItem?.top_weight ?? latestPoint?.top_weight ?? latestPoint?.best_set_weight) !== null
      ? `${formatCompactNumber(currentExerciseItem?.top_weight ?? latestPoint?.top_weight ?? latestPoint?.best_set_weight)} lb top`
      : "No best set";
  const bestSetDetail = bestSet
    ? `${formatCompactNumber(bestSet.estimated_1rm)} est. 1RM`
    : currentExerciseItem
      ? `${formatCompactNumber(currentExerciseItem.sets)} sets · ${formatCompactNumber(currentExerciseItem.reps)} reps`
      : "Log weighted sets";
  const recentPrValue = typeof legacyTrend?.recent_pr === "boolean" ? (legacyTrend.recent_pr ? "Yes" : "No") : "Need data";
  const latestTrendDate = bestSet?.date ?? latestPoint?.date ?? latestPoint?.week ?? currentExerciseItem?.last_date ?? "Needs history";
  const muscleTrends = strength?.muscle_group_trends && typeof strength.muscle_group_trends === "object" ? strength.muscle_group_trends : null;
  const muscleSummary = Array.isArray(muscleTrends?.summary) ? muscleTrends.summary : [];
  const muscleHistory = Array.isArray(muscleTrends?.history) ? muscleTrends.history : [];
  const muscleOptions = Array.isArray(muscleTrends?.muscle_group_options) ? muscleTrends.muscle_group_options : [];
  const unmappedExercises = Array.isArray(muscleTrends?.unmapped_exercises) ? muscleTrends.unmapped_exercises : [];
  const selectedGroups = selectedMuscleGroup ? [selectedMuscleGroup] : muscleSummary.slice(0, 6).map((item) => item.muscle_group);
  const muscleChartData = muscleHistory
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
          <button type="button" onClick={() => setTrendView("exercise")} className={cx("rounded-md px-3 py-2 text-sm font-semibold transition", trendView === "exercise" ? "accent-active" : "text-zinc-300 hover:bg-white/[0.06]")}>
            Exercise View
          </button>
          <button type="button" onClick={() => setTrendView("muscle_group")} className={cx("rounded-md px-3 py-2 text-sm font-semibold transition", trendView === "muscle_group" ? "accent-active" : "text-zinc-300 hover:bg-white/[0.06]")}>
            Muscle Group View
          </button>
        </div>
      </div>
      <div className="space-y-4">
        {trendView === "exercise" ? (
          <ExerciseViewErrorBoundary resetKey={`${selectedExerciseValue}-${trendDateRange}-${exerciseOptions.length}-${trendChartData.length}`}>
            {exerciseOptions.length ? (
              <>
                <SelectInput label="Exercise" value={selectedExerciseValue} options={exerciseOptions} onChange={setSelectedExercise} />
                <div className="grid gap-3 md:grid-cols-3">
                  <MetricCard title="Trend" value={trendLabel} detail={trendSummary} icon={Gauge} accent="border-violet-400/20 bg-violet-400/10 text-violet-300" />
                  <MetricCard title="Best Set" value={bestSetValue} detail={bestSetDetail} icon={Dumbbell} accent="border-amber-400/20 bg-amber-400/10 text-amber-300" />
                  <MetricCard title="Recent PR" value={recentPrValue} detail={latestTrendDate} icon={Sparkles} accent="border-emerald-400/20 bg-emerald-400/10 text-emerald-300" />
                </div>
                {trendChartData.length ? (
                  <div className="grid gap-4 lg:grid-cols-2">
                    <ChartFrame className="h-64">
                      <ResponsiveContainer width="100%" height="100%">
                        <RechartsLineChart data={trendChartData}>
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
                        <BarChart data={trendChartData}>
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
              <EmptyState title="Exercise view unavailable" description="No exercise trend data available yet." action="Log training" onAction={() => undefined} />
            )}
          </ExerciseViewErrorBoundary>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 md:grid-cols-3">
              <SelectInput label="Date range" value={trendDateRange} options={["4w", "8w", "12w", "6m", "all"]} onChange={setTrendDateRange} />
              <SelectInput label="Muscle group" value={selectedMuscleGroup} options={["", ...muscleOptions]} onChange={setSelectedMuscleGroup} />
              <SelectInput label="Metric" value={muscleTrendMetric} options={["strength_index", "weekly_volume", "hard_sets", "total_reps", "best_estimated_1rm"]} onChange={(value) => setMuscleTrendMetric(value as typeof muscleTrendMetric)} />
            </div>
            {muscleSummary.length ? (
              <>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {muscleSummary.map((item) => {
                    const strengthChange = finiteNumberOrNull(item.strength_change_pct);
                    return (
                      <div key={item.muscle_group} className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="font-semibold text-white">{item.muscle_group}</p>
                            <p className={cx("mt-1 text-lg font-semibold", strengthChange === null || strengthChange >= 0 ? "text-emerald-200" : "text-red-200")}>
                              {formatSignedPercentValue(item.strength_change_pct)}
                            </p>
                          </div>
                          <span className="rounded-full border border-white/10 px-2 py-1 text-xs text-zinc-300">Index {formatCompactNumber(item.strength_index)}</span>
                        </div>
                        <p className="mt-3 text-sm text-zinc-400">Weekly volume {formatSignedPercentValue(item.volume_change_pct)} · {formatCompactNumber(item.hard_sets)} sets · {formatCompactNumber(item.total_reps)} reps</p>
                        <p className="mt-2 text-sm text-zinc-300">Best contributor: {item.recent_best_exercise || "No clear contributor"}</p>
                      </div>
                    );
                  })}
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
                {unmappedExercises.length ? (
                  <div className="rounded-lg border border-amber-300/20 bg-amber-300/10 p-3 text-sm text-amber-100">
                    Unmapped exercises: {unmappedExercises.join(", ")}
                  </div>
                ) : null}
              </>
            ) : (
              <EmptyState title="No muscle group trend yet" description="Muscle group trends need weighted Hevy or manual strength rows in the selected range." action="Change filters" onAction={() => setSelectedMuscleGroup("")} />
            )}
          </div>
        )}
      </div>
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
  trainingHistoryMeta,
  strength,
  selectedExercise,
  setSelectedExercise,
  trainingInsight,
  onImportStrava,
  onPreviewHevy,
  onConfirmHevy,
  onCancelHevy,
  onSyncHevy,
  onMoveWorkout,
  onAnalyzeTraining,
  onLoadMoreTraining,
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
  trainingHistoryMeta: { rawWindowDays: number; hasMoreRecent: boolean; limit: number; message?: string };
  strength: StrengthTrendResponse | null;
  selectedExercise: string;
  setSelectedExercise: (value: string) => void;
  trainingInsight: TrainingInsight | null;
  onImportStrava: () => void;
  onPreviewHevy: () => void;
  onConfirmHevy: () => void;
  onCancelHevy: () => void;
  onSyncHevy: () => void;
  onMoveWorkout: (workoutId: string, newDate: string) => void | Promise<void>;
  onAnalyzeTraining: () => void;
  onLoadMoreTraining: () => void;
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
  const hevyLastResult = hevySync?.last_result ?? {};
  const hevyRows = Number(hevySync?.hevy_rows ?? hevyLastResult.hevy_rows ?? 0) || 0;
  const hevyWorkouts = Number(hevySync?.hevy_workouts ?? hevyLastResult.hevy_workouts ?? 0) || 0;
  const hevyImportedRows = Number(hevyLastResult.imported_rows ?? 0) || 0;
  const hevyEvents = Number(hevyLastResult.events ?? 0) || 0;
  const hevyNewWorkouts = Number(hevyLastResult.new_workouts ?? 0) || 0;
  const hevyUpdatedWorkouts = Number(hevyLastResult.updated_workouts ?? 0) || 0;
  const hevyDeletedRows = Number(hevyLastResult.deleted_rows ?? 0) || 0;
  const hevyChecked = Boolean(hevyLastResult.checked_hevy || hevySync?.last_synced_at);
  const hevyLatestDate = String(hevySync?.latest_workout_date ?? hevyLastResult.latest_workout_date ?? "");
  const hevyStatusLabel = hevySync?.last_error
    ? "Sync error"
    : hevySync?.configured === false || hevySync?.status === "not_configured"
      ? "Not connected"
      : hevySync?.status === "connected" || hevySync?.last_synced_at
        ? "Connected"
        : "Not synced";
  const hevyDebugMessage = hevySync?.last_error
    ? `Sync failed: ${hevySync.last_error}`
    : hevySync?.configured === false || hevySync?.status === "not_configured"
      ? "Hevy API key missing"
      : hevyRows === 0
        ? "No Hevy rows found"
        : "";
  const emptyWorkoutDebugMessage = !workoutHistory.length
    ? hevyDebugMessage || (hevyRows > 0 ? "Hevy rows exist, but /api/training/history returned no grouped workouts." : "No Hevy rows found")
    : "";
  return (
    <div className="space-y-4">
      <TodaysLiftTile workouts={workoutHistory} />
      <div className="grid gap-4">
        <Card>
          <SectionHeader eyebrow="Imports" title="Hevy and Strava" />
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-dashed border-white/15 bg-white/[0.03] p-6">
              <p className="font-medium text-white">Import Hevy workouts</p>
              <p className="mt-2 text-sm text-zinc-400">No background sync runs on startup. Manual refresh checks Hevy incrementally, upserts changed workouts locally, and only uses a recent import fallback when needed.</p>
              <p className={cx("mt-3 text-xs", hevySync?.last_error ? "text-amber-200" : "text-zinc-500")}>
                {relativeSyncTime(hevySync?.last_synced_at ?? "")}
                {hevySync?.last_error ? ` - ${hevySync.last_error}` : ""}
              </p>
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                <div className="rounded-lg border border-white/10 bg-zinc-950/50 p-3">
                  <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Status</p>
                  <p className={cx("mt-1 text-sm font-semibold", hevySync?.last_error ? "text-amber-200" : hevyStatusLabel === "Connected" ? "text-emerald-200" : "text-zinc-200")}>{hevyStatusLabel}</p>
                </div>
                <div className="rounded-lg border border-white/10 bg-zinc-950/50 p-3">
                  <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Rows</p>
                  <p className="mt-1 text-sm font-semibold text-white">{hevyRows} rows · {hevyWorkouts} workouts</p>
                </div>
                <div className="rounded-lg border border-white/10 bg-zinc-950/50 p-3">
                  <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Latest</p>
                  <p className="mt-1 text-sm font-semibold text-white">{hevyLatestDate || "No workout yet"}</p>
                </div>
                <div className="rounded-lg border border-white/10 bg-zinc-950/50 p-3">
                  <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Last check</p>
                  <p className="mt-1 text-sm font-semibold text-white">{hevyChecked ? `${hevyEvents} events` : "Not checked"}</p>
                  <p className="mt-1 text-xs text-zinc-500">{hevyNewWorkouts} new · {hevyUpdatedWorkouts} updated · {hevyDeletedRows} deleted rows</p>
                </div>
              </div>
              {hevyImportedRows > 0 ? (
                <p className="mt-3 text-xs text-zinc-500">Recent fallback import added {hevyImportedRows.toLocaleString()} normalized rows.</p>
              ) : null}
              {hevyDebugMessage ? (
                <div className={cx("mt-3 rounded-lg border p-3 text-sm", hevySync?.last_error || hevySync?.configured === false ? "border-amber-300/25 bg-amber-300/10 text-amber-100" : "border-white/10 bg-white/[0.035] text-zinc-300")}>
                  {hevyDebugMessage}
                </div>
              ) : null}
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
              <p className="mt-2 text-sm text-zinc-400">After connecting Strava, sync recent runs into the training log. Matching Strava activity IDs are updated without creating duplicates.</p>
              <button onClick={onImportStrava} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-orange-300 px-3 py-2 text-sm font-semibold text-zinc-950">
                <RefreshCw className="h-4 w-4" />
                Sync Strava
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
      {emptyWorkoutDebugMessage ? (
        <div className="rounded-lg border border-amber-300/25 bg-amber-300/10 p-4 text-sm text-amber-100">
          {emptyWorkoutDebugMessage}
        </div>
      ) : null}
      <div className="flex flex-col gap-3 rounded-lg border border-white/10 bg-white/[0.035] p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-white">Showing recent raw workouts from last {trainingHistoryMeta.rawWindowDays} days</p>
          <p className="mt-1 text-xs text-zinc-500">
            {trainingHistoryMeta.message || "Older Hevy history is served from consolidated summaries instead of raw set rows."}
          </p>
        </div>
        <button
          type="button"
          onClick={onLoadMoreTraining}
          disabled={!trainingHistoryMeta.hasMoreRecent}
          className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-50"
        >
          Load more
        </button>
      </div>
      <WorkoutHistory workouts={workoutHistory} onImportHevy={onPreviewHevy} onMoveWorkout={onMoveWorkout} metadata={relativeSyncTime(hevySync?.last_synced_at ?? "")} />
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

type CsvExportRange = "all" | "7d" | "30d" | "90d" | "custom";

function localDateDaysAgo(daysAgo: number) {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60_000).toISOString().slice(0, 10);
}

function csvFilenameFromDisposition(header: string | null) {
  if (!header) return `performance-os-backup-${todayString()}.csv`;
  const filenameStarMatch = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (filenameStarMatch?.[1]) {
    return decodeURIComponent(filenameStarMatch[1].replaceAll("\"", ""));
  }
  const filenameMatch = header.match(/filename="?([^";]+)"?/i);
  return filenameMatch?.[1] ?? `performance-os-backup-${todayString()}.csv`;
}

type BackupDatasetPreview = { name: string; label: string; count: number };
type BackupDocumentPreview = { name: string; label: string };
type BackupPreview = {
  fileName: string;
  datasets: BackupDatasetPreview[];
  documents: BackupDocumentPreview[];
  dateRange: { earliest: string; latest: string } | null;
  unknownDatasets: string[];
};
type BackupImportMode = "skip" | "update";
type BackupDatasetResult = {
  incoming_rows?: number;
  current_rows_before?: number;
  saved_rows?: number;
  created_rows?: number;
  updated_rows?: number;
  skipped_rows?: number;
  duplicates_skipped?: number;
};
type BackupSummary = {
  datasets: Record<string, BackupDatasetResult>;
  documents_imported: number;
  documents_skipped: number;
  skip_documents: boolean;
  import_mode: BackupImportMode;
  dry_run: boolean;
};

const BACKUP_DATASET_LABELS: Record<string, string> = {
  nutrition_log: "Food logs",
  frequent_foods: "Frequent foods",
  food_shortcuts: "Food shortcuts",
  meal_templates: "Meal templates",
  body_metrics: "Body metrics (weight, body fat)",
  raw_hevy_workouts: "Raw Hevy workouts",
  raw_hevy_sets: "Raw Hevy sets",
  training_log: "Workouts (Hevy + manual + Strava runs)",
  recovery_log: "Recovery check-ins",
  sleep_entries: "Sleep entries",
  workout_markers: "Workout markers",
  wearable_metrics: "Wearable metrics",
  daily_nutrition_summary: "Daily nutrition summaries",
};

const BACKUP_DOCUMENT_LABELS: Record<string, string> = {
  user_settings: "Settings",
  user_goals: "Goals",
  nutrition_targets: "Macro targets",
  nutrition_recommendation_history: "Recommendation history",
  personal_records: "Personal records",
  hevy_sync_state: "Hevy sync state",
  training_cache_metadata: "Training cache metadata",
};

function buildBackupPreview(fileName: string, bundle: unknown): BackupPreview {
  if (!bundle || typeof bundle !== "object") {
    throw new Error("Backup must be a JSON object.");
  }
  const root = bundle as Record<string, unknown>;
  const dataframes = root.dataframes;
  if (!dataframes || typeof dataframes !== "object") {
    throw new Error("Backup is missing the dataframes section.");
  }
  const datasets: BackupDatasetPreview[] = [];
  const unknownDatasets: string[] = [];
  let earliest: string | null = null;
  let latest: string | null = null;

  for (const [name, value] of Object.entries(dataframes as Record<string, unknown>)) {
    if (!Array.isArray(value)) continue;
    const label = BACKUP_DATASET_LABELS[name];
    if (label) {
      datasets.push({ name, label, count: value.length });
    } else if (value.length > 0) {
      unknownDatasets.push(name);
    }
    for (const row of value) {
      if (!row || typeof row !== "object") continue;
      const dateValue = (row as Record<string, unknown>).date;
      if (typeof dateValue !== "string" || dateValue.length < 10) continue;
      const iso = dateValue.slice(0, 10);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) continue;
      if (!earliest || iso < earliest) earliest = iso;
      if (!latest || iso > latest) latest = iso;
    }
  }
  datasets.sort((a, b) => b.count - a.count);

  const documents: BackupDocumentPreview[] = [];
  const documentsRaw = root.documents;
  if (documentsRaw && typeof documentsRaw === "object") {
    for (const [name, value] of Object.entries(documentsRaw as Record<string, unknown>)) {
      if (!value || typeof value !== "object" || Array.isArray(value)) continue;
      if (Object.keys(value as Record<string, unknown>).length === 0) continue;
      const label = BACKUP_DOCUMENT_LABELS[name] ?? name;
      documents.push({ name, label });
    }
  }
  documents.sort((a, b) => a.label.localeCompare(b.label));

  return {
    fileName,
    datasets,
    documents,
    dateRange: earliest && latest ? { earliest, latest } : null,
    unknownDatasets,
  };
}

function HistoryPage({
  nutritionLogs,
  nutritionHistory,
  nutritionAdherence,
  optimization,
  adaptiveRecommendation,
  bodyMetrics,
  recoveryTrend,
  trainingVolume,
  trainingSummary,
  trainingSummaryStatus,
  muscleCoverage,
  onSyncHevy,
  onExportRawHevy,
  onExportNormalizedTraining,
  onRebuildTrainingSummaries,
  hevySyncing,
  trainingDataAction,
  workoutHistory,
  onMoveWorkout,
  onExcludeNutritionDay,
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
  onBackupImported,
}: Readonly<{
  nutritionLogs: NutritionEntry[];
  nutritionHistory: DailyNutritionSummary[];
  nutritionAdherence: NutritionAdherence | null;
  optimization: OptimizationData | null;
  adaptiveRecommendation: AdaptiveNutritionRecommendation | null;
  bodyMetrics: BodyMetricEntry[];
  recoveryTrend: DashboardData["recovery_trend"];
  trainingVolume: DashboardData["training_volume"];
  trainingSummary: TrainingSummaryResponse | null;
  trainingSummaryStatus: TrainingSummaryStatusResponse | null;
  muscleCoverage: MuscleCoverageResponse | null;
  onSyncHevy: () => void;
  onExportRawHevy: () => void;
  onExportNormalizedTraining: () => void;
  onRebuildTrainingSummaries: () => void;
  hevySyncing: boolean;
  trainingDataAction: "idle" | "exporting" | "rebuilding";
  workoutHistory: WorkoutGroup[];
  onMoveWorkout: (workoutId: string, newDate: string) => void | Promise<void>;
  onExcludeNutritionDay: (date: string) => Promise<void>;
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
  onBackupImported: () => Promise<void>;
}>) {
  const [exportRange, setExportRange] = useState<CsvExportRange>("all");
  const [exportStartDate, setExportStartDate] = useState(localDateDaysAgo(29));
  const [exportEndDate, setExportEndDate] = useState(todayString());
  const [exportLoading, setExportLoading] = useState(false);
  const [exportError, setExportError] = useState("");
  const [backupLoading, setBackupLoading] = useState(false);
  const [backupMessage, setBackupMessage] = useState("");
  const [backupError, setBackupError] = useState("");
  const [backupSkipDocuments, setBackupSkipDocuments] = useState(true);
  const [backupImportMode, setBackupImportMode] = useState<BackupImportMode>("skip");
  const [backupPreview, setBackupPreview] = useState<BackupPreview | null>(null);
  const [backupPreCommit, setBackupPreCommit] = useState<BackupSummary | null>(null);
  const [backupPreCommitLoading, setBackupPreCommitLoading] = useState(false);
  const [backupSummary, setBackupSummary] = useState<BackupSummary | null>(null);
  const [backupFile, setBackupFile] = useState<File | null>(null);
  const backupInputRef = useRef<HTMLInputElement | null>(null);
  const [excludingNutritionDate, setExcludingNutritionDate] = useState("");
  const [excludeNutritionError, setExcludeNutritionError] = useState("");
  const [dailyNutritionHistoryExpanded, setDailyNutritionHistoryExpanded] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(DAILY_NUTRITION_HISTORY_EXPANDED_KEY) === "true";
  });
  const nutritionTrend = useMemo(() => aggregateNutrition(nutritionLogs), [nutritionLogs]);
  const dailyNutritionTrend = useMemo(() => nutritionHistory.length ? nutritionHistory : nutritionTrend.map((entry) => ({
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
  })), [nutritionHistory, nutritionTrend]);
  const caloriesBodyTrend = useMemo(
    () => buildCaloriesBodyTrendData(dailyNutritionTrend, bodyMetrics).slice(-120),
    [bodyMetrics, dailyNutritionTrend],
  );
  const hasBodyweightTrend = caloriesBodyTrend.some((entry) => entry.bodyweight7DayAverage !== null || entry.bodyweight !== null);
  const hasBodyFatTrend = caloriesBodyTrend.some((entry) => entry.bodyFat7PointAverage !== null || entry.bodyFatPercent !== null);
  const dailyNutritionHistorySummary = useMemo(() => {
    const calorieValues = nutritionHistory
      .map((entry) => Number(entry.total_calories))
      .filter((value) => Number.isFinite(value));
    const averageCalories = calorieValues.length
      ? Math.round(calorieValues.reduce((total, value) => total + value, 0) / calorieValues.length)
      : null;
    const latestDate = nutritionHistory.reduce((latest, entry) => {
      const date = typeof entry.date === "string" ? entry.date : "";
      return date && (!latest || date > latest) ? date : latest;
    }, "");

    const summaryText = [
      `${nutritionHistory.length.toLocaleString()} logged ${nutritionHistory.length === 1 ? "day" : "days"}`,
      averageCalories !== null ? `${averageCalories.toLocaleString()} avg kcal` : "average calories unavailable",
      latestDate ? `latest ${latestDate}` : "no latest date",
    ].join(" · ");

    return {
      averageCalories,
      latestDate,
      loggedDays: nutritionHistory.length,
      summaryText,
    };
  }, [nutritionHistory]);
  const trainingLastResult = trainingSummaryStatus?.last_hevy_result ?? {};
  const trainingLastNewWorkouts = Number(trainingSummaryStatus?.last_hevy_new_workouts ?? trainingLastResult.new_workouts ?? 0) || 0;
  const trainingLastUpdatedWorkouts = Number(trainingSummaryStatus?.last_hevy_updated_workouts ?? trainingLastResult.updated_workouts ?? 0) || 0;
  const trainingLastDeletedRows = Number(trainingSummaryStatus?.last_hevy_deleted_rows ?? trainingLastResult.deleted_rows ?? 0) || 0;
  const trainingLastEvents = Number(trainingLastResult.events ?? 0) || 0;
  const trainingLastFailures = trainingSummaryStatus?.last_hevy_failures?.length
    ? trainingSummaryStatus.last_hevy_failures
    : typeof trainingSummaryStatus?.last_hevy_error === "string" && trainingSummaryStatus.last_hevy_error
      ? [trainingSummaryStatus.last_hevy_error]
      : [];
  const latestHevyWorkoutDate = trainingSummaryStatus?.latest_hevy_workout_date ?? "";
  const latestHevyWorkoutTitle = trainingSummaryStatus?.latest_hevy_workout_title ?? "";
  const historyAdaptiveSignals = recordOrEmpty(adaptiveRecommendation?.signals);
  const historyBodyComposition = recordOrEmpty(historyAdaptiveSignals.bodyComposition);
  const historyAdaptiveReasons = stringList(adaptiveRecommendation?.reasoning);
  const historyAdaptiveTrends = stringList(adaptiveRecommendation?.detectedTrends);
  const historyMissingWarnings = stringList(adaptiveRecommendation?.missingDataWarnings);
  const optimizationMacroAdherence = recordOrEmpty(optimization?.macro_adherence);
  const optimizationPlateau = recordOrEmpty(optimization?.plateau_detection);
  const optimizationBaseline = recordOrEmpty(optimization?.personal_baseline);
  const optimizationMacroComponents = recordOrEmpty(optimizationMacroAdherence.components);
  const optimizationPlateauDetails = arrayOrEmpty<OptimizationData["plateau_detection"]["details"][number]>(optimizationPlateau.details);
  const optimizationBaselineInsights = arrayOrEmpty<OptimizationData["personal_baseline"]["insights"][number]>(optimizationBaseline.insights);
  const optimizationMacroDaily = arrayOrEmpty<OptimizationData["macro_adherence"]["daily"][number]>(optimizationMacroAdherence.daily);
  const optimizationMacroCorrelations = arrayOrEmpty<OptimizationData["macro_adherence"]["correlations"][number]>(optimizationMacroAdherence.correlations);
  const muscleCoverageItems = Array.isArray(muscleCoverage?.items) ? muscleCoverage.items : [];

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(DAILY_NUTRITION_HISTORY_EXPANDED_KEY, dailyNutritionHistoryExpanded ? "true" : "false");
  }, [dailyNutritionHistoryExpanded]);

  const handleCsvExport = useCallback(async () => {
    setExportLoading(true);
    setExportError("");
    try {
      const params = new URLSearchParams();
      if (exportRange === "custom") {
        if (exportStartDate) params.set("startDate", exportStartDate);
        if (exportEndDate) params.set("endDate", exportEndDate);
      } else if (exportRange !== "all") {
        const days = Number(exportRange.replace("d", ""));
        params.set("startDate", localDateDaysAgo(days - 1));
        params.set("endDate", todayString());
      }

      const query = params.toString();
      const response = await fetch(apiUrl(`/api/export/daily-csv${query ? `?${query}` : ""}`), {
        cache: "no-store",
        credentials: "include",
      });

      if (!response.ok) {
        const text = await response.text();
        let message = `Export failed (${response.status}).`;
        try {
          const payload = JSON.parse(text);
          message = payload.detail || payload.message || message;
        } catch {
          message = text || message;
        }
        throw new Error(message);
      }

      const blob = await response.blob();
      const objectUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = csvFilenameFromDisposition(response.headers.get("Content-Disposition"));
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setExportError(error instanceof Error ? error.message : "CSV export failed.");
    } finally {
      setExportLoading(false);
    }
  }, [exportEndDate, exportRange, exportStartDate]);

  const handleExcludeNutritionDay = useCallback(async (date: string) => {
    const selectedDate = String(date || "").slice(0, 10);
    if (!selectedDate) return;
    const confirmed = window.confirm(`Exclude ${selectedDate} from nutrition analytics? Raw food logs will remain stored, but this day will not count toward trends, adherence, dashboard summaries, or recommendations.`);
    if (!confirmed) return;
    setExcludeNutritionError("");
    setExcludingNutritionDate(selectedDate);
    try {
      await onExcludeNutritionDay(selectedDate);
    } catch (error) {
      setExcludeNutritionError(error instanceof Error ? error.message : "Could not exclude nutrition day.");
    } finally {
      setExcludingNutritionDate("");
    }
  }, [onExcludeNutritionDay]);

  const handleFullBackupExport = useCallback(async () => {
    setBackupLoading(true);
    setBackupError("");
    setBackupMessage("");
    try {
      const response = await fetch(apiUrl("/api/export/full-backup"), {
        cache: "no-store",
        credentials: "include",
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Backup export failed (${response.status}).`);
      }
      const blob = await response.blob();
      const objectUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = csvFilenameFromDisposition(response.headers.get("Content-Disposition")).replace(".csv", ".json");
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(objectUrl);
      setBackupMessage("Full JSON backup downloaded.");
    } catch (error) {
      setBackupError(error instanceof Error ? error.message : "Backup export failed.");
    } finally {
      setBackupLoading(false);
    }
  }, []);

  const postBackupImport = useCallback(async (file: File, options: { skipDocuments: boolean; mode: BackupImportMode; dryRun: boolean }): Promise<BackupSummary> => {
    const formData = new FormData();
    formData.append("file", file);
    const params = new URLSearchParams({
      skip_documents: options.skipDocuments ? "true" : "false",
      import_mode: options.mode,
      dry_run: options.dryRun ? "true" : "false",
    });
    const response = await fetch(apiUrl(`/api/import/full-backup?${params.toString()}`), {
      method: "POST",
      body: formData,
      credentials: "include",
    });
    const text = await response.text();
    if (!response.ok) {
      let message = `Backup import failed (${response.status}).`;
      try {
        const payload = JSON.parse(text);
        message = payload.detail || payload.message || message;
      } catch {
        message = text || message;
      }
      throw new Error(message);
    }
    const payload = JSON.parse(text);
    return {
      datasets: (payload?.datasets ?? {}) as Record<string, BackupDatasetResult>,
      documents_imported: Number(payload?.documents_imported ?? 0),
      documents_skipped: Number(payload?.documents_skipped ?? 0),
      skip_documents: Boolean(payload?.skip_documents),
      import_mode: (payload?.import_mode === "update" ? "update" : "skip") as BackupImportMode,
      dry_run: Boolean(payload?.dry_run),
    };
  }, []);

  const runDryRun = useCallback(async (file: File, mode: BackupImportMode, skipDocuments: boolean) => {
    setBackupPreCommitLoading(true);
    try {
      const result = await postBackupImport(file, { skipDocuments, mode, dryRun: true });
      setBackupPreCommit(result);
    } catch (error) {
      setBackupError(error instanceof Error ? error.message : "Could not analyze backup against production.");
      setBackupPreCommit(null);
    } finally {
      setBackupPreCommitLoading(false);
    }
  }, [postBackupImport]);

  const handleBackupFileSelect = useCallback(async (file: File) => {
    setBackupError("");
    setBackupMessage("");
    setBackupSummary(null);
    setBackupPreview(null);
    setBackupPreCommit(null);
    setBackupFile(null);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const preview = buildBackupPreview(file.name, parsed);
      if (preview.datasets.length === 0 && preview.documents.length === 0) {
        throw new Error("Backup contains no recognizable Performance OS data.");
      }
      setBackupPreview(preview);
      setBackupFile(file);
      void runDryRun(file, backupImportMode, backupSkipDocuments);
    } catch (error) {
      setBackupError(error instanceof Error ? error.message : "Backup file is not valid JSON.");
    } finally {
      if (backupInputRef.current) {
        backupInputRef.current.value = "";
      }
    }
  }, [backupImportMode, backupSkipDocuments, runDryRun]);

  const handleBackupCancel = useCallback(() => {
    setBackupPreview(null);
    setBackupPreCommit(null);
    setBackupFile(null);
    setBackupError("");
  }, []);

  const handleBackupModeChange = useCallback((mode: BackupImportMode) => {
    setBackupImportMode(mode);
    if (backupFile) {
      void runDryRun(backupFile, mode, backupSkipDocuments);
    }
  }, [backupFile, backupSkipDocuments, runDryRun]);

  const handleBackupSkipDocumentsChange = useCallback((skip: boolean) => {
    setBackupSkipDocuments(skip);
    if (backupFile) {
      void runDryRun(backupFile, backupImportMode, skip);
    }
  }, [backupFile, backupImportMode, runDryRun]);

  const handleBackupConfirm = useCallback(async () => {
    if (!backupFile) return;
    setBackupLoading(true);
    setBackupError("");
    setBackupMessage("");
    setBackupSummary(null);
    try {
      const result = await postBackupImport(backupFile, {
        skipDocuments: backupSkipDocuments,
        mode: backupImportMode,
        dryRun: false,
      });
      setBackupSummary(result);
      setBackupMessage("Backup imported safely.");
      setBackupPreview(null);
      setBackupPreCommit(null);
      setBackupFile(null);
      await onBackupImported();
    } catch (error) {
      setBackupError(error instanceof Error ? error.message : "Backup import failed.");
    } finally {
      setBackupLoading(false);
      if (backupInputRef.current) {
        backupInputRef.current.value = "";
      }
    }
  }, [backupFile, backupSkipDocuments, backupImportMode, postBackupImport, onBackupImported]);

  return (
    <div className="space-y-4">
      <Card>
        <SectionHeader
          eyebrow="Backup"
          title="CSV export"
          action={
            <button
              type="button"
              onClick={handleCsvExport}
              disabled={exportLoading}
              className="accent-outline inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Download className="h-4 w-4" />
              {exportLoading ? "Exporting..." : "Export CSV"}
            </button>
          }
        />
        <div className="grid gap-3 md:grid-cols-[minmax(180px,220px)_repeat(2,minmax(150px,1fr))] md:items-end">
          <label className="space-y-2 text-sm text-zinc-300">
            <span className="block text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">Range</span>
            <select
              value={exportRange}
              onChange={(event) => setExportRange(event.target.value as CsvExportRange)}
              className="accent-focus w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-white outline-none transition"
            >
              <option value="all">All time</option>
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
              <option value="90d">Last 90 days</option>
              <option value="custom">Custom range</option>
            </select>
          </label>
          {exportRange === "custom" ? (
            <>
              <label className="space-y-2 text-sm text-zinc-300">
                <span className="block text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">Start</span>
                <input
                  type="date"
                  value={exportStartDate}
                  onChange={(event) => setExportStartDate(event.target.value)}
                  className="accent-focus w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-white outline-none transition"
                />
              </label>
              <label className="space-y-2 text-sm text-zinc-300">
                <span className="block text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">End</span>
                <input
                  type="date"
                  value={exportEndDate}
                  onChange={(event) => setExportEndDate(event.target.value)}
                  className="accent-focus w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-white outline-none transition"
                />
              </label>
            </>
          ) : null}
        </div>
        {exportError ? (
          <p className="mt-3 rounded-lg border border-red-400/20 bg-red-400/10 px-3 py-2 text-sm text-red-200">{exportError}</p>
        ) : null}
        <div className="mt-4 border-t border-white/10 pt-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-white">Full backup and restore</p>
              <p className="mt-1 text-sm text-zinc-400">JSON backup includes logs, templates, targets, settings, recommendations, and learning insights.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={handleFullBackupExport}
                disabled={backupLoading}
                className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Export Full Backup
              </button>
              <button
                type="button"
                onClick={() => backupInputRef.current?.click()}
                disabled={backupLoading}
                className="rounded-lg border border-emerald-300/25 bg-emerald-300/10 px-3 py-2 text-sm font-semibold text-emerald-100 transition hover:bg-emerald-300/15 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Import Backup
              </button>
              <input
                ref={backupInputRef}
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void handleBackupFileSelect(file);
                }}
              />
            </div>
          </div>
          {backupPreview ? (
            <div className="accent-outline mt-4 rounded-lg border p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-white">Review backup before importing</p>
                  <p className="mt-1 text-xs text-zinc-400">{backupPreview.fileName}</p>
                </div>
                {backupPreview.dateRange ? (
                  <p className="text-xs text-zinc-300">Date range: <span className="accent-text-strong">{backupPreview.dateRange.earliest} → {backupPreview.dateRange.latest}</span></p>
                ) : null}
              </div>
              <div className="mt-4 rounded border border-white/5 bg-zinc-950/40 p-3">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">Import mode</p>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  <label className={cx("flex cursor-pointer items-start gap-2 rounded border px-3 py-2 text-sm transition", backupImportMode === "skip" ? "accent-outline" : "border-white/10 text-zinc-300 hover:bg-white/[0.03]")}>
                    <input
                      type="radio"
                      name="backupImportMode"
                      checked={backupImportMode === "skip"}
                      onChange={() => handleBackupModeChange("skip")}
                      className="mt-1 h-4 w-4"
                    />
                    <span>
                      <span className="font-medium">Skip existing (recommended)</span>
                      <span className="block text-xs text-zinc-400">Current production rows win on a match. Only truly new rows are added.</span>
                    </span>
                  </label>
                  <label className={cx("flex cursor-pointer items-start gap-2 rounded border px-3 py-2 text-sm transition", backupImportMode === "update" ? "border-amber-300/40 bg-amber-300/[0.06] text-amber-100" : "border-white/10 text-zinc-300 hover:bg-white/[0.03]")}>
                    <input
                      type="radio"
                      name="backupImportMode"
                      checked={backupImportMode === "update"}
                      onChange={() => handleBackupModeChange("update")}
                      className="mt-1 h-4 w-4"
                    />
                    <span>
                      <span className="font-medium">Update matching</span>
                      <span className="block text-xs text-zinc-400">Backup rows overwrite production rows that match on dedupe keys. Use to restore from a known-good backup.</span>
                    </span>
                  </label>
                </div>
              </div>

              <div className="mt-4 rounded border border-white/5 bg-zinc-950/40 p-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">Against current production</p>
                  {backupPreCommitLoading ? <p className="text-xs text-zinc-400">Analyzing…</p> : null}
                </div>
                {backupPreview.datasets.length > 0 ? (
                  <ul className="mt-2 grid gap-1 text-sm text-zinc-200 sm:grid-cols-2">
                    {backupPreview.datasets.map((dataset) => {
                      const result = backupPreCommit?.datasets?.[dataset.name];
                      const created = Number(result?.created_rows ?? 0);
                      const updated = Number(result?.updated_rows ?? 0);
                      const skipped = Number(result?.skipped_rows ?? result?.duplicates_skipped ?? 0);
                      return (
                        <li key={dataset.name} className="rounded border border-white/5 bg-zinc-950/60 px-3 py-2">
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-zinc-100">{dataset.label}</span>
                            <span className="text-xs text-zinc-500">{dataset.count.toLocaleString()} in backup</span>
                          </div>
                          {result ? (
                            <p className="mt-1 text-xs text-zinc-400">
                              <span className="text-emerald-200">{created.toLocaleString()} new</span>
                              {backupImportMode === "update" ? <> · <span className="text-amber-200">{updated.toLocaleString()} update</span></> : null}
                              {backupImportMode === "skip" ? <> · <span className="text-zinc-400">{skipped.toLocaleString()} skipped</span></> : null}
                            </p>
                          ) : (
                            <p className="mt-1 text-xs text-zinc-500">—</p>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
              </div>

              {backupPreview.documents.length > 0 ? (
                <div className="mt-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">Documents in backup</p>
                  <p className="mt-1 text-sm text-zinc-300">{backupPreview.documents.map((document) => document.label).join(", ")}</p>
                </div>
              ) : null}
              {backupPreview.unknownDatasets.length > 0 ? (
                <p className="mt-3 text-xs text-amber-200/80">Ignored unknown datasets: {backupPreview.unknownDatasets.join(", ")}</p>
              ) : null}
              <label className="mt-4 flex items-start gap-2 text-sm text-zinc-200">
                <input
                  type="checkbox"
                  checked={backupSkipDocuments}
                  onChange={(event) => handleBackupSkipDocumentsChange(event.target.checked)}
                  className="accent-control mt-1 h-4 w-4 rounded border-white/20 bg-zinc-950"
                />
                <span>
                  <span className="font-medium">Skip importing settings &amp; documents</span>
                  <span className="block text-xs text-zinc-400">Recommended. Prevents overwriting current settings/goals/macro targets/personal records/hevy sync state with values from this backup.</span>
                </span>
              </label>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={handleBackupConfirm}
                  disabled={backupLoading || backupPreCommitLoading}
                  className="rounded-lg border border-emerald-300/25 bg-emerald-300/10 px-3 py-2 text-sm font-semibold text-emerald-100 transition hover:bg-emerald-300/15 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {backupLoading ? "Importing..." : "Confirm Import"}
                </button>
                <button
                  type="button"
                  onClick={handleBackupCancel}
                  disabled={backupLoading}
                  className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : null}
          {backupSummary ? (
            <div className="mt-4 rounded-lg border border-emerald-300/25 bg-emerald-300/[0.06] p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <p className="text-sm font-semibold text-white">Import complete</p>
                <button
                  type="button"
                  onClick={() => setBackupSummary(null)}
                  className="text-xs text-zinc-400 underline-offset-2 hover:text-zinc-200 hover:underline"
                >
                  Dismiss
                </button>
              </div>
              <p className="mt-1 text-xs text-zinc-400">Mode: <span className="accent-text-strong">{backupSummary.import_mode === "update" ? "Update matching" : "Skip existing"}</span></p>
              <ul className="mt-3 grid gap-1 text-sm text-zinc-200 sm:grid-cols-2">
                {Object.entries(backupSummary.datasets).map(([key, result]) => {
                  const label = BACKUP_DATASET_LABELS[key] ?? key;
                  const incoming = Number(result.incoming_rows ?? 0);
                  const created = Number(result.created_rows ?? 0);
                  const updated = Number(result.updated_rows ?? 0);
                  const skipped = Number(result.skipped_rows ?? result.duplicates_skipped ?? 0);
                  return (
                    <li key={key} className="rounded border border-white/5 bg-zinc-950/40 px-3 py-2">
                      <p className="text-zinc-100">{label}</p>
                      <p className="mt-0.5 text-xs text-zinc-400">
                        {incoming.toLocaleString()} in backup · <span className="text-emerald-200">{created.toLocaleString()} new</span>
                        {updated > 0 ? <> · <span className="text-amber-200">{updated.toLocaleString()} updated</span></> : null}
                        {skipped > 0 ? <> · <span className="text-zinc-400">{skipped.toLocaleString()} skipped</span></> : null}
                      </p>
                    </li>
                  );
                })}
              </ul>
              <p className="mt-3 text-xs text-zinc-400">
                Documents: {backupSummary.documents_imported} imported, {backupSummary.documents_skipped} skipped
                {backupSummary.skip_documents ? " (documents skipped by request)" : ""}.
              </p>
            </div>
          ) : null}
          {backupMessage && !backupSummary ? <p className="mt-3 rounded-lg border border-emerald-300/20 bg-emerald-300/10 px-3 py-2 text-sm text-emerald-100">{backupMessage}</p> : null}
          {backupError ? <p className="mt-3 rounded-lg border border-red-400/20 bg-red-400/10 px-3 py-2 text-sm text-red-200">{backupError}</p> : null}
        </div>
      </Card>
      <Card>
        <SectionHeader
          eyebrow="Training Data"
          title="Training Data Management"
          action={
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={onSyncHevy}
                disabled={hevySyncing || trainingDataAction !== "idle"}
                className="inline-flex items-center gap-2 rounded-lg border border-emerald-300/25 bg-emerald-300/10 px-3 py-2 text-sm font-semibold text-emerald-100 transition hover:bg-emerald-300/15 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <RefreshCw className={cx("h-4 w-4", hevySyncing && "animate-spin")} />
                {hevySyncing ? "Syncing..." : "Sync Hevy"}
              </button>
              <button
                type="button"
                onClick={onExportRawHevy}
                disabled={trainingDataAction !== "idle"}
                className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Download className="h-4 w-4" />
                {trainingDataAction === "exporting" ? "Exporting..." : "Export Raw Hevy Data"}
              </button>
              <button
                type="button"
                onClick={onExportNormalizedTraining}
                disabled={trainingDataAction !== "idle"}
                className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Download className="h-4 w-4" />
                Export Normalized Training
              </button>
              <button
                type="button"
                onClick={onRebuildTrainingSummaries}
                disabled={trainingDataAction !== "idle"}
                className="accent-outline inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
              >
                <RefreshCw className={cx("h-4 w-4", trainingDataAction === "rebuilding" && "animate-spin")} />
                {trainingDataAction === "rebuilding" ? "Rebuilding..." : "Rebuild Training Summaries"}
              </button>
            </div>
          }
        />
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
          <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
            <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Last Hevy check</p>
            <p className="mt-2 text-sm font-semibold text-white">{trainingSummaryStatus?.last_hevy_check || trainingSummaryStatus?.last_hevy_sync ? relativeSyncTime(trainingSummaryStatus.last_hevy_check || trainingSummaryStatus.last_hevy_sync || "") : "Never checked"}</p>
            <p className="mt-1 text-xs text-zinc-500">Manual/webhook/cron only</p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
            <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Imported Hevy</p>
            <p className="mt-2 text-2xl font-semibold text-white">{(trainingSummaryStatus?.raw_hevy_workouts ?? 0).toLocaleString()}</p>
            <p className="mt-1 text-xs text-zinc-500">{(trainingSummaryStatus?.raw_hevy_sets ?? 0).toLocaleString()} raw sets</p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
            <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Normalized cache</p>
            <p className="mt-2 text-2xl font-semibold text-white">{(trainingSummaryStatus?.normalized_workouts ?? 0).toLocaleString()}</p>
            <p className="mt-1 text-xs text-zinc-500">{(trainingSummaryStatus?.normalized_sets ?? trainingSummaryStatus?.total_raw_rows ?? 0).toLocaleString()} set rows</p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
            <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Recent raw window</p>
            <p className="mt-2 text-2xl font-semibold text-white">{(trainingSummaryStatus?.recent_raw_rows ?? 0).toLocaleString()}</p>
            <p className="mt-1 text-xs text-zinc-500">{trainingSummaryStatus?.raw_window_days ?? 180} days</p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
            <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Latest Hevy workout</p>
            <p className="mt-2 text-sm font-semibold text-white">{latestHevyWorkoutDate ? compactDate(latestHevyWorkoutDate.slice(0, 10)) : "No workout yet"}</p>
            <p className="mt-1 truncate text-xs text-zinc-500">{latestHevyWorkoutTitle || "Local normalized cache"}</p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
            <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">Last rebuild</p>
            <p className="mt-2 text-sm font-semibold text-white">{trainingSummaryStatus?.last_summary_rebuild_date ? compactDate(trainingSummaryStatus.last_summary_rebuild_date.slice(0, 10)) : "Not yet"}</p>
            <p className="mt-1 text-xs text-zinc-500">{trainingSummaryStatus?.weekly_summaries ?? 0} weekly · {trainingSummaryStatus?.exercise_prs ?? 0} PR rows</p>
          </div>
        </div>
        <div className={cx("mt-3 rounded-lg border p-3 text-sm", trainingLastFailures.length ? "border-amber-300/25 bg-amber-300/10 text-amber-100" : "border-white/10 bg-white/[0.025] text-zinc-300")}>
          <p className="font-semibold text-white">Last incremental sync</p>
          <p className="mt-1 text-xs text-zinc-400">
            {trainingLastEvents.toLocaleString()} Hevy events checked · {trainingLastNewWorkouts.toLocaleString()} new · {trainingLastUpdatedWorkouts.toLocaleString()} updated · {trainingLastDeletedRows.toLocaleString()} deleted rows.
          </p>
          {trainingLastFailures.length ? <p className="mt-2 text-xs">{trainingLastFailures.join(" ")}</p> : null}
        </div>
        <div className="mt-4 rounded-lg border border-white/10 bg-zinc-950/50 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-semibold text-white">Coaching data contract</p>
            <span className={cx("rounded-full border px-2 py-1 text-xs font-semibold capitalize", trainingSummaryStatus?.cache_health === "ready" ? "border-emerald-300/25 bg-emerald-300/10 text-emerald-100" : "border-amber-300/25 bg-amber-300/10 text-amber-100")}>
              Cache {trainingSummaryStatus?.cache_health ?? "unknown"}
            </span>
          </div>
          <p className="mt-2 text-xs text-zinc-500">
            Startup source: {trainingSummaryStatus?.architecture?.startup_source?.replaceAll("_", " ") ?? "local normalized training cache"}.
            Older rows: {(trainingSummaryStatus?.older_raw_rows ?? 0).toLocaleString()} retained for export/debugging.
            Sync mode: {trainingSummaryStatus?.architecture?.hevy_sync_mode?.replaceAll("_", " ") ?? "incremental events manual webhook or external cron"}.
          </p>
          <div className="mt-3 grid gap-2 text-sm text-zinc-400 lg:grid-cols-3">
            <p>{trainingSummaryStatus?.coaching_contract?.plateau_detection ?? "Plateau detection uses recent raw set-level rows."}</p>
            <p>{trainingSummaryStatus?.coaching_contract?.calorie_changes ?? "Calorie changes use recent weight, nutrition, training, recovery, sleep, and cardio load."}</p>
            <p>{trainingSummaryStatus?.coaching_contract?.long_term_context ?? "Long-term context uses weekly/monthly summaries and PR history."}</p>
          </div>
        </div>
      </Card>
      <Card>
        <SectionHeader
          eyebrow="Workouts"
          title="Weekly Muscle Coverage"
          action={<span className="text-xs text-zinc-500">Last 7 days vs target/baseline</span>}
        />
        {muscleCoverageItems.length ? (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2 text-xs">
              {[
                ["Purple", "Missed", "#7c3aed"],
                ["Red", "Not hit enough", "#ef4444"],
                ["Yellow", "Slightly lacking", "#facc15"],
                ["Green", "Good", "#22c55e"],
              ].map(([color, label, hex]) => (
                <span key={color} className="inline-flex items-center gap-2 rounded-full border border-white/10 px-2.5 py-1 text-zinc-300">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: hex }} />
                  {label}
                </span>
              ))}
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              {muscleCoverageItems.map((item) => {
                const pct = finiteNumberOrNull(item.coverage_pct) ?? 0;
                const color = item.color_hex || "#71717a";
                return (
                  <div key={item.muscle_group} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-white">{item.muscle_group}</p>
                      <span className="h-3 w-3 rounded-full" style={{ backgroundColor: color }} />
                    </div>
                    <div className="mt-3 h-2 rounded-full bg-zinc-900">
                      <div className="h-full rounded-full transition-[width,background-color] duration-300" style={{ width: `${Math.min(Math.max(pct, 0), 100)}%`, backgroundColor: color }} />
                    </div>
                    <p className="mt-2 text-xs text-zinc-400">
                      {formatWholeNumber(item.hard_sets)} hard sets / {formatWholeNumber(item.target_sets)} target
                    </p>
                    <p className="mt-1 text-xs text-zinc-500">
                      {formatWholeNumber(item.volume)} volume · {item.status || "Learning"}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <p className="rounded-lg border border-dashed border-white/10 bg-white/[0.025] p-4 text-sm text-zinc-400">
            {muscleCoverage?.message || "Weekly muscle coverage will appear once lifting history is available."}
          </p>
        )}
      </Card>
      {adaptiveRecommendation ? (
        <Card>
          <SectionHeader eyebrow="Adaptive Nutrition" title="Closed-loop analysis" />
          <div className="grid gap-3 lg:grid-cols-4">
            <div className="rounded-lg border border-emerald-300/15 bg-emerald-300/[0.055] p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-emerald-200/80">Recommendation</p>
              <p className="mt-2 text-2xl font-semibold text-white">{adaptiveRecommendation.caloriesTarget} kcal</p>
              <p className="mt-1 text-sm text-zinc-400">P {adaptiveRecommendation.proteinTarget}g · C {adaptiveRecommendation.carbsTarget}g · F {adaptiveRecommendation.fatTarget}g</p>
              <p className="mt-2 text-xs text-zinc-500">{adaptiveRecommendation.calorieAdjustment > 0 ? "+" : ""}{adaptiveRecommendation.calorieAdjustment} kcal vs active baseline</p>
            </div>
            <div className="accent-outline rounded-lg border p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.14em]">Day type</p>
              <p className="mt-2 text-lg font-semibold text-white">{adaptiveRecommendation.dayType ?? "Learning"}</p>
              <p className="mt-2 text-sm leading-6 text-zinc-400">{adaptiveRecommendation.dayTypeAdjustment?.reason ?? "Training day adjustment appears with logged workload."}</p>
            </div>
            <div className="rounded-lg border border-violet-300/15 bg-violet-300/[0.055] p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-violet-200/80">Confidence</p>
              <p className="mt-2 text-lg font-semibold capitalize text-white">{recommendationConfidenceLabel(adaptiveRecommendation.confidence, adaptiveRecommendation.confidenceLevel)}</p>
              <p className="mt-2 text-sm leading-6 text-zinc-400">Data quality {adaptiveRecommendation.dataQualityScore ?? 0}/100 · next review {adaptiveRecommendation.nextReviewDate ?? "pending"}</p>
            </div>
            <div className="rounded-lg border border-amber-300/15 bg-amber-300/[0.055] p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-amber-200/80">Composition</p>
              <p className="mt-2 text-lg font-semibold capitalize text-white">{stringOrFallback(historyBodyComposition.lean_gain_quality, "unknown")}</p>
              <p className="mt-2 text-sm leading-6 text-zinc-400">
                Lean trend {formatWholeNumber(historyBodyComposition.lean_mass_trend_14)} lb/wk · Fat trend {formatWholeNumber(historyBodyComposition.fat_mass_trend_14)} lb/wk
              </p>
            </div>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-3">
            <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
              <p className="text-sm font-semibold text-white">Why it changed</p>
              <ul className="mt-3 space-y-2 text-sm leading-6 text-zinc-400">
                {(historyAdaptiveReasons.length ? historyAdaptiveReasons : ["No target change is currently justified."]).slice(0, 6).map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
              <p className="text-sm font-semibold text-white">Personal trends</p>
              <ul className="mt-3 space-y-2 text-sm leading-6 text-zinc-400">
                {(historyAdaptiveTrends.length ? historyAdaptiveTrends : ["More overlapping history is needed before stronger personal trends are useful."]).slice(0, 6).map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
              <p className="text-sm font-semibold text-white">Data gaps</p>
              <ul className="mt-3 space-y-2 text-sm leading-6 text-zinc-400">
                {(historyMissingWarnings.length ? historyMissingWarnings : ["No major data gaps detected."]).slice(0, 6).map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
          </div>
        </Card>
      ) : null}
      {optimization ? (
        <Card>
          <SectionHeader eyebrow="Optimization" title="Trend intelligence" />
          <div className="grid gap-3 lg:grid-cols-3">
            <div className="accent-outline rounded-lg border p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.14em]">Macro adherence</p>
              <p className="mt-2 text-3xl font-semibold text-white">{formatWholeNumber(optimizationMacroAdherence.weekly_score)}</p>
              <p className="mt-2 text-sm leading-6 text-zinc-400">{stringOrFallback(optimizationMacroAdherence.summary, "Adaptive data temporarily unavailable.")}</p>
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                {Object.entries(optimizationMacroComponents).map(([key, value]) => (
                  <span key={key} className="rounded-lg border border-white/10 bg-black/10 px-2 py-1 capitalize text-zinc-300">{key}: {formatWholeNumber(value)}</span>
                ))}
              </div>
            </div>
            <div className="rounded-lg border border-amber-300/15 bg-amber-300/[0.06] p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-amber-200/80">Plateau detection</p>
              <p className="mt-2 text-sm leading-6 text-zinc-300">{stringOrFallback(optimizationPlateau.summary, "Adaptive data temporarily unavailable.")}</p>
              <div className="mt-3 space-y-2">
                {(optimizationPlateauDetails.length ? optimizationPlateauDetails : [{ name: "Clear", message: "No conservative plateau flags are active.", severity: "low", signal: "clear", duration_weeks: 0, type: "clear", muscle_group: "" }]).slice(0, 5).map((alert) => (
                  <div key={`${alert.type}-${alert.name}-${alert.signal}`} className="rounded-lg border border-white/10 bg-black/10 p-2">
                    <p className="text-sm font-semibold text-white">{alert.name}</p>
                    <p className="mt-1 text-xs leading-5 text-zinc-400">{alert.message}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-lg border border-violet-300/15 bg-violet-300/[0.06] p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-violet-200/80">Personal baseline</p>
              <p className="mt-2 text-sm leading-6 text-zinc-300">{stringOrFallback(optimizationBaseline.summary, "Adaptive data temporarily unavailable.")}</p>
              <div className="mt-3 space-y-2">
                {(optimizationBaselineInsights.length ? optimizationBaselineInsights : [{ title: "Learning", summary: "More overlapping history is needed before baseline ranges are useful.", confidence: "low", metric: "learning" }]).slice(0, 5).map((insight) => (
                  <div key={`${insight.metric}-${insight.title}`} className="rounded-lg border border-white/10 bg-black/10 p-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-semibold text-white">{insight.title}</p>
                      <span className="rounded-full border border-white/10 px-2 py-0.5 text-[11px] capitalize text-zinc-300">{insight.confidence}</span>
                    </div>
                    <p className="mt-1 text-xs leading-5 text-zinc-400">{insight.summary}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
          {optimizationMacroDaily.length ? (
            <ChartFrame className="mt-4 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <RechartsLineChart data={optimizationMacroDaily}>
                  <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                  <YAxis domain={[0, 100]} stroke="#71717a" tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                  <Line dataKey="score" name="Adherence score" stroke="var(--accent-primary)" strokeWidth={3} dot={false} />
                </RechartsLineChart>
              </ResponsiveContainer>
            </ChartFrame>
          ) : null}
          {optimizationMacroCorrelations.length ? (
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {optimizationMacroCorrelations.map((correlation) => (
                <div key={correlation.label} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                  <p className="text-sm font-semibold text-white">{correlation.label}</p>
                  <p className="mt-2 text-xs leading-5 text-zinc-400">{correlation.summary}</p>
                </div>
              ))}
            </div>
          ) : null}
        </Card>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionHeader eyebrow="Nutrition" title="Calories vs Body Trend" />
          <div className="space-y-4">
            {dailyNutritionTrend.length ? (
              <>
              <div className="grid gap-3 md:grid-cols-4">
                <MetricCard title="7-day Calories" value={nutritionAdherence?.average_calories ? `${Math.round(nutritionAdherence.average_calories)}` : "No data"} detail={nutritionAdherence?.average_calories_delta !== null && nutritionAdherence?.average_calories_delta !== undefined ? `${deltaText(nutritionAdherence.average_calories_delta, " kcal")} avg` : "Totals only"} icon={Apple} accent="accent-outline" />
                <MetricCard title="7-day Protein" value={nutritionAdherence?.average_protein ? `${Math.round(nutritionAdherence.average_protein)}g` : "No data"} detail={nutritionAdherence?.average_protein_delta !== null && nutritionAdherence?.average_protein_delta !== undefined ? `${deltaText(nutritionAdherence.average_protein_delta, "g")} avg` : "Totals only"} icon={ProteinMoleculeIcon} accent="border-teal-400/20 bg-teal-400/10 text-teal-300" />
                <MetricCard title="Over Target" value={`${nutritionAdherence?.days_over_target ?? 0}`} detail="Recent logged days" icon={Gauge} accent="border-amber-400/20 bg-amber-400/10 text-amber-300" />
                <MetricCard title="Adherence" value={nutritionAdherence?.consistency_score ? `${Math.round(nutritionAdherence.consistency_score)}%` : "No target"} detail="Calories/macros vs targets" icon={Sparkles} accent="border-violet-400/20 bg-violet-400/10 text-violet-300" />
              </div>
              {nutritionAdherence?.data_quality_note ? (
                <p className={cx("text-xs", (nutritionAdherence.missing_days ?? 0) > 0 ? "text-amber-300/90" : "text-zinc-500")}>
                  Nutrition confidence: {(nutritionAdherence.confidence ?? "low").replace(/^./, (c) => c.toUpperCase())} — {nutritionAdherence.data_quality_note}
                </p>
              ) : null}
              <ChartFrame className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <RechartsLineChart data={caloriesBodyTrend}>
                    <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                    <XAxis dataKey="date" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                    <YAxis yAxisId="calories" stroke="#71717a" tickLine={false} axisLine={false} width={48} />
                    <YAxis yAxisId="weight" orientation="right" stroke="#71717a" tickLine={false} axisLine={false} width={44} domain={["dataMin - 2", "dataMax + 2"]} />
                    {hasBodyFatTrend ? (
                      <YAxis yAxisId="bodyFat" orientation="right" hide domain={["dataMin - 1", "dataMax + 1"]} />
                    ) : null}
                    <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                    <Line yAxisId="calories" dataKey="calories" name="Daily calories" stroke="rgba(96,165,250,0.35)" strokeWidth={1.5} dot={false} connectNulls />
                    <Line yAxisId="calories" dataKey="calories7DayAverage" name="7-day avg calories" stroke="#60a5fa" strokeWidth={3} dot={false} connectNulls />
                    <Line yAxisId="calories" dataKey="targetCalories" name="Calorie target" stroke="var(--accent-primary)" strokeWidth={2} strokeDasharray="4 4" dot={false} connectNulls />
                    {hasBodyweightTrend ? (
                      <Line yAxisId="weight" dataKey="bodyweight7DayAverage" name="7-day avg bodyweight" stroke="#f59e0b" strokeWidth={3} dot={false} connectNulls />
                    ) : null}
                    {hasBodyFatTrend ? (
                      <Line yAxisId="bodyFat" dataKey="bodyFat7PointAverage" name="Body fat %" stroke="#f472b6" strokeWidth={2} dot={false} connectNulls />
                    ) : null}
                  </RechartsLineChart>
                </ResponsiveContainer>
              </ChartFrame>
              <div className="flex flex-wrap gap-2 text-xs text-zinc-500">
                <span className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1">Blue: calories</span>
                <span className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1">Orange: bodyweight</span>
                {hasBodyFatTrend ? (
                  <span className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1">Pink: body fat %</span>
                ) : (
                  <span className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1">Body fat % not logged yet.</span>
                )}
                {!hasBodyweightTrend ? (
                  <span className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1">Bodyweight needs logged measurements.</span>
                ) : null}
              </div>
              </>
            ) : (
              <p className="rounded-lg border border-dashed border-white/15 bg-white/[0.03] px-4 py-3 text-sm text-zinc-400">
                Nutrition charts will appear once food entries are saved.
              </p>
            )}
            <div className="overflow-hidden rounded-lg border border-white/10 bg-white/[0.035]">
              <button
                type="button"
                aria-expanded={dailyNutritionHistoryExpanded}
                aria-controls="daily-nutrition-history-panel"
                onClick={() => setDailyNutritionHistoryExpanded((expanded) => !expanded)}
                className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition hover:bg-white/[0.04]"
              >
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-white">Daily Nutrition History</span>
                  <span className="mt-1 block truncate text-xs text-zinc-500">{dailyNutritionHistorySummary.summaryText}</span>
                </span>
                <ChevronDown className={cx("h-4 w-4 shrink-0 text-zinc-400 transition-transform duration-200", dailyNutritionHistoryExpanded && "rotate-180")} />
              </button>
              {dailyNutritionHistoryExpanded ? (
                <div id="daily-nutrition-history-panel" className="border-t border-white/10 p-3">
                  {excludeNutritionError ? (
                    <p className="mb-3 rounded-lg border border-red-300/20 bg-red-300/10 px-3 py-2 text-sm text-red-100">{excludeNutritionError}</p>
                  ) : null}
                  {nutritionHistory.length ? (
                    <DailyNutritionHistoryTable rows={nutritionHistory.slice().reverse()} excludingDate={excludingNutritionDate} onExcludeDay={handleExcludeNutritionDay} />
                  ) : (
                    <div className="rounded-lg border border-dashed border-white/15 bg-black/10 p-4">
                      <p className="font-medium text-white">No nutrition history yet</p>
                      <p className="mt-2 text-sm text-zinc-400">Daily summaries will appear here once food logs are saved and summarized.</p>
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          </div>
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
        <Card>
          <SectionHeader eyebrow="Training" title="Historical performance summaries" />
          {trainingSummary?.items?.length ? (
            <div className="space-y-4">
              <p className="text-sm text-zinc-400">
                Long-term charts use consolidated {trainingSummary.window} summaries, so old Hevy set rows stay out of startup analytics.
              </p>
              <ChartFrame className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <RechartsLineChart data={trainingSummary.items}>
                    <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                    <XAxis dataKey="period_start" tickFormatter={compactDate} stroke="#71717a" tickLine={false} axisLine={false} />
                    <YAxis yAxisId="volume" stroke="#71717a" tickLine={false} axisLine={false} />
                    <YAxis yAxisId="workouts" orientation="right" stroke="#71717a" tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={{ background: "#09090b", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8 }} />
                    <Line yAxisId="volume" dataKey="total_volume" name="Volume" stroke="var(--accent-primary)" strokeWidth={3} dot={false} />
                    <Line yAxisId="workouts" dataKey="workout_count" name="Workouts" stroke="#60a5fa" strokeWidth={2} dot={false} />
                  </RechartsLineChart>
                </ResponsiveContainer>
              </ChartFrame>
              {trainingSummary.muscle_groups?.length ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  {trainingSummary.muscle_groups.slice(-24).slice(0, 8).map((item) => (
                    <div key={`${item.period_start}-${item.muscle_group}`} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-semibold text-white">{item.muscle_group}</p>
                        <p className="text-xs text-zinc-500">{item.period_label || item.period_start}</p>
                      </div>
                      <p className="mt-2 text-xs text-zinc-400">{Math.round(Number(item.total_volume) || 0).toLocaleString()} volume · {item.hard_sets || item.total_sets || 0} hard sets</p>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-white/15 bg-white/[0.03] p-6">
              <p className="font-medium text-white">No historical summaries yet</p>
              <p className="mt-2 text-sm text-zinc-400">{trainingSummary?.message || "Run training history consolidation after import to populate long-term graphs without loading old raw sets."}</p>
            </div>
          )}
        </Card>
      </div>
      <WorkoutHistory workouts={workoutHistory} onImportHevy={() => undefined} onMoveWorkout={onMoveWorkout} defaultExpanded metadata="Training history" />
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

type SpecialFishDirection = "right" | "left";
type SpecialFishInstance = {
  id: number;
  direction: SpecialFishDirection;
  topPercent: number;
};

const SPECIAL_FISH_INTERVAL_MS = 15_000;
// Lifetime must outlast the (slowed) 17s swim so she finishes crossing.
const SPECIAL_FISH_LIFETIME_MS = 18_000;
const SPECIAL_FISH_INITIAL_DELAY_MS = 2_500;
const SPECIAL_FISH_BUBBLE_MS = 2_000;

// Ambient yellow-fish school — an occasional group event, not constant.
const SCHOOL_FISH_COUNT = 8;
const YELLOW_SCHOOL_INTERVAL_MS = 11_000;     // how often a spawn is considered
const YELLOW_SCHOOL_SPAWN_CHANCE = 0.45;      // probability per check, keeps it irregular
const YELLOW_SCHOOL_LIFETIME_MS = 32_000;     // outlasts the slowest fish + entry stagger
const YELLOW_SCHOOL_INITIAL_DELAY_MS = 6_000;

type YellowSchoolInstance = {
  id: number;
  direction: SpecialFishDirection;
};

function YellowFishSchool({ instance }: Readonly<{ instance: YellowSchoolInstance }>) {
  const swimsLeft = instance.direction === "left";
  return (
    <>
      {Array.from({ length: SCHOOL_FISH_COUNT }).map((_, i) => {
        // Deterministic per-index variation — organic loose formation with no
        // per-render randomness (avoids rerender/animation jitter).
        const topPercent = 11 + ((i * 37) % 70) / 10;       // ~11-16% band, clear of girlfriend path
        const swimSpeed = 24 + ((i * 53) % 90) / 20;        // ~24-28s, slightly varied speeds
        const swimDelay = ((i * 29) % 65) / 22;             // staggered entry → spacing differences
        const fishWidth = 22 + (i % 3) * 1.8;               // subtle size differences, smaller than standard
        const fishOpacity = 0.64 + (i % 3) * 0.08;
        const bobSpeed = 3.5 + (i % 4) * 0.45;
        return (
          <span
            key={i}
            aria-hidden="true"
            className={cx("aquarium-fish school-fish school-fish-cross", swimsLeft && "swim-left")}
            style={{
              top: `${topPercent}%`,
              "--swim-speed": `${swimSpeed}s`,
              "--swim-delay": `${swimDelay}s`,
              "--bob-speed": `${bobSpeed}s`,
              "--fish-width": `${fishWidth}px`,
              "--fish-opacity": fishOpacity,
            } as React.CSSProperties}
          >
            <svg className="fish-svg" viewBox="0 0 42 20" focusable="false">
              <path className="tail" d="M6 10L1 4C0 3 1 1 3 2L11 7V13L3 18C1 19 0 17 1 16L6 10Z" />
              <ellipse className="body" cx="24" cy="10" rx="14" ry="6.5" />
              <path className="fin top-fin" d="M16 4C20 1 27 2 30 6C25 5 20 4 16 4Z" />
              <circle className="eye" cx="34" cy="8" r="1.2" />
            </svg>
          </span>
        );
      })}
    </>
  );
}

function SpecialGirlfriendFish({
  instance,
  showBubble,
  onClick,
}: Readonly<{
  instance: SpecialFishInstance;
  showBubble: boolean;
  onClick: () => void;
}>) {
  const swimsLeft = instance.direction === "left";
  return (
    <button
      type="button"
      data-fish-type="special_girlfriend_fish"
      aria-label={showBubble ? "Special aquarium fish says fussing" : "Special aquarium fish"}
      onClick={onClick}
      className={cx("aquarium-fish special_girlfriend_fish special-fish-cross", swimsLeft && "swim-left")}
      style={{ top: `${instance.topPercent}%` }}
    >
      <span className={cx("special-fish-bubble", showBubble && "is-visible")} aria-hidden="true">
        *fussing*
      </span>
      <svg className="fish-svg special-fish-svg" viewBox="0 0 78 42" focusable="false" aria-hidden="true">
        <path className="tail" d="M10 21L2 10C0 7 3 4 6 6L20 14V28L6 36C3 38 0 35 2 32L10 21Z" />
        <path className="body" d="M18 21C23 9 38 4 53 8C66 11 74 21 68 30C62 39 39 40 24 30C20 27 18 24 18 21Z" />
        <path className="fin top-fin" d="M32 8C38 1 51 3 56 10C48 9 40 8 32 8Z" />
        <path className="fin bottom-fin" d="M33 33C41 40 55 36 59 27C52 32 43 34 33 33Z" />
        <path className="stripe" d="M31 10C36 18 36 27 30 34" />
        <circle className="blush" cx="57" cy="23" r="2.1" />
        <circle className="eye" cx="52" cy="17" r="1.6" />
        <circle className="eye" cx="62" cy="17" r="1.6" />
        <circle className="glasses-lens" cx="52" cy="17" r="4" />
        <circle className="glasses-lens" cx="62" cy="17" r="4" />
        <path className="glasses-bridge" d="M56 17h2" />
        <path className="heart" d="M61.9 9.9c-1.1-1.2-3.1-.4-3.1 1.2 0 2 3.1 3.6 3.1 3.6s3.2-1.6 3.2-3.6c0-1.6-2-2.4-3.2-1.2Z" />
      </svg>
    </button>
  );
}

function AquariumEasterEgg() {
  const [isOpen, setIsOpen] = useState(false);
  const [specialFish, setSpecialFish] = useState<SpecialFishInstance | null>(null);
  const [showSpecialBubble, setShowSpecialBubble] = useState(false);
  const specialBubbleTimeout = useRef<number | null>(null);
  const specialFishActiveRef = useRef(false);
  const specialFishIdRef = useRef(0);
  const despawnTimeout = useRef<number | null>(null);
  const [yellowSchool, setYellowSchool] = useState<YellowSchoolInstance | null>(null);
  const schoolActiveRef = useRef(false);
  const schoolIdRef = useRef(0);
  const schoolDespawnTimeout = useRef<number | null>(null);

  const clearSpecialBubbleTimeout = useCallback(() => {
    if (specialBubbleTimeout.current !== null) {
      window.clearTimeout(specialBubbleTimeout.current);
      specialBubbleTimeout.current = null;
    }
  }, []);

  const clearDespawnTimeout = useCallback(() => {
    if (despawnTimeout.current !== null) {
      window.clearTimeout(despawnTimeout.current);
      despawnTimeout.current = null;
    }
  }, []);

  const clearSchoolDespawnTimeout = useCallback(() => {
    if (schoolDespawnTimeout.current !== null) {
      window.clearTimeout(schoolDespawnTimeout.current);
      schoolDespawnTimeout.current = null;
    }
  }, []);

  useEffect(() => () => {
    clearSpecialBubbleTimeout();
    clearDespawnTimeout();
    clearSchoolDespawnTimeout();
  }, [clearSpecialBubbleTimeout, clearDespawnTimeout, clearSchoolDespawnTimeout]);

  // Periodically swim the special fish across the aquarium while it is open.
  // Only one fish exists at a time; each spawn auto-despawns after its swim.
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      return;
    }

    const trySpawn = () => {
      if (specialFishActiveRef.current) {
        return;
      }
      specialFishActiveRef.current = true;
      specialFishIdRef.current += 1;
      const id = specialFishIdRef.current;
      setSpecialFish({
        id,
        direction: Math.random() < 0.5 ? "right" : "left",
        topPercent: 22 + Math.random() * 48,
      });
      clearDespawnTimeout();
      despawnTimeout.current = window.setTimeout(() => {
        despawnTimeout.current = null;
        specialFishActiveRef.current = false;
        setSpecialFish((current) => (current?.id === id ? null : current));
        setShowSpecialBubble(false);
        clearSpecialBubbleTimeout();
      }, SPECIAL_FISH_LIFETIME_MS);
    };

    const firstSpawn = window.setTimeout(trySpawn, SPECIAL_FISH_INITIAL_DELAY_MS);
    const interval = window.setInterval(trySpawn, SPECIAL_FISH_INTERVAL_MS);

    return () => {
      window.clearTimeout(firstSpawn);
      window.clearInterval(interval);
      clearDespawnTimeout();
      specialFishActiveRef.current = false;
      setSpecialFish(null);
    };
  }, [isOpen, clearDespawnTimeout, clearSpecialBubbleTimeout]);

  // Occasionally send a loose school of yellow fish across the aquarium.
  // Each check has a chance to spawn, so the event feels random, not constant.
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      return;
    }

    const trySpawnSchool = () => {
      if (schoolActiveRef.current || Math.random() > YELLOW_SCHOOL_SPAWN_CHANCE) {
        return;
      }
      schoolActiveRef.current = true;
      schoolIdRef.current += 1;
      const id = schoolIdRef.current;
      setYellowSchool({ id, direction: Math.random() < 0.5 ? "right" : "left" });
      clearSchoolDespawnTimeout();
      schoolDespawnTimeout.current = window.setTimeout(() => {
        schoolDespawnTimeout.current = null;
        schoolActiveRef.current = false;
        setYellowSchool((current) => (current?.id === id ? null : current));
      }, YELLOW_SCHOOL_LIFETIME_MS);
    };

    const firstSchool = window.setTimeout(trySpawnSchool, YELLOW_SCHOOL_INITIAL_DELAY_MS);
    const schoolInterval = window.setInterval(trySpawnSchool, YELLOW_SCHOOL_INTERVAL_MS);

    return () => {
      window.clearTimeout(firstSchool);
      window.clearInterval(schoolInterval);
      clearSchoolDespawnTimeout();
      schoolActiveRef.current = false;
      setYellowSchool(null);
    };
  }, [isOpen, clearSchoolDespawnTimeout]);

  const toggleAquarium = () => {
    if (isOpen) {
      clearSpecialBubbleTimeout();
      clearDespawnTimeout();
      specialFishActiveRef.current = false;
      setSpecialFish(null);
      setShowSpecialBubble(false);
      setIsOpen(false);
      return;
    }
    setShowSpecialBubble(false);
    setIsOpen(true);
  };

  const showSpecialFishMessage = () => {
    clearSpecialBubbleTimeout();
    setShowSpecialBubble(true);
    specialBubbleTimeout.current = window.setTimeout(() => {
      setShowSpecialBubble(false);
      specialBubbleTimeout.current = null;
    }, SPECIAL_FISH_BUBBLE_MS);
  };

  return (
    <div className="flex flex-col items-start gap-3 pt-2">
      <button
        type="button"
        aria-expanded={isOpen}
        aria-controls="settings-aquarium"
        aria-label={isOpen ? "Close Aquarium easter egg" : "Open Aquarium easter egg"}
        onClick={toggleAquarium}
        className="accent-hover rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs font-semibold text-zinc-400 transition"
      >
        Aquarium
      </button>
      {isOpen ? (
        <div
          id="settings-aquarium"
          className="aquarium-tile accent-border relative h-64 w-full max-w-2xl overflow-hidden rounded-lg border bg-[#04111f] shadow-2xl shadow-[var(--accent-glow)] sm:h-72"
        >
          <div className="aquarium-water aquarium-water-back" aria-hidden="true" />
          <div className="aquarium-water aquarium-water-mid" aria-hidden="true" />
          <div className="aquarium-light-rays" aria-hidden="true" />
          <div className="aquarium-shimmer" aria-hidden="true" />
          <div className="aquarium-particles particles-back" aria-hidden="true" />
          <div className="aquarium-particles particles-front" aria-hidden="true" />
          <span className="aquarium-shark" aria-hidden="true">
            <svg viewBox="0 0 132 38" focusable="false">
              <path d="M7 20C28 7 69 3 112 18C119 13 126 11 130 13C125 19 125 23 130 29C123 30 118 26 112 22C75 35 32 32 7 20Z" />
              <path className="shark-fin" d="M60 11C66 1 75 1 80 12C72 10 66 10 60 11Z" />
              <circle cx="105" cy="17" r="1.3" />
            </svg>
          </span>
          <span className="aquarium-turtle" aria-hidden="true">
            <svg viewBox="0 0 84 46" focusable="false">
              <ellipse className="shell" cx="42" cy="24" rx="22" ry="13" />
              <circle className="head" cx="67" cy="22" r="6" />
              <path className="flipper front" d="M54 16C65 8 72 9 74 14C67 17 61 19 54 22Z" />
              <path className="flipper back" d="M28 17C18 9 10 10 8 16C16 18 22 20 30 23Z" />
              <path className="flipper lower-front" d="M53 29C63 36 69 35 72 30C65 29 59 27 53 24Z" />
              <path className="flipper lower-back" d="M29 30C19 38 11 36 9 30C16 29 23 27 30 24Z" />
              <path className="shell-line" d="M26 23C36 17 48 17 58 24M31 31C39 25 47 25 54 31" />
              <circle className="eye" cx="70" cy="20" r="1.1" />
            </svg>
          </span>
          <span className="aquarium-bubble bubble-one" aria-hidden="true" />
          <span className="aquarium-bubble bubble-two" aria-hidden="true" />
          <span className="aquarium-bubble bubble-three" aria-hidden="true" />
          <span className="aquarium-bubble bubble-four" aria-hidden="true" />
          <span className="aquarium-bubble bubble-five" aria-hidden="true" />
          <span className="aquarium-bubble bubble-six" aria-hidden="true" />
          <span className="aquarium-bubble bubble-seven" aria-hidden="true" />
          <span className="aquarium-bubble bubble-eight" aria-hidden="true" />
          <span className="aquarium-pineapple" aria-hidden="true">
            <span className="pineapple-crown" />
            <span className="pineapple-body" />
          </span>
          <span className="aquarium-rock rock-one" aria-hidden="true" />
          <span className="aquarium-rock rock-two" aria-hidden="true" />
          <span className="aquarium-rock rock-three" aria-hidden="true" />
          <span className="aquarium-seaweed seaweed-one" aria-hidden="true" />
          <span className="aquarium-seaweed seaweed-two" aria-hidden="true" />
          <span className="aquarium-seaweed seaweed-three" aria-hidden="true" />
          <span className="aquarium-seaweed seaweed-four" aria-hidden="true" />
          <span className="aquarium-seaweed seaweed-five" aria-hidden="true" />
          <span className="aquarium-coral" aria-hidden="true" />
          <span className="aquarium-coral coral-two" aria-hidden="true" />
          <span className="aquarium-fish fish-orange" aria-hidden="true">
            <svg className="fish-svg" viewBox="0 0 72 34" focusable="false">
              <path className="tail" d="M8 17L1 7C0 5 2 3 4 4L18 12V22L4 30C2 31 0 29 1 27L8 17Z" />
              <ellipse className="body" cx="36" cy="17" rx="24" ry="12" />
              <path className="fin top-fin" d="M26 8C31 1 42 3 46 9C39 8 33 8 26 8Z" />
              <path className="fin bottom-fin" d="M30 25C35 31 45 29 48 22C41 25 36 26 30 25Z" />
              <path className="stripe" d="M28 8C32 14 32 21 27 27" />
              <circle className="eye" cx="55" cy="14" r="2" />
            </svg>
          </span>
          <span className="aquarium-fish fish-tropical swim-left" aria-hidden="true">
            <svg className="fish-svg" viewBox="0 0 72 38" focusable="false">
              <path className="tail" d="M9 19L1 8C-1 5 2 2 5 4L20 13V25L5 34C2 36-1 33 1 30L9 19Z" />
              <path className="body" d="M18 19C22 8 35 3 48 8C60 12 67 19 62 27C57 35 36 38 23 28C20 26 18 23 18 19Z" />
              <path className="fin top-fin" d="M35 7C41 0 52 3 55 10C48 9 41 8 35 7Z" />
              <path className="fin bottom-fin" d="M34 30C42 36 55 33 58 25C51 29 43 31 34 30Z" />
              <path className="stripe stripe-one" d="M34 7C39 15 39 25 33 32" />
              <path className="stripe stripe-two" d="M45 8C50 16 50 25 45 32" />
              <circle className="eye" cx="56" cy="17" r="2.1" />
            </svg>
          </span>
          <span className="aquarium-fish fish-sleek" aria-hidden="true">
            <svg className="fish-svg" viewBox="0 0 86 28" focusable="false">
              <path className="tail" d="M10 14L1 5C-1 3 1 0 4 2L21 9V19L4 26C1 28-1 25 1 23L10 14Z" />
              <path className="body" d="M18 15C27 4 51 1 75 13C77 14 77 16 75 17C51 28 28 26 18 15Z" />
              <path className="fin top-fin" d="M39 8C46 2 56 4 62 9C54 8 47 8 39 8Z" />
              <path className="fin bottom-fin" d="M40 20C48 25 59 24 64 18C55 21 48 21 40 20Z" />
              <path className="stripe" d="M30 10C43 14 55 15 70 15" />
              <circle className="eye" cx="68" cy="13" r="1.8" />
            </svg>
          </span>
          <span className="aquarium-fish fish-round swim-left" aria-hidden="true">
            <svg className="fish-svg" viewBox="0 0 62 42" focusable="false">
              <path className="tail" d="M10 21L2 10C0 7 3 4 6 6L18 14V28L6 36C3 38 0 35 2 32L10 21Z" />
              <ellipse className="body" cx="35" cy="21" rx="20" ry="16" />
              <path className="fin top-fin" d="M28 8C33 1 44 2 49 10C42 9 35 8 28 8Z" />
              <path className="fin bottom-fin" d="M30 34C37 41 49 37 52 28C46 33 38 35 30 34Z" />
              <circle className="spot" cx="32" cy="18" r="3.2" />
              <circle className="spot spot-two" cx="43" cy="25" r="2.2" />
              <circle className="eye" cx="49" cy="17" r="2" />
            </svg>
          </span>
          <span className="aquarium-fish fish-school" aria-hidden="true">
            <span className="school-cluster">
              {[0, 1, 2].map((index) => (
                <svg key={index} className={`school-svg school-${index + 1}`} viewBox="0 0 42 20" focusable="false">
                  <path className="tail" d="M6 10L1 4C0 3 1 1 3 2L11 7V13L3 18C1 19 0 17 1 16L6 10Z" />
                  <ellipse className="body" cx="24" cy="10" rx="14" ry="6.5" />
                  <circle className="eye" cx="34" cy="8" r="1.2" />
                </svg>
              ))}
            </span>
          </span>
          {yellowSchool ? <YellowFishSchool key={yellowSchool.id} instance={yellowSchool} /> : null}
          {specialFish ? (
            <SpecialGirlfriendFish
              key={specialFish.id}
              instance={specialFish}
              showBubble={showSpecialBubble}
              onClick={showSpecialFishMessage}
            />
          ) : null}
          <div className="pointer-events-none absolute inset-0 rounded-lg ring-1 ring-inset ring-white/10" />
          <style>{`
            .aquarium-tile {
              isolation: isolate;
              background:
                linear-gradient(180deg, #08263a 0%, #073047 38%, #051827 68%, #020817 100%);
            }
            .aquarium-water {
              position: absolute;
              inset: 0;
              pointer-events: none;
            }
            .aquarium-water-back {
              z-index: 0;
              background:
                radial-gradient(circle at 18% 16%, rgba(125, 211, 252, 0.26), transparent 27%),
                radial-gradient(circle at 78% 12%, rgba(45, 212, 191, 0.16), transparent 30%),
                radial-gradient(circle at 54% 66%, rgba(14, 165, 233, 0.14), transparent 42%),
                linear-gradient(180deg, rgba(34, 211, 238, 0.22), rgba(14, 116, 144, 0.08) 48%, rgba(2, 6, 23, 0.86));
            }
            .aquarium-water-mid {
              z-index: 1;
              opacity: 0.6;
              background:
                repeating-linear-gradient(176deg, rgba(255,255,255,0.045) 0 1px, transparent 1px 26px),
                radial-gradient(ellipse at 50% 100%, rgba(14, 116, 144, 0.42), transparent 58%);
              animation: aquarium-current 12s ease-in-out infinite alternate;
            }
            .aquarium-light-rays {
              position: absolute;
              inset: -18% -22% auto -18%;
              z-index: 2;
              height: 88%;
              opacity: 0.28;
              pointer-events: none;
              background:
                linear-gradient(112deg, transparent 2%, rgba(224, 242, 254, 0.18) 10%, transparent 18%),
                linear-gradient(101deg, transparent 28%, rgba(186, 230, 253, 0.12) 40%, transparent 52%),
                linear-gradient(124deg, transparent 58%, rgba(125, 211, 252, 0.14) 67%, transparent 78%);
              filter: blur(0.8px);
              transform-origin: top center;
              animation: aquarium-rays 9s ease-in-out infinite alternate;
            }
            .aquarium-shimmer {
              position: absolute;
              inset: 0;
              z-index: 8;
              opacity: 0.2;
              pointer-events: none;
              background:
                linear-gradient(90deg, transparent, rgba(240, 249, 255, 0.08), transparent),
                repeating-linear-gradient(88deg, rgba(255,255,255,0.035) 0 1px, transparent 1px 18px);
              mix-blend-mode: screen;
              animation: aquarium-shimmer 7s linear infinite;
            }
            .aquarium-particles {
              position: absolute;
              inset: 0;
              z-index: 3;
              pointer-events: none;
              background-image:
                radial-gradient(circle, rgba(224, 242, 254, 0.22) 0 1px, transparent 1.5px),
                radial-gradient(circle, rgba(125, 211, 252, 0.16) 0 1px, transparent 1.5px);
              background-position: 8% 22%, 70% 40%;
              background-size: 74px 58px, 112px 86px;
              animation: aquarium-particles 18s linear infinite;
            }
            .particles-back {
              opacity: 0.22;
              filter: blur(1.4px);
            }
            .particles-front {
              opacity: 0.28;
              background-size: 92px 72px, 128px 96px;
              animation-duration: 13s;
              animation-direction: reverse;
            }
            .aquarium-tile::after {
              position: absolute;
              inset: auto 0 0;
              z-index: 5;
              height: 48px;
              content: "";
              background:
                radial-gradient(ellipse at 18% 78%, rgba(251, 191, 36, 0.24), transparent 28%),
                radial-gradient(ellipse at 75% 82%, rgba(217, 119, 6, 0.18), transparent 26%),
                linear-gradient(180deg, transparent, rgba(120, 53, 15, 0.28) 46%, rgba(68, 36, 12, 0.58));
              filter: blur(0.2px);
            }
            .aquarium-fish {
              position: absolute;
              left: -26%;
              display: block;
              border: 0;
              padding: 0;
              background: transparent;
              color: inherit;
              font: inherit;
              opacity: var(--fish-opacity, 0.92);
              filter: blur(var(--fish-blur, 0)) drop-shadow(0 0 10px rgba(125, 211, 252, var(--fish-glow, 0.12)));
              animation: aquarium-swim-right var(--swim-speed, 20s) linear infinite;
              animation-delay: var(--swim-delay, 0s);
              will-change: transform;
              z-index: var(--fish-depth, 2);
            }
            .aquarium-fish.swim-left {
              left: auto;
              right: -26%;
              animation-name: aquarium-swim-left;
              --fish-direction: -1;
            }
            .fish-svg {
              display: block;
              width: var(--fish-width, 54px);
              height: auto;
              transform-origin: center;
              animation: aquarium-fish-bob var(--bob-speed, 4.5s) ease-in-out infinite;
              animation-delay: var(--bob-delay, 0s);
            }
            .body { fill: var(--fish-body); }
            .tail,
            .fin { fill: var(--fish-fin); }
            .stripe {
              fill: none;
              stroke: var(--fish-detail);
              stroke-width: 3;
              stroke-linecap: round;
              opacity: 0.62;
            }
            .spot { fill: var(--fish-detail); opacity: 0.58; }
            .eye { fill: #020617; stroke: rgba(255,255,255,0.58); stroke-width: 0.7; }
            .fish-orange {
              top: 34%;
              --fish-width: 54px;
              --fish-body: #fb923c;
              --fish-fin: #facc15;
              --fish-detail: #fff7ed;
              --swim-speed: 18s;
              --swim-delay: -5s;
              --bob-speed: 3.8s;
              --bob-delay: -1.3s;
              --fish-depth: 4;
            }
            .fish-tropical {
              top: 58%;
              --fish-width: 50px;
              --fish-body: #38bdf8;
              --fish-fin: #fde047;
              --fish-detail: #0f172a;
              --swim-speed: 25s;
              --swim-delay: -13s;
              --bob-speed: 4.9s;
              --bob-delay: -2.4s;
              --fish-depth: 3;
            }
            .fish-sleek {
              top: 18%;
              --fish-width: 72px;
              --fish-body: #67e8f9;
              --fish-fin: #5eead4;
              --fish-detail: #e0f2fe;
              --swim-speed: 31s;
              --swim-delay: -20s;
              --bob-speed: 5.8s;
              --bob-delay: -3s;
              --fish-opacity: 0.55;
              --fish-blur: 0.7px;
              --fish-depth: 1;
            }
            .fish-round {
              top: 42%;
              --fish-width: 44px;
              --fish-body: #f472b6;
              --fish-fin: #c084fc;
              --fish-detail: #fdf2f8;
              --swim-speed: 21s;
              --swim-delay: -7s;
              --bob-speed: 4.1s;
              --bob-delay: -1.8s;
              --fish-depth: 5;
            }
            .fish-school {
              top: 70%;
              --swim-speed: 34s;
              --swim-delay: -24s;
              --bob-speed: 6.4s;
              --fish-opacity: 0.48;
              --fish-blur: 0.8px;
              --fish-depth: 1;
            }
            .school-cluster {
              position: relative;
              display: block;
              width: 78px;
              height: 32px;
              animation: aquarium-fish-bob var(--bob-speed, 6s) ease-in-out infinite;
            }
            .school-svg {
              position: absolute;
              width: 28px;
              --fish-body: #bae6fd;
              --fish-fin: #7dd3fc;
            }
            .school-svg .body { fill: var(--fish-body); }
            .school-svg .tail { fill: var(--fish-fin); }
            .school-svg .eye { fill: #020617; stroke: rgba(255,255,255,0.45); stroke-width: 0.5; }
            .school-1 { left: 0; top: 4px; }
            .school-2 { left: 24px; top: 0; opacity: 0.75; transform: scale(0.82); }
            .school-3 { left: 45px; top: 12px; opacity: 0.68; transform: scale(0.7); }
            /* Ambient yellow-fish school — each fish carries its own --swim-speed,
               --swim-delay, top and size inline for a loose, organic formation. */
            .school-fish {
              --fish-body: #fde047;
              --fish-fin: #facc15;
              --fish-depth: 2;
              filter: drop-shadow(0 0 7px rgba(250, 204, 21, 0.20));
            }
            .school-fish.school-fish-cross {
              animation-iteration-count: 1;
              animation-fill-mode: forwards;
            }
            .fish-tropical .stripe-one { stroke: rgba(15, 23, 42, 0.62); }
            .fish-tropical .stripe-two { stroke: rgba(15, 23, 42, 0.42); }
            .fish-sleek .stripe {
              stroke-width: 2;
              opacity: 0.45;
            }
            .special_girlfriend_fish {
              --fish-width: 66px;
              --fish-body: #f9a8d4;
              --fish-fin: #f472b6;
              --fish-detail: #fdf2f8;
              --fish-opacity: 0.96;
              --fish-depth: 6;
              --fish-glow: 0.2;
              cursor: pointer;
              overflow: visible;
              filter: drop-shadow(0 0 12px rgba(244, 114, 182, 0.20));
            }
            /* One graceful swim across the aquarium, then it leaves and is unmounted.
               Slowed ~42% from the original 12s so the glasses and heart read clearly. */
            .special_girlfriend_fish.special-fish-cross {
              --swim-speed: 17s;
              --swim-delay: 0s;
              --bob-speed: 6.2s;
              animation-iteration-count: 1;
              animation-fill-mode: forwards;
            }
            /* Ambient yellow-fish school — small, soft-glow, one-shot crossing. */
            .school-fish {
              --fish-body: #fde047;
              --fish-fin: #facc15;
              --fish-detail: #fef9c3;
              --fish-depth: 2;
              filter: drop-shadow(0 0 7px rgba(250, 204, 21, 0.18));
            }
            .school-fish .body { fill: var(--fish-body); }
            .school-fish .tail,
            .school-fish .fin { fill: var(--fish-fin); }
            .school-fish .eye { fill: #020617; stroke: rgba(255, 255, 255, 0.5); stroke-width: 0.5; }
            .school-fish.school-fish-cross {
              animation-iteration-count: 1;
              animation-fill-mode: forwards;
            }
            .special_girlfriend_fish:hover .special-fish-svg,
            .special_girlfriend_fish:focus-visible .special-fish-svg {
              filter: drop-shadow(0 0 8px rgba(244, 114, 182, 0.28));
            }
            .special_girlfriend_fish:focus-visible {
              outline: 2px solid rgba(125, 211, 252, 0.72);
              outline-offset: 4px;
              border-radius: 999px;
            }
            .special-fish-svg .stripe {
              stroke: rgba(255, 255, 255, 0.66);
              stroke-width: 2.3;
            }
            .special-fish-svg .blush {
              fill: rgba(251, 113, 133, 0.58);
            }
            .special-fish-svg .glasses-lens,
            .special-fish-svg .glasses-bridge {
              fill: none;
              stroke: rgba(15, 23, 42, 0.82);
              stroke-width: 1.35;
              stroke-linecap: round;
            }
            .special-fish-svg .heart {
              fill: #ef4444;
              opacity: 0.9;
            }
            .special-fish-bubble {
              position: absolute;
              left: 50%;
              top: -28px;
              z-index: 8;
              transform: translate3d(-50%, 6px, 0) scale(0.96);
              border: 1px solid rgba(186, 230, 253, 0.22);
              border-radius: 999px;
              background: rgba(8, 47, 73, 0.76);
              box-shadow: 0 8px 22px rgba(2, 6, 23, 0.28);
              color: rgba(240, 249, 255, 0.86);
              font-size: 11px;
              font-weight: 600;
              letter-spacing: 0;
              line-height: 1;
              opacity: 0;
              padding: 6px 9px;
              pointer-events: none;
              white-space: nowrap;
              transition: opacity 280ms ease, transform 280ms ease;
            }
            .special-fish-bubble::after {
              position: absolute;
              left: 50%;
              bottom: -4px;
              width: 7px;
              height: 7px;
              content: "";
              transform: translateX(-50%) rotate(45deg);
              border-right: 1px solid rgba(186, 230, 253, 0.18);
              border-bottom: 1px solid rgba(186, 230, 253, 0.18);
              background: rgba(8, 47, 73, 0.76);
            }
            .special-fish-bubble.is-visible {
              transform: translate3d(-50%, 0, 0) scale(1);
              opacity: 0.94;
            }
            .aquarium-bubble {
              position: absolute;
              bottom: -14px;
              width: 7px;
              height: 7px;
              border-radius: 999px;
              border: 1px solid rgba(186, 230, 253, 0.6);
              background: rgba(186, 230, 253, 0.08);
              animation: aquarium-bubble-rise 8s ease-in infinite;
              z-index: 7;
            }
            .bubble-one { left: 16%; animation-delay: -1s; animation-duration: 7s; }
            .bubble-two { left: 28%; width: 4px; height: 4px; animation-delay: -4s; animation-duration: 9s; }
            .bubble-three { left: 74%; animation-delay: -2s; animation-duration: 10s; }
            .bubble-four { left: 85%; width: 5px; height: 5px; animation-delay: -6s; animation-duration: 8s; }
            .bubble-five { left: 52%; width: 3px; height: 3px; animation-delay: -5s; animation-duration: 11s; opacity: 0.55; }
            .bubble-six { left: 63%; width: 9px; height: 9px; animation-delay: -8s; animation-duration: 12s; opacity: 0.42; }
            .bubble-seven { left: 39%; width: 5px; height: 5px; animation-delay: -10s; animation-duration: 13s; opacity: 0.5; }
            .bubble-eight { left: 92%; width: 3px; height: 3px; animation-delay: -3s; animation-duration: 10s; opacity: 0.44; }
            .aquarium-pineapple {
              position: absolute;
              left: 19%;
              bottom: 21px;
              z-index: 4;
              width: 28px;
              height: 42px;
              opacity: 0.42;
              filter: blur(0.35px) saturate(0.86);
              transform: rotate(-5deg) scale(0.92);
            }
            .pineapple-body {
              position: absolute;
              left: 5px;
              bottom: 0;
              width: 18px;
              height: 25px;
              border-radius: 45% 45% 36% 36%;
              background:
                repeating-linear-gradient(45deg, rgba(120, 53, 15, 0.32) 0 2px, transparent 2px 7px),
                repeating-linear-gradient(-45deg, rgba(120, 53, 15, 0.26) 0 2px, transparent 2px 7px),
                linear-gradient(180deg, #facc15, #d97706);
              box-shadow: inset 0 0 10px rgba(120, 53, 15, 0.35);
            }
            .pineapple-crown,
            .pineapple-crown::before,
            .pineapple-crown::after {
              position: absolute;
              left: 11px;
              bottom: 22px;
              width: 6px;
              height: 18px;
              content: "";
              border-radius: 999px 999px 0 0;
              background: linear-gradient(180deg, rgba(74, 222, 128, 0.9), rgba(21, 128, 61, 0.45));
              transform-origin: bottom center;
            }
            .pineapple-crown::before { left: -7px; bottom: 0; transform: rotate(-34deg); }
            .pineapple-crown::after { left: 7px; bottom: 0; transform: rotate(33deg); }
            .aquarium-rock {
              position: absolute;
              bottom: 17px;
              z-index: 6;
              border-radius: 999px 999px 12px 12px;
              background: linear-gradient(180deg, rgba(148, 163, 184, 0.45), rgba(51, 65, 85, 0.75));
              box-shadow: inset -6px -5px 12px rgba(2, 6, 23, 0.24);
            }
            .rock-one { left: 9%; width: 36px; height: 18px; }
            .rock-two { right: 18%; width: 52px; height: 23px; opacity: 0.72; }
            .rock-three { right: 7%; width: 28px; height: 14px; opacity: 0.55; filter: blur(0.4px); }
            .aquarium-seaweed {
              position: absolute;
              bottom: 22px;
              z-index: 7;
              width: 9px;
              height: 52px;
              border-radius: 999px 999px 0 0;
              background: linear-gradient(180deg, rgba(45, 212, 191, 0.88), rgba(20, 184, 166, 0.20));
              transform-origin: bottom center;
              animation: aquarium-sway 4s ease-in-out infinite alternate;
            }
            .aquarium-seaweed::before,
            .aquarium-seaweed::after {
              position: absolute;
              bottom: 8px;
              width: 7px;
              height: 35px;
              content: "";
              border-radius: 999px 999px 0 0;
              background: linear-gradient(180deg, rgba(74, 222, 128, 0.72), rgba(20, 184, 166, 0.14));
              transform-origin: bottom center;
            }
            .aquarium-seaweed::before { left: -8px; transform: rotate(-18deg); }
            .aquarium-seaweed::after { right: -8px; transform: rotate(18deg); }
            .seaweed-one { left: 7%; height: 64px; }
            .seaweed-two { right: 10%; height: 50px; animation-delay: -1.8s; }
            .seaweed-three { left: 31%; height: 42px; width: 7px; opacity: 0.54; filter: blur(0.5px); animation-delay: -2.6s; z-index: 4; }
            .seaweed-four { right: 27%; height: 72px; width: 10px; animation-delay: -3.4s; }
            .seaweed-five { left: 46%; height: 34px; width: 6px; opacity: 0.48; filter: blur(0.8px); animation-delay: -1.1s; z-index: 4; }
            .aquarium-coral {
              position: absolute;
              right: 20%;
              bottom: 23px;
              z-index: 7;
              width: 28px;
              height: 24px;
              border-radius: 999px 999px 8px 8px;
              background: linear-gradient(180deg, rgba(244, 114, 182, 0.88), rgba(244, 114, 182, 0.22));
              opacity: 0.72;
            }
            .aquarium-coral::before,
            .aquarium-coral::after,
            .coral-two::before,
            .coral-two::after {
              position: absolute;
              bottom: 9px;
              width: 9px;
              height: 21px;
              content: "";
              border-radius: 999px;
              background: inherit;
              transform-origin: bottom center;
            }
            .aquarium-coral::before { left: -6px; transform: rotate(-28deg); }
            .aquarium-coral::after { right: -5px; transform: rotate(30deg); }
            .coral-two {
              left: 58%;
              right: auto;
              width: 22px;
              height: 18px;
              opacity: 0.5;
              background: linear-gradient(180deg, rgba(251, 146, 60, 0.82), rgba(251, 146, 60, 0.18));
              filter: blur(0.3px);
              z-index: 5;
            }
            .aquarium-turtle {
              position: absolute;
              left: -22%;
              top: 52%;
              z-index: 3;
              width: 82px;
              opacity: 0;
              filter: blur(0.35px) drop-shadow(0 0 12px rgba(45, 212, 191, 0.12));
              animation: aquarium-turtle-cross 46s linear infinite;
              animation-delay: 10s;
              will-change: transform, opacity;
            }
            .aquarium-turtle svg { display: block; width: 100%; height: auto; }
            .aquarium-turtle .shell { fill: rgba(20, 184, 166, 0.72); }
            .aquarium-turtle .head,
            .aquarium-turtle .flipper { fill: rgba(94, 234, 212, 0.58); }
            .aquarium-turtle .shell-line {
              fill: none;
              stroke: rgba(15, 23, 42, 0.42);
              stroke-width: 1.4;
              stroke-linecap: round;
            }
            .aquarium-shark {
              position: absolute;
              right: -34%;
              top: 15%;
              z-index: 1;
              width: 132px;
              opacity: 0;
              filter: blur(1.1px);
              animation: aquarium-shark-pass 68s linear infinite;
              animation-delay: 22s;
              will-change: transform, opacity;
            }
            .aquarium-shark svg { display: block; width: 100%; height: auto; }
            .aquarium-shark path,
            .aquarium-shark circle {
              fill: rgba(8, 20, 32, 0.68);
            }
            .aquarium-shark .shark-fin {
              fill: rgba(10, 28, 44, 0.62);
            }
            @keyframes aquarium-swim-right {
              0% { transform: translate3d(-10%, 0, 0) scale(var(--depth-scale, 1)); }
              42% { transform: translate3d(58vw, 7px, 0) scale(var(--depth-scale, 1)); }
              100% { transform: translate3d(122vw, -5px, 0) scale(var(--depth-scale, 1)); }
            }
            @keyframes aquarium-swim-left {
              0% { transform: translate3d(10%, 0, 0) scale(var(--depth-scale, 1)); }
              52% { transform: translate3d(-55vw, -7px, 0) scale(var(--depth-scale, 1)); }
              100% { transform: translate3d(-122vw, 6px, 0) scale(var(--depth-scale, 1)); }
            }
            @keyframes aquarium-fish-bob {
              0%, 100% { transform: translateY(0) scaleX(var(--fish-direction, 1)) rotate(-1deg); }
              50% { transform: translateY(5px) scaleX(var(--fish-direction, 1)) rotate(1.4deg); }
            }
            @keyframes aquarium-bubble-rise {
              0% { transform: translateY(0) scale(0.85); opacity: 0; }
              18% { opacity: 0.58; }
              100% { transform: translateY(-260px) translateX(12px) scale(1.2); opacity: 0; }
            }
            @keyframes aquarium-sway {
              from { transform: rotate(-4deg); }
              to { transform: rotate(5deg); }
            }
            @keyframes aquarium-current {
              from { transform: translate3d(-10px, 0, 0); opacity: 0.44; }
              to { transform: translate3d(10px, 4px, 0); opacity: 0.68; }
            }
            @keyframes aquarium-rays {
              from { transform: rotate(-2deg) translateX(-10px); opacity: 0.18; }
              to { transform: rotate(2.5deg) translateX(10px); opacity: 0.34; }
            }
            @keyframes aquarium-shimmer {
              from { transform: translateX(-22%); }
              to { transform: translateX(22%); }
            }
            @keyframes aquarium-particles {
              from { transform: translate3d(0, 0, 0); }
              to { transform: translate3d(18px, -28px, 0); }
            }
            @keyframes aquarium-turtle-cross {
              0%, 13% { opacity: 0; transform: translate3d(0, 4px, 0) rotate(-1deg); }
              18% { opacity: 0.58; }
              54% { opacity: 0.62; transform: translate3d(62vw, -8px, 0) rotate(2deg); }
              76% { opacity: 0; transform: translate3d(104vw, 2px, 0) rotate(-1deg); }
              100% { opacity: 0; transform: translate3d(104vw, 2px, 0) rotate(-1deg); }
            }
            @keyframes aquarium-shark-pass {
              0%, 56% { opacity: 0; transform: translate3d(0, 0, 0) scaleX(-1); }
              60% { opacity: 0.18; }
              70% { opacity: 0.16; transform: translate3d(-52vw, 7px, 0) scaleX(-1); }
              82%, 100% { opacity: 0; transform: translate3d(-106vw, -3px, 0) scaleX(-1); }
            }
            @media (prefers-reduced-motion: reduce) {
              .aquarium-fish,
              .fish-svg,
              .school-cluster,
              .aquarium-bubble,
              .aquarium-seaweed,
              .aquarium-water-mid,
              .aquarium-light-rays,
              .aquarium-shimmer,
              .aquarium-particles,
              .aquarium-turtle,
              .aquarium-shark {
                animation: none;
              }
              .special-fish-bubble {
                transition: none;
              }
              .fish-orange { left: 14%; }
              .fish-tropical { right: 12%; }
              .fish-sleek { left: 42%; }
              .fish-round { right: 40%; }
              .fish-school { left: 26%; }
              .aquarium-bubble { opacity: 0.35; bottom: 58%; }
              .aquarium-turtle { left: 24%; opacity: 0.42; }
              .aquarium-shark { right: 8%; opacity: 0.12; }
            }
          `}</style>
        </div>
      ) : null}
    </div>
  );
}

function healthStatusClass(status: string) {
  if (status === "connected") return "border-emerald-300/20 bg-emerald-300/10 text-emerald-100";
  if (status === "green") return "border-emerald-300/20 bg-emerald-300/10 text-emerald-100";
  if (status === "syncing") return "accent-outline";
  if (status === "yellow") return "border-amber-300/20 bg-amber-300/10 text-amber-100";
  if (status === "error") return "border-red-400/25 bg-red-400/10 text-red-100";
  if (status === "red") return "border-red-400/25 bg-red-400/10 text-red-100";
  if (status === "gray") return "border-zinc-500/30 bg-zinc-500/10 text-zinc-300";
  return "border-amber-300/20 bg-amber-300/10 text-amber-100";
}

function diagnosticIcon(status: DiagnosticStatus) {
  if (status === "green") return Check;
  if (status === "red") return X;
  if (status === "gray") return CircleMinus;
  return AlertTriangle;
}

function DiagnosticStatusDashboard({ settings }: Readonly<{ settings: SettingsData | null }>) {
  if (!settings) return null;
  const primary: Array<[string, string, DiagnosticComponent | undefined]> = [
    ["backend", "Backend", settings.backend],
    ["database", "Supabase Postgres", settings.database],
    ["frontend", "Frontend API", settings.frontend],
    ["openai", "OpenAI", settings.openai],
    ["strava", "Strava", settings.strava],
    ["hevy", "Hevy", settings.hevy],
    ["withings", "Withings", settings.withings],
  ];
  const other = Object.entries(settings.other_integrations ?? {}).map(([key, value]) => [key, key.replaceAll("_", " / "), value] as const);
  const cards = [...primary, ...other].filter(([id, , component]) => id !== "backend" && Boolean(component));
  const checkedAt = settings.checked_at ? relativeSyncTime(settings.checked_at) : "";
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <SectionHeader eyebrow="Diagnostics" title="API and integration health" />
        <div className={cx("rounded-full border px-3 py-1 text-xs font-semibold capitalize", healthStatusClass(settings.overall_status === "ok" ? "green" : settings.overall_status === "error" ? "red" : "yellow"))}>
          {settings.overall_status ?? "unknown"}
        </div>
      </div>
      <div className="mt-1 flex flex-wrap gap-2 text-xs text-zinc-500">
        <span>Environment: <span className="text-zinc-300">{settings.environment ?? "unknown"}</span></span>
        {checkedAt ? <span>Checked {checkedAt}</span> : null}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {cards.map(([id, title, component]) => {
          if (!component) return null;
          const Icon = diagnosticIcon(component.status);
          const missing = component.missing_env_vars?.length ? component.missing_env_vars.join(", ") : "";
          return (
            <div key={id} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
              <div className="flex items-start gap-3">
                <span className={cx("mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border", healthStatusClass(component.status))}>
                  <Icon className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-semibold text-white">{title}</p>
                    <span className={cx("rounded-full border px-2 py-0.5 text-[10px] font-semibold capitalize", healthStatusClass(component.status))}>
                      {component.status}
                    </span>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-zinc-400">{component.message}</p>
                  {component.user_action_required && component.user_action_message ? (
                    <p className="mt-2 text-xs leading-5 text-amber-100">{component.user_action_message}</p>
                  ) : null}
                  <div className="mt-2 grid gap-1 text-[11px] leading-5 text-zinc-500">
                    {missing ? <p>Missing env: <span className="text-zinc-300">{missing}</span></p> : null}
                    {component.last_successful_sync ? <p>Last sync: <span className="text-zinc-300">{relativeSyncTime(component.last_successful_sync)}</span></p> : null}
                    {component.latest_record ? <p>Latest record: <span className="text-zinc-300">{component.latest_record}</span></p> : null}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {settings.required_user_actions?.length ? (
        <div className="mt-4 rounded-lg border border-amber-300/20 bg-amber-300/10 p-3">
          <p className="text-sm font-semibold text-amber-100">Required actions</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-5 text-amber-50">
            {settings.required_user_actions.map((action) => <li key={action}>{action}</li>)}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}

function IntegrationHealthGrid({
  cards,
  onSyncHevy,
  onImportStrava,
  onConnectStrava,
  onConnectWithings,
  onSyncWithings,
}: Readonly<{
  cards: SettingsHealthCard[];
  onSyncHevy: () => void;
  onImportStrava: () => void;
  onConnectStrava: (reconnect?: boolean) => void;
  onConnectWithings: () => void;
  onSyncWithings: () => void;
}>) {
  const actionFor = (card: SettingsHealthCard) => {
    if (card.action === "hevy_sync") return { label: "Sync", onClick: onSyncHevy };
    if (card.action === "strava_import") return { label: "Sync", onClick: onImportStrava };
    if (card.action === "strava_connect") return { label: "Connect Strava", onClick: () => onConnectStrava(false) };
    if (card.action === "strava_reconnect") return { label: "Reconnect Strava", onClick: () => onConnectStrava(true) };
    if (card.action === "withings_connect") return { label: "Connect", onClick: onConnectWithings };
    if (card.action === "withings_sync") return { label: "Sync", onClick: onSyncWithings };
    return null;
  };
  return (
    <Card>
      <SectionHeader eyebrow="Health" title="Integration and data health" />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => {
          const action = actionFor(card);
          return (
            <div key={card.id} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-white">{card.title}</p>
                  <p className="mt-1 text-xs leading-5 text-zinc-400">{card.detail}</p>
                </div>
                <span className={cx("shrink-0 rounded-full border px-2 py-1 text-[11px] font-semibold capitalize", healthStatusClass(card.status))}>
                  {card.status}
                </span>
              </div>
              <div className="mt-3 flex items-center justify-between gap-2">
                <p className="text-xs font-medium text-zinc-500">{card.last_synced_at ? relativeSyncTime(card.last_synced_at) : card.label}</p>
                {action ? (
                  <button type="button" onClick={action.onClick} className="rounded-md border border-white/10 px-2 py-1 text-xs font-semibold text-zinc-200 transition hover:bg-white/[0.04]">
                    {action.label}
                  </button>
                ) : null}
              </div>
              {card.id === "strava" && card.metadata ? (
                <div className="mt-3 grid gap-1 border-t border-white/10 pt-3 text-[11px] leading-5 text-zinc-500">
                  <p>Athlete: <span className="text-zinc-300">{card.metadata.athlete_id || "Not connected"}</span></p>
                  <p>Token: <span className="capitalize text-zinc-300">{card.metadata.token_status || "missing"}</span></p>
                  <p>Scopes: <span className="text-zinc-300">{card.metadata.scopes || "Not granted"}</span></p>
                  <p>Fetched: <span className="text-zinc-300">{card.metadata.last_fetched_count ?? 0}</span> · Imported: <span className="text-zinc-300">{card.metadata.last_imported_count ?? 0}</span> · Updated: <span className="text-zinc-300">{card.metadata.last_updated_count ?? 0}</span></p>
                  {card.metadata.latest_activity_date ? <p>Latest activity: <span className="text-zinc-300">{card.metadata.latest_activity_date}</span></p> : null}
                </div>
              ) : null}
              {card.id === "withings" && card.metadata ? (
                <div className="mt-3 grid gap-1 border-t border-white/10 pt-3 text-[11px] leading-5 text-zinc-500">
                  <p>User: <span className="text-zinc-300">{card.metadata.userid || "Not connected"}</span></p>
                  <p>Token: <span className="capitalize text-zinc-300">{card.metadata.token_status || "missing"}</span></p>
                  <p>Scopes: <span className="text-zinc-300">{card.metadata.scopes || "Not granted"}</span></p>
                  <p>Fetched: <span className="text-zinc-300">{card.metadata.last_fetched_count ?? 0}</span> · Imported: <span className="text-zinc-300">{card.metadata.last_imported_count ?? 0}</span> · Updated: <span className="text-zinc-300">{card.metadata.last_updated_count ?? 0}</span></p>
                  {card.metadata.latest_measurement_date ? <p>Latest measurement: <span className="text-zinc-300">{card.metadata.latest_measurement_date}</span></p> : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </Card>
  );
}


function apiConnectionStyle(status: string) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "connected") {
    return {
      card: "border-emerald-300/20 bg-emerald-300/[0.06]",
      badge: "border-emerald-300/25 bg-emerald-300/10 text-emerald-100",
      icon: Check,
    };
  }
  if (["ready_to_connect", "needs_reconnect", "rate_limited"].includes(normalized)) {
    return {
      card: "border-amber-300/20 bg-amber-300/[0.06]",
      badge: "border-amber-300/25 bg-amber-300/10 text-amber-100",
      icon: AlertTriangle,
    };
  }
  if (["missing_api_key", "missing_credentials", "not_checked", "not_configured"].includes(normalized)) {
    return {
      card: "border-zinc-500/25 bg-zinc-500/[0.06]",
      badge: "border-zinc-500/30 bg-zinc-500/10 text-zinc-300",
      icon: CircleMinus,
    };
  }
  return {
    card: "border-red-400/25 bg-red-400/[0.06]",
    badge: "border-red-400/25 bg-red-400/10 text-red-100",
    icon: X,
  };
}


function formatConnectionStatus(status: string) {
  return String(status || "not_checked").replaceAll("_", " ");
}


function ApiConnectionTestPanel({
  results,
  testing,
  onTest,
}: Readonly<{
  results: ApiConnectionTestResponse | null;
  testing: boolean;
  onTest: () => void;
}>) {
  const cards: Array<{ id: "hevy" | "openai" | "withings"; title: string; description: string }> = [
    { id: "hevy", title: "Hevy", description: "API key and workout endpoint" },
    { id: "openai", title: "OpenAI / ChatGPT", description: "API key and lightweight API reachability" },
    { id: "withings", title: "Withings", description: "App credentials, OAuth token, scope, and body metrics API" },
  ];
  return (
    <Card>
      <SectionHeader
        eyebrow="Connections"
        title="API Connection Tests"
        action={
          <button
            type="button"
            onClick={onTest}
            disabled={testing}
            className="accent-bg inline-flex h-10 items-center gap-2 rounded-lg px-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw className={cx("h-4 w-4", testing && "animate-spin")} />
            {testing ? "Testing..." : "Test API Connections"}
          </button>
        }
      />
      <div className="grid gap-3 lg:grid-cols-3">
        {cards.map((card) => {
          const result = results?.[card.id];
          const status = result?.status ?? "not_checked";
          const style = apiConnectionStyle(status);
          const Icon = style.icon;
          const layers = Object.entries(result?.layers ?? {});
          return (
            <div key={card.id} className={cx("rounded-lg border p-4", style.card)}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold text-white">{card.title}</p>
                  <p className="mt-1 text-xs leading-5 text-zinc-400">{card.description}</p>
                </div>
                <span className={cx("inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border", style.badge)}>
                  <Icon className="h-4 w-4" />
                </span>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <span className={cx("rounded-full border px-2.5 py-1 text-xs font-semibold capitalize", style.badge)}>
                  {formatConnectionStatus(status)}
                </span>
                <span className="text-xs text-zinc-500">
                  {result?.lastCheckedAt ? `Checked ${relativeSyncTime(result.lastCheckedAt)}` : "Not checked yet"}
                </span>
              </div>
              <p className="mt-3 text-sm leading-6 text-zinc-200">{result?.message ?? "Run the connection test to verify this API."}</p>
              {layers.length ? (
                <div className="mt-3 grid gap-2 border-t border-white/10 pt-3 text-xs leading-5">
                  {layers.map(([key, layer]) => (
                    <div key={key} className="flex items-start justify-between gap-3 rounded-lg border border-white/10 bg-black/10 px-2.5 py-2">
                      <span className="font-medium capitalize text-zinc-300">{key.replaceAll("_", " ")}</span>
                      <span className="max-w-[70%] text-right text-zinc-500">{formatConnectionStatus(layer.status)} - {layer.message}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function startupStatusClass(status: StartupDebugEntry["status"]) {
  if (status === "ok") return "border-emerald-300/25 bg-emerald-300/10 text-emerald-100";
  if (status === "pending") return "border-zinc-300/20 bg-white/[0.04] text-zinc-200";
  if (status === "timeout" || status === "canceled") return "border-amber-300/25 bg-amber-300/10 text-amber-100";
  return "border-red-300/25 bg-red-300/10 text-red-100";
}

function startupDebugSummary(entry: StartupDebugEntry) {
  const duration = entry.durationMs != null ? ` in ${entry.durationMs.toLocaleString()}ms` : "";
  if (entry.status === "ok") return `${entry.httpStatus ?? 200} OK${duration}`;
  if (entry.status === "pending") return "Pending";
  if (entry.status === "timeout") return `Timeout after ${entry.durationMs?.toLocaleString() ?? "unknown"}ms`;
  if (entry.status === "canceled") return `Canceled${duration}`;
  return `${entry.httpStatus ? `${entry.httpStatus} ` : ""}${entry.errorMessage ?? "Error"}${duration}`;
}

function dashboardBlockName(block: DashboardDebugBlock) {
  return block.block || block.name || "unknown";
}

function dashboardCoreFailed(data: DashboardData | null | undefined) {
  return Boolean(data && (data.core_ready === false || data.debug?.dashboard_status === "failed"));
}

function dashboardCoreFailedBlocks(data: DashboardData | null | undefined) {
  const requiredNames = data?.debug?.required_blocks_failed ?? [];
  const blocks = data?.debug?.blocks ?? data?.debug?.errors ?? data?.errors ?? [];
  const matched = blocks.filter((block) => requiredNames.includes(dashboardBlockName(block)) || block.status === "error" || block.status === "timeout");
  if (matched.length) return matched;
  return requiredNames.map((name) => ({ block: name, status: "error", message: "Required dashboard core block failed." }));
}

function dashboardCoreFailureReason(data: DashboardData | null | undefined) {
  const names = data?.debug?.required_blocks_failed ?? dashboardCoreFailedBlocks(data).map(dashboardBlockName);
  return names.length
    ? `Core backend blocks failed: ${names.join(", ")}.`
    : "Dashboard core reported core_ready=false.";
}

class CoreSystemFailureError extends Error {
  readonly dashboard: DashboardData;

  constructor(dashboard: DashboardData) {
    super(dashboardCoreFailureReason(dashboard));
    this.name = "CoreSystemFailureError";
    this.dashboard = dashboard;
  }
}

function buildSystemFailureDebugReport(failure: SystemFailureReport, entries: StartupDebugEntry[]) {
  const dashboardDebug = failure.dashboard?.debug ?? {};
  return {
    headline: "System failed to load",
    reason: failure.reason,
    endpoint: "/api/dashboard/core",
    status: dashboardDebug.dashboard_status ?? "failed",
    ok: failure.dashboard?.ok ?? false,
    core_ready: failure.dashboard?.core_ready ?? false,
    generated_at: dashboardDebug.generated_at ?? null,
    required_blocks: dashboardDebug.required_blocks ?? [],
    required_blocks_failed: failure.requiredBlocksFailed,
    failed_blocks: failure.failedBlocks,
    blocks: dashboardDebug.blocks ?? [],
    frontend_request_timings: entries,
    backend_label: publicApiBaseLabel(),
    vercel_url: typeof window !== "undefined" ? window.location.href : "",
    timestamp: new Date().toISOString(),
  };
}

function StartupDebugPanel({
  entries,
  initiallyOpen = false,
  open,
  onOpenChange,
}: Readonly<{
  entries: StartupDebugEntry[];
  initiallyOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}>) {
  const [localOpen, setLocalOpen] = useState<boolean | null>(null);
  const isOpen = open ?? localOpen ?? initiallyOpen;
  const setPanelOpen = (nextOpen: boolean) => {
    if (open === undefined) {
      setLocalOpen(nextOpen);
    } else {
      onOpenChange?.(nextOpen);
    }
  };
  const sortedEntries = entries.slice().sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  const copyReport = async () => {
    const report = JSON.stringify(sortedEntries, null, 2);
    try {
      await navigator.clipboard.writeText(report);
    } catch {
      window.prompt("Copy debug report", report);
    }
  };

  return (
    <div className="mt-4 rounded-lg border border-white/10 bg-black/20 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" onClick={() => setPanelOpen(!isOpen)} className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-zinc-100">
          <AlertTriangle className="h-4 w-4" />
          {isOpen ? "Hide Debug" : "Show Debug"}
        </button>
        <button type="button" onClick={() => void copyReport()} disabled={!sortedEntries.length} className="rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-50">
          Copy debug report
        </button>
      </div>
      {isOpen ? (
        sortedEntries.length ? (
          <div className="mt-3 space-y-2">
            {sortedEntries.map((entry) => (
              <div key={`${entry.key}-${entry.timestamp}`} className="rounded-lg border border-white/10 bg-zinc-950/70 p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-semibold text-white">{entry.label}</p>
                    <p className="mt-1 break-all text-xs text-zinc-500">{entry.path}</p>
                  </div>
                  <span className={cx("rounded-full border px-2.5 py-1 text-xs font-semibold capitalize", startupStatusClass(entry.status))}>{entry.status}</span>
                </div>
                <div className="mt-3 grid gap-2 text-xs text-zinc-300 sm:grid-cols-2 lg:grid-cols-4">
                  <p><span className="text-zinc-500">Required:</span> {entry.required ? "yes" : "no"}</p>
                  <p><span className="text-zinc-500">HTTP:</span> {entry.httpStatus ?? "--"}</p>
                  <p><span className="text-zinc-500">Duration:</span> {entry.durationMs != null ? `${entry.durationMs.toLocaleString()}ms` : "--"}</p>
                  <p><span className="text-zinc-500">Backend:</span> {entry.backendLabel ?? "--"}</p>
                </div>
                <p className="mt-2 text-sm text-zinc-200">{startupDebugSummary(entry)}</p>
                {entry.errorMessage ? <p className="mt-2 break-words text-xs leading-5 text-red-100/80">{entry.errorMessage}</p> : null}
                {entry.responseText && entry.status !== "ok" ? <pre className="mt-2 max-h-36 overflow-auto rounded-md bg-black/30 p-2 text-xs text-zinc-300">{entry.responseText}</pre> : null}
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-sm text-zinc-400">No startup requests have been recorded yet.</p>
        )
      ) : null}
    </div>
  );
}

function SystemFailureScreen({
  failure,
  entries,
  onRetry,
}: Readonly<{
  failure: SystemFailureReport;
  entries: StartupDebugEntry[];
  onRetry: () => void;
}>) {
  const [debugOpen, setDebugOpen] = useState(true);
  const report = buildSystemFailureDebugReport(failure, entries);
  const reportText = JSON.stringify(report, null, 2);
  const generatedAt = failure.dashboard?.debug?.generated_at ?? failure.timestamp;
  const copyReport = async () => {
    try {
      await navigator.clipboard.writeText(reportText);
    } catch {
      window.prompt("Copy debug report", reportText);
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <Card className="border-red-400/35 bg-red-400/[0.08]">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-red-300/30 bg-red-300/10">
                <AlertTriangle className="h-5 w-5 text-red-100" />
              </span>
              <div>
                <p className="text-sm font-semibold uppercase tracking-[0.16em] text-red-100/70">Startup diagnostics</p>
                <h2 className="mt-1 text-2xl font-semibold text-white">System failed to load</h2>
              </div>
            </div>
            <p className="mt-4 max-w-3xl text-sm leading-6 text-red-50/80">
              Core backend blocks failed. The app is paused so bad data is not shown.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {failure.failedBlocks.length ? failure.failedBlocks.map((block) => (
                <span key={`${dashboardBlockName(block)}-${block.error_type ?? block.status ?? block.message}`} className="rounded-full border border-red-300/30 bg-red-300/10 px-3 py-1 text-xs font-semibold text-red-50">
                  {dashboardBlockName(block)}: {block.error_type ?? block.status ?? "failed"}
                </span>
              )) : (
                <span className="rounded-full border border-red-300/30 bg-red-300/10 px-3 py-1 text-xs font-semibold text-red-50">
                  dashboard_core: failed
                </span>
              )}
            </div>
            <p className="mt-3 text-xs text-red-100/60">Generated {generatedAt}</p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <button type="button" onClick={onRetry} className="inline-flex h-10 items-center gap-2 rounded-lg border border-red-200/40 bg-red-200/10 px-3 text-sm font-semibold text-red-50 transition hover:bg-red-200/15">
              <RefreshCw className="h-4 w-4" />
              Retry
            </button>
            <button type="button" onClick={() => void copyReport()} className="inline-flex h-10 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm font-semibold text-zinc-100 transition hover:bg-white/[0.07]">
              <Copy className="h-4 w-4" />
              Copy debug report
            </button>
          </div>
        </div>
      </Card>

      <div className="rounded-lg border border-white/10 bg-black/20 p-3">
        <button type="button" onClick={() => setDebugOpen((value) => !value)} className="flex w-full items-center justify-between gap-3 rounded-lg px-2 py-2 text-left">
          <span className="text-sm font-semibold text-white">Debug report</span>
          <ChevronDown className={cx("h-4 w-4 text-zinc-400 transition", debugOpen && "rotate-180")} />
        </button>
        {debugOpen ? (
          <div className="mt-3 space-y-4">
            <div className="grid gap-3 text-xs text-zinc-300 md:grid-cols-2 xl:grid-cols-4">
              <p><span className="text-zinc-500">Endpoint:</span> /api/dashboard/core</p>
              <p><span className="text-zinc-500">Status:</span> {String(report.status)}</p>
              <p><span className="text-zinc-500">Backend:</span> {publicApiBaseLabel()}</p>
              <p><span className="text-zinc-500">Timestamp:</span> {failure.timestamp}</p>
              <p className="break-all md:col-span-2 xl:col-span-4"><span className="text-zinc-500">Vercel URL:</span> {typeof window !== "undefined" ? window.location.href : ""}</p>
            </div>

            <div className="space-y-2">
              {(failure.failedBlocks.length ? failure.failedBlocks : [{ block: "dashboard_core", status: "error", message: failure.reason }]).map((block) => (
                <div key={`${dashboardBlockName(block)}-${block.error_type ?? block.message}`} className="rounded-lg border border-red-300/20 bg-red-300/[0.055] p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-semibold text-red-50">{dashboardBlockName(block)}</p>
                    <span className="rounded-full border border-red-300/30 px-2.5 py-1 text-xs font-semibold text-red-50">{block.status ?? "failed"}</span>
                  </div>
                  <div className="mt-3 grid gap-2 text-xs text-red-50/80 md:grid-cols-2 xl:grid-cols-4">
                    <p><span className="text-red-100/50">Error:</span> {block.error_type ?? "--"}</p>
                    <p><span className="text-red-100/50">Duration:</span> {block.duration_ms != null ? `${block.duration_ms}ms` : "--"}</p>
                    <p><span className="text-red-100/50">Function:</span> {block.function ?? "--"}</p>
                    <p><span className="text-red-100/50">Endpoint:</span> {block.endpoint ?? "/api/dashboard/core"}</p>
                  </div>
                  {block.message ? <p className="mt-3 break-words text-sm leading-6 text-red-50">{block.message}</p> : null}
                  {block.trace_excerpt ? <pre className="mt-3 max-h-44 overflow-auto rounded-md bg-black/35 p-3 text-xs leading-5 text-red-50/75">{block.trace_excerpt}</pre> : null}
                </div>
              ))}
            </div>

            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">Frontend request timings</p>
              <div className="space-y-2">
                {entries.slice(-12).map((entry) => (
                  <div key={`${entry.key}-${entry.timestamp}`} className="rounded-lg border border-white/10 bg-zinc-950/70 p-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-semibold text-white">{entry.label}</p>
                        <p className="mt-1 break-all text-xs text-zinc-500">{entry.path}</p>
                      </div>
                      <span className={cx("rounded-full border px-2.5 py-1 text-xs font-semibold capitalize", startupStatusClass(entry.status))}>{entry.status}</span>
                    </div>
                    <p className="mt-2 text-xs text-zinc-300">{startupDebugSummary(entry)}</p>
                    {entry.errorMessage ? <p className="mt-2 break-words text-xs leading-5 text-red-100/80">{entry.errorMessage}</p> : null}
                    {entry.responseText && entry.status !== "ok" ? <pre className="mt-2 max-h-36 overflow-auto rounded-md bg-black/30 p-2 text-xs text-zinc-300">{entry.responseText}</pre> : null}
                  </div>
                ))}
              </div>
            </div>

            <pre className="max-h-72 overflow-auto rounded-lg border border-white/10 bg-zinc-950/80 p-3 text-xs leading-5 text-zinc-300">{reportText}</pre>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function StartupDebugPage({
  entries,
  onRetry,
}: Readonly<{
  entries: StartupDebugEntry[];
  onRetry: () => void;
}>) {
  const latest = entries.slice(-6);
  return (
    <div className="space-y-4">
      <Card>
        <SectionHeader
          eyebrow="Diagnostics"
          title="Startup Debug"
          action={
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => window.open("/api/debug/proxy-dashboard-core", "_blank", "noopener,noreferrer")} className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04]">
                <ExternalLink className="h-4 w-4" />
                Core probe
              </button>
              <button type="button" onClick={() => window.open("/api/debug/proxy", "_blank", "noopener,noreferrer")} className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04]">
                <ExternalLink className="h-4 w-4" />
                Proxy probe
              </button>
              <button type="button" onClick={onRetry} className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04]">
                <RefreshCw className="h-4 w-4" />
                Retry startup
              </button>
            </div>
          }
        />
        {latest.length ? (
          <div className="grid gap-3 md:grid-cols-3">
            {latest.map((entry) => (
              <div key={`${entry.key}-${entry.timestamp}`} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate text-sm font-semibold text-white">{entry.label}</p>
                  <span className={cx("rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize", startupStatusClass(entry.status))}>{entry.status}</span>
                </div>
                <p className="mt-2 text-xs text-zinc-400">{startupDebugSummary(entry)}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-zinc-400">No startup requests have been recorded yet.</p>
        )}
        <StartupDebugPanel entries={entries} initiallyOpen />
      </Card>
    </div>
  );
}


function AccentThemePicker({ value, onChange }: Readonly<{ value: AccentTheme; onChange: (theme: AccentTheme) => void }>) {
  return (
    <Card>
      <SectionHeader eyebrow="Appearance" title="Accent Color" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {accentThemeOptions.map((option) => {
          const active = value === option.id;
          return (
            <button
              key={option.id}
              type="button"
              onClick={() => onChange(option.id)}
              className={cx(
                "flex min-h-20 items-center justify-between gap-3 rounded-lg border px-3 py-3 text-left transition",
                active ? "accent-soft shadow-lg shadow-[var(--accent-glow)]" : "border-white/10 bg-white/[0.035] text-zinc-300 hover:border-[var(--accent-border)] hover:bg-white/[0.055]",
              )}
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className={cx("h-8 w-8 shrink-0 rounded-full border border-white/20 shadow-inner", option.swatch)} />
                <span className="min-w-0">
                  <span className={cx("block text-sm font-semibold", active ? "accent-text-strong" : "text-white")}>{option.label}</span>
                  <span className="mt-1 block text-xs text-zinc-500">{active ? "Active" : "Theme color"}</span>
                </span>
              </span>
              {active ? <Check className="h-4 w-4 shrink-0 accent-text-strong" /> : null}
            </button>
          );
        })}
      </div>
    </Card>
  );
}

function settingsStatusBadgeClass(status?: string) {
  const normalized = String(status || "").toLowerCase();
  if (normalized.includes("connected") || normalized === "configured" || normalized === "green") {
    return "border-emerald-300/25 bg-emerald-300/10 text-emerald-100";
  }
  if (normalized.includes("reconnect") || normalized.includes("expired") || normalized.includes("syncing") || normalized.includes("warning") || normalized === "yellow") {
    return "border-amber-300/25 bg-amber-300/10 text-amber-100";
  }
  if (normalized.includes("error") || normalized === "red") {
    return "border-red-400/25 bg-red-400/10 text-red-100";
  }
  return "border-zinc-500/30 bg-zinc-500/10 text-zinc-300";
}

function settingsStatusLabel(status?: string) {
  const value = String(status || "Not configured").trim();
  if (!value) return "Not configured";
  return value.replaceAll("_", " ");
}

function settingsHealthCard(settings: SettingsData | null, id: string) {
  return settings?.health?.find((card) => card.id === id);
}

function settingsService(settings: SettingsData | null, id: string) {
  return settings?.services?.[id];
}

function settingsLastSync(settings: SettingsData | null, id: string) {
  const health = settingsHealthCard(settings, id);
  const service = settingsService(settings, id);
  const diagnostic = id === "hevy"
    ? settings?.hevy
    : id === "strava"
      ? settings?.strava
      : id === "withings"
        ? settings?.withings
        : id === "openai"
          ? settings?.openai
          : undefined;
  return health?.last_synced_at || service?.last_synced_at || diagnostic?.last_successful_sync || "";
}

function SettingsConnectionCard({
  title,
  description,
  status,
  lastSync,
  actions = [],
}: Readonly<{
  title: string;
  description: string;
  status?: string;
  lastSync?: string;
  actions?: Array<{ label: string; onClick: () => void; disabled?: boolean; variant?: "primary" | "secondary" | "danger" }>;
}>) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.035] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-white">{title}</p>
          <p className="mt-1 text-sm leading-6 text-zinc-400">{description}</p>
        </div>
        <span className={cx("shrink-0 rounded-full border px-2.5 py-1 text-xs font-semibold capitalize", settingsStatusBadgeClass(status))}>
          {settingsStatusLabel(status)}
        </span>
      </div>
      <p className="mt-3 text-xs text-zinc-500">
        {lastSync ? `Last sync ${relativeSyncTime(lastSync)}` : "Last sync not available"}
      </p>
      {actions.length ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {actions.map((action) => (
            <button
              key={action.label}
              type="button"
              onClick={action.onClick}
              disabled={action.disabled}
              className={cx(
                "h-10 rounded-lg px-3 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50",
                action.variant === "primary"
                  ? "accent-bg"
                  : action.variant === "danger"
                    ? "border border-red-300/20 text-red-100 hover:bg-red-300/10"
                    : "border border-white/10 text-zinc-200 hover:bg-white/[0.04]",
              )}
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SettingsInfoRows({ rows }: Readonly<{ rows: Array<{ label: string; value: string; detail?: string }> }>) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {rows.map((row) => (
        <div key={row.label} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-500">{row.label}</p>
          <p className="mt-1 text-sm font-semibold text-white">{row.value}</p>
          {row.detail ? <p className="mt-1 text-xs leading-5 text-zinc-500">{row.detail}</p> : null}
        </div>
      ))}
    </div>
  );
}


function SettingsPage({
  settings,
  accentTheme,
  apiConnectionTests,
  apiConnectionTesting,
  forms,
  setForms,
  onSubmit,
  onAccentThemeChange,
  onTestApiConnections,
  onConnectStrava,
  onConnectWithings,
  onSyncWithings,
  onSyncWithingsHistory,
  onTestOpenAI,
  onSyncHevy,
  onImportStrava,
  onClearWithings,
}: Readonly<{
  settings: SettingsData | null;
  accentTheme: AccentTheme;
  apiConnectionTests: ApiConnectionTestResponse | null;
  apiConnectionTesting: boolean;
  forms: FormState;
  setForms: React.Dispatch<React.SetStateAction<FormState>>;
  onSubmit: (event: FormEvent) => void;
  onAccentThemeChange: (theme: AccentTheme) => void;
  onTestApiConnections: () => void;
  onConnectStrava: (reconnect?: boolean) => void;
  onConnectWithings: () => void;
  onSyncWithings: () => void;
  onSyncWithingsHistory: () => void;
  onTestOpenAI: () => void;
  onSyncHevy: () => void;
  onImportStrava: () => void;
  onClearWithings: () => void;
}>) {
  const withingsConnected = settings?.statuses?.withings === "Connected";
  const stravaStatus = settings?.statuses?.strava ?? "Not configured";
  const stravaReconnect = stravaStatus === "Connected" || stravaStatus === "Reconnect required" || stravaStatus === "Expired/Reauth required";
  const stravaConnected = stravaStatus === "Connected";
  const hevyStatus = settings?.statuses?.hevy_api_key ?? settingsHealthCard(settings, "hevy")?.status ?? "Not configured";
  const withingsStatus = settings?.statuses?.withings ?? settingsHealthCard(settings, "withings")?.status ?? "Not configured";
  const fitbitStatus = settings?.statuses?.fitbit_google_health ?? settings?.statuses?.fitbit_client_id ?? "Not configured";
  const openAiStatus = settings?.statuses?.openai_api_key ?? settingsService(settings, "openai")?.status ?? "Not configured";
  const appleHealthStatus = settings?.statuses?.apple_health_export_file ?? "Local upload";
  return (
    <div className="space-y-4">
      <Card>
        <SectionHeader eyebrow="Connections" title="Integrations" />
        <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
          <SettingsConnectionCard
            title="Hevy"
            description={settingsHealthCard(settings, "hevy")?.detail ?? "Workout import and training history."}
            status={hevyStatus}
            lastSync={settingsLastSync(settings, "hevy")}
            actions={[{ label: "Sync Hevy", onClick: onSyncHevy, variant: "secondary" }]}
          />
          <SettingsConnectionCard
            title="Strava"
            description={settingsHealthCard(settings, "strava")?.detail ?? "OAuth connection for run and cardio imports."}
            status={stravaStatus}
            lastSync={settingsLastSync(settings, "strava")}
            actions={[{ label: stravaReconnect ? "Reconnect Strava" : "Connect Strava", onClick: () => onConnectStrava(stravaReconnect), variant: "primary" }]}
          />
          <SettingsConnectionCard
            title="Withings"
            description={settingsHealthCard(settings, "withings")?.detail ?? "Scale measurements and body composition sync."}
            status={withingsStatus}
            lastSync={settingsLastSync(settings, "withings")}
            actions={[
              { label: withingsConnected ? "Reconnect Withings" : "Connect Withings", onClick: onConnectWithings, variant: "primary" },
              { label: "Disconnect", onClick: onClearWithings, disabled: !withingsConnected, variant: "danger" },
            ]}
          />
          <SettingsConnectionCard
            title="Fitbit / Google Health"
            description="Prepared for wearable recovery signals when OAuth sync is enabled."
            status={fitbitStatus}
            lastSync={settingsLastSync(settings, "fitbit")}
          />
          <SettingsConnectionCard
            title="OpenAI"
            description={settingsService(settings, "openai")?.message ?? "Food parser and higher-accuracy nutrition parsing."}
            status={openAiStatus}
            lastSync={settingsLastSync(settings, "openai")}
            actions={[{ label: "Test Food Parser", onClick: onTestOpenAI, variant: "secondary" }]}
          />
          <SettingsConnectionCard
            title="Apple Health"
            description="Local export upload support for web-based imports."
            status={appleHealthStatus}
            lastSync={settingsLastSync(settings, "apple_health")}
          />
        </div>
      </Card>
      <Card>
        <SectionHeader eyebrow="Preferences" title="App Preferences" />
        <SettingsInfoRows
          rows={[
            { label: "Language", value: "English", detail: "Interface copy and date formatting use the current app locale." },
            { label: "Units", value: "lb", detail: "Weight and nutrition views use imperial display units." },
            { label: "Mobile layout", value: "Bottom tabs on phones", detail: "Desktop and tablet keep the sidebar layout." },
            { label: "Auto-refresh", value: "After sync actions", detail: "Dashboard and history refresh after imports and manual syncs." },
          ]}
        />
      </Card>
      <AccentThemePicker value={accentTheme} onChange={onAccentThemeChange} />
      <Card>
        <SectionHeader eyebrow="Nutrition & AI" title="Food Logging Preferences" />
        <SettingsInfoRows
          rows={[
            { label: "AI food parsing", value: "Hybrid saved-food first", detail: "Saved foods and shortcuts are matched before model estimates." },
            { label: "Higher accuracy", value: "Use when confidence is low", detail: "Ambiguous entries can escalate without changing the normal quick path." },
            { label: "Macro calories", value: "Auto-calculate by default", detail: "Manual calories are still respected when overridden." },
            { label: "Default logging", value: "Quick-log saved foods", detail: "Presets log fast; AI-estimated foods stay reviewable before saving." },
            { label: "Low confidence", value: "Confirm before logging", detail: "Assumptions stay visible before uncertain AI estimates are saved." },
          ]}
        />
      </Card>
      <Card>
        <SectionHeader eyebrow="Data & Sync" title="Manual Sync Actions" />
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {[
            { label: "Sync Hevy", detail: "Refresh workout history and training summaries.", onClick: onSyncHevy, disabled: false },
            { label: "Manual Strava Import", detail: "Import recent run/cardio activities.", onClick: onImportStrava, disabled: !stravaConnected },
            { label: "Sync Weight Now", detail: "Pull the latest Withings scale measurement.", onClick: onSyncWithings, disabled: !withingsConnected },
            { label: "Sync Withings History", detail: "Backfill historical weight and body composition.", onClick: onSyncWithingsHistory, disabled: !withingsConnected },
          ].map((action) => (
            <div key={action.label} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
              <p className="text-sm font-semibold text-white">{action.label}</p>
              <p className="mt-1 min-h-10 text-xs leading-5 text-zinc-500">{action.detail}</p>
              <button
                type="button"
                onClick={action.onClick}
                disabled={action.disabled}
                className="mt-3 h-10 w-full rounded-lg border border-white/10 px-3 text-sm font-semibold text-zinc-200 transition hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-50"
              >
                Run
              </button>
            </div>
          ))}
        </div>
      </Card>
      <details className="group rounded-xl border border-white/10 bg-white/[0.025] p-4">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.24em] text-zinc-500">Advanced / Debug</p>
            <h2 className="mt-1 text-lg font-semibold text-white">Diagnostics and local connection fields</h2>
            <p className="mt-1 text-sm text-zinc-500">Raw statuses, API tests, and saved integration values are tucked away here.</p>
          </div>
          <ChevronDown className="h-5 w-5 shrink-0 text-zinc-400 transition group-open:rotate-180" />
        </summary>
        <div className="mt-4 space-y-4">
          <Card>
            <SectionHeader eyebrow="Integrations" title="API keys and local connection info" />
            <form onSubmit={onSubmit} className="grid gap-4 md:grid-cols-2">
              {Object.entries(integrationLabels).map(([key, label]) => (
                <TextInput
                  key={key}
                  label={label}
                  type={key.includes("secret") || key.includes("key") ? "password" : "text"}
                  value={forms.settings[key] ?? ""}
                  placeholder={settings?.integrations?.[key] ?? "Leave blank if not configured"}
                  onChange={(value) => setForms((state) => ({ ...state, settings: { ...state.settings, [key]: value } }))}
                />
              ))}
              <button className="accent-bg h-11 rounded-lg text-sm font-semibold md:col-span-2">Save settings locally</button>
            </form>
          </Card>
          <Card>
            <SectionHeader eyebrow="Diagnostics" title="Backend connection" />
            <p className="text-sm text-zinc-400">
              Active backend base URL:{" "}
              <span className="accent-text-strong font-mono">{publicApiBaseLabel()}</span>
            </p>
            <p className="mt-1 text-xs text-zinc-500">
              Resolved from NEXT_PUBLIC_API_URL. Requests time out after {Math.round(DEFAULT_API_TIMEOUT_MS / 1000)}s.
            </p>
          </Card>
          <ApiConnectionTestPanel results={apiConnectionTests} testing={apiConnectionTesting} onTest={onTestApiConnections} />
          <DiagnosticStatusDashboard settings={settings} />
          {settings?.health?.length ? <IntegrationHealthGrid cards={settings.health} onSyncHevy={onSyncHevy} onImportStrava={onImportStrava} onConnectStrava={onConnectStrava} onConnectWithings={onConnectWithings} onSyncWithings={onSyncWithings} /> : null}
          <Card>
            <SectionHeader eyebrow="Raw state" title="Saved integration values" />
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {Object.entries(integrationLabels).map(([key, label]) => (
                <div key={key} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
                  <p className="font-semibold text-white">{label}</p>
                  <p className="mt-2 text-sm text-zinc-400">Saved value: {settings?.integrations?.[key] ?? "Not configured"}</p>
                  <p className={cx("mt-3 inline-flex rounded-full border px-3 py-1 text-xs font-semibold", settingsStatusBadgeClass(settings?.statuses?.[key]))}>
                    {settingsStatusLabel(settings?.statuses?.[key])}
                  </p>
                </div>
              ))}
            </div>
          </Card>
          <p className="text-xs leading-5 text-zinc-500">
            Apple Health remains file-upload based for the web app. HealthKit requires an iOS app and explicit user permissions.
          </p>
        </div>
      </details>
      <AquariumEasterEgg />
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

function DailyNutritionHistoryTable({
  rows,
  excludingDate,
  onExcludeDay,
}: Readonly<{
  rows: DailyNutritionSummary[];
  excludingDate: string;
  onExcludeDay: (date: string) => void;
}>) {
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
            <th className="px-3 py-2 font-medium">action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/10">
          {rows.map((row, index) => {
            const rowDate = String(row.date || "").slice(0, 10);
            return (
              <tr key={`${rowDate}-${index}`} className="text-zinc-200">
                {columns.map((column) => {
                  const value = (row as unknown as Record<string, unknown>)[column];
                  return (
                    <td key={column} className="px-3 py-2">
                      {value === null || value === undefined || value === "" ? "—" : String(value)}
                    </td>
                  );
                })}
                <td className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => onExcludeDay(rowDate)}
                    disabled={!rowDate || excludingDate === rowDate}
                    className="rounded-lg border border-red-300/20 px-2.5 py-1 text-xs font-semibold text-red-100 transition hover:bg-red-300/10 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {excludingDate === rowDate ? "Excluding..." : "Exclude"}
                  </button>
                </td>
              </tr>
            );
          })}
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

function initialPageFromUrl(): PageId {
  if (typeof window === "undefined") return "dashboard";
  const page = new URLSearchParams(window.location.search).get("page");
  return navigation.some((item) => item.id === page) ? page as PageId : "dashboard";
}

function initialIntegrationNotice(kind: "message" | "error") {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const provider = params.has("strava") ? "Strava" : params.has("withings") ? "Withings" : "";
  if (!provider) return null;
  const status = (params.get(provider.toLowerCase()) ?? "").toLowerCase();
  const text = params.get("message");
  if (kind === "message" && status === "connected") return text || `${provider} connected.`;
  if (kind === "error" && status === "error") return text || `${provider} connection failed.`;
  return null;
}

function HomeContent() {
  const [activePage, setActivePage] = useState<PageId>("dashboard");
  const [headerDateLabel, setHeaderDateLabel] = useState(headerDateString);
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
  const [workoutMarkers, setWorkoutMarkers] = useState<WorkoutMarker[]>([]);
  const [wearableMetrics, setWearableMetrics] = useState<WearableMetricEntry[]>([]);
  const [wearableSignals, setWearableSignals] = useState<WearableSignals | null>(null);
  const [trainingReadiness, setTrainingReadiness] = useState<TrainingReadinessSignals | null>(null);
  const [muscleCoverage, setMuscleCoverage] = useState<MuscleCoverageResponse | null>(null);
  const [workoutHistory, setWorkoutHistory] = useState<WorkoutGroup[]>([]);
  const [trainingHistoryMeta, setTrainingHistoryMeta] = useState({ rawWindowDays: 180, hasMoreRecent: false, limit: 50, message: "" });
  const [trainingSummary, setTrainingSummary] = useState<TrainingSummaryResponse | null>(null);
  const [trainingSummaryStatus, setTrainingSummaryStatus] = useState<TrainingSummaryStatusResponse | null>(null);
  const [trainingDataAction, setTrainingDataAction] = useState<"idle" | "exporting" | "rebuilding">("idle");
  const [strengthTrends, setStrengthTrends] = useState<StrengthTrendResponse | null>(null);
  const [trainingPrs, setTrainingPrs] = useState<TrainingPrResponse | null>(null);
  const [trainingPrsLoading, setTrainingPrsLoading] = useState(false);
  const [selectedExercise, setSelectedExercise] = useState("");
  const [trendView, setTrendView] = useState<"exercise" | "muscle_group">("muscle_group");
  const [selectedMuscleGroup, setSelectedMuscleGroup] = useState("");
  const [trendDateRange, setTrendDateRange] = useState("12w");
  const [muscleTrendMetric, setMuscleTrendMetric] = useState<keyof Pick<MuscleGroupTrendHistory, "strength_index" | "weekly_volume" | "hard_sets" | "total_reps" | "best_estimated_1rm">>("strength_index");
  const [trainingInsight, setTrainingInsight] = useState<TrainingInsight | null>(null);
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [apiConnectionTests, setApiConnectionTests] = useState<ApiConnectionTestResponse | null>(null);
  const [apiConnectionTesting, setApiConnectionTesting] = useState(false);
  const [accentTheme, setAccentTheme] = useState<AccentTheme>(() => readStoredAccentTheme());
  const [forms, setForms] = useState<FormState>(initialForms);
  const [aiText, setAiText] = useState("");
  const [parsedFoods, setParsedFoods] = useState<ParsedFood[]>([]);
  const [parseResult, setParseResult] = useState<FoodParseResponse | null>(null);
  const [foodAiFlow, setFoodAiFlow] = useState<FoodAiFlowStep[]>([]);
  const [foodAiDebug, setFoodAiDebug] = useState<FoodAiDebugState | null>(null);
  const [parseLoading, setParseLoading] = useState(false);
  const [manualFoodMode, setManualFoodMode] = useState<"direct" | "serving">("direct");
  const [manualCaloriesOverridden, setManualCaloriesOverridden] = useState(false);
  const [quickFoodLogStatuses, setQuickFoodLogStatuses] = useState<Record<string, QuickFoodLogStatus>>({});
  const [quickFoodPendingCount, setQuickFoodPendingCount] = useState(0);
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
  const [loadingMessage, setLoadingMessage] = useState("Waking backend...");
  const [message, setMessage] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [loadFailures, setLoadFailures] = useState<string[]>([]);
  const [systemFailure, setSystemFailure] = useState<SystemFailureReport | null>(null);
  const [rateLimited, setRateLimited] = useState(false);
  const [startupDebug, setStartupDebug] = useState<StartupDebugEntry[]>([]);
  const [showDebugPanel, setShowDebugPanel] = useState(false);
  const mobileNavRef = useRef<HTMLDivElement | null>(null);
  const quickFoodQueueRef = useRef<QuickFoodLogJob[]>([]);
  const quickFoodProcessingRef = useRef(false);
  const quickFoodProcessRef = useRef<() => void>(() => undefined);
  const quickFoodLastClickRef = useRef<Record<string, number>>({});
  const materializedDefaultShortcutIdsRef = useRef<Record<string, string>>({});
  const mobileItemRefs = useRef<Partial<Record<PageId, HTMLButtonElement | null>>>({});
  const [mobileHighlight, setMobileHighlight] = useState<MobileNavHighlight>({ left: 0, top: 0, width: 0, height: 0, ready: false });
  const bottomNavRef = useRef<HTMLDivElement | null>(null);
  const bottomItemRefs = useRef<Partial<Record<PageId, HTMLButtonElement | null>>>({});
  const [bottomHighlight, setBottomHighlight] = useState<MobileNavHighlight>({ left: 0, top: 0, width: 0, height: 0, ready: false });

  useEffect(() => {
    const interval = window.setInterval(() => {
      setHeaderDateLabel(headerDateString());
    }, 60_000);
    return () => window.clearInterval(interval);
  }, []);

  // Surface server-side rate limiting (HTTP 429) while the fetch layer retries.
  useEffect(() => subscribeRateLimit(setRateLimited), []);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setActivePage(initialPageFromUrl());
      setMessage(initialIntegrationNotice("message"));
      setApiError(initialIntegrationNotice("error"));
    }, 0);
    return () => window.clearTimeout(timeout);
  }, []);

  useLayoutEffect(() => {
    const measureActiveNavItems = () => {
      const mobileItem = mobileItemRefs.current[activePage];
      if (mobileItem && mobileNavRef.current) {
        setMobileHighlight({
          left: mobileItem.offsetLeft,
          top: mobileItem.offsetTop,
          width: mobileItem.offsetWidth,
          height: mobileItem.offsetHeight,
          ready: true,
        });
      } else {
        setMobileHighlight((current) => ({ ...current, ready: false }));
      }
      const bottomItem = bottomItemRefs.current[activePage];
      if (bottomItem && bottomNavRef.current) {
        setBottomHighlight({
          left: bottomItem.offsetLeft,
          top: bottomItem.offsetTop,
          width: bottomItem.offsetWidth,
          height: bottomItem.offsetHeight,
          ready: true,
        });
      } else {
        setBottomHighlight((current) => ({ ...current, ready: false }));
      }
    };

    measureActiveNavItems();
    window.addEventListener("resize", measureActiveNavItems);
    return () => window.removeEventListener("resize", measureActiveNavItems);
  }, [activePage]);

  useEffect(() => {
    document.documentElement.dataset.accentTheme = accentTheme;
    window.localStorage.setItem(ACCENT_THEME_STORAGE_KEY, accentTheme);
  }, [accentTheme]);

  const currentPage = navigation.find((item) => item.id === activePage) ?? navigation[0];
  const activePrimaryNavIndex = primaryNavigation.findIndex((item) => item.id === activePage);
  const primaryNavActive = activePrimaryNavIndex >= 0;
  const activeNavOffset = Math.max(0, activePrimaryNavIndex) * 48;
  const [sidebarHighlightOffset, setSidebarHighlightOffset] = useState(0);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      setSidebarHighlightOffset(activeNavOffset);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeNavOffset]);

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

  const applySettingsData = useCallback((nextSettings: SettingsData) => {
    setSettings(nextSettings);
    if (nextSettings.appearance?.accent_color) {
      setAccentTheme(sanitizeAccentTheme(nextSettings.appearance.accent_color));
    }
  }, []);

  const recordStartupDebug = useCallback((entry: StartupDebugEntry) => {
    setStartupDebug((current) => {
      const filtered = current.filter((item) => item.key !== entry.key || item.status !== "pending");
      return [...filtered, entry].slice(-80);
    });
  }, []);

  const handleAccentThemeChange = useCallback(async (theme: AccentTheme) => {
    const nextTheme = sanitizeAccentTheme(theme);
    setAccentTheme(nextTheme);
    setSettings((state) => state ? { ...state, appearance: { ...(state.appearance ?? {}), accent_color: nextTheme } } : state);
    try {
      const updated = await apiSend<SettingsData>("/api/settings", "PUT", { appearance: { accent_color: nextTheme } });
      applySettingsData(updated);
      setMessage(`Accent color set to ${accentThemeOptions.find((option) => option.id === nextTheme)?.label ?? "Lime"}.`);
    } catch {
      window.localStorage.setItem(ACCENT_THEME_STORAGE_KEY, nextTheme);
      setMessage("Accent color saved on this device. Backend settings were unavailable.");
    }
  }, [applySettingsData]);

  const handleTestApiConnections = useCallback(async () => {
    setApiConnectionTesting(true);
    setApiError(null);
    setMessage(null);
    try {
      const results = await apiGet<ApiConnectionTestResponse>("/api/integrations/test", SETTINGS_API_TIMEOUT_MS);
      setApiConnectionTests(results);
      setMessage("API connection tests complete.");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "API connection tests failed.");
    } finally {
      setApiConnectionTesting(false);
    }
  }, []);

  const loadDeferredData = useCallback(async () => {
    const deferredSteps: Array<{
      key: string;
      label: string;
      path: string;
      timeoutMs?: number;
      run: () => Promise<void>;
    }> = [
      {
        key: "integration_status",
        label: "Integration status",
        path: "/api/integrations/status?external_checks=false",
        timeoutMs: SETTINGS_API_TIMEOUT_MS,
        run: async () => applySettingsData(await trackedApiGet<SettingsData>({ key: "integration_status", label: "Integration status", path: "/api/integrations/status?external_checks=false", required: false }, SETTINGS_API_TIMEOUT_MS, recordStartupDebug)),
      },
      {
        key: "backend_startup_debug",
        label: "Backend startup debug",
        path: "/api/debug/startup",
        timeoutMs: SETTINGS_API_TIMEOUT_MS,
        run: async () => {
          await trackedApiGet<Record<string, unknown>>({ key: "backend_startup_debug", label: "Backend startup debug", path: "/api/debug/startup", required: false }, SETTINGS_API_TIMEOUT_MS, recordStartupDebug);
        },
      },
      {
        key: "nutrition_logs",
        label: "Nutrition logs",
        path: "/api/nutrition/logs?days=90&limit=300",
        run: async () => {
          const data = await trackedApiGet<{ items: NutritionEntry[] }>({ key: "nutrition_logs", label: "Nutrition logs", path: "/api/nutrition/logs?days=90&limit=300", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug);
          setNutritionLogs(data.items);
        },
      },
      {
        key: "nutrition_history",
        label: "Nutrition history",
        path: "/api/nutrition/history",
        run: async () => {
          const data = await trackedApiGet<{ items: DailyNutritionSummary[]; adherence: NutritionAdherence }>({ key: "nutrition_history", label: "Nutrition history", path: "/api/nutrition/history", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug);
          setNutritionHistory(data.items);
          setNutritionAdherence(data.adherence);
        },
      },
      {
        key: "nutrition_shortcuts",
        label: "Nutrition shortcuts",
        path: "/api/nutrition/shortcuts",
        run: async () => setShortcutData(await trackedApiGet<NutritionShortcutData>({ key: "nutrition_shortcuts", label: "Nutrition shortcuts", path: "/api/nutrition/shortcuts", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug)),
      },
      {
        key: "body_metrics",
        label: "Body metrics",
        path: "/api/body-metrics",
        run: async () => {
          const data = await trackedApiGet<{ items: BodyMetricEntry[]; canonical_items?: BodyMetricEntry[]; raw_items?: BodyMetricEntry[] }>({ key: "body_metrics", label: "Body metrics", path: "/api/body-metrics", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug);
          setBodyMetrics(data.canonical_items ?? data.items);
        },
      },
      {
        key: "recovery_logs",
        label: "Recovery logs",
        path: "/api/recovery/logs",
        run: async () => {
          const data = await trackedApiGet<{ items: RecoveryEntry[] }>({ key: "recovery_logs", label: "Recovery logs", path: "/api/recovery/logs", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug);
          setRecoveryLogs(data.items);
        },
      },
      {
        key: "sleep",
        label: "Sleep",
        path: "/api/recovery/sleep",
        run: async () => {
          const data = await trackedApiGet<{ items: SleepEntry[] }>({ key: "sleep", label: "Sleep", path: "/api/recovery/sleep", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug);
          setSleepEntries(data.items);
        },
      },
      {
        key: "workout_markers",
        label: "Workout markers",
        path: "/api/workout-markers",
        run: async () => {
          const data = await trackedApiGet<{ items: WorkoutMarker[] }>({ key: "workout_markers", label: "Workout markers", path: "/api/workout-markers", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug);
          setWorkoutMarkers(Array.isArray(data.items) ? data.items : []);
        },
      },
      {
        key: "wearable_metrics",
        label: "Wearable metrics",
        path: "/api/wearables/metrics",
        run: async () => {
          const data = await trackedApiGet<{ items: WearableMetricEntry[] }>({ key: "wearable_metrics", label: "Wearable metrics", path: "/api/wearables/metrics", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug);
          setWearableMetrics(Array.isArray(data.items) ? data.items : []);
        },
      },
      {
        key: "wearable_signals",
        label: "Wearable signals",
        path: "/api/wearables/signals",
        run: async () => setWearableSignals(await trackedApiGet<WearableSignals>({ key: "wearable_signals", label: "Wearable signals", path: "/api/wearables/signals", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug)),
      },
      {
        key: "training_readiness",
        label: "Training readiness",
        path: "/api/wearables/training-readiness",
        run: async () => setTrainingReadiness(await trackedApiGet<TrainingReadinessSignals>({ key: "training_readiness", label: "Training readiness", path: "/api/wearables/training-readiness", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug)),
      },
      {
        key: "training_history",
        label: "Training history",
        path: "/api/training/history?limit=50&days=180",
        run: async () => {
          const data = await trackedApiGet<TrainingHistoryResponse>({ key: "training_history", label: "Training history", path: "/api/training/history?limit=50&days=180", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug);
          setWorkoutHistory(data.items);
          setTrainingHistoryMeta({
            rawWindowDays: Number(data.raw_window_days || data.days || 180),
            hasMoreRecent: Boolean(data.has_more_recent),
            limit: Number(data.limit || 50),
            message: data.message || "",
          });
        },
      },
      {
        key: "training_summary",
        label: "Training summary",
        path: "/api/training/summary?window=weekly&period=all",
        run: async () => setTrainingSummary(await trackedApiGet<TrainingSummaryResponse>({ key: "training_summary", label: "Training summary", path: "/api/training/summary?window=weekly&period=all", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug)),
      },
      {
        key: "training_summary_status",
        label: "Training summary status",
        path: "/api/training/summary/status",
        run: async () => setTrainingSummaryStatus(await trackedApiGet<TrainingSummaryStatusResponse>({ key: "training_summary_status", label: "Training summary status", path: "/api/training/summary/status", required: false }, SETTINGS_API_TIMEOUT_MS, recordStartupDebug)),
      },
      {
        key: "strength_trends",
        label: "Strength trends",
        path: strengthTrendPath(),
        run: async () => {
          const path = strengthTrendPath();
          const data = await trackedApiGet<StrengthTrendResponse>({ key: "strength_trends", label: "Strength trends", path, required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug);
          setStrengthTrends(data);
          const exerciseOptions = Array.isArray(data.exercise_options) ? data.exercise_options : [];
          setSelectedExercise((current) => current || data.selected_exercise || exerciseOptions[0] || "");
        },
      },
      {
        key: "hevy_sync_status",
        label: "Hevy sync status",
        path: "/api/training/sync/hevy/status",
        run: async () => setHevySync(await trackedApiGet<HevySyncStatus>({ key: "hevy_sync_status", label: "Hevy sync status", path: "/api/training/sync/hevy/status", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug)),
      },
      {
        key: "muscle_coverage",
        label: "Weekly muscle coverage",
        path: "/api/training/muscle-coverage",
        run: async () => setMuscleCoverage(await trackedApiGet<MuscleCoverageResponse>({ key: "muscle_coverage", label: "Weekly muscle coverage", path: "/api/training/muscle-coverage", required: false }, DEFAULT_API_TIMEOUT_MS, recordStartupDebug)),
      },
    ];

    const failures: string[] = [];
    for (const step of deferredSteps) {
      const started = performance.now();
      try {
        await step.run();
        console.info(`[startup] ${step.key} loaded in ${Math.round(performance.now() - started)} ms`);
      } catch (error) {
        const reason = error instanceof Error ? error.message : String(error);
        console.error(`[startup] deferred ${step.key} failed - backend ${publicApiBaseLabel()} - ${reason}`);
        failures.push(`${step.label}: ${reason}`);
      }
    }
    if (failures.length > 0) {
      setLoadFailures((current) => Array.from(new Set([...current, ...failures])));
    }
  }, [applySettingsData, recordStartupDebug, strengthTrendPath]);

  const refreshAll = useCallback(async (options?: { allowColdStartRetry?: boolean }) => {
    const maxAttempts = options?.allowColdStartRetry === false ? 1 : 2;
    setApiError(null);
    setLoadFailures([]);
    setSystemFailure(null);

    type GoalsResponse = {
      goals: Goals;
      targets: Targets;
      weight_feedback: WeightFeedback;
      lean_bulk_decision: LeanBulkDecision;
      adaptive_recommendation: AdaptiveNutritionRecommendation;
    };

    const steps: Array<{
      key: string;
      label: string;
      path: string;
      timeoutMs: number;
      required: boolean;
      run: () => Promise<void>;
    }> = [
      {
        key: "dashboard_core",
        label: "Dashboard",
        path: dashboardCorePath(),
        timeoutMs: STARTUP_API_TIMEOUT_MS,
        required: true,
        run: async () => {
          const path = dashboardCorePath();
          const dashboardData = await trackedApiGet<DashboardData>({ key: "dashboard_core", label: "Dashboard", path, required: true }, STARTUP_API_TIMEOUT_MS, recordStartupDebug);
          setDashboard(dashboardData);
          if (dashboardCoreFailed(dashboardData)) {
            const failedBlocks = dashboardCoreFailedBlocks(dashboardData);
            const reason = dashboardCoreFailureReason(dashboardData);
            recordStartupDebug({
              key: "dashboard_core_core_failure",
              label: "Dashboard core readiness",
              path,
              required: true,
              status: "error",
              httpStatus: 200,
              errorMessage: reason,
              responseText: JSON.stringify({
                ok: dashboardData.ok,
                core_ready: dashboardData.core_ready,
                dashboard_status: dashboardData.debug?.dashboard_status,
                required_blocks_failed: dashboardData.debug?.required_blocks_failed,
                errors: failedBlocks,
              }, null, 2).slice(0, 4000),
              backendLabel: publicApiBaseLabel(),
              timestamp: new Date().toISOString(),
            });
            throw new CoreSystemFailureError(dashboardData);
          }
        },
      },
      {
        key: "goals",
        label: "Goals & targets",
        path: "/api/goals",
        timeoutMs: STARTUP_API_TIMEOUT_MS,
        required: true,
        run: async () => {
          const goalsData = await trackedApiGet<GoalsResponse>({ key: "goals", label: "Goals & targets", path: "/api/goals", required: true }, STARTUP_API_TIMEOUT_MS, recordStartupDebug);
          setForms((state) => ({ ...state, goals: goalsData.goals }));
        },
      },
      {
        key: "settings",
        label: "Settings",
        path: "/api/settings",
        timeoutMs: SETTINGS_API_TIMEOUT_MS,
        required: false,
        run: async () => applySettingsData(await trackedApiGet<SettingsData>({ key: "settings", label: "Settings", path: "/api/settings", required: false }, SETTINGS_API_TIMEOUT_MS, recordStartupDebug)),
      },
    ];

    const runStartupStep = async (step: (typeof steps)[number]) => {
      const started = performance.now();
      console.info("[startup] starting", step.key);
      await step.run();
      console.info("[startup] finished", step.key);
      console.info(`[startup] ${step.key} loaded in ${Math.round(performance.now() - started)} ms`);
    };

    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      setLoadingMessage(attempt === 1 ? "Loading core dashboard..." : "Retrying core dashboard...");
      const results = await Promise.allSettled(steps.map(runStartupStep));

      const failures: string[] = [];
      const requiredFailures: string[] = [];
      const requiredReasons: string[] = [];
      const requiredFailureBlocks: DashboardDebugBlock[] = [];
      let coreFailureReport: SystemFailureReport | null = null;
      results.forEach((result, index) => {
        if (result.status === "rejected") {
          const step = steps[index];
          const reason = result.reason instanceof Error ? result.reason.message : String(result.reason);
          console.error(`[startup] attempt ${attempt}/${maxAttempts} ${step.key} failed - backend ${publicApiBaseLabel()} - ${reason}`);
          failures.push(`${step.label}: ${reason}`);
          if (step.required) {
            requiredFailures.push(step.label);
            requiredReasons.push(reason.toLowerCase());
            requiredFailureBlocks.push({
              block: step.key,
              name: step.key,
              status: classifyRequestDebugStatus(result.reason),
              error_type: result.reason instanceof Error ? result.reason.name : "StartupError",
              message: reason,
              endpoint: step.path,
            });
          }
          if (result.reason instanceof CoreSystemFailureError) {
            coreFailureReport = {
              dashboard: result.reason.dashboard,
              failedBlocks: dashboardCoreFailedBlocks(result.reason.dashboard),
              requiredBlocksFailed: result.reason.dashboard.debug?.required_blocks_failed ?? dashboardCoreFailedBlocks(result.reason.dashboard).map(dashboardBlockName),
              reason,
              timestamp: new Date().toISOString(),
            };
          }
        }
      });

      if (requiredFailures.length > 0) {
        const failureKind = classifyStartupFailure(requiredReasons);
        if (attempt < maxAttempts && isColdStartRetryable(failureKind)) {
          setApiError(null);
          setLoadFailures([]);
          setLoading(true);
          setLoadingMessage(
            failureKind === "timeout"
              ? "Core startup data was slow. Retrying in a few seconds."
              : "Reconnecting to core startup data in a few seconds.",
          );
          await sleep(COLD_START_RETRY_DELAY_MS);
          continue;
        }

        setLoadFailures(failures);
        if (coreFailureReport) {
          setSystemFailure(coreFailureReport);
          setApiError(null);
        } else if (failureKind === "auth") {
          scheduleLoginRedirect();
          setApiError(`Core data failed to load: ${requiredFailures.join(", ")}. ${startupFailureHint(failureKind)}`);
        } else {
          const reason = `Core data failed to load: ${requiredFailures.join(", ")}. ${startupFailureHint(failureKind)}`;
          setSystemFailure({
            dashboard: null,
            failedBlocks: requiredFailureBlocks,
            requiredBlocksFailed: requiredFailureBlocks.map(dashboardBlockName),
            reason,
            timestamp: new Date().toISOString(),
          });
          setApiError(null);
        }
      } else {
        setLoadFailures(failures);
        if (failures.length > 0) {
          setApiError(null);
        }
        window.setTimeout(() => {
          void loadDeferredData();
        }, 250);
      }
      setLoading(false);
      return;
    }
    setLoading(false);
  }, [applySettingsData, loadDeferredData, recordStartupDebug]);

  const refreshDashboardCoreOnly = useCallback(async (date = todayString()) => {
    const dashboardData = await apiGet<DashboardData>(dashboardCorePath(date), STARTUP_API_TIMEOUT_MS);
    setDashboard(dashboardData);
    return dashboardData;
  }, []);

  const refreshBodyMetricsOnly = useCallback(async () => {
    const data = await apiGet<{ items: BodyMetricEntry[]; canonical_items?: BodyMetricEntry[]; raw_items?: BodyMetricEntry[]; freshness?: BodyMetricFreshnessDebug }>("/api/body-metrics", DEFAULT_API_TIMEOUT_MS);
    setBodyMetrics(data.canonical_items ?? data.items);
    return data;
  }, []);

  const syncWeightNow = useCallback(async () => {
    setApiError(null);
    setMessage(null);
    try {
      const result = await apiSend<WithingsSyncResult>("/api/body-metrics/sync/withings", "POST", { days: 30 });
      if (result.status === "error") {
        throw new Error(result.message ?? "Withings weight sync failed.");
      }
      const [bodyData, updatedSettings] = await Promise.all([
        refreshBodyMetricsOnly(),
        apiGet<SettingsData>("/api/integrations/status?external_checks=false", SETTINGS_API_TIMEOUT_MS),
      ]);
      applySettingsData(updatedSettings);
      await refreshDashboardCoreOnly();
      const freshness = result.freshness ?? bodyData.freshness;
      const created = Number(result.created_measurements ?? result.imported_rows ?? 0);
      const updated = Number(result.updated_measurements ?? result.updated_rows ?? 0);
      const skipped = Number(result.skipped_rows ?? 0);
      const latestWeight = freshness?.latest_canonical_weight;
      const latestDate = freshness?.latest_canonical_date || result.latest_date || result.latest_measure_date || "";
      const latestText = latestWeight ? ` Latest canonical weight: ${formatWeight(latestWeight)}${latestDate ? ` on ${latestDate}` : ""}.` : "";
      setMessage(`Weight sync complete: ${created} imported, ${updated} updated, ${skipped} skipped.${latestText}`);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Withings weight sync failed.");
    }
  }, [applySettingsData, refreshBodyMetricsOnly, refreshDashboardCoreOnly]);

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

  const applyTodayFoodPayload = useCallback((payload: NutritionTodayResponse) => {
    const date = payload.date;
    setNutritionLogs((current) => {
      const otherDays = current.filter((entry) => entry.date !== date);
      return [...otherDays, ...payload.items];
    });
    setDashboard((current) => {
      if (!current || current.date !== date) return current;
      const targets = recordOrEmpty(current.targets);
      const totals = payload.totals;
      const metric = (value: number, target: unknown) => {
        const safeValue = Number(value) || 0;
        const safeTarget = finiteNumberOrNull(target);
        return {
          eaten: safeValue,
          target: safeTarget,
          left: safeTarget ? Math.max(safeTarget - safeValue, 0) : null,
          over: safeTarget ? Math.max(safeValue - safeTarget, 0) : null,
          percent: safeTarget ? Math.min(Math.max((safeValue / safeTarget) * 100, 0), 100) : 0,
        };
      };
      return {
        ...current,
        nutrition_today: {
          calories: Number(totals.calories) || 0,
          protein: Number(totals.protein) || 0,
          carbs: Number(totals.carbs) || 0,
          fat: Number(totals.fat) || 0,
        },
        food: {
          calories: metric(totals.calories, targets.target_calories),
          protein: metric(totals.protein, targets.protein_grams),
          carbs: metric(totals.carbs, targets.carb_grams),
          fat: metric(totals.fat, targets.fat_grams),
          has_targets: Boolean(finiteNumberOrNull(targets.target_calories) && finiteNumberOrNull(targets.protein_grams) && finiteNumberOrNull(targets.carb_grams) && finiteNumberOrNull(targets.fat_grams)),
          has_food_logged: Boolean((Number(totals.calories) || 0) > 0 || (Number(totals.protein) || 0) > 0 || (Number(totals.carbs) || 0) > 0 || (Number(totals.fat) || 0) > 0),
        },
      };
    });
  }, []);

  const refreshTodayFoodOnly = useCallback(async (date = forms.nutrition.date) => {
    const selectedDate = date || todayString();
    console.info("[food] refreshing today-only nutrition", selectedDate);
    const payload = await apiGet<NutritionTodayResponse>(`/api/nutrition/today?date=${encodeURIComponent(selectedDate)}`, SETTINGS_API_TIMEOUT_MS);
    applyTodayFoodPayload(payload);
    return payload;
  }, [applyTodayFoodPayload, forms.nutrition.date]);

  const refreshFoodShortcutsOnly = useCallback(async () => {
    setShortcutData(await apiGet<NutritionShortcutData>("/api/nutrition/shortcuts", SETTINGS_API_TIMEOUT_MS));
  }, []);

  const refreshNutritionLogsOnly = useCallback(async () => {
    const data = await apiGet<{ items: NutritionEntry[] }>("/api/nutrition/logs?days=90&limit=300", SETTINGS_API_TIMEOUT_MS);
    setNutritionLogs(data.items);
    return data;
  }, []);

  const updateQuickFoodStatus = useCallback((statusKey: string, update: (current: QuickFoodLogStatus) => QuickFoodLogStatus) => {
    setQuickFoodLogStatuses((current) => ({
      ...current,
      [statusKey]: update(current[statusKey] ?? { pending: 0, added: false, error: null }),
    }));
  }, []);

  const adjustDashboardFoodTotals = useCallback((date: string, entry: Pick<NutritionEntry, "calories" | "protein" | "carbs" | "fat">, direction: 1 | -1) => {
    setDashboard((current) => {
      if (!current || current.date !== date) return current;
      const targets = recordOrEmpty(current.targets);
      const currentNutrition = recordOrEmpty(current.nutrition_today);
      const totals = {
        calories: Math.max(0, (finiteNumberOrNull(currentNutrition.calories) ?? finiteNumberOrNull(current.food?.calories?.eaten) ?? 0) + ((finiteNumberOrNull(entry.calories) ?? 0) * direction)),
        protein: Math.max(0, (finiteNumberOrNull(currentNutrition.protein) ?? finiteNumberOrNull(current.food?.protein?.eaten) ?? 0) + ((finiteNumberOrNull(entry.protein) ?? 0) * direction)),
        carbs: Math.max(0, (finiteNumberOrNull(currentNutrition.carbs) ?? finiteNumberOrNull(current.food?.carbs?.eaten) ?? 0) + ((finiteNumberOrNull(entry.carbs) ?? 0) * direction)),
        fat: Math.max(0, (finiteNumberOrNull(currentNutrition.fat) ?? finiteNumberOrNull(current.food?.fat?.eaten) ?? 0) + ((finiteNumberOrNull(entry.fat) ?? 0) * direction)),
      };
      const metric = (value: number, target: unknown) => {
        const safeTarget = finiteNumberOrNull(target);
        return {
          eaten: value,
          target: safeTarget,
          left: safeTarget ? Math.max(safeTarget - value, 0) : null,
          over: safeTarget ? Math.max(value - safeTarget, 0) : null,
          percent: safeTarget ? Math.min(Math.max((value / safeTarget) * 100, 0), 100) : 0,
        };
      };
      return {
        ...current,
        nutrition_today: totals,
        food: {
          calories: metric(totals.calories, finiteNumberOrNull(targets.target_calories) ?? current.food?.calories?.target),
          protein: metric(totals.protein, finiteNumberOrNull(targets.protein_grams) ?? current.food?.protein?.target),
          carbs: metric(totals.carbs, finiteNumberOrNull(targets.carb_grams) ?? current.food?.carbs?.target),
          fat: metric(totals.fat, finiteNumberOrNull(targets.fat_grams) ?? current.food?.fat?.target),
          has_targets: Boolean(finiteNumberOrNull(targets.target_calories) ?? current.food?.has_targets),
          has_food_logged: Object.values(totals).some((value) => value > 0),
        },
      };
    });
  }, []);

  const addOptimisticFoodEntry = useCallback((entry: NutritionEntry) => {
    setNutritionLogs((current) => [...current, entry]);
    adjustDashboardFoodTotals(entry.date, entry, 1);
  }, [adjustDashboardFoodTotals]);

  const rollbackOptimisticFoodEntry = useCallback((entry: NutritionEntry) => {
    setNutritionLogs((current) => current.filter((item) => item.food_log_id !== entry.food_log_id));
    adjustDashboardFoodTotals(entry.date, entry, -1);
  }, [adjustDashboardFoodTotals]);

  const replaceOptimisticFoodEntry = useCallback((optimisticEntry: NutritionEntry, savedEntry: NutritionEntry) => {
    setNutritionLogs((current) => current.map((item) => item.food_log_id === optimisticEntry.food_log_id ? savedEntry : item));
    const delta = {
      calories: (finiteNumberOrNull(savedEntry.calories) ?? 0) - (finiteNumberOrNull(optimisticEntry.calories) ?? 0),
      protein: (finiteNumberOrNull(savedEntry.protein) ?? 0) - (finiteNumberOrNull(optimisticEntry.protein) ?? 0),
      carbs: (finiteNumberOrNull(savedEntry.carbs) ?? 0) - (finiteNumberOrNull(optimisticEntry.carbs) ?? 0),
      fat: (finiteNumberOrNull(savedEntry.fat) ?? 0) - (finiteNumberOrNull(optimisticEntry.fat) ?? 0),
    };
    adjustDashboardFoodTotals(savedEntry.date || optimisticEntry.date, delta, 1);
  }, [adjustDashboardFoodTotals]);

  const processQuickFoodQueue = useCallback(() => {
    if (quickFoodProcessingRef.current) return;
    quickFoodProcessingRef.current = true;
    void (async () => {
      const refreshDates = new Set<string>();
      let shouldRefreshShortcuts = false;
      while (quickFoodQueueRef.current.length) {
        const job = quickFoodQueueRef.current.shift();
        if (!job) continue;
        try {
          const savedEntry = await job.run();
          if (savedEntry) {
            replaceOptimisticFoodEntry(job.optimisticEntry, savedEntry);
          }
          updateQuickFoodStatus(job.statusKey, (current) => ({
            ...current,
            pending: Math.max(0, current.pending - 1),
            added: true,
            error: null,
          }));
          window.setTimeout(() => {
            updateQuickFoodStatus(job.statusKey, (current) => ({ ...current, added: false }));
          }, 1200);
          refreshDates.add(job.date);
          shouldRefreshShortcuts = shouldRefreshShortcuts || Boolean(job.refreshShortcuts);
          setMessage(`Added ${job.label}.`);
        } catch (error) {
          const messageText = error instanceof Error ? error.message : `Could not log ${job.label}.`;
          rollbackOptimisticFoodEntry(job.optimisticEntry);
          updateQuickFoodStatus(job.statusKey, (current) => ({
            ...current,
            pending: Math.max(0, current.pending - 1),
            added: false,
            error: messageText,
          }));
          setApiError(messageText);
        } finally {
          setQuickFoodPendingCount((count) => Math.max(0, count - 1));
        }
      }
      quickFoodProcessingRef.current = false;
      if (refreshDates.size) {
        void Promise.all([
          ...Array.from(refreshDates).map((date) => refreshTodayFoodOnly(date)),
          refreshNutritionLogsOnly(),
          shouldRefreshShortcuts ? refreshFoodShortcutsOnly() : Promise.resolve(),
          ...Array.from(refreshDates).map((date) => refreshDashboardCoreOnly(date).catch((error) => {
            console.warn("[dashboard] refresh after quick food queue failed", error);
          })),
        ]).catch((error) => {
          console.warn("[food] quick log settle refresh failed", error);
        });
      }
      if (quickFoodQueueRef.current.length) {
        quickFoodProcessRef.current();
      }
    })();
  }, [
    refreshDashboardCoreOnly,
    refreshFoodShortcutsOnly,
    refreshNutritionLogsOnly,
    refreshTodayFoodOnly,
    replaceOptimisticFoodEntry,
    rollbackOptimisticFoodEntry,
    updateQuickFoodStatus,
  ]);

  useEffect(() => {
    quickFoodProcessRef.current = processQuickFoodQueue;
  }, [processQuickFoodQueue]);

  const queueQuickFoodLog = useCallback((job: Omit<QuickFoodLogJob, "id"> & { dedupeKey: string }) => {
    const now = Date.now();
    const lastClickAt = quickFoodLastClickRef.current[job.dedupeKey] ?? 0;
    if (now - lastClickAt < 300) {
      return;
    }
    quickFoodLastClickRef.current[job.dedupeKey] = now;
    const queuedJob: QuickFoodLogJob = {
      ...job,
      id: `quick-food:${now}:${Math.random().toString(36).slice(2)}`,
    };
    setMessage(null);
    setApiError(null);
    addOptimisticFoodEntry(queuedJob.optimisticEntry);
    updateQuickFoodStatus(queuedJob.statusKey, (current) => ({
      ...current,
      pending: current.pending + 1,
      added: false,
      error: null,
    }));
    setQuickFoodPendingCount((count) => count + 1);
    quickFoodQueueRef.current.push(queuedJob);
    processQuickFoodQueue();
  }, [addOptimisticFoodEntry, processQuickFoodQueue, updateQuickFoodStatus]);

  const submitFoodAndRefreshToday = useCallback(async (
    event: FormEvent,
    action: () => Promise<void>,
    success: string,
    date = forms.nutrition.date,
    afterRefresh?: (payload: NutritionTodayResponse) => void,
    onFailure?: (message: string) => void,
  ) => {
    event.preventDefault();
    setMessage(null);
    setApiError(null);
    try {
      await action();
      const payload = await refreshTodayFoodOnly(date);
      afterRefresh?.(payload);
      refreshDashboardCoreOnly(date).catch((error) => {
        console.warn("[dashboard] refresh after food update failed", error);
      });
      setMessage(success);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Food update failed.";
      onFailure?.(message);
      setApiError(message);
    }
  }, [forms.nutrition.date, refreshDashboardCoreOnly, refreshTodayFoodOnly]);

  const submitWithoutRefresh = useCallback(async (event: FormEvent, action: () => Promise<void>, success: string) => {
    event.preventDefault();
    setMessage(null);
    setApiError(null);
    try {
      await action();
      setMessage(success);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Action failed.");
    }
  }, []);

  const refreshWorkoutMarkersOnly = useCallback(async () => {
    const data = await apiGet<{ items: WorkoutMarker[] }>("/api/workout-markers", SETTINGS_API_TIMEOUT_MS);
    setWorkoutMarkers(Array.isArray(data.items) ? data.items : []);
    return data;
  }, []);

  const refreshWearablesOnly = useCallback(async () => {
    const [metrics, signals, readiness] = await Promise.all([
      apiGet<{ items: WearableMetricEntry[] }>("/api/wearables/metrics", SETTINGS_API_TIMEOUT_MS),
      apiGet<WearableSignals>("/api/wearables/signals", SETTINGS_API_TIMEOUT_MS),
      apiGet<TrainingReadinessSignals>("/api/wearables/training-readiness", SETTINGS_API_TIMEOUT_MS),
    ]);
    setWearableMetrics(Array.isArray(metrics.items) ? metrics.items : []);
    setWearableSignals(signals);
    setTrainingReadiness(readiness);
    return { metrics, signals, readiness };
  }, []);

  const refreshMuscleCoverageOnly = useCallback(async () => {
    const data = await apiGet<MuscleCoverageResponse>("/api/training/muscle-coverage", SETTINGS_API_TIMEOUT_MS);
    setMuscleCoverage({ ...data, items: Array.isArray(data.items) ? data.items : [] });
    return data;
  }, []);

  const submitWorkoutMarker = useCallback((event: FormEvent) => {
    void submitWithoutRefresh(event, async () => {
      const marker = {
        ...forms.workoutMarker,
        date: forms.nutrition.date || forms.workoutMarker.date || todayString(),
        workout_time: forms.workoutMarker.workout_time || "",
        workout_type: forms.workoutMarker.workout_type || "Strength",
      };
      const result = await apiSend<{ item?: WorkoutMarker; items?: WorkoutMarker[]; status?: string; message?: string }>("/api/workout-markers", "POST", marker);
      if (result.status === "error") {
        throw new Error(result.message || "Workout marker could not be saved.");
      }
      setWorkoutMarkers(Array.isArray(result.items) ? result.items : result.item ? [result.item, ...workoutMarkers] : workoutMarkers);
      setForms((state) => ({
        ...state,
        workoutMarker: {
          date: todayString(),
          workout_time: "",
          workout_type: "Strength",
          notes: "",
        },
      }));
      await Promise.all([
        refreshWorkoutMarkersOnly().catch(() => undefined),
        apiGet<TrainingReadinessSignals>("/api/wearables/training-readiness", SETTINGS_API_TIMEOUT_MS).then(setTrainingReadiness).catch(() => undefined),
      ]);
    }, "Workout marker saved.");
  }, [forms.nutrition.date, forms.workoutMarker, refreshWorkoutMarkersOnly, submitWithoutRefresh, workoutMarkers]);

  const submitWearableMetric = useCallback((event: FormEvent) => {
    void submitWithoutRefresh(event, async () => {
      const payload = Object.fromEntries(
        Object.entries(forms.wearable).map(([key, value]) => [
          key,
          value === "" ? null : value,
        ]),
      );
      const result = await apiSend<{ item?: WearableMetricEntry; items?: WearableMetricEntry[]; status?: string; message?: string }>("/api/wearables/metrics", "POST", payload);
      if (result.status === "error") {
        throw new Error(result.message || "Wearable metric could not be saved.");
      }
      if (Array.isArray(result.items)) {
        setWearableMetrics(result.items);
      }
      setForms((state) => ({
        ...state,
        wearable: {
          ...state.wearable,
          date: todayString(),
          sleep_hours: "",
          sleep_score: "",
          resting_hr: "",
          hrv: "",
          steps: "",
          active_minutes: "",
          calories_burned: "",
        },
      }));
      await refreshWearablesOnly();
    }, "Wearable metric saved.");
  }, [forms.wearable, refreshWearablesOnly, submitWithoutRefresh]);

  const moveWorkoutDate = useCallback(async (workoutId: string, newDate: string) => {
    setMessage(null);
    setApiError(null);
    try {
      const result = await apiSend<{ status?: string; message?: string; old_date?: string; new_date?: string; updated_rows?: number }>(
        "/api/training/workout-date",
        "POST",
        { workout_id: workoutId, new_date: newDate },
      );
      if (result.status && result.status !== "ok") {
        throw new Error(result.message || "Could not move the workout.");
      }
      if (typeof result.updated_rows === "number" && result.updated_rows <= 0) {
        throw new Error("No workout rows were updated.");
      }
      setMessage(`Workout moved to ${result.new_date ?? newDate}. Analytics refreshed.`);
      await refreshAll();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not move the workout.";
      setApiError(message);
      throw new Error(message);
    }
  }, [refreshAll]);

  const excludeNutritionDay = useCallback(async (date: string) => {
    const selectedDate = String(date || "").slice(0, 10);
    if (!selectedDate) return;
    setMessage(null);
    setApiError(null);
    try {
      const result = await apiSend<{ status?: string; message?: string; date?: string; updated_rows?: number }>(
        `/api/nutrition/history/${encodeURIComponent(selectedDate)}/exclude`,
        "POST",
        {},
      );
      if (result.status && result.status !== "ok") {
        throw new Error(result.message || "Could not exclude nutrition day.");
      }
      setMessage(`Nutrition day ${result.date ?? selectedDate} excluded from analytics.`);
      await refreshAll();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not exclude nutrition day.";
      setApiError(message);
      throw new Error(message);
    }
  }, [refreshAll]);

  const updateSelectedExercise = (exercise: string) => {
    setSelectedExercise(exercise);
    void apiGet<StrengthTrendResponse>(strengthTrendPath(exercise))
      .then(setStrengthTrends)
      .catch((error) => setApiError(error instanceof Error ? error.message : "Unable to load strength trend."));
  };

  const loadTrainingPrs = useCallback(async (refresh = false) => {
    await Promise.resolve();
    setTrainingPrsLoading(true);
    try {
      const path = `/api/training/prs?limit=50${refresh ? "&refresh=true" : ""}`;
      const data = await apiGet<TrainingPrResponse>(path, DEFAULT_API_TIMEOUT_MS);
      setTrainingPrs({
        ...data,
        items: Array.isArray(data.items) ? data.items : [],
        diagnostics: recordOrEmpty(data.diagnostics),
      });
    } catch (error) {
      setTrainingPrs({
        status: "error",
        items: [],
        source: "error",
        message: error instanceof Error ? error.message : "Unable to load exercise PRs.",
        diagnostics: {
          source_reason: error instanceof Error ? error.message : "Unable to load exercise PRs.",
        },
      });
    } finally {
      setTrainingPrsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activePage === "goals" && !trainingPrs && !trainingPrsLoading) {
      const timer = window.setTimeout(() => {
        void loadTrainingPrs(false);
      }, 0);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [activePage, loadTrainingPrs, trainingPrs, trainingPrsLoading]);

  const refreshTrainingData = useCallback(async (showErrors = false, nextLimit = 50) => {
    const failures: string[] = [];
    const historyPath = `/api/training/history?limit=${nextLimit}&days=${trainingHistoryMeta.rawWindowDays || 180}`;
    const [history, status, trends, summary, summaryStatus, coverage] = await Promise.allSettled([
      apiGet<TrainingHistoryResponse>(historyPath, DEFAULT_API_TIMEOUT_MS),
      apiGet<HevySyncStatus>("/api/training/sync/hevy/status", SETTINGS_API_TIMEOUT_MS),
      apiGet<StrengthTrendResponse>(strengthTrendPath(), DEFAULT_API_TIMEOUT_MS),
      apiGet<TrainingSummaryResponse>("/api/training/summary?window=weekly&period=all", DEFAULT_API_TIMEOUT_MS),
      apiGet<TrainingSummaryStatusResponse>("/api/training/summary/status", SETTINGS_API_TIMEOUT_MS),
      refreshMuscleCoverageOnly(),
    ]) as [PromiseSettledResult<TrainingHistoryResponse>, PromiseSettledResult<HevySyncStatus>, PromiseSettledResult<StrengthTrendResponse>, PromiseSettledResult<TrainingSummaryResponse>, PromiseSettledResult<TrainingSummaryStatusResponse>, PromiseSettledResult<MuscleCoverageResponse>];
    let historyDebug: TrainingHistoryResponse["debug"] | undefined;
    if (history.status === "fulfilled") {
      setWorkoutHistory(history.value.items);
      setTrainingHistoryMeta({
        rawWindowDays: Number(history.value.raw_window_days || history.value.days || trainingHistoryMeta.rawWindowDays || 180),
        hasMoreRecent: Boolean(history.value.has_more_recent),
        limit: Number(history.value.limit || nextLimit),
        message: history.value.message || "",
      });
      historyDebug = history.value.debug;
    } else {
      failures.push(history.reason instanceof Error ? history.reason.message : "Training history failed.");
    }
    if (status.status === "fulfilled") {
      setHevySync((current) => ({
        ...status.value,
        hevy_rows: status.value.hevy_rows ?? historyDebug?.hevy_rows ?? current?.hevy_rows,
        hevy_workouts: status.value.hevy_workouts ?? historyDebug?.hevy_workouts ?? current?.hevy_workouts,
        latest_workout_date: status.value.latest_workout_date ?? historyDebug?.latest_workout_date ?? current?.latest_workout_date,
        latest_workout_title: status.value.latest_workout_title ?? historyDebug?.latest_workout_title ?? current?.latest_workout_title,
      }));
    } else {
      failures.push(status.reason instanceof Error ? status.reason.message : "Hevy status failed.");
    }
    if (trends.status === "fulfilled") {
      setStrengthTrends(trends.value);
      const exerciseOptions = Array.isArray(trends.value.exercise_options) ? trends.value.exercise_options : [];
      setSelectedExercise((current) => current || trends.value.selected_exercise || exerciseOptions[0] || "");
    } else {
      failures.push(trends.reason instanceof Error ? trends.reason.message : "Strength trends failed.");
    }
    if (summary.status === "fulfilled") {
      setTrainingSummary(summary.value);
    } else {
      failures.push(summary.reason instanceof Error ? summary.reason.message : "Training summary failed.");
    }
    if (summaryStatus.status === "fulfilled") {
      setTrainingSummaryStatus(summaryStatus.value);
    } else {
      failures.push(summaryStatus.reason instanceof Error ? summaryStatus.reason.message : "Training summary status failed.");
    }
    if (coverage.status === "rejected") {
      failures.push(coverage.reason instanceof Error ? coverage.reason.message : "Weekly muscle coverage failed.");
    }
    if (showErrors && failures.length) {
      setApiError(`Training refresh failed: ${failures.join(" ")}`);
    }
  }, [refreshMuscleCoverageOnly, strengthTrendPath, trainingHistoryMeta.rawWindowDays]);

  useEffect(() => {
    if (activePage !== "training") return;
    const timeout = window.setTimeout(() => {
      void refreshTrainingData(false);
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [activePage, refreshTrainingData]);

  const loadMoreTrainingHistory = useCallback(() => {
    const nextLimit = trainingHistoryMeta.limit + 50;
    void refreshTrainingData(true, nextLimit);
  }, [refreshTrainingData, trainingHistoryMeta.limit]);

  const refreshTrainingSummaryStatus = useCallback(async () => {
    const [summary, status] = await Promise.all([
      apiGet<TrainingSummaryResponse>("/api/training/summary?window=weekly&period=all", DEFAULT_API_TIMEOUT_MS),
      apiGet<TrainingSummaryStatusResponse>("/api/training/summary/status", SETTINGS_API_TIMEOUT_MS),
    ]);
    setTrainingSummary(summary);
    setTrainingSummaryStatus(status);
  }, []);

  const exportRawHevyData = useCallback(async () => {
    setTrainingDataAction("exporting");
    setApiError(null);
    setMessage(null);
    try {
      const response = await fetch(apiUrl("/api/training/export/hevy-raw"), {
        cache: "no-store",
        credentials: "include",
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Raw Hevy export failed (${response.status}).`);
      }
      const blob = await response.blob();
      const objectUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = csvFilenameFromDisposition(response.headers.get("Content-Disposition"));
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(objectUrl);
      setMessage("Raw Hevy data exported.");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Raw Hevy export failed.");
    } finally {
      setTrainingDataAction("idle");
    }
  }, []);

  const exportNormalizedTrainingData = useCallback(async () => {
    setTrainingDataAction("exporting");
    setApiError(null);
    setMessage(null);
    try {
      const response = await fetch(apiUrl("/api/training/export/normalized"), {
        cache: "no-store",
        credentials: "include",
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Normalized training export failed (${response.status}).`);
      }
      const blob = await response.blob();
      const objectUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = csvFilenameFromDisposition(response.headers.get("Content-Disposition"));
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(objectUrl);
      setMessage("Normalized training data exported.");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Normalized training export failed.");
    } finally {
      setTrainingDataAction("idle");
    }
  }, []);

  const rebuildTrainingSummaries = useCallback(async () => {
    setTrainingDataAction("rebuilding");
    setApiError(null);
    setMessage(null);
    try {
      const result = await apiSend<{ raw_rows_summarized?: number; weekly_summaries?: number; monthly_summaries?: number }>("/api/training/consolidate-history", "POST", {});
      await Promise.all([refreshTrainingSummaryStatus(), refreshDashboardCoreOnly()]);
      setMessage(`Training summaries rebuilt: ${(result.raw_rows_summarized ?? 0).toLocaleString()} older rows summarized.`);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Training summary rebuild failed.");
    } finally {
      setTrainingDataAction("idle");
    }
  }, [refreshDashboardCoreOnly, refreshTrainingSummaryStatus]);

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
        status: result.status,
        configured: true,
        last_synced_at: result.last_synced_at,
        last_error: result.status === "error" ? result.failures?.join(" ") ?? result.message ?? "Hevy sync failed." : "",
        last_result: result as unknown as Record<string, unknown>,
        hevy_rows: result.hevy_rows,
        hevy_workouts: result.hevy_workouts,
        latest_workout_date: result.latest_workout_date,
        latest_workout_title: result.latest_workout_title,
      });
      await refreshTrainingData(true);
      await refreshTrainingSummaryStatus();
      await refreshDashboardCoreOnly();
      if (showMessage) {
        const failureText = result.failures?.length ? ` ${result.failures.length} failures.` : "";
        const changeText = `${result.new_workouts ?? 0} new, ${result.updated_workouts ?? 0} updated`;
        const importText = result.fallback_recent_import && result.imported_rows !== undefined ? `, ${result.imported_rows} fallback rows imported` : "";
        setMessage(`Hevy checked: ${result.events} events, ${changeText}${importText}, ${result.deleted_rows} rows deleted.${failureText}`);
      }
    } catch (error) {
      const messageText = error instanceof Error ? error.message : "Hevy sync failed.";
      setApiError(messageText);
      setHevySync((state) => ({
        status: "error",
        configured: state?.configured,
        last_synced_at: state?.last_synced_at ?? "",
        last_error: messageText,
        last_result: state?.last_result ?? {},
        hevy_rows: state?.hevy_rows,
        hevy_workouts: state?.hevy_workouts,
        latest_workout_date: state?.latest_workout_date,
        latest_workout_title: state?.latest_workout_title,
      }));
    } finally {
      setHevySyncing(false);
    }
  }, [refreshDashboardCoreOnly, refreshTrainingData, refreshTrainingSummaryStatus]);

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
    if (entry.fiber !== null && entry.fiber !== undefined) {
      const fiber = Number(entry.fiber);
      if (!Number.isFinite(fiber) || fiber < 0) {
        return "fiber must be a number greater than or equal to 0.";
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

  const updateFoodAiFlowStep = (step: string, status: FoodAiFlowStep["status"], message: string) => {
    setFoodAiFlow((items) => [...items.filter((item) => item.step !== step), { step, status, message }]);
  };

  const updateFoodAiDebug = (patch: FoodAiDebugState) => {
    setFoodAiDebug((current) => ({
      ...(current ?? {}),
      ...patch,
      updatedAt: new Date().toISOString(),
    }));
  };

  const draftFromAnalyzeItem = (item: FoodAnalyzeItem): ParsedFood => ({
    food_name: item.display_name || item.name,
    display_name: item.display_name || item.name,
    normalized_name: item.normalized_name,
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
    confidence_score: typeof item.confidence_score === "number" ? item.confidence_score : null,
    source: item.source,
    source_id: item.source_id,
    source_url: item.source_url ?? "",
    assumptions: item.assumptions,
    needs_review: Boolean(item.needs_review || item.needs_confirmation),
    needs_confirmation: Boolean(item.needs_review || item.needs_confirmation),
    verification_needed: Boolean(item.needs_review || item.needs_confirmation),
    verification_reason: item.assumptions.join(" "),
    verification_status: item.needs_review || item.needs_confirmation ? "review_required" : "ready",
    notes: item.assumptions.join(" ") || "Review before saving.",
  });

  const draftFromSavedFoodMatch = (match: Extract<SavedFoodMatch, { type: "shortcut" | "frequent" }>): ParsedFood => {
    const isShortcut = match.type === "shortcut";
    const item = match.item;
    const shortcutItem = isShortcut ? item as FoodShortcut | PresetFoodShortcut : null;
    const frequentItem = !isShortcut ? item as NutritionShortcutData["frequent_foods"][number] : null;
    const name = shortcutItem?.shortcut_name ?? frequentItem?.food_name ?? match.label;
    const sourceId = shortcutItem?.shortcut_id ?? frequentItem?.food_name ?? match.id;
    return {
      food_name: name,
      display_name: name,
      normalized_name: normalizeSearchText(name).replaceAll(" ", "_"),
      original_text: aiText.trim() || name,
      quantity: "1",
      quantity_value: 1,
      unit: "serving",
      serving_description: "1 saved serving",
      calories: Number(item.calories) || 0,
      protein: Number(item.protein) || 0,
      carbs: Number(item.carbs) || 0,
      fat: Number(item.fat) || 0,
      fiber: "fiber" in item ? item.fiber ?? null : null,
      sugar: null,
      sodium: "sodium" in item ? item.sodium ?? null : null,
      confidence: "high",
      confidence_score: 1,
      source: match.type === "shortcut" ? "saved_shortcut" : "existing_database",
      source_id: sourceId,
      source_url: "",
      assumptions: [`Matched ${match.type === "shortcut" ? "saved shortcut" : "frequent food"}: ${name}`],
      needs_review: false,
      needs_confirmation: false,
      verification_needed: false,
      verification_reason: "Exact stored macros were used before AI parsing.",
      verification_status: "ready",
      notes: match.type === "shortcut" && "notes" in item && item.notes ? item.notes : "Exact stored macros were used.",
    };
  };

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

  const parsedFoodsLogPayload = () => ({
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

  const saveParsedFoodsToToday = async (payload = parsedFoodsLogPayload()) => {
    if (!parsedFoods.length) {
      throw new Error("No parsed food items are available to save. Run Analyze first.");
    }
    const response = await apiSend<FoodBulkLogResponse>("/api/food/log-bulk", "POST", payload);
    if (response.status !== "ok") {
      throw new Error(response.message || "Food save failed.");
    }
    if (response.created !== parsedFoods.length) {
      throw new Error(`Food save mismatch: backend saved ${response.created} of ${parsedFoods.length} parsed item(s).`);
    }
    return response;
  };

  const pageContent = {
    dashboard: (
      <TargetSectionErrorBoundary title="Dashboard unavailable" description="Insufficient dashboard target or recommendation data." resetKey={`${dashboard?.date ?? ""}-${dashboard?.targets?.target_calories ?? ""}`}>
        <Dashboard
          data={dashboard}
          setActivePage={setActivePage}
        />
      </TargetSectionErrorBoundary>
    ),
    food: (
      <FoodPage
        logs={nutritionLogs}
        targets={dashboard?.targets ?? null}
        dayTypeMacros={dashboard?.optimization?.day_type_macros ?? null}
        adaptiveRecommendation={dashboard?.adaptive_recommendation ?? null}
        onApplySuggestedMacros={() =>
          void submitAndRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            await apiSend("/api/goals/apply-suggested-macros", "POST", {});
          }, "Suggested macros applied.")
        }
        onRunNutritionEngine={() =>
          void submitWithoutRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            const selectedDate = forms.nutrition.date || todayString();
            const result = await apiSend<RecommendationRunResponse>(
              `/api/recommendations/run?date=${encodeURIComponent(selectedDate)}&finalize_day=true`,
              "POST",
              {},
            );
            if (result.dashboard) {
              setDashboard(result.dashboard);
            }
            const history = await apiGet<{ items: DailyNutritionSummary[]; adherence: NutritionAdherence }>("/api/nutrition/history", SETTINGS_API_TIMEOUT_MS);
            setNutritionHistory(history.items);
            setNutritionAdherence(history.adherence);
            await refreshTodayFoodOnly(selectedDate);
          }, "Daily nutrition summary finalized and recommendations refreshed.")
        }
        nutritionHistory={nutritionHistory}
        nutritionAdherence={nutritionAdherence}
        shortcuts={shortcutData.items}
        frequentFoods={shortcutData.frequent_foods}
        mealTemplates={shortcutData.meal_templates}
        workoutMarkers={workoutMarkers}
        forms={forms}
        setForms={setForms}
        onWorkoutMarkerSubmit={submitWorkoutMarker}
        manualCaloriesOverridden={manualCaloriesOverridden}
        setManualCaloriesOverridden={setManualCaloriesOverridden}
        manualFoodMode={manualFoodMode}
        setManualFoodMode={setManualFoodMode}
        servingForm={servingForm}
        setServingForm={setServingForm}
        servingPreview={calculateServingPreview(servingForm)}
        labelUploadResult={labelUploadResult}
        onLabelUpload={(file) => {
          void submitWithoutRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            const formData = new FormData();
            formData.append("file", file);
            const result = await apiUpload<LabelUploadResult>("/api/nutrition/label-upload", formData);
            setLabelUploadResult(result);
            setServingForm((state) => ({ ...state, source_label_file: result.path }));
          }, "Nutrition label uploaded.")
        }}
        onSaveServingShortcut={() =>
          void submitWithoutRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
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
            await refreshFoodShortcutsOnly();
          }, "Serving-scaled food saved as shortcut.")
        }
        aiText={aiText}
        setAiText={setAiText}
        parsedFoods={parsedFoods}
        setParsedFoods={setParsedFoods}
        parseLoading={parseLoading}
        parseResult={parseResult}
        foodAiFlow={foodAiFlow}
        foodAiDebug={foodAiDebug}
        manualSaving={manualFoodSaving}
        manualError={manualFoodError}
        aiParsingConfigured={Boolean(settings?.services?.openai?.configured ?? (settings?.statuses.openai_api_key === "Configured" || settings?.statuses.openai_api_key === "Connected"))}
        quickFoodLogStatuses={quickFoodLogStatuses}
        quickFoodPendingCount={quickFoodPendingCount}
        shortcutSuggestion={shortcutSuggestion}
        onUseSuggestion={() => {
          if (!shortcutSuggestion) return;
          void submitFoodAndRefreshToday({ preventDefault: () => undefined } as FormEvent, async () => {
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
          submitWithoutRefresh(event, async () => {
            const parseStarted = performance.now();
            setFoodAiFlow([]);
            setFoodAiDebug(null);
            setParseResult(null);
            setParsedFoods([]);
            updateFoodAiFlowStep("Input", "pending", "Checking text and saved-food matches.");
            try {
              const cleanedText = aiText.trim();
              if (!cleanedText) {
                throw new Error("Enter food text before analyzing.");
              }
              if (cleanedText.length > 4000) {
                throw new Error("Food text must be 4,000 characters or fewer.");
              }
              updateFoodAiFlowStep("Input", "ok", `${cleanedText.length} character(s) ready for analysis.`);
              updateFoodAiDebug({
                endpoint_called: "/api/food/analyze-text",
                request_body_received: { date: forms.nutrition.date, text: cleanedText, force_openai: forceAiParse },
                frontend_received_items: false,
                log_insert_attempted: false,
                log_insert_success: false,
                analyzeEndpoint: "/api/food/analyze-text",
                analyzeRequestBody: { date: forms.nutrition.date, text: cleanedText, force_openai: forceAiParse },
                analyzeResponseStatus: "pending",
                parsedItemCount: 0,
              });
              const shortcutCandidates = [...shortcutData.items, ...DEFAULT_PRESET_FOODS];
              const savedMatch = findSavedFoodMatch(cleanedText, shortcutCandidates, shortcutData.meal_templates, shortcutData.frequent_foods);
              if (savedMatch && !forceAiParse) {
                if (savedMatch.type === "shortcut" || savedMatch.type === "frequent") {
                  const drafts = [draftFromSavedFoodMatch(savedMatch)];
                  setForceAiParse(false);
                  setShortcutSuggestion(null);
                  setParsedFoods(drafts);
                  setParseResult({
                    foods: drafts,
                    total: {
                      calories: drafts.reduce((sum, food) => sum + (Number(food.calories) || 0), 0),
                      protein: drafts.reduce((sum, food) => sum + (Number(food.protein) || 0), 0),
                      carbs: drafts.reduce((sum, food) => sum + (Number(food.carbs) || 0), 0),
                      fat: drafts.reduce((sum, food) => sum + (Number(food.fat) || 0), 0),
                    },
                    source: "saved_shortcut",
                    cached: true,
                    success: true,
                    error_code: null,
                    message: "Matched exact stored macros. Review before saving.",
                    parser: {
                      default_model_used: false,
                      escalated: false,
                      final_model: "saved_shortcut",
                      model_used: "saved_shortcut",
                      estimated_input_tokens: 0,
                      estimated_output_tokens: 0,
                      estimated_cost_usd: 0,
                    },
                    debug: {
                      backend_endpoint_reached: false,
                      openai_called: false,
                      parser_source: "saved_shortcut",
                      parser_cached: true,
                      final_model: "saved_shortcut",
                      estimated_input_tokens: 0,
                      estimated_output_tokens: 0,
                      estimated_cost_usd: 0,
                    },
                  });
                  updateFoodAiDebug({
                    analyzeResponseStatus: "ok",
                    analyzeResponseMs: Math.round(performance.now() - parseStarted),
                    openai_called: false,
                    model_used: "saved_shortcut",
                    parser_source: "saved_shortcut",
                    external_lookup_status: "skipped",
                    raw_items_count: drafts.length,
                    normalized_items_count: drafts.length,
                    response_shape: { has_items: true, has_foods: true, has_totals: true, has_total: true, status: "ok" },
                    frontend_received_items: true,
                    parsedItemCount: drafts.length,
                    default_model_used: false,
                    escalated: false,
                    final_model: "saved_shortcut",
                    estimated_input_tokens: 0,
                    estimated_output_tokens: 0,
                    estimated_cost_usd: 0,
                  });
                  updateFoodAiFlowStep("Saved match", "ok", `${savedMatch.label} matched exact stored macros.`);
                  updateFoodAiFlowStep("Review", "ok", "Saved-food draft is visible below. Review it, then click Save to today.");
                  return;
                }
                setShortcutSuggestion(savedMatch);
                updateFoodAiDebug({ exactError: "Saved meal template matched before AI parsing. Use it or choose Parse new anyway." });
                updateFoodAiFlowStep("Saved match", "pending", `${savedMatch.label} matched locally. Use it or choose Parse new anyway.`);
                throw new Error("Saved meal template found. Use it or choose Parse new anyway.");
              }
              updateFoodAiFlowStep("Saved match", "ok", forceAiParse ? "Bypassing saved match and parsing new food." : "No saved shortcut blocked the parser.");
              setForceAiParse(false);
              setShortcutSuggestion(null);
              setParseLoading(true);
              updateFoodAiFlowStep("Request", "pending", "POST /api/food/analyze-text");
              const analyzed = await apiSend<FoodAnalyzeResponse>("/api/food/analyze-text", "POST", { date: forms.nutrition.date, text: cleanedText, force_openai: forceAiParse });
              updateFoodAiFlowStep("Request", "ok", `/api/food/analyze-text responded in ${Math.round(performance.now() - parseStarted)}ms.`);
              const analyzedItems = Array.isArray(analyzed.items) ? analyzed.items : Array.isArray(analyzed.foods) ? analyzed.foods : [];
              updateFoodAiDebug({
                analyzeResponseStatus: analyzed.status || (analyzed.success ? "ok" : "error"),
                analyzeResponseMs: Math.round(performance.now() - parseStarted),
                openai_called: Boolean(analyzed.steps?.openai_called ?? analyzed.debug?.openai_called),
                model_used: String(analyzed.steps?.model_used || analyzed.parser?.final_model || analyzed.debug?.final_model || analyzed.debug?.model || "unknown"),
                parser_source: String(analyzed.parser_source || analyzed.debug?.parser_source || analyzed.source || "unknown"),
                external_lookup_status: String(analyzed.external_lookup_status || analyzed.debug?.external_lookup_status || "unknown"),
                raw_items_count: Number(analyzed.steps?.raw_items_count ?? analyzedItems.length),
                normalized_items_count: analyzedItems.length,
                default_model_used: Boolean(analyzed.steps?.default_model_used ?? analyzed.parser?.default_model_used),
                escalated: Boolean(analyzed.steps?.escalated ?? analyzed.parser?.escalated ?? analyzed.debug?.escalated),
                escalation_reason: String(analyzed.steps?.escalation_reason || analyzed.parser?.escalation_reason || analyzed.debug?.escalation_reason || ""),
                final_model: String(analyzed.steps?.model_used || analyzed.parser?.final_model || analyzed.debug?.final_model || ""),
                estimated_input_tokens: Number(analyzed.steps?.estimated_input_tokens ?? analyzed.parser?.estimated_input_tokens ?? analyzed.debug?.estimated_input_tokens ?? 0),
                estimated_output_tokens: Number(analyzed.steps?.estimated_output_tokens ?? analyzed.parser?.estimated_output_tokens ?? analyzed.debug?.estimated_output_tokens ?? 0),
                estimated_cost_usd: Number(analyzed.steps?.estimated_cost_usd ?? analyzed.parser?.estimated_cost_usd ?? analyzed.debug?.estimated_cost_usd ?? 0),
                response_shape: {
                  has_items: Array.isArray(analyzed.items),
                  has_foods: Array.isArray(analyzed.foods),
                  has_totals: Boolean(analyzed.totals),
                  has_total: Boolean(analyzed.total),
                  status: analyzed.status || (analyzed.success ? "ok" : "error"),
                },
                frontend_received_items: analyzedItems.length > 0,
                parsedItemCount: analyzedItems.length,
                exactError: analyzed.success ? undefined : (analyzed.message || analyzed.error_code || "Food analysis failed."),
              });
              if (!Array.isArray(analyzed.items) && !Array.isArray(analyzed.foods)) {
                throw new Error("Food analysis response did not include an items or foods array.");
              }
              const drafts = analyzedItems.map(draftFromAnalyzeItem);
              const failedStep = analyzed.debug?.failed_step || analyzed.debug?.parsing_status || "parse";
              const backendMessage = analyzed.message || analyzed.debug?.message || analyzed.error_code || "Food analysis failed.";
              const totals = analyzed.totals ?? analyzed.total ?? { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: null, sugar_g: null, sodium_mg: null };
              updateFoodAiFlowStep("Parse result", analyzed.success && drafts.length ? "ok" : "error", `${drafts.length} parsed item(s). ${analyzed.error_code ? `Error code: ${analyzed.error_code}. ` : ""}${backendMessage}`);
              setParseResult({
                foods: drafts,
                total: {
                  calories: totals.calories,
                  protein: totals.protein_g,
                  carbs: totals.carbs_g,
                  fat: totals.fat_g,
                },
                source: "food_analyze_text",
                cached: false,
                success: analyzed.success,
                error_code: analyzed.error_code,
                message: [analyzed.message, ...analyzed.warnings].filter(Boolean).join(" "),
                parser: analyzed.parser,
                debug: analyzed.debug,
              });
              setParsedFoods(drafts);
              if (!analyzed.success || analyzed.status === "error") {
                throw new Error(`AI parser failed at ${failedStep}: ${backendMessage}`);
              }
              if (!drafts.length) {
                throw new Error("Food analysis returned no parsed items.");
              }
              updateFoodAiFlowStep("Review", "ok", "Parsed drafts are visible below. Review them, then click Save to today.");
            } catch (error) {
              updateFoodAiDebug({ exactError: error instanceof Error ? error.message : "Food analysis failed." });
              updateFoodAiFlowStep("Failure", "error", error instanceof Error ? error.message : "Food analysis failed.");
              throw error;
            }
          }, "Food text parsed. Review before saving.").finally(() => setParseLoading(false))
        }
        onSaveParsedFoods={(event) =>
          submitFoodAndRefreshToday(event, async () => {
            try {
              const logPayload = parsedFoodsLogPayload();
              updateFoodAiFlowStep("Save", "pending", `POST /api/food/log-bulk with ${parsedFoods.length} parsed item(s).`);
              updateFoodAiDebug({
                logEndpoint: "/api/food/log-bulk",
                logRequestBody: logPayload,
                log_insert_attempted: true,
                log_insert_success: false,
                logInsertStatus: "pending",
                logRequested: logPayload.items.length,
              });
              const result = await saveParsedFoodsToToday(logPayload);
              updateFoodAiDebug({
                log_insert_success: result.status === "ok",
                logInsertStatus: result.status,
                logCreated: result.created,
                logRequested: result.requested ?? logPayload.items.length,
                refreshEndpoint: `/api/nutrition/today?date=${encodeURIComponent(forms.nutrition.date || todayString())}`,
                refreshStatus: "pending",
              });
              updateFoodAiFlowStep("Save", "ok", `Saved ${result.created} parsed item(s) to food_logs. Today's totals refresh next.`);
              setParsedFoods([]);
              setParseResult(null);
              setAiText("");
            } catch (error) {
              updateFoodAiDebug({ log_insert_success: false, logInsertStatus: "error", exactError: error instanceof Error ? error.message : "Could not save parsed food items." });
              updateFoodAiFlowStep("Save", "error", error instanceof Error ? error.message : "Could not save parsed food items.");
              throw error;
            }
          }, "Confirmed parsed food entries saved.", forms.nutrition.date, (payload) => {
            updateFoodAiDebug({
              refreshStatus: "ok",
              refreshCalories: Number(payload.totals?.calories) || 0,
            });
            updateFoodAiFlowStep("Refresh", "ok", `Today's nutrition refreshed: ${Math.round(Number(payload.totals?.calories) || 0)} kcal.`);
          }, (message) => {
            updateFoodAiDebug({ refreshStatus: "error", exactError: message });
            updateFoodAiFlowStep("Failure", "error", message);
          })
        }
        onSaveShortcut={(event) =>
          submitWithoutRefresh(event, async () => {
            await saveParsedShortcut();
            await refreshFoodShortcutsOnly();
          }, "Saved AI parse as a food shortcut.")
        }
        onSaveMealTemplate={(event) =>
          submitWithoutRefresh(event, async () => {
            await saveParsedMealTemplate();
            await refreshFoodShortcutsOnly();
          }, "Saved AI parse as a meal template.")
        }
        onSaveAndLogToday={(event) =>
          submitFoodAndRefreshToday(event, async () => {
            await saveParsedShortcut();
            await saveParsedMealTemplate();
            await saveParsedFoodsToToday();
            await refreshFoodShortcutsOnly();
            setParsedFoods([]);
            setParseResult(null);
            setAiText("");
          }, "Saved shortcut/template and logged food today.")
        }
        onLogShortcut={(shortcut) => {
          const date = forms.nutrition.date || todayString();
          const statusKey = shortcutQuickLogKey(shortcut);
          queueQuickFoodLog({
            dedupeKey: statusKey,
            statusKey,
            date,
            label: shortcut.shortcut_name,
            optimisticEntry: optimisticFoodEntry(`optimistic:${statusKey}:${Date.now()}:${Math.random().toString(36).slice(2)}`, date, shortcut.shortcut_name, {
              calories: shortcut.calories,
              protein: shortcut.protein,
              carbs: shortcut.carbs,
              fat: shortcut.fat,
              fiber: shortcut.fiber,
              sodium: shortcut.sodium,
              potassium: shortcut.potassium,
              iconType: suggestFoodIconType(shortcut.shortcut_name),
              serving_description: "Saved preset queued",
              source: "saved_shortcut",
            }),
            run: async () => {
              const response = await apiSend<{ item: NutritionEntry }>(`/api/nutrition/shortcuts/${shortcut.shortcut_id}/log`, "POST", {
                date,
                meal_type: DEFAULT_MEAL_TYPE,
              });
              return response.item;
            },
          });
        }}
        onCreateShortcut={(shortcut) =>
          submitWithoutRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            await apiSend("/api/nutrition/shortcuts", "POST", shortcutMutationPayload(shortcut));
            await refreshFoodShortcutsOnly();
          }, "Preset saved.")
        }
        onCreateAndLogPreset={(shortcut) => {
          const date = forms.nutrition.date || todayString();
          const statusKey = shortcutQuickLogKey(shortcut);
          queueQuickFoodLog({
            dedupeKey: statusKey,
            statusKey,
            date,
            label: shortcut.shortcut_name,
            refreshShortcuts: true,
            optimisticEntry: optimisticFoodEntry(`optimistic:${statusKey}:${Date.now()}:${Math.random().toString(36).slice(2)}`, date, shortcut.shortcut_name, {
              calories: shortcut.calories,
              protein: shortcut.protein,
              carbs: shortcut.carbs,
              fat: shortcut.fat,
              fiber: shortcut.fiber,
              sodium: shortcut.sodium,
              potassium: shortcut.potassium,
              iconType: suggestFoodIconType(shortcut.shortcut_name),
              serving_description: "Preset queued",
              source: "default_preset",
            }),
            run: async () => {
              let shortcutId = materializedDefaultShortcutIdsRef.current[shortcut.shortcut_id];
              if (!shortcutId) {
                const created = await apiSend<{ item: FoodShortcut }>("/api/nutrition/shortcuts", "POST", shortcutMutationPayload(shortcut));
                shortcutId = created.item.shortcut_id;
                materializedDefaultShortcutIdsRef.current[shortcut.shortcut_id] = shortcutId;
              }
              const response = await apiSend<{ item: NutritionEntry }>(`/api/nutrition/shortcuts/${shortcutId}/log`, "POST", {
                date,
                meal_type: DEFAULT_MEAL_TYPE,
              });
              return response.item;
            },
          });
        }}
        onLogFrequentFood={(food) => {
          const date = forms.nutrition.date || todayString();
          const statusKey = frequentFoodQuickLogKey(food.food_name);
          queueQuickFoodLog({
            dedupeKey: statusKey,
            statusKey,
            date,
            label: food.food_name,
            optimisticEntry: optimisticFoodEntry(`optimistic:${statusKey}:${Date.now()}:${Math.random().toString(36).slice(2)}`, date, food.food_name, {
              calories: food.calories,
              protein: food.protein,
              carbs: food.carbs,
              fat: food.fat,
              serving_description: "Frequent food queued",
              source: "frequent_food",
            }),
            run: async () => {
              const response = await apiSend<{ item: NutritionEntry }>(`/api/nutrition/frequent-foods/${encodeURIComponent(food.food_name)}/log`, "POST", {
                date,
                meal_type: DEFAULT_MEAL_TYPE,
              });
              return response.item;
            },
          });
        }}
        onDeleteFoodLog={(entry) =>
          submitFoodAndRefreshToday({ preventDefault: () => undefined } as FormEvent, async () => {
            if (!entry.food_log_id) throw new Error("Food log ID is missing.");
            await apiDelete(`/api/nutrition/logs/${encodeURIComponent(entry.food_log_id)}`);
          }, "Food entry removed.", entry.date)
        }
        onUpdateFoodLog={(entry, updates) =>
          submitFoodAndRefreshToday({ preventDefault: () => undefined } as FormEvent, async () => {
            if (!entry.food_log_id) throw new Error("Food log ID is missing.");
            await apiSend(`/api/nutrition/logs/${encodeURIComponent(entry.food_log_id)}`, "PUT", updates);
          }, "Food icon updated.", entry.date)
        }
        onUpdateShortcut={(shortcut) =>
          submitWithoutRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            await apiSend(`/api/nutrition/shortcuts/${shortcut.shortcut_id}`, "PUT", shortcutMutationPayload(shortcut));
            await refreshFoodShortcutsOnly();
          }, "Shortcut updated.")
        }
        onDeleteShortcut={(shortcutId) =>
          submitWithoutRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            await apiDelete(`/api/nutrition/shortcuts/${shortcutId}`);
            await refreshFoodShortcutsOnly();
          }, "Shortcut deleted.")
        }
        onLogMealTemplate={(template) => {
          const date = forms.nutrition.date || todayString();
          const statusKey = mealTemplateQuickLogKey(template.template_name);
          queueQuickFoodLog({
            dedupeKey: statusKey,
            statusKey,
            date,
            label: template.template_name,
            optimisticEntry: optimisticFoodEntry(`optimistic:${statusKey}:${Date.now()}:${Math.random().toString(36).slice(2)}`, date, template.template_name, {
              calories: template.calories,
              protein: template.protein,
              carbs: template.carbs,
              fat: template.fat,
              serving_description: `${template.foods} item meal queued`,
              source: "meal_template",
            }),
            run: async () => {
              const response = await apiSend<{ item?: NutritionEntry; items?: NutritionEntry[] }>(`/api/nutrition/meal-templates/${encodeURIComponent(template.template_name)}/log`, "POST", {
                date,
                meal_type: DEFAULT_MEAL_TYPE,
              });
              return response.item ?? response.items?.[0] ?? null;
            },
          });
        }}
        onRenameMealTemplate={(templateName, nextName) =>
          submitWithoutRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
            await apiSend(`/api/nutrition/meal-templates/${encodeURIComponent(templateName)}`, "PUT", {
              template_name: nextName,
            });
            await refreshFoodShortcutsOnly();
          }, "Meal template renamed.")
        }
        onSubmit={(event) =>
          submitFoodAndRefreshToday(event, async () => {
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
                  serving_description: "",
                  calories: 0,
                  protein: 0,
                  carbs: 0,
                  fat: 0,
                  fiber: null,
                },
              }));
              setManualCaloriesOverridden(false);
            } finally {
              setManualFoodSaving(false);
            }
          }, "Food entry saved.")
        }
      />
    ),
    goals: (
      <GoalsPageErrorBoundary resetKey={`${dashboard?.date ?? ""}-${Boolean(dashboard?.adaptive_recommendation)}`}>
        <GoalsPage
          goals={dashboard?.goals ?? null}
          targets={dashboard?.targets ?? null}
          weightFeedback={dashboard?.weight_feedback ?? null}
          leanBulkDecision={dashboard?.lean_bulk_decision ?? null}
          adaptiveRecommendation={dashboard?.adaptive_recommendation ?? null}
          trainingPrs={trainingPrs}
          trainingPrsLoading={trainingPrsLoading}
          onRefreshTrainingPrs={() => {
            void loadTrainingPrs(true);
          }}
          onApplySuggestedMacros={() =>
            void submitAndRefresh({ preventDefault: () => undefined } as FormEvent, async () => {
              await apiSend("/api/goals/apply-suggested-macros", "POST", {});
            }, "Suggested macros applied.")
          }
        />
      </GoalsPageErrorBoundary>
    ),
    recovery: (
      <RecoveryPage
        bodyMetrics={bodyMetrics}
        recoveryLogs={recoveryLogs}
        sleepEntries={sleepEntries}
        wearableMetrics={wearableMetrics}
        wearableSignals={wearableSignals}
        trainingReadiness={trainingReadiness}
        adaptiveRecommendation={dashboard?.adaptive_recommendation ?? null}
        withingsLastSyncedAt={
          settings?.withings?.last_successful_sync
          ?? settings?.services?.withings?.last_synced_at
          ?? settings?.health?.find((card) => card.id === "withings")?.last_synced_at
          ?? ""
        }
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
        onWearableSubmit={submitWearableMetric}
        onSyncWeightNow={syncWeightNow}
        onSyncWithingsHistory={async () => {
          setApiError(null);
          setMessage(null);
          try {
            const result = await apiSend<WithingsSyncResult>("/api/withings/sync-history", "POST", { days: 3650 });
            if (result.status === "error") {
              throw new Error(result.message ?? "Withings history sync failed.");
            }
            const dateRange = result.earliest_date && result.latest_date ? ` (${result.earliest_date} to ${result.latest_date})` : "";
            setMessage(`Withings history sync complete: ${result.imported_measurements} scale measurement(s) imported or updated from ${result.fetched_groups} group(s)${dateRange}.`);
            await refreshAll();
          } catch (error) {
            setApiError(error instanceof Error ? error.message : "Withings history sync failed.");
          }
        }}
      />
    ),
    training: (
      <TrainingPage
        workoutHistory={workoutHistory}
        trainingHistoryMeta={trainingHistoryMeta}
        onMoveWorkout={moveWorkoutDate}
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
          void submitWithoutRefresh(
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
          void (async () => {
            setMessage(null);
            setApiError(null);
            try {
              const result = await apiSend<{
                status: string;
                message?: string;
                imported_workouts: number;
                imported_rows: number;
                skipped_duplicates: number;
                failures?: string[];
                last_synced_at?: string;
                hevy_rows?: number;
                hevy_workouts?: number;
                latest_workout_date?: string;
                latest_workout_title?: string;
              }>("/api/training/import/hevy", "POST", { page_size: 10, pages: 1 });
              if (result.status === "error") {
                throw new Error(result.message ?? "Hevy import failed.");
              }
              setHevyPreview(null);
              setHevySync({
                status: result.status,
                configured: true,
                last_synced_at: result.last_synced_at ?? "",
                last_error: result.status === "error" ? result.failures?.join(" ") ?? result.message ?? "Hevy import failed." : "",
                last_result: result as unknown as Record<string, unknown>,
                hevy_rows: result.hevy_rows,
                hevy_workouts: result.hevy_workouts,
                latest_workout_date: result.latest_workout_date,
                latest_workout_title: result.latest_workout_title,
              });
              await refreshTrainingData(true);
              await refreshDashboardCoreOnly();
              const failureText = result.failures?.length ? ` ${result.failures.length} failures.` : "";
              setMessage(`Imported ${result.imported_workouts} Hevy workouts (${result.imported_rows} rows). Skipped ${result.skipped_duplicates} duplicates.${failureText}`);
            } catch (error) {
              setApiError(error instanceof Error ? error.message : "Hevy import failed.");
            }
          })();
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
        onLoadMoreTraining={loadMoreTrainingHistory}
        onImportStrava={() => {
          void submitAndRefresh(
            { preventDefault: () => undefined } as FormEvent,
            async () => {
              const result = await apiSend<{ status: string; message?: string; fetched_activities?: number; imported_runs: number; updated_runs?: number; skipped_duplicates: number; latest_activity_date?: string; reconnect_required?: boolean }>("/api/training/import/strava", "POST", { per_page: 30 });
              if (result.status !== "ok") {
                throw new Error(result.message ?? "Strava import failed.");
              }
              setMessage(`Synced ${result.fetched_activities ?? result.imported_runs} Strava runs. Imported ${result.imported_runs}, updated ${result.updated_runs ?? 0}.`);
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
        optimization={dashboard?.optimization ?? null}
        adaptiveRecommendation={dashboard?.adaptive_recommendation ?? null}
        bodyMetrics={bodyMetrics}
        recoveryTrend={dashboard?.recovery_trend ?? []}
        trainingVolume={dashboard?.training_volume ?? []}
        trainingSummary={trainingSummary}
        trainingSummaryStatus={trainingSummaryStatus}
        muscleCoverage={muscleCoverage}
        onSyncHevy={() => {
          void syncHevyNow(true);
        }}
        onExportRawHevy={exportRawHevyData}
        onExportNormalizedTraining={exportNormalizedTrainingData}
        onRebuildTrainingSummaries={rebuildTrainingSummaries}
        hevySyncing={hevySyncing}
        trainingDataAction={trainingDataAction}
        workoutHistory={workoutHistory}
        onMoveWorkout={moveWorkoutDate}
        onExcludeNutritionDay={excludeNutritionDay}
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
        onBackupImported={refreshAll}
      />
    ),
    settings: (
      <SettingsPage
        settings={settings}
        accentTheme={accentTheme}
        apiConnectionTests={apiConnectionTests}
        apiConnectionTesting={apiConnectionTesting}
        forms={forms}
        setForms={setForms}
        onAccentThemeChange={handleAccentThemeChange}
        onTestApiConnections={handleTestApiConnections}
        onSyncHevy={() => {
          void syncHevyNow(true);
        }}
        onImportStrava={() => {
          void submitAndRefresh(
            { preventDefault: () => undefined } as FormEvent,
            async () => {
              const result = await apiSend<{ status: string; message?: string; fetched_activities?: number; imported_runs: number; updated_runs?: number; skipped_duplicates: number; latest_activity_date?: string; reconnect_required?: boolean }>("/api/training/import/strava", "POST", { per_page: 30 });
              if (result.status !== "ok") {
                throw new Error(result.message ?? "Strava import failed.");
              }
              setMessage(`Synced ${result.fetched_activities ?? result.imported_runs} Strava runs. Imported ${result.imported_runs}, updated ${result.updated_runs ?? 0}.`);
            },
            "Strava import complete.",
          );
        }}
        onConnectStrava={async (reconnect = false) => {
          setApiError(null);
          setMessage(null);
          try {
            const result = await apiGet<{ status: string; message?: string; auth_url: string }>(`/api/integrations/strava/auth-url${reconnect ? "?reconnect=true" : ""}`);
            if (result.status !== "ok" || !result.auth_url) {
              throw new Error(result.message ?? "Unable to generate Strava authorization URL.");
            }
            window.location.href = result.auth_url;
          } catch (error) {
            setApiError(error instanceof Error ? error.message : "Unable to connect Strava.");
          }
        }}
        onConnectWithings={async () => {
          setApiError(null);
          setMessage(null);
          try {
            const result = await apiGet<{ status: string; message?: string; auth_url: string }>("/api/integrations/withings/auth-url");
            if (result.status !== "ok" || !result.auth_url) {
              throw new Error(result.message ?? "Unable to generate Withings authorization URL.");
            }
            window.location.href = result.auth_url;
          } catch (error) {
            setApiError(error instanceof Error ? error.message : "Unable to connect Withings.");
          }
        }}
        onSyncWithings={async () => {
          setApiError(null);
          setMessage(null);
          try {
            const result = await apiSend<WithingsSyncResult>("/api/withings/sync", "POST", {});
            if (result.status === "error") {
              throw new Error(result.message ?? "Withings sync failed.");
            }
            setMessage(`Withings sync complete: ${result.imported_measurements} scale measurement(s) imported or updated.`);
            await refreshAll();
          } catch (error) {
            setApiError(error instanceof Error ? error.message : "Withings sync failed.");
          }
        }}
        onSyncWithingsHistory={async () => {
          setApiError(null);
          setMessage(null);
          try {
            const result = await apiSend<WithingsSyncResult>("/api/withings/sync-history", "POST", { days: 3650 });
            if (result.status === "error") {
              throw new Error(result.message ?? "Withings history sync failed.");
            }
            const dateRange = result.earliest_date && result.latest_date ? ` (${result.earliest_date} to ${result.latest_date})` : "";
            setMessage(`Withings history sync complete: ${result.imported_measurements} scale measurement(s) imported or updated from ${result.fetched_groups} group(s)${dateRange}.`);
            await refreshAll();
          } catch (error) {
            setApiError(error instanceof Error ? error.message : "Withings history sync failed.");
          }
        }}
        onClearWithings={async () => {
          setApiError(null);
          setMessage(null);
          try {
            const updated = await apiSend<SettingsData>("/api/integrations/withings/disconnect", "POST", {});
            applySettingsData(updated);
            setMessage("Withings disconnected. Reconnect from Settings when ready.");
            await refreshAll();
          } catch (error) {
            setApiError(error instanceof Error ? error.message : "Unable to disconnect Withings.");
          }
        }}
        onTestOpenAI={async () => {
          const path = "/api/debug/food-parser-test";
          const body = { text: "banana and protein shake" };
          const timestamp = new Date().toISOString();
          const started = performance.now();
          setApiError(null);
          setMessage(null);
          recordStartupDebug({
            key: "food_parser_diagnostic",
            label: "Food parser diagnostic",
            path,
            required: false,
            status: "pending",
            httpStatus: null,
            backendLabel: publicApiBaseLabel(),
            timestamp,
          });
          try {
            const result = await apiSend<FoodParserDiagnosticResponse>(path, "POST", body);
            const durationMs = Math.round(performance.now() - started);
            const frontendReceivedItems = Array.isArray(result.items) && result.items.length > 0;
            const diagnostic = {
              ...result,
              frontend_received_items: frontendReceivedItems,
              log_insert_attempted: false,
              log_insert_success: false,
              parser_source: result.parser_source || result.debug?.parser_source || "unknown",
              external_lookup_status: result.external_lookup_status || result.debug?.external_lookup_status || "unknown",
            };
            recordStartupDebug({
              key: "food_parser_diagnostic",
              label: "Food parser diagnostic",
              path,
              required: false,
              status: result.status === "ok" && frontendReceivedItems ? "ok" : "error",
              httpStatus: 200,
              durationMs,
              errorMessage: result.status === "ok" && frontendReceivedItems ? undefined : result.message || result.error_code || "Food parser returned no items.",
              responseText: JSON.stringify(diagnostic, null, 2).slice(0, 2000),
              backendLabel: publicApiBaseLabel(),
              timestamp: new Date().toISOString(),
            });
            setFoodAiDebug({
              endpoint_called: result.endpoint_called,
              request_body_received: result.request_body_received,
              diagnostic_force_openai: result.diagnostic_force_openai,
              openai_called: result.openai_called,
              model_used: result.model_used,
              parser_source: diagnostic.parser_source,
              external_lookup_status: diagnostic.external_lookup_status,
              raw_items_count: result.raw_items_count,
              normalized_items_count: result.normalized_items_count,
              response_shape: result.response_shape,
              frontend_received_items: frontendReceivedItems,
              log_insert_attempted: false,
              log_insert_success: false,
              analyzeEndpoint: result.endpoint_called,
              analyzeRequestBody: result.request_body_received,
              analyzeResponseStatus: result.status,
              parsedItemCount: result.items?.length ?? 0,
              exactError: result.status === "ok" && frontendReceivedItems ? undefined : result.message || result.error_code || "Food parser returned no items.",
            });
            if (result.status !== "ok" || !frontendReceivedItems) {
              throw new Error(result.message || result.error_code || "Food parser returned no items.");
            }
            setMessage(`Food parser diagnostic passed: ${result.normalized_items_count} item(s) from ${result.endpoint_called}. OpenAI called: ${String(result.openai_called)}.`);
          } catch (error) {
            const durationMs = Math.round(performance.now() - started);
            const message = error instanceof Error ? error.message : "OpenAI parser test failed.";
            recordStartupDebug({
              key: "food_parser_diagnostic",
              label: "Food parser diagnostic",
              path,
              required: false,
              status: "error",
              httpStatus: null,
              durationMs,
              errorMessage: message,
              backendLabel: publicApiBaseLabel(),
              timestamp: new Date().toISOString(),
            });
            setApiError(message);
          }
        }}
        onSubmit={(event) =>
          submitAndRefresh(event, async () => {
            const updated = await apiSend<SettingsData>("/api/settings", "PUT", { integrations: forms.settings });
            applySettingsData(updated);
            setForms((state) => ({ ...state, settings: {} }));
          }, "Settings saved locally.")
        }
      />
    ),
    debug: (
      <StartupDebugPage
        entries={startupDebug}
        onRetry={() => {
          setLoading(true);
          void refreshAll();
        }}
      />
    ),
  };

  return (
    <main data-accent-theme={accentTheme} className="min-h-screen bg-[#07080b] text-zinc-100">
      <div className="accent-page-glow pointer-events-none fixed inset-0" />
      <div className="relative flex min-h-screen">
        <aside className="sticky top-0 hidden h-screen w-72 shrink-0 border-r border-white/10 bg-black/35 p-5 backdrop-blur-xl lg:block">
          <div className="mb-8 flex items-center gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/POSLOGO.png"
              alt="Performance OS logo"
              width={40}
              height={40}
              className="h-10 w-10 shrink-0 rounded-lg object-contain"
            />
            <div>
              <p className="font-semibold text-white">Performance OS</p>
              <p className="text-xs text-zinc-500">Local-first dashboard</p>
            </div>
          </div>
          <nav className="relative">
            <span
              aria-hidden="true"
              className={cx(
                "accent-active pointer-events-none absolute left-0 right-0 top-0 h-10 rounded-lg transition-[transform,opacity] duration-[220ms] ease-[cubic-bezier(0.22,1,0.36,1)] will-change-transform motion-reduce:transition-none",
                primaryNavActive ? "opacity-100" : "opacity-0",
              )}
              style={{ transform: `translate3d(0, ${sidebarHighlightOffset}px, 0)` }}
            />
            <div className="space-y-2">
              {primaryNavigation.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    onClick={() => setActivePage(item.id)}
                    data-testid={`nav-${item.id}`}
                    className={cx("relative z-10 flex h-10 w-full items-center gap-3 rounded-lg px-3 text-left text-sm transition-colors", activePage === item.id ? "text-[#050505]" : "text-zinc-400 hover:bg-white/[0.06] hover:text-white")}
                  >
                    <Icon className="h-4 w-4" />
                    {item.label}
                  </button>
                );
              })}
            </div>
          </nav>
          <div className="absolute bottom-5 left-5 right-5 border-t border-white/10 pt-4">
            <p className="px-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-600">Diagnostics</p>
            <button
              onClick={() => setActivePage(debugNavigationItem.id)}
              data-testid={`nav-${debugNavigationItem.id}`}
              className={cx(
                "mt-3 flex h-9 w-full items-center gap-2 rounded-lg px-3 text-left text-xs transition-colors",
                activePage === debugNavigationItem.id
                  ? "border border-amber-300/20 bg-amber-300/10 text-amber-100"
                  : "text-zinc-500 hover:bg-white/[0.04] hover:text-zinc-300",
              )}
            >
              <AlertTriangle className="h-3.5 w-3.5" />
              {debugNavigationItem.label}
            </button>
          </div>
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <header className="mobile-safe-header sticky top-0 z-20 border-b border-white/10 bg-[#07080b]/80 px-4 py-4 backdrop-blur-xl sm:px-6 lg:px-8">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-sm text-zinc-500">Performance optimization dashboard</p>
                <h1 className="mt-2 text-2xl font-semibold text-white sm:text-3xl">{currentPage.label}</h1>
              </div>
              <div className="flex items-center gap-3 self-start lg:self-auto">
                <span className="text-sm text-zinc-500">{headerDateLabel}</span>
                <button onClick={() => void refreshAll()} className="inline-flex h-10 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-zinc-200">
                  <RefreshCw className="h-4 w-4" />
                  Refresh
                </button>
              </div>
            </div>
            <div ref={mobileNavRef} className="relative mt-4 hidden overflow-x-auto pb-1 sm:block lg:hidden">
              <span
                aria-hidden="true"
                className={cx(
                  "accent-active pointer-events-none absolute rounded-lg transition-[transform,width,height,opacity] duration-200 ease-out",
                  mobileHighlight.ready ? "opacity-100" : "opacity-0",
                )}
                style={{
                  height: mobileHighlight.height,
                  width: mobileHighlight.width,
                  transform: `translate(${mobileHighlight.left}px, ${mobileHighlight.top}px)`,
                }}
              />
              <div className="flex gap-2">
                {primaryNavigation.map((item) => (
                  <button
                    key={item.id}
                    ref={(node) => {
                      mobileItemRefs.current[item.id] = node;
                    }}
                    onClick={() => setActivePage(item.id)}
                    data-testid={`nav-${item.id}-mobile`}
                    className={cx("relative z-10 whitespace-nowrap rounded-lg px-3 py-2 text-sm transition-colors", activePage === item.id ? "text-[#050505]" : "bg-white/[0.06] text-zinc-300")}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          </header>

          <div className="p-4 pb-[calc(6rem+env(safe-area-inset-bottom))] sm:p-6 lg:p-8">
            {rateLimited ? (
              <Card className="mb-4 border-amber-400/30 bg-amber-400/10">
                <p className="text-sm text-amber-100">Temporarily rate limited — retrying shortly. This is a server limit, not your account.</p>
              </Card>
            ) : null}
            {systemFailure ? (
              <SystemFailureScreen
                failure={systemFailure}
                entries={startupDebug}
                onRetry={() => {
                  setLoading(true);
                  void refreshAll();
                }}
              />
            ) : (
              <>
            {apiError ? (
              <Card className="mb-4 border-red-400/30 bg-red-400/10">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-red-100">Action needs attention</p>
                    <p className="mt-2 text-sm text-red-100/80">{apiError}</p>
                    <p className="mt-2 text-sm text-red-100/70">If this is a connection issue, start FastAPI with: uvicorn backend_new.main:app --reload</p>
                  </div>
                  <button
                    onClick={() => {
                      setLoading(true);
                      void refreshAll();
                    }}
                    className="inline-flex h-9 items-center gap-2 rounded-lg border border-red-300/40 bg-red-400/10 px-3 text-sm text-red-50"
                  >
                    <RefreshCw className="h-4 w-4" />
                    Retry
                  </button>
                </div>
                <StartupDebugPanel entries={startupDebug} open={showDebugPanel} onOpenChange={setShowDebugPanel} />
              </Card>
            ) : null}
            {!apiError && loadFailures.length > 0 ? (
              <Card className="mb-4 border-amber-400/30 bg-amber-400/10">
                <p className="font-medium text-amber-100">Some optional data did not load</p>
                <ul className="mt-2 space-y-1 text-sm text-amber-100/80">
                  {loadFailures.map((line) => (
                    <li key={line}>• {line}</li>
                  ))}
                </ul>
                <p className="mt-2 text-sm text-amber-100/70">The rest of the app is usable. Use Refresh to try the failing services again.</p>
              </Card>
            ) : null}
            {message ? (
              <Card className="mb-4 border-emerald-400/30 bg-emerald-400/10">
                <p className="text-sm text-emerald-100">{message}</p>
              </Card>
            ) : null}
            {loading ? (
              <Card>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-sm text-zinc-300">{loadingMessage}</p>
                  <button
                    onClick={() => {
                      setLoading(true);
                      void refreshAll();
                    }}
                    className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-zinc-200"
                  >
                    <RefreshCw className="h-4 w-4" />
                    Retry
                  </button>
                </div>
              </Card>
            ) : (
              <TargetSectionErrorBoundary
                title={`${currentPage.label} temporarily unavailable`}
                description="Adaptive data temporarily unavailable."
                resetKey={`${activePage}-${dashboard?.date ?? ""}-${dashboard?.targets?.target_calories ?? ""}`}
              >
                {pageContent[activePage]}
              </TargetSectionErrorBoundary>
            )}
              </>
            )}
          </div>
        </section>
        <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-white/10 bg-[#07080b]/85 px-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] pt-2 shadow-2xl shadow-black/40 backdrop-blur-xl sm:hidden" aria-label="Primary navigation">
          <div ref={bottomNavRef} className="relative overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <span
              aria-hidden="true"
              className={cx(
                "accent-active pointer-events-none absolute rounded-lg transition-[transform,width,height,opacity] duration-200 ease-out will-change-transform motion-reduce:transition-none",
                bottomHighlight.ready ? "opacity-100" : "opacity-0",
              )}
              style={{
                height: bottomHighlight.height,
                width: bottomHighlight.width,
                transform: `translate(${bottomHighlight.left}px, ${bottomHighlight.top}px)`,
              }}
            />
            <div className="flex min-w-max gap-1">
              {mobileBottomNavigation.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    ref={(node) => {
                      bottomItemRefs.current[item.id] = node;
                    }}
                    onClick={() => setActivePage(item.id)}
                    data-testid={`nav-${item.id}-bottom`}
                    aria-label={item.label}
                    className={cx(
                      "relative z-10 flex h-14 min-w-[74px] flex-col items-center justify-center gap-1 rounded-lg px-2 text-[10px] font-medium leading-tight transition-colors",
                      activePage === item.id ? "text-[#050505]" : "text-zinc-400 hover:bg-white/[0.06] hover:text-white",
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="max-w-[4rem] truncate">{item.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </nav>
      </div>
    </main>
  );
}
