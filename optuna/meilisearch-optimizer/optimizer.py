#!/usr/bin/env python3
"""
Meilisearch Configuration Optimizer using Bayesian Optimization (Optuna).

Supports two optimization modes:
- infra: Tune VM specs (CPU, RAM, disk) - creates new VM per trial
- config: Tune Meilisearch config on fixed host - reconfigures existing VM

Usage:
    # Infrastructure optimization
    uv run python meilisearch-optimizer/optimizer.py --cloud selectel --mode infra --trials 10

    # Config optimization on fixed host
    uv run python meilisearch-optimizer/optimizer.py --cloud selectel --mode config --cpu 8 --ram 16 --trials 20

    # Full optimization
    uv run python meilisearch-optimizer/optimizer.py --cloud selectel --mode full --trials 15
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import optuna
from optuna.samplers import TPESampler

sys.path.insert(0, str(Path(__file__).parent.parent))

from common import (
    destroy_all,
    get_terraform,
    get_tf_output,
    load_results,
    run_ssh_command,
    save_results,
    wait_for_vm_ready,
)

RESULTS_DIR = Path(__file__).parent
STUDY_DB = RESULTS_DIR / "study.db"
BENCHMARK_SCRIPT = RESULTS_DIR / "benchmark.js"
DATASET_SCRIPT = RESULTS_DIR / "dataset.py"

# Meilisearch master key (must match terraform)
MASTER_KEY = "benchmark-master-key-change-in-production"

# Dataset config
DATASET_SIZE = 500000  # 500K products


@dataclass
class CloudConfig:
    name: str
    terraform_dir: Path


def get_cloud_config(cloud: str) -> CloudConfig:
    base = Path(__file__).parent.parent.parent / "terraform"
    return CloudConfig(
        name=cloud.upper(),
        terraform_dir=base / cloud,
    )


# Search spaces
def get_infra_search_space():
    return {
        "cpu": [2, 4, 8, 16],
        "ram_gb": [4, 8, 16, 32],
        "disk_type": ["fast", "universal"],  # NVMe vs SSD
    }


def get_config_search_space():
    return {
        "max_indexing_memory_mb": [256, 512, 1024, 2048],
        "max_indexing_threads": [0, 2, 4, 8],  # 0 = auto
    }


@dataclass
class BenchmarkResult:
    """Benchmark results."""

    qps: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    error_rate: float = 0.0
    indexing_time_s: float = 0.0
    error: str | None = None


def wait_for_meilisearch_ready(
    vm_ip: str, timeout: int = 300, jump_host: str | None = None
) -> bool:
    """Wait for Meilisearch to be healthy."""
    print("  Waiting for Meilisearch to be ready...")

    start = time.time()
    while time.time() - start < timeout:
        try:
            code, output = run_ssh_command(
                vm_ip,
                "curl -sf http://localhost:7700/health",
                timeout=10,
                jump_host=jump_host,
            )
            if code == 0 and "available" in output.lower():
                print(f"  Meilisearch ready! ({time.time() - start:.0f}s)")
                return True
        except Exception:
            pass
        time.sleep(5)

    print(f"  Warning: Meilisearch not ready after {timeout}s")
    return False


def upload_and_index_dataset(
    benchmark_ip: str, meili_ip: str, jump_host: str | None = None
) -> float:
    """Generate, upload and index the dataset. Returns indexing time in seconds."""
    print(f"  Generating and indexing {DATASET_SIZE:,} products...")

    # Generate dataset on benchmark VM using Node.js
    gen_cmd = f"""
cd /tmp && node << 'JSEOF'
const fs = require('fs');

// Seeded RNG (Mulberry32)
let seed = 42;
function rng() {{
  seed = (seed + 0x6d2b79f5) | 0;
  let t = seed;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}}

const pick = arr => arr[Math.floor(rng() * arr.length)];

