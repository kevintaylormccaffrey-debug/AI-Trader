from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
from typing import Any

import requests
import yaml


DEFAULT_SETTINGS: dict[str, Any] = {
    "portfolio_path": "data/portfolio.json",
    "watchlist_path": "data/watchlist.json",
    "output_dir": "output",
    "dashboard_path": "output/dashboard.html",
    "report_path": "output/latest_report.json",
    "market_data": {
        "timeout_seconds": 12,
        "history_days": 90,
        "user_agent": "KevinStockResearchAgent/0.1",
    },
    "news": {"lookback_days": 7, "max_items_per_ticker": 5, "timeout_seconds": 12},
    "openai": {
        "gpt_enabled": True,
        "rules_only_mode": False,
        "model": "gpt-5-nano",
        "api_url": "https://api.openai.com/v1/responses",
        "max_gpt_calls_per_day": 4,
        "max_articles_per_run": 8,
        "max_events_per_call": 3,
        "max_tokens_per_call": 800,
        "max_daily_gpt_budget_estimate": 0.05,
        "estimated_input_cost_per_1m_tokens": 0.05,
        "estimated_output_cost_per_1m_tokens": 0.40,
        "relevance_threshold": 55,
        "price_move_threshold_pct": 5,
        "unusual_volume_ratio": 2.0,
        "important_classifications": ["risk elevated", "research opportunity", "sell watch"],
    },
    "discovery": {"max_ideas": 5, "minimum_price": 5},
    "scoring": {
        "weights": {
            "price_momentum": 0.18,
            "news_sentiment": 0.18,
            "downside_from_cost_basis": 0.20,
            "earnings_proximity": 0.10,
            "sector_trend": 0.14,
            "thesis_risk": 0.12,
            "valuation_caution": 0.08,
        }
    },
    "alerts": {"discord_enabled": True, "max_discord_chars": 1900},
    "history": {
        "signals_history_path": "data/signals_history.json",
        "paper_trades_path": "data/paper_trades.json",
        "evaluation_days": 14,
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(path: str | Path) -> dict[str, Any]:
    settings_path = Path(path)
    if settings_path.exists():
        loaded = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    else:
        loaded = {}
    return deep_merge(DEFAULT_SETTINGS, loaded)


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_json_from_env_or_path(env_var: str, path: str | Path) -> dict[str, Any]:
    raw = os.getenv(env_var)
    if raw:
        return json.loads(raw)
    return load_json(path)


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, sort_keys=False), encoding="utf-8")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def today_utc() -> dt.date:
    return utc_now().date()


def user_agent(settings: dict[str, Any]) -> str:
    return str(settings.get("market_data", {}).get("user_agent") or "StockResearchAgent/0.1")


def http_get(url: str, settings: dict[str, Any], timeout_key: str = "market_data") -> tuple[str | None, str | None]:
    timeout = settings.get(timeout_key, {}).get("timeout_seconds")
    if timeout is None:
        timeout = settings.get("market_data", {}).get("timeout_seconds", 12)
    headers = {
        "User-Agent": user_agent(settings),
        "Accept": "text/csv,application/rss+xml,application/xml,text/xml,*/*",
    }
    try:
        response = requests.get(url, headers=headers, timeout=float(timeout))
        response.raise_for_status()
        return response.text, None
    except requests.RequestException as exc:
        return None, str(exc)


