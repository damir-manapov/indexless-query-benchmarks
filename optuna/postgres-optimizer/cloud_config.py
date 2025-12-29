"""Cloud configuration for Postgres optimizer."""

from dataclasses import dataclass, field
from pathlib import Path

TERRAFORM_DIR = Path(__file__).parent.parent.parent / "terraform"


@dataclass
class CloudConfig:
    """Cloud provider configuration."""

    name: str
    terraform_dir: Path
    disk_types: list[str]
    cpu_cost: float  # Cost per vCPU per hour
    ram_cost: float  # Cost per GB RAM per hour
    disk_cost_multipliers: dict[str, float] = field(default_factory=dict)


# Selectel cloud config
SELECTEL_CONFIG = CloudConfig(
    name="selectel",
    terraform_dir=TERRAFORM_DIR / "selectel",
    disk_types=["fast", "universal", "basic"],
    cpu_cost=0.5,
    ram_cost=0.2,
    disk_cost_multipliers={
        "fast": 0.015,
        "universal": 0.008,
        "basic": 0.004,
    },
)

# Timeweb cloud config
TIMEWEB_CONFIG = CloudConfig(
    name="timeweb",
    terraform_dir=TERRAFORM_DIR / "timeweb",
    disk_types=["nvme", "hdd"],
    cpu_cost=0.4,
    ram_cost=0.15,
    disk_cost_multipliers={
        "nvme": 0.012,
        "hdd": 0.003,
    },
)


def get_cloud_config(cloud: str) -> CloudConfig:
    """Get cloud configuration by name."""
    configs = {
        "selectel": SELECTEL_CONFIG,
        "timeweb": TIMEWEB_CONFIG,
    }
    if cloud not in configs:
        raise ValueError(f"Unknown cloud: {cloud}. Available: {list(configs.keys())}")
    return configs[cloud]


def get_infra_search_space(cloud: str) -> dict:
    """Get infrastructure search space (VM specs)."""
    return {
        "mode": ["single", "cluster"],
        "cpu": [2, 4, 8, 16],
        "ram_gb": [4, 8, 16, 32, 64],
        "disk_type": ["nvme"] if cloud == "timeweb" else ["fast"],
        "disk_size_gb": [50, 100, 200],
    }


def get_config_search_space(ram_gb: int) -> dict:
    """Get Postgres config search space based on available RAM."""
    return {
        # Memory settings (percentages of RAM)
        "shared_buffers_pct": [15, 20, 25, 30, 35, 40],
        "effective_cache_size_pct": [50, 60, 70, 75],
        "work_mem_mb": [4, 16, 32, 64, 128, 256],
        "maintenance_work_mem_mb": [64, 128, 256, 512, 1024],
        # Connection settings
        "max_connections": [50, 100, 200, 500],
        # Planner settings
        "random_page_cost": [1.1, 1.5, 2.0, 4.0],
        "effective_io_concurrency": [1, 50, 100, 200],
        # WAL settings
        "wal_buffers_mb": [16, 32, 64, 128],
        "max_wal_size_gb": [1, 2, 4, 8],
        "checkpoint_completion_target": [0.5, 0.7, 0.9],
        # Workers
        "max_worker_processes": [2, 4, 8],
        "max_parallel_workers_per_gather": [0, 1, 2, 4],
    }