const CATEGORIES = ["Laptops", "Smartphones", "Tablets", "Headphones", "Cameras", "TVs", "Gaming", "Wearables", "Audio", "Accessories"];
const BRANDS = ["Apple", "Samsung", "Sony", "LG", "Dell", "HP", "Lenovo", "Asus", "Acer", "Microsoft", "Google", "Bose", "JBL", "Canon", "Nikon"];
const ADJECTIVES = ["Pro", "Ultra", "Max", "Plus", "Lite", "Mini", "Elite", "Premium", "Advanced", "Essential"];
const PRICE_BASE = {{Laptops: 1000, Smartphones: 500, Tablets: 400, Headphones: 100, Cameras: 800, TVs: 600, Gaming: 200, Wearables: 200, Audio: 150, Accessories: 30}};

function genProduct(i) {{
  const cat = pick(CATEGORIES);
  const brand = pick(BRANDS);
  const adj = pick(ADJECTIVES);
  const singular = cat.endsWith('s') ? cat.slice(0, -1) : cat;
  return {{
    id: i,
    title: `${{brand}} ${{adj}} ${{singular}} ${{i % 20}}`,
    description: `High-quality ${{cat.toLowerCase()}} from ${{brand}} with ${{adj.toLowerCase()}} features`,
    brand,
    category: cat,
    price: Math.round(PRICE_BASE[cat] * (0.5 + rng() * 2) * 100) / 100,
    rating: Math.round((3 + rng() * 2) * 10) / 10,
    in_stock: rng() > 0.1
  }};
}}

const stream = fs.createWriteStream('/tmp/products.ndjson');
const total = {DATASET_SIZE};
for (let i = 1; i <= total; i++) {{
  stream.write(JSON.stringify(genProduct(i)) + '\\n');
  if (i % 100000 === 0) console.log(`Generated ${{i}} products`);
}}
stream.end(() => console.log(`Done generating ${{total}} products`));
JSEOF
"""
    code, output = run_ssh_command(benchmark_ip, gen_cmd, timeout=300)
    if code != 0:
        print(f"  Failed to generate dataset: {output}")
        return -1

    # Create index with settings
    create_cmd = f"""
curl -sf -X POST 'http://{meili_ip}:7700/indexes' \\
  -H 'Authorization: Bearer {MASTER_KEY}' \\
  -H 'Content-Type: application/json' \\
  --data '{{"uid": "products", "primaryKey": "id"}}'
"""
    run_ssh_command(benchmark_ip, create_cmd, timeout=30)

    # Configure index settings
    settings_cmd = f"""
curl -sf -X PATCH 'http://{meili_ip}:7700/indexes/products/settings' \\
  -H 'Authorization: Bearer {MASTER_KEY}' \\
  -H 'Content-Type: application/json' \\
  --data '{{
    "searchableAttributes": ["title", "description", "brand"],
    "filterableAttributes": ["category", "brand", "price", "rating", "in_stock"],
    "sortableAttributes": ["price", "rating"]
  }}'
"""
    run_ssh_command(benchmark_ip, settings_cmd, timeout=30)
    time.sleep(2)

    # Upload documents in batches
    start_time = time.time()

    upload_cmd = f"""
split -l 50000 /tmp/products.ndjson /tmp/batch_
for f in /tmp/batch_*; do
  echo "Uploading $f..."
  curl -sf -X POST "http://{meili_ip}:7700/indexes/products/documents" \\
    -H "Authorization: Bearer {MASTER_KEY}" \\
    -H "Content-Type: application/x-ndjson" \\
    --data-binary @"$f"
  echo ""
done
"""
    code, output = run_ssh_command(benchmark_ip, upload_cmd, timeout=600)
    if code != 0:
        print(f"  Failed to upload dataset: {output}")
        return -1

    # Wait for indexing to complete
    print("  Waiting for indexing to complete...")
    wait_cmd = f"""
while true; do
  status=$(curl -sf 'http://{meili_ip}:7700/tasks?statuses=processing,enqueued' \\
    -H 'Authorization: Bearer {MASTER_KEY}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total', 0))")
  if [ "$status" = "0" ]; then
    echo "Indexing complete"
    break
  fi
  echo "Tasks remaining: $status"
  sleep 2
done
"""
    code, output = run_ssh_command(benchmark_ip, wait_cmd, timeout=600)

    indexing_time = time.time() - start_time
    print(f"  Indexing completed in {indexing_time:.1f}s")

    # Verify document count
    stats_cmd = f"""
