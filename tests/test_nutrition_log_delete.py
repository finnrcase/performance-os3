import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src import nutrition as nutrition_module


class NutritionLogDeleteTest(unittest.TestCase):
    def test_food_log_ids_delete_single_entry_and_clear_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            nutrition_path = Path(temp_dir) / "nutrition_log.csv"
            with patch.object(nutrition_module, "NUTRITION_LOG_PATH", nutrition_path):
                banana = nutrition_module.create_food_entry(
                    date="2026-05-12",
                    meal_type="Breakfast",
                    food_name="Banana",
                    calories=105,
                    protein=1.3,
                    carbs=27,
                    fat=0.3,
                )
                rice = nutrition_module.create_food_entry(
                    date="2026-05-13",
                    meal_type="Dinner",
                    food_name="Rice",
                    calories=200,
                    protein=4,
                    carbs=45,
                    fat=0,
                )
                nutrition_module.save_nutrition_log(pd.DataFrame([banana, rice]))

                loaded = nutrition_module.load_nutrition_log()
                self.assertTrue(loaded["food_log_id"].astype(str).str.len().gt(0).all())

                deleted = nutrition_module.delete_food_log_entry(banana["food_log_id"])
                remaining = nutrition_module.load_nutrition_log()
                self.assertEqual(deleted["food_name"], "Banana")
                self.assertEqual(len(remaining), 1)
                self.assertEqual(remaining.iloc[0]["food_name"], "Rice")

                result = nutrition_module.clear_food_logs_for_date("2026-05-13")
                self.assertEqual(result["removed"], 1)
                self.assertTrue(nutrition_module.load_nutrition_log().empty)

    def test_food_log_icon_type_can_be_suggested_updated_and_cleared(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            nutrition_path = Path(temp_dir) / "nutrition_log.csv"
            with patch.object(nutrition_module, "NUTRITION_LOG_PATH", nutrition_path):
                entry = nutrition_module.create_food_entry(
                    date="2026-05-14",
                    meal_type="Food",
                    food_name="Everything bagel",
                    calories=280,
                    protein=11,
                    carbs=56,
                    fat=2,
                )
                self.assertEqual(entry["iconType"], "bagel")
                nutrition_module.save_nutrition_log(pd.DataFrame([entry]))

                updated = nutrition_module.update_food_log_entry(entry["food_log_id"], {"iconType": "chicken"})
                self.assertEqual(updated["iconType"], "chicken")
                self.assertEqual(nutrition_module.load_nutrition_log().iloc[0]["iconType"], "chicken")

                cleared = nutrition_module.update_food_log_entry(entry["food_log_id"], {"iconType": None})
                self.assertEqual(cleared["iconType"], "")

    def test_food_shortcut_log_preserves_preset_metadata(self):
        shortcut = pd.DataFrame(
            [
                {
                    "shortcut_id": "shortcut-oats",
                    "shortcut_name": "Oats Overnight",
                    "calories": 280,
                    "protein": 20,
                    "carbs": 35,
                    "fat": 7,
                    "fiber": 6,
                    "sodium": 260,
                    "potassium": 220,
                    "serving_size_grams": 100,
                    "default_grams_consumed": 150,
                    "calories_per_serving": 280,
                    "protein_per_serving": 20,
                    "carbs_per_serving": 35,
                    "fat_per_serving": 7,
                    "notes": "test preset",
                    "created_at": "2026-05-14T00:00:00+00:00",
                    "source": "manual",
                }
            ]
        )
        saved_frames = []

        with patch.object(nutrition_module, "load_food_shortcuts", return_value=shortcut), patch.object(
            nutrition_module, "load_nutrition_log", return_value=pd.DataFrame(columns=nutrition_module.NUTRITION_COLUMNS)
        ), patch.object(nutrition_module, "save_nutrition_log", side_effect=lambda frame: saved_frames.append(frame.copy())):
            entry = nutrition_module.log_food_shortcut("shortcut-oats", date="2026-05-14", meal_type="Food")

        self.assertEqual(entry["food_name"], "Oats Overnight")
        self.assertEqual(entry["source"], "shortcut")
        self.assertEqual(entry["source_id"], "shortcut-oats")
        self.assertEqual(float(entry["fiber"]), 6.0)
        self.assertEqual(float(entry["sodium"]), 260.0)
        self.assertEqual(float(entry["potassium"]), 220.0)
        self.assertEqual(float(entry["serving_size_grams"]), 100.0)
        self.assertEqual(float(entry["grams_consumed"]), 150.0)
        self.assertEqual(float(entry["serving_multiplier"]), 1.5)
        self.assertEqual(len(saved_frames), 1)
        self.assertEqual(len(saved_frames[0]), 1)


if __name__ == "__main__":
    unittest.main()
