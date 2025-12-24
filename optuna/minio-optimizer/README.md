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

| Parameter | Values | Notes |
|-----------|--------|-------|
| nodes | 2 (fixed) | Limited by floating IP quota |
| cpu_per_node | 2, 4, 8, 12 | vCPU per MinIO node |
| ram_per_node | 8, 16, 32, 64 | GB per node |
| drives_per_node | 3 (fixed) | Hardcoded in terraform |
| drive_size_gb | 100, 200, 400 | Size per drive |
| drive_type | fast, universal | SSD tier |

Total: ~32 possible configurations (4×4×3×2)

## Output

Results are saved to `results.json`:

```json
[
  {
    "trial": 0,
    "timestamp": "2024-12-24T10:00:00",
    "config": {
      "cpu_per_node": 8,
      "ram_per_node": 32,
      "drives_per_node": 3,
      "drive_size_gb": 200,
      "drive_type": "fast"
    },
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
