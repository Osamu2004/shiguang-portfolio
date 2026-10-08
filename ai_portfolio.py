"""Small, read-only portfolio views for local AI tools and the HTTP API."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

import holding_calendar


SCHEMA_VERSION = 1


@contextmanager
def read_database(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError("尚未找到拾光投资数据库")
    connection = sqlite3.connect("file:" + quote(str(path.resolve()), safe="/") + "?mode=ro",
                                 uri=True, timeout=5)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")  # Keep all queries in one SQLite read snapshot.
        yield connection
    finally:
        connection.close()


def _amount(value):
    return str(Decimal(value).quantize(Decimal("0.01")))


def _generated_at():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def current_portfolio(path):
    """Return app-recorded current positions and cash, without legacy cost fields."""
    with read_database(path) as connection:
        holdings = [dict(row) for row in connection.execute("""
            SELECT code,name,category,market_value,holding_profit,return_rate,updated_at
            FROM holdings WHERE archived_at IS NULL
            ORDER BY CAST(market_value AS REAL) DESC,code,name
        """)]
        accounts = [dict(row) for row in connection.execute("""
            SELECT name,account_type,platform,balance,updated_at FROM accounts
            ORDER BY CAST(balance AS REAL) DESC,name
        """)]
        snapshot_rows = connection.execute("""
            SELECT holding_key,day,source FROM holding_snapshots
            ORDER BY day DESC,created_at DESC
        """)
        latest_snapshots = {}
        for row in snapshot_rows:
            latest_snapshots.setdefault(row["holding_key"], dict(row))

    fund_total = sum((Decimal(row["market_value"]) for row in holdings), Decimal("0"))
    cash_total = sum((Decimal(row["balance"]) for row in accounts), Decimal("0"))
    reported_profit = sum((Decimal(row["holding_profit"]) for row in holdings), Decimal("0"))
    bases = [Decimal(row["market_value"]) - Decimal(row["holding_profit"]) for row in holdings]
    reported_rate = (_amount(reported_profit / sum(bases) * 100)
                     if bases and all(base > 0 for base in bases) else None)
    output_holdings = []
    for row in holdings:
        key = row["code"] or "name:" + row["name"]
        snapshot = latest_snapshots.get(key, {})
        output_holdings.append({
            "code": row["code"] or None,
            "name": row["name"],
            "category": row["category"],
            "market_value": row["market_value"],
            "reported_holding_profit": row["holding_profit"],
            "reported_return_rate_pct": row["return_rate"],
            "recorded_at": row["updated_at"],
            "snapshot_day": snapshot.get("day", row["updated_at"][:10]),
            "snapshot_source": snapshot.get("source"),
            "purchase_channel": None,
        })
    output_accounts = [{"name": row["name"], "account_type": row["account_type"],
                        "platform": row["platform"], "balance": row["balance"],
                        "recorded_at": row["updated_at"]} for row in accounts]
    timestamps = [row["updated_at"] for row in holdings + accounts]
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "current_portfolio",
        "generated_at": _generated_at(),
        "last_recorded_at": max(timestamps) if timestamps else None,
        "currency": "CNY",
        "data_basis": {
            "holdings": "app_recorded_snapshots",
            "cash_accounts": "app_recorded_balances",
            "live_broker_or_alipay_sync": False,
            "purchase_channel_recorded": False,
            "reported_profit_excludes_realized_gains_and_cash": True,
        },
        "totals": {
            "assets": _amount(fund_total + cash_total),
            "holdings_market_value": _amount(fund_total),
            "cash_accounts": _amount(cash_total),
            "reported_current_holding_profit": _amount(reported_profit),
            "current_holding_return_rate_pct": reported_rate,
        },
        "holdings": output_holdings,
        "cash_accounts": output_accounts,
    }


def dated_holdings(path, day):
    """Return only dated fund/ETF snapshots; historical cash is unavailable."""
    with read_database(path) as connection:
        view = holding_calendar.dated_view(connection, day)
    positions = []
    total = Decimal("0")
    for row in view["positions"]:
        value = Decimal(row["market_value"])
        if not row["closed"]:
            total += value
        positions.append({
            "code": row.get("code") or None,
            "name": row["name"],
            "category": row["category"],
            "market_value": _amount(value),
            "reported_holding_profit": row["holding_profit"],
            "reported_return_rate_pct": row["return_rate"],
            "snapshot_day": row["day"],
            "snapshot_source": row.get("source"),
            "snapshot_recorded_at": row.get("created_at"),
            "closed": row["closed"],
            "closed_on": row["closed_on"],
            "purchase_channel": None,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "dated_holdings",
        "generated_at": _generated_at(),
        "day": view["day"],
        "currency": "CNY",
        "valuation_method": "latest_recorded_snapshot_on_or_before_day",
        "historical_cash_available": False,
        "holdings_market_value": _amount(total),
        "positions": positions,
        "snapshot_days": view["snapshotDays"],
    }
