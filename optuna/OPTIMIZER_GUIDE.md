# Optimizer Writing Guide

This document describes patterns and rules for writing Bayesian optimizers in this project.

## Architecture Overview

```
optuna/
├── common.py              # Shared utilities (SSH, Terraform, results I/O)
├── {service}-optimizer/
│   ├── optimizer.py       # Main optimizer script
│   ├── benchmark.js       # k6 benchmark script (if HTTP-based)
│   ├── study.db           # Optuna study database (per service)
│   └── README.md          # Service-specific documentation
```

## Required Components

### Cloud Configuration

```python
@dataclass
class CloudConfig:
    name: str              # "selectel", "timeweb"
    terraform_dir: Path    # Path to terraform directory
    disk_types: list[str]  # Available disk types (from pricing.py)
    cpu_cost: float        # Cost per vCPU per month (from common pricing)
    ram_cost: float        # Cost per GB RAM per month
    disk_cost_multipliers: dict[str, float]  # Per disk type

def get_cloud_config(cloud: str) -> CloudConfig:
    pricing = get_cloud_pricing(cloud)  # From pricing.py
    return CloudConfig(
        name=cloud,
        terraform_dir=TERRAFORM_BASE / cloud,
        disk_types=get_disk_types(cloud),  # Derived from pricing.py
        cpu_cost=pricing.cpu_cost,
        ram_cost=pricing.ram_cost,
        disk_cost_multipliers=pricing.disk_cost_multipliers,
    )
```

### Common Pricing

Cloud pricing rates are defined in `pricing.py` and shared across all optimizers:

```python
from pricing import get_cloud_pricing, get_disk_types
from pricing import get_cloud_pricing, CloudPricing

# Returns CloudPricing(cpu_cost=655, ram_cost=238, disk_cost_multipliers={...})
pricing = get_cloud_pricing("selectel")
```

| Cloud    | CPU (₽/vCPU/mo) | RAM (₽/GB/mo) | Disk (₽/GB/mo)                                                |
| -------- | --------------- | ------------- | ------------------------------------------------------------- |
| Selectel | 655             | 238           | fast: 39, universal: 18, universal2: 9, basicssd: 9, basic: 7 |
| Timeweb  | 220             | 180           | nvme: 5, ssd: 4, hdd: 2                                       |

### Cloud Constraints

Cloud providers have minimum RAM requirements per CPU. These constraints are defined in `pricing.py`:

| vCPU | Min RAM (Selectel) |
| ---- | ------------------ |
| 2    | 2 GB               |
| 4    | 4 GB               |
| 8    | 8 GB               |
| 16   | 32 GB              |

Use `filter_valid_ram()` from `pricing.py` to constrain Optuna's search space **before** suggesting:

```python
from pricing import filter_valid_ram

# In objective_infra():
cpu = trial.suggest_categorical("cpu", space["cpu"])
valid_ram = filter_valid_ram(cloud, cpu, space["ram_gb"])

infra_config = {
    "cpu": cpu,
    # IMPORTANT: Use CPU-specific parameter name for RAM!
    # Optuna's CategoricalDistribution doesn't support dynamic value spaces.
    # Using f"ram_gb_cpu{cpu}" creates separate distributions per CPU.
    "ram_gb": trial.suggest_categorical(f"ram_gb_cpu{cpu}", valid_ram),
    ...
}
```

**Why CPU-specific RAM parameter names?**

Optuna's `CategoricalDistribution` rejects different choice sets for the same parameter name
when using RDB storage (`study.db`). For example, if trial 1 uses `ram_gb=[4,8,16,32]` for cpu=4,
and trial 2 tries to use `ram_gb=[32]` for cpu=16, Optuna throws:
`CategoricalDistribution does not support dynamic value space`

The solution is to use CPU-specific names like `ram_gb_cpu4`, `ram_gb_cpu16` so each CPU
configuration gets its own fixed distribution.

This approach is better than pruning because:

- No wasted trials on invalid configs
- Optuna learns only from valid parameter space
- Cleaner trial history

This is **required** for all optimizers with infrastructure optimization.

### Trial Timings Dataclass

Track timing for each phase of a trial for analysis and debugging:

```python
@dataclass
class TrialTimings:
    """Timing measurements for each phase of a trial."""

    terraform_s: float = 0.0      # Terraform apply
    vm_ready_s: float = 0.0       # Wait for VM cloud-init
    service_ready_s: float = 0.0  # Wait for service to start
    data_load_s: float = 0.0      # Load test data (indexing, pgbench init, etc.)
    benchmark_s: float = 0.0      # Run benchmark
    trial_total_s: float = 0.0    # End-to-end trial time
```

