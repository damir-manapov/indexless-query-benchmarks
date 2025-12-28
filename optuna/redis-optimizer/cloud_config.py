"""Cloud configuration for Redis optimizer."""

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
    cpu_cost=0.5,  # ~₽45/month per vCPU = ~$0.5/hr
    ram_cost=0.2,  # ~₽180/month per GB = ~$0.2/hr
    disk_cost_multipliers={
        "fast": 0.015,  # SSD
        "universal": 0.008,  # Hybrid
        "basic": 0.004,  # HDD
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


def get_config_space(cloud: str) -> dict:
    """Get configuration search space for a cloud."""
    # Common config space for Redis
    return {
        "mode": ["single", "sentinel"],
        "cpu_per_node": [2, 4, 8],
        "ram_per_node": [4, 8, 16, 32],
        "maxmemory_policy": ["allkeys-lru", "volatile-lru"],
        "io_threads": [1, 2, 4],
        "persistence": ["none", "rdb"],
    }
