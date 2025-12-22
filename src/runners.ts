import { createClient } from "@clickhouse/client";
import postgres from "postgres";
import { Trino, BasicAuth } from "trino-client";
import type { BenchmarkResult, QueryDefinition } from "./types.js";

export interface DatabaseRunner {
  name: string;
  connect(): Promise<void>;
  disconnect(): Promise<void>;
  runQuery(sql: string): Promise<{ durationMs: number; rowCount: number }>;
}

export class PostgresRunner implements DatabaseRunner {
  name = "postgres";
  private sql: postgres.Sql | null = null;

  connect(): Promise<void> {
    this.sql = postgres({
      host: "localhost",
      port: 5432,
      database: "benchmarks",
      username: "postgres",
      password: "postgres",
    });
    return Promise.resolve();
  }

  async disconnect(): Promise<void> {
    if (this.sql) {
      await this.sql.end();
      this.sql = null;
    }
  }

  async runQuery(query: string): Promise<{ durationMs: number; rowCount: number }> {
    if (!this.sql) throw new Error("Not connected");
    const start = Date.now();
    const result = await this.sql.unsafe(query);
    return { durationMs: Date.now() - start, rowCount: result.length };
  }
}

export class ClickHouseRunner implements DatabaseRunner {
  name = "clickhouse";
  private client: ReturnType<typeof createClient> | null = null;

  connect(): Promise<void> {
    this.client = createClient({
      url: "http://localhost:8123",
      username: "default",
      password: "clickhouse",
      database: "benchmarks",
      request_timeout: 300_000, // 5 minutes for expensive queries like Levenshtein
    });
    return Promise.resolve();
  }

  async disconnect(): Promise<void> {
    if (this.client) {
      await this.client.close();
      this.client = null;
    }
  }

  async runQuery(query: string): Promise<{ durationMs: number; rowCount: number }> {
    if (!this.client) throw new Error("Not connected");
    const start = Date.now();
    const result = await this.client.query({ query, format: "JSONEachRow" });
    const rows: unknown[] = await result.json();
    return { durationMs: Date.now() - start, rowCount: rows.length };
  }
}

export class TrinoRunner implements DatabaseRunner {
  name = "trino";
  private trino: Trino | null = null;

  connect(): Promise<void> {
    this.trino = Trino.create({
      server: "http://localhost:8080",
      catalog: "iceberg",
      schema: "benchmarks",
      auth: new BasicAuth("trino"),
    });
    return Promise.resolve();
  }

  disconnect(): Promise<void> {
    this.trino = null;
    return Promise.resolve();
  }

  async runQuery(query: string): Promise<{ durationMs: number; rowCount: number }> {
    if (!this.trino) throw new Error("Not connected");
    const start = Date.now();
    const queryResult = await this.trino.query(query);

    let rowCount = 0;
    for await (const result of queryResult) {
      const trinoResult = result as { error?: { message: string }; data?: unknown[] };
      if (trinoResult.error) {
        throw new Error(`Trino query failed: ${trinoResult.error.message}`);
      }
      if (trinoResult.data) {
        rowCount += trinoResult.data.length;
      }
    }

    return { durationMs: Date.now() - start, rowCount };
  }
}

export async function runBenchmark(
  runner: DatabaseRunner,
  queryDef: QueryDefinition,
  runs: number
): Promise<BenchmarkResult[]> {
  const sql = queryDef.sql[runner.name as keyof typeof queryDef.sql];
  if (!sql) {
    return [];
  }

  const results: BenchmarkResult[] = [];

  for (let i = 0; i < runs; i++) {
    try {
      const { durationMs, rowCount } = await runner.runQuery(sql);
      results.push({
        query: queryDef.name,
        database: runner.name,
        durationMs,
        rowsReturned: rowCount,
      });
    } catch (error) {
      results.push({
        query: queryDef.name,
        database: runner.name,
        durationMs: 0,
        rowsReturned: 0,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  return results;
}