Timings are populated in the objective function and stored with results:

```python
timings = TrialTimings()
infra_start = time.time()
benchmark_ip, service_ip = ensure_infra(cloud_config, infra_config)
timings.terraform_s = time.time() - infra_start

# ... run benchmark ...

timings.trial_total_s = time.time() - trial_start
result.timings = timings
```

### Benchmark Result Dataclass

```python
@dataclass
class BenchmarkResult:
    # Primary metrics (required)
    throughput: float = 0      # QPS, ops/s, MB/s - depends on service
    latency_p50_ms: float = 0
    latency_p95_ms: float = 0
    latency_p99_ms: float = 0

    # Optional metrics
    error_rate: float = 0

    # Error handling
    error: str | None = None

    # Timing data (required)
    timings: TrialTimings | None = None

    def is_valid(self) -> bool:
        return self.error is None and self.throughput > 0
```

### Search Spaces

Define separate functions for infrastructure and configuration parameters:

```python
def get_infra_search_space() -> dict:
    """Infrastructure parameters that require VM recreation."""
    return {
        "cpu": [2, 4, 8, 16],
        "ram_gb": [4, 8, 16, 32],
        "disk_type": ["fast", "universal2", "universal", "basicssd", "basic"],
    }

def get_config_search_space() -> dict:
    """Service configuration that can be changed without VM restart."""
    return {
        "max_connections": (50, 500),    # (min, max) for int range
        "cache_size_mb": (64, 4096),
        "enable_feature": [True, False],  # List for categorical
    }
```

### Caching Functions

**Required for all optimizers** to avoid re-running expensive benchmarks:

```python
def results_file() -> Path:
    """Return path to JSON results cache."""
    return Path(__file__).parent / "results.json"
```

All optimizers use a single `results.json` file.
Cloud is included in `config_to_key()` to ensure uniqueness across providers.

```python
def config_to_key(infra: dict, config: dict, cloud: str) -> str:
    """Create unique key from config for deduplication. Cloud is part of key."""
    return json.dumps({"cloud": cloud, "infra": infra, "config": config}, sort_keys=True)

def find_cached_result(infra: dict, config: dict, cloud: str) -> dict | None:
    """Search cache for existing result."""
    key = config_to_key(infra, config, cloud)
    for r in load_results(results_file()):
        cached_key = config_to_key(
            r.get("infra", {}), r.get("config", {}), r.get("cloud", "")
        )
        if cached_key == key:
            if r.get("error") or r.get("throughput", 0) <= 0:
                continue  # Skip failed results
            return r
    return None

def save_result(cloud: str, infra: dict, config: dict,
                result: BenchmarkResult, trial_num: int,
                cloud_config: CloudConfig) -> None:
    """Save benchmark result to cache."""
    path = results_file()
    results = load_results(path)

    # Calculate cost and efficiency
    cost = calculate_cost(infra, cloud_config)
    cost_efficiency = result.throughput / cost if cost > 0 else 0

    # Convert timings to dict for JSON serialization
    timings_dict = None
    if result.timings:
        timings_dict = {
            "terraform_s": result.timings.terraform_s,
            "vm_ready_s": result.timings.vm_ready_s,
            "benchmark_s": result.timings.benchmark_s,
            "trial_total_s": result.timings.trial_total_s,
        }

    results.append({
        "trial": trial_num,
        "timestamp": datetime.now().isoformat(),
        "cloud": cloud,  # Store cloud for key matching
        "infra": infra,
        "config": config,
        "cost_per_month": cost,           # ₽/mo for this config
        "cost_efficiency": cost_efficiency,  # throughput per ₽/mo
        "metrics": {
            "throughput": result.throughput,
            "latency_p95_ms": result.latency_p95_ms,
            # ... all metrics
        },
        "timings": timings_dict,  # Store timing data for analysis
    })
    save_results(results, path)

    # Auto-export markdown after each trial for live updates
    export_results_md(cloud)
```

### Infrastructure Management

