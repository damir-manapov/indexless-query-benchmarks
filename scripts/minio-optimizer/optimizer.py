#!/usr/bin/env python3
"""
MinIO Configuration Optimizer using Bayesian Optimization (Optuna).

This script:
1. Suggests MinIO configurations using Optuna's TPE sampler
2. Deploys configuration via Terraform
3. Runs warp benchmark
4. Records results and feeds back to optimizer
5. Repeats until n_trials reached

Usage:
    python optimizer.py --trials 20 --benchmark-vm-ip 81.177.222.139
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import optuna
from optuna.samplers import TPESampler

# Configuration space
CONFIG_SPACE = {
    "nodes": [2],  # Fixed at 2 due to IP quota
    "cpu_per_node": [2, 4, 8, 12],
    "ram_per_node": [8, 16, 32, 64],
    "drives_per_node": [3],  # Fixed at 3 (hardcoded in terraform block_device)
    "drive_size_gb": [100, 200, 400],
    "drive_type": ["fast", "universal"],
}

TERRAFORM_DIR = Path(__file__).parent.parent.parent / "terraform"
RESULTS_FILE = Path(__file__).parent / "results.json"


@dataclass
class BenchmarkResult:
    config: dict
    get_mib_s: float
    put_mib_s: float
    total_mib_s: float
    get_obj_s: float
    put_obj_s: float
    total_obj_s: float
    duration_s: float
    error: str | None = None


def run_command(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a command and return exit code, stdout, stderr."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def update_tfvars(config: dict) -> None:
    """Update terraform.tfvars with new MinIO configuration."""
    tfvars_path = TERRAFORM_DIR / "terraform.tfvars"
    
    with open(tfvars_path) as f:
        content = f.read()
    
    # Update MinIO-specific variables
    replacements = {
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
            # Append if not found
            content += f"\n{replacement}\n"
    
    with open(tfvars_path, "w") as f:
        f.write(content)


def deploy_minio(config: dict) -> bool:
    """Deploy MinIO cluster with given configuration."""
    print(f"  Deploying MinIO: {config}")
    
    update_tfvars(config)
    
    # Taint MinIO resources to force recreation
    taint_resources = [
        "openstack_compute_instance_v2.minio[0]",
        "openstack_compute_instance_v2.minio[1]",
        "openstack_blockstorage_volume_v3.minio_boot[0]",
        "openstack_blockstorage_volume_v3.minio_boot[1]",
    ]
    
    # Add data volume taints based on drive count
    for i in range(config["drives_per_node"] * 2):
        taint_resources.append(f"openstack_blockstorage_volume_v3.minio_data[{i}]")
    
    for resource in taint_resources:
        run_command(["terraform", "taint", resource], cwd=TERRAFORM_DIR)
    
    # Apply
    code, stdout, stderr = run_command(
        ["terraform", "apply", "-auto-approve"],
        cwd=TERRAFORM_DIR,
    )
    
    if code != 0:
        print(f"  Terraform apply failed: {stderr}")
        return False
    
    # Wait for MinIO to be ready
    print("  Waiting for MinIO to initialize (90s)...")
    time.sleep(90)
    
    return True


def run_warp_benchmark(vm_ip: str, minio_ip: str = "10.0.0.10") -> BenchmarkResult | None:
    """Run warp benchmark and parse results."""
    print("  Running warp benchmark...")
    
    warp_cmd = f"""warp mixed \
        --host={minio_ip}:9000 \
        --access-key=minioadmin \
        --secret-key=minioadmin123 \
        --autoterm \
        --json"""
    
    ssh_cmd = ["ssh", f"root@{vm_ip}", warp_cmd]
    
    start_time = time.time()
    code, stdout, stderr = run_command(ssh_cmd)
    duration = time.time() - start_time
    
    if code != 0:
        print(f"  Warp failed: {stderr}")
        return None
    
    return parse_warp_output(stdout, duration)


def parse_warp_output(output: str, duration: float) -> BenchmarkResult | None:
    """Parse warp benchmark output."""
    # Parse the text output for metrics
    result = {
        "get_mib_s": 0.0,
        "put_mib_s": 0.0,
        "total_mib_s": 0.0,
        "get_obj_s": 0.0,
        "put_obj_s": 0.0,
        "total_obj_s": 0.0,
    }
    
    # Patterns for parsing warp output
    patterns = {
        "get": r"Report: GET.*?Average: ([\d.]+) MiB/s, ([\d.]+) obj/s",
        "put": r"Report: PUT.*?Average: ([\d.]+) MiB/s, ([\d.]+) obj/s",
        "total": r"Report: Total.*?Average: ([\d.]+) MiB/s, ([\d.]+) obj/s",
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, output, re.DOTALL)
        if match:
            result[f"{key}_mib_s"] = float(match.group(1))
            result[f"{key}_obj_s"] = float(match.group(2))
    
    return BenchmarkResult(
        config={},
        duration_s=duration,
        **result,
    )


def save_result(result: BenchmarkResult, config: dict, trial_number: int) -> None:
    """Save benchmark result to JSON file."""
    results = []
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            results = json.load(f)
    
    results.append({
        "trial": trial_number,
        "timestamp": datetime.now().isoformat(),
        "config": config,
        "get_mib_s": result.get_mib_s,
        "put_mib_s": result.put_mib_s,
        "total_mib_s": result.total_mib_s,
        "get_obj_s": result.get_obj_s,
        "put_obj_s": result.put_obj_s,
        "total_obj_s": result.total_obj_s,
        "duration_s": result.duration_s,
        "error": result.error,
    })
    
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)


def calculate_cost(config: dict) -> float:
    """Estimate hourly cost for the configuration (rough Selectel pricing)."""
    nodes = config.get("nodes", 2)
    cpu = config["cpu_per_node"]
    ram = config["ram_per_node"]
    drives = config["drives_per_node"]
    drive_size = config["drive_size_gb"]
    drive_type = config["drive_type"]
    
    # Rough pricing per node (RUB/hour, very approximate)
    cpu_cost = cpu * 0.5
    ram_cost = ram * 0.1
    
    drive_multiplier = {"fast": 0.01, "universal": 0.005, "basic": 0.002}
    storage_cost = drives * drive_size * drive_multiplier.get(drive_type, 0.01)
    
    return nodes * (cpu_cost + ram_cost + storage_cost)


def objective(trial: optuna.Trial, vm_ip: str) -> float:
    """Optuna objective function."""
    config = {
        "nodes": 2,  # Fixed
        "cpu_per_node": trial.suggest_categorical("cpu_per_node", CONFIG_SPACE["cpu_per_node"]),
        "ram_per_node": trial.suggest_categorical("ram_per_node", CONFIG_SPACE["ram_per_node"]),
        "drives_per_node": 3,  # Fixed (hardcoded in terraform)
        "drive_size_gb": trial.suggest_categorical("drive_size_gb", CONFIG_SPACE["drive_size_gb"]),
        "drive_type": trial.suggest_categorical("drive_type", CONFIG_SPACE["drive_type"]),
    }
    
    print(f"\nTrial {trial.number}: {config}")
    
    # Deploy
    if not deploy_minio(config):
        return 0.0  # Failed deployment
    
    # Benchmark
    result = run_warp_benchmark(vm_ip)
    if result is None:
        return 0.0  # Failed benchmark
    
    result.config = config
    save_result(result, config, trial.number)
    
    # Objective: maximize throughput per cost
    cost = calculate_cost(config)
    score = result.total_mib_s / cost if cost > 0 else 0
    
    print(f"  Result: {result.total_mib_s:.1f} MiB/s, Cost: {cost:.2f}, Score: {score:.2f}")
    
    return result.total_mib_s  # Or use score for cost-efficiency


def main():
    parser = argparse.ArgumentParser(description="MinIO Configuration Optimizer")
    parser.add_argument("--trials", type=int, default=10, help="Number of trials")
    parser.add_argument("--benchmark-vm-ip", required=True, help="Benchmark VM IP")
    parser.add_argument("--study-name", default="minio-optimization", help="Optuna study name")
    args = parser.parse_args()
    
    print(f"Starting MinIO optimization with {args.trials} trials")
    print(f"Benchmark VM: {args.benchmark_vm_ip}")
    print(f"Terraform dir: {TERRAFORM_DIR}")
    print(f"Results file: {RESULTS_FILE}")
    print()
    
    # Create study with TPE sampler (good for hyperparameter optimization)
    study = optuna.create_study(
        study_name=args.study_name,
        direction="maximize",
        sampler=TPESampler(seed=42),
    )
    
    study.optimize(
        lambda trial: objective(trial, args.benchmark_vm_ip),
        n_trials=args.trials,
        show_progress_bar=True,
    )
    
    print("\n" + "=" * 60)
    print("OPTIMIZATION COMPLETE")
    print("=" * 60)
    print(f"Best trial: {study.best_trial.number}")
    print(f"Best config: {study.best_trial.params}")
    print(f"Best throughput: {study.best_trial.value:.1f} MiB/s")
    
    # Print all trials
    print("\nAll trials:")
    for trial in study.trials:
        if trial.value:
            print(f"  Trial {trial.number}: {trial.value:.1f} MiB/s - {trial.params}")


if __name__ == "__main__":
    main()
