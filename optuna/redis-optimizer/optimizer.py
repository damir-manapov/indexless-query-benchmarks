#!/usr/bin/env python3
"""
Multi-Cloud Redis Configuration Optimizer using Bayesian Optimization (Optuna).

Supports both Selectel and Timeweb Cloud providers.
Optimizes Redis single-node and Sentinel configurations.

Usage:
    uv run python redis-optimizer/optimizer.py --cloud selectel --trials 10 --metric ops_per_sec
    uv run python redis-optimizer/optimizer.py --cloud selectel --trials 10 --metric p99_latency_ms
    uv run python redis-optimizer/optimizer.py --cloud selectel --no-destroy
    uv run python redis-optimizer/optimizer.py --cloud selectel --show-results
    uv run python redis-optimizer/optimizer.py --cloud selectel --export-md
"""

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import optuna
from optuna.samplers import TPESampler

# Add parent dir to path for common imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from common import (
    clear_known_hosts_on_vm,
    destroy_all,
    get_terraform,
    get_tf_output,
    load_results,
    run_ssh_command,
    save_results,
    wait_for_vm_ready,
)

from cloud_config import CloudConfig, get_cloud_config, get_config_space

RESULTS_DIR = Path(__file__).parent
STUDY_DB = RESULTS_DIR / "study.db"

# Available optimization metrics
METRICS = {
    "ops_per_sec": "Operations per second (higher is better)",
    "p99_latency_ms": "99th percentile latency in ms (lower is better)",
    "cost_efficiency": "Ops/sec per $/hr (higher is better)",
}


def config_summary(r: dict) -> str:
    """Format config as a compact string."""
    c = r.get("config", {})
    nodes = r.get("nodes", 1 if c.get("mode") == "single" else 3)
    return f"{c.get('mode', '?')} {nodes}×{c.get('cpu_per_node', 0)}cpu/{c.get('ram_per_node', 0)}gb io={c.get('io_threads', 0)} {c.get('persistence', '?')}"


def format_results(cloud: str) -> dict | None:
    """Format benchmark results for display/export. Returns None if no results."""
    results = load_results(results_file(cloud))

    if not results:
        return None

    results_sorted = sorted(results, key=lambda x: x.get("ops_per_sec", 0), reverse=True)

    # Extract row data
    rows = []
    for r in results_sorted:
        cfg = r.get("config", {})
        mode = cfg.get("mode", "?")
        rows.append({
            "mode": mode,
            "nodes": r.get("nodes", 1 if mode == "single" else 3),
            "cpu": cfg.get("cpu_per_node", 0),
            "ram": cfg.get("ram_per_node", 0),
            "policy": cfg.get("maxmemory_policy", "?"),
            "io": cfg.get("io_threads", 0),
            "persist": cfg.get("persistence", "?"),
            "ops": r.get("ops_per_sec", 0),
            "p99": r.get("p99_latency_ms", 0),
            "cost": r.get("cost_per_hour", 0),
            "eff": r.get("cost_efficiency", 0),
        })

    # Best configs
    best_ops = max(results, key=lambda x: x.get("ops_per_sec", 0))
    best_latency = min(results, key=lambda x: x.get("p99_latency_ms", float("inf")))
    best_efficiency = max(results, key=lambda x: x.get("cost_efficiency", 0))

    return {
        "cloud": cloud,
        "rows": rows,
        "best": {
            "ops": {"value": best_ops.get("ops_per_sec", 0), "config": config_summary(best_ops)},
            "latency": {"value": best_latency.get("p99_latency_ms", 0), "config": config_summary(best_latency)},
            "efficiency": {"value": best_efficiency.get("cost_efficiency", 0), "config": config_summary(best_efficiency)},
        },
    }


def show_results(cloud: str) -> None:
    """Display all benchmark results for a cloud in a table format."""
    data = format_results(cloud)

    if not data:
        print(f"No results found for {cloud}")
        return

    print(f"\n{'='*100}")
    print(f"Redis Benchmark Results - {cloud.upper()}")
    print(f"{'='*100}")

    # Header
    print(
        f"{'#':>3} {'Mode':<8} {'Nodes':>5} {'CPU':>4} {'RAM':>4} {'Policy':<12} "
        f"{'IO':>3} {'Persist':<5} {'Ops/s':>10} {'p99ms':>7} {'$/hr':>6} {'Eff':>8}"
    )
    print("-" * 100)

    for i, r in enumerate(data["rows"], 1):
        print(
            f"{i:>3} {r['mode'][:8]:<8} {r['nodes']:>5} {r['cpu']:>4} {r['ram']:>4} {r['policy'][:12]:<12} "
            f"{r['io']:>3} {r['persist'][:5]:<5} {r['ops']:>10.0f} {r['p99']:>7.2f} {r['cost']:>6.2f} {r['eff']:>8.0f}"
        )

    print("-" * 100)
    print(f"Total: {len(data['rows'])} results")

    best = data["best"]
    print(f"\nBest by ops/sec:     {best['ops']['value']:>10.0f} {'ops/s':<9} [{best['ops']['config']}]")
    print(f"Best by p99 latency: {best['latency']['value']:>10.2f} {'ms':<9} [{best['latency']['config']}]")
    print(f"Best by efficiency:  {best['efficiency']['value']:>10.0f} {'ops/$/hr':<9} [{best['efficiency']['config']}]")