```python
def ensure_infra(cloud_config: CloudConfig, infra_config: dict) -> tuple[str, str]:
    """Create or update infrastructure. Returns (benchmark_ip, service_ip)."""
    tf = get_terraform(cloud_config.terraform_dir)

    # Check if VM exists with matching specs
    current_ip = get_tf_output(tf, "benchmark_vm_ip")
    if current_ip and validate_vm_exists(current_ip):
        current_specs = get_tf_output(tf, "vm_specs")
        if specs_match(current_specs, infra_config):
            return current_ip, get_tf_output(tf, "service_ip")

    # Apply new infrastructure
    tf_vars = build_tf_vars(infra_config)
    ret_code, stdout, stderr = tf.apply(skip_plan=True, var=tf_vars)

    if ret_code != 0:
        raise RuntimeError(f"Failed to create infrastructure: {stderr}")

    return get_tf_output(tf, "benchmark_vm_ip"), get_tf_output(tf, "service_ip")
```

### Benchmark Execution

```python
def run_benchmark(benchmark_ip: str, service_ip: str,
                  config: dict) -> BenchmarkResult:
    """Execute benchmark and return metrics."""

    # 1. Configure service with new settings
    if not apply_config(benchmark_ip, service_ip, config):
        return BenchmarkResult(error="Failed to apply config")

    # 2. Wait for service ready
    if not wait_for_service_ready(service_ip):
        return BenchmarkResult(error="Service not ready")

    # 3. Run benchmark tool (k6, pgbench, memtier, warp, etc.)
    code, output = run_ssh_command(benchmark_ip, benchmark_cmd, timeout=300)

    # 4. Parse results
    return parse_benchmark_output(output)
```

### Result Parsing (for k6)

Use `raw_decode` to handle extra data after JSON:

```python
def parse_k6_results(results_json: str) -> BenchmarkResult:
    """Parse k6 JSON results with robust error handling."""
    try:
        decoder = json.JSONDecoder()
        content = results_json.strip()
        start_idx = content.find("{")
        if start_idx == -1:
            return BenchmarkResult(error="No JSON found in k6 results")

        json_content, _ = decoder.raw_decode(content, start_idx)
        metrics = json_content.get("metrics", {})

        return BenchmarkResult(
            throughput=metrics.get("http_reqs", {}).get("rate", 0),
            latency_p95_ms=metrics.get("latency_ms", {}).get("p(95)", 0),
            # ...
        )
    except json.JSONDecodeError as e:
        return BenchmarkResult(error=f"Failed to parse results: {e}")
```

### Optuna Objective Function

```python
def objective(trial: optuna.Trial, cloud_config: CloudConfig,
              metric: str, fixed_infra: dict | None = None) -> float:
    """Optuna objective function."""

    # 1. Sample parameters
    if fixed_infra:
        infra = fixed_infra
    else:
        infra = {
            "cpu": trial.suggest_categorical("cpu", [2, 4, 8, 16]),
            "ram_gb": trial.suggest_categorical("ram_gb", [4, 8, 16, 32]),
        }

    config = {
        "max_connections": trial.suggest_int("max_connections", 50, 500),
        "cache_mb": trial.suggest_int("cache_mb", 64, 4096, log=True),
    }

    # 2. Check cache first
    cached = find_cached_result(infra, config, cloud_config.name, mode)
    if cached:
        print(f"  Using cached result")
        return get_metric_value(cached, metric)

    # 3. Create/update infrastructure
    try:
        benchmark_ip, service_ip = ensure_infra(cloud_config, infra)
    except RuntimeError as e:
        print(f"  Infrastructure failed: {e}")
        raise optuna.TrialPruned()

    # 4. Run benchmark
    result = run_benchmark(benchmark_ip, service_ip, config)

    if not result.is_valid():
        print(f"  Benchmark failed: {result.error}")
        raise optuna.TrialPruned()

    # 5. Save and return
    save_result(cloud_config.name, mode, infra, config, result, trial.number)
    return get_metric_value(result, metric)
```

### Main Function

```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cloud", required=True, choices=["selectel", "timeweb"])
    parser.add_argument("--mode", default="full", choices=["infra", "config", "full"])
    parser.add_argument("--metric", default="throughput",
                        choices=["throughput", "p95_ms", "cost_efficiency"])
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--cpu", type=int, help="Fixed CPU (for config mode)")
    parser.add_argument("--ram", type=int, help="Fixed RAM (for config mode)")
    parser.add_argument("--show-results", action="store_true")
    parser.add_argument("--destroy", action="store_true")
    args = parser.parse_args()

    cloud_config = get_cloud_config(args.cloud)

    if args.show_results:
        show_results(args.cloud)
        return

    if args.destroy:
        destroy_all(cloud_config.terraform_dir, cloud_config.name)
        return

    # Create/load Optuna study
    # Include metric in study name to prevent direction mismatch when reusing study
    storage = f"sqlite:///{Path(__file__).parent}/study.db"
    study_name = f"{SERVICE_NAME}-{args.cloud}-{args.mode}-{args.metric}"

    direction = "maximize" if args.metric == "throughput" else "minimize"
    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        direction=direction,
        load_if_exists=True,
    )

    # Build objective with fixed params
    fixed_infra = None
    if args.mode == "config":
        fixed_infra = {"cpu": args.cpu, "ram_gb": args.ram, "disk_type": "fast"}

    try:
        study.optimize(
            lambda t: objective(t, cloud_config, args.metric, fixed_infra),
            n_trials=args.trials,
        )
    finally:
        if not args.keep_infra:
            destroy_all(cloud_config.terraform_dir, cloud_config.name)
```

