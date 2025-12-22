import type { QueryDefinition } from "./types.js";

/**
 * Benchmark queries for indexless tables.
 * These queries demonstrate full table scans and columnar storage benefits.
 */
export const QUERIES: QueryDefinition[] = [
  {
    name: "full-count",
    description: "Count all rows in the table",
    sql: {
      postgres: "SELECT COUNT(*) FROM samples",
      clickhouse: "SELECT COUNT(*) FROM samples",
      trino: "SELECT COUNT(*) FROM iceberg.benchmarks.samples",
    },
  },
  {
    name: "filter-by-status",
    description: "Filter rows by status column",
    sql: {
      postgres: "SELECT COUNT(*) FROM samples WHERE status = 'active'",
      clickhouse: "SELECT COUNT(*) FROM samples WHERE status = 'active'",
      trino: "SELECT COUNT(*) FROM iceberg.benchmarks.samples WHERE status = 'active'",
    },
  },
  {
    name: "aggregate-by-status",
    description: "Group by status with aggregation",
    sql: {
      postgres: "SELECT status, COUNT(*), AVG(value) FROM samples GROUP BY status",
      clickhouse: "SELECT status, COUNT(*), AVG(value) FROM samples GROUP BY status",
      trino: "SELECT status, COUNT(*), AVG(value) FROM iceberg.benchmarks.samples GROUP BY status",
    },
  },
  {
    name: "range-scan",
    description: "Range scan on value column",
    sql: {
      postgres: "SELECT COUNT(*) FROM samples WHERE value BETWEEN 100 AND 500",
      clickhouse: "SELECT COUNT(*) FROM samples WHERE value BETWEEN 100 AND 500",
      trino: "SELECT COUNT(*) FROM iceberg.benchmarks.samples WHERE value BETWEEN 100 AND 500",
    },
  },
  {
    name: "top-n",
    description: "Get top N rows by value",
    sql: {
      postgres: "SELECT * FROM samples ORDER BY value DESC LIMIT 100",
      clickhouse: "SELECT * FROM samples ORDER BY value DESC LIMIT 100",
      trino: "SELECT * FROM iceberg.benchmarks.samples ORDER BY value DESC LIMIT 100",
    },
  },
  {
    name: "string-like",
    description: "String pattern matching (full scan)",
    sql: {
      postgres: "SELECT COUNT(*) FROM samples WHERE name LIKE '%abc%'",
      clickhouse: "SELECT COUNT(*) FROM samples WHERE name LIKE '%abc%'",
      trino: "SELECT COUNT(*) FROM iceberg.benchmarks.samples WHERE name LIKE '%abc%'",
    },
  },
  {
    name: "distinct-count",
    description: "Count distinct values",
    sql: {
      postgres: "SELECT COUNT(DISTINCT status) FROM samples",
      clickhouse: "SELECT COUNT(DISTINCT status) FROM samples",
      trino: "SELECT COUNT(DISTINCT status) FROM iceberg.benchmarks.samples",
    },
  },
  {
    name: "percentile",
    description: "Calculate percentiles",
    sql: {
      postgres:
        "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY value), PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY value) FROM samples",
      clickhouse: "SELECT quantile(0.5)(value), quantile(0.95)(value) FROM samples",
      trino:
        "SELECT approx_percentile(value, 0.5), approx_percentile(value, 0.95) FROM iceberg.benchmarks.samples",
    },
  },
  {
    name: "pagination-offset",
    description: "Deep pagination with OFFSET (unordered)",
    sql: {
      postgres: "SELECT * FROM samples OFFSET 10000 LIMIT 10",
      clickhouse: "SELECT * FROM samples LIMIT 10 OFFSET 10000",
      trino: "SELECT * FROM iceberg.benchmarks.samples OFFSET 10000 LIMIT 10",
    },
  },
  {
    name: "pagination-offset-ordered",
    description: "Deep pagination with OFFSET (ordered)",
    sql: {
      postgres: "SELECT * FROM samples ORDER BY value OFFSET 10000 LIMIT 10",
      clickhouse: "SELECT * FROM samples ORDER BY value LIMIT 10 OFFSET 10000",
      trino: "SELECT * FROM iceberg.benchmarks.samples ORDER BY value OFFSET 10000 LIMIT 10",
    },
  },
  {
    name: "dedupe",
    description: "Select distinct rows by multiple columns",
    sql: {
      postgres: "SELECT DISTINCT status, name FROM samples",
      clickhouse: "SELECT DISTINCT status, name FROM samples",
      trino: "SELECT DISTINCT status, name FROM iceberg.benchmarks.samples",
    },
  },
  {
    name: "filter-join",
    description: "Filter with JOIN on lookup table",
    sql: {
      postgres:
        "SELECT COUNT(*) FROM samples s JOIN categories c ON s.category_id = c.id WHERE c.priority = 'high'",
      clickhouse:
        "SELECT COUNT(*) FROM samples s JOIN categories c ON s.category_id = c.id WHERE c.priority = 'high'",
      trino:
        "SELECT COUNT(*) FROM iceberg.benchmarks.samples s JOIN iceberg.benchmarks.categories c ON s.category_id = c.id WHERE c.priority = 'high'",
    },
  },
  {
    name: "aggregate-join",
    description: "Aggregate with JOIN on lookup table",
    sql: {
      postgres:
        "SELECT c.priority, COUNT(*), AVG(s.value) FROM samples s JOIN categories c ON s.category_id = c.id GROUP BY c.priority",
      clickhouse:
        "SELECT c.priority, COUNT(*), AVG(s.value) FROM samples s JOIN categories c ON s.category_id = c.id GROUP BY c.priority",
      trino:
        "SELECT c.priority, COUNT(*), AVG(s.value) FROM iceberg.benchmarks.samples s JOIN iceberg.benchmarks.categories c ON s.category_id = c.id GROUP BY c.priority",
    },
  },
];
