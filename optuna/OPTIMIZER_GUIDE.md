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

### 1. Cloud Configuration

```python
@dataclass
class CloudConfig:
    name: str              # "selectel", "timeweb"
    terraform_dir: Path    # Path to terraform directory

def get_cloud_config(cloud: str) -> CloudConfig:
    base = Path(__file__).parent.parent.parent / "terraform"
    return CloudConfig(name=cloud.upper(), terraform_dir=base / cloud)
```

### 2. Benchmark Result Dataclass

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

    def is_valid(self) -> bool:
        return self.error is None and self.throughput > 0
```

### 3. Search Spaces

Define separate functions for infrastructure and configuration parameters:

```python
def get_infra_search_space() -> dict:
    """Infrastructure parameters that require VM recreation."""
    return {
        "cpu": [2, 4, 8, 16],
        "ram_gb": [4, 8, 16, 32],
        "disk_type": ["basic", "fast", "universal"],
    }

def get_config_search_space() -> dict:
    """Service configuration that can be changed without VM restart."""
    return {
        "max_connections": (50, 500),    # (min, max) for int range
        "cache_size_mb": (64, 4096),
        "enable_feature": [True, False],  # List for categorical
    }
```

### 4. Caching Functions

**Required for all optimizers** to avoid re-running expensive benchmarks:

```python
def results_file(cloud: str) -> Path:
    """Return path to JSON results cache."""
    return Path(__file__).parent / f"results_{cloud.lower()}.json"
```

All optimizers use a single `results_{cloud}.json` file per cloud provider.
Deduplication is handled by `config_to_key()` which creates a unique hash from the configuration.

```python
def config_to_key(infra: dict, config: dict) -> str:
    """Create unique key from config for deduplication."""
    combined = {**infra, **config}
    return json.dumps(combined, sort_keys=True)

def find_cached_result(infra: dict, config: dict, cloud: str) -> dict | None:
    """Search cache for existing result."""
    key = config_to_key(infra, config)
    for r in load_results(results_file(cloud)):
        if config_to_key(r.get("infra", {}), r.get("config", {})) == key:
            if r.get("error") or r.get("throughput", 0) <= 0:
                continue  # Skip failed results
            return r
    return None

def save_result(cloud: str, infra: dict, config: dict, 
                result: BenchmarkResult, trial_num: int) -> None:
    """Save benchmark result to cache."""
    path = results_file(cloud)
    results = load_results(path)
    results.append({
        "trial": trial_num,
        "timestamp": datetime.now().isoformat(),
        "infra": infra,
        "config": config,
        "metrics": {
            "throughput": result.throughput,
            "latency_p95_ms": result.latency_p95_ms,
            # ... all metrics
        },
    })
    save_results(results, path)
```

### 5. Infrastructure Management

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

### 6. Benchmark Execution

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

### 7. Result Parsing (for k6)

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

### 8. Optuna Objective Function

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

### 9. Main Function

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
        show_results(args.cloud, args.mode)
        return

    if args.destroy:
        destroy_all(cloud_config.terraform_dir, cloud_config.name)
        return

    # Create/load Optuna study
    storage = f"sqlite:///{Path(__file__).parent}/study.db"
    study_name = f"{SERVICE_NAME}-{args.cloud}-{args.mode}"

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

## Optimization Modes

| Mode | Infrastructure | Config | Use Case |
|------|---------------|--------|----------|
| `infra` | Variable | Fixed | Find best VM specs |
| `config` | Fixed | Variable | Tune service parameters |
| `full` | Variable | Variable | Complete optimization |

## Common Pitfalls

### 1. JSON Parsing
Always use `json.JSONDecoder().raw_decode()` for k6 output - it may have extra data after the JSON.

### 2. SSH Timeouts
Long-running benchmarks need increased timeouts:
```python
run_ssh_command(vm_ip, cmd, timeout=600)  # 10 minutes for benchmarks
```

### 3. Stale Terraform State
VMs may be deleted externally. Always validate before reusing:
```python
if current_ip and validate_vm_exists(current_ip):
    # VM exists, can reuse
```

### 4. Pruned Trials
Infrastructure failures should prune the trial, not crash:
```python
raise optuna.TrialPruned()  # Not raise RuntimeError
```

## Shared Utilities (common.py)

| Function | Purpose |
|----------|---------|
| `run_ssh_command()` | Execute command on remote VM |
| `wait_for_vm_ready()` | Wait for cloud-init completion |
| `get_terraform()` | Get initialized Terraform instance |
| `get_tf_output()` | Get Terraform output value |
| `destroy_all()` | Destroy all Terraform resources |
| `load_results()` / `save_results()` | JSON cache I/O |

## Checklist for New Optimizer

- [ ] `CloudConfig` dataclass with terraform directory
- [ ] `BenchmarkResult` dataclass with all metrics
- [ ] `get_infra_search_space()` and `get_config_search_space()`
- [ ] `results_file()`, `config_to_key()`, `find_cached_result()`, `save_result()`
- [ ] `ensure_infra()` with VM validation
- [ ] `run_benchmark()` with timeout handling
- [ ] `parse_*_output()` with error handling
- [ ] `objective_infra()` and `objective_config()` (or single `objective()`)
- [ ] CLI with `--cloud`, `--mode`, `--metric`, `--trials`, `--show-results`, `--destroy`
- [ ] Trial pruning on failures
