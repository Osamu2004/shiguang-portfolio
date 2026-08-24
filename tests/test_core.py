import importlib.util
import json
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("app", Path(__file__).parents[1] / "server.py")
app = importlib.util.module_from_spec(spec); spec.loader.exec_module(app)

class CoreTest(unittest.TestCase):
    def test_model_json_accepts_fence(self):
        text = '```json\n{"holdings":[{"code":"000001","name":"基金A","market_value":"1,234.5","confidence":"high"}]}\n```'
        self.assertEqual(app.parse_model_json(text)[0]["market_value"], "1234.50")

    def test_diff_has_three_states(self):
        old = [{"id": 1, "code": "1", "name": "A", "market_value": "100"},
               {"id": 2, "code": "2", "name": "B", "market_value": "50"}]
        new = [{"code": "1", "name": "A", "market_value": "120.00", "confidence": "high"},
               {"code": "3", "name": "C", "market_value": "20.00", "confidence": "high"}]
        self.assertEqual([x["action"] for x in app.diff_holdings(old, new)], ["update", "new", "missing"])

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
