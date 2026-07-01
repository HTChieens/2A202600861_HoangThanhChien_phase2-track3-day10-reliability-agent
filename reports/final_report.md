# Day 10 Reliability Report

## 1. Architecture summary

This project implements a reliability layer for an LLM gateway. Requests check the semantic cache first. Cache misses are routed through provider-specific circuit breakers, then through the provider fallback chain. If every provider path fails, the gateway returns a static degraded response.

```
User Request
    |
    v
[ReliabilityGateway]
    |
    v
[Semantic Cache] ---- HIT ----> Return cached response
    |
   MISS
    |
    v
[Circuit Breaker: primary] ---> FakeLLMProvider primary
    |
    v
[Circuit Breaker: backup] ----> FakeLLMProvider backup
    |
    v
[Static fallback message]
```

## 2. Configuration

| Setting | Value | Reason |
|---|---:|---|
| failure_threshold | 3 | Opens a circuit after repeated failures without reacting to a single transient error. |
| reset_timeout_seconds | 2 | Keeps recovery visible in local chaos runs. |
| success_threshold | 1 | One successful half-open probe closes the circuit in this lab. |
| cache TTL | 300 seconds | Reuses repeated lab prompts while bounding staleness. |
| similarity_threshold | 0.92 | Conservative threshold to reduce false semantic hits. |
| load_test requests | 100 per scenario | Produces useful metrics without making the lab too slow. |
| cache backend | memory by default; Redis supported | Memory is fast locally; Redis enables shared cache state. |

## 3. SLO definitions

| SLI | SLO target | Actual value | Met? |
|---|---|---:|---|
| Availability | >= 99% | 99.33% | Yes |
| Latency P95 | < 2500 ms | 306.90 ms | Yes |
| Fallback success rate | >= 95% | 97.10% | Yes |
| Cache hit rate | >= 10% | 60.33% | Yes |
| Recovery time | < 5000 ms | 2455.09 ms | Yes |

## 4. Metrics

Metrics from `reports/metrics.json`:

| Metric | Value |
|---|---:|
| total_requests | 300 |
| availability | 0.9933 |
| error_rate | 0.0067 |
| latency_p50_ms | 0.0 |
| latency_p95_ms | 306.9 |
| latency_p99_ms | 317.54 |
| fallback_success_rate | 0.971 |
| cache_hit_rate | 0.6033 |
| circuit_open_count | 7 |
| recovery_time_ms | 2455.0864696502686 |
| estimated_cost | 0.052382 |
| estimated_cost_saved | 0.181 |

## 5. Cache comparison

The comparison artifact in `reports/cache_comparison.json` was used for the no-cache baseline.

| Metric | Without cache | With cache | Delta |
|---|---:|---:|---|
| latency_p50_ms | 274.61 ms | 0 ms | -274.61 ms |
| latency_p95_ms | 317.13 ms | 306.9 ms | -10.23 ms |
| estimated_cost | 0.122702 | 0.052382 | -0.07032 |
| cache_hit_rate | 0 | 0.6033 | +0.6033 |
| availability | 0.9733 | 0.9933 | +0.02 |
| circuit_open_count | 24 | 7 | -17 |

## 6. Redis shared cache

In-memory cache is insufficient for multi-instance deployments because each process has isolated cache state. `SharedRedisCache` stores query/response pairs in Redis with TTL, so separate gateway instances can reuse the same cached responses while keeping privacy and false-hit guardrails.

Evidence collected during verification:

```text
Redis cache tests: 6 passed
Shared state example: ('shared cache evidence response', 1.0)
Redis key example: rl:cache:4918eb19ce89
```

## 7. Chaos scenarios

| Scenario | Expected behavior | Observed behavior | Pass/Fail |
|---|---|---|---|
| primary_timeout_100 | Primary fails 100%; backup should serve requests and circuit should open. | Scenario status: pass. | Pass |
| primary_flaky_50 | Primary is flaky; gateway should mix primary, fallback, and circuit protection. | Scenario status: pass. | Pass |
| all_healthy | Baseline run should mostly use primary/cache with limited fallback. | Scenario status: pass. | Pass |

## 8. Failure analysis

One remaining weakness is that circuit breaker state is still local to each gateway process. In production, multiple gateway instances could disagree about provider health. A stronger version would store breaker counters and state transitions in Redis or another shared coordination layer.

Semantic cache correctness is also heuristic. The implementation blocks privacy-sensitive queries and obvious number/year mismatches, but production should add stronger intent classification and domain-specific cache keys.

## 9. Next steps

1. Add Redis-backed shared circuit breaker state.
2. Persist per-scenario metrics instead of only combined metrics.
3. Add a dedicated memory-vs-Redis latency benchmark.
