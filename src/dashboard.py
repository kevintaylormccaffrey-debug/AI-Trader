from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, str):
        return esc(value)
    return f"${value:,.2f}"


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%"


def score_class(score: float | None) -> str:
    if score is None:
        return "neutral"
    if score >= 65:
        return "good"
    if score <= 45:
        return "bad"
    return "neutral"


def score_pill(label: str, item: dict[str, Any]) -> str:
    score = item.get("score")
    reason = esc(item.get("reason", ""))
    return (
        f"<span class='score {score_class(score)}' title='{reason}'>"
        f"{esc(label)} {esc(score)}</span>"
    )


def render_score_grid(scores: dict[str, Any]) -> str:
    components = scores.get("components", {})
    labels = {
        "price_momentum": "Momentum",
        "news_sentiment": "News",
        "downside_from_cost_basis": "Downside",
        "earnings_proximity": "Earnings",
        "sector_trend": "Sector",
        "thesis_risk": "Thesis",
        "valuation_caution": "Valuation",
    }
    pills = [score_pill(label, components.get(key, {"score": "n/a"})) for key, label in labels.items()]
    return "<div class='score-grid'>" + "".join(pills) + "</div>"


def overall_score(item: dict[str, Any]) -> float:
    try:
        return float(item.get("scores", {}).get("overall_score", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def component_value(item: dict[str, Any], key: str) -> float:
    try:
        return float(item.get("scores", {}).get("components", {}).get(key, {}).get("score", 50) or 50)
    except (TypeError, ValueError):
        return 50.0


def component_details(item: dict[str, Any], key: str) -> dict[str, Any]:
    details = item.get("scores", {}).get("components", {}).get(key, {}).get("details", {})
    return details if isinstance(details, dict) else {}


def signed_pct(value: Any) -> str:
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def compact_reason(value: Any, limit: int = 170) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return esc(text)
    return esc(text[: limit - 3].rstrip() + "...")


def driver_items(item: dict[str, Any]) -> list[str]:
    drivers: list[str] = []
    momentum = component_value(item, "price_momentum")
    momentum_details = component_details(item, "price_momentum")
    if momentum >= 58:
        drivers.append(
            "Momentum is supportive"
            f" ({signed_pct(momentum_details.get('change_5d_pct'))} 5d,"
            f" {signed_pct(momentum_details.get('change_20d_pct'))} 20d)."
        )
    elif momentum <= 45:
        drivers.append("Momentum is weak or mixed; avoid treating this as a clean add signal.")

    thesis = component_value(item, "thesis_risk")
    if thesis >= 60:
        drivers.append("Thesis-risk score is healthy enough for additional research.")
    elif thesis <= 45:
        drivers.append("Thesis-risk score is elevated; review what could break the original thesis.")

    news = component_value(item, "news_sentiment")
    if news >= 54:
        drivers.append("Recent news/catalyst tone is neutral-to-constructive.")
    elif news <= 40:
        drivers.append("Recent news sentiment is a concern.")

    downside = component_value(item, "downside_from_cost_basis")
    downside_details = component_details(item, "downside_from_cost_basis")
    pnl = downside_details.get("pnl_pct_from_cost")
    if pnl is not None and downside >= 60:
        drivers.append(f"Position is above cost basis ({signed_pct(pnl)}), so downside-from-cost is not currently flashing red.")
    elif pnl is not None and downside <= 45:
        drivers.append(f"Position is below cost basis ({signed_pct(pnl)}); check max-loss rules before adding.")

    sector = component_value(item, "sector_trend")
    if sector >= 55:
        drivers.append("Sector/proxy trend is supportive.")
    elif sector <= 45:
        drivers.append("Sector/proxy trend is not helping the signal.")

    valuation = component_value(item, "valuation_caution")
    if valuation <= 50:
        drivers.append("Valuation or position sizing still needs review before any action.")

    return drivers[:5]


def render_driver_list(item: dict[str, Any]) -> str:
    drivers = driver_items(item)
    if not drivers:
        return ""
    return "<div class='driver-list'><strong>Why this appeared</strong><ul>" + "".join(f"<li>{esc(driver)}</li>" for driver in drivers) + "</ul></div>"


def action_card(item: dict[str, Any], label: str, note: str) -> str:
    score = item.get("scores", {}).get("overall_score")
    return (
        "<article class='radar-card'>"
        f"<h3>{esc(item.get('ticker'))} <span>{esc(label)}</span></h3>"
        f"<p>{compact_reason(item.get('action_reasoning') or item.get('why_it_matches') or item.get('risk'))}</p>"
        f"<p><strong>Score:</strong> {esc(score)} | <strong>Momentum:</strong> {esc(component_value(item, 'price_momentum'))} | <strong>Thesis:</strong> {esc(component_value(item, 'thesis_risk'))}</p>"
        f"{render_driver_list(item)}"
        f"<p class='small-note'>{esc(note)}</p>"
        "</article>"
    )


def render_action_radar(report: dict[str, Any]) -> str:
    holdings = report.get("holdings", [])
    sell_watch = report.get("sell_watch", [])
    add_watch = [item for item in holdings if item.get("action") == "add watch"]
    if not add_watch:
        add_watch = [
            item
            for item in holdings
            if item.get("status") != "core_holding"
            and overall_score(item) >= 58
            and component_value(item, "price_momentum") >= 58
            and component_value(item, "thesis_risk") >= 55
        ]
    add_watch = sorted(add_watch, key=overall_score, reverse=True)[:4]
    other_checks = [
        item
        for item in holdings
        if item.get("watch_priority") == "high" and item.get("action") not in {"hold", "add watch", "sell watch"}
    ][:4]
    ideas = report.get("discovery_ideas", [])[:4]

    def bucket(title: str, items_html: str, empty: str) -> str:
        return (
            "<div class='radar-bucket'>"
            f"<h3>{esc(title)}</h3>"
            + (items_html if items_html else f"<p class='small-note'>{esc(empty)}</p>")
            + "</div>"
        )

    add_html = "".join(
        action_card(
            item,
            "add watch" if item.get("action") == "add watch" else "review for add",
            "Prompt to research adding exposure. Not a buy instruction.",
        )
        for item in add_watch
    )
    sell_html = "".join(
        action_card(item, "review sell thesis", "Risk prompt. Check thesis, sizing, and stop/loss rules before acting.")
        for item in sell_watch[:4]
    )
    checks_html = "".join(
        action_card(item, item.get("action", "thesis check"), "Review why the model did not classify this as a clean hold.")
        for item in other_checks
    )
    ideas_html = "".join(
        action_card(item, "new research candidate", "Not owned unless you add it manually. Research before any trade.")
        for item in ideas
    )
    return (
        "<div class='radar-grid'>"
        + bucket("Look Into Adding / Buying More", add_html, "No owned positions cleared the add-watch filter today.")
        + bucket("Risk / Sell-Watch Review", sell_html, "No sell-watch rules triggered today.")
        + bucket("Other Thesis Checks", checks_html, "No elevated thesis checks outside sell-watch.")
        + bucket("New Stocks To Research", ideas_html, "No discovery ideas passed the current filters.")
        + "</div>"
    )


def render_holdings(holdings: list[dict[str, Any]]) -> str:
    rows = []
    for item in holdings:
        value_display = money(item.get("current_value")) if item.get("current_value") is not None else esc(item.get("portfolio_weight_pct", "n/a")) + "% weight"
        price_context = esc(item.get("price_band", ""))
        pnl_display = money(item.get("unrealized_gain_loss")) if item.get("unrealized_gain_loss") is not None else "redacted"
        rows.append(
            "<tr>"
            f"<td><strong>{esc(item['ticker'])}</strong><span>{esc(item.get('company'))}</span></td>"
            f"<td>{value_display}<span>{price_context}</span></td>"
            f"<td>{pnl_display}<span>{pct(item.get('unrealized_gain_loss_pct'))}</span></td>"
            f"<td><span class='action'>{esc(item.get('action'))}</span><span>{esc(item.get('action_reasoning'))}</span></td>"
            f"<td>{render_score_grid(item.get('scores', {}))}</td>"
            "</tr>"
        )
    return "<div class='table-wrap'><table><thead><tr><th>Holding</th><th>Value</th><th>P/L</th><th>Signal</th><th>Scores</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"


def render_news(news_items: list[dict[str, Any]]) -> str:
    if not news_items:
        return "<p>No recent catalyst items were found.</p>"
    rows = []
    for item in news_items[:40]:
        url = item.get("url")
        title = esc(item.get("title", "Untitled"))
        title_html = f"<a href='{esc(url)}' target='_blank' rel='noopener'>{title}</a>" if url else title
        rows.append(
            "<tr>"
            f"<td><strong>{esc(item.get('ticker'))}</strong></td>"
            f"<td>{title_html}<span>{esc(item.get('source'))}</span></td>"
            f"<td>{esc(item.get('tag'))}</td>"
            f"<td>{esc(item.get('sentiment_score'))}</td>"
            f"<td>{esc(item.get('risk_score'))}</td>"
            "</tr>"
        )
    return (
        "<details class='news-details'><summary>Show recent headline/catalyst table</summary>"
        "<p class='small-note'>Raw headline feed used by the scoring model. GPT summaries and action radar above are the condensed view.</p>"
        "<div class='table-wrap'><table><thead><tr><th>Ticker</th><th>Headline</th><th>Tag</th><th>Sentiment</th><th>Risk</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div></details>"
    )


def render_gpt_analysis(gpt_analysis: dict[str, Any]) -> str:
    events = gpt_analysis.get("events", [])
    usage = gpt_analysis.get("usage", {})
    if not events:
        return (
            "<p>No events met the configured GPT relevance threshold.</p>"
            f"<p class='small-note'>Mode: {esc(gpt_analysis.get('mode', 'none'))}</p>"
        )
    cards = []
    for event in events[:8]:
        cards.append(
            "<article class='item-card'>"
            f"<h3>{esc(event.get('ticker'))} <span>{esc(event.get('classification'))} | confidence {esc(event.get('confidence_score'))}</span></h3>"
            f"<p><strong>Event:</strong> {esc(event.get('event_title'))}</p>"
            f"<p><strong>Why it matters:</strong> {esc(event.get('why_it_matters'))}</p>"
            f"<p><strong>Thesis:</strong> {esc(event.get('thesis_change'))}</p>"
            f"<p><strong>Uncertainty:</strong> {esc(event.get('uncertainty_notes'))}</p>"
            f"<p><strong>Source:</strong> {esc(event.get('analysis_source'))}</p>"
            "</article>"
        )
    notes = "; ".join(str(note) for note in usage.get("limit_notes", []))
    return (
        "<div class='cards'>" + "".join(cards) + "</div>"
        "<div class='usage-line'>"
        f"Mode: {esc(gpt_analysis.get('mode'))} | Model: {esc(usage.get('model'))} | "
        f"Calls: {esc(usage.get('gpt_call_count'))} | Est. cost: ${esc(usage.get('estimated_cost_usd'))} | "
        f"Tokens: {esc(usage.get('input_tokens'))} in / {esc(usage.get('output_tokens'))} out"
        f"{' | Notes: ' + esc(notes) if notes else ''}"
        "</div>"
    )


def render_watchlist(items: list[dict[str, Any]]) -> str:
    if not items:
        return "<p>No watchlist items configured.</p>"
    cards = []
    for item in items:
        cards.append(
            "<article class='item-card'>"
            f"<h3>{esc(item.get('ticker'))} <span>{esc(item.get('company'))}</span></h3>"
            f"<p>{esc(item.get('thesis'))}</p>"
            f"<p><strong>Price:</strong> {esc(item.get('price_band')) if item.get('price_band') else money(item.get('current_price'))} | <strong>Signal:</strong> {esc(item.get('action'))}</p>"
            f"{render_score_grid(item.get('scores', {}))}"
            "</article>"
        )
    return "<div class='cards'>" + "".join(cards) + "</div>"


def render_discovery(items: list[dict[str, Any]]) -> str:
    if not items:
        return "<p>No discovery ideas passed the current filters.</p>"
    cards = []
    for item in items:
        cards.append(
            "<article class='item-card'>"
            f"<h3>{esc(item.get('ticker'))} <span>{esc(item.get('company'))}</span></h3>"
            f"<p><strong>Sector:</strong> {esc(item.get('sector'))}</p>"
            f"<p><strong>Why it matches:</strong> {esc(item.get('why_it_matches'))}</p>"
            f"<p><strong>Catalyst:</strong> {esc(item.get('catalyst'))}</p>"
            f"<p><strong>Risk:</strong> {esc(item.get('risk'))}</p>"
            f"<p><strong>Valuation:</strong> {esc(item.get('valuation_warning'))}</p>"
            f"<p><strong>Confidence:</strong> {esc(item.get('confidence_level'))} | <strong>Score:</strong> {esc(item.get('scores', {}).get('overall_score'))}</p>"
            f"{render_score_grid(item.get('scores', {}))}"
            "</article>"
        )
    return "<div class='cards'>" + "".join(cards) + "</div>"


def render_signal_accuracy(signal_history: dict[str, Any]) -> str:
    stats = signal_history.get("accuracy_stats", {})
    summary = signal_history.get("summary", {})
    session_stats = signal_history.get("accuracy_by_run_session", {})
    if not stats:
        return (
            "<p>Signal accuracy tracking has started. Enough time must pass before outcomes can be evaluated.</p>"
            f"<p class='small-note'>Signals tracked: {esc(summary.get('total_signals', 0))}; pending: {esc(summary.get('pending_signals', 0))}</p>"
        )
    rows = []
    for signal_type, bucket in sorted(stats.items()):
        rows.append(
            "<tr>"
            f"<td>{esc(signal_type)}</td>"
            f"<td>{esc(bucket.get('total'))}</td>"
            f"<td>{esc(bucket.get('evaluated'))}</td>"
            f"<td>{esc(bucket.get('pending'))}</td>"
            f"<td>{esc(bucket.get('accuracy_pct'))}%</td>"
            f"<td>{pct(bucket.get('average_return_pct'))}</td>"
            "</tr>"
        )
    session_rows = []
    for session, bucket in sorted(session_stats.items()):
        session_rows.append(
            "<tr>"
            f"<td>{esc(session)}</td>"
            f"<td>{esc(bucket.get('total'))}</td>"
            f"<td>{esc(bucket.get('evaluated'))}</td>"
            f"<td>{esc(bucket.get('pending'))}</td>"
            f"<td>{esc(bucket.get('accuracy_pct'))}%</td>"
            "</tr>"
        )
    session_table = (
        "<h3>By Run Timing</h3><div class='table-wrap'><table><thead><tr><th>Run</th><th>Total</th><th>Evaluated</th><th>Pending</th><th>Accuracy</th></tr></thead><tbody>"
        + "".join(session_rows)
        + "</tbody></table></div>"
        if session_rows
        else ""
    )
    return (
        "<div class='table-wrap'><table><thead><tr><th>Signal Type</th><th>Total</th><th>Evaluated</th><th>Pending</th><th>Accuracy</th><th>Avg Return</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
        + session_table
    )


def render_learning_accuracy(signal_history: dict[str, Any], signal_accuracy: dict[str, Any]) -> str:
    accuracy = signal_accuracy or {}
    overall = accuracy.get("overall", {})
    reviewed_today = accuracy.get("reviewed_today", [])
    open_signals = accuracy.get("open_signals", [])
    reviewed_signals = accuracy.get("reviewed_signals", [])
    by_type = accuracy.get("accuracy_by_signal_type", {})

    metrics = (
        "<div class='summary-grid'>"
        f"<div class='metric'><strong>{esc(overall.get('open', 0))}</strong><span>Open signals</span></div>"
        f"<div class='metric'><strong>{esc(overall.get('reviewed', 0))}</strong><span>Reviewed signals</span></div>"
        f"<div class='metric'><strong>{esc(overall.get('accuracy_pct'))}%</strong><span>Overall accuracy</span></div>"
        f"<div class='metric'><strong>{pct(overall.get('average_return_after_signal_pct'))}</strong><span>Avg post-signal return</span></div>"
        "</div>"
    )

    def compact_signal_rows(items: list[dict[str, Any]], include_outcome: bool = False) -> str:
        if not items:
            return "<p>No signals in this bucket yet.</p>"
        rows = []
        for item in items[:10]:
            outcome = item.get("outcome_label") or item.get("status")
            result = pct(item.get("return_since_signal_pct")) if include_outcome else esc(item.get("review_date"))
            rows.append(
                "<tr>"
                f"<td>{esc(item.get('ticker'))}</td>"
                f"<td>{esc(item.get('recommendation_label') or item.get('signal_type'))}</td>"
                f"<td>{esc(item.get('confidence'))}</td>"
                f"<td>{result}</td>"
                f"<td>{esc(outcome)}</td>"
                "</tr>"
            )
        return (
            "<div class='table-wrap'><table><thead><tr><th>Ticker</th><th>Signal</th><th>Confidence</th><th>"
            + ("Return" if include_outcome else "Review Date")
            + "</th><th>Status</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
        )

    type_rows = []
    for signal_type, bucket in sorted(by_type.items()):
        type_rows.append(
            "<tr>"
            f"<td>{esc(signal_type)}</td>"
            f"<td>{esc(bucket.get('total'))}</td>"
            f"<td>{esc(bucket.get('reviewed'))}</td>"
            f"<td>{esc(bucket.get('open'))}</td>"
            f"<td>{esc(bucket.get('accuracy_pct'))}%</td>"
            f"<td>{pct(bucket.get('average_return_after_signal_pct'))}</td>"
            "</tr>"
        )
    by_type_table = (
        "<div class='table-wrap'><table><thead><tr><th>Signal Type</th><th>Total</th><th>Reviewed</th><th>Open</th><th>Accuracy</th><th>Avg Return</th></tr></thead><tbody>"
        + "".join(type_rows)
        + "</tbody></table></div>"
        if type_rows
        else "<p>Accuracy by signal type will appear after signals are reviewed.</p>"
    )

    return (
        metrics
        + f"<p class='small-note'>Learning mode: {esc(accuracy.get('learning_mode', signal_history.get('learning_mode', 'observe_only')))}. {esc(accuracy.get('scoring_insight', 'Collecting signal outcomes.'))}</p>"
        + "<h3>Reviewed Today</h3>"
        + compact_signal_rows(reviewed_today, include_outcome=True)
        + "<h3>Open Signals</h3>"
        + compact_signal_rows(open_signals)
        + "<h3>Recently Reviewed Signals</h3>"
        + compact_signal_rows(list(reversed(reviewed_signals)), include_outcome=True)
        + "<h3>Accuracy By Signal Type</h3>"
        + by_type_table
    )


def render_historical_performance(signal_history: dict[str, Any], paper_trades: dict[str, Any]) -> str:
    best = signal_history.get("best_performing_signals", [])
    worst = signal_history.get("worst_performing_signals", [])
    trades = paper_trades.get("paper_trades", [])

    def signal_list(items: list[dict[str, Any]]) -> str:
        if not items:
            return "<p>Not enough evaluated signals yet.</p>"
        rows = []
        for item in items[:5]:
            outcome = item.get("later_outcome", {})
            rows.append(
                "<tr>"
                f"<td>{esc(item.get('ticker'))}</td>"
                f"<td>{esc(item.get('signal_type'))}</td>"
                f"<td>{esc(item.get('date'))}</td>"
                f"<td>{pct(outcome.get('return_pct'))}</td>"
                f"<td>{esc(outcome.get('accurate'))}</td>"
                "</tr>"
            )
        return "<div class='table-wrap'><table><thead><tr><th>Ticker</th><th>Signal</th><th>Date</th><th>Return</th><th>Accurate</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"

    open_trades = [trade for trade in trades if trade.get("status") == "open"]
    trade_note = f"Paper records tracked: {len(trades)}; open simulated records: {len(open_trades)}. No real trades are executed."
    return (
        "<div class='history-grid'>"
        "<div><h3>Best Signals</h3>" + signal_list(best) + "</div>"
        "<div><h3>Worst Signals</h3>" + signal_list(worst) + "</div>"
        "</div>"
        f"<p class='small-note'>{esc(trade_note)}</p>"
    )


def render_methodology(report: dict[str, Any]) -> str:
    methodology = report.get("methodology", {})
    weights = methodology.get("weights", {})
    weight_rows = "".join(f"<li>{esc(key.replace('_', ' '))}: {esc(value)}</li>" for key, value in weights.items())
    rules = "".join(f"<li>{esc(rule)}</li>" for rule in methodology.get("safety_rules", []))
    return (
        "<div class='methodology'>"
        f"<p>{esc(methodology.get('summary'))}</p>"
        f"<ul>{weight_rows}</ul>"
        f"<h3>Safety Rules</h3><ul>{rules}</ul>"
        "</div>"
    )


def generate_dashboard(report: dict[str, Any], output_path: str | Path) -> None:
    summary = report.get("portfolio_summary", {})
    title = esc(report.get("dashboard_title") or "Stock Research Agent")
    report_json = esc(json.dumps(report, indent=2))
    sanitized = bool(report.get("privacy", {}).get("sanitized"))
    if sanitized:
        summary_metrics = f"""
        <div class="metric"><strong>100%</strong><span>Total portfolio indexed</span></div>
        <div class="metric"><strong>{pct(summary.get("invested_allocation_pct"))}</strong><span>Invested allocation</span></div>
        <div class="metric"><strong>{pct(summary.get("cash_allocation_pct"))}</strong><span>Cash / SPAXX allocation</span></div>
        <div class="metric"><strong>{pct(summary.get("unrealized_gain_loss_pct"))}</strong><span>Unrealized P/L</span></div>
        """
        privacy_note = "Public sanitized view. Exact shares, cost basis, dollar values, and exact prices are redacted."
    else:
        summary_metrics = f"""
        <div class="metric"><strong>{money(summary.get("total_value"))}</strong><span>Total value</span></div>
        <div class="metric"><strong>{money(summary.get("invested_value"))}</strong><span>Invested value</span></div>
        <div class="metric"><strong>{money(summary.get("cash_value"))}</strong><span>Cash / SPAXX</span></div>
        <div class="metric"><strong>{pct(summary.get("unrealized_gain_loss_pct"))}</strong><span>Unrealized P/L</span></div>
        """
        privacy_note = "Private full-detail view."
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --bg: #f7f8fa;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #5f6b7a;
      --line: #d9e0e8;
      --accent: #0f766e;
      --accent-2: #b45309;
      --bad: #b42318;
      --good: #047857;
      --neutral: #475569;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.45;
    }}
    header {{
      background: #17202a;
      color: #fff;
      padding: 28px clamp(16px, 4vw, 48px);
      border-bottom: 5px solid var(--accent);
    }}
    header h1 {{ margin: 0 0 8px; font-size: clamp(1.6rem, 4vw, 2.5rem); letter-spacing: 0; }}
    header p {{ margin: 0; color: #d7dee7; max-width: 900px; }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 24px auto 48px; }}
    section {{ margin: 0 0 24px; padding: 22px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }}
    h2 {{ margin: 0 0 16px; font-size: 1.2rem; letter-spacing: 0; }}
    h3 {{ margin: 0 0 8px; font-size: 1rem; letter-spacing: 0; }}
    h3 span, td span {{ display: block; color: var(--muted); font-weight: 500; font-size: .86rem; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .metric {{ border-left: 4px solid var(--accent); padding: 10px 12px; background: #f8fbfb; }}
    .metric strong {{ display: block; font-size: 1.2rem; }}
    .metric span {{ color: var(--muted); font-size: .86rem; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
    th, td {{ text-align: left; vertical-align: top; padding: 12px; border-bottom: 1px solid var(--line); }}
    th {{ color: var(--muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; }}
    a {{ color: var(--accent); }}
    .action {{ display: inline-block; margin-bottom: 4px; color: #fff; background: var(--accent-2); border-radius: 999px; padding: 2px 8px; font-size: .82rem; font-weight: 700; }}
    .score-grid {{ display: flex; flex-wrap: wrap; gap: 6px; min-width: 230px; }}
    .score {{ border: 1px solid var(--line); border-radius: 999px; padding: 3px 7px; font-size: .78rem; background: #fff; }}
    .score.good {{ color: var(--good); border-color: #a7f3d0; background: #ecfdf5; }}
    .score.bad {{ color: var(--bad); border-color: #fecaca; background: #fef2f2; }}
    .score.neutral {{ color: var(--neutral); border-color: #cbd5e1; background: #f8fafc; }}
    .cards {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    .item-card {{ border: 1px solid var(--line); border-radius: 8px; padding: 16px; background: #fff; }}
    .item-card p {{ margin: 8px 0; }}
    .radar-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    .radar-bucket {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: #fbfcfd; }}
    .radar-bucket h3 {{ margin-bottom: 12px; }}
    .radar-card {{ border-left: 4px solid var(--accent); padding: 10px 12px; margin: 0 0 10px; background: #fff; }}
    .radar-card:last-child {{ margin-bottom: 0; }}
    .radar-card p {{ margin: 6px 0; }}
    .driver-list {{ margin: 8px 0; padding: 8px 10px; background: #f8fafc; border: 1px solid var(--line); border-radius: 6px; }}
    .driver-list strong {{ display: block; margin-bottom: 4px; font-size: .86rem; }}
    .driver-list ul {{ margin: 0; padding-left: 18px; }}
    .driver-list li {{ margin: 2px 0; color: var(--muted); font-size: .86rem; }}
    .methodology ul {{ margin: 8px 0 0; padding-left: 20px; }}
    details {{ margin-top: 16px; }}
    details.news-details {{ margin-top: 0; }}
    summary {{ cursor: pointer; font-weight: 700; color: var(--accent); }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #111827; color: #e5e7eb; padding: 16px; border-radius: 8px; font-size: .78rem; }}
    .disclaimer {{ border-left: 4px solid var(--accent-2); background: #fff7ed; padding: 12px; margin-top: 14px; color: #7c2d12; }}
    .usage-line, .small-note {{ color: var(--muted); font-size: .88rem; margin-top: 12px; }}
    .history-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
    @media (max-width: 760px) {{
      main {{ width: min(100% - 20px, 1180px); margin-top: 10px; }}
      section {{ padding: 16px; }}
      .summary-grid, .cards, .history-grid, .radar-grid {{ grid-template-columns: 1fr; }}
      header {{ padding: 22px 16px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <p>Generated {esc(report.get("generated_at"))} ({esc(report.get("run_session", "unknown"))}). Human-in-the-loop research only; this agent never executes trades.</p>
  </header>
  <main>
    <section>
      <h2>Portfolio Summary</h2>
      <div class="summary-grid">
        {summary_metrics}
      </div>
      <p class="disclaimer">{esc(privacy_note)} Not financial advice. Human review required. Signals can be wrong because public data can lag, headlines can be incomplete, and valuation context requires deeper research.</p>
    </section>
    <section><h2>Action Radar</h2>{render_action_radar(report)}</section>
    <section><h2>Holdings</h2>{render_holdings(report.get("holdings", []))}</section>
    <section><h2>GPT Analysis</h2>{render_gpt_analysis(report.get("gpt_analysis", {}))}</section>
    <section><h2>Sell Watch</h2>{render_holdings(report.get("sell_watch", [])) if report.get("sell_watch") else "<p>No holdings triggered sell-watch rules.</p>"}</section>
    <section><h2>Watchlist</h2>{render_watchlist(report.get("watchlist", []))}</section>
    <section><h2>Discovery Ideas</h2>{render_discovery(report.get("discovery_ideas", []))}</section>
    <section><h2>Learning / Signal Accuracy</h2>{render_learning_accuracy(report.get("signal_history", {}), report.get("signal_accuracy", {}))}</section>
    <section><h2>Signal Accuracy Summary</h2>{render_signal_accuracy(report.get("signal_history", {}))}</section>
    <section><h2>Historical Performance</h2>{render_historical_performance(report.get("signal_history", {}), report.get("paper_trades", {}))}</section>
    <section><h2>News/Catalysts</h2>{render_news(report.get("news_catalysts", []))}</section>
    <section><h2>Learning/Feedback Metrics</h2><p class="small-note">Signals are evaluated after the configured horizon. Positive signals are judged by later positive returns; risk signals are judged by whether they avoided or warned about weakness. These metrics are experimental and for learning only.</p></section>
    <section><h2>Methodology</h2>{render_methodology(report)}<details><summary>Raw latest_report.json</summary><pre>{report_json}</pre></details></section>
  </main>
</body>
</html>
"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_doc, encoding="utf-8")
