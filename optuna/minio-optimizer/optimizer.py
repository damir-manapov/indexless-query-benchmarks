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

# Configuration space
CONFIG_SPACE = {
    "nodes": [1, 2, 3, 4, 6],  # Variable node count (1 = single node)
    "cpu_per_node": [2, 4, 8, 12],
    "ram_per_node": [8, 16, 32, 64],
    "drives_per_node": [1, 2, 3, 4],  # Variable drives per node
    "drive_size_gb": [100, 200, 400],
    "drive_type": ["fast", "universal"],
}


def calculate_ec_level(nodes: int, drives_per_node: int) -> int:
    """Calculate erasure coding level based on total drives.

    MinIO uses EC:N where N = total_drives // 2, but requires at least 4 drives.
    With fewer than 4 drives, EC is disabled (returns 0).
    """
    total_drives = nodes * drives_per_node
    if total_drives >= 4:
        return total_drives // 2
    return 0  # No erasure coding


TERRAFORM_DIR = Path(__file__).parent.parent.parent / "terraform"
RESULTS_FILE = Path(__file__).parent / "results.json"
STUDY_DB = Path(__file__).parent / "study.db"


def load_results() -> list[dict[str, Any]]:
    """Load all results from results.json."""
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return []


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


def find_cached_result(config: dict) -> dict | None:
    """Find a cached result for the given config."""
    target_key = config_to_key(config)
    for result in load_results():
        if config_to_key(result["config"]) == target_key:
            return result
    return None


def seed_study_from_results(study: optuna.Study) -> int:
    """Seed Optuna study with historical results from results.json."""
    results = load_results()
    if not results:
        return 0

    # Get existing trial configs to avoid duplicates
    existing_keys = set()
    for trial in study.trials:
        if trial.state == TrialState.COMPLETE:
            existing_keys.add(config_to_key(trial.params))

    seeded = 0
    for result in results:
        config = result["config"]
        key = config_to_key(config)

        if key in existing_keys:
            continue  # Already in study

        # Add historical trial
        try:
            study.add_trial(
                optuna.trial.create_trial(
                    params=config,
                    values=[result["total_mib_s"]],
                    state=TrialState.COMPLETE,
                )
            )
            existing_keys.add(key)
            seeded += 1
        except Exception as e:
            print(f"  Warning: Could not seed trial: {e}")

    return seeded


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
    # Data generation metrics (Trino/Iceberg ingestion)
    gen_rows: int = 0
    gen_duration_s: float = 0.0
    gen_rows_per_sec: float = 0.0
    gen_batch_durations: list[float] | None = None
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
            # Append if not found
            content += f"\n{replacement}\n"

    with open(tfvars_path, "w") as f:
        f.write(content)


def deploy_minio(config: dict) -> bool:
    """Deploy MinIO cluster with given configuration."""
    print(f"  Deploying MinIO: {config}")

    update_tfvars(config)

    # Taint MinIO resources to force recreation
    taint_resources = []

    # Taint all node instances and boot volumes
    for i in range(config["nodes"]):
        taint_resources.append(f"openstack_compute_instance_v2.minio[{i}]")
        taint_resources.append(f"openstack_blockstorage_volume_v3.minio_boot[{i}]")

    # Add data volume taints based on total drive count
    total_drives = config["nodes"] * config["drives_per_node"]
    for i in range(total_drives):
        taint_resources.append(f"openstack_blockstorage_volume_v3.minio_data[{i}]")

    # Also taint network ports
    for i in range(config["nodes"]):
        taint_resources.append(f"openstack_networking_port_v2.minio[{i}]")

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


def restart_trino(vm_ip: str) -> bool:
    """Restart Trino on benchmark VM to reconnect to new MinIO."""
    print("  Restarting Trino on benchmark VM...")

    # Restart compose with standalone-minio config
    restart_cmd = (
        "cd /root/indexless-query-benchmarks && "
        "pnpm compose:down 2>/dev/null; "
        "pnpm compose:up:trino:64gb:standalone-minio"
    )

    code, stdout, stderr = run_command(["ssh", f"root@{vm_ip}", restart_cmd])

    if code != 0:
        print(f"  Trino restart failed: {stderr}")
        return False

    # Wait for Trino to be ready
    print("  Waiting for Trino to start (30s)...")
    time.sleep(30)

    return True


def run_warp_benchmark(
    vm_ip: str, minio_ip: str = "10.0.0.10"
) -> BenchmarkResult | None:
    """Run warp benchmark and parse results."""
    print("  Running warp benchmark...")

    # Note: --json doesn't work well with mixed, use text output
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

    ssh_cmd = ["ssh", f"root@{vm_ip}", warp_cmd]

    start_time = time.time()
    code, stdout, stderr = run_command(ssh_cmd)
    duration = time.time() - start_time

    # Combine stdout and stderr since warp may output to either
    output = stdout + stderr

    if code != 0:
        print(f"  Warp failed: {output[:500]}")
        return None

    return parse_warp_output(output, duration)


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

    # Normalize output - remove extra whitespace from SSH line wrapping
    output = " ".join(output.split())

    # Patterns for parsing warp output (more flexible)
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

    # Debug output
    if result["total_mib_s"] == 0:
        print(f"  Warning: Could not parse warp output. Sample: {output[:200]}...")

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


