from __future__ import annotations

import datetime as dt
from typing import Any


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def component(score: float, reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "score": round(clamp(score), 1),
        "reason": reason,
        "details": details or {},
    }


def pct_change(history: list[dict[str, Any]], sessions_back: int) -> float | None:
    clean = [row for row in history if row.get("close") is not None]
    if len(clean) < 2:
        return None
    end = float(clean[-1]["close"])
    start_index = max(0, len(clean) - 1 - sessions_back)
    start = float(clean[start_index]["close"])
    if start == 0:
        return None
    return (end - start) / start * 100


def score_price_momentum(history: list[dict[str, Any]]) -> dict[str, Any]:
    change_5d = pct_change(history, 5)
    change_20d = pct_change(history, 20)
    if change_5d is None and change_20d is None:
        return component(50, "Insufficient price history; momentum treated as neutral.", {})

    short = change_5d or 0
    medium = change_20d or short
    raw = 50 + short * 2.2 + medium * 1.15
    score = clamp(raw, 10, 90)
    if score >= 65:
        reason = "Positive short and medium-term price momentum."
    elif score <= 40:
        reason = "Weak price momentum; trend needs review."
    else:
        reason = "Momentum is mixed or close to neutral."
    return component(
        score,
        reason,
        {
            "change_5d_pct": round(short, 2),
            "change_20d_pct": round(medium, 2),
        },
    )


def score_news_sentiment(news_items: list[dict[str, Any]]) -> dict[str, Any]:
    actionable = [item for item in news_items if item.get("title") != "News fetch unavailable"]
    if not actionable:
        return component(50, "No recent high-confidence news signal; sentiment treated as neutral.", {})

    avg_sentiment = sum(float(item.get("sentiment_score") or 0) for item in actionable) / len(actionable)
    avg_risk = sum(float(item.get("risk_score") or 50) for item in actionable) / len(actionable)
    score = 50 + avg_sentiment * 35 - max(0, avg_risk - 50) * 0.35
    if score >= 62:
        reason = "Recent catalyst language skews constructive."
    elif score <= 38:
        reason = "Recent news contains elevated negative or risk language."
    else:
        reason = "Recent news is mixed, low-signal, or balanced."
    return component(
        score,
        reason,
        {
            "average_sentiment": round(avg_sentiment, 2),
            "average_risk": round(avg_risk, 1),
            "top_tags": sorted({item.get("tag", "other") for item in actionable})[:5],
        },
    )


def score_downside_from_cost_basis(
    current_price: float | None,
    cost_basis: float | None,
    max_loss_pct: float | None,
) -> dict[str, Any]:
    if not current_price or not cost_basis:
        return component(50, "No cost basis is available; downside-from-cost score is neutral.", {})

    pnl_pct = (current_price - cost_basis) / cost_basis * 100
    max_loss = float(max_loss_pct or 15)
    threshold_price = cost_basis * (1 - max_loss / 100)
    if pnl_pct >= 0:
        score = 65 + min(25, pnl_pct * 0.18)
        reason = "Position is above cost basis."
    else:
        drawdown = abs(pnl_pct)
        score = 65 - (drawdown / max(max_loss, 1)) * 55
        reason = "Position is below cost basis; compare to max-loss rule."
    return component(
        score,
        reason,
        {
            "pnl_pct_from_cost": round(pnl_pct, 2),
            "max_loss_pct": max_loss,
            "sell_watch_threshold_price": round(threshold_price, 2),
        },
    )


def score_earnings_proximity(earnings_date: str | None, now: dt.date | None = None) -> dict[str, Any]:
    if not earnings_date:
        return component(50, "Upcoming earnings date unavailable; score treated as neutral.", {})

    today = now or dt.datetime.now(dt.timezone.utc).date()
    try:
        event_date = dt.date.fromisoformat(earnings_date[:10])
    except ValueError:
        return component(50, "Earnings date could not be parsed; score treated as neutral.", {"raw": earnings_date})

    days = (event_date - today).days
    if 0 <= days <= 7:
        return component(35, "Earnings are within one week; gap risk elevated.", {"days_until_earnings": days})
    if 8 <= days <= 21:
        return component(45, "Earnings are approaching; watch catalyst risk.", {"days_until_earnings": days})
    if -2 <= days < 0:
        return component(45, "Earnings just occurred; post-report volatility can linger.", {"days_since_earnings": abs(days)})
    return component(58, "No near-term earnings event detected.", {"days_until_earnings": days})


