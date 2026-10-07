"""As-of views for dated fund and ETF holding snapshots."""
from datetime import date, datetime
from decimal import Decimal


def valid_day(value):
    raw = str(value or "").strip()
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("请输入有效的盘点日期")
    if raw != parsed.isoformat() or parsed > date.today():
        raise ValueError("盘点日期不能晚于今天")
    return raw


def dated_view(conn, day):
    day = valid_day(day)
    today = date.today().isoformat()
    days = {row[0] for row in conn.execute(
        "SELECT DISTINCT day FROM holding_snapshots WHERE day<=?", (today,))}
    holdings = [dict(row) for row in conn.execute("SELECT * FROM holdings")]
    for holding in holdings:
        archived_day = (holding.get("archived_at") or "")[:10]
        if archived_day and archived_day <= today:
            days.add(archived_day)
    records = [dict(row) for row in conn.execute(
        "SELECT * FROM holding_snapshots WHERE day=? ORDER BY name,holding_key", (day,))]
    latest = {}
    for row in conn.execute(
        "SELECT * FROM holding_snapshots WHERE day<=? ORDER BY day DESC,created_at DESC", (day,)):
        latest.setdefault(row["holding_key"], dict(row))
    positions = []
    seen = set()
    for holding in holdings:
        key = holding["code"] or "name:" + holding["name"]
        row = latest.get(key)
        archived_day = (holding.get("archived_at") or "")[:10]
        if row is None and holding["updated_at"][:10] <= day:
            row = {"day": holding["updated_at"][:10], "holding_key": key,
                   "code": holding["code"], "name": holding["name"],
                   "market_value": holding["market_value"],
                   "holding_profit": holding["holding_profit"],
                   "return_rate": holding["return_rate"]}
        if row is None:
            continue
        closed = Decimal(row["market_value"]) == 0 or bool(archived_day and archived_day <= day)
        positions.append({**row, "category": holding["category"], "closed": closed,
                          "closed_on": row["day"] if Decimal(row["market_value"]) == 0 else archived_day or None,
                          "market_value": "0.00" if closed else row["market_value"]})
        seen.add(key)
    # Keep snapshots from older backups even when their holding record is missing.
    for key, row in latest.items():
        if key not in seen:
            positions.append({**row, "category": "未分类",
                              "closed": Decimal(row["market_value"]) == 0,
                              "closed_on": row["day"] if Decimal(row["market_value"]) == 0 else None})
    positions.sort(key=lambda row: (row["closed"], row["name"], row["holding_key"]))
    return {"day": day, "snapshotDays": sorted(days), "records": records,
            "positions": positions}
