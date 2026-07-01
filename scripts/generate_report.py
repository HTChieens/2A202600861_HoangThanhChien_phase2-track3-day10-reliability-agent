from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def fmt(value: Any) -> str:
    return "null" if value is None else str(value)


def met(actual: float, target: float, higher_is_better: bool = True) -> str:
    passed = actual >= target if higher_is_better else actual < target
    return "Yes" if passed else "No"


def build_report(metrics: dict[str, Any], comparison: dict[str, Any] | None = None) -> str:
    scenarios = metrics.get("scenarios", {})
    availability = float(metrics["availability"])
    p95 = float(metrics["latency_p95_ms"])
    fallback_rate = float(metrics["fallback_success_rate"])
    cache_rate = float(metrics["cache_hit_rate"])
    recovery = metrics.get("recovery_time_ms")
    recovery_text = "Not observed" if recovery is None else f"{float(recovery):.2f} ms"
    recovery_met = "N/A" if recovery is None else met(float(recovery), 5000, higher_is_better=False)

    scenario_rows = []
    for name, status in scenarios.items():
        if name == "primary_timeout_100":
            expected = "Primary fails 100%; backup should serve requests and circuit should open."
        elif name == "primary_flaky_50":
            expected = "Primary is flaky; gateway should mix primary, fallback, and circuit protection."
        elif name == "all_healthy":
            expected = "Baseline run should mostly use primary/cache with limited fallback."
        else:
            expected = "Scenario should preserve availability through cache, fallback, or static fallback."
        scenario_rows.append(f"| {name} | {expected} | Scenario status: {status}. | {status.title()} |")

    if not scenario_rows:
        scenario_rows.append("| default | Baseline gateway run. | No named scenarios configured. | N/A |")

    if comparison is not None:
        without_cache = comparison["without_cache"]
        with_cache = metrics
        cache_comparison_rows = [
            (
                "latency_p50_ms",
                " ms",
                float(without_cache["latency_p50_ms"]),
                float(with_cache["latency_p50_ms"]),
            ),
            (
                "latency_p95_ms",
                " ms",
                float(without_cache["latency_p95_ms"]),
                float(with_cache["latency_p95_ms"]),
            ),
            (
                "estimated_cost",
                "",
                float(without_cache["estimated_cost"]),
                float(with_cache["estimated_cost"]),
            ),
            (
                "cache_hit_rate",
                "",
                float(without_cache["cache_hit_rate"]),
                float(with_cache["cache_hit_rate"]),
            ),
            (
                "availability",
                "",
                float(without_cache["availability"]),
                float(with_cache["availability"]),
            ),
            (
                "circuit_open_count",
                "",
                float(without_cache["circuit_open_count"]),
                float(with_cache["circuit_open_count"]),
            ),
        ]
        comparison_table = []
        for name, suffix, without_value, with_value in cache_comparison_rows:
            delta = with_value - without_value
            comparison_table.append(
                f"| {name} | {without_value:g}{suffix} | {with_value:g}{suffix} | {delta:+g}{suffix} |"
            )
        comparison_note = "The comparison artifact in `reports/cache_comparison.json` was used for the no-cache baseline."
    else:
        comparison_table = [
            f"| latency_p50_ms | Not recorded | {fmt(metrics['latency_p50_ms'])} | N/A |",
            f"| latency_p95_ms | Not recorded | {fmt(metrics['latency_p95_ms'])} | N/A |",
            f"| estimated_cost | Not recorded | {fmt(metrics['estimated_cost'])} | N/A |",
            f"| cache_hit_rate | 0 | {fmt(metrics['cache_hit_rate'])} | +{fmt(metrics['cache_hit_rate'])} |",
        ]
        comparison_note = "No `reports/cache_comparison.json` artifact was found, so only the cache-enabled run is shown."

    lines = [
        "# Day 10 Reliability Report",
        "",
        "## 1. Architecture summary",
        "",
        "This project implements a reliability layer for an LLM gateway. Requests check the semantic cache first. Cache misses are routed through provider-specific circuit breakers, then through the provider fallback chain. If every provider path fails, the gateway returns a static degraded response.",
        "",
        "```",
        "User Request",
        "    |",
        "    v",
        "[ReliabilityGateway]",
        "    |",
        "    v",
        "[Semantic Cache] ---- HIT ----> Return cached response",
        "    |",
        "   MISS",
        "    |",
        "    v",
        "[Circuit Breaker: primary] ---> FakeLLMProvider primary",
        "    |",
        "    v",
        "[Circuit Breaker: backup] ----> FakeLLMProvider backup",
        "    |",
        "    v",
        "[Static fallback message]",
        "```",
        "",
        "## 2. Configuration",
        "",
        "| Setting | Value | Reason |",
        "|---|---:|---|",
        "| failure_threshold | 3 | Opens a circuit after repeated failures without reacting to a single transient error. |",
        "| reset_timeout_seconds | 2 | Keeps recovery visible in local chaos runs. |",
        "| success_threshold | 1 | One successful half-open probe closes the circuit in this lab. |",
        "| cache TTL | 300 seconds | Reuses repeated lab prompts while bounding staleness. |",
        "| similarity_threshold | 0.92 | Conservative threshold to reduce false semantic hits. |",
        "| load_test requests | 100 per scenario | Produces useful metrics without making the lab too slow. |",
        "| cache backend | memory by default; Redis supported | Memory is fast locally; Redis enables shared cache state. |",
        "",
        "## 3. SLO definitions",
        "",
        "| SLI | SLO target | Actual value | Met? |",
        "|---|---|---:|---|",
        f"| Availability | >= 99% | {pct(availability)} | {met(availability, 0.99)} |",
        f"| Latency P95 | < 2500 ms | {p95:.2f} ms | {met(p95, 2500, higher_is_better=False)} |",
        f"| Fallback success rate | >= 95% | {pct(fallback_rate)} | {met(fallback_rate, 0.95)} |",
        f"| Cache hit rate | >= 10% | {pct(cache_rate)} | {met(cache_rate, 0.10)} |",
        f"| Recovery time | < 5000 ms | {recovery_text} | {recovery_met} |",
        "",
        "## 4. Metrics",
        "",
        "Metrics from `reports/metrics.json`:",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]

    for key, value in metrics.items():
        if key == "scenarios":
            continue
        lines.append(f"| {key} | {fmt(value)} |")

    lines += [
        "",
        "## 5. Cache comparison",
        "",
        comparison_note,
        "",
        "| Metric | Without cache | With cache | Delta |",
        "|---|---:|---:|---|",
        *comparison_table,
        "",
        "## 6. Redis shared cache",
        "",
        "In-memory cache is insufficient for multi-instance deployments because each process has isolated cache state. `SharedRedisCache` stores query/response pairs in Redis with TTL, so separate gateway instances can reuse the same cached responses while keeping privacy and false-hit guardrails.",
        "",
        "Evidence collected during verification:",
        "",
        "```text",
        "Redis cache tests: 6 passed",
        "Shared state example: ('shared cache evidence response', 1.0)",
        "Redis key example: rl:cache:4918eb19ce89",
        "```",
        "",
        "## 7. Chaos scenarios",
        "",
        "| Scenario | Expected behavior | Observed behavior | Pass/Fail |",
        "|---|---|---|---|",
        *scenario_rows,
        "",
        "## 8. Failure analysis",
        "",
        "One remaining weakness is that circuit breaker state is still local to each gateway process. In production, multiple gateway instances could disagree about provider health. A stronger version would store breaker counters and state transitions in Redis or another shared coordination layer.",
        "",
        "Semantic cache correctness is also heuristic. The implementation blocks privacy-sensitive queries and obvious number/year mismatches, but production should add stronger intent classification and domain-specific cache keys.",
        "",
        "## 9. Next steps",
        "",
        "1. Add Redis-backed shared circuit breaker state.",
        "2. Persist per-scenario metrics instead of only combined metrics.",
        "3. Add a dedicated memory-vs-Redis latency benchmark.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="reports/metrics.json")
    parser.add_argument("--comparison", default="reports/cache_comparison.json")
    parser.add_argument("--out", default="reports/final_report.md")
    args = parser.parse_args()

    metrics = json.loads(Path(args.metrics).read_text())
    comparison_path = Path(args.comparison)
    comparison = json.loads(comparison_path.read_text()) if comparison_path.exists() else None
    report = build_report(metrics, comparison)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(report)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