curl -sf 'http://{meili_ip}:7700/indexes/products/stats' \\
  -H 'Authorization: Bearer {MASTER_KEY}'
"""
    code, output = run_ssh_command(benchmark_ip, stats_cmd, timeout=30)
    if code == 0:
        try:
            stats = json.loads(output.strip().split("\n")[-1])
            print(f"  Indexed {stats.get('numberOfDocuments', 0):,} documents")
        except Exception:
            pass

    return indexing_time


def run_k6_benchmark(
    benchmark_ip: str, meili_ip: str, vus: int = 10, duration: int = 60
) -> BenchmarkResult:
    """Run k6 benchmark from benchmark VM."""
    print(f"  Running k6 benchmark (vus={vus}, duration={duration}s)...")

    # Upload k6 script
    with open(BENCHMARK_SCRIPT) as f:
        script_content = f.read()

    upload_cmd = f"cat > /tmp/benchmark.js << 'EOFSCRIPT'\n{script_content}\nEOFSCRIPT"
    run_ssh_command(benchmark_ip, upload_cmd, timeout=30)

    # Run k6
    k6_cmd = f"""
k6 run /tmp/benchmark.js \\
  -e MEILI_URL=http://{meili_ip}:7700 \\
  -e MEILI_KEY={MASTER_KEY} \\
  -e VUS={vus} \\
  -e DURATION={duration}s \\
  --summary-export=/tmp/k6_results.json \\
  2>&1
"""
    code, output = run_ssh_command(benchmark_ip, k6_cmd, timeout=duration + 60)

    if code != 0:
        return BenchmarkResult(error=f"k6 failed: {output[:500]}")

    # Parse results
    cat_cmd = "cat /tmp/k6_results.json"
    code, results_json = run_ssh_command(benchmark_ip, cat_cmd, timeout=10)

    if code != 0:
        return BenchmarkResult(error="Failed to get k6 results")

    try:
        # Use raw_decode to extract first JSON object (handles extra data after JSON)
        decoder = json.JSONDecoder()
        content = results_json.strip()
        start_idx = content.find("{")
        if start_idx == -1:
            return BenchmarkResult(error="No JSON found in k6 results")

        json_content, _ = decoder.raw_decode(content, start_idx)

        # Extract metrics from parsed JSON
        metrics = json_content.get("metrics", {})
        http_reqs = metrics.get("http_reqs", {})
        search_latency = metrics.get("search_latency_ms", {})
        search_errors = metrics.get("search_errors", {})

        qps = http_reqs.get("rate", 0)
        p50 = search_latency.get("med", 0) if search_latency else 0
        p95 = search_latency.get("p(95)", 0) if search_latency else 0
        p99 = search_latency.get("p(99)", 0) if search_latency else 0

        total_reqs = http_reqs.get("count", 1)
        errors = search_errors.get("count", 0) if search_errors else 0
        error_rate = errors / total_reqs if total_reqs > 0 else 0

        return BenchmarkResult(
            qps=qps,
            p50_ms=p50,
            p95_ms=p95,
            p99_ms=p99,
            error_rate=error_rate,
        )

    except Exception as e:
        return BenchmarkResult(error=f"Failed to parse results: {e}")


def ensure_infra(
    cloud_config: CloudConfig, infra_config: dict | None = None
) -> tuple[str, str]:
    """Ensure Meilisearch and Benchmark VMs exist. Returns (benchmark_ip, meili_ip)."""
    print(f"\nChecking infrastructure for {cloud_config.name}...")

    tf = get_terraform(cloud_config.terraform_dir)

    meili_ip = get_tf_output(tf, "meilisearch_vm_ip")
    benchmark_ip = get_tf_output(tf, "benchmark_vm_ip")

    if meili_ip and benchmark_ip:
        print(f"  Found Meilisearch VM: {meili_ip}")
        print(f"  Found Benchmark VM: {benchmark_ip}")
        try:
            code, _ = run_ssh_command(
                meili_ip,
                "curl -sf http://localhost:7700/health",
                timeout=10,
                jump_host=benchmark_ip,
            )
            if code == 0:
                return benchmark_ip, meili_ip
        except Exception:
            pass

    print("  Creating infrastructure...")
    tf_vars = {
        "meilisearch_enabled": True,
        "postgres_enabled": False,
        "redis_enabled": False,
        "minio_enabled": False,
    }

    if infra_config:
        tf_vars.update(
            {
                "meilisearch_cpu": infra_config.get("cpu", 4),
                "meilisearch_ram_gb": infra_config.get("ram_gb", 8),
                "meilisearch_disk_type": infra_config.get("disk_type", "fast"),
            }
        )

    ret_code, stdout, stderr = tf.apply(skip_plan=True, var=tf_vars)

    if ret_code != 0:
        raise RuntimeError(f"Failed to create infrastructure: {stderr}")

    meili_ip = get_tf_output(tf, "meilisearch_vm_ip")
    benchmark_ip = get_tf_output(tf, "benchmark_vm_ip")

    if not meili_ip:
        raise RuntimeError("Meilisearch VM created but no IP returned")
    if not benchmark_ip:
        raise RuntimeError("Benchmark VM created but no IP returned")

    print(f"  Meilisearch VM: {meili_ip}")
    print(f"  Benchmark VM: {benchmark_ip}")

    # Wait for VMs
    wait_for_vm_ready(benchmark_ip)
    wait_for_vm_ready(meili_ip, jump_host=benchmark_ip)
    wait_for_meilisearch_ready(meili_ip, jump_host=benchmark_ip)

    return benchmark_ip, meili_ip


def reconfigure_meilisearch(
    meili_ip: str, config: dict, jump_host: str | None = None
) -> bool:
    """Reconfigure Meilisearch with new settings."""
    print(f"  Reconfiguring Meilisearch: {config}")

    max_mem = config.get("max_indexing_memory_mb", 1024)
    max_threads = config.get("max_indexing_threads", 0)

    # Update environment file
    env_content = f"""MEILI_ENV=production
