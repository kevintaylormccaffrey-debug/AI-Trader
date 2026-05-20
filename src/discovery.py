from __future__ import annotations

from typing import Any

from src import data_sources
from src.news import fetch_recent_news, summarize_news
from src.scoring import score_research_candidate


DISCOVERY_UNIVERSE: list[dict[str, Any]] = [
    {
        "ticker": "AVGO",
        "company": "Broadcom",
        "sector": "AI datacenter semiconductors",
        "why_it_matches": "Large-cap semiconductor and custom silicon exposure tied to AI infrastructure.",
        "catalyst": "AI networking/custom accelerator demand and VMware integration progress.",
        "risk": "Integration debt, customer concentration, and premium expectations.",
        "valuation_warning": "Premium valuation; expectations may already discount strong AI growth.",
        "confidence_level": "medium",
        "labels": ["semiconductors", "AI", "datacenter", "large cap"],
    },
    {
        "ticker": "MRVL",
        "company": "Marvell Technology",
        "sector": "datacenter semiconductors",
        "why_it_matches": "Datacenter connectivity, custom silicon, and optical/networking exposure.",
        "catalyst": "AI infrastructure buildout and custom silicon ramps.",
        "risk": "Cyclical end markets and execution risk in custom silicon.",
        "valuation_warning": "Growth premium requires sustained datacenter acceleration.",
        "confidence_level": "medium",
        "labels": ["semiconductors", "AI", "datacenter", "mid cap"],
    },
    {
        "ticker": "ARM",
        "company": "Arm Holdings",
        "sector": "semiconductor IP",
        "why_it_matches": "Low-power compute architecture aligns with edge AI and mobile/datacenter efficiency.",
        "catalyst": "AI device cycles and royalty growth from higher-value chip designs.",
        "risk": "Very high expectations, customer concentration, and royalty model sensitivity.",
        "valuation_warning": "Often trades at a rich growth multiple; valuation caution is high.",
        "confidence_level": "medium",
        "labels": ["semiconductors", "AI", "large cap"],
    },
    {
        "ticker": "CDNS",
        "company": "Cadence Design Systems",
        "sector": "semiconductor design automation",
        "why_it_matches": "EDA software is a picks-and-shovels beneficiary of advanced chip design complexity.",
        "catalyst": "AI-assisted chip design tools and continued advanced-node demand.",
        "risk": "High software multiple and semiconductor cycle sensitivity.",
        "valuation_warning": "Premium software valuation; pullbacks can be sharp if growth slows.",
        "confidence_level": "medium",
        "labels": ["automation", "semiconductors", "AI", "large cap"],
    },
    {
        "ticker": "SNPS",
        "company": "Synopsys",
        "sector": "semiconductor design automation",
        "why_it_matches": "EDA and IP exposure to advanced chips, AI hardware, and verification complexity.",
        "catalyst": "Design complexity, AI-enabled EDA, and IP demand.",
        "risk": "Valuation, integration risk, and semiconductor capex cycles.",
        "valuation_warning": "Premium valuation; confirm growth durability before acting.",
        "confidence_level": "medium",
        "labels": ["automation", "semiconductors", "AI", "large cap"],
    },
    {
        "ticker": "TSM",
        "company": "Taiwan Semiconductor Manufacturing",
        "sector": "semiconductor foundry",
        "why_it_matches": "Advanced foundry leadership supports AI accelerators, CPUs, and edge chips.",
        "catalyst": "Advanced-node demand and AI chip production volume.",
        "risk": "Geopolitical concentration and cyclical foundry utilization.",
        "valuation_warning": "Valuation can expand with AI demand; geopolitical discount may persist.",
        "confidence_level": "medium",
        "labels": ["semiconductors", "AI", "large cap"],
    },
    {
        "ticker": "MU",
        "company": "Micron Technology",
        "sector": "memory semiconductors",
        "why_it_matches": "High-bandwidth memory demand is tied to AI datacenter growth.",
        "catalyst": "HBM pricing, datacenter memory demand, and supply discipline.",
        "risk": "Memory remains cyclical; downturns can be severe.",
        "valuation_warning": "Cyclical earnings can make valuation screens misleading.",
        "confidence_level": "medium",
        "labels": ["semiconductors", "AI", "datacenter", "large cap"],
    },
    {
        "ticker": "DDOG",
        "company": "Datadog",
        "sector": "cloud observability software",
        "why_it_matches": "Cloud monitoring and AI observability fit high-growth infrastructure software.",
        "catalyst": "AI workload monitoring, cloud optimization, and platform expansion.",
        "risk": "Software spending cycles and premium valuation.",
        "valuation_warning": "High-growth software multiple requires durable net retention.",
        "confidence_level": "medium",
        "labels": ["high-growth tech", "AI", "software", "mid cap"],
    },
]


def label_allowed(candidate: dict[str, Any], preferences: dict[str, Any], settings: dict[str, Any]) -> bool:
    labels = {str(label).lower() for label in candidate.get("labels", [])}
    excluded = {str(label).lower() for label in settings.get("discovery", {}).get("excluded_labels", [])}
    avoid = {str(label).lower() for label in preferences.get("avoid_sectors", [])}
    if labels & excluded or labels & avoid:
        return False

    preferred = {str(label).lower() for label in preferences.get("preferred_sectors", [])}
    if not preferred:
        return True
    haystack = " ".join(labels | {str(candidate.get("sector", "")).lower()})
    return any(pref.lower() in haystack for pref in preferred)


def generate_discovery_ideas(
    portfolio: dict[str, Any],
    watchlist: dict[str, Any],
    settings: dict[str, Any],
    sector_signals: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    held = {str(item.get("ticker", "")).upper() for item in portfolio.get("holdings", [])}
    watched = {str(item.get("ticker", "")).upper() for item in watchlist.get("tickers", [])}
    preferences = portfolio.get("discovery_preferences", {})
    max_ideas = int(settings.get("discovery", {}).get("max_ideas", 5))
    minimum_price = float(settings.get("discovery", {}).get("minimum_price", 5))

    ideas: list[dict[str, Any]] = []
    for candidate in DISCOVERY_UNIVERSE:
        ticker = candidate["ticker"].upper()
        if ticker in held or ticker in watched:
            continue
        if not label_allowed(candidate, preferences, settings):
            continue

        market = data_sources.fetch_market_snapshot(ticker, settings)
        price = market.get("price")
        if price is not None and price < minimum_price:
            continue
        news_items = fetch_recent_news(ticker, settings)
        earnings = data_sources.fetch_earnings_date(ticker, settings)
        score = score_research_candidate(
            candidate,
            market,
            news_items,
            earnings.get("earnings_date"),
            sector_signals,
            settings,
        )
        idea = {
            **candidate,
            "current_price": price,
            "daily_change_pct": market.get("daily_change_pct"),
            "market_data_source": market.get("source"),
            "earnings_date": earnings.get("earnings_date"),
            "news_summary": summarize_news(news_items),
            "news": news_items,
            "scores": score,
        }
        ideas.append(idea)

    ideas.sort(key=lambda row: row.get("scores", {}).get("overall_score", 0), reverse=True)
    return ideas[:max_ideas]
