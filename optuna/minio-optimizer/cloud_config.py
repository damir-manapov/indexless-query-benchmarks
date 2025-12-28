"""Cloud provider configurations for the optimizer."""

from dataclasses import dataclass
from pathlib import Path


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
    # Cost factors (relative, for comparison)
    cpu_cost: float
    ram_cost: float
    disk_cost_multipliers: dict[str, float]


# Base path for terraform configs
TERRAFORM_BASE = Path(__file__).parent.parent.parent / "terraform"


CLOUD_CONFIGS: dict[str, CloudConfig] = {
    "selectel": CloudConfig(
        name="selectel",
        terraform_dir=TERRAFORM_BASE / "selectel",
        disk_types=["fast", "universal", "basic"],
        instance_resource="openstack_compute_instance_v2.minio",
        boot_volume_resource="openstack_blockstorage_volume_v3.minio_boot",
        data_volume_resource="openstack_blockstorage_volume_v3.minio_data",
        network_port_resource="openstack_networking_port_v2.minio",
        cpu_cost=0.5,
        ram_cost=0.1,
        disk_cost_multipliers={"fast": 0.01, "universal": 0.005, "basic": 0.002},
    ),
    "timeweb": CloudConfig(
        name="timeweb",
        terraform_dir=TERRAFORM_BASE / "timeweb",
        disk_types=["nvme", "ssd", "hdd"],
        instance_resource="twc_server.minio",
        boot_volume_resource=None,  # Timeweb doesn't use separate boot volumes
        data_volume_resource="twc_server_disk.minio_data",
        network_port_resource=None,  # Timeweb handles networking differently
        cpu_cost=0.4,  # Slightly cheaper
        ram_cost=0.08,
        disk_cost_multipliers={"nvme": 0.012, "ssd": 0.008, "hdd": 0.003},
    ),
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
