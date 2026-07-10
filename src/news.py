from __future__ import annotations

import datetime as dt
import email.utils
import html
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any

from src.data_sources import fmp_get_json, http_get, utc_now


TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "earnings": ("earnings", "eps", "revenue", "quarter", "results", "profit"),
    "guidance": ("guidance", "outlook", "forecast", "raises forecast", "cuts forecast"),
    "lawsuit": ("lawsuit", "sues", "investigation", "probe", "settlement", "antitrust"),
    "analyst action": ("upgrade", "downgrade", "price target", "analyst", "initiates", "rating"),
    "product launch": ("launch", "unveil", "introduces", "release", "product", "platform"),
    "macro": ("fed", "rates", "inflation", "tariff", "macro", "economy", "recession"),
    "sector move": ("semiconductor", "chip", "ai", "software", "datacenter", "sector", "nasdaq"),
    "dilution": ("offering", "dilution", "convertible", "share sale", "secondary"),
    "insider activity": ("insider", "buys shares", "sells shares", "ceo bought", "director bought"),
}

POSITIVE_KEYWORDS = (
    "beat",
    "beats",
    "raise",
    "raises",
    "upgrade",
    "upgraded",
    "growth",
    "record",
    "strong",
    "wins",
    "expands",
    "partnership",
    "launch",
    "outperform",
    "bullish",
)

NEGATIVE_KEYWORDS = (
    "miss",
    "misses",
    "cut",
    "cuts",
    "downgrade",
    "downgraded",
    "lawsuit",
    "investigation",
    "weak",
    "delay",
    "lowers",
    "plunges",
    "slumps",
    "layoffs",
    "bearish",
    "warning",
    "falls",
)

HIGH_RISK_TAGS = {"lawsuit", "dilution", "guidance"}


