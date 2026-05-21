from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import discord
import requests
from discord import app_commands

from src import data_sources
from src.gpt_analysis import calc_cost, estimate_tokens


MAX_DISCORD_DESCRIPTION = 3900


def truncate(text: Any, limit: int = 1000) -> str:
    value = "" if text is None else str(text)
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return str(value)


def money(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def load_json_file(path: str | Path, default: Any) -> Any:
    json_path = Path(path)
    if not json_path.exists():
        return default
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def response_paths(settings: dict[str, Any]) -> tuple[Path, Path]:
    private_report = Path(settings.get("report_path", "output/latest_report.json"))
    public_report = Path(settings.get("public_report_path", "public/latest_report.json"))
    return private_report, public_report


class ResearchState:
    def __init__(self, settings_path: str = "config/settings.yaml") -> None:
        self.settings_path = settings_path

    def load(self) -> dict[str, Any]:
        settings = data_sources.load_settings(self.settings_path)
        private_report, public_report = response_paths(settings)
        report_path = private_report if private_report.exists() else public_report
        report = load_json_file(report_path, {})
        portfolio = data_sources.load_json_from_env_or_path("PORTFOLIO_JSON", settings["portfolio_path"])
        watchlist = data_sources.load_json_from_env_or_path("WATCHLIST_JSON", settings["watchlist_path"])
        signals = load_json_file(settings.get("history", {}).get("signals_history_path", "data/signals_history.json"), {})
        paper = load_json_file(settings.get("history", {}).get("paper_trades_path", "data/paper_trades.json"), {})
        return {
            "settings": settings,
            "report": report,
            "portfolio": portfolio,
            "watchlist": watchlist,
            "signals": signals,
            "paper": paper,
            "report_path": str(report_path),
        }


def holding_lines(report: dict[str, Any], limit: int = 8) -> list[str]:
    lines: list[str] = []
    for item in report.get("holdings", [])[:limit]:
        ticker = item.get("ticker")
        action = item.get("action", "n/a")
        score = item.get("scores", {}).get("overall_score", "n/a")
        weight = item.get("position_weight_pct") or item.get("portfolio_weight_pct")
        pnl = item.get("unrealized_gain_loss_pct")
        price = item.get("current_price") or item.get("price_band")
        lines.append(f"**{ticker}**: {action}, score {score}, weight {pct(weight)}, P/L {pct(pnl)}, price {price}")
    return lines


def watchlist_lines(report: dict[str, Any], limit: int = 8) -> list[str]:
    lines: list[str] = []
    for item in report.get("watchlist", [])[:limit]:
        score = item.get("scores", {}).get("overall_score", "n/a")
        lines.append(
            f"**{item.get('ticker')}**: {item.get('action', 'research only')}, score {score}, {truncate(item.get('thesis'), 120)}"
        )
    return lines


def signal_lines(signals: dict[str, Any], limit: int = 8) -> list[str]:
    rows = list(reversed(signals.get("signals", [])))[:limit]
    if not rows:
        return ["No signals recorded yet."]
    return [
        f"**{row.get('ticker')}**: {row.get('signal_type')} ({row.get('source')}, conf {row.get('confidence')}) - {truncate(row.get('reason'), 110)}"
        for row in rows
    ]


def gpt_event_lines(report: dict[str, Any], limit: int = 6) -> list[str]:
    events = report.get("gpt_analysis", {}).get("events", [])[:limit]
    if not events:
        return ["No GPT event analyses found in the latest report."]
    return [
        f"**{event.get('ticker')}**: {event.get('classification')} ({event.get('confidence_score')}) - {truncate(event.get('why_it_matters'), 120)}"
        for event in events
    ]


def performance_lines(signals: dict[str, Any], key: str, limit: int = 5) -> list[str]:
    rows = signals.get(key, [])[:limit]
    if not rows:
        return ["Not enough evaluated signals yet."]
    output = []
    for row in rows:
        outcome = row.get("later_outcome", {})
        output.append(
            f"**{row.get('ticker')}**: {row.get('signal_type')} from {row.get('date')} -> {pct(outcome.get('return_pct'))}, accurate={outcome.get('accurate')}"
        )
    return output


def build_embed(title: str, description: str, color: int = 0x0F766E) -> discord.Embed:
    embed = discord.Embed(title=title, description=truncate(description, MAX_DISCORD_DESCRIPTION), color=color)
    embed.set_footer(text="Research only. Not financial advice. Human review required.")
    return embed


def add_fields(embed: discord.Embed, fields: list[tuple[str, str, bool]]) -> discord.Embed:
    for name, value, inline in fields:
        embed.add_field(name=name, value=truncate(value or "n/a", 1024), inline=inline)
    return embed


def latest_context_for_prompt(state: dict[str, Any], question: str) -> str:
    report = state["report"]
    portfolio = state["portfolio"]
    signals = state["signals"]
    paper = state["paper"]
    summary = report.get("portfolio_summary", {})
    context = {
        "question": question,
        "portfolio_summary": {
            "name": summary.get("portfolio_name") or portfolio.get("portfolio_name"),
            "unrealized_gain_loss_pct": summary.get("unrealized_gain_loss_pct"),
            "cash_allocation_pct": summary.get("cash_allocation_pct"),
            "sell_watch_count": summary.get("sell_watch_count"),
            "high_priority_alert_count": summary.get("high_priority_alert_count"),
            "run_session": report.get("run_session"),
            "generated_at": report.get("generated_at"),
        },
        "holdings": [
            {
                "ticker": item.get("ticker"),
                "company": item.get("company"),
                "sector": item.get("sector"),
                "thesis": item.get("thesis"),
                "action": item.get("action"),
                "reasoning": item.get("action_reasoning"),
                "overall_score": item.get("scores", {}).get("overall_score"),
                "pnl_pct": item.get("unrealized_gain_loss_pct"),
                "weight_pct": item.get("position_weight_pct") or item.get("portfolio_weight_pct"),
                "news_summary": item.get("news_summary"),
            }
            for item in report.get("holdings", [])[:10]
        ],
        "watchlist": [
            {
                "ticker": item.get("ticker"),
                "company": item.get("company"),
                "thesis": item.get("thesis"),
                "action": item.get("action"),
                "overall_score": item.get("scores", {}).get("overall_score"),
            }
            for item in report.get("watchlist", [])[:8]
        ],
        "discovery_ideas": [
            {
                "ticker": item.get("ticker"),
                "company": item.get("company"),
                "sector": item.get("sector"),
                "why_it_matches": item.get("why_it_matches"),
                "risk": item.get("risk"),
                "overall_score": item.get("scores", {}).get("overall_score"),
            }
            for item in report.get("discovery_ideas", [])[:8]
        ],
        "gpt_events": report.get("gpt_analysis", {}).get("events", [])[:8],
        "recent_signals": list(reversed(signals.get("signals", [])))[:12],
        "accuracy_stats": signals.get("accuracy_stats", {}),
        "best_performing_signals": signals.get("best_performing_signals", [])[:5],
        "worst_performing_signals": signals.get("worst_performing_signals", [])[:5],
        "paper_summary": {
            "paper_trade_count": len(paper.get("paper_trades", [])),
            "open_paper_trade_count": len([trade for trade in paper.get("paper_trades", []) if trade.get("status") == "open"]),
        },
        "discovery_preferences": portfolio.get("discovery_preferences", {}),
    }
    return json.dumps(context, separators=(",", ":"), default=str)


def ask_openai(question: str, state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    settings = state["settings"]
    cfg = settings.get("openai", {})
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return (
            "I can answer rules-only commands, but `OPENAI_API_KEY` is not set for `/ask` reasoning.",
            {"gpt_call_count": 0, "estimated_cost_usd": 0.0},
        )

    context = latest_context_for_prompt(state, question)
    prompt = (
        "You are Kevin's personal AI stock research assistant. Use the provided JSON context and answer the question. "
        "Be conversational but concise. Do not give financial advice, guaranteed returns, or buy-now instructions. "
        "Use research language such as research candidate, hold thesis intact, risk elevated, sell watch, or human review required. "
        "Include confidence and uncertainty/risk notes when relevant. Keep under 900 words.\n\n"
        f"Context JSON:\n{context}"
    )
    max_tokens = int(cfg.get("chat_max_tokens_per_call", 700))
    payload: dict[str, Any] = {
        "model": cfg.get("chat_model") or cfg.get("model", "gpt-5-nano"),
        "input": prompt,
        "max_output_tokens": max_tokens,
    }
    if str(payload["model"]).startswith("gpt-5"):
        payload["reasoning"] = {"effort": "minimal"}

    response = requests.post(
        str(cfg.get("api_url", "https://api.openai.com/v1/responses")),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=45,
    )
    response.raise_for_status()
    data = response.json()
    text = data.get("output_text")
    if not text:
        pieces = []
        for output in data.get("output", []) or []:
            for content in output.get("content", []) or []:
                if content.get("text"):
                    pieces.append(content["text"])
        text = "\n".join(pieces)

    usage = data.get("usage", {}) or {}
    input_tokens = int(usage.get("input_tokens") or estimate_tokens(prompt))
    output_tokens = int(usage.get("output_tokens") or estimate_tokens(text or ""))
    return text or "I could not generate a useful answer from the current context.", {
        "gpt_call_count": 1,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": calc_cost(input_tokens, output_tokens, settings),
    }


class StockResearchBot(discord.Client):
    def __init__(self, state: ResearchState, guild_id: int | None = None) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.state = state
        self.guild_id = guild_id

    async def setup_hook(self) -> None:
        register_commands(self)
        if self.guild_id:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()


def register_commands(bot: StockResearchBot) -> None:
    @bot.tree.command(name="ask", description="Ask the AI research assistant about your portfolio, watchlist, or signals.")
    @app_commands.describe(question="Question to ask the stock research assistant")
    async def ask(interaction: discord.Interaction, question: str) -> None:
        await interaction.response.defer(thinking=True)
        state = bot.state.load()
        try:
            answer, usage = ask_openai(question, state)
        except requests.RequestException as exc:
            answer = f"OpenAI request failed, so I cannot answer `/ask` right now: {exc}"
            usage = {"gpt_call_count": 0, "estimated_cost_usd": 0.0}
        embed = build_embed("Research Assistant", answer)
        embed.add_field(
            name="Usage",
            value=f"GPT calls: {usage.get('gpt_call_count', 0)} | Est. cost: ${usage.get('estimated_cost_usd', 0)}",
            inline=False,
        )
        await interaction.followup.send(embed=embed)

    @bot.tree.command(name="portfolio", description="Show current portfolio signals from the latest report.")
    async def portfolio(interaction: discord.Interaction) -> None:
        state = bot.state.load()
        report = state["report"]
        summary = report.get("portfolio_summary", {})
        description = "\n".join(holding_lines(report)) or "No holdings found."
        embed = build_embed("Portfolio Signals", description)
        add_fields(
            embed,
            [
                ("Generated", str(report.get("generated_at", "n/a")), True),
                ("Run", str(report.get("run_session", "n/a")), True),
                ("Unrealized P/L", pct(summary.get("unrealized_gain_loss_pct")), True),
            ],
        )
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="signals", description="Show recent signals and GPT event notes.")
    async def signals(interaction: discord.Interaction) -> None:
        state = bot.state.load()
        embed = build_embed("Recent Signals", "\n".join(signal_lines(state["signals"])))
        embed.add_field(name="Latest GPT/Event Notes", value="\n".join(gpt_event_lines(state["report"])), inline=False)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="watchlist", description="Show watchlist signals from the latest report.")
    async def watchlist(interaction: discord.Interaction) -> None:
        state = bot.state.load()
        await interaction.response.send_message(embed=build_embed("Watchlist", "\n".join(watchlist_lines(state["report"]))))

    @bot.tree.command(name="top-performers", description="Show best-performing historical signals.")
    async def top_performers(interaction: discord.Interaction) -> None:
        state = bot.state.load()
        await interaction.response.send_message(
            embed=build_embed("Best-Performing Signals", "\n".join(performance_lines(state["signals"], "best_performing_signals")))
        )

    @bot.tree.command(name="worst-performers", description="Show worst-performing historical signals.")
    async def worst_performers(interaction: discord.Interaction) -> None:
        state = bot.state.load()
        await interaction.response.send_message(
            embed=build_embed("Worst-Performing Signals", "\n".join(performance_lines(state["signals"], "worst_performing_signals")), color=0xB42318)
        )

    @bot.tree.command(name="open-alerts", description="Show current sell-watch and high-priority alerts.")
    async def open_alerts(interaction: discord.Interaction) -> None:
        state = bot.state.load()
        report = state["report"]
        sell_watch = report.get("sell_watch", [])
        high_priority = report.get("high_priority_alerts", [])
        lines = []
        if sell_watch:
            lines.append("**Sell Watch**")
            lines.extend(f"- {item.get('ticker')}: {truncate(item.get('action_reasoning'), 160)}" for item in sell_watch[:6])
        if high_priority:
            lines.append("**High Priority**")
            lines.extend(f"- {item.get('ticker')}: {item.get('action')} | {truncate(item.get('action_reasoning'), 160)}" for item in high_priority[:6])
        await interaction.response.send_message(embed=build_embed("Open Alerts", "\n".join(lines) or "No open alerts in the latest report."))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the interactive Discord stock research bot.")
    parser.add_argument("--settings", default="config/settings.yaml", help="Path to settings YAML.")
    args = parser.parse_args()

    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN is not set.")
    guild_id_raw = os.getenv("DISCORD_GUILD_ID")
    guild_id = int(guild_id_raw) if guild_id_raw else None
    bot = StockResearchBot(ResearchState(args.settings), guild_id)
    bot.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
