"""Dated, manually valued stock holdings. Zero marks liquidation, not a cash transfer."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def create_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS stock_snapshots (
      symbol TEXT NOT NULL, day TEXT NOT NULL, name TEXT NOT NULL,
      market_value TEXT NOT NULL, updated_at TEXT NOT NULL,
      PRIMARY KEY(symbol,day))""")
    conn.execute("CREATE INDEX IF NOT EXISTS stock_snapshots_by_day ON stock_snapshots(day)")


def valid_day(value):
    raw = str(value or "").strip()
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("请输入有效的日期")
    if raw != parsed.isoformat() or parsed > date.today():
        raise ValueError("日期不能晚于今天")
    return raw


def amount(value):
    try:
        result = Decimal(str(value).replace(",", "").replace("¥", "").strip())
        if not result.is_finite() or result < 0 or result > Decimal("100000000000"):
            raise ValueError()
        return str(result.quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        raise ValueError("持仓金额格式不正确")


def positions_on(conn, day=None):
    day = day or date.today().isoformat()
    rows = conn.execute("""SELECT s.* FROM stock_snapshots s WHERE s.day<=?
      AND s.day=(SELECT MAX(t.day) FROM stock_snapshots t WHERE t.symbol=s.symbol AND t.day<=?)
      ORDER BY s.market_value+0 DESC,s.symbol""", (day, day))
    return [{**dict(row), "closed": Decimal(row["market_value"]) == 0} for row in rows]


def dated_view(conn, day):
    day = valid_day(day)
    days = [row[0] for row in conn.execute(
        "SELECT DISTINCT day FROM stock_snapshots WHERE day<=? ORDER BY day", (date.today().isoformat(),))]
    records = [dict(row) for row in conn.execute(
        "SELECT * FROM stock_snapshots WHERE day=? ORDER BY symbol", (day,))]
    return {"day": day, "snapshotDays": days, "records": records,
            "positions": positions_on(conn, day)}


def save_snapshot(conn, raw):
    symbol = str(raw.get("symbol", "")).strip().upper()
    name = str(raw.get("name", "")).strip()[:80]
    if not re.fullmatch(r"[A-Z0-9.^_-]{1,20}", symbol) or not name:
        raise ValueError("请填写股票代码和名称")
    day = valid_day(raw.get("day"))
    market_value = amount(raw.get("market_value"))
    if Decimal(market_value) == 0:
        prior = conn.execute("""SELECT 1 FROM stock_snapshots WHERE symbol=? AND day<?
          AND market_value+0>0 LIMIT 1""", (symbol, day)).fetchone()
        existing = conn.execute("SELECT 1 FROM stock_snapshots WHERE symbol=? AND day=?",
                                (symbol, day)).fetchone()
        if not prior and not existing:
            raise ValueError("清仓前需先记录该股票的非零持仓快照")
    now = datetime.now().isoformat(timespec="microseconds")
    conn.execute("""INSERT INTO stock_snapshots VALUES(?,?,?,?,?)
      ON CONFLICT(symbol,day) DO UPDATE SET name=excluded.name,
      market_value=excluded.market_value,updated_at=excluded.updated_at""",
      (symbol, day, name, market_value, now))
    return {"symbol": symbol, "day": day, "closed": market_value == "0.00"}