MEILI_HTTP_ADDR=0.0.0.0:7700
MEILI_MASTER_KEY={MASTER_KEY}
MEILI_NO_ANALYTICS=true
MEILI_LOG_LEVEL=INFO
MEILI_MAX_INDEXING_MEMORY={max_mem}Mb
MEILI_MAX_INDEXING_THREADS={max_threads if max_threads > 0 else "auto"}
"""

    update_cmd = f"cat > /etc/meilisearch.env << 'EOF'\n{env_content}EOF"
    code, output = run_ssh_command(
        meili_ip, update_cmd, timeout=30, jump_host=jump_host
    )
    if code != 0:
        print(f"  Failed to update config: {output}")
        return False

    # Restart Meilisearch
    restart_cmd = "systemctl restart meilisearch && sleep 3"
    code, output = run_ssh_command(
        meili_ip, restart_cmd, timeout=60, jump_host=jump_host
    )
    if code != 0:
        print(f"  Failed to restart Meilisearch: {output}")
        return False

    # Wait for it to be ready
    return wait_for_meilisearch_ready(meili_ip, timeout=60, jump_host=jump_host)


def results_file() -> Path:
    """Get results file path."""
    return RESULTS_DIR / "results.json"


def config_to_key(infra: dict, meili_config: dict, cloud: str) -> str:
    """Convert config dicts to a hashable key for deduplication."""
    return json.dumps(
        {"cloud": cloud, "infra": infra, "meili": meili_config}, sort_keys=True
    )


def find_cached_result(infra: dict, meili_config: dict, cloud: str) -> dict | None:
    """Find a cached successful result for the given config."""
    target_key = config_to_key(infra, meili_config, cloud)

    rf = results_file()
    if not rf.exists():
        return None
    for result in load_results(rf):
        result_key = config_to_key(
            result.get("infra", {}), result.get("config", {}), result.get("cloud", "")
        )
        if result_key == target_key:
            if result.get("error"):
                continue  # Skip errored, try next
            if result.get("qps", 0) <= 0:
                continue  # Skip failed, try next
            return result
    return None


def get_metric_value(result: dict, metric: str) -> float:
    """Extract the optimization metric value from a result."""
    if metric == "qps":
        return result.get("qps", 0)
    elif metric == "indexing_time":
        return result.get("indexing_time_s", float("inf"))
    else:  # p95_ms default
        return result.get("p95_ms", float("inf"))


def save_result(
    result: BenchmarkResult,
    infra_config: dict,
    meili_config: dict,
    trial_num: int,
    cloud: str,
    cloud_config: CloudConfig,
    indexing_time: float = 0,
):
    """Save benchmark result."""
    rf = results_file()
    results = load_results(rf)

    results.append(
        {
            "trial": trial_num,
            "timestamp": datetime.now().isoformat(),
            "cloud": cloud,
            "infra": infra_config,
            "config": meili_config,
            "qps": result.qps,
            "p50_ms": result.p50_ms,
            "p95_ms": result.p95_ms,
            "p99_ms": result.p99_ms,
            "error_rate": result.error_rate,
            "indexing_time_s": indexing_time,
            "error": result.error,
        }
    )

    save_results(results, rf)

    # Auto-export markdown after each trial
    export_results_md(cloud)


def config_summary(r: dict) -> str:
    """Format config as a compact string."""
    infra = r.get("infra", {})
    cfg = r.get("config", {})
    infra_str = f"{infra.get('cpu', 0)}cpu/{infra.get('ram_gb', 0)}gb/{infra.get('disk_type', '?')}"
    if cfg:
        cfg_str = f" mem={cfg.get('max_indexing_memory_mb', 0)}mb thr={cfg.get('max_indexing_threads', 0)}"
        return infra_str + cfg_str
    return infra_str


def format_results(cloud: str) -> dict | None:
    """Format benchmark results for display/export. Returns None if no results."""
    results = load_results(results_file())

    # Filter by cloud
    results = [r for r in results if r.get("cloud", "") == cloud]

    if not results:
        return None

    results_sorted = sorted(results, key=lambda x: x.get("qps", 0), reverse=True)

    rows = []
    for r in results_sorted:
        infra = r.get("infra", {})
        cfg = r.get("config", {})
        rows.append(
            {
                "cpu": infra.get("cpu", 0),
                "ram": infra.get("ram_gb", 0),
                "disk": infra.get("disk_type", "?"),
                "mem_mb": cfg.get("max_indexing_memory_mb", 0),
                "threads": cfg.get("max_indexing_threads", 0),
                "qps": r.get("qps", 0),
                "p50": r.get("p50_ms", 0),
                "p95": r.get("p95_ms", 0),
                "p99": r.get("p99_ms", 0),
                "idx_time": r.get("indexing_time_s", 0),
            }
        )

    best_qps = max(results, key=lambda x: x.get("qps", 0))
    best_p95 = min(
        [r for r in results if r.get("p95_ms", float("inf")) > 0],
        key=lambda x: x.get("p95_ms", float("inf")),
        default=best_qps,
    )
    best_idx = min(
        [r for r in results if r.get("indexing_time_s", 0) > 0],
        key=lambda x: x.get("indexing_time_s", float("inf")),
        default=best_qps,
    )

    return {
        "cloud": cloud,
        "rows": rows,
        "best": {
            "qps": {
                "value": best_qps.get("qps", 0),
                "config": config_summary(best_qps),
            },
            "p95": {
                "value": best_p95.get("p95_ms", 0),
                "config": config_summary(best_p95),
            },
            "indexing": {
                "value": best_idx.get("indexing_time_s", 0),
                "config": config_summary(best_idx),
            },
        },
    }


def show_results(cloud: str) -> None:
    """Display all benchmark results for a cloud in a table format."""
    data = format_results(cloud)

    if not data:
        print(f"No results found for {cloud}")
        return

    print(f"\n{'=' * 100}")
    print(f"Meilisearch Benchmark Results - {cloud.upper()}")
    print(f"{'=' * 100}")

    print(
        f"{'#':>3} {'CPU':>4} {'RAM':>4} {'Disk':<9} {'Mem MB':>7} {'Thr':>4} "
        f"{'QPS':>8} {'p50':>7} {'p95':>7} {'p99':>7} {'Idx(s)':>8}"
    )
    print("-" * 100)

    for i, r in enumerate(data["rows"], 1):
        print(
            f"{i:>3} {r['cpu']:>4} {r['ram']:>4} {r['disk']:<9} {r['mem_mb']:>7} {r['threads']:>4} "
            f"{r['qps']:>8.1f} {r['p50']:>7.1f} {r['p95']:>7.1f} {r['p99']:>7.1f} {r['idx_time']:>8.1f}"
        )

    print("-" * 100)
    print(f"Total: {len(data['rows'])} results")

    best = data["best"]
    print(
        f"\nBest by QPS:      {best['qps']['value']:>8.1f} {'QPS':<6} [{best['qps']['config']}]"
    )
    print(
        f"Best by p95:      {best['p95']['value']:>8.1f} {'ms':<6} [{best['p95']['config']}]"
    )
    print(
        f"Best by indexing: {best['indexing']['value']:>8.1f} {'sec':<6} [{best['indexing']['config']}]"
    )


def export_results_md(cloud: str, output_path: Path | None = None) -> None:
    """Export benchmark results to a markdown file."""
    data = format_results(cloud)

    if not data:
        print(f"No results found for {cloud}")
        return

    if output_path is None:
        output_path = RESULTS_DIR / f"RESULTS_{cloud.upper()}.md"

    lines = [
        f"# Meilisearch Benchmark Results - {cloud.upper()}",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Results",
        "",
        "| # | CPU | RAM | Disk | Mem MB | Thr | QPS | p50 (ms) | p95 (ms) | p99 (ms) | Idx (s) |",
        "|--:|----:|----:|------|-------:|----:|----:|---------:|---------:|---------:|--------:|",
    ]

    for i, r in enumerate(data["rows"], 1):
        lines.append(
            f"| {i} | {r['cpu']} | {r['ram']} | {r['disk']} | {r['mem_mb']} | {r['threads']} | "
            f"{r['qps']:.1f} | {r['p50']:.1f} | {r['p95']:.1f} | {r['p99']:.1f} | {r['idx_time']:.1f} |"
        )

    best = data["best"]
    lines.extend(
        [
            "",
            "## Best Configurations",
            "",
            f"- **Best by QPS:** {best['qps']['value']:.1f} QPS — `{best['qps']['config']}`",
            f"- **Best by p95 latency:** {best['p95']['value']:.1f}ms — `{best['p95']['config']}`",
            f"- **Best by indexing time:** {best['indexing']['value']:.1f}s — `{best['indexing']['config']}`",
            "",
        ]
    )

    output_path.write_text("\n".join(lines))
    print(f"Results exported to {output_path}")


def objective_infra(
    trial: optuna.Trial,
    cloud: str,
    cloud_config: CloudConfig,
    metric: str = "p95_ms",
) -> float:
    """Objective function for infrastructure optimization."""
    space = get_infra_search_space()

    infra_config = {
        "cpu": trial.suggest_categorical("cpu", space["cpu"]),
        "ram_gb": trial.suggest_categorical("ram_gb", space["ram_gb"]),
        "disk_type": trial.suggest_categorical("disk_type", space["disk_type"]),
    }

    print(f"\n{'=' * 60}")
    print(f"Trial {trial.number} [infra]: {infra_config}")
    print(f"{'=' * 60}")

    # Check cache
    cached = find_cached_result(infra_config, {}, cloud)
    if cached:
        cached_value = get_metric_value(cached, metric)
        print(f"  Using cached result: {cached_value:.2f} ({metric})")
        return cached_value

    # Destroy and recreate
    print("  Destroying previous VM...")
    destroy_all(cloud_config.terraform_dir, cloud_config.name)
    time.sleep(5)

    try:
        benchmark_ip, meili_ip = ensure_infra(cloud_config, infra_config)
    except Exception as e:
        print(f"  Failed to create infrastructure: {e}")
        raise optuna.TrialPruned("Infrastructure creation failed")

    # Index dataset
    indexing_time = upload_and_index_dataset(benchmark_ip, meili_ip)
    if indexing_time < 0:
        raise optuna.TrialPruned("Indexing failed")

    # Run benchmark
    vus = infra_config["cpu"] * 2
    result = run_k6_benchmark(benchmark_ip, meili_ip, vus=vus, duration=60)

    if result.error:
        print(f"  Benchmark failed: {result.error}")
        raise optuna.TrialPruned(result.error)

    print(f"  Result: {result.qps:.1f} QPS, p95={result.p95_ms:.1f}ms")

    save_result(
        result,
        infra_config,
        {},
        trial.number,
        cloud,
        cloud_config,
        indexing_time,
    )

    # Return metric (minimize p95, maximize qps)
    if metric == "p95_ms":
        return result.p95_ms
    elif metric == "qps":
        return result.qps
    else:
        return result.p95_ms


def objective_config(
    trial: optuna.Trial,
    cloud: str,
    cloud_config: CloudConfig,
    benchmark_ip: str,
    meili_ip: str,
    infra_config: dict,
    metric: str = "p95_ms",
) -> float:
    """Objective function for config optimization."""
    space = get_config_search_space()

    config = {
        "max_indexing_memory_mb": trial.suggest_categorical(
            "max_indexing_memory_mb", space["max_indexing_memory_mb"]
        ),
        "max_indexing_threads": trial.suggest_categorical(
            "max_indexing_threads", space["max_indexing_threads"]
        ),
    }

    print(f"\n{'=' * 60}")
    print(f"Trial {trial.number} [config]: {config}")
    print(f"{'=' * 60}")

    # Check cache
    cached = find_cached_result(infra_config, config, cloud)
    if cached:
        cached_value = get_metric_value(cached, metric)
        print(f"  Using cached result: {cached_value:.2f} ({metric})")
        return cached_value

    # Reconfigure and re-index
    if not reconfigure_meilisearch(meili_ip, config, jump_host=benchmark_ip):
        raise optuna.TrialPruned("Meilisearch config failed")

    # Re-index to test indexing performance with new settings
    # First delete existing index
    delete_cmd = f"""
