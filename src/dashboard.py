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
    return "<div class='table-wrap'><table><thead><tr><th>Ticker</th><th>Headline</th><th>Tag</th><th>Sentiment</th><th>Risk</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"


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
    .methodology ul {{ margin: 8px 0 0; padding-left: 20px; }}
    details {{ margin-top: 16px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #111827; color: #e5e7eb; padding: 16px; border-radius: 8px; font-size: .78rem; }}
    .disclaimer {{ border-left: 4px solid var(--accent-2); background: #fff7ed; padding: 12px; margin-top: 14px; color: #7c2d12; }}
    @media (max-width: 760px) {{
      main {{ width: min(100% - 20px, 1180px); margin-top: 10px; }}
      section {{ padding: 16px; }}
      .summary-grid, .cards {{ grid-template-columns: 1fr; }}
      header {{ padding: 22px 16px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <p>Generated {esc(report.get("generated_at"))}. Human-in-the-loop research only; this agent never executes trades.</p>
  </header>
  <main>
    <section>
      <h2>Portfolio Summary</h2>
      <div class="summary-grid">
        {summary_metrics}
      </div>
      <p class="disclaimer">{esc(privacy_note)} Not financial advice. Human review required. Signals can be wrong because public data can lag, headlines can be incomplete, and valuation context requires deeper research.</p>
    </section>
    <section><h2>Holdings</h2>{render_holdings(report.get("holdings", []))}</section>
    <section><h2>News/Catalysts</h2>{render_news(report.get("news_catalysts", []))}</section>
    <section><h2>Sell Watch</h2>{render_holdings(report.get("sell_watch", [])) if report.get("sell_watch") else "<p>No holdings triggered sell-watch rules.</p>"}</section>
    <section><h2>Watchlist</h2>{render_watchlist(report.get("watchlist", []))}</section>
    <section><h2>Discovery Ideas</h2>{render_discovery(report.get("discovery_ideas", []))}</section>
    <section><h2>Methodology</h2>{render_methodology(report)}<details><summary>Raw latest_report.json</summary><pre>{report_json}</pre></details></section>
  </main>
</body>
</html>
"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_doc, encoding="utf-8")
