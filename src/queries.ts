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
      postgres: "SELECT COUNT(*) FROM samples WHERE first_name LIKE '%an%'",
      clickhouse: "SELECT COUNT(*) FROM samples WHERE first_name LIKE '%an%'",
      trino: "SELECT COUNT(*) FROM iceberg.benchmarks.samples WHERE first_name LIKE '%an%'",
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
      postgres: "SELECT DISTINCT first_name, last_name FROM samples",
      clickhouse: "SELECT DISTINCT first_name, last_name FROM samples",
      trino: "SELECT DISTINCT first_name, last_name FROM iceberg.benchmarks.samples",
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
  {
    name: "join-multi-filter",
    description: "JOIN with multiple filter conditions",
    sql: {
      postgres:
        "SELECT COUNT(*) FROM samples s JOIN categories c ON s.category_id = c.id WHERE c.priority = 'high' AND c.region = 'north' AND c.is_active = 1",
      clickhouse:
        "SELECT COUNT(*) FROM samples s JOIN categories c ON s.category_id = c.id WHERE c.priority = 'high' AND c.region = 'north' AND c.is_active = 1",
      trino:
        "SELECT COUNT(*) FROM iceberg.benchmarks.samples s JOIN iceberg.benchmarks.categories c ON s.category_id = c.id WHERE c.priority = 'high' AND c.region = 'north' AND c.is_active = 1",
    },
  },
  {
    name: "join-range-filter",
    description: "JOIN with range filter on numeric column",
    sql: {
      postgres:
        "SELECT COUNT(*) FROM samples s JOIN categories c ON s.category_id = c.id WHERE c.weight BETWEEN 25 AND 75",
      clickhouse:
        "SELECT COUNT(*) FROM samples s JOIN categories c ON s.category_id = c.id WHERE c.weight BETWEEN 25 AND 75",
      trino:
        "SELECT COUNT(*) FROM iceberg.benchmarks.samples s JOIN iceberg.benchmarks.categories c ON s.category_id = c.id WHERE c.weight BETWEEN 25 AND 75",
    },
  },
  {
    name: "join-group-multi",
    description: "JOIN with GROUP BY multiple columns",
    sql: {
      postgres:
        "SELECT c.priority, c.region, COUNT(*), AVG(s.value) FROM samples s JOIN categories c ON s.category_id = c.id GROUP BY c.priority, c.region",
      clickhouse:
        "SELECT c.priority, c.region, COUNT(*), AVG(s.value) FROM samples s JOIN categories c ON s.category_id = c.id GROUP BY c.priority, c.region",
      trino:
        "SELECT c.priority, c.region, COUNT(*), AVG(s.value) FROM iceberg.benchmarks.samples s JOIN iceberg.benchmarks.categories c ON s.category_id = c.id GROUP BY c.priority, c.region",
    },
  },
  // Entity resolution queries - find duplicates and match corrupted records
  {
    name: "dup-exact-name",
    description: "Find exact duplicate names (GROUP BY HAVING)",
    sql: {
      postgres:
        "SELECT first_name, last_name, COUNT(*) as cnt FROM samples GROUP BY first_name, last_name HAVING COUNT(*) > 1",
      clickhouse:
        "SELECT first_name, last_name, COUNT(*) as cnt FROM samples GROUP BY first_name, last_name HAVING COUNT(*) > 1",
      trino:
        "SELECT first_name, last_name, COUNT(*) as cnt FROM iceberg.benchmarks.samples GROUP BY first_name, last_name HAVING COUNT(*) > 1",
    },
  },
  {
    name: "dup-group-size",
    description: "Distribution of duplicate group sizes",
    sql: {
      postgres:
        "SELECT cnt, COUNT(*) as groups FROM (SELECT first_name, last_name, COUNT(*) as cnt FROM samples GROUP BY first_name, last_name) sub GROUP BY cnt ORDER BY cnt",
      clickhouse:
        "SELECT cnt, COUNT(*) as groups FROM (SELECT first_name, last_name, COUNT(*) as cnt FROM samples GROUP BY first_name, last_name) GROUP BY cnt ORDER BY cnt",
      trino:
        "SELECT cnt, COUNT(*) as groups FROM (SELECT first_name, last_name, COUNT(*) as cnt FROM iceberg.benchmarks.samples GROUP BY first_name, last_name) sub GROUP BY cnt ORDER BY cnt",
    },
  },
  {
    name: "dup-window-rank",
    description: "Rank duplicates within groups (window function)",
    sql: {
      postgres:
        "SELECT id, first_name, last_name, ROW_NUMBER() OVER (PARTITION BY first_name, last_name ORDER BY id) as rn FROM samples",
      clickhouse:
        "SELECT id, first_name, last_name, ROW_NUMBER() OVER (PARTITION BY first_name, last_name ORDER BY id) as rn FROM samples",
      trino:
        "SELECT id, first_name, last_name, ROW_NUMBER() OVER (PARTITION BY first_name, last_name ORDER BY id) as rn FROM iceberg.benchmarks.samples",
    },
  },
  {
    name: "match-exact",
    description: "Match corrupted to samples by exact email",
    sql: {
      postgres: "SELECT COUNT(*) FROM corrupted c JOIN samples s ON c.email = s.email",
      clickhouse: "SELECT COUNT(*) FROM corrupted c JOIN samples s ON c.email = s.email",
      trino:
        "SELECT COUNT(*) FROM iceberg.benchmarks.corrupted c JOIN iceberg.benchmarks.samples s ON c.email = s.email",
    },
  },
  {
    name: "match-corrupted-exact",
    description: "Match corrupted email to original (should find fewer)",
    sql: {
      postgres: "SELECT COUNT(*) FROM corrupted c JOIN samples s ON c.corrupted_email = s.email",
      clickhouse: "SELECT COUNT(*) FROM corrupted c JOIN samples s ON c.corrupted_email = s.email",
      trino:
        "SELECT COUNT(*) FROM iceberg.benchmarks.corrupted c JOIN iceberg.benchmarks.samples s ON c.corrupted_email = s.email",
    },
  },
  {
    name: "match-self-join",
    description: "Self-join to find duplicate pairs",
    sql: {
      postgres:
        "SELECT COUNT(*) FROM samples a JOIN samples b ON a.first_name = b.first_name AND a.last_name = b.last_name AND a.id < b.id",
      clickhouse:
        "SELECT COUNT(*) FROM samples a JOIN samples b ON a.first_name = b.first_name AND a.last_name = b.last_name AND a.id < b.id",
      trino:
        "SELECT COUNT(*) FROM iceberg.benchmarks.samples a JOIN iceberg.benchmarks.samples b ON a.first_name = b.first_name AND a.last_name = b.last_name AND a.id < b.id",
    },
  },
];
