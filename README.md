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

## Prerequisites

- Node.js 20+
- pnpm
- Docker

## Installation

```bash
pnpm install
```

## Usage

### Start Databases

```bash
pnpm compose:up
```

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
```

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
pnpm benchmark --exclude expensive    # Skip expensive queries

# Generate reports (JSON + Markdown)
pnpm benchmark --report
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
