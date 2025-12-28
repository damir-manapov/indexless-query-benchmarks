# MinIO Configuration Optimizer

Bayesian optimization for finding the best MinIO cluster configuration using Optuna.

## How It Works

1. **Optuna suggests** a configuration (CPU, RAM, drives, drive type)
2. **Terraform deploys** the MinIO cluster with that config
3. **Warp benchmarks** the cluster
4. **Results logged** to `results_{cloud}.json`
5. **Optuna learns** from results and suggests the next config
6. **Repeat** until trials exhausted

## Self-Sufficient Design

The optimizer is fully self-sufficient and handles:

- **No infrastructure** → Creates benchmark VM and MinIO cluster from scratch
- **Stale state** → Detects orphaned Terraform state and auto-clears it
- **Unreachable VMs** → Validates VMs via SSH before using them
- **Volume resize limitations** → Destroys MinIO between trials (OpenStack can't shrink volumes)
- **Resource conflicts** → Uses unique naming to avoid conflicts

## Supported Clouds

| Cloud    | Terraform Dir         | Disk Types             |
| -------- | --------------------- | ---------------------- |
| Selectel | `terraform/selectel/` | fast, universal, basic |
| Timeweb  | `terraform/timeweb/`  | nvme                   |

## Setup

```bash
cd optuna/minio-optimizer
uv sync
```

## Usage

```bash
# Run optimization on Selectel (5 trials, destroy at end)
uv run python optimizer_multicloud.py --cloud selectel --trials 5

# Run on Timeweb, keep infrastructure after
uv run python optimizer_multicloud.py --cloud timeweb --trials 10 --no-destroy

# Resume a previous study (uses cached results)
uv run python optimizer_multicloud.py --cloud selectel --trials 20
```

### From Scratch (Full Self-Sufficiency Test)

```bash
# Clear everything and start fresh
cd ../../terraform/selectel
terraform destroy -auto-approve
rm -f terraform.tfstate terraform.tfstate.backup
cd ../../optuna/minio-optimizer
rm -f study.db results_selectel.json

# Run - it will create everything from scratch
uv run python optimizer_multicloud.py --cloud selectel --trials 5
```

## Configuration Space

Configuration space varies by cloud (defined in `cloud_config.py`):

### Selectel

| Parameter       | Values                 | Notes                 |
| --------------- | ---------------------- | --------------------- |
| nodes           | 1, 2, 4                | Number of MinIO nodes |
| cpu_per_node    | 2, 4, 8                | vCPU per MinIO node   |
| ram_per_node    | 4, 8, 16, 32           | GB per node           |
| drives_per_node | 1, 2, 4                | Drives per node       |
| drive_size_gb   | 100, 200               | Size per drive        |
| drive_type      | fast, universal, basic | SSD tier              |

### Timeweb

| Parameter       | Values       | Notes                 |
| --------------- | ------------ | --------------------- |
| nodes           | 1, 2, 4      | Number of MinIO nodes |
| cpu_per_node    | 2, 4, 8      | vCPU per MinIO node   |
| ram_per_node    | 4, 8, 16, 32 | GB per node           |
| drives_per_node | 1, 2, 4      | Drives per node       |
| drive_size_gb   | 100, 200     | Size per drive        |
| drive_type      | nvme         | Only NVMe available   |

## Erasure Coding

MinIO requires at least 4 drives for erasure coding. EC level = total_drives / 2.

| Config | Total Drives | EC Level | Fault Tolerance |
| ------ | ------------ | -------- | --------------- |
| 1×1    | 1            | 0        | None            |
| 2×1    | 2            | 0        | None            |
| 4×1    | 4            | 2        | 2 failures      |
| 1×4    | 4            | 2        | 2 failures      |
| 2×4    | 8            | 4        | 4 failures      |
| 4×4    | 16           | 8        | 8 failures      |

## Sample Results (Selectel, Dec 2025)

| Config                         | Throughput | Cost/hr | Efficiency |
| ------------------------------ | ---------- | ------- | ---------- |
| 2×2CPU×4GB, 1×200GB fast       | 351 MiB/s  | $6.80   | 51.6       |
| 1×4CPU×32GB, 4×100GB universal | 412 MiB/s  | $7.20   | 57.2       |

Best found: **1 node, 4 CPU, 32GB RAM, 4×100GB universal** → 412 MiB/s @ $7.20/hr

## Output

Results are saved to `results_{cloud}.json` (e.g., `results_selectel.json`):

```json
[
  {
    "trial": 0,
    "timestamp": "2025-12-28T09:32:28.859435",
    "cloud": "selectel",
    "config": {
      "nodes": 2,
      "cpu_per_node": 2,
      "ram_per_node": 4,
      "drives_per_node": 1,
      "drive_size_gb": 200,
      "drive_type": "fast"
    },
    "total_drives": 2,
    "cost_per_hour": 6.8,
    "cost_efficiency": 51.63,
    "total_mib_s": 351.07,
    "get_mib_s": 302.47,
    "put_mib_s": 50.55,
    "duration_s": 192.79,
    "error": null,
    "system_baseline": {
      "fio": {
        "rand_read_iops": 12500,
        "rand_write_iops": 7500,
        "rand_read_lat_ms": 0.32,
        "rand_write_lat_ms": 0.53,
        "seq_read_mib_s": 450,
        "seq_write_mib_s": 380
      },
      "sysbench": {
        "cpu_events_per_sec": 1250,
        "mem_mib_per_sec": 8500
      }
    }
  }
]
```

### System Baseline Metrics

Before each warp benchmark, system baseline tests run on the MinIO node:

#### Disk Performance (fio)

| Metric              | Description                           |
| ------------------- | ------------------------------------- |
| `rand_read_iops`    | Random 4K read IOPS                   |
| `rand_write_iops`   | Random 4K write IOPS                  |
| `rand_read_lat_ms`  | Random read latency (ms)              |
| `rand_write_lat_ms` | Random write latency (ms)             |
| `seq_read_mib_s`    | Sequential 1M read bandwidth (MiB/s)  |
| `seq_write_mib_s`   | Sequential 1M write bandwidth (MiB/s) |

#### CPU & Memory (sysbench)

| Metric               | Description                        |
| -------------------- | ---------------------------------- |
| `cpu_events_per_sec` | CPU prime number events per second |
| `mem_mib_per_sec`    | Memory throughput (MiB/s)          |

This helps correlate MinIO throughput with underlying hardware performance.

## Notes

- Each trial takes ~5-7 minutes (deploy + baseline + warp benchmark + destroy)
- 10 trials ≈ 50-70 minutes
- Cost per trial: ~$0.10-0.50 depending on config
- The optimizer maximizes total throughput (MiB/s)
- Optuna study persisted in `study.db` (SQLite) for resumption
- Cloud-specific results allow comparing Selectel vs Timeweb
