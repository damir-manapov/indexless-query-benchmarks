#!/usr/bin/env python3
"""
Multi-Cloud MinIO Configuration Optimizer using Bayesian Optimization (Optuna).

Supports both Selectel and Timeweb Cloud providers.
Automatically creates benchmark VM if not provided.

Usage:
    python optimizer_multicloud.py --cloud timeweb --trials 5
    python optimizer_multicloud.py --cloud selectel --trials 10 --no-destroy
    python optimizer_multicloud.py --cloud timeweb --benchmark-vm-ip 1.2.3.4 --trials 10
"""

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import optuna
from optuna.samplers import TPESampler
from python_terraform import Terraform

from cloud_config import CloudConfig, get_cloud_config, get_config_space

RESULTS_DIR = Path(__file__).parent
STUDY_DB = RESULTS_DIR / "study.db"

# Available optimization metrics
METRICS = {
    "total_mib_s": "Total throughput (MiB/s)",
    "cost_efficiency": "Throughput per cost (MiB/s per $/hr)",
    "get_mib_s": "Read throughput (MiB/s)",
    "put_mib_s": "Write throughput (MiB/s)",
}


def get_metric_value(result: dict, metric: str) -> float:
    """Extract the optimization metric value from a result."""
    return result.get(metric, 0)


def results_file(cloud: str) -> Path:
    """Get results file path for a cloud."""
    return RESULTS_DIR / f"results_{cloud}.json"


@dataclass
class FioResult:
    """FIO benchmark results for disk baseline."""

    # Random 4K I/O
    rand_read_iops: float = 0.0
    rand_write_iops: float = 0.0
    rand_read_lat_ms: float = 0.0
    rand_write_lat_ms: float = 0.0
    # Sequential 1M I/O
    seq_read_mib_s: float = 0.0
    seq_write_mib_s: float = 0.0


@dataclass
class SysbenchResult:
    """Sysbench benchmark results for CPU and memory baseline."""

    # CPU benchmark
    cpu_events_per_sec: float = 0.0
    # Memory benchmark
    mem_mib_per_sec: float = 0.0


@dataclass
class SystemBaseline:
    """Combined system baseline metrics."""

    fio: FioResult | None = None
    sysbench: SysbenchResult | None = None


@dataclass
class TrialTimings:
    """Timing measurements for each phase of a trial."""

    minio_deploy_s: float = 0.0  # Terraform create MinIO cluster
    baseline_s: float = 0.0  # fio + sysbench tests
    benchmark_s: float = 0.0  # warp benchmark
    minio_destroy_s: float = 0.0  # Terraform destroy MinIO
    trial_total_s: float = 0.0  # End-to-end trial time


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
    error: str | None = None
    baseline: SystemBaseline | None = None
    timings: TrialTimings | None = None


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
    """Find a cached successful result for the given config.

    Returns None if:
    - No cached result exists
    - Cached result has error (failed trial)
    - Cached result has 0 throughput (benchmark failed)
    - Cached result is missing required metrics (system_baseline, timings)
    """
    target_key = config_to_key(config)
    for result in load_results(cloud):
        if config_to_key(result["config"]) == target_key:
            # Skip failed results - they should be retried
            if result.get("error"):
                return None
            if result.get("total_mib_s", 0) <= 0:
                return None
            # Skip results missing required metrics
            if not result.get("system_baseline"):
                return None
            if not result.get("timings"):
                return None
            return result
    return None


