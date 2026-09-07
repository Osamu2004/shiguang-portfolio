"""Launch the built macOS app with a temporary ledger and check its HTTP API."""
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "qa-output"
out.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="shiguang-native-") as data:
    with (out / "native.log").open("w") as log:
        proc = subprocess.Popen([str(root / "dist/Shiguang.app/Contents/MacOS/Shiguang")],
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
            for endpoint in ("/", "/api/coin-catalog", "/api/china-coin-catalog", "/api/australia-coin-catalog", "/api/export", "/api/scholar-extension"):
                with urllib.request.urlopen(base + endpoint, timeout=5) as response:
                    content = response.read()
                    assert response.status == 200 and content
                    checks[endpoint] = {"status": response.status, "bytes": len(content)}
            (out / "native-smoke.json").write_text(json.dumps(checks, indent=2))
            print(json.dumps(checks, indent=2))
        finally:
            proc.terminate()
            proc.wait(timeout=10)
