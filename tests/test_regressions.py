"""Regression cases for the September 2026 source and UI audit."""
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
import sync_engine


class RegressionTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        for name, value in (("DATA", root), ("DB", root / "portfolio.db")):
            p = patch.object(server, name, value)
            p.start()
            self.addCleanup(p.stop)
        with server.db():
            pass

    def post(self, endpoint, payload, origin=None, host="127.0.0.1:8787"):
        handler = server.Handler.__new__(server.Handler)
        body = json.dumps(payload).encode()
        handler.path = endpoint
        handler.headers = {"Content-Length": str(len(body)), "Host": host}
        if origin is not None:
            handler.headers["Origin"] = origin
        handler.rfile = io.BytesIO(body)
        responses = []
        handler.json_response = lambda data, status=200: responses.append((status, data))
        handler.do_POST()
        return responses[0]

    def get_json(self, endpoint):
        handler = server.Handler.__new__(server.Handler)
        handler.path = endpoint
        handler.headers = {}
        responses = []
        handler.json_response = lambda data, status=200: responses.append((status, data))
        handler.do_GET()
        return responses[0]

    def test_etf_august_purchase_october_clear_and_date_paging(self):
        self.assertEqual(self.post("/api/accounts", {"name":"可用现金", "account_type":"证券账户",
            "platform":"测试", "balance":"500"})[0], 200)
        etf = {"code":"510300", "name":"沪深300 ETF", "category":"ETF",
               "holding_profit":"0", "return_rate":"0"}
        self.assertEqual(self.post("/api/holdings", {**etf,"day":"2026-08-12","market_value":"1000"})[0], 200)
        self.assertEqual(self.post("/api/holdings", {**etf,"day":"2026-09-12","market_value":"1250",
            "holding_profit":"250","return_rate":"25"})[0], 200)
        self.assertEqual(self.post("/api/holdings", {**etf,"day":"2026-10-01","market_value":"0"})[0], 200)
        august = self.get_json("/api/holdings/calendar?day=2026-08-12")[1]
        september = self.get_json("/api/holdings/calendar?day=2026-09-12")[1]
        october = self.get_json("/api/holdings/calendar?day=2026-10-01")[1]
        self.assertEqual(august["positions"][0]["market_value"], "1000.00")
        self.assertFalse(august["positions"][0]["closed"])
        self.assertEqual(september["positions"][0]["holding_profit"], "250.00")
        self.assertEqual(september["positions"][0]["return_rate"], "25.00")
        self.assertTrue(october["positions"][0]["closed"])
        self.assertEqual(october["snapshotDays"], ["2026-08-12", "2026-09-12", "2026-10-01"])
        current = self.get_json("/api/state")[1]
        self.assertEqual(current["total"], "500.00")
        self.assertEqual(current["accounts"][0]["balance"], "500.00")
        self.assertEqual(current["holdings"], [])
        self.assertEqual(current["archivedHoldings"][0]["market_value"], "0.00")
        self.assertEqual(self.post("/api/holdings", {**etf,"day":"2026-10-02","market_value":"0",
            "name":"另一只 ETF", "code":"510500"})[0], 400)

    def test_backdated_etf_snapshot_does_not_replace_newer_current_value(self):
        etf = {"code":"510300", "name":"沪深300 ETF", "category":"ETF",
               "holding_profit":"0", "return_rate":"0"}
        self.assertEqual(self.post("/api/holdings", {**etf,"market_value":"2000"})[0], 200)
        self.assertEqual(self.post("/api/holdings", {**etf,"day":"2026-08-12","market_value":"1000"})[0], 200)
        self.assertEqual(self.get_json("/api/state")[1]["fundTotal"], "2000.00")
        self.assertEqual(self.get_json("/api/holdings/calendar?day=2026-08-12")[1]["positions"][0]["market_value"], "1000.00")

    def test_deleting_etf_clear_snapshot_restores_current_holding(self):
        etf = {"code":"510300", "name":"沪深300 ETF", "category":"ETF",
               "holding_profit":"0", "return_rate":"0"}
        self.post("/api/holdings", {**etf,"day":"2026-08-12","market_value":"1000"})
        self.post("/api/holdings", {**etf,"day":"2026-10-01","market_value":"0"})
        self.assertEqual(self.post("/api/holdings/history/delete", {"code":"510300","day":"2026-10-01"})[0], 200)
        current = self.get_json("/api/state")[1]
        self.assertEqual(current["fundTotal"], "1000.00")
        self.assertEqual(len(current["holdings"]), 1)

    def test_cleared_etf_requires_new_nonzero_snapshot_to_reopen(self):
        etf = {"code":"510300", "name":"沪深300 ETF", "category":"ETF",
               "holding_profit":"0", "return_rate":"0"}
        self.post("/api/holdings", {**etf,"day":"2026-08-12","market_value":"1000"})
        self.post("/api/holdings", {**etf,"day":"2026-10-01","market_value":"0"})
        self.assertEqual(self.post("/api/holdings/restore", {"code":"510300"})[0], 400)
        self.assertEqual(self.post("/api/holdings", {**etf,"day":"2026-10-05","market_value":"1100"})[0], 200)
        self.assertTrue(self.get_json("/api/holdings/calendar?day=2026-10-02")[1]["positions"][0]["closed"])
        self.assertFalse(self.get_json("/api/holdings/calendar?day=2026-10-05")[1]["positions"][0]["closed"])
        self.assertEqual(self.get_json("/api/state")[1]["fundTotal"], "1100.00")

    def test_old_standalone_stock_records_are_preserved_but_not_counted(self):
        with server.db() as conn:
            conn.execute("INSERT INTO stock_snapshots VALUES(?,?,?,?,?)",
                         ("510300", "2026-08-12", "旧版误录 ETF", "1000.00", "2026-10-01"))
        self.assertEqual(self.get_json("/api/state")[1]["total"], "0")
        self.assertEqual(sync_engine.export_data(server.DB)["tables"]["stock_snapshots"][0]["market_value"], "1000.00")

    def test_foreign_origin_cannot_modify_local_data(self):
        payload = {"name": "跨站账户", "account_type": "现金", "platform": "测试", "balance": "100"}
        self.assertEqual(self.post("/api/accounts", payload, origin="https://example.com")[0], 403)
        self.assertEqual(self.post("/api/accounts", payload, origin="http://example.com",
                                   host="example.com")[0], 403)
        self.assertEqual(self.post("/api/accounts", payload, host="[invalid")[0], 403)
        with server.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 0)
        self.assertEqual(self.post("/api/accounts", payload,
                                   origin="http://127.0.0.1:8787")[0], 200)

    def test_extension_access_is_limited_to_scholar_import(self):
        origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/api/state"
        handler.headers = {"Host": "127.0.0.1:8787", "Origin": origin}
        self.assertFalse(handler.request_allowed())
        self.assertEqual(handler.extension_origin(), "")
        status, data = self.post("/api/scholar/import", {
            "profile": {"id": "test", "name": "测试研究者"}, "papers": []
        }, origin=origin)
        self.assertEqual(status, 200, data)

    def test_repeated_save_does_not_collide_in_audit_log(self):
        with server.db() as conn:
            for value in (100, 200):
                server.audit(conn, "SAVE", "same holding", {"value": value}, "2026-09-07T10:00:00")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0], 2)

    def test_invalid_nonfinite_values_are_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            for cleaner in (server.money, server.signed_money, server.optional_number):
                with self.subTest(value=value, cleaner=cleaner.__name__):
                    with self.assertRaises(ValueError):
                        cleaner(value)
            status, _ = self.post("/api/holdings", {
                "name": "测试", "market_value": "100", "holding_profit": "0", "return_rate": value})
            self.assertEqual(status, 400)

    def test_complete_loss_can_be_recorded(self):
        item = server.clean_item({"name": "测试", "market_value": "0", "holding_profit": "-100", "return_rate": "-100"})
        self.assertEqual(item["holding_profit"], "-100.00")
        self.assertNotIn("cost", item)

    def test_rounded_platform_rate_does_not_create_inferred_principal(self):
        payload = {"code": "000001", "name": "测试", "market_value": "5981.99",
                   "holding_profit": "-518.01", "return_rate": "-7.97"}
        self.assertEqual(self.post("/api/holdings", payload)[0], 200)
        with server.db() as conn:
            self.assertEqual(conn.execute("SELECT cost FROM holdings").fetchone()[0], "0.00")
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/api/state"
        handler.headers = {}
        responses = []
        handler.json_response = lambda data, status=200: responses.append(data)
        handler.do_GET()
        self.assertIsNone(responses[0]["totalCost"])
        self.assertEqual(responses[0]["profit"], "-518.01")

    def test_existing_legacy_principal_is_preserved_but_not_recomputed(self):
        with server.db() as conn:
            conn.execute("""INSERT INTO holdings(code,name,category,market_value,cost,updated_at,holding_profit,return_rate)
                VALUES(?,?,?,?,?,?,?,?)""", ("000001", "测试", "宽基指数", "1100.00", "1000.00",
                                       "2026-09-01", "100.00", "10.00"))
        self.assertEqual(self.post("/api/holdings", {"code": "000001", "name": "测试",
            "market_value": "1200", "holding_profit": "200", "return_rate": "20"})[0], 200)
        with server.db() as conn:
            self.assertEqual(conn.execute("SELECT cost FROM holdings").fetchone()[0], "1000.00")

    def test_code_correction_moves_history_and_strategy_across_devices(self):
        with server.db() as conn:
            conn.execute("""INSERT INTO holdings(code,name,category,market_value,cost,updated_at,holding_profit,return_rate)
                VALUES(?,?,?,?,?,?,?,?)""", ("000001", "测试", "宽基指数", "100", "90", "2026-09-01", "10", "11.11"))
            conn.execute("INSERT INTO holding_snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                         ("2026-09-01", "000001", "000001", "测试", "100", "10", "11.11", "manual", "2026-09-01"))
            conn.execute("""INSERT INTO fund_strategies(code,mode,daily_amount,per_drop_pct_amount,max_daily_amount,updated_at)
                VALUES(?,?,?,?,?,?)""", ("000001", "daily", "10", "0", "0", "2026-09-01"))
        stale = sync_engine.export_data(server.DB)
        stale_db = server.DATA / "stale.db"
        shutil.copy2(server.DB, stale_db)
        status, data = self.post("/api/holdings", {"code": "000002", "name": "测试",
            "market_value": "200", "holding_profit": "20", "return_rate": "11.11"})
        self.assertEqual(status, 200, data)
        fresh = sync_engine.export_data(server.DB)
        for local, remote in ((stale, fresh), (fresh, stale)):
            merged = sync_engine.merge_vaults(local, remote)
            self.assertEqual([row["code"] for row in merged["tables"]["holdings"]], ["000002"])
            self.assertEqual({row["holding_key"] for row in merged["tables"]["holding_snapshots"]}, {"000002"})
            self.assertEqual([row["code"] for row in merged["tables"]["fund_strategies"]], ["000002"])
            sync_engine.import_data(stale_db, merged)
            with server.sqlite3.connect(stale_db) as conn:
                self.assertEqual(conn.execute("SELECT code FROM holdings").fetchone()[0], "000002")
                self.assertEqual({row[0] for row in conn.execute("SELECT holding_key FROM holding_snapshots")}, {"000002"})
                self.assertEqual(conn.execute("SELECT code FROM fund_strategies").fetchone()[0], "000002")

    def test_backup_includes_research_and_retired_archive(self):
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/api/export"
        handler.wfile = io.BytesIO()
        handler.send_response = lambda *args: None
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        handler.do_GET()
        payload = json.loads(handler.wfile.getvalue())
        for key in ("legacyArchive", "scholarProfiles", "scholarSnapshots", "scholarPapers", "scholarPaperSnapshots", "scholarSettings"):
            self.assertIn(key, payload)

    def test_static_path_stays_inside_static_directory(self):
        handler = server.Handler.__new__(server.Handler)
        for url in ("/../server.py", "/%2e%2e/server.py", "/../../data/portfolio.db"):
            with self.subTest(url=url):
                self.assertTrue(Path(handler.translate_path(url)).is_relative_to(server.STATIC.resolve()))

    def test_request_body_must_be_an_object(self):
        for value in ([], None, 12):
            status, data = self.post("/api/accounts", value)
            self.assertEqual(status, 400)
            self.assertIn("JSON 对象", data["error"])

    def test_removed_routes_and_old_tables_are_retained(self):
        status, data = self.post("/api/coin-collection", {"coin_id": "old", "quantity": 1})
        self.assertEqual(status, 404)
        with server.db() as conn:
            self.assertNotIn("coins", {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")})
            conn.execute("CREATE TABLE coins (id TEXT PRIMARY KEY, name TEXT, updated_at TEXT)")
            conn.execute("INSERT INTO coins VALUES ('old', '旧藏品', '2026-09-01')")
        with server.db() as conn:
            self.assertEqual(conn.execute("SELECT name FROM coins WHERE id='old'").fetchone()[0], "旧藏品")
        archive = sync_engine.export_data(server.DB)
        self.assertEqual(archive["tables"]["coins"][0]["name"], "旧藏品")
        self.assertEqual(sync_engine.merge_vaults({"tables": {}}, archive)["tables"]["coins"][0]["id"], "old")
        sync_engine.import_data(server.DB, archive)
        with server.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM coins").fetchone()[0], 1)

    def test_old_preference_column_is_ignored(self):
        with server.db() as conn:
            conn.execute("ALTER TABLE user_preferences ADD COLUMN show_coins INTEGER NOT NULL DEFAULT 1")
        status, _ = self.post("/api/preferences", {"show_health": True, "show_research": False})
        self.assertEqual(status, 200)
        synced = sync_engine.export_data(server.DB)["tables"]["user_preferences"][0]
        self.assertEqual(synced["show_health"], 1)
        self.assertNotIn("show_coins", synced)
        remote = {"tables": {"user_preferences": [{"id": 1, "show_health": 0,
                  "show_research": 1, "show_coins": 1, "updated_at": "2099-01-01"}]}}
        merged = sync_engine.merge_vaults({"tables": {}}, remote)
        sync_engine.import_data(server.DB, merged)
        with server.db() as conn:
            row = conn.execute("SELECT show_health,show_research FROM user_preferences").fetchone()
            self.assertEqual(tuple(row), (0, 1))

    def test_market_merge_uses_fetch_time_not_export_time(self):
        old = {"updatedAt": "2026-09-09", "tables": {"fund_market_daily": [{"code": "1", "day": "2026-09-01", "unit_nav": "1", "fetched_at": "2026-09-01"}]}}
        new = {"updatedAt": "2026-09-07", "tables": {"fund_market_daily": [{"code": "1", "day": "2026-09-01", "unit_nav": "2", "fetched_at": "2026-09-07"}]}}
        for first, second in ((old, new), (new, old)):
            self.assertEqual(sync_engine.merge_vaults(first, second)["tables"]["fund_market_daily"][0]["unit_nav"], "2")

    def test_no_update_does_not_exit_application(self):
        with patch("updater.stage_and_install", return_value={"ok": True, "message": "已是最新版本"}), \
             patch.object(server.threading, "Thread") as thread:
            self.assertEqual(self.post("/api/update/install", {})[0], 200)
            thread.assert_not_called()

    def test_history_restore_does_not_infer_principal(self):
        original = {"code": "000001", "name": "测试", "market_value": "1100", "holding_profit": "100", "return_rate": "20"}
        self.assertEqual(self.post("/api/holdings", original)[0], 200)
        with server.db() as conn:
            conn.execute("UPDATE holding_snapshots SET day='2026-09-01'")
        self.assertEqual(self.post("/api/holdings", {**original, "market_value": "1200"})[0], 200)
        from datetime import date
        status, data = self.post("/api/holdings/history/delete", {"code": "000001", "day": date.today().isoformat()})
        self.assertEqual(status, 200, data)
        with server.db() as conn:
            self.assertEqual(conn.execute("SELECT cost FROM holdings").fetchone()[0], "0.00")


if __name__ == "__main__":
    unittest.main()
