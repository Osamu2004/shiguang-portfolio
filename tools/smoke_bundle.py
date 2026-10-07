"""Launch the built macOS app with a temporary ledger and check its HTTP API."""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
app = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "dist/Shiguang.app"
out = root / "qa-output"
out.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="shiguang-native-") as data:
    with (out / "native.log").open("w") as log:
        proc = subprocess.Popen([str(app / "Contents/MacOS/Shiguang")],
                                env={**os.environ, "SHIGUANG_DATA_DIR": data, "PORT": "18788"},
                                stdout=log, stderr=log)
        try:
            base = "http://127.0.0.1:18788"
            for attempt in range(80):
                if proc.poll() is not None:
                    raise RuntimeError("Native app exited early; see qa-output/native.log")
                try:
                    with urllib.request.urlopen(base + "/api/state", timeout=1) as response:
                        state = json.load(response)
                    break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(.25)
            else:
                raise RuntimeError("Native app did not start")
            assert state["holdings"] == [] and state["accounts"] == []
            checks = {}
            for endpoint in ("/", "/api/state", "/api/health", "/api/export"):
                with urllib.request.urlopen(base + endpoint, timeout=5) as response:
                    content = response.read()
                    assert response.status == 200 and content
                    checks[endpoint] = {"status": response.status, "bytes": len(content)}
            for endpoint in ("/api/coins", "/api/coin-catalog", "/api/china-coin-catalog",
                             "/api/australia-coin-catalog", "/api/graded-coins", "/coins.css", "/api/stocks",
                             "/api/scholar", "/api/scholar/config", "/api/scholar-extension"):
                try:
                    urllib.request.urlopen(base + endpoint, timeout=5)
                    raise AssertionError(f"Retired endpoint is still available: {endpoint}")
                except urllib.error.HTTPError as error:
                    assert error.code == 404, (endpoint, error.code)
                    checks[endpoint] = {"status": 404}
            foreign_get = urllib.request.Request(base + "/api/state",
                                                 headers={"Origin": "chrome-extension://untrustedexample"})
            try:
                urllib.request.urlopen(foreign_get, timeout=5)
                raise AssertionError("An extension could read the ledger")
            except urllib.error.HTTPError as error:
                assert error.code == 403 and not error.headers.get("Access-Control-Allow-Origin")
                checks["foreign-origin GET /api/state"] = {"status": 403}
            body = json.dumps({"name": "打包测试", "account_type": "现金",
                               "platform": "测试", "balance": "12.34"}).encode()
            for origin, expected in (("https://example.com", 403), (base, 200)):
                request = urllib.request.Request(base + "/api/accounts", data=body,
                                                 headers={"Origin": origin, "Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        status = response.status
                except urllib.error.HTTPError as error:
                    status = error.code
                assert status == expected, (origin, status)
            with urllib.request.urlopen(base + "/api/state", timeout=5) as response:
                saved = json.load(response)
            assert len(saved["accounts"]) == 1 and saved["accounts"][0]["balance"] == "12.34"
            for day, value in (("2026-08-12", "1000"), ("2026-10-01", "0")):
                etf_body = json.dumps({"day": day, "code": "510300", "name": "打包测试 ETF",
                                       "category": "ETF", "market_value": value,
                                       "holding_profit": "0", "return_rate": "0"}).encode()
                request = urllib.request.Request(base + "/api/holdings", data=etf_body,
                                                 headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=5) as response:
                    assert response.status == 200
            with urllib.request.urlopen(base + "/api/holdings/calendar?day=2026-08-12", timeout=5) as response:
                august = json.load(response)
            with urllib.request.urlopen(base + "/api/state", timeout=5) as response:
                after_close = json.load(response)
            assert august["positions"][0]["market_value"] == "1000.00"
            assert after_close["fundTotal"] == "0" and after_close["total"] == "12.34"
            assert after_close["archivedHoldings"][0]["market_value"] == "0.00"
            checks["ETF August/October lifecycle"] = {"status": 200}
            checks["same-origin POST /api/accounts"] = {"status": 200}
            checks["foreign-origin POST /api/accounts"] = {"status": 403}
            (out / "native-smoke.json").write_text(json.dumps(checks, indent=2))
            print(json.dumps(checks, indent=2))
        finally:
            proc.terminate()
            proc.wait(timeout=10)
