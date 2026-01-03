"""Cloud pricing configuration.

Centralized pricing rates for all optimizers.
Update this file when cloud provider prices change.
"""

from dataclasses import dataclass, field


@dataclass
class CloudPricing:
    """Pricing rates for a cloud provider."""

    cpu_cost: float  # Cost per vCPU per month (₽)
    ram_cost: float  # Cost per GB RAM per month (₽)
    disk_cost_multipliers: dict[str, float] = field(default_factory=dict)


# Cloud pricing rates in rubles (₽) per month
# Based on https://selectel.ru/prices/ and https://timeweb.cloud/
# Consistent across all optimizers
CLOUD_PRICING: dict[str, CloudPricing] = {
    "selectel": CloudPricing(
        # Standard Line pricing (ru-9 pool, Jan 2026)
        # Derived from calculator: 2vCPU/4GB = 2263₽, extrapolated
        cpu_cost=655,  # ₽/vCPU/month
        ram_cost=238,  # ₽/GB/month
        disk_cost_multipliers={
            # Selectel disk types: https://docs.selectel.ru/cloud-servers/volumes/about-network-volumes/
            "fast": 39,  # ₽/GB/month - SSD Быстрый (NVMe)
            "universal2": 18,  # ₽/GB/month - SSD Универсальный v2 (+ IOPS billing)
            "universal": 18,  # ₽/GB/month - SSD Универсальный
            "basicssd": 9,  # ₽/GB/month - SSD Базовый
            "basic": 7,  # ₽/GB/month - HDD Базовый
        },
    ),
    "timeweb": CloudPricing(
        # Timeweb Cloud pricing (Jan 2026)
        # Derived from fixed tariffs: 1vCPU/1GB=477₽, 1vCPU/2GB=657₽, 2vCPU/2GB=882₽
        cpu_cost=220,  # ₽/vCPU/month (estimated)
        ram_cost=180,  # ₽/GB/month (657-477=180 for 1GB)
        disk_cost_multipliers={
            "nvme": 5,  # ₽/GB/month (estimated from tariffs)
            "ssd": 4,  # ₽/GB/month
            "hdd": 2,  # ₽/GB/month
        },
    ),
}


def get_cloud_pricing(cloud: str) -> CloudPricing:
    """Get pricing rates for a cloud provider."""
    if cloud not in CLOUD_PRICING:
        raise ValueError(
            f"Unknown cloud: {cloud}. Available: {list(CLOUD_PRICING.keys())}"
        )
    return CLOUD_PRICING[cloud]


# ============================================================================
# Cloud Constraints
# ============================================================================

# Minimum RAM (GB) required per vCPU count
# Based on cloud provider's Standard Line offerings
CLOUD_MIN_RAM: dict[str, dict[int, int]] = {
    "selectel": {
        # Selectel Standard Line constraints
        2: 2,  # 2 vCPU: min 2GB
        4: 4,  # 4 vCPU: min 4GB
        8: 8,  # 8 vCPU: min 8GB
        16: 32,  # 16 vCPU: min 32GB
        32: 64,  # 32 vCPU: min 64GB
    },
    "timeweb": {},  # No known constraints
}


def get_min_ram_for_cpu(cloud: str, cpu: int) -> int:
    """Get minimum RAM (GB) required for given CPU count."""
    constraints = CLOUD_MIN_RAM.get(cloud, {})
    return constraints.get(cpu, 0)


def validate_infra_config(cloud: str, cpu: int, ram_gb: int) -> str | None:
    """Validate infrastructure config against cloud constraints.

    Returns error message if invalid, None if valid.
    """
    min_ram = get_min_ram_for_cpu(cloud, cpu)
    if ram_gb < min_ram:
        return f"{cpu} vCPU requires min {min_ram}GB RAM on {cloud}"
    return None


def filter_valid_ram(cloud: str, cpu: int, ram_options: list[int]) -> list[int]:
    """Filter RAM options to only those valid for the given CPU count.

    Use this to constrain Optuna's search space before suggesting,
    rather than pruning invalid configs after the fact.
    """
    min_ram = get_min_ram_for_cpu(cloud, cpu)
    valid = [r for r in ram_options if r >= min_ram]
    # Fallback to all options if no constraints or empty result
    return valid if valid else ram_options
