"""Regression cases for the September 2026 source and UI audit."""
import io
import json
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

    def post(self, endpoint, payload):
        handler = server.Handler.__new__(server.Handler)
        body = json.dumps(payload).encode()
        handler.path = endpoint
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        responses = []
        handler.json_response = lambda data, status=200: responses.append((status, data))
        handler.do_POST()
        return responses[0]

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
        self.assertEqual(item["cost"], "100.00")

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

    def test_history_restore_uses_same_cost_rule_as_save(self):
        original = {"code": "000001", "name": "测试", "market_value": "1100", "holding_profit": "100", "return_rate": "20"}
        self.assertEqual(self.post("/api/holdings", original)[0], 200)
        with server.db() as conn:
            conn.execute("UPDATE holding_snapshots SET day='2026-09-01'")
        self.assertEqual(self.post("/api/holdings", {**original, "market_value": "1200"})[0], 200)
        from datetime import date
        status, data = self.post("/api/holdings/history/delete", {"code": "000001", "day": date.today().isoformat()})
        self.assertEqual(status, 200, data)
        with server.db() as conn:
            self.assertEqual(conn.execute("SELECT cost FROM holdings").fetchone()[0], "500.00")


if __name__ == "__main__":
    unittest.main()
