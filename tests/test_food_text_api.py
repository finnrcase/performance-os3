import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from src import nutrition as nutrition_module


SAMPLE_ANALYSIS = {
    "items": [
        {
            "name": "eggs",
            "original_text": "3 eggs",
            "quantity": 3,
            "unit": "large eggs",
            "serving_description": "3 large eggs",
            "calories": 216,
            "protein_g": 18,
            "carbs_g": 1.2,
            "fat_g": 14.4,
            "fiber_g": 0,
            "sugar_g": 0,
            "sodium_mg": 210,
            "confidence": "high",
            "source": "usda_fdc",
            "source_id": "171287",
            "source_url": "https://fdc.nal.usda.gov/",
            "assumptions": [],
            "needs_review": False,
        },
        {
            "name": "toast with butter",
            "original_text": "2 slices sourdough toast with butter",
            "quantity": 2,
            "unit": "slices",
            "serving_description": "2 slices with assumed 1 tbsp butter",
            "calories": 310,
            "protein_g": 8,
            "carbs_g": 42,
            "fat_g": 12,
            "fiber_g": 2,
            "sugar_g": 3,
            "sodium_mg": 420,
            "confidence": "medium",
            "source": "openai_estimate",
            "source_id": None,
            "source_url": None,
            "assumptions": ["Butter amount was estimated."],
            "needs_review": True,
        },
    ],
    "totals": {
        "calories": 526,
        "protein_g": 26,
        "carbs_g": 43.2,
        "fat_g": 26.4,
        "fiber_g": 2,
        "sugar_g": 3,
        "sodium_mg": 630,
    },
    "warnings": ["Review toast with butter: butter amount was estimated."],
    "success": True,
    "message": "Mock parsed.",
    "error_code": None,
    "debug": {"backend_endpoint_reached": True, "openai_key_configured": False, "model": "mock"},
}


class FoodTextApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_analyze_text_rejects_empty_input(self):
        response = self.client.post("/api/food/analyze-text", json={"date": "2026-05-13", "text": "   "})
        self.assertEqual(response.status_code, 400)

    def test_analyze_text_returns_structured_draft_items_and_totals(self):
        sample_text = (
            "Breakfast: 3 eggs, 2 slices sourdough toast with butter. "
            "Lunch: chipotle chicken bowl with rice, black beans, cheese and guac. "
            "Snack: whey protein shake with a banana."
        )
        with patch("backend.routes.nutrition.analyze_food_text", return_value=SAMPLE_ANALYSIS):
            response = self.client.post("/api/food/analyze-text", json={"date": "2026-05-13", "text": sample_text})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["items"][0]["source"], "usda_fdc")
        self.assertTrue(data["items"][1]["needs_review"])
        self.assertEqual(data["totals"]["calories"], 526)

    def test_log_bulk_persists_reviewed_items_to_regular_nutrition_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "nutrition_log.csv"
            with patch.object(nutrition_module, "NUTRITION_LOG_PATH", temp_path), patch(
                "backend.routes.nutrition.rebuild_daily_summary", return_value=None
            ):
                response = self.client.post(
                    "/api/food/log-bulk",
                    json={
                        "date": "2026-05-13",
                        "meal_type": "Breakfast",
                        "items": SAMPLE_ANALYSIS["items"],
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["saved"], 2)
                saved = nutrition_module.load_nutrition_log()
                self.assertEqual(len(saved), 2)
                self.assertEqual(float(saved["calories"].sum()), 526.0)
                self.assertEqual(saved.iloc[0]["created_via"], "text_ai")
                self.assertFalse(bool(saved.iloc[0]["needs_review"]))

    def test_meal_template_can_be_renamed_without_losing_foods(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_path = Path(temp_dir) / "meal_templates.csv"
            with patch.object(nutrition_module, "MEAL_TEMPLATES_PATH", templates_path):
                create_response = self.client.post(
                    "/api/nutrition/meal-templates",
                    json={
                        "template_name": "Chicken Burrito Bowl",
                        "default_meal_type": "Food",
                        "foods": [
                            {"food_name": "Chicken", "calories": 220, "protein": 35, "carbs": 0, "fat": 8},
                            {"food_name": "Rice", "calories": 240, "protein": 4, "carbs": 52, "fat": 1},
                        ],
                    },
                )
                self.assertEqual(create_response.status_code, 200)

                rename_response = self.client.put(
                    "/api/nutrition/meal-templates/Chicken%20Burrito%20Bowl",
                    json={"template_name": "Chicken Burrito Bowl w/ Extra Rice"},
                )

                self.assertEqual(rename_response.status_code, 200)
                saved = nutrition_module.load_meal_templates()
                self.assertEqual(len(saved), 2)
                self.assertEqual(set(saved["template_name"]), {"Chicken Burrito Bowl w/ Extra Rice"})
                self.assertEqual(float(saved["calories"].sum()), 460.0)

    def test_meal_template_log_adds_all_template_foods_to_selected_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_path = Path(temp_dir) / "meal_templates.csv"
            nutrition_path = Path(temp_dir) / "nutrition_log.csv"
            with patch.object(nutrition_module, "MEAL_TEMPLATES_PATH", templates_path), patch.object(
                nutrition_module, "NUTRITION_LOG_PATH", nutrition_path
            ), patch("backend.routes.nutrition.rebuild_daily_summary", return_value=None):
                self.client.post(
                    "/api/nutrition/meal-templates",
                    json={
                        "template_name": "Protein Breakfast",
                        "default_meal_type": "Food",
                        "foods": [
                            {"food_name": "Eggs", "calories": 216, "protein": 18, "carbs": 1, "fat": 14},
                            {"food_name": "Toast", "calories": 180, "protein": 6, "carbs": 34, "fat": 2},
                        ],
                    },
                )

                response = self.client.post(
                    "/api/nutrition/meal-templates/Protein%20Breakfast/log",
                    json={"date": "2026-05-13", "meal_type": "Food"},
                )

                self.assertEqual(response.status_code, 200)
                saved = nutrition_module.load_nutrition_log()
                self.assertEqual(len(saved), 2)
                self.assertEqual(set(saved["date"]), {"2026-05-13"})
                self.assertEqual(float(saved["calories"].sum()), 396.0)


if __name__ == "__main__":
    unittest.main()
