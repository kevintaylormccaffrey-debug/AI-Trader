from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re
from pathlib import Path
from typing import Any
import urllib.parse

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
        "price_provider": "fmp",
        "price_providers": ["fmp", "yahoo_chart", "stooq"],
        "history_days": 90,
        "user_agent": "KevinStockResearchAgent/0.1",
    },
    "fmp": {
        "enabled": True,
        "api_key_env": "FMP_API_KEY",
        "base_url": "https://financialmodelingprep.com/stable",
        "fundamentals_enabled": True,
    },
    "news": {"lookback_days": 7, "max_items_per_ticker": 5, "timeout_seconds": 12, "sources": ["fmp", "yahoo", "google"]},
    "openai": {
        "gpt_enabled": True,
        "rules_only_mode": False,
        "model": "gpt-5-nano",
        "chat_model": "gpt-5-nano",
        "api_url": "https://api.openai.com/v1/responses",
        "max_gpt_calls_per_day": 8,
        "max_articles_per_run": 16,
        "max_events_per_call": 4,
        "max_tokens_per_call": 900,
        "chat_max_tokens_per_call": 700,
        "max_daily_gpt_budget_estimate": 0.25,
        "estimated_input_cost_per_1m_tokens": 0.05,
        "estimated_output_cost_per_1m_tokens": 0.40,
        "relevance_threshold": 45,
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
        "signal_accuracy_path": "output/signal_accuracy.json",
        "learning_mode": "observe_only",
        "review_after_days": 14,
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


def fmp_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return settings.get("fmp", {})


def fmp_api_key(settings: dict[str, Any]) -> str | None:
    cfg = fmp_settings(settings)
    if not cfg.get("enabled", True):
        return None
    env_name = str(cfg.get("api_key_env") or "FMP_API_KEY")
    return os.getenv(env_name)


def fmp_source_url(endpoint: str, params: dict[str, Any], settings: dict[str, Any]) -> str:
    base_url = str(fmp_settings(settings).get("base_url") or "https://financialmodelingprep.com/stable").rstrip("/")
    clean_params = {key: value for key, value in params.items() if value is not None and key != "apikey"}
    query = urllib.parse.urlencode(clean_params)
    return f"{base_url}/{endpoint.lstrip('/')}?{query}" if query else f"{base_url}/{endpoint.lstrip('/')}"


def redact_url_secret(value: str, api_key: str | None = None) -> str:
    redacted = value
    if api_key:
        redacted = redacted.replace(api_key, "[redacted]")
    return re.sub(r"([?&]apikey=)[^&\s]+", r"\1[redacted]", redacted, flags=re.IGNORECASE)


def fmp_get_json(
    endpoint: str,
    params: dict[str, Any],
    settings: dict[str, Any],
    timeout_key: str = "market_data",
) -> tuple[Any | None, str | None, str]:
    api_key = fmp_api_key(settings)
    public_url = fmp_source_url(endpoint, params, settings)
    if not api_key:
        return None, "FMP_API_KEY is not set; skipped FMP provider.", public_url

    base_url = str(fmp_settings(settings).get("base_url") or "https://financialmodelingprep.com/stable").rstrip("/")
    request_params = {**params, "apikey": api_key}
    timeout = settings.get(timeout_key, {}).get("timeout_seconds")
    if timeout is None:
        timeout = settings.get("market_data", {}).get("timeout_seconds", 12)
    headers = {"User-Agent": user_agent(settings), "Accept": "application/json"}
    try:
        response = requests.get(
            f"{base_url}/{endpoint.lstrip('/')}",
            params=request_params,
            headers=headers,
            timeout=float(timeout),
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return None, redact_url_secret(str(exc), api_key), public_url
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"FMP returned non-JSON response: {exc}", public_url

    if isinstance(payload, dict):
        message = payload.get("Error Message") or payload.get("error") or payload.get("message")
        if message and not payload.get("symbol"):
            return None, str(message), public_url
    return payload, None, public_url


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


def parse_timestamp(value: Any) -> str:
    if value in (None, ""):
        return utc_now().isoformat()
    try:
        return dt.datetime.fromtimestamp(int(value), dt.timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value)


def fetch_fmp_price_history(ticker: str, settings: dict[str, Any], days: int | None = None) -> list[dict[str, Any]]:
    lookback_days = days or int(settings.get("market_data", {}).get("history_days", 90))
    end = today_utc()
    start = end - dt.timedelta(days=lookback_days * 2)
    payload, error, url = fmp_get_json(
        "historical-price-eod/full",
        {"symbol": ticker.upper(), "from": f"{start:%Y-%m-%d}", "to": f"{end:%Y-%m-%d}"},
        settings,
        "market_data",
    )
    if error or not payload:
        return [{"error": error, "source_url": url}]

    rows = payload if isinstance(payload, list) else payload.get("historical", [])
    history: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        close = safe_float(row.get("close") or row.get("adjClose"))
        if close is None:
            continue
        history.append(
            {
                "date": row.get("date"),
                "open": safe_float(row.get("open")),
                "high": safe_float(row.get("high")),
                "low": safe_float(row.get("low")),
                "close": close,
                "volume": safe_float(row.get("volume")),
                "source": "fmp",
                "source_url": url,
            }
        )
    history.sort(key=lambda item: item.get("date") or "")
    return history[-lookback_days:]


def fetch_fmp_quote(
    ticker: str,
    settings: dict[str, Any],
    fallback_price: float | None = None,
) -> dict[str, Any]:
    payload, error, url = fmp_get_json("quote", {"symbol": ticker.upper()}, settings, "market_data")
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
        "history": [],
    }
    if error or not payload:
        return quote

    row = payload[0] if isinstance(payload, list) and payload else payload if isinstance(payload, dict) else {}
    price = safe_float(row.get("price"))
    if price is None:
        quote["error"] = quote["error"] or f"FMP returned no usable price for {ticker}."
        return quote

    previous_close = safe_float(row.get("previousClose"))
    daily_change_pct = safe_float(row.get("changesPercentage") or row.get("changePercentage"))
    quote.update(
        {
            "price": price,
            "open": safe_float(row.get("open")),
            "high": safe_float(row.get("dayHigh") or row.get("high")),
            "low": safe_float(row.get("dayLow") or row.get("low")),
            "volume": safe_float(row.get("volume")),
            "as_of": parse_timestamp(row.get("timestamp")),
            "source": "fmp",
            "error": None,
            "previous_close": previous_close,
            "daily_change_pct": round(daily_change_pct, 2) if daily_change_pct is not None else None,
        }
    )
    return quote


def fetch_fmp_key_metrics(ticker: str, settings: dict[str, Any]) -> dict[str, Any]:
    if not fmp_settings(settings).get("fundamentals_enabled", True):
        return {"ticker": ticker.upper(), "source": "fmp", "metrics": {}, "error": "FMP fundamentals disabled."}
    payload, error, url = fmp_get_json("key-metrics", {"symbol": ticker.upper(), "limit": 1}, settings, "market_data")
    result: dict[str, Any] = {
        "ticker": ticker.upper(),
        "source": "fmp",
        "source_url": url,
        "metrics": {},
        "error": error,
    }
    if error or not payload:
        return result
    row = payload[0] if isinstance(payload, list) and payload else payload if isinstance(payload, dict) else {}
    wanted = (
        "calendarYear",
        "period",
        "peRatio",
        "priceToSalesRatio",
        "priceToFreeCashFlowsRatio",
        "priceEarningsToGrowthRatio",
        "debtToEquity",
        "revenuePerShare",
        "freeCashFlowPerShare",
    )
    result["metrics"] = {key: row.get(key) for key in wanted if row.get(key) is not None}
    result["error"] = None if result["metrics"] else "FMP returned no key metrics."
    return result


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


def fetch_yahoo_chart_snapshot(
    ticker: str,
    settings: dict[str, Any],
    fallback_price: float | None = None,
    days: int | None = None,
) -> dict[str, Any]:
    lookback_days = days or int(settings.get("market_data", {}).get("history_days", 90))
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}?range={lookback_days}d&interval=1d"
    text, error = http_get(url, settings, "market_data")
    snapshot: dict[str, Any] = {
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
        "history": [],
    }
    if not text:
        return snapshot

    try:
        payload = json.loads(text)
        chart = payload.get("chart", {})
        chart_error = chart.get("error")
        if chart_error:
            snapshot["error"] = chart_error.get("description") or str(chart_error)
            return snapshot
        results = chart.get("result") or []
        if not results:
            snapshot["error"] = "Yahoo chart returned no result rows."
            return snapshot

        result = results[0]
        meta = result.get("meta", {})
        timestamps = result.get("timestamp") or []
        quote_blocks = result.get("indicators", {}).get("quote") or []
        quote = quote_blocks[0] if quote_blocks else {}
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        history: list[dict[str, Any]] = []
        for index, raw_ts in enumerate(timestamps):
            close = safe_float(closes[index] if index < len(closes) else None)
            if close is None:
                continue
            stamp = dt.datetime.fromtimestamp(int(raw_ts), dt.timezone.utc)
            history.append(
                {
                    "date": stamp.date().isoformat(),
                    "open": safe_float(opens[index] if index < len(opens) else None),
                    "high": safe_float(highs[index] if index < len(highs) else None),
                    "low": safe_float(lows[index] if index < len(lows) else None),
                    "close": close,
                    "volume": safe_float(volumes[index] if index < len(volumes) else None),
                    "source": "yahoo_chart",
                    "source_url": url,
                }
            )

        last_history = history[-1] if history else {}
        price = safe_float(meta.get("regularMarketPrice")) or last_history.get("close") or fallback_price
        previous_close = (
            history[-2]["close"]
            if len(history) >= 2
            else safe_float(meta.get("previousClose")) or safe_float(meta.get("chartPreviousClose"))
        )
        daily_change_pct = None
        if price and previous_close:
            daily_change_pct = round((float(price) - float(previous_close)) / float(previous_close) * 100, 2)

        snapshot.update(
            {
                "price": price,
                "open": last_history.get("open"),
                "high": last_history.get("high"),
                "low": last_history.get("low"),
                "volume": last_history.get("volume"),
                "as_of": dt.datetime.fromtimestamp(
                    int(meta.get("regularMarketTime") or timestamps[-1]),
                    dt.timezone.utc,
                ).isoformat()
                if (meta.get("regularMarketTime") or timestamps)
                else utc_now().isoformat(),
                "source": "yahoo_chart" if price is not None else snapshot["source"],
                "error": None if price is not None else "Yahoo chart returned no usable price.",
                "previous_close": previous_close,
                "daily_change_pct": daily_change_pct,
                "history": history[-lookback_days:],
            }
        )
        return snapshot
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        snapshot["error"] = str(exc)
        return snapshot


