import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location("app", Path(__file__).parents[1] / "server.py")
app = importlib.util.module_from_spec(spec); spec.loader.exec_module(app)

class CoreTest(unittest.TestCase):
    def test_database_adds_archive_column_without_losing_holdings(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            with mock.patch.object(app, "DATA", data), mock.patch.object(app, "DB", data / "portfolio.db"):
                with app.db() as conn:
                    columns = {row[1] for row in conn.execute("PRAGMA table_info(holdings)")}
                    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    conn.execute("INSERT INTO holdings(code,name,category,market_value,cost,updated_at) VALUES(?,?,?,?,?,?)",
                                 ("050025", "测试基金", "海外基金", "100", "90", "2026-08-25T10:00:00"))
                with app.db() as conn:
                    self.assertIn("archived_at", columns)
                    self.assertIn("audit_logs", tables)
                    self.assertIn("deleted_records", tables)
                    self.assertEqual(conn.execute("SELECT name FROM holdings WHERE code='050025'").fetchone()[0], "测试基金")

    def test_holding_keeps_cost_separate_from_value(self):
        item = app.clean_item({"name": "ETF", "category": "债券基金", "cost": "1000", "market_value": "1120"})
        self.assertEqual(item["cost"], "1000.00")
        self.assertEqual(item["market_value"], "1120.00")
        self.assertEqual(item["category"], "债券基金")

    def test_holding_rejects_unknown_category(self):
        with self.assertRaisesRegex(ValueError, "基金类别"):
            app.clean_item({"name": "ETF", "category": "未知", "market_value": "100"})

    def test_holding_cost_is_derived_from_alipay_profit(self):
        item = app.clean_item({"name": "ETF", "market_value": "1120", "holding_profit": "120"})
        self.assertEqual(item["cost"], "1000.00")

    def test_negative_holding_profit_is_supported(self):
        item = app.clean_item({"name": "ETF", "market_value": "920", "holding_profit": "-80"})
        self.assertEqual(item["cost"], "1000.00")

    def test_fund_code_lookup_returns_chinese_name(self):
        response = mock.MagicMock()
        payload = {"Datas": {"SHORTNAME": "博时标普500ETF联接A", "FULLNAME": "基金全称",
                             "FTYPE": "指数型-海外股票"}}
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        with mock.patch.object(app, "load_fund_catalog", return_value={}), \
             mock.patch.object(app.urllib.request, "urlopen", return_value=response):
            fund = app.lookup_fund("050025")
        self.assertEqual(fund["name"], "博时标普500ETF联接A")
        self.assertEqual(fund["category"], "海外基金")

    def test_fund_lookup_prefers_local_catalog(self):
        catalog = {"050025": {"name": "博时标普500ETF联接A", "fundType": "指数型-海外股票",
                              "category": "海外基金"}}
        with mock.patch.object(app, "load_fund_catalog", return_value=catalog), \
             mock.patch.object(app.urllib.request, "urlopen") as opened:
            fund = app.lookup_fund("050025")
        self.assertEqual(fund["name"], "博时标普500ETF联接A")
        opened.assert_not_called()

    def test_two_of_three_alipay_fields_are_enough(self):
        item = app.clean_item({"name": "ETF", "market_value": "1100", "return_rate": "10%"})
        self.assertEqual(item["cost"], "1000.00")
        self.assertEqual(item["holding_profit"], "100.00")

    def test_profit_and_rate_calculate_market_value(self):
        item = app.clean_item({"name": "ETF", "holding_profit": "100", "return_rate": "10"})
        self.assertEqual(item["market_value"], "1100.00")
        self.assertEqual(item["cost"], "1000.00")

    def test_inconsistent_three_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "不一致"):
            app.clean_item({"name": "ETF", "market_value": "1100", "holding_profit": "100", "return_rate": "20"})

    def test_consistent_rounded_rate_is_accepted(self):
        item = app.clean_item({"name": "ETF", "market_value": "1100", "holding_profit": "100", "return_rate": "10.00"})
        self.assertEqual(item["return_rate"], "10.00")

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
