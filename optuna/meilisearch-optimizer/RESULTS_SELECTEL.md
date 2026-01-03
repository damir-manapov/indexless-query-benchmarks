# Meilisearch Benchmark Results - SELECTEL

Generated: 2026-01-03 10:23:26

## Results

| # | CPU | RAM | Disk | Mem MB | Thr | QPS | p50 (ms) | p95 (ms) | p99 (ms) | Idx (s) |
|--:|----:|----:|------|-------:|----:|----:|---------:|---------:|---------:|--------:|
| 1 | 8 | 16 | fast | 0 | 0 | 1293.5 | 2.0 | 3.0 | 0.0 | 10.1 |
| 2 | 8 | 8 | fast | 0 | 0 | 1291.1 | 2.0 | 3.0 | 0.0 | 9.7 |
| 3 | 8 | 16 | universal | 0 | 0 | 1289.2 | 2.0 | 3.0 | 0.0 | 11.8 |
| 4 | 4 | 32 | fast | 0 | 0 | 658.7 | 1.0 | 3.0 | 0.0 | 14.4 |
| 5 | 4 | 32 | universal | 0 | 0 | 638.7 | 2.0 | 3.0 | 0.0 | 18.3 |
| 6 | 2 | 16 | fast | 0 | 0 | 327.6 | 1.0 | 3.0 | 0.0 | 26.2 |
| 7 | 2 | 8 | fast | 0 | 0 | 326.8 | 1.0 | 3.0 | 0.0 | 26.2 |
| 8 | 2 | 4 | fast | 0 | 0 | 317.4 | 2.0 | 4.0 | 0.0 | 29.8 |

## Best Configurations

- **Best by QPS:** 1293.5 QPS — `8cpu/16gb/fast`
- **Best by p95 latency:** 3.0ms — `4cpu/32gb/universal`
- **Best by indexing time:** 9.7s — `8cpu/8gb/fast`
