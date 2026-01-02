# Meilisearch Configuration Optimizer

Bayesian optimization for finding the best Meilisearch configuration using Optuna.

## How It Works

1. **Optuna suggests** a configuration (CPU, RAM, indexing settings)
2. **Terraform deploys** Meilisearch VM
3. **Dataset indexed** - 500K synthetic e-commerce products
4. **k6 runs** search benchmark with realistic query patterns
5. **Results logged** to `results_{cloud}.json`
6. **Optuna learns** and suggests next config

## Optimization Modes

| Mode   | Description                                                   |
| ------ | ------------------------------------------------------------- |
| infra  | Tune VM specs (CPU, RAM, disk) - creates new VM per trial     |
| config | Tune Meilisearch config on fixed host - reconfigures existing |
| full   | Two-phase: infra optimization first, then config on best host |

## Setup

```bash
cd optuna
uv sync
```

## Usage

```bash
# Infrastructure optimization
uv run python meilisearch-optimizer/optimizer.py --cloud selectel --mode infra --trials 10

# Config optimization on fixed 8cpu/16gb host
uv run python meilisearch-optimizer/optimizer.py --cloud selectel --mode config --cpu 8 --ram 16 --trials 20

# Full optimization
uv run python meilisearch-optimizer/optimizer.py --cloud selectel --mode full --trials 15

# Optimize for QPS instead of p95 latency
uv run python meilisearch-optimizer/optimizer.py --cloud selectel --mode config --metric qps --trials 10

# Keep infrastructure after optimization
uv run python meilisearch-optimizer/optimizer.py --cloud selectel --mode config --trials 5 --no-destroy

# Show results
uv run python meilisearch-optimizer/optimizer.py --cloud selectel --mode infra --show-results
```

## Configuration Space

### Infrastructure (--mode infra)

| Parameter | Values          | Notes       |
| --------- | --------------- | ----------- |
| cpu       | 2, 4, 8, 16     | vCPU count  |
| ram_gb    | 4, 8, 16, 32    | GB per VM   |
| disk_type | fast, universal | NVMe vs SSD |

### Meilisearch Config (--mode config)

| Parameter              | Values               | Notes            |
| ---------------------- | -------------------- | ---------------- |
| max_indexing_memory_mb | 256, 512, 1024, 2048 | RAM for indexing |
| max_indexing_threads   | 0, 2, 4, 8           | 0 = auto         |

## Metrics

| Metric        | Direction | Description             |
| ------------- | --------- | ----------------------- |
| p95_ms        | Minimize  | 95th percentile latency |
| qps           | Maximize  | Queries per second      |
| indexing_time | Minimize  | Time to index 500K docs |

## Query Patterns

The benchmark uses a realistic mix of search queries:

| Query Type      | Weight | Example                              |
| --------------- | ------ | ------------------------------------ |
| Simple keyword  | 50%    | `laptop`, `phone`, `samsung`         |
| Typo-tolerant   | 20%    | `laptp`, `samsng`, `wirless`         |
| Filtered search | 20%    | `laptop` + `price < 1000`            |
| Phrase + sort   | 10%    | `"gaming laptop"` + `sort=price:asc` |

## Dataset

Synthetic e-commerce products (500K documents), generated using Node.js:

```json
{
  "id": 1,
  "title": "Apple Pro Laptop 5",
  "description": "High-quality laptops from Apple with pro features",
  "brand": "Apple",
  "category": "Laptops",
  "price": 1499.99,
  "rating": 4.5,
  "in_stock": true
}
```

- **Searchable**: title, description, brand
- **Filterable**: category, brand, price, rating, in_stock
- **Sortable**: price, rating

### Local Dataset Generation (TypeScript)

```bash
# Generate 500K products
npx tsx dataset.ts --count 500000 --output products.ndjson

# Generate smaller test set
npx tsx dataset.ts --count 1000 --output test.ndjson
```

## Infrastructure

- **Meilisearch VM**: 10.0.0.40 (internal IP)
- **Benchmark VM**: Public IP (runs k6 load generator)
- Both connected via internal VPC network
