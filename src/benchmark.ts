import { parseArgs } from "node:util";
import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import {
  PostgresRunner,
  ClickHouseRunner,
  TrinoRunner,
  runBenchmark,
  type DatabaseRunner,
} from "./runners.js";
import { QUERIES } from "./queries.js";
import { formatDuration, calculateStats } from "./utils.js";

interface QueryResult {
  query: string;
  description: string;
  minMs: number;
  avgMs: number;
  p95Ms: number;
  maxMs: number;
}

interface DatabaseResult {
  database: string;
  results: QueryResult[];
}

interface BenchmarkReport {
  timestamp: string;
  warmupRuns: number;
  benchmarkRuns: number;
  databases: DatabaseResult[];
}

const { values } = parseArgs({
  options: {
    postgres: { type: "boolean", default: false },
    clickhouse: { type: "boolean", default: false },
    trino: { type: "boolean", default: false },
    warmup: { type: "string", default: "1" },
    runs: { type: "string", short: "r", default: "3" },
    query: { type: "string", short: "q" },
    report: { type: "boolean", default: false },
    help: { type: "boolean", short: "h", default: false },
  },
});

if (values.help) {
  console.log(`
Usage: pnpm benchmark [options]

Options:
  --postgres       Run benchmarks on PostgreSQL
  --clickhouse     Run benchmarks on ClickHouse
  --trino          Run benchmarks on Trino
  --warmup <n>     Number of warmup runs (default: 1)
  -r, --runs <n>   Number of benchmark runs (default: 3)
  -q, --query <n>  Run specific query by name
  --report         Generate JSON and Markdown reports in reports/
  -h, --help       Show this help message

If no database is specified, all databases are benchmarked.

Examples:
  pnpm benchmark                          # All databases, all queries
  pnpm benchmark --postgres --trino       # PostgreSQL and Trino only
  pnpm benchmark -q full-count -r 5       # Specific query, 5 runs
  pnpm benchmark --report                 # Generate reports
`);
  process.exit(0);
}

const WARMUP_RUNS = parseInt(values.warmup, 10);
const BENCHMARK_RUNS = parseInt(values.runs, 10);

// If no database specified, run all
const noDbSelected = !values.postgres && !values.clickhouse && !values.trino;
const runPostgres = values.postgres || noDbSelected;
const runClickHouse = values.clickhouse || noDbSelected;
const runTrino = values.trino || noDbSelected;

// Filter queries if specified
const queryFilter = values.query;
const queriesToRun = queryFilter ? QUERIES.filter((q) => q.name === queryFilter) : QUERIES;

if (queryFilter && queriesToRun.length === 0) {
  console.error(`Query "${queryFilter}" not found. Available queries:`);
  QUERIES.forEach((q) => {
    console.error(`  - ${q.name}: ${q.description}`);
  });
  process.exit(1);
}

async function benchmarkDatabase(runner: DatabaseRunner): Promise<DatabaseResult> {
  console.log(`\n=== ${runner.name.toUpperCase()} ===`);
  const dbResult: DatabaseResult = { database: runner.name, results: [] };

  try {
    await runner.connect();
    console.log(`Connected to ${runner.name}`);

    for (const queryDef of queriesToRun) {
      console.log(`\n[${queryDef.name}] ${queryDef.description}`);

      // Warmup
      if (WARMUP_RUNS > 0) {
        console.log(`  Warming up (${String(WARMUP_RUNS)} runs)...`);
        await runBenchmark(runner, queryDef, WARMUP_RUNS);
      }

      // Benchmark
      console.log(`  Benchmarking (${String(BENCHMARK_RUNS)} runs)...`);
      const results = await runBenchmark(runner, queryDef, BENCHMARK_RUNS);

      if (results.length === 0) {
        console.log(`  Skipped (no SQL for ${runner.name})`);
        continue;
      }

      const errors = results.filter((r) => r.error);
      if (errors.length > 0) {
        console.log(`  Errors: ${String(errors.length)}/${String(results.length)}`);
        errors.forEach((e) => {
          console.log(`    - ${e.error ?? "Unknown error"}`);
        });
        continue;
      }

      const durations = results.map((r) => r.durationMs);
      const stats = calculateStats(durations);
      console.log(
        `  Results: min=${formatDuration(stats.min)}, avg=${formatDuration(stats.avg)}, ` +
          `p95=${formatDuration(stats.p95)}, max=${formatDuration(stats.max)}`
      );

      dbResult.results.push({
        query: queryDef.name,
        description: queryDef.description,
        minMs: stats.min,
        avgMs: stats.avg,
        p95Ms: stats.p95,
        maxMs: stats.max,
      });
    }

    await runner.disconnect();
    console.log(`Disconnected from ${runner.name}`);
  } catch (error) {
    console.error(`Error with ${runner.name}:`, error instanceof Error ? error.message : error);
  }

  return dbResult;
}