### Results Display and Export

All optimizers should provide console display and markdown export:

```python
def config_summary(r: dict) -> str:
    """Format config as a compact string for display."""
    infra = r.get("infra", {})
    return f"{infra.get('cpu', 0)}cpu/{infra.get('ram_gb', 0)}gb"


def format_results(cloud: str) -> dict | None:
    """Structure results for display/export. Returns None if no results."""
    results = load_results(results_file())
    results = [r for r in results if r.get("cloud", "") == cloud]
    if not results:
        return None

    # Sort by primary metric, extract rows, find best configs
    return {"cloud": cloud, "rows": [...], "best": {...}}


def show_results(cloud: str) -> None:
    """Display results table to console."""
    data = format_results(cloud)
    if not data:
        print(f"No results found for {cloud}")
        return
    # Print formatted table


def export_results_md(cloud: str, output_path: Path | None = None) -> None:
    """Export results to RESULTS_{CLOUD}.md markdown file."""
    data = format_results(cloud)
    if not data:
        return

    if output_path is None:
        output_path = RESULTS_DIR / f"RESULTS_{cloud.upper()}.md"

    lines = [
        f"# {SERVICE_NAME} Benchmark Results - {cloud.upper()}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Results",
        "| # | ... |",  # Table header
        "|--:|...|",    # Alignment
    ]
    # Add rows and best configs
    output_path.write_text("\n".join(lines))
```

## Optimization Modes

| Mode     | Infrastructure | Config   | Use Case                |
| -------- | -------------- | -------- | ----------------------- |
| `infra`  | Variable       | Fixed    | Find best VM specs      |
| `config` | Fixed          | Variable | Tune service parameters |
| `full`   | Variable       | Variable | Complete optimization   |

## Common Pitfalls

### JSON Parsing

Always use `json.JSONDecoder().raw_decode()` for k6 output - it may have extra data after the JSON.

### SSH Timeouts

Long-running benchmarks need increased timeouts:

```python
run_ssh_command(vm_ip, cmd, timeout=600)  # 10 minutes for benchmarks
```

### Stale Terraform State

VMs may be deleted externally. Always validate before reusing:

```python
if current_ip and validate_vm_exists(current_ip):
    # VM exists, can reuse
```

### Pruned Trials

Infrastructure failures should prune the trial, not crash:

```python
raise optuna.TrialPruned()  # Not raise RuntimeError
```

## Shared Utilities (common.py)

| Function                            | Purpose                            |
| ----------------------------------- | ---------------------------------- |
| `run_ssh_command()`                 | Execute command on remote VM       |
| `wait_for_vm_ready()`               | Wait for cloud-init completion     |
| `get_terraform()`                   | Get initialized Terraform instance |
| `get_tf_output()`                   | Get Terraform output value         |
| `destroy_all()`                     | Destroy all Terraform resources    |
| `load_results()` / `save_results()` | JSON cache I/O                     |

## Checklist for New Optimizer

- [ ] `CloudConfig` dataclass with terraform directory and pricing (use `get_cloud_pricing()`)
- [ ] `BenchmarkResult` dataclass with all metrics and `timings: TrialTimings`
- [ ] `TrialTimings` dataclass for phase timing
- [ ] `calculate_cost()` using common pricing rates
- [ ] `get_infra_search_space()` and `get_config_search_space()`
- [ ] `results_file()`, `config_to_key()`, `find_cached_result()`, `save_result()`
- [ ] `ensure_infra()` with VM validation
- [ ] `run_benchmark()` with timeout handling
- [ ] `parse_*_output()` with error handling
- [ ] `objective_infra()` with `filter_valid_ram()` for cloud constraints
- [ ] `objective_config()` (or single `objective()`)
- [ ] CLI with `--cloud`, `--mode`, `--metric`, `--trials`, `--show-results`, `--destroy`
- [ ] Trial pruning on failures and cached duplicates
