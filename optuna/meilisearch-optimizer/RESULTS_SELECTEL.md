# Meilisearch Benchmark Results - SELECTEL

Generated: 2026-01-03 01:06:52

## Results

| # | CPU | RAM | Disk | Mem MB | Thr | QPS | p50 (ms) | p95 (ms) | p99 (ms) | Idx (s) |
|--:|----:|----:|------|-------:|----:|----:|---------:|---------:|---------:|--------:|
| 1 | 4 | 32 | fast | 0 | 0 | 658.7 | 1.0 | 3.0 | 0.0 | 14.4 |
| 2 | 4 | 32 | universal | 0 | 0 | 638.7 | 2.0 | 3.0 | 0.0 | 18.3 |

## Best Configurations

- **Best by QPS:** 658.7 QPS — `4cpu/32gb/fast`
- **Best by p95 latency:** 3.0ms — `4cpu/32gb/universal`
- **Best by indexing time:** 14.4s — `4cpu/32gb/fast`
