# Redis Benchmark Results - SELECTEL

Generated: 2025-12-29 21:20:11

## Results

| # | Mode | Nodes | CPU | RAM | Policy | IO | Persist | Ops/s | p99 (ms) | $/hr | Efficiency |
|--:|------|------:|----:|----:|--------|---:|---------|------:|---------:|-----:|-----------:|
| 1 | sentinel | 3 | 2 | 8 | allkeys-lru | 1 | rdb | 117594 | 2.69 | 10.05 | 11701 |
| 2 | single | 1 | 2 | 16 | allkeys-lru | 2 | none | 85534 | 3.38 | 4.95 | 17280 |
| 3 | sentinel | 3 | 2 | 16 | allkeys-lru | 1 | rdb | 81348 | 3.92 | 14.85 | 5478 |
| 4 | sentinel | 3 | 4 | 4 | allkeys-lru | 2 | none | 78126 | 3.44 | 10.65 | 7336 |

## Best Configurations

- **Best by ops/sec:** 117594 ops/s — `sentinel 3×2cpu/8gb io=1 rdb`
- **Best by p99 latency:** 2.69ms — `sentinel 3×2cpu/8gb io=1 rdb`
- **Best by efficiency:** 17280 ops/$/hr — `single 1×2cpu/16gb io=2 none`
