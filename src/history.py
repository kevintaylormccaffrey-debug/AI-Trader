from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any


POSITIVE_SIGNALS = {"add watch", "research opportunity", "hold thesis intact"}
RISK_SIGNALS = {"sell watch", "risk elevated"}
NEUTRAL_SIGNALS = {"research only", "short-term noise", "hold"}


def load_history(path: str | Path, default_key: str) -> dict[str, Any]:
    history_path = Path(path)
    if not history_path.exists():
        return {"last_updated": None, default_key: []}
    try:
        return json.loads(history_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"last_updated": None, default_key: []}


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except ValueError:
        date_value = parse_date(value)
        if date_value:
            return dt.datetime.combine(date_value, dt.time(0, 0), tzinfo=dt.timezone.utc)
    return None


def iso_date_plus(value: str | None, days: int) -> str:
    base = parse_datetime(value) or dt.datetime.now(dt.timezone.utc)
    return (base.date() + dt.timedelta(days=days)).isoformat()


def current_item_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = report.get("holdings", []) + report.get("watchlist", []) + report.get("discovery_ideas", [])
    return {str(item.get("ticker", "")).upper(): item for item in items if item.get("ticker")}


def benchmark_item(report: dict[str, Any]) -> dict[str, Any] | None:
    by_ticker = current_item_map(report)
    for ticker in ("VOO", "SPY", "VTI"):
        if ticker in by_ticker and by_ticker[ticker].get("current_price"):
            return by_ticker[ticker]
    return None


def signal_identity(parts: list[Any]) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def signal_key(signal: dict[str, Any]) -> str:
    return "|".join(
        [
            str(signal.get("date_time") or signal.get("date")),
            str(signal.get("ticker")),
            str(signal.get("signal_type")),
            str(signal.get("recommendation_label")),
            str(signal.get("source")),
            str(signal.get("run_session")),
            str(signal.get("reason", ""))[:160],
        ]
    )


def normalized_label(signal: dict[str, Any]) -> str:
    return str(signal.get("recommendation_label") or signal.get("signal_type") or "unknown").lower()


def success_for_label(label: str, return_pct: float, benchmark_return: float | None = None) -> bool:
    comparison_return = benchmark_return if benchmark_return is not None else 0.0
    if label in POSITIVE_SIGNALS:
        return return_pct >= comparison_return
    if label in RISK_SIGNALS:
        return return_pct <= comparison_return
    if label == "short-term noise":
        return abs(return_pct) <= 5
    if label in {"research only", "hold"}:
        return return_pct >= comparison_return - 5
    return return_pct >= comparison_return


def outcome_label_for(signal: dict[str, Any], return_pct: float, benchmark_return: float | None) -> str:
    label = normalized_label(signal)
    successful = success_for_label(label, return_pct, benchmark_return)
    if successful:
        return "successful"
    if label in POSITIVE_SIGNALS or label in RISK_SIGNALS:
        return "false_positive"
    if label in NEUTRAL_SIGNALS and return_pct <= -5:
        return "false_negative"
    return "unsuccessful"


