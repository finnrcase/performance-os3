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


if __name__ == "__main__":
    unittest.main()
