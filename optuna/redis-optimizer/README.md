# Redis Configuration Optimizer

Bayesian optimization for finding the best Redis configuration using Optuna.

## How It Works

1. **Optuna suggests** a configuration (mode, CPU, RAM, eviction policy, io-threads, persistence)
2. **Terraform deploys** Redis single-node or Sentinel cluster
3. **memtier_benchmark** runs workload (80% GET, 20% SET)
4. **Results logged** to `results_{cloud}.json`
5. **Optuna learns** from results and suggests the next config
6. **Repeat** until trials exhausted

## Supported Modes

| Mode     | Nodes | Description                                         |
| -------- | ----- | --------------------------------------------------- |
| single   | 1     | Single Redis instance at 10.0.0.20                  |
| sentinel | 3     | 1 master + 2 replicas with Sentinel at 10.0.0.20-22 |

## Setup

```bash
cd optuna
uv sync
```

## Usage

```bash
# Optimize for ops/sec (higher is better)
uv run python redis-optimizer/optimizer.py --cloud selectel --trials 10 --metric ops_per_sec

# Optimize for p99 latency (lower is better)
uv run python redis-optimizer/optimizer.py --cloud selectel --trials 10 --metric p99_latency_ms

# Optimize for cost efficiency (ops/sec per $/hr)
uv run python redis-optimizer/optimizer.py --cloud selectel --trials 10 --metric cost_efficiency

# Keep infrastructure after optimization
uv run python redis-optimizer/optimizer.py --cloud selectel --trials 10 --no-destroy
```

### From Scratch

```bash
# Clear everything and start fresh
cd terraform/selectel
terraform destroy -auto-approve
rm -f terraform.tfstate terraform.tfstate.backup
cd ../../optuna
rm -f redis-optimizer/study.db redis-optimizer/results_selectel.json

# Run - it will create everything from scratch
uv run python redis-optimizer/optimizer.py --cloud selectel --trials 5
```

## Configuration Space

| Parameter        | Values                    | Notes                          |
| ---------------- | ------------------------- | ------------------------------ |
| mode             | single, sentinel          | Deployment topology            |
| cpu_per_node     | 2, 4, 8                   | vCPU per Redis node            |
| ram_per_node     | 4, 8, 16, 32              | GB per node                    |
| maxmemory_policy | allkeys-lru, volatile-lru | Eviction policy                |
| io_threads       | 1, 2, 4                   | Redis 6+ threaded I/O          |
| persistence      | none, rdb                 | Snapshotting (RDB) or disabled |

## Metrics

| Metric          | Direction | Description                   |
| --------------- | --------- | ----------------------------- |
| ops_per_sec     | Maximize  | Total operations per second   |
| p99_latency_ms  | Minimize  | 99th percentile latency in ms |
| cost_efficiency | Maximize  | ops/sec per $/hr              |

## Benchmark Workload

Uses `memtier_benchmark` with:

- **80% GET / 20% SET** ratio
- 16 threads, 50 connections per thread
- 10,000 requests per connection
- Random keys with 256-byte values

## Infrastructure

Redis nodes are deployed at:

- **Single mode**: 10.0.0.20
- **Sentinel mode**: 10.0.0.20 (master), 10.0.0.21-22 (replicas)

Benchmark VM connects from the same subnet to minimize network latency.
