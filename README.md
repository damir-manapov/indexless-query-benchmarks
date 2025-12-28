# indexless-query-benchmarks

Benchmark typical queries on Trino+Iceberg, PostgreSQL, and ClickHouse without indexes.

## Overview

This project benchmarks query performance on tables without traditional indexes, demonstrating how columnar databases and modern storage formats handle full-scan workloads.

### Assumptions

We assume that query parameters — what to filter, order by, how to join tables, etc. — are dynamic and defined by the user at runtime. Thus, queries are not known beforehand and no indexes can be used in most cases.

This may not be your case. You may heavily constrain what users can configure, find ways to define indexes on the fly, or have someone monitor usage and adjust indexes manually. If so, you should perform measurements with the expected indexes yourself.

### Databases Tested

- **PostgreSQL** - Traditional RDBMS for baseline comparison
- **ClickHouse** - Columnar OLAP database
- **Trino + Iceberg** - Query engine with lakehouse storage

### Query Types

**Basic queries:**

- Full count
- Filter by column
- Group by with aggregation
- Range scans
- Top-N queries
- String pattern matching (LIKE)
- Distinct count
- Percentile calculations
- Deep pagination - unordered (OFFSET)
- Deep pagination - ordered (OFFSET + ORDER BY)
- Deduplication (SELECT DISTINCT)

**JOIN queries:**

- JOIN with filter on lookup table
- JOIN with aggregate on lookup table
- JOIN with multiple filter conditions
- JOIN with range filter
- JOIN with GROUP BY multiple columns

**Deduplication queries:**

- Find duplicate names (GROUP BY HAVING)
- Duplicate group size distribution
- Rank duplicates within groups (window function)

**Matching queries:**

- Match corrupted to samples by exact email
- Match corrupted email to original
- Self-join to find duplicate pairs
- Fuzzy match using Levenshtein distance (expensive)

## Measurements of data generation

All set up done by compose file, minio used as s3 storage.

### Generated entity in Trino

Different count of rows for main table by 100m batches. Id, first, last name from eng dictionaries, float, status, datetime.

### 12 cpu (AMD EPYC 7763 64-Core Processor), 96 ram, fast ssd (25k/15k iops, 500mbs) - selectel

300m total, 100m batch ~56s in 3m 2s, 1,741,988 r/s

600m total, 100m batch ~56s in 6m 6s, 1,721,467 r/s

So writing is definetly linear. It was expected, but worth to check anyway.

### The same, but universal-2 ssd (up to 16k iops, 200mbs) - selectel

One locale minio instance:

- 300m total, 100m batch ~1m 18s in 4m 14s, 1,253,772 r/s
- 600m total, 100m batch ~1m 18s in 8m 17s, 1,274,608 r/s

Cloud selectel S3:

- 300m total, 100m batch
- 600m total, 100m batch ~1m 4s in 6m 42s, 1,557,814 r/s

### The same, but universal-1 ssd (7k/4k iops, 200mbs) - selectel

### The same, but base ssd (640/320 iops, 150mbs) - selectel

### The same, but base hdd (320/120 iops, 100mbs) - selectel

## Prerequisites

- Node.js 24+
- pnpm
- Docker

## Installation

```bash
pnpm install
```

## Cloud Deployment

For running benchmarks on cloud VMs with production MinIO cluster, see [terraform/README.md](terraform/README.md).

Two cloud providers are supported:

- **Selectel** - OpenStack-based, see [terraform/selectel/README.md](terraform/selectel/README.md)
- **Timeweb** - Simple API, see [terraform/timeweb/README.md](terraform/timeweb/README.md)

For automated MinIO configuration optimization using Bayesian search, see [optuna/minio-optimizer/README.md](optuna/minio-optimizer/README.md).

```bash
# Selectel
cd terraform/selectel
export TF_VAR_selectel_domain="123456"
export TF_VAR_selectel_username="your-username"
export TF_VAR_selectel_password="your-password"
export TF_VAR_selectel_openstack_password="your-openstack-password"

# Or Timeweb
cd terraform/timeweb
export TWC_TOKEN="your-api-token"

# Then
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform apply
```

## Usage

### Start Databases

```bash
pnpm compose:up
```

#### Memory-Constrained Environments

For running a single database with specific memory limits (the limit applies to the database container only; ensure your machine has additional RAM for the host OS):

