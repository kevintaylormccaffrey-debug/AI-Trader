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


def build_discord_message(report: dict[str, Any], settings: dict[str, Any]) -> str:
    summary = report.get("portfolio_summary", {})
    sell_watch = report.get("sell_watch", [])
    high_priority = [
        holding
        for holding in report.get("holdings", [])
        if holding.get("watch_priority") == "high" and holding.get("action") != "hold"
    ]
    ideas = report.get("discovery_ideas", [])[:3]
    url = dashboard_url(settings) or report.get("dashboard_url") or "Dashboard URL not configured"

    lines = [
        "**Daily Stock Research Agent**",
        f"Portfolio: {summary.get('portfolio_name', 'Portfolio')} | Total: {money(summary.get('total_value'))} | Day data as of {report.get('generated_at', 'n/a')}",
        f"Unrealized P/L: {money(summary.get('unrealized_gain_loss'))} ({pct(summary.get('unrealized_gain_loss_pct'))})",
    ]

    if high_priority:
        lines.append("**High-priority alerts**")
        for item in high_priority[:4]:
            lines.append(f"- {item['ticker']}: {item['action']} | score {item['scores']['overall_score']} | {item['action_reasoning']}")
    else:
        lines.append("High-priority alerts: none from current rules.")

    if sell_watch:
        lines.append("**Sell watch**")
        for item in sell_watch[:4]:
            lines.append(f"- {item['ticker']}: {item.get('action_reasoning')}")
    else:
        lines.append("Sell watch: none triggered.")

    if ideas:
        lines.append("**New research ideas**")
        for idea in ideas:
            lines.append(f"- {idea['ticker']} ({idea['company']}): {idea['sector']} | confidence {idea['confidence_level']}")

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
            "**Not financial advice. Human review required. No trades are executed by this agent.**",
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
