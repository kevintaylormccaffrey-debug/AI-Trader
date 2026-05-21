from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluated_signals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        signal
        for signal in payload.get("signals", [])
        if signal.get("status") == "reviewed" or (signal.get("later_outcome") or {}).get("status") == "evaluated"
    ]


def print_signal(signal: dict[str, Any]) -> None:
    outcome = signal.get("later_outcome") or {}
    return_pct = signal.get("return_since_signal_pct", outcome.get("return_pct"))
    accurate = signal.get("successful", outcome.get("accurate"))
    print(
        f"{signal.get('ticker')} | {signal.get('recommendation_label', signal.get('signal_type'))} | "
        f"{signal.get('date')} | return {return_pct}% | "
        f"accurate={accurate} | {signal.get('reason')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate signal history accuracy.")
    parser.add_argument("--history", default="data/signals_history.json", help="Path to signals history JSON.")
    parser.add_argument("--top", type=int, default=5, help="Number of best/worst signals to print.")
    args = parser.parse_args()

    payload = load(Path(args.history))
    signals = evaluated_signals(payload)
    stats = payload.get("accuracy_stats", {})

    print("Accuracy by signal type")
    if not stats:
        print("No evaluated signals yet.")
    for signal_type, bucket in sorted(stats.items()):
        print(
            f"- {signal_type}: total={bucket.get('total')} evaluated={bucket.get('evaluated')} "
            f"pending={bucket.get('pending')} accuracy={bucket.get('accuracy_pct')}% "
            f"avg_return={bucket.get('average_return_pct')}%"
        )

    ranked = sorted(
        signals,
        key=lambda signal: signal.get("return_since_signal_pct", (signal.get("later_outcome") or {}).get("return_pct")) or 0,
        reverse=True,
    )
    print("\nBest-performing signals")
    for signal in ranked[: args.top]:
        print_signal(signal)

    print("\nWorst-performing signals")
    for signal in list(reversed(ranked[-args.top:])):
        print_signal(signal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
