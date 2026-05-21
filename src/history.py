from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


POSITIVE_SIGNALS = {"add watch", "research opportunity", "hold thesis intact"}
RISK_SIGNALS = {"sell watch", "risk elevated"}


def load_history(path: str | Path, default_key: str) -> dict[str, Any]:
    history_path = Path(path)
    if not history_path.exists():
        return {"last_updated": None, default_key: []}
    try:
        return json.loads(history_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"last_updated": None, default_key: []}


def write_history(path: str | Path, payload: dict[str, Any]) -> None:
    history_path = Path(path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def current_item_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = report.get("holdings", []) + report.get("watchlist", []) + report.get("discovery_ideas", [])
    return {str(item.get("ticker", "")).upper(): item for item in items if item.get("ticker")}


def signal_key(signal: dict[str, Any]) -> str:
    return "|".join(
        [
            str(signal.get("date")),
            str(signal.get("ticker")),
            str(signal.get("signal_type")),
            str(signal.get("source")),
            str(signal.get("run_session")),
            str(signal.get("reason", ""))[:120],
        ]
    )


def signal_accuracy(signal_type: str, return_pct: float) -> bool:
    normalized = signal_type.lower()
    if normalized in POSITIVE_SIGNALS:
        return return_pct >= 0
    if normalized in RISK_SIGNALS:
        return return_pct <= 0
    if normalized == "short-term noise":
        return abs(return_pct) <= 5
    return abs(return_pct) <= 3


def create_rule_signals(report: dict[str, Any]) -> list[dict[str, Any]]:
    generated_date = str(report.get("generated_at", ""))[:10]
    run_session = report.get("run_session", "unknown")
    signals: list[dict[str, Any]] = []
    for item in report.get("holdings", []) + report.get("watchlist", []):
        action = item.get("action")
        if action not in {"sell watch", "add watch", "research only"}:
            continue
        signals.append(
            {
                "date": generated_date,
                "run_session": run_session,
                "ticker": item.get("ticker"),
                "signal_type": action,
                "source": "rules",
                "confidence": item.get("scores", {}).get("overall_score"),
                "reason": item.get("action_reasoning"),
                "price_at_signal": item.get("current_price"),
                "later_outcome": {"status": "pending"},
            }
        )
    return signals


def create_gpt_signals(report: dict[str, Any]) -> list[dict[str, Any]]:
    generated_date = str(report.get("generated_at", ""))[:10]
    run_session = report.get("run_session", "unknown")
    by_ticker = current_item_map(report)
    signals: list[dict[str, Any]] = []
    for event in report.get("gpt_analysis", {}).get("events", []):
        classification = event.get("classification")
        if not classification or classification == "short-term noise":
            continue
        ticker = str(event.get("ticker", "")).upper()
        item = by_ticker.get(ticker, {})
        signals.append(
            {
                "date": generated_date,
                "run_session": run_session,
                "ticker": ticker,
                "signal_type": classification,
                "source": event.get("analysis_source", "gpt"),
                "confidence": event.get("confidence_score"),
                "reason": event.get("why_it_matters"),
                "price_at_signal": item.get("current_price"),
                "event_title": event.get("event_title"),
                "later_outcome": {"status": "pending"},
            }
        )
    return signals


def update_pending_outcomes(
    signals: list[dict[str, Any]],
    report: dict[str, Any],
    evaluation_days: int,
) -> list[dict[str, Any]]:
    today = parse_date(report.get("generated_at")) or dt.datetime.now(dt.timezone.utc).date()
    by_ticker = current_item_map(report)
    for signal in signals:
        outcome = signal.get("later_outcome") or {}
        if outcome.get("status") == "evaluated":
            continue
        signal_date = parse_date(signal.get("date"))
        if not signal_date:
            continue
        days_elapsed = (today - signal_date).days
        if days_elapsed < evaluation_days:
            outcome["status"] = "pending"
            outcome["days_elapsed"] = days_elapsed
            signal["later_outcome"] = outcome
            continue
        ticker = str(signal.get("ticker", "")).upper()
        current_price = by_ticker.get(ticker, {}).get("current_price")
        entry_price = signal.get("price_at_signal")
        if not current_price or not entry_price:
            outcome["status"] = "pending"
            outcome["days_elapsed"] = days_elapsed
            signal["later_outcome"] = outcome
            continue
        return_pct = (float(current_price) - float(entry_price)) / float(entry_price) * 100
        outcome = {
            "status": "evaluated",
            "as_of": today.isoformat(),
            "days_elapsed": days_elapsed,
            "current_price_at_evaluation": round(float(current_price), 2),
            "return_pct": round(return_pct, 2),
            "accurate": signal_accuracy(str(signal.get("signal_type", "")), return_pct),
        }
        signal["later_outcome"] = outcome
    return signals


def compute_accuracy_stats(signals: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for signal in signals:
        signal_type = str(signal.get("signal_type") or "unknown")
        bucket = stats.setdefault(
            signal_type,
            {
                "total": 0,
                "evaluated": 0,
                "pending": 0,
                "accurate": 0,
                "accuracy_pct": None,
                "average_return_pct": None,
            },
        )
        bucket["total"] += 1
        outcome = signal.get("later_outcome") or {}
        if outcome.get("status") == "evaluated":
            bucket["evaluated"] += 1
            if outcome.get("accurate"):
                bucket["accurate"] += 1
            bucket.setdefault("_returns", []).append(float(outcome.get("return_pct") or 0))
        else:
            bucket["pending"] += 1

    for bucket in stats.values():
        returns = bucket.pop("_returns", [])
        if bucket["evaluated"]:
            bucket["accuracy_pct"] = round(bucket["accurate"] / bucket["evaluated"] * 100, 1)
            bucket["average_return_pct"] = round(sum(returns) / len(returns), 2) if returns else None
    return stats


def compute_accuracy_by_run_session(signals: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for signal in signals:
        session = str(signal.get("run_session") or "unknown")
        bucket = stats.setdefault(
            session,
            {"total": 0, "evaluated": 0, "pending": 0, "accurate": 0, "accuracy_pct": None},
        )
        bucket["total"] += 1
        outcome = signal.get("later_outcome") or {}
        if outcome.get("status") == "evaluated":
            bucket["evaluated"] += 1
            if outcome.get("accurate"):
                bucket["accurate"] += 1
        else:
            bucket["pending"] += 1
    for bucket in stats.values():
        if bucket["evaluated"]:
            bucket["accuracy_pct"] = round(bucket["accurate"] / bucket["evaluated"] * 100, 1)
    return stats


def best_and_worst(signals: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evaluated = [
        signal
        for signal in signals
        if (signal.get("later_outcome") or {}).get("status") == "evaluated"
        and (signal.get("later_outcome") or {}).get("return_pct") is not None
    ]
    evaluated.sort(key=lambda signal: float(signal["later_outcome"]["return_pct"]), reverse=True)
    return evaluated[:5], list(reversed(evaluated[-5:])) if evaluated else []


def update_paper_trades(
    paper_payload: dict[str, Any],
    signals: list[dict[str, Any]],
    report: dict[str, Any],
) -> dict[str, Any]:
    trades = paper_payload.setdefault("paper_trades", [])
    existing = {
        "|".join([str(trade.get("opened_at")), str(trade.get("ticker")), str(trade.get("signal_type"))])
        for trade in trades
    }
    today = str(report.get("generated_at", ""))[:10]
    by_ticker = current_item_map(report)

    for signal in signals:
        if signal.get("signal_type") not in POSITIVE_SIGNALS:
            continue
        key = "|".join([str(signal.get("date")), str(signal.get("ticker")), str(signal.get("signal_type"))])
        if key in existing or not signal.get("price_at_signal"):
            continue
        trades.append(
            {
                "opened_at": signal.get("date"),
                "ticker": signal.get("ticker"),
                "signal_type": signal.get("signal_type"),
                "source": signal.get("source"),
                "confidence": signal.get("confidence"),
                "entry_price": signal.get("price_at_signal"),
                "status": "open",
                "notes": "Simulated paper record only. No real trade was executed.",
            }
        )
        existing.add(key)

    for trade in trades:
        ticker = str(trade.get("ticker", "")).upper()
        current_price = by_ticker.get(ticker, {}).get("current_price")
        entry_price = trade.get("entry_price")
        if current_price and entry_price:
            return_pct = (float(current_price) - float(entry_price)) / float(entry_price) * 100
            trade["latest_return_pct"] = round(return_pct, 2)
            trade["last_checked"] = today
    paper_payload["last_updated"] = report.get("generated_at")
    paper_payload["notes"] = "Paper-trade records are simulated learning records only. The agent never executes real trades."
    return paper_payload


def update_signal_history(report: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    history_settings = settings.get("history", {})
    history_path = history_settings.get("signals_history_path", "data/signals_history.json")
    paper_path = history_settings.get("paper_trades_path", "data/paper_trades.json")
    evaluation_days = int(history_settings.get("evaluation_days", 14))

    history = load_history(history_path, "signals")
    signals = history.setdefault("signals", [])
    existing = {signal_key(signal) for signal in signals}

    new_signals = create_rule_signals(report) + create_gpt_signals(report)
    for signal in new_signals:
        if not signal.get("ticker") or signal_key(signal) in existing:
            continue
        signals.append(signal)
        existing.add(signal_key(signal))

    signals = update_pending_outcomes(signals, report, evaluation_days)
    stats = compute_accuracy_stats(signals)
    run_session_stats = compute_accuracy_by_run_session(signals)
    best, worst = best_and_worst(signals)
    history.update(
        {
            "last_updated": report.get("generated_at"),
            "signals": signals,
            "accuracy_stats": stats,
            "accuracy_by_run_session": run_session_stats,
            "best_performing_signals": best,
            "worst_performing_signals": worst,
            "summary": {
                "total_signals": len(signals),
                "new_signals_this_run": len(new_signals),
                "evaluated_signals": sum(1 for signal in signals if (signal.get("later_outcome") or {}).get("status") == "evaluated"),
                "pending_signals": sum(1 for signal in signals if (signal.get("later_outcome") or {}).get("status") != "evaluated"),
            },
        }
    )
    write_history(history_path, history)

    paper_payload = load_history(paper_path, "paper_trades")
    paper_payload = update_paper_trades(paper_payload, signals, report)
    write_history(paper_path, paper_payload)
    return {"signals_history": history, "paper_trades": paper_payload}
