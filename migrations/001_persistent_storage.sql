-- Performance OS durable storage tables.
-- These JSONB-backed tables preserve the current app data shape while moving
-- real user data out of local CSV/JSON files for production.

CREATE TABLE IF NOT EXISTS food_logs (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS frequent_foods (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS food_shortcuts (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS meal_templates (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS body_metric_logs (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS workout_logs (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS exercise_prs (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS exercise_prs_exercise_idx ON exercise_prs ((data->>'exercise'));
CREATE INDEX IF NOT EXISTS exercise_prs_updated_at_idx ON exercise_prs (updated_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS recovery_logs (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS sleep_logs (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS wearable_metrics (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS google_health_connections (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS google_health_daily_summary (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS google_health_sleep (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS google_health_heart (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS google_health_activity (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS google_health_recovery_signals (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS google_health_sync_runs (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS daily_nutrition_summaries (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS api_connections (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS macro_targets (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS user_goal_settings (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS personal_records (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS integration_sync_state (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS ai_food_cache (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS usda_food_cache (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS verified_food_cache (id BIGSERIAL PRIMARY KEY, row_order INTEGER NOT NULL DEFAULT 0, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE INDEX IF NOT EXISTS food_logs_row_order_idx ON food_logs (row_order);
CREATE INDEX IF NOT EXISTS meal_templates_row_order_idx ON meal_templates (row_order);
CREATE INDEX IF NOT EXISTS body_metric_logs_row_order_idx ON body_metric_logs (row_order);
CREATE INDEX IF NOT EXISTS workout_logs_row_order_idx ON workout_logs (row_order);
CREATE INDEX IF NOT EXISTS recovery_logs_row_order_idx ON recovery_logs (row_order);
CREATE INDEX IF NOT EXISTS sleep_logs_row_order_idx ON sleep_logs (row_order);
CREATE INDEX IF NOT EXISTS wearable_metrics_date_idx ON wearable_metrics ((data->>'date') DESC, row_order DESC, id DESC);
CREATE INDEX IF NOT EXISTS wearable_metrics_metric_id_idx ON wearable_metrics ((data->>'metric_id'));
CREATE INDEX IF NOT EXISTS google_health_connections_connection_id_idx ON google_health_connections ((data->>'connection_id'));
CREATE INDEX IF NOT EXISTS google_health_daily_summary_date_idx ON google_health_daily_summary ((data->>'date') DESC, row_order DESC, id DESC);
CREATE INDEX IF NOT EXISTS google_health_sleep_date_idx ON google_health_sleep ((data->>'date') DESC, row_order DESC, id DESC);
CREATE INDEX IF NOT EXISTS google_health_heart_date_idx ON google_health_heart ((data->>'date') DESC, row_order DESC, id DESC);
CREATE INDEX IF NOT EXISTS google_health_activity_date_idx ON google_health_activity ((data->>'date') DESC, row_order DESC, id DESC);
CREATE INDEX IF NOT EXISTS google_health_recovery_signals_date_idx ON google_health_recovery_signals ((data->>'date') DESC, row_order DESC, id DESC);
CREATE INDEX IF NOT EXISTS google_health_sync_runs_started_at_idx ON google_health_sync_runs ((data->>'started_at') DESC, row_order DESC, id DESC);
