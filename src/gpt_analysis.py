from __future__ import annotations

import json
import os
import re
from typing import Any

import requests


IMPORTANT_TAGS = {
    "earnings",
    "guidance",
    "lawsuit",
    "analyst action",
    "product launch",
    "sector move",
    "dilution",
    "insider activity",
}

IMPORTANT_KEYWORDS = (
    "earnings",
    "guidance",
    "upgrade",
    "downgrade",
    "price target",
    "partnership",
    "customer win",
    "contract",
    "lawsuit",
    "probe",
    "investigation",
    "regulatory",
    "sec",
    "ftc",
    "antitrust",
    "ai",
    "datacenter",
    "data center",
    "semiconductor",
    "chip",
    "fpga",
    "automation",
    "unusual volume",
)

ALLOWED_CLASSIFICATIONS = {
    "hold thesis intact",
    "risk elevated",
    "research opportunity",
    "sell watch",
    "short-term noise",
}


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 4) + 1)


def normalize_title(title: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return re.sub(r"\s+", " ", clean)


def calc_cost(input_tokens: int, output_tokens: int, settings: dict[str, Any]) -> float:
    cfg = settings.get("openai", {})
    input_rate = float(cfg.get("estimated_input_cost_per_1m_tokens", 0.05))
    output_rate = float(cfg.get("estimated_output_cost_per_1m_tokens", 0.40))
    return round((input_tokens / 1_000_000 * input_rate) + (output_tokens / 1_000_000 * output_rate), 6)


def event_context_by_ticker(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = report.get("holdings", []) + report.get("watchlist", []) + report.get("discovery_ideas", [])
    return {str(item.get("ticker", "")).upper(): item for item in items if item.get("ticker")}


def relevance_for_news(item: dict[str, Any], security: dict[str, Any], settings: dict[str, Any]) -> tuple[int, list[str]]:
    cfg = settings.get("openai", {})
    price_move_threshold = float(cfg.get("price_move_threshold_pct", 5))
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    haystack = f"{title} {summary}".lower()
    tag = str(item.get("tag") or "other")
    risk_score = float(item.get("risk_score") or 0)
    sentiment = abs(float(item.get("sentiment_score") or 0))
    daily_change = abs(float(security.get("daily_change_pct") or 0))

    score = 0
    reasons: list[str] = []
    if tag in IMPORTANT_TAGS:
        score += 28
        reasons.append(f"tag:{tag}")
    keyword_hits = sorted({keyword for keyword in IMPORTANT_KEYWORDS if keyword in haystack})
    if keyword_hits:
        score += min(30, len(keyword_hits) * 8)
        reasons.append("keywords:" + ",".join(keyword_hits[:4]))
    if risk_score >= 60:
        score += 18
        reasons.append(f"risk:{risk_score:.0f}")
    if sentiment >= 0.35:
        score += 10
        reasons.append(f"sentiment:{sentiment:.2f}")
    if daily_change >= price_move_threshold:
        score += 18
        reasons.append(f"price_move:{daily_change:.2f}%")
    if security.get("watch_priority") == "high":
        score += 8
        reasons.append("high_priority")
    if security.get("action") in {"sell watch", "add watch"}:
        score += 12
        reasons.append(f"signal:{security.get('action')}")

    if item.get("title") == "News fetch unavailable" or item.get("source") == "agent":
        score = 0
        reasons = ["low_quality_fetch_error"]
    return min(100, score), reasons


def fallback_classification(event: dict[str, Any]) -> dict[str, Any]:
    tag = str(event.get("tag") or "other")
    risk = float(event.get("risk_score") or 50)
    ticker = event.get("ticker")
    title = event.get("title") or event.get("event_title") or "Event"

    if tag in {"lawsuit", "dilution"} or risk >= 75:
        classification = "sell watch"
        confidence = 68
        why = "Rules flagged a high-risk event that may threaten the thesis."
    elif tag in {"guidance", "analyst action"} or risk >= 62:
        classification = "risk elevated"
        confidence = 62
        why = "Rules found catalyst or risk language that deserves review."
    elif tag in {"earnings", "product launch", "sector move"}:
        classification = "research opportunity"
        confidence = 58
        why = "Rules found a potentially material catalyst."
    else:
        classification = "short-term noise"
        confidence = 48
        why = "Rules did not find enough evidence that the event changes the long-term thesis."

    return {
        "ticker": ticker,
        "event_title": title,
        "classification": classification,
        "confidence_score": confidence,
        "why_it_matters": why,
        "thesis_change": "Human review required; rules-only fallback cannot fully assess thesis change.",
        "uncertainty_notes": "No GPT call was used, or a limit/API issue caused fallback analysis.",
        "source_url": event.get("url") or "",
        "analysis_source": "rules",
    }


def build_events(report: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = settings.get("openai", {})
    relevance_threshold = int(cfg.get("relevance_threshold", 55))
    max_articles = int(cfg.get("max_articles_per_run", 8))
    price_move_threshold = float(cfg.get("price_move_threshold_pct", 5))
    by_ticker = event_context_by_ticker(report)
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in report.get("news_catalysts", []):
        ticker = str(item.get("ticker", "")).upper()
        security = by_ticker.get(ticker, {})
        title = str(item.get("title") or "")
        key = (item.get("url") or normalize_title(title)).lower()
        if not ticker or not title or key in seen:
            continue
        seen.add(key)
        relevance, reasons = relevance_for_news(item, security, settings)
        if relevance < relevance_threshold:
            continue
        events.append(
            {
                "event_type": "news",
                "ticker": ticker,
                "company": security.get("company"),
                "title": title[:220],
                "summary": str(item.get("summary") or "")[:500],
                "url": item.get("url"),
                "source": item.get("source"),
                "published_at": item.get("published_at"),
                "tag": item.get("tag"),
                "sentiment_score": item.get("sentiment_score"),
                "risk_score": item.get("risk_score"),
                "relevance_score": relevance,
                "relevance_reasons": reasons,
                "security_context": {
                    "sector": security.get("sector"),
                    "time_horizon": security.get("time_horizon"),
                    "thesis": security.get("thesis"),
                    "action": security.get("action"),
                    "action_reasoning": security.get("action_reasoning"),
                    "daily_change_pct": security.get("daily_change_pct"),
                    "overall_score": security.get("scores", {}).get("overall_score"),
                },
            }
        )

    for ticker, security in by_ticker.items():
        daily_change = security.get("daily_change_pct")
        if daily_change is None or abs(float(daily_change)) < price_move_threshold:
            continue
        key = f"price-move:{ticker}:{daily_change}"
        if key in seen:
            continue
        seen.add(key)
        events.append(
            {
                "event_type": "price_move",
                "ticker": ticker,
                "company": security.get("company"),
                "title": f"{ticker} moved {float(daily_change):+.2f}% in the latest session",
                "summary": "Large price movement crossed the configured GPT relevance threshold.",
                "url": "",
                "source": "market_data",
                "published_at": report.get("generated_at"),
                "tag": "price move",
                "sentiment_score": 0,
                "risk_score": 62 if float(daily_change) < 0 else 45,
                "relevance_score": 70,
                "relevance_reasons": [f"price_move:{abs(float(daily_change)):.2f}%"],
                "security_context": {
                    "sector": security.get("sector"),
                    "time_horizon": security.get("time_horizon"),
                    "thesis": security.get("thesis"),
                    "action": security.get("action"),
                    "action_reasoning": security.get("action_reasoning"),
                    "daily_change_pct": daily_change,
                    "overall_score": security.get("scores", {}).get("overall_score"),
                },
            }
        )

    events.sort(key=lambda event: (event.get("relevance_score", 0), event.get("risk_score", 0)), reverse=True)
    return events[:max_articles]


def prompt_for_events(events: list[dict[str, Any]]) -> str:
    compact_events = [
        {
            "ticker": event.get("ticker"),
            "company": event.get("company"),
            "event_type": event.get("event_type"),
            "title": event.get("title"),
            "summary": event.get("summary"),
            "tag": event.get("tag"),
            "risk_score": event.get("risk_score"),
            "sentiment_score": event.get("sentiment_score"),
            "relevance_reasons": event.get("relevance_reasons"),
            "security_context": event.get("security_context"),
            "source_url": event.get("url"),
        }
        for event in events
    ]
    return (
        "You are a cautious stock research assistant. You do not give financial advice or buy-now calls. "
        "Analyze only the events below. Be concise. Return strict JSON with key 'events'. "
        "For each event return ticker, event_title, classification, confidence_score, why_it_matters, "
        "thesis_change, uncertainty_notes, source_url. classification must be one of: "
        "hold thesis intact, risk elevated, research opportunity, sell watch, short-term noise. "
        "confidence_score is 0-100. Keep each text field under 24 words.\n\n"
        + json.dumps({"events": compact_events}, separators=(",", ":"))
    )


def response_format_schema() -> dict[str, Any]:
    event_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "ticker": {"type": "string"},
            "event_title": {"type": "string"},
            "classification": {
                "type": "string",
                "enum": [
                    "hold thesis intact",
                    "risk elevated",
                    "research opportunity",
                    "sell watch",
                    "short-term noise",
                ],
            },
            "confidence_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "why_it_matters": {"type": "string"},
            "thesis_change": {"type": "string"},
            "uncertainty_notes": {"type": "string"},
            "source_url": {"type": "string"},
        },
        "required": [
            "ticker",
            "event_title",
            "classification",
            "confidence_score",
            "why_it_matters",
            "thesis_change",
            "uncertainty_notes",
            "source_url",
        ],
    }
    return {
        "format": {
            "type": "json_schema",
            "name": "stock_event_analysis",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "events": {
                        "type": "array",
                        "items": event_schema,
                    }
                },
                "required": ["events"],
            },
        }
    }


