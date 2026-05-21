from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
from typing import Any

from src import data_sources
from src.dashboard import generate_dashboard
from src.discord_alerts import send_discord_alert
from src.discovery import generate_discovery_ideas
from src.gpt_analysis import analyze_events
from src.history import update_signal_history
from src.news import fetch_recent_news, summarize_news
from src.sanitize import sanitize_report
from src.scoring import classify_holding, score_holding, score_price_momentum, score_research_candidate


def round_money(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def resolve_path(path: str | Path) -> Path:
    return Path(path)


def build_sector_signals(settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    proxy_map = settings.get("market_data", {}).get("sector_proxy_map", {})
    signals: dict[str, dict[str, Any]] = {}
    for sector_key, proxy in proxy_map.items():
        market = data_sources.fetch_market_snapshot(str(proxy), settings)
        score = score_price_momentum(market.get("history", []))
        details = dict(score.get("details", {}))
        details["proxy_ticker"] = proxy
        signals[str(sector_key)] = {
            "score": score["score"],
            "reason": f"{sector_key} proxy {proxy}: {score['reason']}",
            "details": details,
        }
    return signals


def current_run_session() -> str:
    override = os.getenv("RUN_SESSION")
    if override:
        return override.strip().lower()
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    if event_name and event_name != "schedule":
        return event_name.replace("_", "-").lower()
    now = data_sources.utc_now()
    if now.hour < 16:
        return "morning"
    if now.hour < 22:
        return "afternoon"
    return "off-hours"


def enrich_holding(
    holding: dict[str, Any],
    settings: dict[str, Any],
    sector_signals: dict[str, dict[str, Any]],
    total_value: float,
) -> dict[str, Any]:
    ticker = str(holding["ticker"]).upper()
    market = data_sources.fetch_market_snapshot(ticker, settings, holding.get("current_price"))
    news_items = fetch_recent_news(ticker, settings)
    earnings = data_sources.fetch_earnings_date(ticker, settings)
    scores = score_holding(
        holding,
        market,
        news_items,
        earnings.get("earnings_date"),
        sector_signals,
        settings,
    )

    current_price = market.get("price") or holding.get("current_price")
    shares = float(holding.get("shares", 0))
    cost_basis = float(holding.get("cost_basis", 0))
    current_value = shares * float(current_price or 0)
    cost_value = shares * cost_basis
    gain_loss = current_value - cost_value
    gain_loss_pct = (gain_loss / cost_value * 100) if cost_value else None
    position_weight_pct = (current_value / total_value * 100) if total_value else None

    metrics = {
        "current_price": current_price,
        "current_value": current_value,
        "unrealized_gain_loss": gain_loss,
        "unrealized_gain_loss_pct": gain_loss_pct,
        "position_weight_pct": position_weight_pct,
    }
    classification = classify_holding(holding, metrics, scores, settings)

    return {
        **holding,
        "ticker": ticker,
        "current_price": round_money(current_price),
        "previous_close": round_money(market.get("previous_close")),
        "daily_change_pct": market.get("daily_change_pct"),
        "current_value": round_money(current_value),
        "cost_value": round_money(cost_value),
        "unrealized_gain_loss": round_money(gain_loss),
        "unrealized_gain_loss_pct": round(gain_loss_pct, 2) if gain_loss_pct is not None else None,
        "position_weight_pct": round(position_weight_pct, 2) if position_weight_pct is not None else None,
        "market_data_source": market.get("source"),
        "market_data_as_of": market.get("as_of"),
        "earnings_date": earnings.get("earnings_date"),
        "news_summary": summarize_news(news_items),
        "news": news_items,
        "scores": scores,
        "action": classification["action"],
        "action_reasoning": classification["reasoning"],
        "action_triggers": classification["triggers"],
    }


def enrich_watchlist_item(
    item: dict[str, Any],
    settings: dict[str, Any],
    sector_signals: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ticker = str(item["ticker"]).upper()
    market = data_sources.fetch_market_snapshot(ticker, settings)
    news_items = fetch_recent_news(ticker, settings)
    earnings = data_sources.fetch_earnings_date(ticker, settings)
    scores = score_research_candidate(
        item,
        market,
        news_items,
        earnings.get("earnings_date"),
        sector_signals,
        settings,
    )
    return {
        **item,
        "ticker": ticker,
        "current_price": round_money(market.get("price")),
        "previous_close": round_money(market.get("previous_close")),
        "daily_change_pct": market.get("daily_change_pct"),
        "market_data_source": market.get("source"),
        "earnings_date": earnings.get("earnings_date"),
        "news_summary": summarize_news(news_items),
        "news": news_items,
        "scores": scores,
        "action": "research only",
        "action_reasoning": "Watchlist item only; review manually before any portfolio decision.",
    }


def build_report(settings: dict[str, Any]) -> dict[str, Any]:
    portfolio = data_sources.load_json_from_env_or_path("PORTFOLIO_JSON", resolve_path(settings["portfolio_path"]))
    watchlist = data_sources.load_json_from_env_or_path("WATCHLIST_JSON", resolve_path(settings["watchlist_path"]))
    sector_signals = build_sector_signals(settings)

    cash = portfolio.get("cash_position", {})
    cash_value = float(cash.get("value", 0) or 0)
    preliminary_total = cash_value
    for holding in portfolio.get("holdings", []):
        shares = float(holding.get("shares", 0))
        preliminary_total += shares * float(holding.get("current_price", 0) or 0)

    holdings = [
        enrich_holding(holding, settings, sector_signals, preliminary_total)
        for holding in portfolio.get("holdings", [])
    ]
    invested_value = sum(float(item.get("current_value") or 0) for item in holdings)
    total_value = invested_value + cash_value

    if total_value and abs(total_value - preliminary_total) > 0.01:
        for item in holdings:
            item["position_weight_pct"] = round(float(item.get("current_value") or 0) / total_value * 100, 2)

    watchlist_items = [
        enrich_watchlist_item(item, settings, sector_signals)
        for item in watchlist.get("tickers", [])
    ]
    discovery_ideas = generate_discovery_ideas(portfolio, watchlist, settings, sector_signals)

    news_catalysts = []
    for item in holdings + watchlist_items:
        news_catalysts.extend(item.get("news", []))
    news_catalysts.sort(key=lambda row: row.get("published_at") or "", reverse=True)

    cost_value = sum(float(item.get("cost_value") or 0) for item in holdings)
    unrealized = sum(float(item.get("unrealized_gain_loss") or 0) for item in holdings)
    unrealized_pct = (unrealized / cost_value * 100) if cost_value else None
    sell_watch = [item for item in holdings if item.get("action") == "sell watch"]
    high_priority_alerts = [
        item
        for item in holdings
        if item.get("watch_priority") == "high" and item.get("action") in {"sell watch", "research only", "add watch"}
    ]

    generated_at = data_sources.utc_now().isoformat()
    run_session = current_run_session()
    dashboard_url = data_sources.dashboard_url(settings)
    report: dict[str, Any] = {
        "generated_at": generated_at,
        "run_session": run_session,
        "dashboard_title": settings.get("dashboard", {}).get("title", "Stock Research Agent"),
        "dashboard_url": dashboard_url,
        "disclaimer": "Not financial advice. Human review required. This agent does not execute trades.",
        "portfolio_summary": {
            "portfolio_name": portfolio.get("portfolio_name"),
            "cash_ticker": cash.get("ticker"),
            "cash_value": round_money(cash_value),
            "cash_yield_7d": cash.get("yield_7d"),
            "invested_value": round_money(invested_value),
            "total_value": round_money(total_value),
            "cost_value": round_money(cost_value),
            "unrealized_gain_loss": round_money(unrealized),
            "unrealized_gain_loss_pct": round(unrealized_pct, 2) if unrealized_pct is not None else None,
            "sell_watch_count": len(sell_watch),
            "high_priority_alert_count": len(high_priority_alerts),
        },
        "holdings": holdings,
        "watchlist": watchlist_items,
        "news_catalysts": news_catalysts,
        "sell_watch": sell_watch,
        "high_priority_alerts": high_priority_alerts,
        "discovery_ideas": discovery_ideas,
        "sector_signals": sector_signals,
        "methodology": {
            "summary": "Scores are transparent rule-based research signals. Higher component scores generally mean lower concern or stronger confirmation. They are not buy/sell instructions.",
            "weights": settings.get("scoring", {}).get("weights", {}),
            "components": [
                "price_momentum",
                "news_sentiment",
                "downside_from_cost_basis",
                "earnings_proximity",
                "sector_trend",
                "thesis_risk",
                "valuation_caution",
            ],
            "safety_rules": [
                "Never execute trades.",
                "Never claim guaranteed returns.",
                "Never issue blind buy-now alerts.",
                "Use research-candidate, sell-watch, risk-elevated, and hold-thesis-intact language.",
                "Include uncertainty because data can lag and signals can be wrong.",
            ],
            "data_sources": [
                "Stooq public CSV for prices and price history, with portfolio fallback prices if unavailable.",
                "Yahoo Finance and Google News RSS feeds for recent headlines.",
                "Yahoo quote summary calendar events for best-effort earnings dates.",
                "OpenAI Responses API for important-event analysis when enabled and within configured cost limits.",
            ],
        },
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate stock research report, dashboard, and optional Discord alert.")
    parser.add_argument("--settings", default="config/settings.yaml", help="Path to settings YAML.")
    parser.add_argument("--skip-discord", action="store_true", help="Generate outputs without sending Discord alert.")
    args = parser.parse_args()

    settings = data_sources.load_settings(args.settings)
    report = build_report(settings)
    report["gpt_analysis"] = analyze_events(report, settings)
    history_payload = update_signal_history(report, settings)
    report["signal_history"] = history_payload["signals_history"]
    report["paper_trades"] = history_payload["paper_trades"]

    report_path = resolve_path(settings["report_path"])
    dashboard_path = resolve_path(settings["dashboard_path"])
    data_sources.write_json(report_path, report)
    generate_dashboard(report, dashboard_path)

    public_report = sanitize_report(report)
    public_report_path = resolve_path(settings.get("public_report_path", "public/latest_report.json"))
    public_dashboard_path = resolve_path(settings.get("public_dashboard_path", "public/dashboard.html"))
    data_sources.write_json(public_report_path, public_report)
    generate_dashboard(public_report, public_dashboard_path)

    if not args.skip_discord:
        send_result = send_discord_alert(report, settings)
        report["discord_alert"] = send_result
        data_sources.write_json(report_path, report)

    print(f"Wrote {report_path}")
    print(f"Wrote {dashboard_path}")
    print(f"Wrote {public_report_path}")
    print(f"Wrote {public_dashboard_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
