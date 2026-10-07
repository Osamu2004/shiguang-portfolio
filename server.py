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
import math
import uuid
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import concurrent.futures
from datetime import datetime
from decimal import Decimal, InvalidOperation
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import certifi
import holding_calendar

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC = ROOT / "static"
RESOURCES = ROOT / "resources"
DATA = Path(os.getenv("SHIGUANG_DATA_DIR", str(Path(__file__).resolve().parent / "data")))
DB = DATA / "portfolio.db"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
FUND_CATALOG = DATA / "fund-catalog.json"
MARKET_INDICES = (
    ("000001", "上证指数", "A股", "1.000001"),
    ("000300", "沪深300", "A股", "1.000300"),
    ("399006", "创业板指", "A股", "0.399006"),
    ("HSI", "恒生指数", "港股", "100.HSI"),
    ("NDX", "纳斯达克100", "美股", "100.NDX"),
    ("SPX", "标普500", "美股", "100.SPX"),
)


def db():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""CREATE TABLE IF NOT EXISTS holdings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, name TEXT NOT NULL,
      category TEXT NOT NULL DEFAULT '宽基指数', market_value TEXT NOT NULL,
      cost TEXT NOT NULL DEFAULT '0', updated_at TEXT NOT NULL,
      UNIQUE(code), UNIQUE(name)
    )""")
    holding_columns = {row[1] for row in conn.execute("PRAGMA table_info(holdings)")}
    if "archived_at" not in holding_columns:
        conn.execute("ALTER TABLE holdings ADD COLUMN archived_at TEXT")
    if "holding_profit" not in holding_columns:
        conn.execute("ALTER TABLE holdings ADD COLUMN holding_profit TEXT NOT NULL DEFAULT '0.00'")
        conn.execute("UPDATE holdings SET holding_profit=printf('%.2f',(market_value + 0) - (cost + 0))")
    if "return_rate" not in holding_columns:
        conn.execute("ALTER TABLE holdings ADD COLUMN return_rate TEXT NOT NULL DEFAULT '0.00'")
    conn.execute("""CREATE TABLE IF NOT EXISTS accounts (
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
      account_type TEXT NOT NULL, platform TEXT NOT NULL, balance TEXT NOT NULL,
      updated_at TEXT NOT NULL
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
    conn.execute("""CREATE TABLE IF NOT EXISTS holding_snapshots (
      day TEXT NOT NULL, holding_key TEXT NOT NULL, code TEXT, name TEXT NOT NULL,
      market_value TEXT NOT NULL, holding_profit TEXT NOT NULL, return_rate TEXT NOT NULL,
      source TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(day,holding_key)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS fund_market_daily (
      code TEXT NOT NULL,day TEXT NOT NULL,unit_nav TEXT NOT NULL,cumulative_nav TEXT,
      daily_change_pct TEXT NOT NULL,source TEXT NOT NULL,fetched_at TEXT NOT NULL,
      PRIMARY KEY(code,day))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS market_index_daily (
      code TEXT NOT NULL,day TEXT NOT NULL,close TEXT NOT NULL,daily_change_pct TEXT NOT NULL,
      source TEXT NOT NULL,fetched_at TEXT NOT NULL,PRIMARY KEY(code,day))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS fund_strategies (
      code TEXT PRIMARY KEY,mode TEXT NOT NULL DEFAULT 'none',daily_amount TEXT NOT NULL DEFAULT '0',
      per_drop_pct_amount TEXT NOT NULL DEFAULT '0',max_daily_amount TEXT NOT NULL DEFAULT '0',
      drawdown_budget TEXT NOT NULL DEFAULT '0',executed_drawdown_stage INTEGER NOT NULL DEFAULT 0,
      drawdown_thresholds TEXT NOT NULL DEFAULT '10,20,35,50',
      drawdown_allocations TEXT NOT NULL DEFAULT '20,20,30,30',
      updated_at TEXT NOT NULL)""")
    strategy_columns = {row[1] for row in conn.execute("PRAGMA table_info(fund_strategies)")}
    if "drawdown_budget" not in strategy_columns:
        conn.execute("ALTER TABLE fund_strategies ADD COLUMN drawdown_budget TEXT NOT NULL DEFAULT '0'")
    if "executed_drawdown_stage" not in strategy_columns:
        conn.execute("ALTER TABLE fund_strategies ADD COLUMN executed_drawdown_stage INTEGER NOT NULL DEFAULT 0")
    if "drawdown_thresholds" not in strategy_columns:
        conn.execute("ALTER TABLE fund_strategies ADD COLUMN drawdown_thresholds TEXT NOT NULL DEFAULT '10,20,35,50'")
    if "drawdown_allocations" not in strategy_columns:
        conn.execute("ALTER TABLE fund_strategies ADD COLUMN drawdown_allocations TEXT NOT NULL DEFAULT '20,20,30,30'")
    conn.execute("""CREATE TABLE IF NOT EXISTS user_preferences (
      id INTEGER PRIMARY KEY CHECK(id=1),show_health INTEGER NOT NULL DEFAULT 0,
      show_research INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS scholar_profiles (
      profile_id TEXT PRIMARY KEY,name TEXT NOT NULL,affiliation TEXT,interests TEXT,profile_url TEXT,updated_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS scholar_snapshots (
      profile_id TEXT NOT NULL,day TEXT NOT NULL,citations_all INTEGER NOT NULL,citations_recent INTEGER,
      h_index_all INTEGER NOT NULL,h_index_recent INTEGER,i10_all INTEGER NOT NULL,i10_recent INTEGER,
      yearly_citations TEXT NOT NULL DEFAULT '{}',captured_at TEXT NOT NULL,PRIMARY KEY(profile_id,day))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS scholar_papers (
      profile_id TEXT NOT NULL,paper_id TEXT NOT NULL,title TEXT NOT NULL,authors TEXT,venue TEXT,
      publication_year INTEGER,url TEXT,updated_at TEXT NOT NULL,PRIMARY KEY(profile_id,paper_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS scholar_paper_snapshots (
      profile_id TEXT NOT NULL,paper_id TEXT NOT NULL,day TEXT NOT NULL,citations INTEGER NOT NULL,
      captured_at TEXT NOT NULL,PRIMARY KEY(profile_id,paper_id,day))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS scholar_settings (
      id INTEGER PRIMARY KEY CHECK(id=1),profile_url TEXT NOT NULL,auto_open INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS audit_logs (
      id TEXT PRIMARY KEY, event_type TEXT NOT NULL, summary TEXT NOT NULL,
      details TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS deleted_records (
      table_name TEXT NOT NULL, record_key TEXT NOT NULL, deleted_at TEXT NOT NULL,
      PRIMARY KEY(table_name,record_key))""")
    # Preserve records written by the short-lived standalone stock UI in
    # backups and encrypted sync without counting them as separate assets.
    conn.execute("""CREATE TABLE IF NOT EXISTS stock_snapshots (
      symbol TEXT NOT NULL, day TEXT NOT NULL, name TEXT NOT NULL,
      market_value TEXT NOT NULL, updated_at TEXT NOT NULL,
      PRIMARY KEY(symbol,day))""")
    return conn


def audit(conn, event_type, summary, details=None, now=None):
    now = now or datetime.now().isoformat(timespec="microseconds")
    event_id = uuid.uuid4().hex
    conn.execute("INSERT INTO audit_logs VALUES(?,?,?,?,?)",
                 (event_id, event_type, summary, json.dumps(details or {}, ensure_ascii=False), now))


def money(value):
    try:
        result = Decimal(str(value).replace(",", "").replace("¥", "").strip())
        if not result.is_finite() or result < 0 or result > Decimal("100000000000"):
            raise ValueError()
        return str(result.quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        raise ValueError("金额格式不正确")


def signed_money(value):
    try:
        result = Decimal(str(value).replace(",", "").replace("¥", "").strip())
        if not result.is_finite() or abs(result) > Decimal("100000000000"):
            raise ValueError()
        return result.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError("持有收益格式不正确")


def clean_item(raw):
    name = str(raw.get("name", "")).strip()[:80]
    if not name:
        raise ValueError("缺少基金名称")
    code = re.sub(r"\D", "", str(raw.get("code", "")))[:6]
    if code and len(code) != 6:
        raise ValueError("基金代码必须为 6 位数字")
    allowed_categories = {"宽基指数", "行业主题", "股票基金", "混合基金", "债券基金", "货币基金", "黄金商品", "海外基金", "其他基金", "ETF"}
    category = str(raw.get("category", "宽基指数")).strip()
    if category not in allowed_categories:
        raise ValueError("基金类别不正确")
    if any(raw.get(key) in (None, "") for key in ("market_value", "holding_profit", "return_rate")):
        raise ValueError("请按支付宝原样填写当前金额、持有收益和持有收益率")
    value = Decimal(money(raw["market_value"]))
    profit = signed_money(raw["holding_profit"])
    try:
        reported_rate = Decimal(str(raw["return_rate"]).replace("%", "").strip())
    except InvalidOperation:
        raise ValueError("收益率格式不正确")
    if not reported_rate.is_finite() or abs(reported_rate) > Decimal("100000000000"):
        raise ValueError("收益率格式不正确")
    if reported_rate < -100:
        raise ValueError("收益率不能低于 -100%")
    return {"code": code, "name": name, "category": category, "market_value": money(value),
            "holding_profit": money(abs(profit)) if profit >= 0 else "-" + money(abs(profit)),
            "return_rate": str(reported_rate.quantize(Decimal("0.01")))}


def fund_category(fund_type):
    fund_type = str(fund_type or "")
    if "海外" in fund_type or "QDII" in fund_type.upper(): return "海外基金"
    if "债" in fund_type: return "债券基金"
    if "货币" in fund_type: return "货币基金"
    if "黄金" in fund_type or "商品" in fund_type: return "黄金商品"
    if "指数" in fund_type or "ETF" in fund_type.upper(): return "宽基指数"
    if "混合" in fund_type: return "混合基金"
    if "股票" in fund_type: return "股票基金"
    return "其他基金"


def load_fund_catalog():
    try:
        if FUND_CATALOG.exists() and time.time() - FUND_CATALOG.stat().st_mtime < 7 * 86400:
            return json.loads(FUND_CATALOG.read_text())
        request = urllib.request.Request("https://fund.eastmoney.com/js/fundcode_search.js",
          headers={"Referer": "https://fund.eastmoney.com/", "User-Agent": "shiguang-desktop"})
        with urllib.request.urlopen(request, timeout=20, context=SSL_CONTEXT) as response:
            raw = response.read().decode("utf-8-sig", errors="replace")
        rows = json.loads(raw[raw.find("["):raw.rfind("]") + 1])
        catalog = {row[0]: {"name": row[2], "fundType": row[3], "category": fund_category(row[3])}
                   for row in rows if len(row) >= 4 and len(row[0]) == 6}
        DATA.mkdir(parents=True, exist_ok=True)
        FUND_CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")))
        return catalog
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {}


def lookup_fund(code):
    code = re.sub(r"\D", "", str(code))[:6]
    if len(code) != 6:
        raise ValueError("请输入 6 位基金代码")
    cached = load_fund_catalog().get(code)
    if cached:
        return {"code": code, "name": cached["name"], "fullName": "",
                "fundType": cached["fundType"], "category": cached["category"]}
    query = urllib.parse.urlencode({"FCODE": code, "deviceid": "Wap", "plat": "Wap",
                                    "product": "EFund", "version": "2.0.0"})
    request = urllib.request.Request("https://fundmobapi.eastmoney.com/FundMNewApi/FundMNDetailInformation?" + query,
      headers={"Accept": "application/json", "Referer": "https://fund.eastmoney.com/",
               "User-Agent": "shiguang-desktop"})
    try:
        with urllib.request.urlopen(request, timeout=10, context=SSL_CONTEXT) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise ValueError("基金信息查询失败，请稍后重试")
    data = payload.get("Datas") or {}
    if not data.get("SHORTNAME"):
        raise ValueError("未找到该基金代码")
    fund_type = str(data.get("FTYPE", "")); category = fund_category(fund_type)
    return {"code": code, "name": data["SHORTNAME"], "fullName": data.get("FULLNAME", ""),
            "fundType": fund_type, "category": category}


def fetch_fund_market(code, page_size=1200):
    code = re.sub(r"\D", "", str(code))[:6]
    if len(code) != 6:
        raise ValueError("请输入 6 位基金代码")
    query = urllib.parse.urlencode({"FCODE": code, "pageIndex": 1, "pageSize": page_size,
      "plat": "Android", "appType": "ttjj", "product": "EFund", "version": "6.2.8",
      "deviceid": "shiguang-desktop"})
    request = urllib.request.Request("https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList?" + query,
      headers={"Accept": "application/json", "Referer": "https://fund.eastmoney.com/",
               "User-Agent": "shiguang-desktop"})
    try:
        with urllib.request.urlopen(request, timeout=15, context=SSL_CONTEXT) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise ValueError("公开基金行情连接失败，请稍后重试")
    rows=[]
    for raw in payload.get("Datas") or []:
        day=str(raw.get("FSRQ", "")); nav=str(raw.get("DWJZ", "")).strip()
        change=str(raw.get("JZZZL", "")).replace("%", "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or not nav or change in ("", "--"): continue
        try: Decimal(nav); Decimal(change)
        except InvalidOperation: continue
        rows.append({"code":code,"day":day,"unit_nav":nav,
          "cumulative_nav":str(raw.get("LJJZ", "")).strip(),"daily_change_pct":change,
          "source":"eastmoney-public-nav"})
    if not rows: raise ValueError("暂未获取到该基金的公开净值记录")
    return rows


def fetch_market_index(code, secid, page_size=1200):
    query = urllib.parse.urlencode({"secid": secid, "klt": 101, "fqt": 1,
      "lmt": page_size, "end": "20500101", "fields1": "f1,f2,f3,f4,f5,f6",
      "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"})
    request = urllib.request.Request("https://push2his.eastmoney.com/api/qt/stock/kline/get?" + query,
      headers={"Accept": "application/json", "Referer": "https://quote.eastmoney.com/",
               "User-Agent": "shiguang-desktop"})
    try:
        with urllib.request.urlopen(request, timeout=15, context=SSL_CONTEXT) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        raise ValueError("公开指数行情连接失败，请稍后重试")
    rows = []
    for line in (payload.get("data") or {}).get("klines") or []:
        fields = str(line).split(",")
        if len(fields) < 9 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fields[0]): continue
        try: Decimal(fields[2]); Decimal(fields[8])
        except InvalidOperation: continue
        rows.append({"code": code, "day": fields[0], "close": fields[2],
          "daily_change_pct": fields[8], "source": "eastmoney-public-index"})
    if not rows: raise ValueError("暂未获取到该指数的公开行情")
    return rows


def drawdown_rules(strategy):
    def parse(name, default):
        raw=str((strategy or {}).get(name,default))
        try: values=tuple(Decimal(part.strip()) for part in raw.split(","))
        except InvalidOperation: raise ValueError("回撤档位必须是数字")
        if len(values)!=4: raise ValueError("回撤策略必须设置 4 个档位")
        return values
    thresholds=parse("drawdown_thresholds","10,20,35,50")
    allocations=parse("drawdown_allocations","20,20,30,30")
    if any(x<=0 or x>100 for x in thresholds) or any(a>=b for a,b in zip(thresholds,thresholds[1:])):
        raise ValueError("回撤阈值必须大于 0、不超过 100，并且逐档递增")
    if any(x<0 for x in allocations) or sum(allocations)!=Decimal("100"):
        raise ValueError("四档资金比例必须为非负数，且合计等于 100%")
    return thresholds,allocations


def drawdown_status(strategy, market, history=None):
    values=[]
    for row in history or []:
        try: values.append(Decimal(str(row.get("unit_nav"))))
        except (InvalidOperation, TypeError): pass
    try: current=Decimal(str((market or {}).get("unit_nav")))
    except (InvalidOperation, TypeError): current=Decimal("0")
    if current > 0: values.append(current)
    if not values or current <= 0: return {"highest_nav":None,"drawdown_pct":None,"triggered_stage":0}
    highest=max(values); drawdown=max(Decimal("0"),(highest-current)/highest*100)
    thresholds,_=drawdown_rules(strategy)
    stage=sum(1 for threshold in thresholds if drawdown >= threshold)
    return {"highest_nav":str(highest),"drawdown_pct":str(drawdown.quantize(Decimal("0.01"))),"triggered_stage":stage}


def planned_investment(strategy, market, history=None):
    if not strategy or strategy["mode"] == "none": return Decimal("0")
    if strategy["mode"] == "daily": return Decimal(strategy["daily_amount"])
    if strategy["mode"] == "drawdown":
        status=drawdown_status(strategy,market,history); stage=status["triggered_stage"]
        executed=max(0,min(4,int(strategy.get("executed_drawdown_stage",0))))
        if stage <= executed: return Decimal("0")
        _,allocations=drawdown_rules(strategy); weights=tuple(x/100 for x in allocations)
        return Decimal(strategy["drawdown_budget"])*sum(weights[executed:stage])
    change=Decimal(str((market or {}).get("daily_change_pct", "0")))
    if change >= 0: return Decimal("0")
    amount=(-change)*Decimal(strategy["per_drop_pct_amount"])
    cap=Decimal(strategy["max_daily_amount"])
    return min(amount,cap) if cap > 0 else amount


def clean_account(raw):
    name = str(raw.get("name", "")).strip()[:80]
    if not name:
        raise ValueError("请填写账户名称")
    allowed_types = {"现金", "银行存款", "电子钱包", "证券账户", "理财账户", "其他资产"}
    account_type = str(raw.get("account_type", "现金")).strip()
    if account_type not in allowed_types:
        raise ValueError("账户类型不正确")
    platform = str(raw.get("platform", "")).strip()[:40] or "其他"
    return {"name": name, "account_type": account_type, "platform": platform,
            "balance": money(raw.get("balance", 0))}


def save_asset_snapshot(conn, now):
    fund = Decimal(str(conn.execute("SELECT COALESCE(SUM(market_value + 0),0) FROM holdings WHERE archived_at IS NULL").fetchone()[0]))
    account = Decimal(str(conn.execute("SELECT COALESCE(SUM(balance + 0),0) FROM accounts").fetchone()[0]))
    conn.execute("INSERT OR REPLACE INTO portfolio_snapshots VALUES(?,?,?,?)",
                 (datetime.now().date().isoformat(), money(fund + account), "manual", now))


def rekey_holding_records(conn, old, item, now):
    old_key = old["code"] or "name:" + old["name"]
    new_key = item["code"] or "name:" + item["name"]
    if old_key == new_key:
        return
    for snapshot in conn.execute("SELECT * FROM holding_snapshots WHERE holding_key=?", (old_key,)).fetchall():
        newer = conn.execute("SELECT created_at FROM holding_snapshots WHERE day=? AND holding_key=?",
                             (snapshot["day"], new_key)).fetchone()
        if newer is None or snapshot["created_at"] > newer["created_at"]:
            conn.execute("INSERT OR REPLACE INTO holding_snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                         (snapshot["day"], new_key, item["code"] or None, snapshot["name"],
                          snapshot["market_value"], snapshot["holding_profit"], snapshot["return_rate"],
                          snapshot["source"], snapshot["created_at"]))
        conn.execute("DELETE FROM holding_snapshots WHERE day=? AND holding_key=?",
                     (snapshot["day"], old_key))
        conn.execute("INSERT OR REPLACE INTO deleted_records VALUES('holding_snapshots',?,?)",
                     (snapshot["day"] + ":" + old_key, now))
    if old["code"] and old["code"] != item["code"]:
        if item["code"] and not conn.execute("SELECT 1 FROM fund_strategies WHERE code=?", (item["code"],)).fetchone():
            conn.execute("UPDATE fund_strategies SET code=?,updated_at=? WHERE code=?",
                         (item["code"], now, old["code"]))
        else:
            conn.execute("DELETE FROM fund_strategies WHERE code=?", (old["code"],))
        conn.execute("INSERT OR REPLACE INTO deleted_records VALUES('fund_strategies',?,?)", (old["code"], now))
    conn.execute("INSERT OR REPLACE INTO deleted_records VALUES('holdings',?,?)", (old_key, now))


def inferred_holding_flow(conn, holding_key):
    snapshots=[dict(row) for row in conn.execute(
      "SELECT day,market_value FROM holding_snapshots WHERE holding_key=? ORDER BY day DESC LIMIT 2",(holding_key,))]
    if len(snapshots)<2 or holding_key.startswith("name:"): return None
    current,previous=snapshots[0],snapshots[1]
    navs=[]
    for snapshot in (previous,current):
        nav=conn.execute("""SELECT day,unit_nav FROM fund_market_daily
          WHERE code=? AND day<=? ORDER BY day DESC LIMIT 1""",(holding_key,snapshot["day"])).fetchone()
        if not nav: return {"status":"missing_market","from_day":previous["day"],"to_day":current["day"]}
        try: nav_value=Decimal(nav["unit_nav"])
        except InvalidOperation: return {"status":"missing_market","from_day":previous["day"],"to_day":current["day"]}
        if nav_value<=0: return {"status":"missing_market","from_day":previous["day"],"to_day":current["day"]}
        navs.append((nav["day"],nav_value))
    previous_units=Decimal(previous["market_value"])/navs[0][1]
    current_units=Decimal(current["market_value"])/navs[1][1]
    net_units=current_units-previous_units
    estimated_amount=net_units*navs[1][1]
    return {"status":"estimated","from_day":previous["day"],"to_day":current["day"],
      "previous_nav_day":navs[0][0],"current_nav_day":navs[1][0],
      "net_units":str(net_units.quantize(Decimal("0.0001"))),
      "net_amount":str(abs(estimated_amount).quantize(Decimal("0.01"))),
      "direction":"buy" if net_units>0 else "sell" if net_units<0 else "none"}


class Handler(SimpleHTTPRequestHandler):
    def extension_origin(self):
        origin = self.headers.get("Origin", "")
        if self.path == "/api/scholar/import" and origin.startswith(
            ("chrome-extension://", "extension://", "moz-extension://")
        ):
            return origin
        return ""

    def request_allowed(self):
        headers = getattr(self, "headers", {})
        host = headers.get("Host", "")
        if host:
            try:
                parsed_host = urllib.parse.urlsplit("//" + host)
            except ValueError:
                return False
            if parsed_host.hostname not in ("127.0.0.1", "localhost") or parsed_host.username or parsed_host.password:
                return False
        origin = headers.get("Origin", "")
        if not origin:
            return True
        if self.extension_origin():
            return True
        try:
            parsed_origin = urllib.parse.urlsplit(origin)
        except ValueError:
            return False
        return (parsed_origin.scheme == "http" and parsed_origin.netloc == host
                and parsed_origin.path == "" and not parsed_origin.query and not parsed_origin.fragment)

    def reject_untrusted_request(self):
        if self.request_allowed():
            return False
        self.json_response({"error": "仅接受本机同源请求"}, 403)
        return True

    def do_OPTIONS(self):
        if not self.request_allowed():
            self.send_error(403); return
        origin = self.extension_origin()
        if not origin:
            self.send_error(403); return
        self.send_response(204); self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type"); self.send_header("Access-Control-Allow-Methods", "POST,OPTIONS"); self.end_headers()

    def translate_path(self, path):
        # Use the standard handler's URL decoding and traversal normalization,
        # then enforce confinement even when a static symlink points outside.
        self.directory = str(STATIC)
        target = Path(super().translate_path(path)).resolve()
        if not target.is_relative_to(STATIC.resolve()):
            return str(STATIC / "__not_found__")
        return str(target / "index.html" if target == STATIC.resolve() else target)

    def list_directory(self, path):
        self.send_error(404, "Not found")
        return None

    def json_response(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        origin = self.extension_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size < 0 or size > 1024 * 1024:
            raise ValueError("请求过大")
        data = json.loads(self.rfile.read(size) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        return data

    def do_GET(self):
        if self.reject_untrusted_request():
            return
        if self.path.startswith("/api/funds/lookup?"):
            code = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("code", [""])[0]
            try:
                self.json_response(lookup_fund(code))
            except ValueError as exc:
                self.json_response({"error": str(exc)}, 404)
            return
        if self.path == "/api/preferences":
            with db() as conn: row=conn.execute("SELECT show_health,show_research FROM user_preferences WHERE id=1").fetchone()
            self.json_response(dict(row) if row else {"show_health":0,"show_research":0}); return
        if self.path.startswith("/api/holdings/history?"):
            code = re.sub(r"\D", "", urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("code", [""])[0])[:6]
            with db() as conn:
                rows = [dict(r) for r in conn.execute(
                  "SELECT * FROM holding_snapshots WHERE holding_key=? ORDER BY day DESC LIMIT 365", (code,))]
            self.json_response({"history": rows}); return
        if self.path.startswith("/api/funds/market?"):
            code = re.sub(r"\D", "", urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("code", [""])[0])[:6]
            with db() as conn: rows=[dict(r) for r in conn.execute(
              "SELECT * FROM fund_market_daily WHERE code=? ORDER BY day DESC LIMIT 365",(code,))]
            self.json_response({"history":rows}); return
        if self.path == "/api/holdings/calendar" or self.path.startswith("/api/holdings/calendar?"):
            day = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("day", [datetime.now().date().isoformat()])[0]
            try:
                with db() as conn: result = holding_calendar.dated_view(conn, day)
                self.json_response(result)
            except ValueError as exc:
                self.json_response({"error": str(exc)}, 400)
            return
        if self.path == "/api/market":
            indices=[]; updated_at=""
            with db() as conn:
                for code,name,market,_ in MARKET_INDICES:
                    history=[dict(r) for r in conn.execute(
                      "SELECT day,close,daily_change_pct,source,fetched_at FROM market_index_daily WHERE code=? ORDER BY day",(code,))]
                    if history: updated_at=max(updated_at,history[-1]["fetched_at"])
                    indices.append({"code":code,"name":name,"market":market,"latest":history[-1] if history else None,"history":history})
            self.json_response({"indices":indices,"updatedAt":updated_at,"source":"东方财富公开指数行情"}); return
        if self.path == "/api/state":
            with db() as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM holdings WHERE archived_at IS NULL ORDER BY market_value + 0 DESC")]
                archived = [dict(r) for r in conn.execute("SELECT * FROM holdings WHERE archived_at IS NOT NULL ORDER BY archived_at DESC")]
                accounts = [dict(r) for r in conn.execute("SELECT * FROM accounts ORDER BY balance + 0 DESC")]
                snapshots = list(reversed([dict(r) for r in conn.execute("SELECT * FROM portfolio_snapshots ORDER BY day DESC LIMIT 365")]))
                for row in rows:
                    market=conn.execute("SELECT day,unit_nav,cumulative_nav,daily_change_pct FROM fund_market_daily WHERE code=? ORDER BY day DESC LIMIT 1",(row.get("code"),)).fetchone()
                    market_data=dict(market) if market else None
                    if market_data: row["public_market"]=market_data
                    history=[dict(x) for x in conn.execute("SELECT day,unit_nav,daily_change_pct FROM fund_market_daily WHERE code=? ORDER BY day DESC LIMIT 10000",(row.get("code"),))]
                    row["public_market_history"]=list(reversed(history))
                    strategy=conn.execute("SELECT * FROM fund_strategies WHERE code=?",(row.get("code"),)).fetchone()
                    row["investment_strategy"]=dict(strategy) if strategy else {"mode":"none","daily_amount":"0","per_drop_pct_amount":"0","max_daily_amount":"0","drawdown_budget":"0","executed_drawdown_stage":0,"drawdown_thresholds":"10,20,35,50","drawdown_allocations":"20,20,30,30"}
                    row["drawdown_status"]=drawdown_status(row["investment_strategy"],market_data,history)
                    row["planned_investment"]=str(planned_investment(row["investment_strategy"],market_data,history).quantize(Decimal("0.01")))
                    row["inferred_flow"]=inferred_holding_flow(conn,row.get("code") or "name:"+row["name"])
            total = sum(Decimal(r["market_value"]) for r in rows)
            account_total = sum(Decimal(r["balance"]) for r in accounts)
            reported_profit = sum(Decimal(r["holding_profit"]) for r in rows)
            self.json_response({"holdings": rows, "archivedHoldings": archived, "accounts": accounts,
                "total": str(total + account_total), "fundTotal": str(total),
                "accountTotal": str(account_total), "totalCost": None,
                "profit": str(reported_profit), "snapshots": snapshots})
            return
        if self.path == "/api/manage":
            with db() as conn:
                counts = {"accounts": conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
                          "holdings": conn.execute("SELECT COUNT(*) FROM holdings WHERE archived_at IS NULL").fetchone()[0],
                          "archived": conn.execute("SELECT COUNT(*) FROM holdings WHERE archived_at IS NOT NULL").fetchone()[0],
                          "snapshots": conn.execute("SELECT COUNT(*) FROM holding_snapshots").fetchone()[0]}
                logs = [dict(r) for r in conn.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 100")]
            self.json_response({"counts": counts, "auditLogs": logs}); return
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
                    "accounts": [dict(r) for r in conn.execute("SELECT * FROM accounts ORDER BY id")],
                    "holdings": [dict(r) for r in conn.execute("SELECT * FROM holdings ORDER BY id")],
                    "stockSnapshots": [dict(r) for r in conn.execute("SELECT * FROM stock_snapshots ORDER BY day,symbol")],
                    "holdingSnapshots": [dict(r) for r in conn.execute("SELECT * FROM holding_snapshots ORDER BY day,holding_key")],
                    "fundMarketDaily": [dict(r) for r in conn.execute("SELECT * FROM fund_market_daily ORDER BY day,code")],
                    "marketIndexDaily": [dict(r) for r in conn.execute("SELECT * FROM market_index_daily ORDER BY day,code")],
                    "fundStrategies": [dict(r) for r in conn.execute("SELECT * FROM fund_strategies ORDER BY code")],
                    "userPreferences": [dict(r) for r in conn.execute("SELECT id,show_health,show_research,updated_at FROM user_preferences ORDER BY id")],
                    "healthDaily": [dict(r) for r in conn.execute("SELECT * FROM health_daily ORDER BY day")],
                    "portfolioSnapshots": [dict(r) for r in conn.execute("SELECT * FROM portfolio_snapshots ORDER BY day")],
                    "auditLogs": [dict(r) for r in conn.execute("SELECT * FROM audit_logs ORDER BY created_at")],
                    "deletedRecords": [dict(r) for r in conn.execute("SELECT * FROM deleted_records ORDER BY deleted_at")],
                }
                from sync_engine import retired_data
                payload["legacyArchive"] = retired_data(conn)
                for key, table in (("scholarProfiles", "scholar_profiles"),
                                   ("scholarSnapshots", "scholar_snapshots"),
                                   ("scholarPapers", "scholar_papers"),
                                   ("scholarPaperSnapshots", "scholar_paper_snapshots"),
                                   ("scholarSettings", "scholar_settings")):
                    payload[key] = [dict(r) for r in conn.execute("SELECT * FROM " + table)]
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
        if self.path == "/api/scholar":
            with db() as conn:
                profile = conn.execute("SELECT * FROM scholar_profiles ORDER BY updated_at DESC LIMIT 1").fetchone()
                if not profile: self.json_response({"profile":None,"snapshots":[],"papers":[]}); return
                pid=profile["profile_id"]
                snapshots=[dict(r) for r in conn.execute("SELECT * FROM scholar_snapshots WHERE profile_id=? ORDER BY day",(pid,))]
                papers=[dict(r) for r in conn.execute("""SELECT p.*,(SELECT citations FROM scholar_paper_snapshots s WHERE s.profile_id=p.profile_id AND s.paper_id=p.paper_id ORDER BY day DESC LIMIT 1) citations FROM scholar_papers p WHERE profile_id=? ORDER BY citations DESC,publication_year DESC""",(pid,))]
            self.json_response({"profile":dict(profile),"snapshots":snapshots,"papers":papers}); return
        if self.path == "/api/scholar/config":
            with db() as conn: row=conn.execute("SELECT * FROM scholar_settings WHERE id=1").fetchone()
            self.json_response(dict(row) if row else {"profile_url":"","auto_open":True}); return
        if self.path == "/api/scholar-extension":
            source=RESOURCES / "scholar-extension"; buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as archive:
                for path in source.rglob("*"):
                    if path.is_file(): archive.write(path,path.relative_to(source.parent))
            data=buffer.getvalue(); self.send_response(200); self.send_header("Content-Type","application/zip")
            self.send_header("Content-Disposition",'attachment; filename="Shiguang-Scholar-Extension.zip"')
            self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        if self.path == "/api/update/check":
            try:
                from updater import check
                self.json_response(check())
            except Exception as exc:
                self.json_response({"error": str(exc)}, 503)
            return
        super().do_GET()

    def do_POST(self):
        if self.reject_untrusted_request():
            return
        try:
            if self.path == "/api/holdings":
                raw = self.read_json()
                item = clean_item(raw)
                day = holding_calendar.valid_day(raw.get("day") or datetime.now().date().isoformat())
                now = datetime.now().isoformat(timespec="microseconds")
                with db() as conn:
                    by_code = conn.execute("SELECT * FROM holdings WHERE code=?",
                                           (item["code"],)).fetchone() if item["code"] else None
                    by_name = conn.execute("SELECT * FROM holdings WHERE name=?",
                                           (item["name"],)).fetchone()
                    if by_code and by_name and by_code["id"] != by_name["id"]:
                        raise ValueError("基金代码和名称分别属于不同持仓，请先核对")
                    existing = by_code or by_name
                    if item["market_value"] == "0.00" and not existing:
                        raise ValueError("清仓前需先记录该 ETF 或基金的非零持仓")
                    # Preserve old cost data for backups, but never derive a new principal
                    # from rounded platform profit or return-rate fields.
                    legacy_cost = existing["cost"] if existing else "0.00"
                    values = (item["code"] or None, item["name"], item["category"], item["market_value"], legacy_cost, now,
                              item["holding_profit"], item["return_rate"])
                    if existing:
                        holding_id = existing["id"]
                        rekey_holding_records(conn, existing, item, now)
                        key = item["code"] or "name:" + item["name"]
                        # Backfilling August must not overwrite an unsnapshotted
                        # October current balance from an older app version.
                        has_history = conn.execute("SELECT 1 FROM holding_snapshots WHERE holding_key=? LIMIT 1",
                                                   (key,)).fetchone()
                        if day < existing["updated_at"][:10] and not has_history:
                            if existing["archived_at"]:
                                fallback_day = existing["archived_at"][:10]
                                fallback_value, fallback_profit, fallback_rate = "0.00", "0.00", "0.00"
                            else:
                                fallback_day = existing["updated_at"][:10]
                                fallback_value = existing["market_value"]
                                fallback_profit = existing["holding_profit"]
                                fallback_rate = existing["return_rate"]
                            conn.execute("INSERT OR IGNORE INTO holding_snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                              (fallback_day, key, item["code"] or None, existing["name"], fallback_value,
                               fallback_profit, fallback_rate, "legacy-current", existing["updated_at"]))
                    else:
                        holding_id = conn.execute("INSERT INTO holdings(code,name,category,market_value,cost,updated_at,holding_profit,return_rate) VALUES(?,?,?,?,?,?,?,?)", values).lastrowid
                    key = item["code"] or "name:" + item["name"]
                    conn.execute("DELETE FROM deleted_records WHERE table_name='holdings' AND record_key=?", (key,))
                    conn.execute("INSERT OR REPLACE INTO holding_snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                      (day, key, item["code"] or None, item["name"], item["market_value"],
                       item["holding_profit"], item["return_rate"], "clear-manual" if item["market_value"] == "0.00" else "platform-manual", now))
                    conn.execute("DELETE FROM deleted_records WHERE table_name='holding_snapshots' AND record_key=?",
                                 (day + ":" + key,))
                    latest = conn.execute("SELECT * FROM holding_snapshots WHERE holding_key=? ORDER BY day DESC LIMIT 1", (key,)).fetchone()
                    closed = latest["market_value"] == "0.00"
                    conn.execute("""UPDATE holdings SET code=?,name=?,category=?,market_value=?,cost=?,updated_at=?,
                      holding_profit=?,return_rate=?,archived_at=? WHERE id=?""",
                      (item["code"] or None, item["name"], item["category"], latest["market_value"],
                       legacy_cost, now, latest["holding_profit"], latest["return_rate"],
                       latest["day"] + "T00:00:00" if closed else None,
                       holding_id))
                    audit(conn, "HOLDING_SNAPSHOT_SAVED", "保存基金快照：" + item["name"],
                          {"code": item["code"], "day": day, "marketValue": item["market_value"],
                           "mode": "dated-snapshot", "closed": closed}, now)
                    save_asset_snapshot(conn, now)
                self.json_response({"ok": True, "mode": "updated" if existing else "created",
                                    "preserved": True, "values": item})
                return
            if self.path == "/api/funds/market/refresh":
                raw=self.read_json(); requested=re.sub(r"\D", "", str(raw.get("code", "")))[:6]
                with db() as conn:
                    codes=[requested] if len(requested)==6 else [r[0] for r in conn.execute(
                      "SELECT DISTINCT code FROM holdings WHERE archived_at IS NULL AND length(code)=6")]
                updated=0; errors={}; now=datetime.now().isoformat(timespec="microseconds"); page_size=10000 if raw.get("full_history") else 120
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(4,max(1,len(codes)))) as pool:
                    futures={pool.submit(fetch_fund_market,code,page_size):code for code in codes}
                    for future in concurrent.futures.as_completed(futures):
                        code=futures[future]
                        try:
                            market_rows=future.result()
                            with db() as conn:
                                for row in market_rows: conn.execute("INSERT OR REPLACE INTO fund_market_daily VALUES(?,?,?,?,?,?,?)",
                                  (row["code"],row["day"],row["unit_nav"],row["cumulative_nav"],row["daily_change_pct"],row["source"],now))
                            updated+=1
                        except Exception as exc: errors[code]=str(exc) if isinstance(exc,ValueError) else "公开行情读取失败"
                self.json_response({"ok":True,"updated":updated,"errors":errors}); return
            if self.path == "/api/market/refresh":
                now=datetime.now().isoformat(timespec="microseconds"); updated=0; errors={}
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                    futures={pool.submit(fetch_market_index,code,secid):code for code,_,_,secid in MARKET_INDICES}
                    for future in concurrent.futures.as_completed(futures):
                        code=futures[future]
                        try:
                            rows=future.result()
                            with db() as conn:
                                for row in rows: conn.execute("INSERT OR REPLACE INTO market_index_daily VALUES(?,?,?,?,?,?)",
                                  (row["code"],row["day"],row["close"],row["daily_change_pct"],row["source"],now))
                            updated+=1
                        except Exception as exc: errors[code]=str(exc) if isinstance(exc,ValueError) else "公开指数行情读取失败"
                self.json_response({"ok":True,"updated":updated,"errors":errors}); return
            if self.path == "/api/funds/strategy":
                raw=self.read_json(); code=re.sub(r"\D", "", str(raw.get("code", "")))[:6]
                mode=str(raw.get("mode", "none"));
                if len(code)!=6: raise ValueError("基金代码不正确")
                if mode not in ("none","daily","drop","drawdown"): raise ValueError("定投策略不正确")
                daily=money(raw.get("daily_amount",0)); per_pct=money(raw.get("per_drop_pct_amount",0)); cap=money(raw.get("max_daily_amount",0)); budget=money(raw.get("drawdown_budget",0))
                thresholds=",".join(str(raw.get("drawdown_threshold_"+str(i),default)).strip() for i,default in enumerate((10,20,35,50),1))
                allocations=",".join(str(raw.get("drawdown_allocation_"+str(i),default)).strip() for i,default in enumerate((20,20,30,30),1))
                try: executed=int(raw.get("executed_drawdown_stage",0))
                except (TypeError,ValueError): raise ValueError("已执行档位不正确")
                if executed not in range(5): raise ValueError("已执行档位不正确")
                if mode=="daily" and Decimal(daily)<=0: raise ValueError("每日定投金额必须大于 0")
                if mode=="drop" and Decimal(per_pct)<=0: raise ValueError("每下跌 1% 的定投金额必须大于 0")
                if mode=="drawdown" and Decimal(budget)<=0: raise ValueError("回撤资金总额必须大于 0")
                if mode=="drawdown": drawdown_rules({"drawdown_thresholds":thresholds,"drawdown_allocations":allocations})
                now=datetime.now().isoformat(timespec="microseconds")
                with db() as conn:
                    if not conn.execute("SELECT 1 FROM holdings WHERE code=?",(code,)).fetchone(): raise ValueError("未找到该基金")
                    conn.execute("""INSERT OR REPLACE INTO fund_strategies
                      (code,mode,daily_amount,per_drop_pct_amount,max_daily_amount,drawdown_budget,executed_drawdown_stage,drawdown_thresholds,drawdown_allocations,updated_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?)""",(code,mode,daily,per_pct,cap,budget,executed,thresholds,allocations,now))
                    audit(conn,"FUND_STRATEGY_SAVED","保存基金定投策略："+code,{"mode":mode},now)
                self.json_response({"ok":True}); return
            if self.path == "/api/preferences":
                raw=self.read_json(); now=datetime.now().isoformat(timespec="microseconds")
                values=tuple(1 if raw.get(key,False) else 0 for key in ("show_health","show_research"))
                with db() as conn: conn.execute("INSERT OR REPLACE INTO user_preferences (id,show_health,show_research,updated_at) VALUES(1,?,?,?)",values+(now,))
                self.json_response({"ok":True}); return
            if self.path in ("/api/holdings/archive", "/api/holdings/restore"):
                code = re.sub(r"\D", "", str(self.read_json().get("code", "")))[:6]
                if len(code) != 6: raise ValueError("基金代码不正确")
                now = datetime.now().isoformat(timespec="microseconds")
                with db() as conn:
                    row = conn.execute("SELECT * FROM holdings WHERE code=?", (code,)).fetchone()
                    if not row: raise ValueError("未找到可操作的持仓")
                    if self.path.endswith("archive"):
                        changed = conn.execute("UPDATE holdings SET archived_at=?,updated_at=? WHERE code=? AND archived_at IS NULL",
                                               (now, now, code)).rowcount
                        if changed:
                            conn.execute("INSERT OR REPLACE INTO holding_snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                              (now[:10], code, code, row["name"], "0.00", "0.00", "0.00", "manual-archive", now))
                    else:
                        if Decimal(row["market_value"]) == 0:
                            raise ValueError("已清仓持仓请到资产账户记录新的非零快照")
                        changed = conn.execute("UPDATE holdings SET archived_at=NULL,updated_at=? WHERE code=? AND archived_at IS NOT NULL", (now, code)).rowcount
                        if changed:
                            old_day = (row["archived_at"] or "")[:10]
                            if old_day:
                                conn.execute("INSERT OR IGNORE INTO holding_snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                                  (old_day, code, code, row["name"], "0.00", "0.00", "0.00", "legacy-archive", row["archived_at"]))
                            conn.execute("INSERT OR REPLACE INTO holding_snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                              (now[:10], code, code, row["name"], row["market_value"],
                               row["holding_profit"], row["return_rate"], "manual-restore", now))
                    if changed:
                        conn.execute("DELETE FROM deleted_records WHERE table_name='holding_snapshots' AND record_key=?",
                                     (now[:10] + ":" + code,))
                        audit(conn, "HOLDING_ARCHIVED" if self.path.endswith("archive") else "HOLDING_RESTORED",
                              ("归档" if self.path.endswith("archive") else "恢复") + "基金：" + code, {"code": code}, now)
                    save_asset_snapshot(conn, now)
                if not changed: raise ValueError("未找到可操作的持仓")
                self.json_response({"ok": True}); return
            if self.path == "/api/holdings/history/delete":
                raw = self.read_json(); code = re.sub(r"\D", "", str(raw.get("code", "")))[:6]
                day = str(raw.get("day", ""))
                if len(code) != 6 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day): raise ValueError("历史记录参数不正确")
                now = datetime.now().isoformat(timespec="microseconds")
                with db() as conn:
                    old = conn.execute("SELECT * FROM holding_snapshots WHERE holding_key=? AND day=?", (code, day)).fetchone()
                    if not old: raise ValueError("历史记录不存在")
                    conn.execute("DELETE FROM holding_snapshots WHERE holding_key=? AND day=?", (code, day))
                    conn.execute("INSERT OR REPLACE INTO deleted_records VALUES('holding_snapshots',?,?)", (day + ":" + code, now))
                    latest = conn.execute("SELECT * FROM holding_snapshots WHERE holding_key=? ORDER BY day DESC LIMIT 1", (code,)).fetchone()
                    if latest:
                        conn.execute("UPDATE holdings SET market_value=?,holding_profit=?,return_rate=?,archived_at=?,updated_at=? WHERE code=?",
                                     (latest["market_value"], latest["holding_profit"], latest["return_rate"],
                                      latest["day"] + "T00:00:00" if latest["market_value"] == "0.00" else None,
                                      now, code))
                    else:
                        conn.execute("UPDATE holdings SET archived_at=?,updated_at=? WHERE code=?", (now, now, code))
                    audit(conn, "HOLDING_SNAPSHOT_DELETED", "删除基金历史快照：" + old["name"],
                          {"code": code, "day": day, "previous": dict(old)}, now)
                    save_asset_snapshot(conn, now)
                self.json_response({"ok": True, "recalculated": bool(latest)}); return
            if self.path == "/api/holdings/delete":
                code = re.sub(r"\D", "", str(self.read_json().get("code", "")))[:6]
                if len(code) != 6: raise ValueError("基金代码不正确")
                now = datetime.now().isoformat(timespec="microseconds")
                with db() as conn:
                    row = conn.execute("SELECT * FROM holdings WHERE code=?", (code,)).fetchone()
                    if not row: raise ValueError("基金不存在")
                    count = conn.execute("SELECT COUNT(*) FROM holding_snapshots WHERE holding_key=?", (code,)).fetchone()[0]
                    if count: raise ValueError("该基金仍有历史快照，只能归档；删除全部快照后才能彻底删除")
                    conn.execute("DELETE FROM holdings WHERE code=?", (code,))
                    conn.execute("INSERT OR REPLACE INTO deleted_records VALUES('holdings',?,?)", (code, now))
                    audit(conn, "HOLDING_DELETED", "彻底删除空基金：" + row["name"], {"code": code}, now)
                    save_asset_snapshot(conn, now)
                self.json_response({"ok": True}); return
            if self.path == "/api/accounts":
                item = clean_account(self.read_json())
                now = datetime.now().isoformat(timespec="microseconds")
                with db() as conn:
                    conn.execute("""INSERT INTO accounts(name,account_type,platform,balance,updated_at)
                      VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET account_type=excluded.account_type,
                      platform=excluded.platform,balance=excluded.balance,updated_at=excluded.updated_at""",
                      (item["name"], item["account_type"], item["platform"], item["balance"], now))
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
                from sync_engine import save_config
                raw = self.read_json(); config = save_config(raw)
                self.json_response({"ok": True, "config": config})
                return
            if self.path == "/api/sync/run":
                from sync_engine import sync
                password = str(self.read_json().get("password", ""))
                result = sync(DB, password)
                with db() as conn:
                    save_asset_snapshot(conn, datetime.now().isoformat(timespec="microseconds"))
                self.json_response(result)
                return
            if self.path == "/api/scholar/import":
                raw=self.read_json(); profile=raw.get("profile") or {}; metrics=profile.get("metrics") or {}
                pid=str(profile.get("id","")).strip()[:80]; name=str(profile.get("name","")).strip()[:120]
                if not pid or not name: raise ValueError("科研快照缺少个人主页 ID 或姓名")
                captured=str(raw.get("capturedAt") or datetime.now().isoformat(timespec="microseconds")); day=captured[:10]
                def whole(v):
                    try: return max(0,int(v or 0))
                    except (TypeError,ValueError): raise ValueError("引用指标格式不正确")
                papers=raw.get("papers") or []; now=datetime.now().isoformat(timespec="microseconds")
                with db() as conn:
                    conn.execute("INSERT OR REPLACE INTO scholar_profiles VALUES(?,?,?,?,?,?)",(pid,name,str(profile.get("affiliation", ""))[:200],json.dumps(profile.get("interests") or [],ensure_ascii=False),str(profile.get("url", ""))[:500],now))
                    conn.execute("INSERT OR REPLACE INTO scholar_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)",(pid,day,whole(metrics.get("citationsAll")),whole(metrics.get("citationsRecent")),whole(metrics.get("hIndexAll")),whole(metrics.get("hIndexRecent")),whole(metrics.get("i10All")),whole(metrics.get("i10Recent")),json.dumps(profile.get("yearlyCitations") or {},ensure_ascii=False),captured))
                    for p in papers[:2000]:
                        title=str(p.get("title","")).strip()[:500]
                        if not title: continue
                        paper_id=str(p.get("id") or hashlib.sha256(title.encode()).hexdigest()[:24])[:120]
                        conn.execute("INSERT OR REPLACE INTO scholar_papers VALUES(?,?,?,?,?,?,?,?)",(pid,paper_id,title,str(p.get("authors", ""))[:1000],str(p.get("venue", ""))[:500],whole(p.get("year")) or None,str(p.get("url", ""))[:1000],now))
                        conn.execute("INSERT OR REPLACE INTO scholar_paper_snapshots VALUES(?,?,?,?,?)",(pid,paper_id,day,whole(p.get("citations")),captured))
                self.json_response({"ok":True,"papers":len(papers),"day":day}); return
            if self.path == "/api/scholar/config":
                raw=self.read_json(); url=str(raw.get("profile_url","")).strip()[:1000]
                parsed=urllib.parse.urlparse(url); query=urllib.parse.parse_qs(parsed.query)
                if parsed.scheme!="https" or parsed.hostname!="scholar.google.com" or parsed.path!="/citations" or not query.get("user"):
                    raise ValueError("请输入完整的 Google Scholar 个人主页地址")
                now=datetime.now().isoformat(timespec="microseconds")
                with db() as conn: conn.execute("INSERT OR REPLACE INTO scholar_settings VALUES(1,?,?,?)",(url,1 if raw.get("auto_open",True) else 0,now))
                self.json_response({"ok":True,"profile_url":url}); return
            if self.path == "/api/update/install":
                from updater import stage_and_install
                result = stage_and_install(); self.json_response(result)
                if result.get("restart_required"):
                    threading.Thread(target=lambda: (time.sleep(1), os._exit(0)), daemon=True).start()
                return
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
    if not math.isfinite(number) or number < minimum or (maximum is not None and number > maximum):
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
    now = datetime.now().isoformat(timespec="microseconds")
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