def extract_output_text(payload: dict[str, Any]) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"])
    pieces: list[str] = []
    for output in payload.get("output", []) or []:
        for content in output.get("content", []) or []:
            text = content.get("text")
            if text:
                pieces.append(str(text))
    return "\n".join(pieces)


def parse_gpt_json(text: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(0))
    events = payload.get("events", payload if isinstance(payload, list) else [])
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def normalize_gpt_event(raw: dict[str, Any], source_event: dict[str, Any]) -> dict[str, Any]:
    classification = str(raw.get("classification") or "short-term noise").strip().lower()
    if classification not in ALLOWED_CLASSIFICATIONS:
        classification = "short-term noise"
    try:
        confidence = int(float(raw.get("confidence_score", 50)))
    except (TypeError, ValueError):
        confidence = 50
    confidence = max(0, min(100, confidence))
    return {
        "ticker": raw.get("ticker") or source_event.get("ticker"),
        "event_title": raw.get("event_title") or source_event.get("title"),
        "classification": classification,
        "confidence_score": confidence,
        "why_it_matters": raw.get("why_it_matters") or "",
        "thesis_change": raw.get("thesis_change") or "",
        "uncertainty_notes": raw.get("uncertainty_notes") or "",
        "source_url": raw.get("source_url") or source_event.get("url") or "",
        "analysis_source": "gpt",
        "relevance_score": source_event.get("relevance_score"),
        "relevance_reasons": source_event.get("relevance_reasons", []),
    }


