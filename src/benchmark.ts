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
import {
  formatDuration,
  calculateStats,
  getEnvironmentInfo,
  type EnvironmentInfo,
} from "./utils.js";

interface QueryResult {
  query: string;
  description: string;
  minMs: number;
  avgMs: number;
  p95Ms: number;
  maxMs: number;
  error?: string;
}

interface TableSize {
  table: string;
  rows: number;
}

interface DatabaseResult {
  database: string;
  tableSizes?: TableSize[];
  results: QueryResult[];
}

interface BenchmarkReport {
  timestamp: string;
  command: string;
  environment: EnvironmentInfo;
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
    exclude: { type: "string", short: "x" },
    only: { type: "string", short: "o" },
    env: { type: "string", short: "e" },
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
  -x, --exclude <tag>  Exclude queries with this tag (e.g., expensive)
  -o, --only <tag>     Run only queries with this tag
  -e, --env <size>     Memory profile (16gb, 32gb, 64gb) for report metadata
  --report         Generate JSON and Markdown reports in reports/
  -h, --help       Show this help message

Tags: basic, join, deduplication, matching, expensive

If no database is specified, all databases are benchmarked.

Examples:
  pnpm benchmark                          # All databases, all queries
  pnpm benchmark --postgres --trino       # PostgreSQL and Trino only
  pnpm benchmark -q full-count -r 5       # Specific query, 5 runs
  pnpm benchmark --exclude expensive      # Skip expensive queries
  pnpm benchmark --only matching          # Only record matching queries
  pnpm benchmark --env 16gb --report      # With environment tag
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
const excludeTag = values.exclude;
const onlyTag = values.only;

let queriesToRun = QUERIES;

// Filter by specific query name
if (queryFilter) {
  queriesToRun = queriesToRun.filter((q) => q.name === queryFilter);
}

// Filter by tags
if (excludeTag) {
  queriesToRun = queriesToRun.filter((q) => !q.tags?.includes(excludeTag));
}
if (onlyTag) {
  queriesToRun = queriesToRun.filter((q) => q.tags?.includes(onlyTag));
}

if (queriesToRun.length === 0) {
  console.error(`No queries match the specified filters.`);
  if (queryFilter) console.error(`  Query: ${queryFilter}`);
  if (excludeTag) console.error(`  Exclude tag: ${excludeTag}`);
  if (onlyTag) console.error(`  Only tag: ${onlyTag}`);
  console.error(`\nAvailable queries:`);
  QUERIES.forEach((q) => {
    const tags = q.tags?.length ? ` [${q.tags.join(", ")}]` : "";
    console.error(`  - ${q.name}${tags}: ${q.description}`);
  });
  process.exit(1);
}

async function benchmarkDatabase(runner: DatabaseRunner): Promise<DatabaseResult> {
  console.log(`\n=== ${runner.name.toUpperCase()} ===`);
  const dbResult: DatabaseResult = { database: runner.name, results: [] };

  try {
    await runner.connect();
    console.log(`Connected to ${runner.name}`);

    // Get table sizes
    try {
      dbResult.tableSizes = await runner.getTableSizes();
      console.log(
        `Tables: ${dbResult.tableSizes.map((t) => `${t.table}(${t.rows.toLocaleString()})`).join(", ")}`
      );
    } catch (error) {
      console.log(
        `  Could not get table sizes: ${error instanceof Error ? error.message : String(error)}`
      );
    }

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
        console.error(`  Errors: ${String(errors.length)}/${String(results.length)}`);
        const firstError = errors[0]?.error ?? "Unknown error";
        console.error(`    - ${firstError}`);
        dbResult.results.push({
          query: queryDef.name,
          description: queryDef.description,
          minMs: 0,
          avgMs: 0,
          p95Ms: 0,
          maxMs: 0,
          error: firstError,
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

  // Build command to reproduce
  const cmdParts = ["pnpm benchmark"];
  if (!noDbSelected) {
    if (runPostgres) cmdParts.push("--postgres");
    if (runClickHouse) cmdParts.push("--clickhouse");
    if (runTrino) cmdParts.push("--trino");
  }
  if (values.query) cmdParts.push(`-q ${values.query}`);
  if (values.exclude) cmdParts.push(`-x ${values.exclude}`);
  if (values.only) cmdParts.push(`-o ${values.only}`);
  cmdParts.push(`--warmup ${String(WARMUP_RUNS)}`);
  cmdParts.push(`-r ${String(BENCHMARK_RUNS)}`);
  if (values.env) cmdParts.push(`--env ${values.env}`);
  cmdParts.push("--report");

  const report: BenchmarkReport = {
    timestamp: new Date().toISOString(),
    command: cmdParts.join(" "),
    environment: getEnvironmentInfo(values.env),
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
  const env = report.environment;

  const lines: string[] = [
    "# Benchmark Report",
    "",
    `**Date:** ${report.timestamp}`,
    `**Warmup Runs:** ${String(report.warmupRuns)}`,
    `**Benchmark Runs:** ${String(report.benchmarkRuns)}`,
    "",
    "## Environment",
    "",
    `| Property | Value |`,
    `|----------|-------|`,
    `| Memory Profile | ${env.memoryProfile ?? "not specified"} |`,
    `| Total Memory | ${String(env.totalMemoryGB)} GB |`,
    `| Free Memory | ${String(env.freeMemoryGB)} GB |`,
    `| CPU Cores | ${String(env.cpuCores)} |`,
    `| CPU Model | ${env.cpuModel} |`,
    `| Platform | ${env.platform} ${env.osRelease} |`,
    `| Node.js | ${env.nodeVersion} |`,
    "",
    "**Command to reproduce:**",
    "```bash",
    report.command,
    "```",
    "",
  ];

  // Table sizes section
  const firstDbWithSizes = report.databases.find((d) => d.tableSizes && d.tableSizes.length > 0);
  if (firstDbWithSizes?.tableSizes) {
    lines.push("## Table Sizes");
    lines.push("");
    lines.push("| Table | Rows |");
    lines.push("|-------|-----:|");
    for (const t of firstDbWithSizes.tableSizes) {
      lines.push(`| ${t.table} | ${t.rows.toLocaleString()} |`);
    }
    lines.push("");
  }

  lines.push("## Results");
  lines.push("");

  // Get all unique queries across all databases
  const allQueries = report.databases.flatMap((db) => db.results.map((r) => r.query));
  const queries = [...new Set(allQueries)];

  // Header
  const dbNames = report.databases.map((d) => d.database);
  lines.push(`| Query | ${dbNames.join(" | ")} |`);
  lines.push(`|-------|${dbNames.map(() => "------:").join("|")}|`);

  // Rows
  for (const query of queries) {
    const cells = report.databases.map((db) => {
      const result = db.results.find((r) => r.query === query);
      if (!result) return "-";
      if (result.error) return "ERROR";
      return formatDuration(result.avgMs);
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
      if (r.error) {
        lines.push(`| ${r.query} | ERROR | - | - | - |`);
      } else {
        lines.push(
          `| ${r.query} | ${formatDuration(r.minMs)} | ${formatDuration(r.avgMs)} | ${formatDuration(r.p95Ms)} | ${formatDuration(r.maxMs)} |`
        );
      }
    }
    lines.push("");
  }

  // Errors section
  const allErrors = report.databases.flatMap((db) =>
    db.results
      .filter((r) => r.error)
      .map((r) => ({ database: db.database, query: r.query, error: r.error }))
  );
  if (allErrors.length > 0) {
    lines.push("## Errors");
    lines.push("");
    for (const e of allErrors) {
      lines.push(`**${e.database} / ${e.query}:**`);
      lines.push("```");
      lines.push(e.error ?? "Unknown error");
      lines.push("```");
      lines.push("");
    }
  }

  return lines.join("\n");
}

main().catch((error: unknown) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
