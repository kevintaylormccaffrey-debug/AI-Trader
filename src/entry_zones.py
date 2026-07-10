from __future__ import annotations

from typing import Any


def _score(item: dict[str, Any], key: str, default: float = 50.0) -> float:
    try:
        return float(item.get("components", {}).get(key, {}).get("score", default) or default)
    except (TypeError, ValueError):
        return default


def _details(item: dict[str, Any], key: str) -> dict[str, Any]:
    details = item.get("components", {}).get(key, {}).get("details", {})
    return details if isinstance(details, dict) else {}


def _pct_change(history: list[dict[str, Any]], sessions_back: int) -> float | None:
    clean = [row for row in history if row.get("close") is not None]
    if len(clean) < 2:
        return None
    end = float(clean[-1]["close"])
    start_index = max(0, len(clean) - 1 - sessions_back)
    start = float(clean[start_index]["close"])
    if start == 0:
        return None
    return (end - start) / start * 100


def _support_prices(history: list[dict[str, Any]], current_price: float) -> dict[str, float | None]:
    clean = [float(row["close"]) for row in history if row.get("close") is not None]

    def average(days: int) -> float | None:
        if len(clean) < max(3, days // 2):
            return None
        sample = clean[-days:] if len(clean) >= days else clean
        return round(sum(sample) / len(sample), 2)

    def recent_low(days: int) -> float | None:
        if not clean:
            return None
        sample = clean[-days:] if len(clean) >= days else clean
        return round(min(sample), 2)

    supports = {
        "sma_20": average(20),
        "sma_50": average(50),
        "recent_low_20": recent_low(20),
    }
    return {key: value for key, value in supports.items() if value and value > 0 and value <= current_price * 1.05}


def build_entry_zone(
    item: dict[str, Any],
    market: dict[str, Any],
    scores: dict[str, Any],
    owned: bool = False,
) -> dict[str, Any] | None:
    current_price = market.get("price") or item.get("current_price")
    if not current_price:
        return None
    current = float(current_price)
    history = market.get("history", [])
    momentum = _score(scores, "price_momentum")
    thesis = _score(scores, "thesis_risk")
    news = _score(scores, "news_sentiment")
    valuation = _score(scores, "valuation_caution")
    downside = _score(scores, "downside_from_cost_basis")
    pnl_pct = _details(scores, "downside_from_cost_basis").get("pnl_pct_from_cost")
    change_20d = _details(scores, "price_momentum").get("change_20d_pct")
    if change_20d is None:
        change_20d = _pct_change(history, 20)

    base_pullback = 0.04
    if momentum >= 70:
        base_pullback += 0.02
    elif momentum <= 45:
        base_pullback -= 0.01
    if valuation <= 50:
        base_pullback += 0.03
    if thesis < 55:
        base_pullback += 0.03
    if news < 45:
        base_pullback += 0.02
    if isinstance(change_20d, (int, float)) and change_20d > 15:
        base_pullback += 0.02
    if owned and isinstance(pnl_pct, (int, float)) and pnl_pct > 15:
        base_pullback += 0.015

    starter_low_pct = max(0.02, min(0.13, base_pullback))
    starter_high_pct = max(0.01, starter_low_pct - 0.025)
    stronger_low_pct = min(0.22, starter_low_pct + 0.075)
    stronger_high_pct = min(0.18, starter_low_pct + 0.035)
    chase_pct = 0.03 if momentum >= 65 else 0.02

    starter_high = current * (1 - starter_high_pct)
    starter_low = current * (1 - starter_low_pct)
    stronger_high = current * (1 - stronger_high_pct)
    stronger_low = current * (1 - stronger_low_pct)
    do_not_chase_above = current * (1 + chase_pct)
    supports = _support_prices(history, current)

    reasons: list[str] = []
    if momentum >= 65:
        reasons.append("Momentum is strong, so the model prefers a pullback instead of chasing.")
    elif momentum <= 45:
        reasons.append("Momentum is weak, so any entry zone needs extra confirmation.")
    else:
        reasons.append("Momentum is mixed, so the zone is anchored to a moderate pullback.")
    if valuation <= 50:
        reasons.append("Valuation caution widens the desired discount.")
    if thesis >= 60:
        reasons.append("Thesis score is constructive enough to keep it on the research list.")
    if news >= 54:
        reasons.append("Recent news tone is not blocking the setup.")
    if owned and isinstance(pnl_pct, (int, float)):
        reasons.append(f"Adding here would be reviewed against current gain/loss from cost basis ({pnl_pct:+.1f}%).")
    if downside <= 45:
        reasons.append("Downside-from-cost is weak; avoid adding until risk is rechecked.")

    return {
        "label": "Research entry zone",
        "current_price": round(current, 2),
        "starter_zone": {
            "low": round(min(starter_low, starter_high), 2),
            "high": round(max(starter_low, starter_high), 2),
            "below_current_pct": [round(starter_high_pct * 100, 1), round(starter_low_pct * 100, 1)],
        },
        "stronger_add_watch_zone": {
            "low": round(min(stronger_low, stronger_high), 2),
            "high": round(max(stronger_low, stronger_high), 2),
            "below_current_pct": [round(stronger_high_pct * 100, 1), round(stronger_low_pct * 100, 1)],
        },
        "do_not_chase_above": round(do_not_chase_above, 2),
        "do_not_chase_above_pct": round(chase_pct * 100, 1),
        "support_reference": supports,
        "confidence": "medium" if thesis >= 60 and news >= 45 else "low",
        "notes": reasons[:5],
        "disclaimer": "Research prompt only. Not financial advice, not a buy order, and not a guaranteed fair value.",
    }
