# Optuna Optimizers

Bayesian optimization for cloud infrastructure configurations using [Optuna](https://optuna.org/).

## Optimizers

| Optimizer                                       | Target                    | Benchmark Tool    |
| ----------------------------------------------- | ------------------------- | ----------------- |
| [meilisearch-optimizer](meilisearch-optimizer/) | Meilisearch search engine | k6                |
| [minio-optimizer](minio-optimizer/)             | MinIO distributed storage | warp              |
| [postgres-optimizer](postgres-optimizer/)       | PostgreSQL database       | pgbench           |
| [redis-optimizer](redis-optimizer/)             | Redis cache               | memtier_benchmark |

## Setup

```bash
cd optuna
uv sync
```

## Usage

```bash
# Meilisearch optimizer
uv run python meilisearch-optimizer/optimizer.py --cloud selectel --mode infra --trials 10

# MinIO optimizer
uv run python minio-optimizer/optimizer.py --cloud selectel --trials 10

# Redis optimizer
uv run python redis-optimizer/optimizer.py --cloud selectel --trials 10

# PostgreSQL optimizer
uv run python postgres-optimizer/optimizer.py --cloud selectel --mode config --trials 10

# Show results and export to markdown
uv run python minio-optimizer/optimizer.py --cloud selectel --show-results
```

## Supported Clouds

- **Selectel** - OpenStack-based, ru-7 region
- **Timeweb** - TWC API, ru-1 location

## Check

```bash
./check.sh  # ruff format, lint, pyright
```
