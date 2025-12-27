#!/usr/bin/env python3
"""
Multi-Cloud MinIO Configuration Optimizer using Bayesian Optimization (Optuna).

Supports both Selectel and Timeweb Cloud providers.

Usage:
    python optimizer_multicloud.py --cloud timeweb --trials 10 --benchmark-vm-ip 1.2.3.4
    python optimizer_multicloud.py --cloud selectel --trials 10 --benchmark-vm-ip 1.2.3.4
"""

import argparse
import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import optuna
from optuna.samplers import TPESampler
from optuna.trial import TrialState

from cloud_config import CloudConfig, get_cloud_config, get_config_space

RESULTS_DIR = Path(__file__).parent
STUDY_DB = RESULTS_DIR / "study.db"


def results_file(cloud: str) -> Path:
    """Get results file path for a cloud."""
    return RESULTS_DIR / f"results_{cloud}.json"


@dataclass
class BenchmarkResult:
    config: dict
    get_mib_s: float = 0.0
    put_mib_s: float = 0.0
    total_mib_s: float = 0.0
    get_obj_s: float = 0.0
    put_obj_s: float = 0.0
    total_obj_s: float = 0.0
    duration_s: float = 0.0
    gen_rows: int = 0
    gen_duration_s: float = 0.0
    gen_rows_per_sec: float = 0.0
    gen_batch_durations: list[float] | None = None
    error: str | None = None


