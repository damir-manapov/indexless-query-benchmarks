# Meilisearch Benchmark Results - SELECTEL

Generated: 2026-01-03 09:21:19

## Results

| # | CPU | RAM | Disk | Mem MB | Thr | QPS | p50 (ms) | p95 (ms) | p99 (ms) | Idx (s) |
|--:|----:|----:|------|-------:|----:|----:|---------:|---------:|---------:|--------:|
| 1 | 8 | 16 | fast | 0 | 0 | 1293.5 | 2.0 | 3.0 | 0.0 | 10.1 |
| 2 | 4 | 32 | fast | 0 | 0 | 658.7 | 1.0 | 3.0 | 0.0 | 14.4 |
| 3 | 4 | 32 | universal | 0 | 0 | 638.7 | 2.0 | 3.0 | 0.0 | 18.3 |
| 4 | 2 | 4 | fast | 0 | 0 | 317.4 | 2.0 | 4.0 | 0.0 | 29.8 |

## Best Configurations

- **Best by QPS:** 1293.5 QPS — `8cpu/16gb/fast`
- **Best by p95 latency:** 3.0ms — `4cpu/32gb/universal`
- **Best by indexing time:** 10.1s — `8cpu/16gb/fast`
