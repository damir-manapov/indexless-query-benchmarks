# Meilisearch Benchmark Results - SELECTEL

Generated: 2026-01-03 20:29:57

## Results

| # | CPU | RAM | Disk | Mem MB | Thr | QPS | p50 (ms) | p95 (ms) | p99 (ms) | Idx (s) | ₽/mo | QPS/₽ |
|--:|----:|----:|------|-------:|----:|----:|---------:|---------:|---------:|--------:|-----:|------:|
| 1 | 32 | 64 | fast | auto | auto | 10494.2 | 2.0 | 3.0 | 0.0 | 7.9 | 36742 | 0.29 |
| 2 | 32 | 64 | fast | 2048 | 2 | 10416.8 | 2.0 | 3.0 | 5.0 | 16.0 | 36742 | 0.28 |
| 3 | 32 | 64 | fast | 512 | 4 | 10407.0 | 2.0 | 3.0 | 5.0 | 11.9 | 36742 | 0.28 |
| 4 | 32 | 64 | fast | 1024 | 4 | 10404.3 | 2.0 | 3.0 | 5.0 | 12.6 | 36742 | 0.28 |
| 5 | 32 | 64 | fast | 512 | 8 | 10284.7 | 2.0 | 4.0 | 6.0 | 10.1 | 36742 | 0.28 |
| 6 | 32 | 64 | universal | auto | auto | 10124.9 | 2.0 | 4.0 | 0.0 | 10.0 | 36642 | 0.28 |
| 7 | 16 | 32 | universal | auto | auto | 8397.1 | 5.0 | 7.0 | 0.0 | 9.8 | 18546 | 0.45 |
| 8 | 16 | 64 | universal | auto | auto | 8247.4 | 5.0 | 7.0 | 0.0 | 9.8 | 26162 | 0.32 |
| 9 | 8 | 32 | fast | auto | auto | 5159.1 | 14.0 | 18.0 | 0.0 | 9.8 | 13406 | 0.38 |
| 10 | 8 | 16 | fast | auto | auto | 4845.6 | 15.0 | 20.0 | 0.0 | 18.0 | 9598 | 0.50 |
| 11 | 4 | 16 | universal | auto | auto | 3101.7 | 31.0 | 37.0 | 0.0 | 15.9 | 6878 | 0.45 |
| 12 | 4 | 64 | fast | auto | auto | 2946.9 | 33.0 | 39.0 | 0.0 | 15.9 | 18402 | 0.16 |
| 13 | 2 | 16 | fast | auto | auto | 1736.9 | 63.0 | 75.0 | 0.0 | 24.1 | 5668 | 0.31 |
| 14 | 2 | 32 | universal | auto | auto | 1688.9 | 65.0 | 79.0 | 0.0 | 26.1 | 9376 | 0.18 |

## Best Configurations

- **Best by QPS:** 10494.2 QPS — `32cpu/64gb/fast mem=auto thr=auto`
- **Best by p95 latency:** 3.0ms — `32cpu/64gb/fast mem=auto thr=auto`
- **Best by indexing time:** 7.9s — `32cpu/64gb/fast mem=auto thr=auto`
- **Best by cost efficiency:** 0.50 QPS/₽ — `8cpu/16gb/fast mem=auto thr=auto`