def run_ssh_command(vm_ip: str, command: str, timeout: int = 300) -> tuple[int, str]:
    """Run command on remote VM via SSH."""
    import subprocess

    result = subprocess.run(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=10",
            f"root@{vm_ip}",
            command,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout + result.stderr


def wait_for_vm_ready(vm_ip: str, timeout: int = 300) -> bool:
    """Wait for benchmark VM to be ready (cloud-init complete)."""
    print(f"  Waiting for VM {vm_ip} to be ready...")

    start = time.time()
    while time.time() - start < timeout:
        try:
            code, _ = run_ssh_command(
                vm_ip, "test -f /root/benchmark-ready", timeout=15
            )
            if code == 0:
                print("  VM is ready!")
                return True
        except Exception as e:
            print(f"  SSH not ready yet: {e}")
        time.sleep(10)

    print(f"  Warning: VM not ready after {timeout}s, continuing anyway...")
    return False


def get_terraform(cloud_config: CloudConfig) -> Terraform:
    """Get Terraform instance, initializing if needed."""
    tf_dir = str(cloud_config.terraform_dir)
    tf = Terraform(working_dir=tf_dir)

    # Check if init needed
    terraform_dir = cloud_config.terraform_dir / ".terraform"
    if not terraform_dir.exists():
        print(f"  Initializing Terraform in {tf_dir}...")
        ret_code, stdout, stderr = tf.init()
        if ret_code != 0:
            raise RuntimeError(f"Terraform init failed: {stderr}")

    return tf


def is_stale_state_error(stderr: str | None) -> bool:
    """Check if the error indicates stale terraform state."""
    if stderr is None:
        return False
    return "not found" in stderr.lower() or "404" in stderr


def clear_terraform_state(cloud_config: CloudConfig) -> None:
    """Clear Terraform state files to start fresh."""
    import os

    tf_dir = cloud_config.terraform_dir
    for f in ["terraform.tfstate", "terraform.tfstate.backup"]:
        path = tf_dir / f
        if path.exists():
            os.remove(path)
            print(f"  Removed stale state: {path}")


def validate_vm_exists(vm_ip: str) -> bool:
    """Check if VM is actually reachable (not just in state)."""
    try:
        code, _ = run_ssh_command(vm_ip, "echo ok", timeout=10)
        return code == 0
    except Exception:
        return False


def terraform_refresh_and_validate(tf: Terraform) -> bool:
    """Run terraform refresh and check if resources are valid."""
    ret_code, stdout, stderr = tf.refresh()
    # Check for "not found" errors indicating stale state
    if is_stale_state_error(stderr):
        return False
    return ret_code == 0


def get_tf_output(tf: Terraform, name: str) -> str | None:
    """Get terraform output value, handling different return formats."""
    try:
        # Use output_cmd to get raw output and parse it ourselves
        ret, out, err = tf.output_cmd(name)
        if ret != 0 or not out:
            return None
        # Output is JSON-formatted, strip quotes and newlines
        value = out.strip().strip('"')
        # Check if it's a valid value (not a warning message or null)
        if not value or value == "null" or value.startswith("╷") or "Warning" in value:
            return None
        return value
    except Exception:
        return None


def ensure_benchmark_vm(cloud_config: CloudConfig) -> str:
    """Ensure benchmark VM exists and return its IP."""
    print(f"\nChecking benchmark VM for {cloud_config.name}...")

    tf = get_terraform(cloud_config)

    # Check if VM already exists in state
    vm_ip = get_tf_output(tf, "benchmark_vm_ip")
    if vm_ip:
        # Validate that the VM is actually reachable
        print(f"  Found VM IP in state: {vm_ip}")
        if validate_vm_exists(vm_ip):
            print(f"  Benchmark VM verified and reachable: {vm_ip}")
            return vm_ip
        else:
            print("  VM in state is not reachable, checking if state is stale...")
            # Try to refresh and see if resources still exist
            if not terraform_refresh_and_validate(tf):
                print("  State is stale (resources deleted), clearing state...")
                clear_terraform_state(cloud_config)
                tf = get_terraform(cloud_config)  # Re-init after clearing state
            else:
                # Resources exist but VM not reachable yet, wait for it
                print("  Resources exist, waiting for VM to become ready...")
                if wait_for_vm_ready(vm_ip, timeout=180):
                    return vm_ip

    # Create VM only (explicitly disable MinIO to avoid terraform.tfvars override)
    print("  Creating benchmark VM...")
    tf_vars = {"minio_enabled": False}
    ret_code, stdout, stderr = tf.apply(skip_plan=True, var=tf_vars)

    if ret_code != 0:
        # Check if it's a stale state error
        if is_stale_state_error(stderr):
            print("  Stale state detected, clearing and retrying...")
            clear_terraform_state(cloud_config)
            tf = get_terraform(cloud_config)
            ret_code, stdout, stderr = tf.apply(skip_plan=True, var=tf_vars)

        if ret_code != 0:
            raise RuntimeError(f"Failed to create benchmark VM: {stderr}")

    # Get IP
    vm_ip = get_tf_output(tf, "benchmark_vm_ip")
    if not vm_ip:
        raise RuntimeError("Benchmark VM created but no IP returned")

    print(f"  Benchmark VM created: {vm_ip}")

    # Wait for VM to be ready
    wait_for_vm_ready(vm_ip)

    return vm_ip


def is_ip_conflict_error(stderr: str | None) -> bool:
    """Check if the error indicates IP/resource conflict (retryable)."""
    if stderr is None:
        return False
    stderr_lower = stderr.lower()
    # OpenStack (Selectel) IP conflicts
    if "IpAddressAlreadyAllocated" in stderr or "already allocated" in stderr_lower:
        return True
    # Timeweb resource conflicts
    if "conflict" in stderr_lower or "already exists" in stderr_lower:
        return True
    # Generic transient errors
    if "resource is busy" in stderr_lower or "try again" in stderr_lower:
        return True
    return False


def deploy_minio(
    config: dict, cloud_config: CloudConfig, max_retries: int = 3
) -> tuple[bool, float]:
    """Deploy MinIO cluster with given configuration. Returns (success, duration_s)."""
    print(f"  Deploying MinIO on {cloud_config.name}: {config}")
    start = time.time()

    tf = get_terraform(cloud_config)

    # Build variables for terraform apply
    tf_vars = {
        "minio_enabled": True,
        "minio_node_count": config["nodes"],
        "minio_node_cpu": config["cpu_per_node"],
        "minio_node_ram_gb": config["ram_per_node"],
        "minio_drives_per_node": config["drives_per_node"],
        "minio_drive_size_gb": config["drive_size_gb"],
        "minio_drive_type": config["drive_type"],
    }

    # Apply with retries for transient errors
    for attempt in range(max_retries):
        ret_code, stdout, stderr = tf.apply(skip_plan=True, var=tf_vars)

        if ret_code == 0:
            break

        # Check for stale state errors
        if is_stale_state_error(stderr):
            print("  Stale state detected, clearing and retrying...")
            clear_terraform_state(cloud_config)
            tf = get_terraform(cloud_config)
            continue

        # Check for IP conflict (OpenStack hasn't released ports yet)
        if is_ip_conflict_error(stderr):
            wait_time = 15 * (attempt + 1)  # 15s, 30s, 45s
            print(f"  IP conflict detected, waiting {wait_time}s for ports to release...")
            time.sleep(wait_time)
            continue

        # Unknown error
        print(f"  Terraform apply failed: {stderr}")
        return False, time.time() - start

    if ret_code != 0:
        print(f"  Terraform apply failed after {max_retries} retries: {stderr}")
        return False, time.time() - start

    print("  Waiting for MinIO to initialize (90s)...")
    time.sleep(90)
    duration = time.time() - start
    print(f"  MinIO deployed in {duration:.1f}s")
    return True, duration


def destroy_minio(cloud_config: CloudConfig) -> tuple[bool, float]:
    """Destroy MinIO cluster but keep benchmark VM. Returns (success, duration_s)."""
    print(f"  Destroying MinIO on {cloud_config.name}...")
    start = time.time()

    tf = get_terraform(cloud_config)

    # Apply with minio_enabled=false to destroy MinIO but keep VM
    ret_code, stdout, stderr = tf.apply(skip_plan=True, var={"minio_enabled": False})

    if ret_code != 0:
        # Handle stale state gracefully
        if is_stale_state_error(stderr):
            print("  Stale state detected during MinIO destroy, clearing state...")
            clear_terraform_state(cloud_config)
            return True, time.time() - start  # State cleared, nothing to destroy
        print(f"  Warning: MinIO destroy may have failed: {stderr}")
        return False, time.time() - start

    duration = time.time() - start
    print(f"  MinIO destroyed in {duration:.1f}s")
    return True, duration


def destroy_all(cloud_config: CloudConfig) -> bool:
    """Destroy all infrastructure."""
    print(f"\nDestroying all resources on {cloud_config.name}...")

    tf = get_terraform(cloud_config)

    # Use auto_approve for destroy (force is deprecated)
    ret_code, stdout, stderr = tf.destroy(auto_approve=True)

    if ret_code != 0:
        # Handle stale state - resources may already be gone
        if is_stale_state_error(stderr):
            print("  Resources already deleted, clearing stale state...")
            clear_terraform_state(cloud_config)
            return True
        print(f"  Warning: Destroy may have failed: {stderr}")
        return False

    print("  All resources destroyed.")
    return True


def run_warp_benchmark(
    vm_ip: str, minio_ip: str = "10.0.0.10"
) -> BenchmarkResult | None:
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
    try:
        code, output = run_ssh_command(vm_ip, warp_cmd, timeout=600)
    except Exception as e:
        print(f"  Warp failed: {e}")
        return None

    duration = time.time() - start_time

    if code != 0:
        print(f"  Warp failed: {output[:500]}")
        return None

    return parse_warp_output(output, duration)


def parse_warp_output(output: str, duration: float) -> BenchmarkResult:
    """Parse warp benchmark output."""
    result = {
        "get_mib_s": 0.0,
        "put_mib_s": 0.0,
        "total_mib_s": 0.0,
        "get_obj_s": 0.0,
        "put_obj_s": 0.0,
        "total_obj_s": 0.0,
    }

    # Parse new warp output format
    # Operation: GET, 70%, Concurrency: 20, Ran 29s.
    #  * Throughput: 305.61 MiB/s, 305.61 obj/s
    get_pattern = (
        r"Operation:\s*GET.*?Throughput:\s*([\d.]+)\s*MiB/s,\s*([\d.]+)\s*obj/s"
    )
    put_pattern = (
        r"Operation:\s*PUT.*?Throughput:\s*([\d.]+)\s*MiB/s,\s*([\d.]+)\s*obj/s"
    )
    total_pattern = r"Cluster Total:\s*([\d.]+)\s*MiB/s,\s*([\d.]+)\s*obj/s"

    get_match = re.search(get_pattern, output, re.DOTALL | re.IGNORECASE)
    if get_match:
        result["get_mib_s"] = float(get_match.group(1))
        result["get_obj_s"] = float(get_match.group(2))

    put_match = re.search(put_pattern, output, re.DOTALL | re.IGNORECASE)
    if put_match:
        result["put_mib_s"] = float(put_match.group(1))
        result["put_obj_s"] = float(put_match.group(2))

    total_match = re.search(total_pattern, output, re.DOTALL | re.IGNORECASE)
    if total_match:
        result["total_mib_s"] = float(total_match.group(1))
        result["total_obj_s"] = float(total_match.group(2))

    # Fallback: calculate total from GET + PUT if Cluster Total not found
    if result["total_mib_s"] == 0 and (
        result["get_mib_s"] > 0 or result["put_mib_s"] > 0
    ):
        result["total_mib_s"] = result["get_mib_s"] + result["put_mib_s"]
        result["total_obj_s"] = result["get_obj_s"] + result["put_obj_s"]

    if result["total_mib_s"] == 0:
        print(f"  Warning: Could not parse warp output. Sample: {output[:500]}...")

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


def run_fio_baseline(vm_ip: str, minio_ip: str = "10.0.0.10") -> FioResult | None:
    """Run fio on MinIO node to get disk baseline performance.

    Runs random 4K and sequential 1M tests on /data1 (MinIO data drive).
    """
    print("  Running fio disk baseline...")

    # SSH to MinIO node via benchmark VM and run fio
    # Test on /data1 which is the first MinIO data drive
    # Run both random 4K and sequential 1M tests
    fio_cmd = (
        f"ssh -o StrictHostKeyChecking=no root@{minio_ip} "
        f'"fio --name=random --directory=/data1 --rw=randrw --rwmixread=70 '
        f"--bs=4k --size=256M --numjobs=4 --runtime=20 --time_based "
        f"--name=sequential --directory=/data1 --rw=rw --rwmixread=70 "
        f"--bs=1M --size=512M --numjobs=1 --runtime=20 --time_based "
        f'--group_reporting --output-format=json 2>/dev/null" 2>/dev/null'
    )

    try:
        code, output = run_ssh_command(vm_ip, fio_cmd, timeout=120)
        if code != 0:
            print(f"  Fio failed with code {code}")
            return None

        return parse_fio_output(output)
    except Exception as e:
        print(f"  Fio failed: {e}")
        return None


def parse_fio_output(output: str) -> FioResult | None:
    """Parse fio JSON output with random and sequential tests."""
    try:
        # Find JSON in output (may have some stderr before it)
        json_start = output.find("{")
        if json_start == -1:
            print("  Warning: No JSON found in fio output")
            return None

        data = json.loads(output[json_start:])
        jobs = data.get("jobs", [])
        if not jobs:
            print("  Warning: No jobs in fio output")
            return None

        result = FioResult()

        for job in jobs:
            job_name = job.get("jobname", "")
            read_stats = job.get("read", {})
            write_stats = job.get("write", {})

            if "random" in job_name.lower():
                # Random 4K - get IOPS and latency
                result.rand_read_iops = read_stats.get("iops", 0)
                result.rand_write_iops = write_stats.get("iops", 0)
                read_lat_ns = read_stats.get("lat_ns", {}).get("mean", 0)
                write_lat_ns = write_stats.get("lat_ns", {}).get("mean", 0)
                result.rand_read_lat_ms = read_lat_ns / 1_000_000
                result.rand_write_lat_ms = write_lat_ns / 1_000_000
            elif "sequential" in job_name.lower():
                # Sequential 1M - get bandwidth
                read_bw_kib = read_stats.get("bw", 0)
                write_bw_kib = write_stats.get("bw", 0)
                result.seq_read_mib_s = read_bw_kib / 1024
                result.seq_write_mib_s = write_bw_kib / 1024

        print(
            f"  Fio: rand {result.rand_read_iops:.0f}/{result.rand_write_iops:.0f} IOPS, "
            f"seq {result.seq_read_mib_s:.0f}/{result.seq_write_mib_s:.0f} MiB/s"
        )

        return result
    except json.JSONDecodeError as e:
        print(f"  Warning: Failed to parse fio JSON: {e}")
        return None
    except Exception as e:
        print(f"  Warning: Failed to parse fio output: {e}")
        return None


def run_sysbench_baseline(
    vm_ip: str, minio_ip: str = "10.0.0.10"
) -> SysbenchResult | None:
    """Run sysbench on MinIO node to get CPU and memory baseline."""
    print("  Running sysbench CPU/memory baseline...")

    result = SysbenchResult()

    # CPU benchmark
    cpu_cmd = (
        f"ssh -o StrictHostKeyChecking=no root@{minio_ip} "
        f'"sysbench cpu --time=10 run 2>/dev/null" 2>/dev/null'
    )
    try:
        code, output = run_ssh_command(vm_ip, cpu_cmd, timeout=30)
        if code == 0:
            # Parse: events per second: 1234.56
            match = re.search(r"events per second:\s*([\d.]+)", output)
            if match:
                result.cpu_events_per_sec = float(match.group(1))
    except Exception as e:
        print(f"  CPU benchmark failed: {e}")

    # Memory benchmark
    mem_cmd = (
        f"ssh -o StrictHostKeyChecking=no root@{minio_ip} "
        f'"sysbench memory --memory-block-size=1M --memory-total-size=10G run 2>/dev/null" 2>/dev/null'
    )
    try:
        code, output = run_ssh_command(vm_ip, mem_cmd, timeout=30)
        if code == 0:
            # Parse: 1234.56 MiB/sec
            match = re.search(r"([\d.]+)\s*MiB/sec", output)
            if match:
                result.mem_mib_per_sec = float(match.group(1))
    except Exception as e:
        print(f"  Memory benchmark failed: {e}")

    print(
        f"  Sysbench: CPU {result.cpu_events_per_sec:.0f} events/s, "
        f"MEM {result.mem_mib_per_sec:.0f} MiB/s"
    )

    return result


def run_system_baseline(vm_ip: str, minio_ip: str = "10.0.0.10") -> SystemBaseline:
    """Run all system baseline benchmarks."""
    print("  Running system baseline benchmarks...")

    fio_result = run_fio_baseline(vm_ip, minio_ip)
    sysbench_result = run_sysbench_baseline(vm_ip, minio_ip)

    return SystemBaseline(fio=fio_result, sysbench=sysbench_result)


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

    # Build baseline metrics dict if available
    baseline_metrics = None
    if result.baseline:
        fio_metrics = None
        if result.baseline.fio:
            fio_metrics = {
                "rand_read_iops": result.baseline.fio.rand_read_iops,
                "rand_write_iops": result.baseline.fio.rand_write_iops,
                "rand_read_lat_ms": result.baseline.fio.rand_read_lat_ms,
                "rand_write_lat_ms": result.baseline.fio.rand_write_lat_ms,
                "seq_read_mib_s": result.baseline.fio.seq_read_mib_s,
                "seq_write_mib_s": result.baseline.fio.seq_write_mib_s,
            }
        sysbench_metrics = None
        if result.baseline.sysbench:
            sysbench_metrics = {
                "cpu_events_per_sec": result.baseline.sysbench.cpu_events_per_sec,
                "mem_mib_per_sec": result.baseline.sysbench.mem_mib_per_sec,
            }
        baseline_metrics = {
            "fio": fio_metrics,
            "sysbench": sysbench_metrics,
        }

    # Build timings dict if available
    timings_metrics = None
    if result.timings:
        timings_metrics = {
            "minio_deploy_s": result.timings.minio_deploy_s,
            "baseline_s": result.timings.baseline_s,
            "benchmark_s": result.timings.benchmark_s,
            "minio_destroy_s": result.timings.minio_destroy_s,
            "trial_total_s": result.timings.trial_total_s,
        }

    results.append(
        {
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
            "system_baseline": baseline_metrics,
            "timings": timings_metrics,
        }
    )

    with open(results_file(cloud), "w") as f:
        json.dump(results, f, indent=2)


def objective(
    trial: optuna.Trial,
    cloud: str,
    cloud_config: CloudConfig,
    vm_ip: str,
    metric: str = "total_mib_s",
) -> float:
    """Optuna objective function."""
    config_space = get_config_space(cloud)

    config = {
        "nodes": trial.suggest_categorical("nodes", config_space["nodes"]),
        "cpu_per_node": trial.suggest_categorical(
            "cpu_per_node", config_space["cpu_per_node"]
        ),
        "ram_per_node": trial.suggest_categorical(
            "ram_per_node", config_space["ram_per_node"]
        ),
        "drives_per_node": trial.suggest_categorical(
            "drives_per_node", config_space["drives_per_node"]
        ),
        "drive_size_gb": trial.suggest_categorical(
            "drive_size_gb", config_space["drive_size_gb"]
        ),
        "drive_type": trial.suggest_categorical(
            "drive_type", config_space["drive_type"]
        ),
    }

    print(f"\n{'=' * 60}")
    print(f"Trial {trial.number} [{cloud}]: {config}")
    print(f"{'=' * 60}")

    # Check cache
    cached = find_cached_result(config, cloud)
    if cached:
        cached_value = get_metric_value(cached, metric)
        print(f"  Using cached result: {cached_value:.2f} ({metric})")
        return cached_value

    # Start timing the trial
    trial_start = time.time()
    timings = TrialTimings()

    # Destroy any existing MinIO before deploying new config
    # (volumes can't be shrunk, so we must recreate)
    print("  Cleaning up previous MinIO deployment...")
    _, cleanup_time = destroy_minio(cloud_config)
    # OpenStack needs time to release ports/IPs, Timeweb is faster
    post_destroy_wait = 15 if cloud == "selectel" else 5
    time.sleep(post_destroy_wait)

    # Deploy MinIO
    success, deploy_time = deploy_minio(config, cloud_config)
    timings.minio_deploy_s = deploy_time
    if not success:
        timings.trial_total_s = time.time() - trial_start
        save_result(
            BenchmarkResult(config=config, error="Deploy failed", timings=timings),
            config,
            trial.number,
            cloud,
            cloud_config,
        )
        return 0.0

    # Run system baseline (fio + sysbench) on MinIO node
    baseline_start = time.time()
    baseline = run_system_baseline(vm_ip)
    timings.baseline_s = time.time() - baseline_start

    # Run benchmark
    benchmark_start = time.time()
    result = run_warp_benchmark(vm_ip)
    timings.benchmark_s = time.time() - benchmark_start

    if result is None:
        timings.trial_total_s = time.time() - trial_start
        save_result(
            BenchmarkResult(
                config=config,
                error="Benchmark failed",
                baseline=baseline,
                timings=timings,
            ),
            config,
            trial.number,
            cloud,
            cloud_config,
        )
        return 0.0

    # Destroy MinIO after benchmark to measure destroy time
    _, destroy_time = destroy_minio(cloud_config)
    timings.minio_destroy_s = destroy_time
    timings.trial_total_s = time.time() - trial_start

    result.config = config
    result.baseline = baseline
    result.timings = timings
    save_result(result, config, trial.number, cloud, cloud_config)

    cost = calculate_cost(config, cloud_config)
    cost_efficiency = result.total_mib_s / cost if cost > 0 else 0
    result_metrics = {
        "total_mib_s": result.total_mib_s,
        "get_mib_s": result.get_mib_s,
        "put_mib_s": result.put_mib_s,
        "cost_efficiency": cost_efficiency,
    }
    metric_value = get_metric_value(result_metrics, metric)
    print(f"  Result: {result.total_mib_s:.1f} MiB/s, Cost: {cost:.2f}/hr, {metric}={metric_value:.2f}")
    print(f"  Timings: deploy={timings.minio_deploy_s:.0f}s, baseline={timings.baseline_s:.0f}s, benchmark={timings.benchmark_s:.0f}s, destroy={timings.minio_destroy_s:.0f}s, total={timings.trial_total_s:.0f}s")

    return metric_value


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Cloud MinIO Optimizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Optimize for throughput (default)
  python optimizer_multicloud.py --cloud selectel --trials 5

  # Optimize for cost efficiency (throughput per dollar)
  python optimizer_multicloud.py --cloud selectel --trials 5 --metric cost_efficiency

  # Optimize for read-heavy workloads
  python optimizer_multicloud.py --cloud timeweb --trials 5 --metric get_mib_s

  # Keep infrastructure after optimization
  python optimizer_multicloud.py --cloud timeweb --trials 5 --no-destroy
        """,
    )
    parser.add_argument(
        "--cloud",
        choices=["selectel", "timeweb"],
        required=True,
        help="Cloud provider",
    )
    parser.add_argument(
        "--metric",
        choices=list(METRICS.keys()),
        default="total_mib_s",
        help=f"Metric to optimize (default: total_mib_s). Options: {', '.join(METRICS.keys())}",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=5,
        help="Number of trials (default: 5)",
    )
    parser.add_argument(
        "--benchmark-vm-ip",
        default=None,
        help="Benchmark VM IP (auto-created if not provided)",
    )
    parser.add_argument(
        "--study-name",
        default=None,
        help="Optuna study name (default: minio-{cloud}-{metric})",
    )
    parser.add_argument(
        "--no-destroy",
        action="store_true",
        help="Keep infrastructure after optimization (default: destroy)",
    )
    args = parser.parse_args()

    cloud_config = get_cloud_config(args.cloud)
    study_name = args.study_name or f"minio-{args.cloud}-{args.metric}"

    print("=" * 60)
    print(f"MinIO Optimizer - {args.cloud.upper()}")
    print("=" * 60)
    print(f"Metric: {args.metric} ({METRICS[args.metric]})")
    print(f"Trials: {args.trials}")
    print(f"Terraform dir: {cloud_config.terraform_dir}")
    print(f"Results file: {results_file(args.cloud)}")
    print(f"Disk types: {cloud_config.disk_types}")
    print(f"Destroy at end: {not args.no_destroy}")
    print()

    # Ensure benchmark VM exists
    if args.benchmark_vm_ip:
        vm_ip = args.benchmark_vm_ip
        print(f"Using provided benchmark VM: {vm_ip}")
    else:
        vm_ip = ensure_benchmark_vm(cloud_config)

    print(f"\nBenchmark VM IP: {vm_ip}")
    print()

    # Create/load Optuna study
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
            print(f"Current best: {study.best_trial.value:.2f} ({args.metric})")
    print()

    try:
        # Run optimization
        study.optimize(
            lambda trial: objective(trial, args.cloud, cloud_config, vm_ip, args.metric),
            n_trials=args.trials,
            show_progress_bar=True,
        )

        # Print results
        print("\n" + "=" * 60)
        print(f"OPTIMIZATION COMPLETE ({args.cloud.upper()})")
        print("=" * 60)

        if study.best_trial:
            print(f"Best trial: {study.best_trial.number}")
            print(f"Best config: {study.best_trial.params}")
            print(f"Best {args.metric}: {study.best_trial.value:.2f}")

            # Calculate cost for best config
            best_cost = calculate_cost(study.best_trial.params, cloud_config)
            print(f"Best config cost: {best_cost:.2f}/hr")

    finally:
        # Cleanup
        if not args.no_destroy:
            destroy_all(cloud_config)
        else:
            print("\n--no-destroy specified, keeping infrastructure.")


if __name__ == "__main__":
    main()