def run_generation_benchmark(
    vm_ip: str,
    rows: int = 100_000_000,
    batch_size: int = 100_000_000,
) -> dict | None:
    """Run Trino data generation benchmark on the VM.

    Returns dict with gen_rows, gen_duration_s, gen_rows_per_sec, gen_batch_durations
    or None on failure.
    """
    print(f"  Running data generation benchmark ({rows:,} rows)...")

    # Run generation with JSON report output
    gen_cmd = (
        f"cd /root/indexless-query-benchmarks && "
        f"pnpm generate --trino -n {rows} -b {batch_size} --report 2>&1"
    )

    ssh_cmd = ["ssh", f"root@{vm_ip}", gen_cmd]

    start_time = time.time()
    code, stdout, stderr = run_command(ssh_cmd)
    total_duration = time.time() - start_time

    output = stdout + stderr

    if code != 0:
        print(f"  Generation exit code {code}, attempting to parse anyway...")
        print(f"  Last 500 chars: ...{output[-500:]}")

    # Parse the JSON report output
    # Look for the generation report JSON file path
    json_match = re.search(r"Generated JSON report: ([\w/\-\.]+)", output)
    if json_match:
        json_path = json_match.group(1)
        # The path is relative to project dir, make it absolute
        full_json_path = f"/root/indexless-query-benchmarks/{json_path}"
        # Read the JSON report from remote
        cat_cmd = ["ssh", f"root@{vm_ip}", f"cat {full_json_path}"]
        code, json_output, _ = run_command(cat_cmd)
        if code == 0:
            try:
                report = json.loads(json_output)
                db_result = next(
                    (
                        d
                        for d in report.get("databases", [])
                        if "Trino" in d["database"]
                    ),
                    None,
                )
                if db_result:
                    table = next(
                        (
                            t
                            for t in db_result.get("tables", [])
                            if t["table"] == "samples"
                        ),
                        None,
                    )
                    if table:
                        return {
                            "gen_rows": table["rows"],
                            "gen_duration_s": table["durationMs"] / 1000.0,
                            "gen_rows_per_sec": table["rowsPerSecond"],
                            "gen_batch_durations": [
                                d / 1000.0 for d in table.get("batchDurations", [])
                            ],
                        }
            except json.JSONDecodeError:
                print("  Warning: Could not parse generation report JSON")

    # Fallback: parse console output for rows/sec
    rows_match = re.search(r"Generated\s+([\d,]+)\s+total\s+rows", output)
    rate_match = re.search(r"([\d,]+)\s+rows/s", output.lower())

    if rows_match:
        gen_rows = int(rows_match.group(1).replace(",", ""))
        gen_rows_per_sec = (
            int(rate_match.group(1).replace(",", "")) if rate_match else 0
        )
        return {
            "gen_rows": gen_rows,
            "gen_duration_s": total_duration,
            "gen_rows_per_sec": gen_rows_per_sec,
            "gen_batch_durations": None,
        }

    print("  Warning: Could not parse generation output")
    return None


def save_result(result: BenchmarkResult, config: dict, trial_number: int) -> None:
    """Save benchmark result to JSON file."""
    results = []
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            results = json.load(f)

    ec_level = calculate_ec_level(config["nodes"], config["drives_per_node"])
    total_drives = config["nodes"] * config["drives_per_node"]
    cost = calculate_cost(config)
    cost_efficiency = result.total_mib_s / cost if cost > 0 else 0

    results.append(
        {
            "trial": trial_number,
            "timestamp": datetime.now().isoformat(),
            "config": config,
            "total_drives": total_drives,
            "ec_level": ec_level,
            "cost_per_hour": cost,
            "cost_efficiency": cost_efficiency,
            "get_mib_s": result.get_mib_s,
            "put_mib_s": result.put_mib_s,
            "total_mib_s": result.total_mib_s,
            "get_obj_s": result.get_obj_s,
            "put_obj_s": result.put_obj_s,
            "total_obj_s": result.total_obj_s,
            "duration_s": result.duration_s,
            "gen_rows": result.gen_rows,
            "gen_duration_s": result.gen_duration_s,
            "gen_rows_per_sec": result.gen_rows_per_sec,
            "gen_batch_durations": result.gen_batch_durations,
            "error": result.error,
        }
    )

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


