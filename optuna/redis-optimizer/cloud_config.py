"""Cloud configuration for Redis optimizer."""

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from pricing import get_cloud_pricing

TERRAFORM_DIR = Path(__file__).parent.parent.parent / "terraform"


@dataclass
class CloudConfig:
    """Cloud provider configuration."""

    name: str
    terraform_dir: Path
    disk_types: list[str]
    cpu_cost: float  # Cost per vCPU per month
    ram_cost: float  # Cost per GB RAM per month
    disk_cost_multipliers: dict[str, float] = field(default_factory=dict)


def _make_config(
    name: str, terraform_subdir: str, disk_types: list[str]
) -> CloudConfig:
    """Create CloudConfig using common pricing."""
    pricing = get_cloud_pricing(name)
    return CloudConfig(
        name=name,
        terraform_dir=TERRAFORM_DIR / terraform_subdir,
        disk_types=disk_types,
        cpu_cost=pricing.cpu_cost,
        ram_cost=pricing.ram_cost,
        disk_cost_multipliers=pricing.disk_cost_multipliers,
    )


# Cloud configs using common pricing
SELECTEL_CONFIG = _make_config("selectel", "selectel", ["fast", "universal", "basic"])
TIMEWEB_CONFIG = _make_config("timeweb", "timeweb", ["nvme", "hdd"])


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
