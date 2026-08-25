import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location("app", Path(__file__).parents[1] / "server.py")
app = importlib.util.module_from_spec(spec); spec.loader.exec_module(app)

class CoreTest(unittest.TestCase):
    def test_database_migrates_existing_fund_strategy_for_drawdown(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder); path=data/"portfolio.db"
            with sqlite3.connect(path) as conn:
                conn.execute("""CREATE TABLE fund_strategies (code TEXT PRIMARY KEY,mode TEXT NOT NULL,
                  daily_amount TEXT NOT NULL,per_drop_pct_amount TEXT NOT NULL,max_daily_amount TEXT NOT NULL,updated_at TEXT NOT NULL)""")
                conn.execute("INSERT INTO fund_strategies VALUES(?,?,?,?,?,?)",("050025","daily","10","0","0","2026-08-26"))
            with mock.patch.object(app,"DATA",data),mock.patch.object(app,"DB",path):
                with app.db() as conn:
                    row=conn.execute("SELECT * FROM fund_strategies WHERE code='050025'").fetchone()
                    self.assertEqual(row["drawdown_budget"],"0")
                    self.assertEqual(row["executed_drawdown_stage"],0)

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

    def test_holding_preserves_platform_values(self):
        item = app.clean_item({"name": "ETF", "category": "债券基金", "market_value": "5981.99",
                               "holding_profit": "-518.01", "return_rate": "-8.09%"})
        self.assertEqual(item["holding_profit"], "-518.01")
        self.assertEqual(item["return_rate"], "-8.09")
        self.assertEqual(item["market_value"], "5981.99")
        self.assertEqual(item["category"], "债券基金")

    def test_holding_rejects_unknown_category(self):
        with self.assertRaisesRegex(ValueError, "基金类别"):
            app.clean_item({"name": "ETF", "category": "未知", "market_value": "100", "holding_profit": "0", "return_rate": "0"})

    def test_negative_holding_profit_is_supported(self):
        item = app.clean_item({"name": "ETF", "market_value": "920", "holding_profit": "-80", "return_rate": "-7.41"})
        self.assertEqual(item["holding_profit"], "-80.00")

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

    def test_public_fund_market_parses_official_nav_change(self):
        response = mock.MagicMock()
        payload = {"Datas": [{"FSRQ":"2026-08-25","DWJZ":"1.2345",
          "LJJZ":"2.3456","JZZZL":"-1.27"}]}
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        with mock.patch.object(app.urllib.request, "urlopen", return_value=response):
            rows = app.fetch_fund_market("050025")
        self.assertEqual(rows[0]["day"], "2026-08-25")
        self.assertEqual(rows[0]["daily_change_pct"], "-1.27")
        self.assertEqual(rows[0]["unit_nav"], "1.2345")

    def test_fund_investment_strategy_defaults_to_no_money(self):
        self.assertEqual(app.planned_investment(None, {"daily_change_pct":"-3"}), 0)

    def test_drop_strategy_scales_with_public_daily_change_and_cap(self):
        strategy={"mode":"drop","daily_amount":"0","per_drop_pct_amount":"100","max_daily_amount":"200"}
        self.assertEqual(app.planned_investment(strategy,{"daily_change_pct":"-2.30"}), 200)
        self.assertEqual(app.planned_investment(strategy,{"daily_change_pct":"1.20"}), 0)

    def test_drawdown_strategy_uses_historical_high_and_unexecuted_tranches(self):
        strategy={"mode":"drawdown","drawdown_budget":"1000","executed_drawdown_stage":1}
        history=[{"unit_nav":"2.00"},{"unit_nav":"1.20"}]
        market={"unit_nav":"1.20","daily_change_pct":"-1"}
        self.assertEqual(app.drawdown_status(strategy,market,history)["triggered_stage"],3)
        self.assertEqual(app.planned_investment(strategy,market,history),500)

    def test_drawdown_strategy_does_not_repeat_executed_stage(self):
        strategy={"mode":"drawdown","drawdown_budget":"1000","executed_drawdown_stage":2}
        history=[{"unit_nav":"2.00"},{"unit_nav":"1.60"}]
        self.assertEqual(app.planned_investment(strategy,{"unit_nav":"1.60"},history),0)

    def test_all_three_platform_fields_are_required(self):
        with self.assertRaisesRegex(ValueError, "原样填写"):
            app.clean_item({"name": "ETF", "market_value": "1100", "return_rate": "10%"})

    def test_inconsistent_platform_fields_are_still_preserved(self):
        item = app.clean_item({"name": "ETF", "market_value": "1100", "holding_profit": "100", "return_rate": "20"})
        self.assertEqual(item["return_rate"], "20.00")

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
