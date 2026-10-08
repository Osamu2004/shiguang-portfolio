"""Cash-only monthly allocation preview for current fund holdings."""

import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP


CENT = Decimal("0.01")
STRATEGY_LABELS = {
    "allocation": "按组合计划",
    "none": "暂停买入",
    "daily": "每日固定金额",
    "drop": "按日跌幅投入",
    "drawdown": "按高点回撤投入",
}


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
    """One buy preview, limited by target gaps, monthly cash and fund rules."""
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
    rule_limits = []
    strategy_modes = []
    stale_markets = []
    for row in holdings:
        # A stale or missing public NAV never changes the purchase priority.
        market_day = (row.get("public_market") or {}).get("day")
        try:
            age = (today - date.fromisoformat(market_day)).days
        except (ValueError, TypeError):
            age = 999
        mode = (row.get("investment_strategy") or {}).get("mode", "allocation")
        stale_market = mode in ("drop", "drawdown") and not 0 <= age <= 7
        if mode == "allocation":
            limit = None
        elif mode == "none" or stale_market or mode not in STRATEGY_LABELS:
            limit = 0
        else:
            limit = max(0, _cents(row.get("planned_investment") or 0))
        strategy_modes.append(mode)
        rule_limits.append(limit)
        stale_markets.append(stale_market)
        raw_drawdown = (row.get("drawdown_status") or {}).get("drawdown_pct")
        try:
            drawdown = Decimal(str(raw_drawdown)) if 0 <= age <= 7 else Decimal(0)
        except (InvalidOperation, TypeError):
            drawdown = Decimal(0)
        signals.append(max(Decimal(0), min(drawdown, Decimal(50))))

    if ready and remaining:
        weights = [Decimal(str(targets[key])) / 100 for key in keys]

        def capacities(spend):
            future_total = Decimal(total + spend)
            gaps = [max(Decimal(0), future_total * weight - value)
                    for weight, value in zip(weights, values)]
            return [min(gap, Decimal(limit)) if limit is not None else gap
                    for gap, limit in zip(gaps, rule_limits)]

        # Find the largest spend whose target gaps and fund-rule limits can
        # absorb it. Using the entire monthly balance as the future total when
        # some fund is paused would make the other funds exceed their targets.
        low, high = 0, remaining
        while low < high:
            candidate = (low + high + 1) // 2
            if sum(capacities(candidate)) >= candidate:
                low = candidate
            else:
                high = candidate - 1
        spend = low
        # Individual target gaps may contain fractions of a cent. Round each
        # up by at most one cent so the combined plan remains cent-executable.
        deficits = [int(gap.to_integral_value(rounding=ROUND_UP)) for gap in capacities(spend)]
        # Split the feasible spend by weighted target gap; only cent rounding
        # can put a resulting weight fractionally above its target.
        left = spend
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
                     "strategy_mode": strategy_modes[i],
                     "strategy_label": STRATEGY_LABELS.get(strategy_modes[i], "暂停买入"),
                     "rule_limit": _money(rule_limits[i]) if rule_limits[i] is not None else None,
                     "market_stale": stale_markets[i],
                     "before_weight": str((Decimal(values[i]) * 100 / total).quantize(CENT)) if total else "0.00",
                     "after_weight": str((Decimal(values[i] + buys[i]) * 100 / after_total).quantize(CENT)) if after_total else "0.00",
                     "drawdown_pct": str(signals[i].quantize(CENT)) if signals[i] else None})
    return {"month": month, "monthly_budget": _money(budget), "monthly_spent": _money(spent),
            "remaining": _money(remaining), "allocated": _money(allocated),
            "unallocated": _money(remaining - allocated), "ready": ready,
            "stale_targets": bool(targets) and set(targets) != set(keys),
            "current_total": _money(total), "after_total": _money(after_total), "rows": rows}
