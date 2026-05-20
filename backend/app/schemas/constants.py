"""Shared table and field constants for backend v2."""

DATAFRAME_TABLES = {
    "nutrition_log": "food_logs",
    "frequent_food": "frequent_foods",
    "food_shortcut": "food_shortcuts",
    "meal_template": "meal_templates",
    "body_metrics": "body_metric_logs",
    "training_log": "workout_logs",
    "recovery_log": "recovery_logs",
    "sleep_log": "sleep_logs",
    "daily_nutrition_summary": "daily_nutrition_summaries",
    "personal_record": "personal_records",
}

DOCUMENT_TABLES = {
    "user_settings": "api_connections",
    "user_goals": "user_goal_settings",
    "nutrition_targets": "macro_targets",
    "training_cache_metadata": "training_cache_metadata",
    "hevy_sync_state": "integration_sync_state",
}

NUTRITION_TOTAL_FIELDS = ("calories", "protein", "carbs", "fat")
