# indexless-query-benchmarks

Benchmark typical queries on Trino+Iceberg, PostgreSQL, and ClickHouse without indexes.

## Overview

This project benchmarks query performance on tables without traditional indexes, demonstrating how columnar databases and modern storage formats handle full-scan workloads.

### Databases Tested

- **PostgreSQL** - Traditional RDBMS for baseline comparison
- **ClickHouse** - Columnar OLAP database
- **Trino + Iceberg** - Query engine with lakehouse storage

### Query Types

- Full count
- Filter by column
- Group by with aggregation
- Range scans
- Top-N queries
- String pattern matching (LIKE)
- Distinct count
- Percentile calculations

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

Use [@mkven/samples-generation](https://www.npmjs.com/package/@mkven/samples-generation) to populate tables:

```bash
# Generate 1 million rows in all databases
npx tsx node_modules/@mkven/samples-generation/scripts/generate-all.ts -r 1_000_000

# Generate 1 billion rows with batching
npx tsx node_modules/@mkven/samples-generation/scripts/generate-all.ts -r 1_000_000_000 -b 100_000_000
```

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
```

### Stop Databases

```bash
pnpm compose:down

# Remove volumes
pnpm compose:reset
```

## Docker Services

| Service    | Port(s)                    | Credentials           |
| ---------- | -------------------------- | --------------------- |
| PostgreSQL | 5432                       | postgres:postgres     |
| ClickHouse | 8123 (HTTP), 9009 (native) | default:clickhouse    |
| Trino      | 8080                       | trino (no password)   |
| MinIO      | 9000 (S3), 9001 (console)  | minioadmin:minioadmin |
| Nessie     | 19120                      | -                     |

## Development

```bash
# Format, lint, typecheck, test
./check.sh

# Full checks including security
./all-checks.sh
```
