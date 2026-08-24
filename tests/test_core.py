import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("app", Path(__file__).parents[1] / "server.py")
app = importlib.util.module_from_spec(spec); spec.loader.exec_module(app)

class CoreTest(unittest.TestCase):
    def test_rejects_negative_money(self):
        with self.assertRaises(ValueError): app.money("-1")

    def test_health_csv_aliases(self):
        row = app.map_health_row({"日期": "2026-08-25", "步数": "8000", "睡眠分钟": "480"})
        value = app.validate_health(row)
        self.assertEqual(value["steps"], 8000)
        self.assertEqual(value["sleep_minutes"], 480)

    def test_health_rejects_impossible_sleep(self):
        with self.assertRaises(ValueError):
            app.validate_health({"day": "2026-08-25", "sleep_minutes": 1500})

if __name__ == "__main__": unittest.main()
