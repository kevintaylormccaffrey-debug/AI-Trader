from __future__ import annotations

from typing import Any


def _score(item: dict[str, Any]) -> float:
    try:
        return float(item.get("scores", {}).get("overall_score", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _component(item: dict[str, Any], key: str, default: float = 50.0) -> float:
    try:
        return float(item.get("scores", {}).get("components", {}).get(key, {}).get("score", default) or default)
    except (TypeError, ValueError):
        return default


def _details(item: dict[str, Any], key: str) -> dict[str, Any]:
    details = item.get("scores", {}).get("components", {}).get(key, {}).get("details", {})
    return details if isinstance(details, dict) else {}


def _signed_pct(value: Any) -> str:
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _headline_catalysts(item: dict[str, Any], limit: int = 2) -> list[str]:
    headlines: list[str] = []
    for row in item.get("news", [])[:limit]:
        title = row.get("title")
        tag = row.get("tag")
        if title and title != "News fetch unavailable":
            headlines.append(f"{tag}: {title}" if tag else str(title))
    return headlines


def _why_now(item: dict[str, Any], source_type: str) -> list[str]:
    reasons: list[str] = []
    momentum = _component(item, "price_momentum")
    momentum_details = _details(item, "price_momentum")
    if momentum >= 58:
        reasons.append(
            "Momentum supports review"
            f" ({_signed_pct(momentum_details.get('change_5d_pct'))} 5d,"
            f" {_signed_pct(momentum_details.get('change_20d_pct'))} 20d)."
        )
    elif momentum <= 45:
        reasons.append("Momentum is weak or mixed, so this needs confirmation before action.")

    thesis = _component(item, "thesis_risk")
    if thesis >= 60:
        reasons.append("Thesis-risk score is constructive.")
    elif thesis <= 45:
        reasons.append("Thesis-risk score is elevated.")

    news = _component(item, "news_sentiment")
    if news >= 54:
        reasons.append("Recent news tone is neutral-to-constructive.")
    elif news <= 40:
        reasons.append("Recent news tone is a risk flag.")

    sector = _component(item, "sector_trend")
    if sector >= 55:
        reasons.append("Sector/proxy trend is supportive.")
    elif sector <= 45:
        reasons.append("Sector/proxy trend is not confirming the setup.")

    if source_type == "discovery":
        match = item.get("why_it_matches")
        catalyst = item.get("catalyst")
        if match:
            reasons.append(str(match))
        if catalyst:
            reasons.append(f"Catalyst to research: {catalyst}")

    reasons.extend(_headline_catalysts(item))
    return reasons[:5] or ["No single driver dominates; review the full score grid before acting."]


def _cautions(item: dict[str, Any], source_type: str) -> list[str]:
    cautions: list[str] = []
    valuation = _component(item, "valuation_caution")
    if valuation <= 50:
        cautions.append("Valuation or multiple risk needs review.")

    earnings = _component(item, "earnings_proximity")
    if earnings <= 45:
        cautions.append("Near-term earnings or post-earnings volatility may distort the signal.")

    downside = _component(item, "downside_from_cost_basis")
    pnl = _details(item, "downside_from_cost_basis").get("pnl_pct_from_cost")
    if pnl is not None and downside <= 45:
        cautions.append(f"Position is below cost basis ({_signed_pct(pnl)}); check max-loss rules before adding.")
    elif pnl is not None and float(pnl) > 20:
        cautions.append(f"Position is already up {_signed_pct(pnl)} from cost basis; avoid chasing size.")

    if source_type == "discovery":
        risk = item.get("risk")
        valuation_warning = item.get("valuation_warning")
        if risk:
            cautions.append(str(risk))
        if valuation_warning:
            cautions.append(str(valuation_warning))

    if not cautions:
        cautions.append("Signal can be wrong if data lags, news context is incomplete, or market conditions reverse.")
    return cautions[:4]


def _confirmations(item: dict[str, Any], bucket: str) -> list[str]:
    confirmations = [
        "Price holds above key trend/support references instead of breaking down.",
        "Recent news remains consistent with the investment thesis.",
    ]
    if bucket in {"research_to_buy", "research_to_add"}:
        confirmations.append("Pullback reaches the research entry zone or strength continues without valuation worsening.")
    if bucket in {"risk_elevated", "sell_watch"}:
        confirmations.append("Risk headlines fade and the score recovers on the next run.")
    return confirmations[:3]


def _invalidations(item: dict[str, Any], bucket: str) -> list[str]:
    invalidations = [
        "Thesis-negative news, guidance weakness, legal/regulatory issues, or sharp relative underperformance.",
        "Score deterioration led by momentum, news sentiment, or thesis risk.",
    ]
    if bucket in {"research_to_buy", "research_to_add"}:
        invalidations.append("Price runs above the do-not-chase zone before fundamentals improve.")
    if bucket in {"risk_elevated", "sell_watch"}:
        invalidations.append("Fresh evidence shows the issue is temporary noise rather than thesis damage.")
    return invalidations[:3]


def _entry(
    item: dict[str, Any],
    bucket: str,
    label: str,
    source_type: str,
    priority: int,
) -> dict[str, Any]:
    return {
        "bucket": bucket,
        "recommendation_label": label,
        "source_type": source_type,
        "priority": priority,
        "ticker": item.get("ticker"),
        "company": item.get("company"),
        "sector": item.get("sector"),
        "score": _score(item),
        "confidence": item.get("confidence_level") or item.get("entry_zone", {}).get("confidence") or "medium",
        "current_action": item.get("action"),
        "why_now": _why_now(item, source_type),
        "cautions": _cautions(item, source_type),
        "what_would_confirm": _confirmations(item, bucket),
        "what_would_invalidate": _invalidations(item, bucket),
        "entry_zone": item.get("entry_zone"),
        "action_reasoning": item.get("action_reasoning") or item.get("why_it_matches") or item.get("risk"),
    }


def build_action_queue(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    holdings = list(report.get("holdings", []))
    watchlist = list(report.get("watchlist", []))
    discovery = list(report.get("discovery_ideas", []))

    sell_watch = sorted(
        [item for item in holdings if item.get("action") == "sell watch"],
        key=_score,
    )[:4]
    risk_elevated = sorted(
        [
            item
            for item in holdings
            if item.get("action") == "research only"
            or _score(item) < 50
            or _component(item, "news_sentiment") <= 40
            or _component(item, "thesis_risk") <= 45
        ],
        key=_score,
    )[:4]

    research_to_add = [item for item in holdings if item.get("action") == "add watch"]
    if not research_to_add:
        research_to_add = [
            item
            for item in holdings
            if item.get("status") != "core_holding"
            and _score(item) >= 58
            and _component(item, "price_momentum") >= 58
            and _component(item, "thesis_risk") >= 55
        ]
    research_to_add = sorted(research_to_add, key=_score, reverse=True)[:4]

    buy_pool = [
        *[
            {**item, "_source_type": "watchlist"}
            for item in watchlist
            if _score(item) >= 56 and _component(item, "thesis_risk") >= 55
        ],
        *[{**item, "_source_type": "discovery"} for item in discovery],
    ]
    research_to_buy = sorted(buy_pool, key=_score, reverse=True)[:5]

    hold_thesis_intact = sorted(
        [
            item
            for item in holdings
            if item.get("action") == "hold"
            and item.get("ticker") not in {row.get("ticker") for row in research_to_add}
            and item.get("ticker") not in {row.get("ticker") for row in risk_elevated}
        ],
        key=_score,
        reverse=True,
    )[:5]

    return {
        "research_to_buy": [
            _entry(item, "research_to_buy", "Research to Buy", item.get("_source_type", "discovery"), index + 1)
            for index, item in enumerate(research_to_buy)
        ],
        "research_to_add": [
            _entry(item, "research_to_add", "Research to Add", "holding", index + 1)
            for index, item in enumerate(research_to_add)
        ],
        "hold_thesis_intact": [
            _entry(item, "hold_thesis_intact", "Hold / Thesis Intact", "holding", index + 1)
            for index, item in enumerate(hold_thesis_intact)
        ],
        "risk_elevated": [
            _entry(item, "risk_elevated", "Risk Elevated", "holding", index + 1)
            for index, item in enumerate(risk_elevated)
        ],
        "sell_watch": [
            _entry(item, "sell_watch", "Sell Watch", "holding", index + 1)
            for index, item in enumerate(sell_watch)
        ],
    }