def objective(
    trial: optuna.Trial,
    vm_ip: str,
    gen_rows: int = 100_000_000,
    gen_batch: int = 100_000_000,
) -> float:
    """Optuna objective function."""
    config = {
        "nodes": trial.suggest_categorical("nodes", CONFIG_SPACE["nodes"]),
        "cpu_per_node": trial.suggest_categorical(
            "cpu_per_node", CONFIG_SPACE["cpu_per_node"]
        ),
        "ram_per_node": trial.suggest_categorical(
            "ram_per_node", CONFIG_SPACE["ram_per_node"]
        ),
        "drives_per_node": trial.suggest_categorical(
            "drives_per_node", CONFIG_SPACE["drives_per_node"]
        ),
        "drive_size_gb": trial.suggest_categorical(
            "drive_size_gb", CONFIG_SPACE["drive_size_gb"]
        ),
        "drive_type": trial.suggest_categorical(
            "drive_type", CONFIG_SPACE["drive_type"]
        ),
    }

    print(f"\nTrial {trial.number}: {config}")

    # Check cache first - avoid re-running same config
    cached = find_cached_result(config)
    if cached:
        print(f"  Using cached result: {cached['total_mib_s']:.1f} MiB/s")
        return cached["total_mib_s"]

    # Deploy
    if not deploy_minio(config):
        return 0.0  # Failed deployment

    # Restart Trino to connect to new MinIO
    if gen_rows > 0:
        if not restart_trino(vm_ip):
            print("  Warning: Trino restart failed, generation may fail")

    # Skip warp benchmark - use generation as primary KPI
    # result = run_warp_benchmark(vm_ip)
    # if result is None:
    #     return 0.0  # Failed benchmark
    result = BenchmarkResult(config=config)

    # Data generation benchmark (Trino/Iceberg ingestion)
    if gen_rows > 0:
        gen_result = run_generation_benchmark(
            vm_ip, rows=gen_rows, batch_size=gen_batch
        )
        if gen_result:
            result.gen_rows = gen_result["gen_rows"]
            result.gen_duration_s = gen_result["gen_duration_s"]
            result.gen_rows_per_sec = gen_result["gen_rows_per_sec"]
            result.gen_batch_durations = gen_result["gen_batch_durations"]
        else:
            return 0.0  # Generation failed
    else:
        gen_result = None

    save_result(result, config, trial.number)

    # Objective: maximize generation throughput
    cost = calculate_cost(config)
    score = result.gen_rows_per_sec / cost if cost > 0 else 0

    print(
        f"  Result: {result.gen_rows_per_sec:,.0f} rows/sec, Cost: {cost:.2f}, Score: {score:.2f}"
    )

    return result.gen_rows_per_sec  # Use generation throughput as KPI


def main():
    parser = argparse.ArgumentParser(description="MinIO Configuration Optimizer")
    parser.add_argument("--trials", type=int, default=10, help="Number of trials")
    parser.add_argument("--benchmark-vm-ip", required=True, help="Benchmark VM IP")
    parser.add_argument(
        "--study-name", default="minio-optimization", help="Optuna study name"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable result caching (re-run all configs)",
    )
    parser.add_argument(
        "--gen-rows",
        type=int,
        default=100_000_000,
        help="Rows for generation benchmark (default: 100M, 0 to skip)",
    )
    parser.add_argument(
        "--gen-batch",
        type=int,
        default=100_000_000,
        help="Batch size for generation benchmark (default: 100M)",
    )
    args = parser.parse_args()

    print(f"Starting MinIO optimization with {args.trials} trials")
    print(f"Benchmark VM: {args.benchmark_vm_ip}")
    print(f"Terraform dir: {TERRAFORM_DIR}")
    print(f"Results file: {RESULTS_FILE}")
    print(f"Study database: {STUDY_DB}")
    if args.gen_rows > 0:
        print(f"Generation benchmark: {args.gen_rows:,} rows, {args.gen_batch:,} batch")
    else:
        print("Generation benchmark: disabled")
    print()

    # Create study with SQLite persistence
    storage = f"sqlite:///{STUDY_DB}"
    study = optuna.create_study(
        study_name=args.study_name,
        storage=storage,
        direction="maximize",
        sampler=TPESampler(seed=42),
        load_if_exists=True,  # Resume existing study
    )

    # Seed study from historical results
    seeded = seed_study_from_results(study)
    if seeded > 0:
        print(f"Seeded {seeded} historical trials from results.json")

    existing_trials = len(study.trials)
    if existing_trials > 0:
        print(f"Resuming study with {existing_trials} existing trials")
        if study.best_trial:
            print(f"Current best: {study.best_trial.value:,.0f} rows/s")
    print()

    study.optimize(
        lambda trial: objective(
            trial, args.benchmark_vm_ip, args.gen_rows, args.gen_batch
        ),
        n_trials=args.trials,
        show_progress_bar=True,
    )

    print("\n" + "=" * 60)
    print("OPTIMIZATION COMPLETE")
    print("=" * 60)
    print(f"Best trial: {study.best_trial.number}")
    print(f"Best config: {study.best_trial.params}")
    print(f"Best throughput: {study.best_trial.value:,.0f} rows/s")

    # Print all trials
    print("\nAll trials:")
    for trial in study.trials:
        if trial.value:
            print(f"  Trial {trial.number}: {trial.value:,.0f} rows/s - {trial.params}")


if __name__ == "__main__":
    main()