def safe_float(value: Any) -> float | None:
    if value in (None, "", "N/D", "null"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def stooq_symbol(ticker: str) -> str:
    clean = ticker.strip().lower().replace("-", ".")
    if clean.endswith(".us"):
        return clean
    return f"{clean}.us"


def fetch_stooq_quote(
    ticker: str,
    settings: dict[str, Any],
    fallback_price: float | None = None,
) -> dict[str, Any]:
    symbol = stooq_symbol(ticker)
    url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
    text, error = http_get(url, settings, "market_data")
    quote: dict[str, Any] = {
        "ticker": ticker.upper(),
        "price": fallback_price,
        "open": None,
        "high": None,
        "low": None,
        "volume": None,
        "as_of": utc_now().isoformat(),
        "source": "portfolio_fallback" if fallback_price is not None else "unavailable",
        "source_url": url,
        "error": error,
    }
    if not text:
        return quote

    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        quote["error"] = "Stooq returned no quote rows."
        return quote

    row = rows[0]
    close = safe_float(row.get("Close"))
    if close is None:
        quote["error"] = quote["error"] or f"Stooq returned no close price for {ticker}."
        return quote

    quote.update(
        {
            "price": close,
            "open": safe_float(row.get("Open")),
            "high": safe_float(row.get("High")),
            "low": safe_float(row.get("Low")),
            "volume": safe_float(row.get("Volume")),
            "as_of": f"{row.get('Date')}T{row.get('Time')}Z",
            "source": "stooq",
            "error": None,
        }
    )
    return quote


def fetch_price_history(ticker: str, settings: dict[str, Any], days: int | None = None) -> list[dict[str, Any]]:
    lookback_days = days or int(settings.get("market_data", {}).get("history_days", 90))
    end = today_utc()
    start = end - dt.timedelta(days=lookback_days * 2)
    symbol = stooq_symbol(ticker)
    url = (
        "https://stooq.com/q/d/l/"
        f"?s={symbol}&i=d&d1={start:%Y%m%d}&d2={end:%Y%m%d}"
    )
    text, error = http_get(url, settings, "market_data")
    if not text:
        return [{"error": error, "source_url": url}]

    history: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(text)):
        close = safe_float(row.get("Close"))
        if close is None:
            continue
        history.append(
            {
                "date": row.get("Date"),
                "open": safe_float(row.get("Open")),
                "high": safe_float(row.get("High")),
                "low": safe_float(row.get("Low")),
                "close": close,
                "volume": safe_float(row.get("Volume")),
                "source": "stooq",
                "source_url": url,
            }
        )
    return history[-lookback_days:]


def fetch_market_snapshot(
    ticker: str,
    settings: dict[str, Any],
    fallback_price: float | None = None,
) -> dict[str, Any]:
    quote = fetch_stooq_quote(ticker, settings, fallback_price)
    history = fetch_price_history(ticker, settings)
    clean_history = [row for row in history if row.get("close") is not None]

    if quote.get("price") is None and clean_history:
        quote["price"] = clean_history[-1]["close"]
        quote["source"] = "stooq_history"
        quote["as_of"] = clean_history[-1]["date"]

    if len(clean_history) >= 2:
        previous_close = clean_history[-2]["close"]
        quote["previous_close"] = previous_close
        if quote.get("price") and previous_close:
            quote["daily_change_pct"] = round((quote["price"] - previous_close) / previous_close * 100, 2)
    else:
        quote["previous_close"] = None
        quote["daily_change_pct"] = None

    quote["history"] = clean_history
    return quote


def fetch_earnings_date(ticker: str, settings: dict[str, Any]) -> dict[str, Any]:
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker.upper()}?modules=calendarEvents"
    text, error = http_get(url, settings, "market_data")
    result = {
        "ticker": ticker.upper(),
        "earnings_date": None,
        "source": "yahoo_quote_summary",
        "source_url": url,
        "error": error,
    }
    if not text:
        return result
    try:
        payload = json.loads(text)
        quote_summary = payload.get("quoteSummary", {})
        results = quote_summary.get("result") or []
        calendar = (results[0] if results else {}).get("calendarEvents", {})
        earnings = calendar.get("earnings", {})
        dates = earnings.get("earningsDate") or []
        if dates:
            raw = dates[0].get("raw")
            if raw:
                result["earnings_date"] = dt.datetime.fromtimestamp(raw, dt.timezone.utc).date().isoformat()
                result["error"] = None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        result["error"] = str(exc)
    return result


def dashboard_url(settings: dict[str, Any]) -> str:
    return os.getenv("DASHBOARD_URL") or str(settings.get("dashboard", {}).get("url") or "")
