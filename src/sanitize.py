from __future__ import annotations

import copy
import re
from typing import Any


EXACT_FINANCIAL_FIELDS = {
    "shares",
    "cost_basis",
    "current_price",
    "previous_close",
    "current_value",
    "cost_value",
    "unrealized_gain_loss",
    "cash_value",
    "invested_value",
    "total_value",
    "value",
    "sell_watch_threshold_price",
    "price_at_signal",
    "current_price_at_evaluation",
    "entry_price",
    "benchmark_price_at_signal",
    "current_price",
    "do_not_chase_above",
    "support_reference",
    "low",
    "high",
}


def price_band(price: Any) -> str | None:
    if price is None:
        return None
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None

    bands = [
        (5, "Under $5"),
        (10, "$5-$10"),
        (15, "$10-$15"),
        (25, "$15-$25"),
        (50, "$25-$50"),
        (75, "$50-$75"),
        (100, "$75-$100"),
        (150, "$100-$150"),
        (250, "$150-$250"),
        (500, "$250-$500"),
        (750, "$500-$750"),
        (1000, "$750-$1,000"),
    ]
    for ceiling, label in bands:
        if value < ceiling:
            return label
    return "$1,000+"


def redact_exact_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [redact_exact_fields(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"([?&]apikey=)[^&\s]+", r"\1[redacted]", value, flags=re.IGNORECASE)
    if not isinstance(value, dict):
        return value

    redacted: dict[str, Any] = {}
    for key, item in value.items():
        if key in EXACT_FINANCIAL_FIELDS:
            continue
        redacted[key] = redact_exact_fields(item)
    return redacted


def sanitize_security_item(item: dict[str, Any]) -> dict[str, Any]:
    sanitized = redact_exact_fields(item)
    if item.get("current_price") is not None:
        sanitized["price_band"] = price_band(item.get("current_price"))
    if item.get("position_weight_pct") is not None:
        sanitized["portfolio_weight_pct"] = item.get("position_weight_pct")
    if item.get("unrealized_gain_loss_pct") is not None:
        sanitized["unrealized_gain_loss_pct"] = item.get("unrealized_gain_loss_pct")
    return sanitized


def sanitize_news_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": item.get("ticker"),
        "title": item.get("title"),
        "url": item.get("url"),
        "source": item.get("source"),
        "published_at": item.get("published_at"),
        "tag": item.get("tag"),
        "sentiment_score": item.get("sentiment_score"),
        "risk_score": item.get("risk_score"),
        "sentiment_reason": item.get("sentiment_reason"),
    }


def sanitize_report(report: dict[str, Any]) -> dict[str, Any]:
    public_report = copy.deepcopy(report)
    summary = report.get("portfolio_summary", {})
    cash_value = summary.get("cash_value") or 0
    total_value = summary.get("total_value") or 0
    try:
        cash_allocation = round(float(cash_value) / float(total_value) * 100, 2) if total_value else None
    except (TypeError, ValueError, ZeroDivisionError):
        cash_allocation = None

    public_report["privacy"] = {
        "sanitized": True,
        "summary": "Public report redacts exact shares, cost basis, dollar values, and exact prices. Use private latest_report.json for full personal figures.",
    }
    public_report["portfolio_summary"] = {
        "portfolio_name": summary.get("portfolio_name"),
        "cash_ticker": summary.get("cash_ticker"),
        "cash_allocation_pct": cash_allocation,
        "cash_yield_7d": summary.get("cash_yield_7d"),
        "invested_allocation_pct": round(100 - cash_allocation, 2) if cash_allocation is not None else None,
        "unrealized_gain_loss_pct": summary.get("unrealized_gain_loss_pct"),
        "sell_watch_count": summary.get("sell_watch_count"),
        "high_priority_alert_count": summary.get("high_priority_alert_count"),
    }

    public_report["holdings"] = [sanitize_security_item(item) for item in report.get("holdings", [])]
    public_report["watchlist"] = [sanitize_security_item(item) for item in report.get("watchlist", [])]
    public_report["sell_watch"] = [sanitize_security_item(item) for item in report.get("sell_watch", [])]
    public_report["high_priority_alerts"] = [
        sanitize_security_item(item) for item in report.get("high_priority_alerts", [])
    ]
    public_report["discovery_ideas"] = [sanitize_security_item(item) for item in report.get("discovery_ideas", [])]
    public_report["action_queue"] = redact_exact_fields(report.get("action_queue", {}))
    public_report["news_catalysts"] = [sanitize_news_item(item) for item in report.get("news_catalysts", [])]
    public_report["signal_history"] = redact_exact_fields(report.get("signal_history", {}))
    public_report["paper_trades"] = redact_exact_fields(report.get("paper_trades", {}))
    public_report["gpt_analysis"] = redact_exact_fields(report.get("gpt_analysis", {}))
    public_report["signal_accuracy"] = redact_exact_fields(report.get("signal_accuracy", {}))

    for idea in public_report.get("discovery_ideas", []):
        idea.pop("news", None)
    for item in public_report.get("holdings", []) + public_report.get("watchlist", []):
        item.pop("news", None)

    return public_report
