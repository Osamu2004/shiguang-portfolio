"""The AI views must reflect app records without changing the database."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class AiApiTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        for name, value in (("DATA", root), ("DB", root / "portfolio.db")):
            p = patch.object(server, name, value)
            p.start()
            self.addCleanup(p.stop)
        server.db().close()

    def request(self, method, path, payload=None, origin=None):
        handler = server.Handler.__new__(server.Handler)
        body = json.dumps(payload or {}).encode()
        handler.path = path
        handler.headers = {"Host": "127.0.0.1:8787", "Content-Length": str(len(body))}
        if origin is not None:
            handler.headers["Origin"] = origin
        handler.rfile = io.BytesIO(body)
        responses = []
        handler.json_response = lambda data, status=200: responses.append((status, data))
        getattr(handler, "do_" + method)()
        return responses[0]

    def test_current_view_matches_holdings_and_cash_without_legacy_cost(self):
        self.assertEqual(self.request("POST", "/api/holdings", {
            "code": "510300", "name": "测试 ETF", "category": "ETF",
            "market_value": "1250", "holding_profit": "250", "return_rate": "25",
        })[0], 200)
        self.assertEqual(self.request("POST", "/api/accounts", {
            "name": "可用现金", "account_type": "证券账户", "platform": "测试券商",
            "balance": "500",
        })[0], 200)
        status, data = self.request("GET", "/api/ai/v1/portfolio")
        self.assertEqual(status, 200)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["totals"]["assets"], "1750.00")
        self.assertEqual(data["totals"]["current_holding_return_rate_pct"], "25.00")
        self.assertEqual(data["holdings"][0]["purchase_channel"], None)
        self.assertNotIn("cost", data["holdings"][0])
        self.assertEqual(data["cash_accounts"][0]["balance"], "500.00")
        self.assertEqual(data["data_basis"]["live_broker_or_alipay_sync"], False)

    def test_dated_view_retains_cleared_etf_but_does_not_invent_cash(self):
        etf = {"code": "510300", "name": "测试 ETF", "category": "ETF",
               "holding_profit": "0", "return_rate": "0"}
        self.request("POST", "/api/holdings", {**etf, "day": "2026-08-12", "market_value": "1000"})
        self.request("POST", "/api/holdings", {**etf, "day": "2026-10-01", "market_value": "0"})
        august = self.request("GET", "/api/ai/v1/holdings?day=2026-08-12")[1]
        october = self.request("GET", "/api/ai/v1/holdings?day=2026-10-01")[1]
        current = self.request("GET", "/api/ai/v1/portfolio")[1]
        self.assertEqual(august["holdings_market_value"], "1000.00")
        self.assertFalse(august["positions"][0]["closed"])
        self.assertEqual(october["holdings_market_value"], "0.00")
        self.assertTrue(october["positions"][0]["closed"])
        self.assertEqual(october["positions"][0]["closed_on"], "2026-10-01")
        self.assertFalse(october["historical_cash_available"])
        self.assertNotIn("total_assets", october)
        self.assertEqual(current["holdings"], [])

    def test_read_only_cli_and_http_validation(self):
        self.request("POST", "/api/holdings", {
            "code": "510300", "name": "测试 ETF", "category": "ETF",
            "market_value": "100", "holding_profit": "0", "return_rate": "0",
        })
        before = server.DB.read_bytes()
        script = Path(__file__).parents[1] / "tools" / "read_portfolio.py"
        result = subprocess.run([sys.executable, str(script), "--db", str(server.DB)],
                                capture_output=True, text=True, check=True,
                                env={**os.environ, "PYTHONIOENCODING": "cp1252"})
        self.assertEqual(json.loads(result.stdout)["totals"]["assets"], "100.00")
        self.assertEqual(json.loads(result.stdout)["holdings"][0]["name"], "测试 ETF")
        self.assertEqual(server.DB.read_bytes(), before)
        self.assertEqual(self.request("GET", "/api/ai/v1/holdings?day=bad")[0], 400)
        self.assertEqual(self.request("GET", "/api/ai/v1/holdings?day=2026-08-12&day=2026-08-13")[0], 400)
        self.assertEqual(self.request("GET", "/api/ai/v1/portfolio",
                                      origin="https://example.com")[0], 403)


if __name__ == "__main__":
    unittest.main()
