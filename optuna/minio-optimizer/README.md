# MinIO Configuration Optimizer

Bayesian optimization for finding the best MinIO cluster configuration using Optuna.

## How It Works

1. **Optuna suggests** a configuration (CPU, RAM, drives, drive type)
2. **Terraform deploys** the MinIO cluster with that config
3. **Warp benchmarks** the cluster
4. **Results logged** to `results.json`
5. **Optuna learns** from results and suggests the next config
6. **Repeat** until trials exhausted

## Setup

```bash
cd scripts/minio-optimizer
uv sync
```

## Usage

```bash
# Make sure terraform is initialized
cd ../../terraform
terraform init

# Run optimization (10 trials)
cd ../scripts/minio-optimizer
uv run python optimizer.py --trials 10 --benchmark-vm-ip 81.177.222.139

# More trials for better exploration
uv run python optimizer.py --trials 20 --benchmark-vm-ip 81.177.222.139
```

## Configuration Space

| Parameter       | Values            | Notes                    |
| --------------- | ----------------- | ------------------------ |
| nodes           | 1, 2, 3, 4, 6     | Number of MinIO nodes    |
| cpu_per_node    | 2, 4, 8, 12       | vCPU per MinIO node      |
| ram_per_node    | 8, 16, 32, 64     | GB per node              |
| drives_per_node | 1, 2, 3, 4        | Drives per node          |
| drive_size_gb   | 100, 200, 400     | Size per drive           |
| drive_type      | fast, universal   | SSD tier                 |

Total: ~1920 possible configurations (5×4×4×4×3×2)

## Erasure Coding Levels

EC level is automatically calculated and tracked:

| Nodes | Drives/Node | Total | EC Level | Fault Tolerance         |
|-------|-------------|-------|----------|-------------------------|
| 1     | 1           | 1     | 0        | None (single drive)     |
| 2     | 1           | 2     | 0        | None (no EC)            |
| 3     | 1           | 3     | 0        | None (no EC)            |
| 4     | 1           | 4     | 2        | 2 drive/node failures   |
| 6     | 1           | 6     | 3        | 3 drive/node failures   |
| 1     | 2           | 2     | 0        | None (no EC)            |
| 1     | 4           | 4     | 2        | 2 drive failures        |
| 2     | 2           | 4     | 2        | 2 drive failures        |
| 2     | 3           | 6     | 3        | 3 drive failures        |
| 2     | 4           | 8     | 4        | 4 drive failures        |
| 4     | 4           | 16    | 8        | 8 drive failures        |

## Output

Results are saved to `results.json`:

```json
[
  {
    "trial": 0,
    "timestamp": "2024-12-24T10:00:00",
    "config": {
      "nodes": 2,
      "cpu_per_node": 8,
      "ram_per_node": 32,
      "drives_per_node": 3,
      "drive_size_gb": 200,
      "drive_type": "fast"
    },
    "total_drives": 6,
    "ec_level": 3,
    "get_mib_s": 450.5,
    "put_mib_s": 150.2,
    "total_mib_s": 600.7,
    "duration_s": 45.3
  }
]
```

## Notes

- Each trial takes ~3-5 minutes (deploy + benchmark + cleanup)
- 20 trials ≈ 1-2 hours
- Cost per trial: ~$0.50-2.00 depending on config
- The optimizer maximizes total throughput (MiB/s)
