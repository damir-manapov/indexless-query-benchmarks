# Optuna Optimizers

Bayesian optimization for cloud infrastructure configurations using [Optuna](https://optuna.org/).

## Optimizers

| Optimizer | Target | Benchmark Tool |
|-----------|--------|----------------|
| [minio-optimizer](minio-optimizer/) | MinIO distributed storage | warp |
| [redis-optimizer](redis-optimizer/) | Redis cache | memtier_benchmark |

## Setup

```bash
cd optuna
uv sync
```

## Usage

```bash
# MinIO optimizer
uv run python minio-optimizer/optimizer.py --cloud selectel --trials 10

# Redis optimizer
uv run python redis-optimizer/optimizer.py --cloud selectel --trials 10
```

## Supported Clouds

- **Selectel** - OpenStack-based, ru-7 region
- **Timeweb** - TWC API, ru-1 location

## Check

```bash
./check.sh  # ruff format, lint, pyright
```
