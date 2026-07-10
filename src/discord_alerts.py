from __future__ import annotations

import os
from typing import Any

import requests

from src.data_sources import dashboard_url


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.2f}"


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%"


def trim_lines(lines: list[str], max_chars: int) -> str:
    message = "\n".join(lines)
    if len(message) <= max_chars:
        return message
    keep = max(0, max_chars - 80)
    return message[:keep].rstrip() + "\n...trimmed. Open dashboard for full report."


def score(item: dict[str, Any]) -> float:
    try:
        return float(item.get("scores", {}).get("overall_score", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def component_score(item: dict[str, Any], key: str) -> float:
    try:
        return float(item.get("scores", {}).get("components", {}).get(key, {}).get("score", 50) or 50)
    except (TypeError, ValueError):
        return 50.0


def component_details(item: dict[str, Any], key: str) -> dict[str, Any]:
    details = item.get("scores", {}).get("components", {}).get(key, {}).get("details", {})
    return details if isinstance(details, dict) else {}


def format_pct_value(value: Any) -> str:
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def short_reason(item: dict[str, Any], limit: int = 130) -> str:
    reason = str(item.get("action_reasoning") or item.get("why_it_matches") or item.get("risk") or "Review the dashboard notes.")
    if len(reason) <= limit:
        return reason
    return reason[: limit - 3].rstrip() + "..."


def add_review_context(item: dict[str, Any]) -> str:
    parts: list[str] = []
    momentum = component_score(item, "price_momentum")
    momentum_details = component_details(item, "price_momentum")
    if momentum >= 58:
        parts.append(
            "momentum improving"
            f" ({format_pct_value(momentum_details.get('change_5d_pct'))} 5d,"
            f" {format_pct_value(momentum_details.get('change_20d_pct'))} 20d)"
        )
    thesis = component_score(item, "thesis_risk")
    if thesis >= 60:
        parts.append("thesis risk score is healthy")
    news = component_score(item, "news_sentiment")
    if news >= 54:
        parts.append("recent news is neutral-to-constructive")
    downside = component_score(item, "downside_from_cost_basis")
    downside_details = component_details(item, "downside_from_cost_basis")
    if downside >= 60 and downside_details.get("pnl_pct_from_cost") is not None:
        parts.append(f"position is above cost basis ({format_pct_value(downside_details.get('pnl_pct_from_cost'))})")
    sector = component_score(item, "sector_trend")
    if sector >= 55:
        parts.append("sector proxy is supportive")
    valuation = component_score(item, "valuation_caution")
    if valuation <= 50:
        parts.append("valuation/position sizing still needs review")
    if not parts:
        parts.append(short_reason(item, 110))
    return "; ".join(parts[:4])


def entry_zone_context(item: dict[str, Any]) -> str | None:
    zone = item.get("entry_zone") or {}
    starter = zone.get("starter_zone") or {}
    stronger = zone.get("stronger_add_watch_zone") or {}
    starter_pct = starter.get("below_current_pct")
    stronger_pct = stronger.get("below_current_pct")
    chase_pct = zone.get("do_not_chase_above_pct")
    if not starter_pct:
        return None

    def pct_range(values: Any) -> str:
        if isinstance(values, list) and len(values) >= 2:
            return f"{values[0]}%-{values[1]}% below current"
        return "pullback from current"

    text = f"Entry research zone: {pct_range(starter_pct)}"
    if stronger_pct:
        text += f"; stronger add-watch: {pct_range(stronger_pct)}"
    if chase_pct:
        text += f"; do-not-chase above +{chase_pct}%"
    return text


def queue_reason(entry: dict[str, Any], key: str, limit: int = 150) -> str:
    values = entry.get(key) or []
    if isinstance(values, list):
        text = "; ".join(str(value) for value in values[:2] if value)
    else:
        text = str(values)
    if not text:
        text = "Open dashboard for full context."
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def queue_entry_line(entry: dict[str, Any]) -> list[str]:
    ticker = entry.get("ticker")
    label = entry.get("recommendation_label")
    score_value = entry.get("score")
    try:
        score_text = f"{float(score_value):.1f}"
    except (TypeError, ValueError):
        score_text = "n/a"
    lines = [
        f"- {ticker}: {label} | score {score_text} | Why: {queue_reason(entry, 'why_now')}",
    ]
    zone_text = entry_zone_context(entry)
    if zone_text:
        lines.append(f"  {zone_text}")
    caution = queue_reason(entry, "cautions", 120)
    if caution:
        lines.append(f"  Watch: {caution}")
    return lines


def build_discord_message(report: dict[str, Any], settings: dict[str, Any]) -> str:
    summary = report.get("portfolio_summary", {})
    queue = report.get("action_queue", {}) or {}
    url = dashboard_url(settings) or report.get("dashboard_url") or "Dashboard URL not configured"

    lines = [
        "**Today's Top Stock Research Queue**",
        f"Portfolio: {summary.get('portfolio_name', 'Portfolio')} | Total: {money(summary.get('total_value'))} | Day data as of {report.get('generated_at', 'n/a')}",
        f"Unrealized P/L: {money(summary.get('unrealized_gain_loss'))} ({pct(summary.get('unrealized_gain_loss_pct'))})",
    ]

    buy_entries = queue.get("research_to_buy", [])[:2]
    add_entries = queue.get("research_to_add", [])[:2]
    risk_entries = queue.get("risk_elevated", [])[:2]
    sell_entries = queue.get("sell_watch", [])[:2]

    if buy_entries:
        lines.append("**Research to Buy, not automatic buys**")
        for entry in buy_entries:
            lines.extend(queue_entry_line(entry))

    if add_entries:
        lines.append("**Research to Add / Buy More**")
        for entry in add_entries:
            lines.extend(queue_entry_line(entry))
    else:
        lines.append("Research to Add: no owned positions cleared the add-watch filter today.")

    if sell_entries:
        lines.append("**Sell Watch**")
        for entry in sell_entries:
            lines.extend(queue_entry_line(entry))
    elif risk_entries:
        lines.append("**Risk Elevated**")
        for entry in risk_entries:
            lines.extend(queue_entry_line(entry))
    else:
        lines.append("Risk / sell-thesis review: none triggered.")

    gpt_events = [
        event
        for event in report.get("gpt_analysis", {}).get("events", [])
        if event.get("analysis_source") == "gpt"
        and event.get("classification") in settings.get("openai", {}).get("important_classifications", [])
    ]
    if gpt_events:
        lines.append("**GPT event notes**")
        for event in gpt_events[:2]:
            lines.append(
                f"- {event.get('ticker')}: {event.get('classification')} ({event.get('confidence_score')}) - {event.get('why_it_matters')}"
            )

    signal_accuracy = report.get("signal_accuracy", {})
    if signal_accuracy:
        reviewed_today = signal_accuracy.get("reviewed_today", [])
        insight = signal_accuracy.get("scoring_insight") or "Collecting signal outcomes."
        lines.append("**Learning Update**")
        if reviewed_today:
            for signal in reviewed_today[:3]:
                result = "right" if signal.get("successful") else "wrong"
                lines.append(
                    f"- {signal.get('ticker')}: {signal.get('recommendation_label')} reviewed {result} ({pct(signal.get('return_since_signal_pct'))})"
                )
        else:
            lines.append("- No signals reached review date today.")
        lines.append(f"- Insight: {insight}")

    lines.extend(
        [
            f"Dashboard: {url}",
            "**Not financial advice. Human review required. Treat these as prompts to research, not instructions to trade.**",
        ]
    )
    return trim_lines(lines, int(settings.get("alerts", {}).get("max_discord_chars", 1900)))


def send_discord_alert(report: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    if not settings.get("alerts", {}).get("discord_enabled", True):
        return {"sent": False, "reason": "Discord alerts disabled in settings."}

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return {"sent": False, "reason": "DISCORD_WEBHOOK_URL is not set; skipped Discord send."}

    message = build_discord_message(report, settings)
    try:
        response = requests.post(webhook_url, json={"content": message}, timeout=12)
        response.raise_for_status()
        return {"sent": True, "status_code": response.status_code}
    except requests.RequestException as exc:
        return {"sent": False, "reason": str(exc)}