def make_signal(
    report: dict[str, Any],
    ticker: str,
    signal_type: str,
    recommendation_label: str,
    confidence: Any,
    price_at_signal: Any,
    reason: str,
    thesis_impact: str,
    time_horizon: str,
    source: str,
    review_after_days: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    date_time = report.get("generated_at")
    report_id = report.get("report_id") or signal_identity([date_time, report.get("run_session")])
    benchmark = benchmark_item(report)
    benchmark_ticker = benchmark.get("ticker") if benchmark else None
    benchmark_price = benchmark.get("current_price") if benchmark else None
    payload: dict[str, Any] = {
        "signal_id": signal_identity([report_id, ticker, signal_type, recommendation_label, source, reason]),
        "date_time": date_time,
        "date": str(date_time or "")[:10],
        "run_session": report.get("run_session", "unknown"),
        "ticker": ticker,
        "signal_type": signal_type,
        "recommendation_label": recommendation_label,
        "confidence": confidence,
        "price_at_signal": price_at_signal,
        "benchmark_ticker": benchmark_ticker,
        "benchmark_price_at_signal": benchmark_price,
        "reason": reason,
        "thesis_impact": thesis_impact,
        "time_horizon": time_horizon,
        "review_after_days": review_after_days,
        "review_date": iso_date_plus(date_time, review_after_days),
        "source_report_id": report_id,
        "source": source,
        "status": "open",
    }
    if extra:
        payload.update(extra)
    return payload


def migrate_signal(signal: dict[str, Any], review_after_days: int) -> dict[str, Any]:
    migrated = dict(signal)
    date_time = migrated.get("date_time") or migrated.get("date")
    if date_time and len(str(date_time)) <= 10:
        date_time = f"{date_time}T00:00:00+00:00"
    migrated.setdefault("date_time", date_time)
    migrated.setdefault("date", str(date_time or "")[:10])
    migrated.setdefault("recommendation_label", migrated.get("signal_type", "unknown"))
    migrated.setdefault("signal_type", migrated.get("recommendation_label", "unknown"))
    migrated.setdefault("thesis_impact", migrated.get("reason", "Legacy signal; thesis impact not captured."))
    migrated.setdefault("time_horizon", "unknown")
    migrated.setdefault("review_after_days", review_after_days)
    migrated.setdefault("review_date", iso_date_plus(migrated.get("date_time"), int(migrated["review_after_days"])))
    migrated.setdefault("source_report_id", f"legacy-{migrated.get('date')}")
    migrated.setdefault("source", migrated.get("source", "legacy"))
    migrated.setdefault("run_session", migrated.get("run_session", "unknown"))
    migrated.setdefault(
        "signal_id",
        signal_identity(
            [
                migrated.get("source_report_id"),
                migrated.get("date_time"),
                migrated.get("ticker"),
                migrated.get("signal_type"),
                migrated.get("source"),
                migrated.get("reason"),
            ]
        ),
    )
    outcome = migrated.get("later_outcome") or {}
    if outcome.get("status") == "evaluated":
        migrated.setdefault("status", "reviewed")
        migrated.setdefault("reviewed_at", outcome.get("as_of"))
        migrated.setdefault("current_price", outcome.get("current_price_at_evaluation"))
        migrated.setdefault("return_since_signal_pct", outcome.get("return_pct"))
        migrated.setdefault("successful", outcome.get("accurate"))
        migrated.setdefault("outcome_label", "successful" if outcome.get("accurate") else "unsuccessful")
        migrated.setdefault("outcome_notes", "Migrated from legacy later_outcome record.")
        migrated.setdefault("days_held", outcome.get("days_elapsed"))
    else:
        migrated.setdefault("status", "open")
    return migrated


def create_rule_signals(report: dict[str, Any], review_after_days: int) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for item in report.get("holdings", []) + report.get("watchlist", []):
        action = item.get("action")
        if action not in {"sell watch", "add watch", "research only"}:
            continue
        ticker = str(item.get("ticker", "")).upper()
        signals.append(
            make_signal(
                report=report,
                ticker=ticker,
                signal_type=action,
                recommendation_label=action,
                confidence=item.get("scores", {}).get("overall_score"),
                price_at_signal=item.get("current_price"),
                reason=item.get("action_reasoning") or "",
                thesis_impact=item.get("action_reasoning") or "Rules signal generated from score and risk thresholds.",
                time_horizon=item.get("time_horizon") or "research",
                source="rules",
                review_after_days=review_after_days,
                extra={"company": item.get("company"), "sector": item.get("sector")},
            )
        )
    return signals


def create_gpt_signals(report: dict[str, Any], review_after_days: int) -> list[dict[str, Any]]:
    by_ticker = current_item_map(report)
    signals: list[dict[str, Any]] = []
    for event in report.get("gpt_analysis", {}).get("events", []):
        classification = event.get("classification")
        if not classification or classification == "short-term noise":
            continue
        ticker = str(event.get("ticker", "")).upper()
        item = by_ticker.get(ticker, {})
        signals.append(
            make_signal(
                report=report,
                ticker=ticker,
                signal_type=classification,
                recommendation_label=classification,
                confidence=event.get("confidence_score"),
                price_at_signal=item.get("current_price"),
                reason=event.get("why_it_matters") or "",
                thesis_impact=event.get("thesis_change") or "",
                time_horizon=item.get("time_horizon") or "research",
                source=event.get("analysis_source", "gpt"),
                review_after_days=review_after_days,
                extra={
                    "company": item.get("company"),
                    "sector": item.get("sector"),
                    "event_title": event.get("event_title"),
                    "source_url": event.get("source_url"),
                    "uncertainty_notes": event.get("uncertainty_notes"),
                },
            )
        )
    return signals


def review_open_signals(
    signals: list[dict[str, Any]],
    report: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    today = parse_date(report.get("generated_at")) or dt.datetime.now(dt.timezone.utc).date()
    by_ticker = current_item_map(report)
    benchmark = benchmark_item(report)
    benchmark_current_price = benchmark.get("current_price") if benchmark else None
    reviewed_today: list[dict[str, Any]] = []

    for signal in signals:
        if signal.get("status") != "open":
            continue
        review_date = parse_date(signal.get("review_date"))
        if not review_date or review_date > today:
            continue

        ticker = str(signal.get("ticker", "")).upper()
        current_price = by_ticker.get(ticker, {}).get("current_price")
        entry_price = signal.get("price_at_signal")
        signal_date = parse_date(signal.get("date_time") or signal.get("date"))
        days_held = (today - signal_date).days if signal_date else None
        if not current_price or not entry_price:
            signal["outcome_notes"] = "Review date arrived, but current or entry price was unavailable."
            signal["days_held"] = days_held
            continue

        return_pct = (float(current_price) - float(entry_price)) / float(entry_price) * 100
        benchmark_return = None
        if signal.get("benchmark_price_at_signal") and benchmark_current_price:
            benchmark_return = (
                (float(benchmark_current_price) - float(signal["benchmark_price_at_signal"]))
                / float(signal["benchmark_price_at_signal"])
                * 100
            )
        outcome_label = outcome_label_for(signal, return_pct, benchmark_return)
        successful = outcome_label == "successful"
        comparison = "benchmark" if benchmark_return is not None else "zero-return baseline"
        signal.update(
            {
                "status": "reviewed",
                "reviewed_at": report.get("generated_at"),
                "current_price": round(float(current_price), 2),
                "return_since_signal_pct": round(return_pct, 2),
                "benchmark_return_pct": round(benchmark_return, 2) if benchmark_return is not None else None,
                "successful": successful,
                "outcome_label": outcome_label,
                "outcome_notes": f"Reviewed against {comparison}; observe-only mode, no strategy auto-change.",
                "days_held": days_held,
                "later_outcome": {
                    "status": "evaluated",
                    "as_of": today.isoformat(),
                    "days_elapsed": days_held,
                    "current_price_at_evaluation": round(float(current_price), 2),
                    "return_pct": round(return_pct, 2),
                    "benchmark_return_pct": round(benchmark_return, 2) if benchmark_return is not None else None,
                    "accurate": successful,
                },
            }
        )
        reviewed_today.append(signal)
    return signals, reviewed_today


def summarize_bucket(items: list[dict[str, Any]]) -> dict[str, Any]:
    reviewed = [item for item in items if item.get("status") == "reviewed"]
    open_items = [item for item in items if item.get("status") == "open"]
    accurate = [item for item in reviewed if item.get("successful")]
    returns = [float(item.get("return_since_signal_pct")) for item in reviewed if item.get("return_since_signal_pct") is not None]
    return {
        "total": len(items),
        "open": len(open_items),
        "reviewed": len(reviewed),
        "successful": len(accurate),
        "accuracy_pct": round(len(accurate) / len(reviewed) * 100, 1) if reviewed else None,
        "average_return_after_signal_pct": round(sum(returns) / len(returns), 2) if returns else None,
    }


def group_stats(signals: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for signal in signals:
        grouped.setdefault(str(signal.get(key) or "unknown"), []).append(signal)
    return {group_key: summarize_bucket(items) for group_key, items in sorted(grouped.items())}


def best_and_worst(signals: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reviewed = [
        signal
        for signal in signals
        if signal.get("status") == "reviewed" and signal.get("return_since_signal_pct") is not None
    ]
    reviewed.sort(key=lambda signal: float(signal["return_since_signal_pct"]), reverse=True)
    return reviewed[:5], list(reversed(reviewed[-5:])) if reviewed else []


def false_positive_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        signal
        for signal in signals
        if signal.get("status") == "reviewed"
        and signal.get("outcome_label") == "false_positive"
    ][:10]


def false_negative_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        signal
        for signal in signals
        if signal.get("status") == "reviewed"
        and signal.get("outcome_label") == "false_negative"
    ][:10]


def compute_signal_accuracy(signals: list[dict[str, Any]], reviewed_today: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    best, worst = best_and_worst(signals)
    return {
        "last_updated": dt.datetime.now(dt.timezone.utc).isoformat(),
        "learning_mode": settings.get("history", {}).get("learning_mode", "observe_only"),
        "overall": summarize_bucket(signals),
        "accuracy_by_ticker": group_stats(signals, "ticker"),
        "accuracy_by_signal_type": group_stats(signals, "signal_type"),
        "accuracy_by_recommendation_label": group_stats(signals, "recommendation_label"),
        "accuracy_by_run_session": group_stats(signals, "run_session"),
        "average_return_after_signal_pct": summarize_bucket(signals).get("average_return_after_signal_pct"),
        "best_signals": best,
        "worst_signals": worst,
        "false_positives": false_positive_signals(signals),
        "false_negatives": false_negative_signals(signals),
        "reviewed_today": reviewed_today,
        "open_signals": [signal for signal in signals if signal.get("status") == "open"][:20],
        "reviewed_signals": [signal for signal in signals if signal.get("status") == "reviewed"][-20:],
        "scoring_insight": scoring_insight(reviewed_today),
    }


def scoring_insight(reviewed_today: list[dict[str, Any]]) -> str:
    if not reviewed_today:
        return "No signals reached review date today; continue collecting observations."
    wins = sum(1 for signal in reviewed_today if signal.get("successful"))
    total = len(reviewed_today)
    if wins == total:
        return "All reviewed signals were directionally useful; observe for more samples before changing strategy."
    if wins == 0:
        return "Reviewed signals missed today; review reasons manually before changing weights."
    return f"{wins}/{total} reviewed signals were directionally useful; mixed result, keep observing."


def legacy_accuracy_stats(signals: list[dict[str, Any]], key: str) -> dict[str, Any]:
    stats = group_stats(signals, key)
    return {
        name: {
            "total": bucket["total"],
            "evaluated": bucket["reviewed"],
            "pending": bucket["open"],
            "accurate": bucket["successful"],
            "accuracy_pct": bucket["accuracy_pct"],
            "average_return_pct": bucket["average_return_after_signal_pct"],
        }
        for name, bucket in stats.items()
    }


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
        if normalized_label(signal) not in POSITIVE_SIGNALS:
            continue
        key = "|".join([str(signal.get("date")), str(signal.get("ticker")), str(signal.get("signal_type"))])
        if key in existing or not signal.get("price_at_signal"):
            continue
        trades.append(
            {
                "opened_at": signal.get("date"),
                "signal_id": signal.get("signal_id"),
                "ticker": signal.get("ticker"),
                "signal_type": signal.get("signal_type"),
                "recommendation_label": signal.get("recommendation_label"),
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
    accuracy_path = history_settings.get("signal_accuracy_path", "output/signal_accuracy.json")
    review_after_days = int(history_settings.get("review_after_days", history_settings.get("evaluation_days", 14)))

    history = load_history(history_path, "signals")
    raw_signals = history.setdefault("signals", [])
    signals = [migrate_signal(signal, review_after_days) for signal in raw_signals]
    existing = {signal.get("signal_id") for signal in signals}

    new_signals = create_rule_signals(report, review_after_days) + create_gpt_signals(report, review_after_days)
    added_signals: list[dict[str, Any]] = []
    for signal in new_signals:
        if not signal.get("ticker") or signal.get("signal_id") in existing:
            continue
        signals.append(signal)
        added_signals.append(signal)
        existing.add(signal.get("signal_id"))

    signals, reviewed_today = review_open_signals(signals, report)
    signal_accuracy = compute_signal_accuracy(signals, reviewed_today, settings)
    best, worst = best_and_worst(signals)
    history.update(
        {
            "last_updated": report.get("generated_at"),
            "learning_mode": history_settings.get("learning_mode", "observe_only"),
            "signals": signals,
            "accuracy_stats": legacy_accuracy_stats(signals, "signal_type"),
            "accuracy_by_run_session": legacy_accuracy_stats(signals, "run_session"),
            "best_performing_signals": best,
            "worst_performing_signals": worst,
            "reviewed_today": reviewed_today,
            "summary": {
                "total_signals": len(signals),
                "new_signals_this_run": len(added_signals),
                "reviewed_today": len(reviewed_today),
                "reviewed_signals": sum(1 for signal in signals if signal.get("status") == "reviewed"),
                "open_signals": sum(1 for signal in signals if signal.get("status") == "open"),
            },
        }
    )
    write_json(history_path, history)
    write_json(accuracy_path, signal_accuracy)

    paper_payload = load_history(paper_path, "paper_trades")
    paper_payload = update_paper_trades(paper_payload, signals, report)
    write_json(paper_path, paper_payload)
    return {"signals_history": history, "paper_trades": paper_payload, "signal_accuracy": signal_accuracy}