def score_sector_trend(sector: str, sector_signals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sector_lower = (sector or "").lower()
    for key, signal in sector_signals.items():
        if key.lower() in sector_lower:
            return component(
                float(signal.get("score", 50)),
                str(signal.get("reason", "Sector proxy trend used.")),
                {"matched_sector": key, **signal.get("details", {})},
            )

    if any(term in sector_lower for term in ("semiconductor", "ai", "datacenter")):
        return component(58, "Sector has strategic AI/datacenter relevance, but proxy trend was unavailable.", {})
    if "index" in sector_lower:
        return component(55, "Broad-market core exposure; sector signal is treated as moderate.", {})
    return component(50, "No sector proxy matched; sector trend treated as neutral.", {})


def score_thesis_risk(
    item: dict[str, Any],
    news_items: list[dict[str, Any]],
    pnl_pct: float | None = None,
) -> dict[str, Any]:
    score = 70.0
    reasons: list[str] = []
    sector = str(item.get("sector", "")).lower()
    status = str(item.get("status", ""))

    if status == "core_holding":
        score += 8
        reasons.append("core holding")
    if any(term in sector for term in ("high-growth", "ai", "automation", "semiconductor", "datacenter")):
        score -= 4
        reasons.append("growth sector expectations")

    if news_items:
        avg_risk = sum(float(news.get("risk_score") or 50) for news in news_items) / len(news_items)
        if avg_risk > 65:
            score -= 18
            reasons.append("news risk elevated")
        elif avg_risk < 35:
            score += 5
            reasons.append("news risk contained")

    if pnl_pct is not None and pnl_pct < -10:
        score -= 10
        reasons.append("price action challenges thesis")

    reason = "Thesis risk based on sector, status, news risk, and price confirmation."
    if reasons:
        reason += " Signals: " + ", ".join(reasons) + "."
    return component(score, reason, {"signals": reasons})


def score_valuation_caution(item: dict[str, Any], current_price: float | None = None) -> dict[str, Any]:
    sector = str(item.get("sector", "")).lower()
    warning_text = str(item.get("valuation_warning") or item.get("valuation_note") or "").lower()
    cost_basis = item.get("cost_basis")
    metrics = item.get("financial_metrics") or {}
    score = 60.0
    details: dict[str, Any] = {}

    if "index" in sector:
        score = 72
        reason = "Diversified ETF valuation risk is tracked through broad market exposure."
    elif any(term in warning_text for term in ("premium", "expensive", "elevated", "multiple")):
        score = 44
        reason = "Valuation warning is explicitly elevated."
    else:
        reason = "No explicit valuation warning; still review multiples before action."

    pe_ratio = metrics.get("peRatio")
    ps_ratio = metrics.get("priceToSalesRatio")
    pfcf_ratio = metrics.get("priceToFreeCashFlowsRatio")
    debt_to_equity = metrics.get("debtToEquity")
    metric_flags: list[str] = []
    for label, raw_value in (
        ("pe_ratio", pe_ratio),
        ("price_to_sales", ps_ratio),
        ("price_to_free_cash_flow", pfcf_ratio),
        ("debt_to_equity", debt_to_equity),
    ):
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        details[label] = round(value, 2)

    try:
        pe = float(pe_ratio)
    except (TypeError, ValueError):
        pe = None
    try:
        ps = float(ps_ratio)
    except (TypeError, ValueError):
        ps = None
    try:
        pfcf = float(pfcf_ratio)
    except (TypeError, ValueError):
        pfcf = None

    if pe and pe > 80:
        score = min(score, 42)
        metric_flags.append("very high P/E")
    elif pe and pe > 45:
        score = min(score, 50)
        metric_flags.append("elevated P/E")
    if ps and ps > 18:
        score = min(score, 42)
        metric_flags.append("very high price/sales")
    elif ps and ps > 10:
        score = min(score, 50)
        metric_flags.append("elevated price/sales")
    if pfcf and pfcf > 80:
        score = min(score, 44)
        metric_flags.append("very high price/free-cash-flow")
    if metric_flags:
        reason = "FMP valuation metrics flag caution: " + ", ".join(metric_flags) + "."
    elif metrics:
        reason = "FMP valuation metrics did not flag an extreme multiple; still compare against peers."

    if current_price and cost_basis:
        price_to_cost = current_price / float(cost_basis)
        details["price_to_cost_basis"] = round(price_to_cost, 2)
        if price_to_cost > 1.8 and "index" not in sector:
            score = min(score, 48)
            reason = "Large gain from cost basis can raise valuation and position-sizing risk."
    if warning_text:
        details["valuation_note"] = item.get("valuation_warning") or item.get("valuation_note")
    return component(score, reason, details)


def aggregate_components(components: dict[str, dict[str, Any]], weights: dict[str, float]) -> float:
    weighted_score = 0.0
    total_weight = 0.0
    for key, item in components.items():
        weight = float(weights.get(key, 0))
        weighted_score += float(item.get("score", 50)) * weight
        total_weight += weight
    if total_weight <= 0:
        return 50.0
    return round(weighted_score / total_weight, 1)


def classify_holding(
    holding: dict[str, Any],
    metrics: dict[str, Any],
    scores: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    scoring_settings = settings.get("scoring", {})
    sell_threshold = float(scoring_settings.get("sell_watch_threshold", 35))
    add_threshold = float(scoring_settings.get("add_watch_threshold", 64))
    elevated_threshold = float(scoring_settings.get("elevated_risk_threshold", 45))
    overall = float(scores.get("overall_score", 50))
    components = scores.get("components", {})

    triggers: list[str] = []
    current_price = metrics.get("current_price")
    threshold_price = components.get("downside_from_cost_basis", {}).get("details", {}).get("sell_watch_threshold_price")
    if current_price and threshold_price and current_price <= threshold_price:
        triggers.append("price is below the configured max-loss threshold")
    if overall <= sell_threshold:
        triggers.append("overall score is below sell-watch threshold")
    if components.get("news_sentiment", {}).get("score", 50) <= 35:
        triggers.append("news sentiment risk is elevated")

    if triggers:
        action = "sell watch"
        explanation = "Human review required: " + "; ".join(triggers) + "."
    elif holding.get("status") == "core_holding":
        action = "hold"
        explanation = "Core holding; continue monitoring broad-market exposure and allocation."
    elif overall >= add_threshold and components.get("price_momentum", {}).get("score", 50) >= 58:
        action = "add watch"
        explanation = "Research candidate for potential additional attention; no automatic buy signal."
    elif overall < elevated_threshold:
        action = "research only"
        explanation = "Risk elevated or signal weak; thesis needs review before any action."
    else:
        action = "hold"
        explanation = "Hold thesis intact, with routine monitoring."

    return {"action": action, "reasoning": explanation, "triggers": triggers}


def score_holding(
    holding: dict[str, Any],
    market: dict[str, Any],
    news_items: list[dict[str, Any]],
    earnings_date: str | None,
    sector_signals: dict[str, dict[str, Any]],
    settings: dict[str, Any],
) -> dict[str, Any]:
    current_price = market.get("price")
    cost_basis = holding.get("cost_basis")
    pnl_pct = None
    if current_price and cost_basis:
        pnl_pct = (float(current_price) - float(cost_basis)) / float(cost_basis) * 100

    components = {
        "price_momentum": score_price_momentum(market.get("history", [])),
        "news_sentiment": score_news_sentiment(news_items),
        "downside_from_cost_basis": score_downside_from_cost_basis(current_price, cost_basis, holding.get("max_loss_pct")),
        "earnings_proximity": score_earnings_proximity(earnings_date),
        "sector_trend": score_sector_trend(str(holding.get("sector", "")), sector_signals),
        "thesis_risk": score_thesis_risk(holding, news_items, pnl_pct),
        "valuation_caution": score_valuation_caution(holding, current_price),
    }
    weights = settings.get("scoring", {}).get("weights", {})
    overall = aggregate_components(components, weights)
    return {
        "overall_score": overall,
        "components": components,
    }


def score_research_candidate(
    candidate: dict[str, Any],
    market: dict[str, Any],
    news_items: list[dict[str, Any]],
    earnings_date: str | None,
    sector_signals: dict[str, dict[str, Any]],
    settings: dict[str, Any],
) -> dict[str, Any]:
    components = {
        "price_momentum": score_price_momentum(market.get("history", [])),
        "news_sentiment": score_news_sentiment(news_items),
        "downside_from_cost_basis": component(
            50,
            "No owned cost basis; downside-from-cost is not applicable for research candidates.",
            {"not_applicable": True},
        ),
        "earnings_proximity": score_earnings_proximity(earnings_date),
        "sector_trend": score_sector_trend(str(candidate.get("sector", "")), sector_signals),
        "thesis_risk": score_thesis_risk(candidate, news_items, None),
        "valuation_caution": score_valuation_caution(candidate, market.get("price")),
    }
    overall = aggregate_components(components, settings.get("scoring", {}).get("weights", {}))
    return {
        "overall_score": overall,
        "components": components,
        "action": "research only",
        "reasoning": "Research candidate only; no trade execution or blind buy alert.",
    }
