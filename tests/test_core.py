import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("app", Path(__file__).parents[1] / "server.py")
app = importlib.util.module_from_spec(spec); spec.loader.exec_module(app)

class CoreTest(unittest.TestCase):
    def test_holding_keeps_cost_separate_from_value(self):
        item = app.clean_item({"name": "ETF", "category": "债券基金", "cost": "1000", "market_value": "1120"})
        self.assertEqual(item["cost"], "1000.00")
        self.assertEqual(item["market_value"], "1120.00")
        self.assertEqual(item["category"], "债券基金")

    def test_holding_rejects_unknown_category(self):
        with self.assertRaisesRegex(ValueError, "基金类别"):
            app.clean_item({"name": "ETF", "category": "未知", "market_value": "100"})

    def test_cash_account_supports_payment_platform(self):
        item = app.clean_account({"name": "支付宝余额", "account_type": "电子钱包",
                                  "platform": "支付宝", "balance": "88.6"})
        self.assertEqual(item["platform"], "支付宝")
        self.assertEqual(item["balance"], "88.60")

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
