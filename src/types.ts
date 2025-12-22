export interface BenchmarkResult {
  query: string;
  database: string;
  durationMs: number;
  rowsReturned: number;
  error?: string;
}

export interface QueryDefinition {
  name: string;
  description: string;
  sql: {
    postgres?: string;
    clickhouse?: string;
    trino?: string;
  };
}

export interface BenchmarkConfig {
  tableName: string;
  rowCount: number;
  warmupRuns: number;
  benchmarkRuns: number;
}
