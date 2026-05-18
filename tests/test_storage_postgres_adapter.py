import json
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src import storage


class FakeCursor:
    def __init__(self):
        self.executed: list[tuple[str, object]] = []
        self.batches: list[tuple[str, list[object]]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((" ".join(str(sql).split()), params))

    def executemany(self, sql, params):
        self.batches.append((" ".join(str(sql).split()), list(params)))


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True


class StoragePostgresAdapterTest(unittest.TestCase):
    def test_dataframe_save_uses_row_level_upsert_and_explicit_deletes(self):
        fake = FakeConnection()
        df = pd.DataFrame(
            [
                {"food_log_id": "food-1", "date": "2026-05-13", "calories": 500},
                {"food_log_id": "food-2", "date": "2026-05-13", "calories": 300},
            ]
        )
        df.attrs["delete_row_keys"] = ["nutrition_log:food-old"]

        with patch("src.storage.use_database", return_value=True), patch("src.storage.ensure_database_schema", return_value=None), patch("src.storage._connect", return_value=fake):
            storage.save_dataframe("nutrition_log", Path("unused.csv"), df, ["food_log_id", "date", "calories"])

        statements = " ".join(sql for sql, _ in fake.cursor_obj.executed)
        batch_sql = " ".join(sql for sql, _ in fake.cursor_obj.batches)
        self.assertIn("DELETE FROM food_logs WHERE row_key = ANY(%s)", statements)
        self.assertIn("ON CONFLICT (row_key) WHERE row_key IS NOT NULL", batch_sql)
        self.assertNotIn("TRUNCATE", statements + batch_sql)
        self.assertTrue(fake.committed)
        upsert_rows = fake.cursor_obj.batches[0][1]
        self.assertEqual([row[0] for row in upsert_rows], ["nutrition_log:food-1", "nutrition_log:food-2"])
        self.assertEqual(json.loads(upsert_rows[0][2])["calories"], 500)

    def test_document_save_upserts_single_document_without_truncate(self):
        fake = FakeConnection()

        with patch("src.storage.use_database", return_value=True), patch("src.storage.ensure_database_schema", return_value=None), patch("src.storage._connect", return_value=fake):
            saved = storage.save_document("user_settings", Path("unused.json"), {"theme": "lime"})

        statements = " ".join(sql for sql, _ in fake.cursor_obj.executed)
        self.assertEqual(saved, {"theme": "lime"})
        self.assertIn("INSERT INTO api_connections (row_key, row_order, data)", statements)
        self.assertIn("ON CONFLICT (row_key) WHERE row_key IS NOT NULL", statements)
        self.assertNotIn("TRUNCATE", statements)
        self.assertTrue(fake.committed)


if __name__ == "__main__":
    unittest.main()