def call_openai(events: list[dict[str, Any]], settings: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cfg = settings.get("openai", {})
    prompt = prompt_for_events(events)
    max_output_tokens = int(cfg.get("max_tokens_per_call", 450))
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    request_payload = {
        "model": cfg.get("model", "gpt-5-nano"),
        "input": prompt,
        "max_output_tokens": max_output_tokens,
        "text": response_format_schema(),
    }
    if str(cfg.get("model", "")).startswith("gpt-5"):
        request_payload["reasoning"] = {"effort": "minimal"}

    response = requests.post(
        str(cfg.get("api_url", "https://api.openai.com/v1/responses")),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=request_payload,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    output_text = extract_output_text(payload)
    usage = payload.get("usage", {}) or {}
    input_tokens = int(usage.get("input_tokens") or estimate_tokens(prompt))
    output_tokens = int(usage.get("output_tokens") or estimate_tokens(output_text))
    batch_usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated": "usage" not in payload,
        "estimated_cost_usd": calc_cost(input_tokens, output_tokens, settings),
    }
    parsed = parse_gpt_json(output_text)
    normalized = [
        normalize_gpt_event(raw, events[index if index < len(events) else -1])
        for index, raw in enumerate(parsed[: len(events)])
    ]
    return normalized, batch_usage


def analyze_events(report: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    cfg = settings.get("openai", {})
    selected_events = build_events(report, settings)
    usage = {
        "model": cfg.get("model", "gpt-5-nano"),
        "gpt_enabled": bool(cfg.get("gpt_enabled", True)),
        "rules_only_mode": bool(cfg.get("rules_only_mode", False)),
        "selected_event_count": len(selected_events),
        "gpt_call_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_usd": 0.0,
        "limit_notes": [],
    }

    if not selected_events:
        usage["limit_notes"].append("No events met GPT relevance thresholds.")
        return {"mode": "none", "events": [], "usage": usage, "selected_events": []}

    api_key_present = bool(os.getenv("OPENAI_API_KEY"))
    if not cfg.get("gpt_enabled", True) or cfg.get("rules_only_mode", False) or not api_key_present:
        if not api_key_present:
            usage["limit_notes"].append("OPENAI_API_KEY missing; used rules-only fallback.")
        else:
            usage["limit_notes"].append("GPT disabled or rules-only mode enabled.")
        return {
            "mode": "rules_only",
            "events": [fallback_classification(event) for event in selected_events],
            "usage": usage,
            "selected_events": selected_events,
        }

    max_calls = int(cfg.get("max_gpt_calls_per_day", 4))
    max_events_per_call = max(1, int(cfg.get("max_events_per_call", 3)))
    max_budget = float(cfg.get("max_daily_gpt_budget_estimate", 0.05))
    analyses: list[dict[str, Any]] = []
    fallback_events: list[dict[str, Any]] = []

    for start in range(0, len(selected_events), max_events_per_call):
        batch = selected_events[start : start + max_events_per_call]
        if usage["gpt_call_count"] >= max_calls:
            usage["limit_notes"].append("Max GPT calls reached; remaining events used rules fallback.")
            fallback_events.extend(batch)
            continue

        prompt = prompt_for_events(batch)
        estimated_input = estimate_tokens(prompt)
        estimated_cost = calc_cost(estimated_input, int(cfg.get("max_tokens_per_call", 450)), settings)
        if usage["estimated_cost_usd"] + estimated_cost > max_budget:
            usage["limit_notes"].append("Max daily GPT budget estimate reached; remaining events used rules fallback.")
            fallback_events.extend(batch)
            continue

        try:
            batch_analyses, batch_usage = call_openai(batch, settings)
            usage["gpt_call_count"] += 1
            usage["input_tokens"] += int(batch_usage["input_tokens"])
            usage["output_tokens"] += int(batch_usage["output_tokens"])
            usage["estimated_cost_usd"] = round(
                usage["estimated_cost_usd"] + float(batch_usage["estimated_cost_usd"]),
                6,
            )
            analyses.extend(batch_analyses)
            if len(batch_analyses) < len(batch):
                fallback_events.extend(batch[len(batch_analyses) :])
        except (requests.RequestException, RuntimeError, json.JSONDecodeError, KeyError, ValueError) as exc:
            usage["limit_notes"].append(f"GPT call failed; used rules fallback: {exc}")
            fallback_events.extend(batch)

    analyses.extend(fallback_classification(event) for event in fallback_events)
    mode = "gpt" if usage["gpt_call_count"] else "rules_only"
    if fallback_events and usage["gpt_call_count"]:
        mode = "gpt_with_rules_fallback"
    return {
        "mode": mode,
        "events": analyses,
        "usage": usage,
        "selected_events": selected_events,
    }