def configured_price_providers(settings: dict[str, Any]) -> list[str]:
    market_settings = settings.get("market_data", {})
    providers = market_settings.get("price_providers")
    if isinstance(providers, list) and providers:
        return [str(provider).strip().lower() for provider in providers if str(provider).strip()]
    provider = str(market_settings.get("price_provider") or "yahoo_chart").strip().lower()
    return [provider]


def fetch_market_snapshot(
    ticker: str,
    settings: dict[str, Any],
    fallback_price: float | None = None,
) -> dict[str, Any]:
    quote: dict[str, Any] | None = None
    provider_errors: list[dict[str, str | None]] = []
    for provider in configured_price_providers(settings):
        if provider == "fmp":
            candidate = fetch_fmp_quote(ticker, settings, fallback_price)
            candidate["history"] = fetch_fmp_price_history(ticker, settings)
        elif provider == "yahoo_chart":
            candidate = fetch_yahoo_chart_snapshot(ticker, settings, fallback_price)
        elif provider == "stooq":
            candidate = fetch_stooq_quote(ticker, settings, fallback_price)
            candidate["history"] = fetch_price_history(ticker, settings)
        else:
            provider_errors.append({"provider": provider, "error": "Unknown price provider."})
            continue
        provider_errors.append({"provider": provider, "error": candidate.get("error")})
        if candidate.get("price") is not None and candidate.get("source") != "portfolio_fallback":
            quote = candidate
            break
        if quote is None:
            quote = candidate

    if quote is None:
        quote = {
            "ticker": ticker.upper(),
            "price": fallback_price,
            "source": "portfolio_fallback" if fallback_price is not None else "unavailable",
            "as_of": utc_now().isoformat(),
            "history": [],
            "error": "No configured price providers were available.",
        }

    history = quote.get("history") or []
    clean_history = [row for row in history if row.get("close") is not None]

    if quote.get("price") is None and clean_history:
        quote["price"] = clean_history[-1]["close"]
        quote["source"] = f"{quote.get('source')}_history"
        quote["as_of"] = clean_history[-1]["date"]

    if len(clean_history) >= 2:
        previous_close = clean_history[-2]["close"]
        quote["previous_close"] = quote.get("previous_close") or previous_close
        if quote.get("price") and previous_close:
            quote["daily_change_pct"] = round((quote["price"] - previous_close) / previous_close * 100, 2)
    else:
        quote["previous_close"] = quote.get("previous_close")
        quote["daily_change_pct"] = quote.get("daily_change_pct")

    quote["history"] = clean_history
    quote["provider_errors"] = provider_errors
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
