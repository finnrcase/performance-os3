"""Shared table and field constants for backend v2."""

DATAFRAME_TABLES = {
    "nutrition_log": "food_logs",
    "body_metrics": "body_metric_logs",
    "training_log": "workout_logs",
    "daily_nutrition_summary": "daily_nutrition_summaries",
}

DOCUMENT_TABLES = {
    "user_settings": "api_connections",
    "user_goals": "user_goal_settings",
    "nutrition_targets": "macro_targets",
    "training_cache_metadata": "training_cache_metadata",
    "hevy_sync_state": "integration_sync_state",
}

NUTRITION_TOTAL_FIELDS = ("calories", "protein", "carbs", "fat")
