#!/usr/bin/env python3
"""
Multi-Cloud Redis Configuration Optimizer using Bayesian Optimization (Optuna).

Supports both Selectel and Timeweb Cloud providers.
Optimizes Redis single-node and Sentinel configurations.

Usage:
    python optimizer.py --cloud selectel --trials 10 --metric ops_per_sec
    python optimizer.py --cloud selectel --trials 10 --metric p99_latency_ms
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
from python_terraform import Terraform

from cloud_config import CloudConfig, get_cloud_config, get_config_space

RESULTS_DIR = Path(__file__).parent
STUDY_DB = RESULTS_DIR / "study.db"

# Available optimization metrics
METRICS = {
    "ops_per_sec": "Operations per second (higher is better)",
    "p99_latency_ms": "99th percentile latency in ms (lower is better)",
    "cost_efficiency": "Ops/sec per $/hr (higher is better)",
}


def results_file(cloud: str) -> Path:
    """Get results file path for a cloud."""
    return RESULTS_DIR / f"results_{cloud}.json"


@dataclass
class MemtierResult:
    """Memtier benchmark results."""

    ops_per_sec: float = 0.0
    get_ops_per_sec: float = 0.0
    set_ops_per_sec: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    p999_latency_ms: float = 0.0
    kb_per_sec: float = 0.0


@dataclass
class BenchmarkResult:
    config: dict
    ops_per_sec: float = 0.0
    p50_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    p999_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    kb_per_sec: float = 0.0
    duration_s: float = 0.0
    error: str | None = None


def config_to_key(config: dict) -> str:
    """Convert config dict to a hashable key for deduplication."""
    return json.dumps(
        {
            "mode": config["mode"],
            "cpu_per_node": config["cpu_per_node"],
            "ram_per_node": config["ram_per_node"],
            "maxmemory_policy": config["maxmemory_policy"],
            "io_threads": config["io_threads"],
            "persistence": config["persistence"],
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
    """Find a cached successful result for the given config."""
    target_key = config_to_key(config)
    for result in load_results(cloud):
        if config_to_key(result["config"]) == target_key:
            if result.get("error"):
                return None
            if result.get("ops_per_sec", 0) <= 0:
                return None
            return result
    return None


def run_ssh_command(
    vm_ip: str, command: str, timeout: int = 300, forward_agent: bool = False
) -> tuple[int, str]:
    """Run command on remote VM via SSH."""
    ssh_args = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=10",
    ]
    if forward_agent:
        ssh_args.append("-A")
    ssh_args.extend([f"root@{vm_ip}", command])

    result = subprocess.run(
        ssh_args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout + result.stderr


def wait_for_vm_ready(vm_ip: str, timeout: int = 300) -> bool:
    """Wait for benchmark VM to be ready."""
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


def clear_known_hosts_on_vm(vm_ip: str) -> None:
    """Clear known_hosts on benchmark VM."""
    try:
        run_ssh_command(vm_ip, "rm -f /root/.ssh/known_hosts", timeout=10)
    except Exception:
        pass


def wait_for_redis_ready(
    vm_ip: str, redis_ip: str = "10.0.0.20", timeout: int = 180
) -> bool:
    """Wait for Redis to be ready."""
    clear_known_hosts_on_vm(vm_ip)

    print(f"  Waiting for Redis at {redis_ip} to be ready...")

    start = time.time()
    while time.time() - start < timeout:
        elapsed = time.time() - start
        try:
            check_cmd = (
                f"ssh -A -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@{redis_ip} "
                f"'test -f /root/redis-ready && redis-cli ping'"
            )
            code, output = run_ssh_command(
                vm_ip, check_cmd, timeout=20, forward_agent=True
            )
            if code == 0 and "PONG" in output:
                print(f"  Redis is ready! ({elapsed:.0f}s)")
                return True
            else:
                print(f"  Redis not ready yet ({elapsed:.0f}s)...")
        except Exception as e:
            print(f"  Redis check failed ({elapsed:.0f}s): {e}")
        time.sleep(10)

    print(f"  Warning: Redis not ready after {timeout}s")
    return False


def get_terraform(cloud_config: CloudConfig) -> Terraform:
    """Get Terraform instance, initializing if needed."""
    tf_dir = str(cloud_config.terraform_dir)
    tf = Terraform(working_dir=tf_dir)

    terraform_dir = cloud_config.terraform_dir / ".terraform"
    if not terraform_dir.exists():
        print(f"  Initializing Terraform in {tf_dir}...")
        ret_code, stdout, stderr = tf.init()
        if ret_code != 0:
            raise RuntimeError(f"Terraform init failed: {stderr}")

    return tf


def get_tf_output(tf: Terraform, name: str) -> str | None:
    """Get terraform output value."""
    try:
        ret, out, err = tf.output_cmd(name)
        if ret != 0 or not out:
            return None
        value = out.strip().strip('"')
        if not value or value == "null":
            return None
        return value
    except Exception:
        return None


def ensure_benchmark_vm(cloud_config: CloudConfig) -> str:
    """Ensure benchmark VM exists and return its IP."""
    print(f"\nChecking benchmark VM for {cloud_config.name}...")

    tf = get_terraform(cloud_config)

    vm_ip = get_tf_output(tf, "benchmark_vm_ip")
    if vm_ip:
        print(f"  Found VM: {vm_ip}")
        try:
            code, _ = run_ssh_command(vm_ip, "echo ok", timeout=10)
            if code == 0:
                return vm_ip
        except Exception:
            pass

    print("  Creating benchmark VM...")
    tf_vars = {"redis_enabled": False, "minio_enabled": False}
    ret_code, stdout, stderr = tf.apply(skip_plan=True, var=tf_vars)

    if ret_code != 0:
        raise RuntimeError(f"Failed to create benchmark VM: {stderr}")

    vm_ip = get_tf_output(tf, "benchmark_vm_ip")
    if not vm_ip:
        raise RuntimeError("Benchmark VM created but no IP returned")

    print(f"  Benchmark VM created: {vm_ip}")
    wait_for_vm_ready(vm_ip)

    # Install memtier_benchmark
    print("  Installing memtier_benchmark...")
    install_cmd = (
        "apt-get update && "
        "apt-get install -y build-essential autoconf automake libpcre3-dev "
        "libevent-dev pkg-config zlib1g-dev libssl-dev git && "
        "cd /tmp && "
        "git clone https://github.com/RedisLabs/memtier_benchmark.git && "
        "cd memtier_benchmark && "
        "autoreconf -ivf && ./configure && make -j$(nproc) && make install"
    )
    code, output = run_ssh_command(vm_ip, install_cmd, timeout=300)
    if code != 0:
        print(
            f"  Warning: memtier_benchmark installation may have failed: {output[:500]}"
        )

    return vm_ip


def deploy_redis(
    config: dict, cloud_config: CloudConfig, vm_ip: str
) -> tuple[bool, float]:
    """Deploy Redis with given configuration."""
    print(f"  Deploying Redis on {cloud_config.name}: {config}")
    start = time.time()

    tf = get_terraform(cloud_config)

    tf_vars = {
        "redis_enabled": True,
        "minio_enabled": False,
        "redis_mode": config["mode"],
        "redis_node_cpu": config["cpu_per_node"],
        "redis_node_ram_gb": config["ram_per_node"],
        "redis_maxmemory_policy": config["maxmemory_policy"],
        "redis_io_threads": config["io_threads"],
        "redis_persistence": config["persistence"],
    }

    ret_code, stdout, stderr = tf.apply(skip_plan=True, var=tf_vars)

    if ret_code != 0:
        print(f"  Terraform apply failed: {stderr}")
        return False, time.time() - start

    if not wait_for_redis_ready(vm_ip):
        print("  Warning: Redis may not be fully ready")

    duration = time.time() - start
    print(f"  Redis deployed in {duration:.1f}s")
    return True, duration


def destroy_redis(cloud_config: CloudConfig) -> tuple[bool, float]:
    """Destroy Redis but keep benchmark VM."""
    print(f"  Destroying Redis on {cloud_config.name}...")
    start = time.time()

    tf = get_terraform(cloud_config)
    ret_code, stdout, stderr = tf.apply(
        skip_plan=True, var={"redis_enabled": False, "minio_enabled": False}
    )

    if ret_code != 0:
        print(f"  Warning: Redis destroy may have failed: {stderr}")
        return False, time.time() - start

    duration = time.time() - start
    print(f"  Redis destroyed in {duration:.1f}s")
    return True, duration


def destroy_all(cloud_config: CloudConfig) -> bool:
    """Destroy all infrastructure."""
    print(f"\nDestroying all resources on {cloud_config.name}...")

    tf_dir = str(cloud_config.terraform_dir)
    result = subprocess.run(
        ["terraform", "destroy", "-auto-approve"],
        cwd=tf_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  Warning: Destroy may have failed: {result.stderr}")
        return False

    print("  All resources destroyed.")
    return True


def run_memtier_benchmark(
    vm_ip: str, redis_ip: str = "10.0.0.20", duration: int = 60
) -> BenchmarkResult | None:
    """Run memtier_benchmark and parse results."""
    print("  Running memtier_benchmark...")

    # Cache-like workload: 80% GET, 20% SET
    memtier_cmd = (
        f"memtier_benchmark "
        f"--server={redis_ip} "
        f"--port=6379 "
        f"--clients=50 "
        f"--threads=4 "
        f"--ratio=1:4 "  # 1 SET : 4 GET = 20% write, 80% read
        f"--key-pattern=R:R "
        f"--key-minimum=1 "
        f"--key-maximum=10000000 "
        f"--data-size=256 "
        f"--test-time={duration} "
        f"--hide-histogram "
        f"2>&1"
    )

    start_time = time.time()
    try:
        code, output = run_ssh_command(vm_ip, memtier_cmd, timeout=duration + 60)
    except Exception as e:
        print(f"  Memtier failed: {e}")
        return None

    elapsed = time.time() - start_time

    if code != 0:
        print(f"  Memtier failed: {output[:500]}")
        return None

    return parse_memtier_output(output, elapsed)


def parse_memtier_output(output: str, duration: float) -> BenchmarkResult:
    """Parse memtier_benchmark output."""
    result = BenchmarkResult(config={}, duration_s=duration)

    # Parse Totals line:
    # Type         Ops/sec     Hits/sec   Misses/sec    Avg. Latency     p50 Latency     p99 Latency   p99.9 Latency       KB/sec
    # Totals     123456.78     98765.43       0.00         1.234           1.111           2.345           5.678        12345.67

    totals_pattern = r"Totals\s+([\d.]+)\s+[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)"
    match = re.search(totals_pattern, output)
    if match:
        result.ops_per_sec = float(match.group(1))
        result.avg_latency_ms = float(match.group(2))
        result.p50_latency_ms = float(match.group(3))
        result.p99_latency_ms = float(match.group(4))
        result.p999_latency_ms = float(match.group(5))
        result.kb_per_sec = float(match.group(6))
    else:
        print(f"  Warning: Could not parse memtier output. Sample: {output[:500]}...")

    return result


def calculate_cost(config: dict, cloud_config: CloudConfig) -> float:
    """Estimate hourly cost for the configuration."""
    nodes = 1 if config["mode"] == "single" else 3
    cpu = config["cpu_per_node"]
    ram = config["ram_per_node"]

    cpu_cost = cpu * cloud_config.cpu_cost
    ram_cost = ram * cloud_config.ram_cost
    # Redis uses fast SSD for boot only (50GB)
    storage_cost = 50 * cloud_config.disk_cost_multipliers.get("fast", 0.015)

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

    cost = calculate_cost(config, cloud_config)
    cost_efficiency = result.ops_per_sec / cost if cost > 0 else 0

    results.append(
        {
            "trial": trial_number,
            "timestamp": datetime.now().isoformat(),
            "cloud": cloud,
            "config": config,
            "nodes": 1 if config["mode"] == "single" else 3,
            "cost_per_hour": cost,
            "cost_efficiency": cost_efficiency,
            "ops_per_sec": result.ops_per_sec,
            "avg_latency_ms": result.avg_latency_ms,
            "p50_latency_ms": result.p50_latency_ms,
            "p99_latency_ms": result.p99_latency_ms,
            "p999_latency_ms": result.p999_latency_ms,
            "kb_per_sec": result.kb_per_sec,
            "duration_s": result.duration_s,
            "error": result.error,
        }
    )

    with open(results_file(cloud), "w") as f:
        json.dump(results, f, indent=2)


def get_metric_value(result: dict, metric: str) -> float:
    """Extract the optimization metric value from a result."""
    if metric == "p99_latency_ms":
        # For latency, we want to minimize, so return negative
        # Optuna maximizes by default
        return -result.get("p99_latency_ms", float("inf"))
    return result.get(metric, 0)


def objective(
    trial: optuna.Trial,
    cloud: str,
    cloud_config: CloudConfig,
    vm_ip: str,
    metric: str = "ops_per_sec",
) -> float:
    """Optuna objective function."""
    config_space = get_config_space(cloud)

    config = {
        "mode": trial.suggest_categorical("mode", config_space["mode"]),
        "cpu_per_node": trial.suggest_categorical(
            "cpu_per_node", config_space["cpu_per_node"]
        ),
        "ram_per_node": trial.suggest_categorical(
            "ram_per_node", config_space["ram_per_node"]
        ),
        "maxmemory_policy": trial.suggest_categorical(
            "maxmemory_policy", config_space["maxmemory_policy"]
        ),
        "io_threads": trial.suggest_categorical(
            "io_threads", config_space["io_threads"]
        ),
        "persistence": trial.suggest_categorical(
            "persistence", config_space["persistence"]
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

    # Destroy any existing Redis
    print("  Cleaning up previous Redis deployment...")
    destroy_redis(cloud_config)
    time.sleep(10)

    # Deploy Redis
    success, deploy_time = deploy_redis(config, cloud_config, vm_ip)
    if not success:
        save_result(
            BenchmarkResult(config=config, error="Deploy failed"),
            config,
            trial.number,
            cloud,
            cloud_config,
        )
        return 0.0 if metric != "p99_latency_ms" else -float("inf")

    # Run benchmark
    result = run_memtier_benchmark(vm_ip)

    if result is None or result.ops_per_sec == 0:
        save_result(
            BenchmarkResult(config=config, error="Benchmark failed"),
            config,
            trial.number,
            cloud,
            cloud_config,
        )
        return 0.0 if metric != "p99_latency_ms" else -float("inf")

    result.config = config
    save_result(result, config, trial.number, cloud, cloud_config)

    cost = calculate_cost(config, cloud_config)
    result_metrics = {
        "ops_per_sec": result.ops_per_sec,
        "p99_latency_ms": result.p99_latency_ms,
        "cost_efficiency": result.ops_per_sec / cost if cost > 0 else 0,
    }

    metric_value = get_metric_value(result_metrics, metric)

    print(
        f"  Result: {result.ops_per_sec:.0f} ops/s, p99={result.p99_latency_ms:.2f}ms, Cost: {cost:.2f}/hr"
    )

    return metric_value


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Cloud Redis Optimizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Optimize for throughput
  python optimizer.py --cloud selectel --trials 10 --metric ops_per_sec

  # Optimize for latency
  python optimizer.py --cloud selectel --trials 10 --metric p99_latency_ms

  # Keep infrastructure after optimization
  python optimizer.py --cloud selectel --trials 10 --no-destroy
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
        default="ops_per_sec",
        help="Metric to optimize (default: ops_per_sec)",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=10,
        help="Number of trials (default: 10)",
    )
    parser.add_argument(
        "--benchmark-vm-ip",
        default=None,
        help="Benchmark VM IP (auto-created if not provided)",
    )
    parser.add_argument(
        "--study-name",
        default=None,
        help="Optuna study name (default: redis-{cloud}-{metric})",
    )
    parser.add_argument(
        "--no-destroy",
        action="store_true",
        help="Keep infrastructure after optimization",
    )
    args = parser.parse_args()

    cloud_config = get_cloud_config(args.cloud)
    study_name = args.study_name or f"redis-{args.cloud}-{args.metric}"

    print("=" * 60)
    print(f"Redis Optimizer - {args.cloud.upper()}")
    print("=" * 60)
    print(f"Metric: {args.metric} ({METRICS[args.metric]})")
    print(f"Trials: {args.trials}")
    print(f"Terraform dir: {cloud_config.terraform_dir}")
    print(f"Results file: {results_file(args.cloud)}")
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
        try:
            best = study.best_trial
            print(f"Current best: {best.value:.2f} ({args.metric})")
        except ValueError:
            pass
    print()

    try:
        study.optimize(
            lambda trial: objective(
                trial, args.cloud, cloud_config, vm_ip, args.metric
            ),
            n_trials=args.trials,
            show_progress_bar=True,
        )

        print("\n" + "=" * 60)
        print(f"OPTIMIZATION COMPLETE ({args.cloud.upper()})")
        print("=" * 60)

        try:
            best = study.best_trial
            print(f"Best trial: {best.number}")
            print(f"Best config: {best.params}")
            if args.metric == "p99_latency_ms" and best.value is not None:
                print(f"Best {args.metric}: {-best.value:.2f}ms")
            elif best.value is not None:
                print(f"Best {args.metric}: {best.value:.2f}")
            else:
                print(f"Best {args.metric}: N/A")

            best_cost = calculate_cost(best.params, cloud_config)
            print(f"Best config cost: {best_cost:.2f}/hr")
        except ValueError:
            print("No successful trials completed")

    finally:
        if not args.no_destroy:
            destroy_all(cloud_config)
        else:
            print("\n--no-destroy specified, keeping infrastructure.")


if __name__ == "__main__":
    main()