def run_command(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a command and return exit code, stdout, stderr."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def config_to_key(config: dict) -> str:
    """Convert config dict to a hashable key for deduplication."""
    return json.dumps(
        {
            "nodes": config["nodes"],
            "cpu_per_node": config["cpu_per_node"],
            "ram_per_node": config["ram_per_node"],
            "drives_per_node": config["drives_per_node"],
            "drive_size_gb": config["drive_size_gb"],
            "drive_type": config["drive_type"],
        },
        sort_keys=True,
    )


def load_results(cloud: str) -> list[dict[str, Any]]:
    """Load results from results file."""
    path = results_file(cloud)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def find_cached_result(config: dict, cloud: str) -> dict | None:
    """Find a cached result for the given config."""
    target_key = config_to_key(config)
    for result in load_results(cloud):
        if config_to_key(result["config"]) == target_key:
            return result
    return None


def update_tfvars_selectel(config: dict, terraform_dir: Path) -> None:
    """Update terraform.tfvars for Selectel."""
    tfvars_path = terraform_dir / "terraform.tfvars"
    
    with open(tfvars_path) as f:
        content = f.read()

    replacements = {
        r"minio_node_count\s*=\s*\d+": f"minio_node_count    = {config['nodes']}",
        r"minio_node_cpu\s*=\s*\d+": f"minio_node_cpu      = {config['cpu_per_node']}",
        r"minio_node_ram_gb\s*=\s*\d+": f"minio_node_ram_gb   = {config['ram_per_node']}",
        r"minio_drives_per_node\s*=\s*\d+": f"minio_drives_per_node = {config['drives_per_node']}",
        r"minio_drive_size_gb\s*=\s*\d+": f"minio_drive_size_gb = {config['drive_size_gb']}",
        r"minio_drive_type\s*=\s*\"[^\"]+\"": f'minio_drive_type    = "{config["drive_type"]}"',
    }

    for pattern, replacement in replacements.items():
        if re.search(pattern, content):
            content = re.sub(pattern, replacement, content)
        else:
            content += f"\n{replacement}\n"

    with open(tfvars_path, "w") as f:
        f.write(content)


def taint_resources_selectel(config: dict, terraform_dir: Path) -> None:
    """Taint Selectel resources to force recreation."""
    taint_resources = []
    
    for i in range(config["nodes"]):
        taint_resources.append(f"openstack_compute_instance_v2.minio[{i}]")
        taint_resources.append(f"openstack_blockstorage_volume_v3.minio_boot[{i}]")
        taint_resources.append(f"openstack_networking_port_v2.minio[{i}]")

    total_drives = config["nodes"] * config["drives_per_node"]
    for i in range(total_drives):
        taint_resources.append(f"openstack_blockstorage_volume_v3.minio_data[{i}]")

    for resource in taint_resources:
        run_command(["terraform", "taint", resource], cwd=terraform_dir)


def taint_resources_timeweb(config: dict, terraform_dir: Path) -> None:
    """Taint Timeweb resources to force recreation."""
    taint_resources = []
    
    for i in range(config["nodes"]):
        taint_resources.append(f"twc_server.minio[{i}]")

    total_drives = config["nodes"] * config["drives_per_node"]
    for i in range(total_drives):
        taint_resources.append(f"twc_server_disk.minio_data[{i}]")

    for resource in taint_resources:
        run_command(["terraform", "taint", resource], cwd=terraform_dir)


def deploy_minio(config: dict, cloud_config: CloudConfig) -> bool:
    """Deploy MinIO cluster with given configuration."""
    print(f"  Deploying MinIO on {cloud_config.name}: {config}")
    
    terraform_dir = cloud_config.terraform_dir
    
    # Build variables for terraform apply
    tf_vars = {
        "minio_enabled": "true",
        "minio_node_count": str(config["nodes"]),
        "minio_node_cpu": str(config["cpu_per_node"]),
        "minio_node_ram_gb": str(config["ram_per_node"]),
        "minio_drives_per_node": str(config["drives_per_node"]),
        "minio_drive_size_gb": str(config["drive_size_gb"]),
    }
    
    # Build -var arguments
    var_args = []
    for key, value in tf_vars.items():
        var_args.extend(["-var", f"{key}={value}"])
    
    # For Selectel, also update tfvars file
    if cloud_config.name == "selectel":
        update_tfvars_selectel(config, terraform_dir)
        taint_resources_selectel(config, terraform_dir)
    else:
        # For Timeweb, use -var for all including drive_type
        var_args.extend(["-var", f"minio_drive_type={config['drive_type']}"])
        taint_resources_timeweb(config, terraform_dir)
    
    # Apply
    cmd = ["terraform", "apply", "-auto-approve"] + var_args
    code, stdout, stderr = run_command(cmd, cwd=terraform_dir)

    if code != 0:
        print(f"  Terraform apply failed: {stderr}")
        return False

    print("  Waiting for MinIO to initialize (90s)...")
    time.sleep(90)
    return True


def run_warp_benchmark(vm_ip: str, minio_ip: str = "10.0.0.10") -> BenchmarkResult | None:
    """Run warp benchmark and parse results."""
    print("  Running warp benchmark...")

    warp_cmd = (
        f"warp mixed "
        f"--host={minio_ip}:9000 "
        f"--access-key=minioadmin "
        f"--secret-key=minioadmin123 "
        f"--get-distrib 60 "
        f"--stat-distrib 25 "
        f"--put-distrib 10 "
        f"--delete-distrib 5 "
        f"--autoterm 2>&1"
    )

    start_time = time.time()
    code, stdout, stderr = run_command(["ssh", f"root@{vm_ip}", warp_cmd])
    duration = time.time() - start_time

    output = stdout + stderr
    if code != 0:
        print(f"  Warp failed: {output[:500]}")
        return None

    return parse_warp_output(output, duration)


def parse_warp_output(output: str, duration: float) -> BenchmarkResult:
    """Parse warp benchmark output."""
    result = {
        "get_mib_s": 0.0, "put_mib_s": 0.0, "total_mib_s": 0.0,
        "get_obj_s": 0.0, "put_obj_s": 0.0, "total_obj_s": 0.0,
    }

    output = " ".join(output.split())

    patterns = {
        "get": r"Report:\s*GET.*?Average:\s*([\d.]+)\s*MiB/s,\s*([\d.]+)\s*obj/s",
        "put": r"Report:\s*PUT.*?Average:\s*([\d.]+)\s*MiB/s,\s*([\d.]+)\s*obj/s",
        "total": r"Report:\s*Total.*?Average:\s*([\d.]+)\s*MiB/s,\s*([\d.]+)\s*obj/s",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, output, re.DOTALL | re.IGNORECASE)
        if match:
            result[f"{key}_mib_s"] = float(match.group(1))
            result[f"{key}_obj_s"] = float(match.group(2))

    return BenchmarkResult(
        config={},
        get_mib_s=result["get_mib_s"],
        put_mib_s=result["put_mib_s"],
        total_mib_s=result["total_mib_s"],
        get_obj_s=result["get_obj_s"],
        put_obj_s=result["put_obj_s"],
        total_obj_s=result["total_obj_s"],
        duration_s=duration,
    )


def calculate_cost(config: dict, cloud_config: CloudConfig) -> float:
    """Estimate hourly cost for the configuration."""
    nodes = config["nodes"]
    cpu = config["cpu_per_node"]
    ram = config["ram_per_node"]
    drives = config["drives_per_node"]
    drive_size = config["drive_size_gb"]
    drive_type = config["drive_type"]

    cpu_cost = cpu * cloud_config.cpu_cost
    ram_cost = ram * cloud_config.ram_cost
    disk_mult = cloud_config.disk_cost_multipliers.get(drive_type, 0.01)
    storage_cost = drives * drive_size * disk_mult

    return nodes * (cpu_cost + ram_cost + storage_cost)


def save_result(
    result: BenchmarkResult, 
    config: dict, 
    trial_number: int,
    cloud: str,
    cloud_config: CloudConfig,
) -> None:
    """Save benchmark result to JSON file."""
    results = load_results(cloud)

    total_drives = config["nodes"] * config["drives_per_node"]
    cost = calculate_cost(config, cloud_config)
    cost_efficiency = result.total_mib_s / cost if cost > 0 else 0

    results.append({
        "trial": trial_number,
        "timestamp": datetime.now().isoformat(),
        "cloud": cloud,
        "config": config,
        "total_drives": total_drives,
        "cost_per_hour": cost,
        "cost_efficiency": cost_efficiency,
        "total_mib_s": result.total_mib_s,
        "get_mib_s": result.get_mib_s,
        "put_mib_s": result.put_mib_s,
        "duration_s": result.duration_s,
        "error": result.error,
    })

    with open(results_file(cloud), "w") as f:
        json.dump(results, f, indent=2)


def objective(
    trial: optuna.Trial,
    cloud: str,
    cloud_config: CloudConfig,
    vm_ip: str,
) -> float:
    """Optuna objective function."""
    config_space = get_config_space(cloud)
    
    config = {
        "nodes": trial.suggest_categorical("nodes", config_space["nodes"]),
        "cpu_per_node": trial.suggest_categorical("cpu_per_node", config_space["cpu_per_node"]),
        "ram_per_node": trial.suggest_categorical("ram_per_node", config_space["ram_per_node"]),
        "drives_per_node": trial.suggest_categorical("drives_per_node", config_space["drives_per_node"]),
        "drive_size_gb": trial.suggest_categorical("drive_size_gb", config_space["drive_size_gb"]),
        "drive_type": trial.suggest_categorical("drive_type", config_space["drive_type"]),
    }

    print(f"\nTrial {trial.number} [{cloud}]: {config}")

    # Check cache
    cached = find_cached_result(config, cloud)
    if cached:
        print(f"  Using cached result: {cached['total_mib_s']:.1f} MiB/s")
        return cached["total_mib_s"]

    # Deploy
    if not deploy_minio(config, cloud_config):
        return 0.0

    # Run benchmark
    result = run_warp_benchmark(vm_ip)
    if result is None:
        return 0.0

    result.config = config
    save_result(result, config, trial.number, cloud, cloud_config)

    cost = calculate_cost(config, cloud_config)
    print(f"  Result: {result.total_mib_s:.1f} MiB/s, Cost: {cost:.2f}")

    return result.total_mib_s


def main():
    parser = argparse.ArgumentParser(description="Multi-Cloud MinIO Optimizer")
    parser.add_argument(
        "--cloud", 
        choices=["selectel", "timeweb"], 
        required=True,
        help="Cloud provider",
    )
    parser.add_argument("--trials", type=int, default=10, help="Number of trials")
    parser.add_argument("--benchmark-vm-ip", required=True, help="Benchmark VM IP")
    parser.add_argument("--study-name", default=None, help="Optuna study name (default: minio-{cloud})")
    args = parser.parse_args()

    cloud_config = get_cloud_config(args.cloud)
    study_name = args.study_name or f"minio-{args.cloud}"

    print(f"Starting MinIO optimization on {args.cloud.upper()}")
    print(f"Trials: {args.trials}")
    print(f"Benchmark VM: {args.benchmark_vm_ip}")
    print(f"Terraform dir: {cloud_config.terraform_dir}")
    print(f"Results file: {results_file(args.cloud)}")
    print(f"Disk types: {cloud_config.disk_types}")
    print()

    storage = f"sqlite:///{STUDY_DB}"
    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        direction="maximize",
        sampler=TPESampler(seed=42),
        load_if_exists=True,
    )

    existing_trials = len(study.trials)
    if existing_trials > 0:
        print(f"Resuming study with {existing_trials} existing trials")
        if study.best_trial:
            print(f"Current best: {study.best_trial.value:.1f} MiB/s")
    print()

    study.optimize(
        lambda trial: objective(trial, args.cloud, cloud_config, args.benchmark_vm_ip),
        n_trials=args.trials,
        show_progress_bar=True,
    )

    print("\n" + "=" * 60)
    print(f"OPTIMIZATION COMPLETE ({args.cloud.upper()})")
    print("=" * 60)
    print(f"Best trial: {study.best_trial.number}")
    print(f"Best config: {study.best_trial.params}")
    print(f"Best throughput: {study.best_trial.value:.1f} MiB/s")


if __name__ == "__main__":
    main()
