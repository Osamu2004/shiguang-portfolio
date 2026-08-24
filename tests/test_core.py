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

if __name__ == "__main__": unittest.main()