```bash
# 16GB machine
pnpm compose:up:postgres:16gb
pnpm compose:up:clickhouse:16gb
pnpm compose:up:trino:16gb

# 32GB machine
pnpm compose:up:postgres:32gb
pnpm compose:up:clickhouse:32gb
pnpm compose:up:trino:32gb

# 64GB machine
pnpm compose:up:postgres:64gb
pnpm compose:up:clickhouse:64gb
pnpm compose:up:trino:64gb
```

#### MinIO Cluster Mode

For higher S3 throughput, run MinIO in distributed mode with 4 nodes:

```bash
# Start MinIO cluster (4 nodes)
pnpm compose:up:minio-cluster

# Start Trino with MinIO cluster backend
pnpm compose:up:trino:minio-cluster

# Start Trino 64GB with MinIO cluster
pnpm compose:up:trino:64gb:minio-cluster
```

#### Standalone MinIO (Terraform-deployed)

When using MinIO deployed via Terraform (see [terraform/README.md](terraform/README.md)), connect Trino to the external cluster:

```bash
# Start Trino with Terraform-deployed MinIO
pnpm compose:up:trino:standalone-minio

# Or with 64GB memory config
pnpm compose:up:trino:64gb:standalone-minio
```

This uses hardcoded endpoint `10.0.0.10:9000` configured for the Terraform MinIO cluster on the private network.

#### Remote S3 Storage

To use external S3 storage (e.g., Selectel Cloud Storage) instead of local MinIO:

```bash
# Set credentials
export S3_ACCESS_KEY=your-access-key
export S3_SECRET_KEY=your-secret-key

# Start Trino with remote S3
pnpm compose:up:trino:remote-s3

# Or with 64GB memory config
pnpm compose:up:trino:64gb:remote-s3
```

Edit `compose/trino/catalog/iceberg.remote-s3.properties` to configure your S3 endpoint, region, and bucket.

### Generate Test Data

```bash
# Generate 100 million rows in all databases (default)
pnpm generate

# Generate custom row count
pnpm generate -n 1_000_000

# Custom batch size
pnpm generate -n 10_000_000 -b 1_000_000

# Specific database only
pnpm generate:postgres -n 10_000_000
pnpm generate:clickhouse -n 10_000_000
pnpm generate:trino -n 10_000_000

# Generate with report (JSON + Markdown)
pnpm generate --postgres --report

# With environment tag for report metadata
pnpm generate --postgres --env 16gb --report
```

Generation reports are saved to `reports/generation-*.{json,md}` with per-table timing and throughput stats.

Default batch sizes: 1M for PostgreSQL, 100M for ClickHouse/Trino.

### Run Benchmarks

```bash
# All databases, all queries
pnpm benchmark

# Specific database
pnpm benchmark --postgres
pnpm benchmark --clickhouse
pnpm benchmark --trino

# Specific query
pnpm benchmark -q full-count

# Multiple runs
pnpm benchmark -r 5 --warmup 2

# Filter by tags
pnpm benchmark --only matching       # Only matching queries
pnpm benchmark --only deduplication   # Only deduplication queries
pnpm benchmark -x expensive           # Skip expensive queries

# Generate reports (JSON + Markdown)
pnpm benchmark --report

# With environment tag for report metadata
pnpm benchmark --postgres --env 16gb --report
```

Reports are saved to `reports/` directory with timestamped filenames. Each report includes:

- **Table sizes** - Row counts for each table
- **Summary table** - Average times per query across databases
- **Detailed results** - Min/Avg/P95/Max for each query per database

**Available tags:**

| Tag             | Description                                |
| --------------- | ------------------------------------------ |
| `basic`         | Simple single-table queries                |
| `join`          | Queries involving JOINs                    |
| `deduplication` | Finding duplicates within a single table   |
| `matching`      | Linking records between tables             |
| `expensive`     | Queries that may timeout on large datasets |

Reports are saved to `reports/` directory with timestamped filenames.

### Stop Databases

```bash
pnpm compose:down

# Remove volumes
pnpm compose:reset
```

## Docker Services

| Service    | Port(s)                    | Credentials           | Database           |
| ---------- | -------------------------- | --------------------- | ------------------ |
| PostgreSQL | 5432                       | postgres:postgres     | benchmarks         |
| ClickHouse | 8123 (HTTP), 9009 (native) | default:clickhouse    | benchmarks         |
| Trino      | 8080                       | trino (no password)   | iceberg.benchmarks |
| MinIO      | 9000 (S3), 9001 (console)  | minioadmin:minioadmin | -                  |
| Nessie     | 19120                      | -                     | -                  |

## Development

```bash
# Format, lint, typecheck, test
./check.sh

# Full checks including security
./all-checks.sh
```
