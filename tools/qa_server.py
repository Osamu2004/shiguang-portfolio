"""Run an isolated demo ledger; never reads the user's data or GitHub credentials."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="shiguang-qa-") as folder:
        os.environ["SHIGUANG_DATA_DIR"] = folder
        os.environ["PORT"] = "18787"
        import server
        import updater
        with server.db() as conn:
            for day, value in (("2026-08-12", "1000"), ("2026-09-12", "1200"), ("2026-10-01", "0")):
                conn.execute("INSERT INTO stock_snapshots VALUES(?,?,?,?,?)",
                             ("600519", day, "排版测试股票", value, "2026-10-01T09:00:00"))
            conn.execute("INSERT INTO accounts(name,account_type,platform,balance,updated_at) VALUES(?,?,?,?,?)",
                         ("测试储蓄账户", "银行存款", "演示银行", "25000", "2026-09-07T09:00:00"))
            conn.execute("INSERT INTO user_preferences VALUES(1,1,1,?)", ("2026-09-07",))
            for i, category in enumerate(("宽基指数", "海外基金", "债券基金"), 1):
                code = f"{i:06}"
                conn.execute("INSERT INTO holdings(code,name,category,market_value,cost,holding_profit,return_rate,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                             (code, "排版测试·较长的基金名称与人民币份额" + str(i), category,
                              "12345.67", "12000", "345.67", "2.88", "2026-09-07T09:00:00"))
                for day, nav in (("2026-09-01", "1.25"), ("2026-09-04", "1.20"), ("2026-09-07", "1.22")):
                    conn.execute("INSERT INTO fund_market_daily VALUES(?,?,?,?,?,?,?)",
                                 (code, day, nav, nav, "1.67", "QA fixture", "2026-09-07"))
            server.save_asset_snapshot(conn, "2026-09-07T09:00:00")
        with patch.object(server, "fetch_fund_market", return_value=[]), \
             patch.object(server, "fetch_market_index", return_value=[]), \
             patch.object(updater, "check", return_value={"current": updater.VERSION, "latest": updater.VERSION, "available": False}), \
             patch.object(server, "lookup_fund", return_value={"name": "测试基金", "category": "宽基指数"}):
            server.main()
