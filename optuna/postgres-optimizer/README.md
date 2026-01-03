# PostgreSQL Configuration Optimizer

Bayesian optimization for finding the best PostgreSQL configuration using Optuna.

## How It Works

1. **Optuna suggests** a configuration (mode, CPU, RAM, shared_buffers, work_mem, etc.)
2. **Terraform deploys** PostgreSQL single-node or Patroni cluster
3. **pgbench** runs TPC-B-like workload
4. **Results logged** to `results.json`
5. **Optuna learns** from results and suggests the next config
6. **Repeat** until trials exhausted

## Optimization Modes

| Mode   | Description                                                            |
| ------ | ---------------------------------------------------------------------- |
| infra  | Tune VM specs (CPU, RAM, disk) - creates new VM per trial              |
| config | Tune postgresql.conf on fixed host - reconfigures existing VM (faster) |
| full   | Two-phase: infra optimization first, then config on best host          |

## Deployment Modes

| Mode    | Nodes | Description                                |
| ------- | ----- | ------------------------------------------ |
| single  | 1     | Single PostgreSQL 18 instance at 10.0.0.30 |
| cluster | 3     | Patroni + etcd HA cluster at 10.0.0.30-32  |

## Setup

```bash
cd optuna
uv sync
```

## Usage

```bash
# Tune VM specs (infrastructure optimization)
uv run python postgres-optimizer/optimizer.py --cloud timeweb --mode infra --trials 10

# Tune postgresql.conf on fixed 8cpu/32gb host (config optimization)
uv run python postgres-optimizer/optimizer.py --cloud timeweb --mode config --cpu 8 --ram 32 --trials 50

# Full optimization (infra first, then config on best host)
uv run python postgres-optimizer/optimizer.py --cloud timeweb --mode full --trials 20

# Optimize for latency instead of TPS
uv run python postgres-optimizer/optimizer.py --cloud timeweb --mode config --metric latency_avg_ms --trials 20

# Keep infrastructure after optimization
uv run python postgres-optimizer/optimizer.py --cloud timeweb --mode config --trials 10 --no-destroy

# Show all benchmark results
uv run python postgres-optimizer/optimizer.py --cloud timeweb --show-results

# Export results to markdown
uv run python postgres-optimizer/optimizer.py --cloud timeweb --export-md
```

### From Scratch

```bash
# Clear everything and start fresh
cd terraform/timeweb
terraform destroy -auto-approve
rm -f terraform.tfstate terraform.tfstate.backup
cd ../../optuna
rm -f postgres-optimizer/study.db postgres-optimizer/results.json

# Run - it will create everything from scratch
uv run python postgres-optimizer/optimizer.py --cloud timeweb --mode config --trials 5
```

## Configuration Space

### Infrastructure (--mode infra)

| Parameter    | Values           | Notes               |
| ------------ | ---------------- | ------------------- |
| mode         | single, cluster  | Deployment topology |
| cpu          | 2, 4, 8, 16      | vCPU per node       |
| ram_gb       | 4, 8, 16, 32, 64 | GB per node         |
| disk_type    | nvme, ssd, hdd   | Storage type        |
| disk_size_gb | 50, 100, 200     | Disk size in GB     |

### PostgreSQL Config (--mode config)

| Parameter                       | Values                  | Notes                          |
| ------------------------------- | ----------------------- | ------------------------------ |
| shared_buffers_pct              | 15, 20, 25, 30, 35, 40  | % of RAM for shared buffers    |
| effective_cache_size_pct        | 50, 60, 70, 75          | % of RAM for cache size hint   |
| work_mem_mb                     | 4, 16, 32, 64, 128, 256 | Per-operation memory           |
| maintenance_work_mem_mb         | 64, 128, 256, 512, 1024 | Maintenance operations memory  |
| max_connections                 | 50, 100, 200, 500       | Max concurrent connections     |
| random_page_cost                | 1.1, 1.5, 2.0, 4.0      | Random I/O cost estimate       |
| effective_io_concurrency        | 100, 200, 500           | Concurrent I/O operations      |
| wal_buffers_mb                  | 16, 32, 64, 128         | WAL buffer size                |
| max_wal_size_gb                 | 1, 2, 4, 8              | Max WAL size before checkpoint |
| checkpoint_completion_target    | 0.7, 0.9                | Checkpoint spread factor       |
| max_worker_processes            | 2, 4, 8, 16             | Background worker processes    |
| max_parallel_workers_per_gather | 0, 2, 4                 | Parallel query workers         |

## Metrics

| Metric          | Direction | Description             |
| --------------- | --------- | ----------------------- |
| tps             | Maximize  | Transactions per second |
| latency_avg_ms  | Minimize  | Average latency in ms   |
| cost_efficiency | Maximize  | TPS per $/hr            |

### Trial Timings

Each trial records phase timings in `results.json`:

- `terraform_s` - Infrastructure provisioning time
- `pgbench_init_s` - pgbench initialization time
- `benchmark_s` - Benchmark execution time
- `trial_total_s` - Total trial duration

## Benchmark Workload

Uses `pgbench` with:

- **TPC-B-like** transaction mix (accounts, branches, tellers, history)
- Scale factor based on RAM (10 × RAM in GB, minimum 50)
- 60-second benchmark runs
- Clients = 4 × CPU cores

## Infrastructure

PostgreSQL nodes are deployed at:

- **Single mode**: 10.0.0.30
- **Cluster mode**: 10.0.0.30 (primary), 10.0.0.31-32 (replicas)

Benchmark VM at 10.0.0.100 connects from the same VPC to minimize network latency.