curl -sf -X DELETE 'http://{meili_ip}:7700/indexes/products' \\
  -H 'Authorization: Bearer {MASTER_KEY}'
"""
    run_ssh_command(benchmark_ip, delete_cmd, timeout=30)
    time.sleep(2)

    indexing_time = upload_and_index_dataset(benchmark_ip, meili_ip)
    if indexing_time < 0:
        raise optuna.TrialPruned("Indexing failed")

    # Run benchmark
    vus = infra_config.get("cpu", 4) * 2
    result = run_k6_benchmark(benchmark_ip, meili_ip, vus=vus, duration=60)

    if result.error:
        print(f"  Benchmark failed: {result.error}")
        raise optuna.TrialPruned(result.error)

    print(
        f"  Result: {result.qps:.1f} QPS, p95={result.p95_ms:.1f}ms, indexing={indexing_time:.1f}s"
    )

    save_result(
        result,
        infra_config,
        config,
        trial.number,
        cloud,
        cloud_config,
        indexing_time,
    )

    if metric == "p95_ms":
        return result.p95_ms
    elif metric == "qps":
        return result.qps
    elif metric == "indexing_time":
        return indexing_time
    else:
        return result.p95_ms


def main():
    parser = argparse.ArgumentParser(description="Meilisearch Configuration Optimizer")
    parser.add_argument(
        "--cloud",
        "-c",
        required=True,
        choices=["selectel", "timeweb"],
        help="Cloud provider",
    )
    parser.add_argument(
        "--mode",
        "-m",
        required=True,
        choices=["infra", "config", "full"],
        help="Optimization mode",
    )
    parser.add_argument("--trials", "-t", type=int, default=10, help="Number of trials")
    parser.add_argument(
        "--metric",
        default="p95_ms",
        choices=["p95_ms", "qps", "indexing_time"],
        help="Metric to optimize",
    )
    parser.add_argument("--cpu", type=int, default=4, help="Fixed CPU for config mode")
    parser.add_argument(
        "--ram", type=int, default=8, help="Fixed RAM GB for config mode"
    )
    parser.add_argument(
        "--no-destroy",
        action="store_true",
        help="Keep infrastructure after optimization",
    )
    parser.add_argument(
        "--show-results", action="store_true", help="Show results and exit"
    )

    args = parser.parse_args()
    cloud_config = get_cloud_config(args.cloud)

    # Determine direction
    direction = "minimize" if args.metric == "p95_ms" else "maximize"
    if args.metric == "indexing_time":
        direction = "minimize"

    print(f"\nMeilisearch Optimizer - {cloud_config.name} [{args.mode}]")
    print(f"Metric: {args.metric} ({direction})")
    print(f"Trials: {args.trials}")

    if args.show_results:
        show_results(args.cloud)
        export_results_md(args.cloud)
        return

    try:
        if args.mode == "infra":
            study = optuna.create_study(
                study_name=f"meilisearch-{args.cloud}-infra-{args.metric}",
                storage=f"sqlite:///{STUDY_DB}",
                load_if_exists=True,
                direction=direction,
                sampler=TPESampler(seed=42),
            )

            study.optimize(
                lambda trial: objective_infra(
                    trial, args.cloud, cloud_config, args.metric
                ),
                n_trials=args.trials,
                catch=(optuna.TrialPruned,),
            )

        elif args.mode == "config":
            infra_config = {
                "cpu": args.cpu,
                "ram_gb": args.ram,
                "disk_type": "fast",
            }

            benchmark_ip, meili_ip = ensure_infra(cloud_config, infra_config)

            # Initial indexing
            upload_and_index_dataset(benchmark_ip, meili_ip)

            study = optuna.create_study(
                study_name=f"meilisearch-{args.cloud}-config-{args.metric}",
                storage=f"sqlite:///{STUDY_DB}",
                load_if_exists=True,
                direction=direction,
                sampler=TPESampler(seed=42),
            )

            study.optimize(
                lambda trial: objective_config(
                    trial,
                    args.cloud,
                    cloud_config,
                    benchmark_ip,
                    meili_ip,
                    infra_config,
                    args.metric,
                ),
                n_trials=args.trials,
                catch=(optuna.TrialPruned,),
            )

        elif args.mode == "full":
            # Phase 1: Infra
            infra_trials = args.trials // 2
            print(
                f"\n=== Phase 1: Infrastructure optimization ({infra_trials} trials) ==="
            )

            study_infra = optuna.create_study(
                study_name=f"meilisearch-{args.cloud}-full-infra-{args.metric}",
                storage=f"sqlite:///{STUDY_DB}",
                load_if_exists=True,
                direction=direction,
                sampler=TPESampler(seed=42),
            )

            study_infra.optimize(
                lambda trial: objective_infra(
                    trial, args.cloud, cloud_config, args.metric
                ),
                n_trials=infra_trials,
                catch=(optuna.TrialPruned,),
            )

            # Phase 2: Config on best infra
            best_infra = study_infra.best_params
            infra_config = {
                "cpu": best_infra["cpu"],
                "ram_gb": best_infra["ram_gb"],
                "disk_type": best_infra["disk_type"],
            }

            config_trials = args.trials - infra_trials
            print(
                f"\n=== Phase 2: Config optimization on best host ({config_trials} trials) ==="
            )
            print(f"Best infra: {infra_config}")

            destroy_all(cloud_config.terraform_dir, cloud_config.name)
            benchmark_ip, meili_ip = ensure_infra(cloud_config, infra_config)
            upload_and_index_dataset(benchmark_ip, meili_ip)

            study_config = optuna.create_study(
                study_name=f"meilisearch-{args.cloud}-full-config-{args.metric}",
                storage=f"sqlite:///{STUDY_DB}",
                load_if_exists=True,
                direction=direction,
                sampler=TPESampler(seed=42),
            )

            study_config.optimize(
                lambda trial: objective_config(
                    trial,
                    args.cloud,
                    cloud_config,
                    benchmark_ip,
                    meili_ip,
                    infra_config,
                    args.metric,
                ),
                n_trials=config_trials,
                catch=(optuna.TrialPruned,),
            )

            print("\n=== Best Configuration ===")
            print(f"Infra: {infra_config}")
            print(f"Config: {study_config.best_params}")
            print(f"Best {args.metric}: {study_config.best_value}")

        # Auto-export results to markdown
        export_results_md(args.cloud)
        print(f"\nResults exported to RESULTS_{args.cloud.upper()}.md")

    finally:
        if not args.no_destroy:
            print("\nCleaning up...")
            destroy_all(cloud_config.terraform_dir, cloud_config.name)


if __name__ == "__main__":
    main()
