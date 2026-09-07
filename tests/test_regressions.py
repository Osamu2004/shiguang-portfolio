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

    def test_backup_includes_collection_and_research_tables(self):
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/api/export"
        handler.wfile = io.BytesIO()
        handler.send_response = lambda *args: None
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        handler.do_GET()
        payload = json.loads(handler.wfile.getvalue())
        for key in ("coins", "coinCollection", "gradedCoins", "scholarProfiles", "scholarSnapshots", "scholarPapers", "scholarPaperSnapshots", "scholarSettings"):
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

    def test_quantity_edit_preserves_cost_and_notes_and_deletion_syncs(self):
        coin_id = server.china_coin_catalog()["coins"][0]["id"]
        status, data = self.post("/api/coin-collection", {
            "coin_id": coin_id, "quantity": 1, "purchase_price": "123", "notes": "测试备注"})
        self.assertEqual(status, 200, data)
        status, data = self.post("/api/coin-collection", {"coin_id": coin_id, "quantity": 2})
        self.assertEqual(status, 200, data)
        with server.db() as conn:
            row = conn.execute("SELECT * FROM coin_collection").fetchone()
            self.assertEqual(row["purchase_price"], "123.00")
            self.assertEqual(row["notes"], "测试备注")
        old = sync_engine.export_data(server.DB)
        self.assertEqual(self.post("/api/coin-collection", {"coin_id": coin_id, "quantity": 0})[0], 200)
        merged = sync_engine.merge_vaults(sync_engine.export_data(server.DB), old)
        sync_engine.import_data(server.DB, merged)
        with server.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM coin_collection").fetchone()[0], 0)

    def test_recreation_wins_over_older_tombstone(self):
        local = {"tables": {"coin_collection": [{"coin_id": "a", "quantity": 2, "updated_at": "2026-09-07"}]}}
        remote = {"tables": {"deleted_records": [{"table_name": "coin_collection", "record_key": "a", "deleted_at": "2026-09-06"}]}}
        for first, second in ((local, remote), (remote, local)):
            merged = sync_engine.merge_vaults(first, second)
            self.assertEqual(len(merged["tables"]["coin_collection"]), 1)
            self.assertEqual(merged["tables"]["deleted_records"], [])

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
