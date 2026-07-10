from __future__ import annotations

from typing import Any

from src import data_sources
from src.entry_zones import build_entry_zone
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
    {
        "ticker": "CRWD",
        "company": "CrowdStrike",
        "sector": "cybersecurity software",
        "why_it_matches": "Endpoint and cloud security remain secular priorities as AI increases attack surface.",
        "catalyst": "Platform consolidation, identity/cloud module growth, and security spending resilience.",
        "risk": "Premium valuation and execution risk after major service incidents.",
        "valuation_warning": "High software multiple; requires durable growth and margin expansion.",
        "confidence_level": "medium",
        "labels": ["cybersecurity", "software", "quality growth", "secular growth", "large cap"],
    },
    {
        "ticker": "PANW",
        "company": "Palo Alto Networks",
        "sector": "cybersecurity software",
        "why_it_matches": "Security platform consolidation and AI-enabled threat detection are durable enterprise priorities.",
        "catalyst": "Platformization strategy, cloud security adoption, and AI security products.",
        "risk": "Sales transition risk, competitive pressure, and premium valuation.",
        "valuation_warning": "Premium multiple; confirm billings and platform adoption trends.",
        "confidence_level": "medium",
        "labels": ["cybersecurity", "software", "quality growth", "secular growth", "large cap"],
    },
    {
        "ticker": "AXON",
        "company": "Axon Enterprise",
        "sector": "public safety technology",
        "why_it_matches": "Mission-critical hardware, cloud evidence software, and AI workflow tools create recurring public-safety demand.",
        "catalyst": "Cloud software attach rates, AI report-writing tools, and public safety modernization.",
        "risk": "Government budget cycles, valuation, and execution expectations.",
        "valuation_warning": "High growth premium; watch for multiple compression if bookings slow.",
        "confidence_level": "medium",
        "labels": ["public safety", "software", "quality growth", "category leader", "large cap"],
    },
    {
        "ticker": "ISRG",
        "company": "Intuitive Surgical",
        "sector": "medtech robotics",
        "why_it_matches": "Robotic surgery leader with recurring instrument revenue and long runway for procedure growth.",
        "catalyst": "New system adoption, procedure volume growth, and international penetration.",
        "risk": "Hospital capex cycles, competition, and premium valuation.",
        "valuation_warning": "Quality compounder valuation; entry price matters.",
        "confidence_level": "medium",
        "labels": ["medtech", "healthcare", "quality growth", "category leader", "large cap"],
    },
    {
        "ticker": "TMDX",
        "company": "TransMedics",
        "sector": "medtech transplant logistics",
        "why_it_matches": "Organ transplant logistics platform targets a specialized market with strong growth potential.",
        "catalyst": "National OCS Program expansion, transplant volume growth, and operating leverage.",
        "risk": "Execution risk, reimbursement sensitivity, and smaller-cap volatility.",
        "valuation_warning": "High-growth medtech valuation can reset quickly on operational misses.",
        "confidence_level": "medium",
        "labels": ["medtech", "healthcare", "quality growth", "secular growth", "mid cap"],
    },
    {
        "ticker": "LLY",
        "company": "Eli Lilly",
        "sector": "pharmaceuticals",
        "why_it_matches": "Large-cap healthcare growth tied to obesity, diabetes, and pipeline execution.",
        "catalyst": "GLP-1 demand, manufacturing expansion, and pipeline readouts.",
        "risk": "Valuation, supply constraints, policy risk, and competition.",
        "valuation_warning": "High expectations are embedded; monitor growth durability.",
        "confidence_level": "medium",
        "labels": ["healthcare", "quality growth", "profitable growth", "large cap"],
    },
    {
        "ticker": "VRT",
        "company": "Vertiv",
        "sector": "datacenter power and cooling",
        "why_it_matches": "AI datacenter buildouts need power, thermal management, and infrastructure capacity.",
        "catalyst": "AI server power density, datacenter capex, and backlog conversion.",
        "risk": "Cyclical infrastructure spending and valuation after strong performance.",
        "valuation_warning": "Momentum premium; watch order growth and margins.",
        "confidence_level": "medium",
        "labels": ["datacenter", "industrial automation", "quality growth", "secular growth", "large cap"],
    },
    {
        "ticker": "ETN",
        "company": "Eaton",
        "sector": "electrical infrastructure",
        "why_it_matches": "Electrification, grid investment, and datacenter power demand support long-term growth.",
        "catalyst": "Electrical backlog, datacenter demand, and infrastructure investment.",
        "risk": "Industrial cycle risk and premium valuation.",
        "valuation_warning": "Quality industrial multiple; verify growth and margin resilience.",
        "confidence_level": "medium",
        "labels": ["industrial automation", "energy infrastructure", "quality growth", "profitable growth", "large cap"],
    },
    {
        "ticker": "CEG",
        "company": "Constellation Energy",
        "sector": "clean energy infrastructure",
        "why_it_matches": "Reliable low-carbon power demand may benefit from datacenter and electrification growth.",
        "catalyst": "Power demand from AI datacenters, nuclear contract pricing, and policy support.",
        "risk": "Regulatory risk, commodity power prices, and project execution.",
        "valuation_warning": "Power-market assumptions can shift; review contracted vs merchant exposure.",
        "confidence_level": "medium",
        "labels": ["energy infrastructure", "datacenter", "quality growth", "large cap"],
    },
    {
        "ticker": "MELI",
        "company": "MercadoLibre",
        "sector": "e-commerce and fintech",
        "why_it_matches": "Latin American e-commerce, payments, and credit platform with long growth runway.",
        "catalyst": "Marketplace growth, fintech adoption, ads, logistics, and operating leverage.",
        "risk": "FX, regional macro volatility, credit losses, and valuation.",
        "valuation_warning": "Premium growth valuation; macro shocks can create drawdowns.",
        "confidence_level": "medium",
        "labels": ["e-commerce", "fintech", "quality growth", "secular growth", "large cap"],
    },
    {
        "ticker": "UBER",
        "company": "Uber",
        "sector": "mobility and delivery platform",
        "why_it_matches": "Global mobility platform with improving profitability, delivery scale, and optionality in autonomous networks.",
        "catalyst": "Free cash flow growth, membership adoption, ads, and autonomous vehicle partnerships.",
        "risk": "Regulation, insurance costs, competition, and macro sensitivity.",
        "valuation_warning": "Multiple depends on durable margin expansion and cash generation.",
        "confidence_level": "medium",
        "labels": ["consumer growth", "software", "quality growth", "profitable growth", "large cap"],
    },
    {
        "ticker": "CAVA",
        "company": "CAVA Group",
        "sector": "consumer restaurant growth",
        "why_it_matches": "Emerging restaurant category leader with unit growth and brand momentum.",
        "catalyst": "New unit expansion, same-store sales, margin improvement, and brand awareness.",
        "risk": "Restaurant execution, consumer slowdown, and very high valuation.",
        "valuation_warning": "High-growth consumer multiple; pullbacks can be sharp.",
        "confidence_level": "medium",
        "labels": ["consumer growth", "quality growth", "category leader", "mid cap"],
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
    discovery_settings = settings.get("discovery", {})
    if discovery_settings.get("include_broad_growth", True):
        broad_labels = {str(label).lower() for label in discovery_settings.get("broad_growth_labels", [])}
        if labels & broad_labels:
            return True
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
        entry_zone = (
            build_entry_zone(candidate, market, score, owned=False)
            if settings.get("entry_zones", {}).get("enabled", True)
            else None
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
            "entry_zone": entry_zone,
        }
        ideas.append(idea)

    ideas.sort(key=lambda row: row.get("scores", {}).get("overall_score", 0), reverse=True)
    return ideas[:max_ideas]
