"""Cloud provider configurations for the optimizer."""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from pricing import get_cloud_pricing


@dataclass
class CloudConfig:
    """Configuration for a cloud provider."""

    name: str
    terraform_dir: Path
    disk_types: list[str]
    # Terraform resource names for tainting
    instance_resource: str
    boot_volume_resource: str | None
    data_volume_resource: str
    network_port_resource: str | None
    # Cost factors (from common pricing)
    cpu_cost: float
    ram_cost: float
    disk_cost_multipliers: dict[str, float]


# Base path for terraform configs
TERRAFORM_BASE = Path(__file__).parent.parent.parent / "terraform"

# Terraform resource mappings per cloud
_TERRAFORM_RESOURCES = {
    "selectel": {
        "instance_resource": "openstack_compute_instance_v2.minio",
        "boot_volume_resource": "openstack_blockstorage_volume_v3.minio_boot",
        "data_volume_resource": "openstack_blockstorage_volume_v3.minio_data",
        "network_port_resource": "openstack_networking_port_v2.minio",
    },
    "timeweb": {
        "instance_resource": "twc_server.minio",
        "boot_volume_resource": None,
        "data_volume_resource": "twc_server_disk.minio_data",
        "network_port_resource": None,
    },
}

_DISK_TYPES = {
    "selectel": ["fast", "universal2", "universal", "basicssd", "basic"],
    "timeweb": ["nvme", "ssd", "hdd"],
}


def _make_config(name: str) -> CloudConfig:
    """Create CloudConfig using common pricing."""
    pricing = get_cloud_pricing(name)
    resources = _TERRAFORM_RESOURCES[name]
    return CloudConfig(
        name=name,
        terraform_dir=TERRAFORM_BASE / name,
        disk_types=_DISK_TYPES[name],
        instance_resource=resources["instance_resource"],
        boot_volume_resource=resources["boot_volume_resource"],
        data_volume_resource=resources["data_volume_resource"],
        network_port_resource=resources["network_port_resource"],
        cpu_cost=pricing.cpu_cost,
        ram_cost=pricing.ram_cost,
        disk_cost_multipliers=pricing.disk_cost_multipliers,
    )


CLOUD_CONFIGS: dict[str, CloudConfig] = {
    "selectel": _make_config("selectel"),
    "timeweb": _make_config("timeweb"),
}


def get_cloud_config(cloud: str) -> CloudConfig:
    """Get configuration for a cloud provider."""
    if cloud not in CLOUD_CONFIGS:
        raise ValueError(
            f"Unknown cloud: {cloud}. Available: {list(CLOUD_CONFIGS.keys())}"
        )
    return CLOUD_CONFIGS[cloud]


def get_config_space(cloud: str) -> dict:
    """Get configuration space for optimization."""
    config = get_cloud_config(cloud)

    return {
        "nodes": [1, 2, 3, 4],  # Reduced for cost control
        "cpu_per_node": [2, 4, 8],
        "ram_per_node": [4, 8, 16, 32],
        "drives_per_node": [1, 2, 3, 4],
        "drive_size_gb": [100, 200],
        "drive_type": config.disk_types,
    }