def export_results_md(cloud: str, output_path: Path | None = None) -> None:
    """Export benchmark results to a markdown file."""
    data = format_results(cloud)

    if not data:
        print(f"No results found for {cloud}")
        return

    if output_path is None:
        output_path = RESULTS_DIR / f"RESULTS_{cloud.upper()}.md"

    lines = [
        f"# Redis Benchmark Results - {cloud.upper()}",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Results",
        "",
        "| # | Mode | Nodes | CPU | RAM | Policy | IO | Persist | Ops/s | p99 (ms) | $/hr | Efficiency |",
        "|--:|------|------:|----:|----:|--------|---:|---------|------:|---------:|-----:|-----------:|",
    ]

    for i, r in enumerate(data["rows"], 1):
        lines.append(
            f"| {i} | {r['mode']} | {r['nodes']} | {r['cpu']} | {r['ram']} | {r['policy']} | {r['io']} | {r['persist']} | {r['ops']:.0f} | {r['p99']:.2f} | {r['cost']:.2f} | {r['eff']:.0f} |"
        )

    best = data["best"]
    lines.extend([
        "",
        "## Best Configurations",
        "",
        f"- **Best by ops/sec:** {best['ops']['value']:.0f} ops/s — `{best['ops']['config']}`",
        f"- **Best by p99 latency:** {best['latency']['value']:.2f}ms — `{best['latency']['config']}`",
        f"- **Best by efficiency:** {best['efficiency']['value']:.0f} ops/$/hr — `{best['efficiency']['config']}`",
        "",
    ])

    output_path.write_text("\n".join(lines))
    print(f"Results exported to {output_path}")



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


def find_cached_result(config: dict, cloud: str) -> dict | None:
    """Find a cached successful result for the given config."""
    target_key = config_to_key(config)
    for result in load_results(results_file(cloud)):
        if config_to_key(result["config"]) == target_key:
            if result.get("error"):
                return None
            if result.get("ops_per_sec", 0) <= 0:
                return None
            return result
    return None


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


def ensure_benchmark_vm(cloud_config: CloudConfig) -> str:
    """Ensure benchmark VM exists and return its IP."""
    print(f"\nChecking benchmark VM for {cloud_config.name}...")

    tf = get_terraform(cloud_config.terraform_dir)

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

    tf = get_terraform(cloud_config.terraform_dir)

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

    tf = get_terraform(cloud_config.terraform_dir)
    ret_code, stdout, stderr = tf.apply(
        skip_plan=True, var={"redis_enabled": False, "minio_enabled": False}
    )

    if ret_code != 0:
        print(f"  Warning: Redis destroy may have failed: {stderr}")
        return False, time.time() - start

    duration = time.time() - start
    print(f"  Redis destroyed in {duration:.1f}s")
    return True, duration


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
    results = load_results(results_file(cloud))

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

    save_results(results, results_file(cloud))


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
        print("  Deploy failed - marking trial as pruned (will retry config later)")
        raise optuna.TrialPruned("Deploy failed")

    # Run benchmark
    result = run_memtier_benchmark(vm_ip)

    if result is None or result.ops_per_sec == 0:
        print("  Benchmark failed - marking trial as pruned (will retry config later)")
        raise optuna.TrialPruned("Benchmark failed")

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
  uv run python redis-optimizer/optimizer.py --cloud selectel --trials 10 --metric ops_per_sec

  # Optimize for latency
  uv run python redis-optimizer/optimizer.py --cloud selectel --trials 10 --metric p99_latency_ms

  # Keep infrastructure after optimization
  uv run python redis-optimizer/optimizer.py --cloud selectel --trials 10 --no-destroy

  # Show all results
  uv run python redis-optimizer/optimizer.py --cloud selectel --show-results

  # Export results to markdown
  uv run python redis-optimizer/optimizer.py --cloud selectel --export-md
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
    parser.add_argument(
        "--show-results",
        action="store_true",
        help="Show all benchmark results and exit",
    )
    parser.add_argument(
        "--export-md",
        action="store_true",
        help="Export results to markdown file and exit",
    )
    args = parser.parse_args()

    # Handle --show-results
    if args.show_results:
        show_results(args.cloud)
        return

    # Handle --export-md
    if args.export_md:
        export_results_md(args.cloud)
        return

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
            destroy_all(cloud_config.terraform_dir, cloud_config.name)
        else:
            print("\n--no-destroy specified, keeping infrastructure.")


if __name__ == "__main__":
    main()
