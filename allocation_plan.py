"""Cash-only monthly allocation preview for current fund holdings."""

import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_DOWN


CENT = Decimal("0.01")


def holding_key(holding):
    return str(holding.get("code") or "name:" + holding["name"])


def clean_targets(raw, holdings):
    if not isinstance(raw, dict):
        raise ValueError("目标权重必须是基金代码与百分比的对应关系")
    keys = {holding_key(holding) for holding in holdings}
    if set(raw) != keys:
        raise ValueError("目标权重必须覆盖当前所有基金；持仓变化后请重新保存")
    cleaned = {}
    for key, value in raw.items():
        try:
            weight = Decimal(str(value))
        except (InvalidOperation, TypeError):
            raise ValueError("目标权重必须是数字") from None
        if not weight.is_finite() or weight < 0 or weight > 100 or weight.as_tuple().exponent < -2:
            raise ValueError("目标权重须在 0–100% 之间，最多两位小数")
        cleaned[key] = str(weight.quantize(CENT))
    total = sum((Decimal(value) for value in cleaned.values()), Decimal(0))
    if total not in (Decimal(0), Decimal(100)):
        raise ValueError("目标权重合计必须是 100%；全部为 0 可暂存预算")
    return cleaned


def _cents(value):
    return int((Decimal(str(value)) * 100).to_integral_value())


def _money(cents):
    return str((Decimal(cents) / 100).quantize(CENT))


def build_plan(holdings, settings, today=None):
    """Buy only underweight current holdings, within this month's remaining budget."""
    today = today or date.today()
    month = today.strftime("%Y-%m")
    settings = settings or {}
    try:
        targets = json.loads(settings.get("target_weights") or "{}")
    except (TypeError, json.JSONDecodeError):
        targets = {}
    budget = _cents(settings.get("monthly_budget") or 0)
    spent = _cents(settings.get("monthly_spent") or 0) if settings.get("spent_month") == month else 0
    remaining = max(0, budget - spent)
    keys = [holding_key(row) for row in holdings]
    ready = bool(holdings) and set(targets) == set(keys) and sum(
        (Decimal(str(value)) for value in targets.values()), Decimal(0)) == 100
    values = [_cents(row["market_value"]) for row in holdings]
    total = sum(values)
    buys = [0] * len(holdings)
    signals = []
    for row in holdings:
        # A stale or missing public NAV never changes the purchase priority.
        market_day = (row.get("public_market") or {}).get("day")
        try:
            age = (today - date.fromisoformat(market_day)).days
        except (ValueError, TypeError):
            age = 999
        raw_drawdown = (row.get("drawdown_status") or {}).get("drawdown_pct")
        try:
            drawdown = Decimal(str(raw_drawdown)) if 0 <= age <= 7 else Decimal(0)
        except (InvalidOperation, TypeError):
            drawdown = Decimal(0)
        signals.append(max(Decimal(0), min(drawdown, Decimal(50))))

    if ready and remaining:
        final_total = total + remaining
        deficits = [max(0, int((Decimal(final_total) * Decimal(str(targets[key])) / 100 - value)
                               .to_integral_value(rounding=ROUND_DOWN)))
                    for key, value in zip(keys, values)]
        # Each extra cent goes to the largest weighted remaining gap. Recompute
        # proportions after a gap is filled, so no purchase overshoots its target.
        left = remaining
        while left and any(deficits):
            scores = [Decimal(gap) * (Decimal(1) + signal / 50)
                      for gap, signal in zip(deficits, signals)]
            score_total = sum(scores)
            portions = [min(gap, int((Decimal(left) * score / score_total)
                                     .to_integral_value(rounding=ROUND_DOWN)))
                        for gap, score in zip(deficits, scores)]
            assigned = sum(portions)
            if assigned == 0:
                index = max(range(len(deficits)), key=lambda i: (scores[i], -i))
                portions[index] = 1
                assigned = 1
            for i, portion in enumerate(portions):
                buys[i] += portion
                deficits[i] -= portion
            left -= assigned

    allocated = sum(buys)
    after_total = total + allocated
    rows = []
    for i, row in enumerate(holdings):
        key = keys[i]
        rows.append({"key": key, "name": row["name"], "code": row.get("code"),
                     "current_value": _money(values[i]), "buy_amount": _money(buys[i]),
                     "target_weight": str(targets.get(key, "0")),
                     "before_weight": str((Decimal(values[i]) * 100 / total).quantize(CENT)) if total else "0.00",
                     "after_weight": str((Decimal(values[i] + buys[i]) * 100 / after_total).quantize(CENT)) if after_total else "0.00",
                     "drawdown_pct": str(signals[i].quantize(CENT)) if signals[i] else None})
    return {"month": month, "monthly_budget": _money(budget), "monthly_spent": _money(spent),
            "remaining": _money(remaining), "allocated": _money(allocated),
            "unallocated": _money(remaining - allocated), "ready": ready,
            "stale_targets": bool(targets) and set(targets) != set(keys),
            "current_total": _money(total), "after_total": _money(after_total), "rows": rows}