def parse_date(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def text_of(element: ET.Element, name: str) -> str:
    found = element.find(name)
    if found is None or found.text is None:
        return ""
    return html.unescape(found.text).strip()


def tag_news(title: str, summary: str = "") -> str:
    haystack = f"{title} {summary}".lower()
    for tag, keywords in TAG_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return tag
    return "other"


def analyze_news_item(title: str, summary: str = "", tag: str | None = None) -> dict[str, Any]:
    haystack = f"{title} {summary}".lower()
    positives = sum(1 for keyword in POSITIVE_KEYWORDS if keyword in haystack)
    negatives = sum(1 for keyword in NEGATIVE_KEYWORDS if keyword in haystack)
    assigned_tag = tag or tag_news(title, summary)

    sentiment = max(-1.0, min(1.0, positives * 0.22 - negatives * 0.28))
    risk = 35 + negatives * 14 - positives * 5
    if assigned_tag in HIGH_RISK_TAGS:
        risk += 14
    if assigned_tag == "earnings":
        risk += 6
    risk = int(max(0, min(100, risk)))

    if sentiment > 0.2:
        reason = "Positive wording or catalyst language detected."
    elif sentiment < -0.2:
        reason = "Negative wording or risk language detected."
    else:
        reason = "Mixed or low-signal headline; human review needed."

    return {
        "tag": assigned_tag,
        "sentiment_score": round(sentiment, 2),
        "risk_score": risk,
        "sentiment_reason": reason,
    }


def parse_rss(text: str, ticker: str, source_name: str, lookback_days: int) -> list[dict[str, Any]]:
    root = ET.fromstring(text)
    items: list[dict[str, Any]] = []
    cutoff = utc_now() - dt.timedelta(days=lookback_days)

    for item in root.findall(".//item"):
        title = text_of(item, "title")
        link = text_of(item, "link")
        summary = text_of(item, "description")
        published = parse_date(text_of(item, "pubDate"))
        source = text_of(item, "source") or source_name
        if not title or not link:
            continue
        if published and published < cutoff:
            continue

        analysis = analyze_news_item(title, summary)
        items.append(
            {
                "ticker": ticker.upper(),
                "title": title,
                "url": link,
                "source": source,
                "published_at": published.isoformat() if published else None,
                "summary": summary,
                **analysis,
            }
        )
    return items


def news_urls(ticker: str, configured_sources: list[str]) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    symbol = ticker.upper()
    if "yahoo" in configured_sources:
        urls.append(
            (
                "Yahoo Finance",
                f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US",
            )
        )
    if "google" in configured_sources:
        query = urllib.parse.quote_plus(f"{symbol} stock earnings analyst catalyst when:7d")
        urls.append(
            (
                "Google News",
                f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
            )
        )
    return urls


def parse_fmp_date(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except ValueError:
        return parse_date(value)


def fetch_fmp_news(ticker: str, settings: dict[str, Any], lookback_days: int, max_items: int) -> list[dict[str, Any]]:
    payload, error, _url = fmp_get_json(
        "news/stock",
        {"symbols": ticker.upper(), "limit": max_items},
        settings,
        "news",
    )
    if error or not payload:
        return []

    cutoff = utc_now() - dt.timedelta(days=lookback_days)
    items: list[dict[str, Any]] = []
    for row in payload if isinstance(payload, list) else []:
        title = str(row.get("title") or "").strip()
        link = str(row.get("url") or "").strip()
        summary = str(row.get("text") or row.get("summary") or "").strip()
        published = parse_fmp_date(row.get("publishedDate") or row.get("published_at") or row.get("date"))
        if not title or not link:
            continue
        if published and published < cutoff:
            continue
        analysis = analyze_news_item(title, summary)
        items.append(
            {
                "ticker": ticker.upper(),
                "title": title,
                "url": link,
                "source": row.get("site") or row.get("publisher") or "Financial Modeling Prep",
                "published_at": published.isoformat() if published else None,
                "summary": summary,
                **analysis,
            }
        )
    return items


def fetch_recent_news(ticker: str, settings: dict[str, Any]) -> list[dict[str, Any]]:
    news_settings = settings.get("news", {})
    max_items = int(news_settings.get("max_items_per_ticker", 5))
    lookback_days = int(news_settings.get("lookback_days", 7))
    configured_sources = [str(source).lower() for source in news_settings.get("sources", ["yahoo", "google"])]

    collected: list[dict[str, Any]] = []
    errors: list[str] = []
    if "fmp" in configured_sources:
        collected.extend(fetch_fmp_news(ticker, settings, lookback_days, max_items))

    for source_name, url in news_urls(ticker, configured_sources):
        text, error = http_get(url, settings, "news")
        if error:
            errors.append(f"{source_name}: {error}")
            continue
        if not text:
            continue
        try:
            collected.extend(parse_rss(text, ticker, source_name, lookback_days))
        except ET.ParseError as exc:
            errors.append(f"{source_name}: XML parse error: {exc}")

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in sorted(collected, key=lambda row: row.get("published_at") or "", reverse=True):
        key = (item.get("url") or item.get("title") or "").lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= max_items:
            break

    if not deduped and errors:
        return [
            {
                "ticker": ticker.upper(),
                "title": "News fetch unavailable",
                "url": "",
                "source": "agent",
                "published_at": utc_now().isoformat(),
                "summary": "; ".join(errors)[:500],
                "tag": "other",
                "sentiment_score": 0,
                "risk_score": 50,
                "sentiment_reason": "No recent news could be fetched; treat signal as uncertain.",
            }
        ]
    return deduped


def summarize_news(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {
            "item_count": 0,
            "top_tags": [],
            "average_sentiment": 0,
            "average_risk": 50,
            "summary": "No recent catalysts found from configured RSS sources.",
        }

    tags = Counter(item.get("tag", "other") for item in items)
    avg_sentiment = sum(float(item.get("sentiment_score") or 0) for item in items) / len(items)
    avg_risk = sum(float(item.get("risk_score") or 50) for item in items) / len(items)
    top_titles = [item.get("title", "") for item in items[:2] if item.get("title")]
    return {
        "item_count": len(items),
        "top_tags": [tag for tag, _ in tags.most_common(3)],
        "average_sentiment": round(avg_sentiment, 2),
        "average_risk": round(avg_risk, 1),
        "summary": " | ".join(top_titles) if top_titles else "Recent news found; review source links.",
    }
