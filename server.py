#!/usr/bin/env python3
"""拾光投资 - 零依赖的本地投资组合服务。"""
import cgi
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC = ROOT / "static"
DATA = Path(os.getenv("SHIGUANG_DATA_DIR", str(Path(__file__).resolve().parent / "data")))
DB = DATA / "portfolio.db"


def db():
    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""CREATE TABLE IF NOT EXISTS holdings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, name TEXT NOT NULL,
      category TEXT NOT NULL DEFAULT '宽基指数', market_value TEXT NOT NULL,
      cost TEXT NOT NULL DEFAULT '0', updated_at TEXT NOT NULL,
      UNIQUE(code), UNIQUE(name)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS health_daily (
      day TEXT PRIMARY KEY, steps INTEGER, sleep_minutes INTEGER,
      resting_heart_rate REAL, active_energy REAL, weight REAL,
      source TEXT NOT NULL DEFAULT 'manual', updated_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS portfolio_snapshots (
      day TEXT PRIMARY KEY, market_value TEXT NOT NULL, source TEXT NOT NULL,
      created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS coins (id TEXT PRIMARY KEY,name TEXT NOT NULL,series TEXT,
      issue_year INTEGER,face_value TEXT NOT NULL DEFAULT '0',material TEXT,image_path TEXT,
      image_source TEXT,image_license TEXT,updated_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS coin_collection (coin_id TEXT PRIMARY KEY,quantity INTEGER NOT NULL,
      grade TEXT,purchase_price TEXT NOT NULL,estimated_value TEXT NOT NULL,storage_location TEXT,notes TEXT,
      updated_at TEXT NOT NULL,FOREIGN KEY(coin_id) REFERENCES coins(id))""")
    return conn


def money(value):
    try:
        result = Decimal(str(value).replace(",", "").replace("¥", "").strip())
        if result < 0 or result > Decimal("100000000000"):
            raise ValueError()
        return str(result.quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        raise ValueError("金额格式不正确")


def clean_item(raw):
    name = str(raw.get("name", "")).strip()[:80]
    if not name:
        raise ValueError("缺少基金名称")
    code = re.sub(r"\D", "", str(raw.get("code", "")))[:6]
    market_value = money(raw.get("market_value", 0))
    return {"code": code, "name": name, "market_value": market_value,
            "cost": money(raw.get("cost", market_value))}


def save_asset_snapshot(conn, now):
    fund = Decimal(str(conn.execute("SELECT COALESCE(SUM(market_value + 0),0) FROM holdings").fetchone()[0]))
    conn.execute("INSERT OR REPLACE INTO portfolio_snapshots VALUES(?,?,?,?)",
                 (datetime.now().date().isoformat(), money(fund), "manual", now))


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        clean = path.split("?", 1)[0].lstrip("/") or "index.html"
        return str(STATIC / clean)

    def json_response(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > 1024 * 1024:
            raise ValueError("请求过大")
        return json.loads(self.rfile.read(size) or b"{}")

    def do_GET(self):
        if self.path == "/api/state":
            with db() as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM holdings ORDER BY market_value + 0 DESC")]
                snapshots = [dict(r) for r in conn.execute("SELECT * FROM portfolio_snapshots ORDER BY day LIMIT 365")]
                coin_row = conn.execute("SELECT COALESCE(SUM(quantity),0),COALESCE(SUM(estimated_value + 0),0) FROM coin_collection").fetchone()
            total = sum(Decimal(r["market_value"]) for r in rows)
            total_cost = sum(Decimal(r["cost"]) for r in rows)
            self.json_response({"holdings": rows, "total": str(total), "totalCost": str(total_cost),
                "profit": str(total-total_cost), "snapshots": snapshots,
                "coins": {"quantity": coin_row[0], "value": str(coin_row[1])}})
            return
        if self.path == "/api/health":
            with db() as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM health_daily ORDER BY day DESC LIMIT 90")]
            self.json_response({"days": rows})
            return
        if self.path == "/api/export":
            with db() as conn:
                payload = {
                    "schemaVersion": 2,
                    "exportedAt": datetime.now().isoformat(),
                    "holdings": [dict(r) for r in conn.execute("SELECT * FROM holdings ORDER BY id")],
                    "healthDaily": [dict(r) for r in conn.execute("SELECT * FROM health_daily ORDER BY day")],
                    "portfolioSnapshots": [dict(r) for r in conn.execute("SELECT * FROM portfolio_snapshots ORDER BY day")],
                }
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="shiguang-backup.json"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data)
            return
        if self.path == "/api/sync/config":
            from sync_engine import load_config
            self.json_response(load_config())
            return
        if self.path == "/api/coins":
            with db() as conn:
                rows=[dict(r) for r in conn.execute("SELECT c.*,x.quantity,x.grade,x.purchase_price,x.estimated_value,x.storage_location,x.notes FROM coins c LEFT JOIN coin_collection x ON x.coin_id=c.id ORDER BY c.issue_year DESC")]
            self.json_response({"coins":rows}); return
        if self.path == "/api/update/check":
            try:
                from updater import check
                self.json_response(check())
            except Exception as exc:
                self.json_response({"error": str(exc)}, 503)
            return
        super().do_GET()

    def do_POST(self):
        try:
            if self.path == "/api/holdings":
                item = clean_item(self.read_json())
                now = datetime.now().isoformat(timespec="seconds")
                with db() as conn:
                    conn.execute("INSERT INTO holdings(code,name,category,market_value,cost,updated_at) VALUES(?,?,?,?,?,?)",
                                 (item["code"] or None, item["name"], "宽基指数", item["market_value"], item["cost"], now))
                    save_asset_snapshot(conn, now)
                self.json_response({"ok": True})
                return
            if self.path == "/api/health":
                self.handle_health()
                return
            if self.path == "/api/health/import":
                self.handle_health_import()
                return
            if self.path == "/api/sync/config":
                from sync_engine import save_config, store_token
                raw = self.read_json(); config = save_config(raw)
                if raw.get("token"): store_token(config["repo"], str(raw["token"]))
                self.json_response({"ok": True, "config": config})
                return
            if self.path == "/api/sync/run":
                from sync_engine import sync
                password = str(self.read_json().get("password", ""))
                self.json_response(sync(DB, password))
                return
            if self.path == "/api/coins":
                raw=self.read_json(); name=str(raw.get("name","")).strip()[:100]
                if not name: raise ValueError("请填写纪念币名称")
                coin_id=str(raw.get("id") or hashlib.sha256(name.encode()).hexdigest()[:16]); now=datetime.now().isoformat(timespec="seconds")
                qty=int(raw.get("quantity") or 0)
                if qty<0: raise ValueError("数量不正确")
                with db() as conn:
                    conn.execute("INSERT OR REPLACE INTO coins VALUES(?,?,?,?,?,?,?,?,?,?)",(coin_id,name,str(raw.get("series",""))[:60],int(raw["issue_year"]) if raw.get("issue_year") else None,money(raw.get("face_value",0)),str(raw.get("material",""))[:40],None,"self","self-owned",now))
                    conn.execute("INSERT OR REPLACE INTO coin_collection VALUES(?,?,?,?,?,?,?,?)",(coin_id,qty,str(raw.get("grade",""))[:30],money(raw.get("purchase_price",0)),money(raw.get("estimated_value",0)),str(raw.get("storage_location",""))[:80],str(raw.get("notes",""))[:500],now))
                self.json_response({"ok":True,"id":coin_id}); return
            if self.path == "/api/update/token":
                from updater import store_token
                store_token(str(self.read_json().get("token", ""))); self.json_response({"ok": True}); return
            if self.path == "/api/update/install":
                from updater import stage_and_install
                result = stage_and_install(); self.json_response(result)
                threading.Thread(target=lambda: (time.sleep(1), os._exit(0)), daemon=True).start(); return
            self.json_response({"error": "未知接口"}, 404)
        except Exception as exc:
            self.json_response({"error": str(exc)}, 400)

    def handle_health(self):
        raw = self.read_json()
        item = validate_health(raw)
        with db() as conn:
            upsert_health(conn, item)
        self.json_response({"ok": True})

    def handle_health_import(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("请上传CSV文件")
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers,
                                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type})
        field = form["file"] if "file" in form else None
        if field is None or not getattr(field, "file", None):
            raise ValueError("未选择CSV文件")
        blob = field.file.read(2 * 1024 * 1024 + 1)
        if len(blob) > 2 * 1024 * 1024:
            raise ValueError("CSV不能超过2MB")
        text = blob.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        count = 0
        with db() as conn:
            for raw in reader:
                mapped = map_health_row(raw)
                upsert_health(conn, validate_health(mapped)); count += 1
        self.json_response({"ok": True, "count": count})


def optional_number(value, kind=float, minimum=0, maximum=None):
    if value is None or str(value).strip() == "":
        return None
    number = kind(str(value).strip())
    if number < minimum or (maximum is not None and number > maximum):
        raise ValueError("健康数据超出合理范围")
    return number


def validate_health(raw):
    day = str(raw.get("day", "")).strip()
    datetime.strptime(day, "%Y-%m-%d")
    return {
        "day": day,
        "steps": optional_number(raw.get("steps"), int, 0, 200000),
        "sleep_minutes": optional_number(raw.get("sleep_minutes"), int, 0, 1440),
        "resting_heart_rate": optional_number(raw.get("resting_heart_rate"), float, 20, 250),
        "active_energy": optional_number(raw.get("active_energy"), float, 0, 20000),
        "weight": optional_number(raw.get("weight"), float, 10, 500),
        "source": str(raw.get("source", "manual"))[:30] or "manual",
    }


def map_health_row(raw):
    aliases = {
        "day": ["day", "date", "日期"], "steps": ["steps", "步数"],
        "sleep_minutes": ["sleep_minutes", "sleep", "睡眠分钟"],
        "resting_heart_rate": ["resting_heart_rate", "resting_hr", "静息心率"],
        "active_energy": ["active_energy", "calories", "活动能量"],
        "weight": ["weight", "weight_kg", "体重"], "source": ["source", "来源"],
    }
    normalized = {str(k).strip().lower(): v for k, v in raw.items()}
    result = {}
    for target, names in aliases.items():
        for name in names:
            if name.lower() in normalized:
                result[target] = normalized[name.lower()]; break
    result.setdefault("source", "csv")
    return result


def upsert_health(conn, item):
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("""INSERT OR REPLACE INTO health_daily
      (day,steps,sleep_minutes,resting_heart_rate,active_energy,weight,source,updated_at)
      VALUES(?,?,?,?,?,?,?,?)""", (item["day"], item["steps"], item["sleep_minutes"],
      item["resting_heart_rate"], item["active_energy"], item["weight"], item["source"], now))


def main():
    port = int(os.getenv("PORT", "8787"))
    db().close()
    print("拾光投资已启动: http://127.0.0.1:%d" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