async function main(): Promise<void> {
  console.log("=== Indexless Query Benchmarks ===");
  console.log(`Warmup: ${String(WARMUP_RUNS)} runs, Benchmark: ${String(BENCHMARK_RUNS)} runs`);
  console.log(`Queries: ${queriesToRun.map((q) => q.name).join(", ")}`);

  const report: BenchmarkReport = {
    timestamp: new Date().toISOString(),
    warmupRuns: WARMUP_RUNS,
    benchmarkRuns: BENCHMARK_RUNS,
    databases: [],
  };

  if (runPostgres) {
    report.databases.push(await benchmarkDatabase(new PostgresRunner()));
  }

  if (runClickHouse) {
    report.databases.push(await benchmarkDatabase(new ClickHouseRunner()));
  }

  if (runTrino) {
    report.databases.push(await benchmarkDatabase(new TrinoRunner()));
  }

  if (values.report) {
    generateReport(report);
  }

  console.log("\n=== Done ===");
}

function generateReport(report: BenchmarkReport): void {
  const reportsDir = "reports";
  mkdirSync(reportsDir, { recursive: true });

  const timestamp = report.timestamp.replace(/[:.]/g, "-").slice(0, 19);

  // JSON report
  const jsonPath = join(reportsDir, `benchmark-${timestamp}.json`);
  writeFileSync(jsonPath, JSON.stringify(report, null, 2));
  console.log(`\nGenerated JSON report: ${jsonPath}`);

  // Markdown report
  const mdPath = join(reportsDir, `benchmark-${timestamp}.md`);
  const md = generateMarkdown(report);
  writeFileSync(mdPath, md);
  console.log(`Generated Markdown report: ${mdPath}`);
}

function generateMarkdown(report: BenchmarkReport): string {
  const lines: string[] = [
    "# Benchmark Report",
    "",
    `**Date:** ${report.timestamp}`,
    `**Warmup Runs:** ${String(report.warmupRuns)}`,
    `**Benchmark Runs:** ${String(report.benchmarkRuns)}`,
    "",
    "## Results",
    "",
  ];

  // Get all unique queries
  const queries = report.databases[0]?.results.map((r) => r.query) ?? [];

  // Header
  const dbNames = report.databases.map((d) => d.database);
  lines.push(`| Query | ${dbNames.join(" | ")} |`);
  lines.push(`|-------|${dbNames.map(() => "------:").join("|")}|`);

  // Rows
  for (const query of queries) {
    const cells = report.databases.map((db) => {
      const result = db.results.find((r) => r.query === query);
      return result ? formatDuration(result.avgMs) : "-";
    });
    lines.push(`| ${query} | ${cells.join(" | ")} |`);
  }

  lines.push("");
  lines.push("## Detailed Results");
  lines.push("");

  for (const db of report.databases) {
    lines.push(`### ${db.database}`);
    lines.push("");
    lines.push("| Query | Min | Avg | P95 | Max |");
    lines.push("|-------|----:|----:|----:|----:|");
    for (const r of db.results) {
      lines.push(
        `| ${r.query} | ${formatDuration(r.minMs)} | ${formatDuration(r.avgMs)} | ${formatDuration(r.p95Ms)} | ${formatDuration(r.maxMs)} |`
      );
    }
    lines.push("");
  }

  return lines.join("\n");
}

main().catch((error: unknown) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
