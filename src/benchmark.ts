import { parseArgs } from "node:util";
import {
  PostgresRunner,
  ClickHouseRunner,
  TrinoRunner,
  runBenchmark,
  type DatabaseRunner,
} from "./runners.js";
import { QUERIES } from "./queries.js";
import { formatDuration, calculateStats } from "./utils.js";

const { values } = parseArgs({
  options: {
    postgres: { type: "boolean", default: false },
    clickhouse: { type: "boolean", default: false },
    trino: { type: "boolean", default: false },
    warmup: { type: "string", default: "1" },
    runs: { type: "string", short: "r", default: "3" },
    query: { type: "string", short: "q" },
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
  -h, --help       Show this help message

If no database is specified, all databases are benchmarked.

Examples:
  pnpm benchmark                          # All databases, all queries
  pnpm benchmark --postgres --trino       # PostgreSQL and Trino only
  pnpm benchmark -q full-count -r 5       # Specific query, 5 runs
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

async function benchmarkDatabase(runner: DatabaseRunner): Promise<void> {
  console.log(`\n=== ${runner.name.toUpperCase()} ===`);

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
    }

    await runner.disconnect();
    console.log(`Disconnected from ${runner.name}`);
  } catch (error) {
    console.error(`Error with ${runner.name}:`, error instanceof Error ? error.message : error);
  }
}

async function main(): Promise<void> {
  console.log("=== Indexless Query Benchmarks ===");
  console.log(`Warmup: ${String(WARMUP_RUNS)} runs, Benchmark: ${String(BENCHMARK_RUNS)} runs`);
  console.log(`Queries: ${queriesToRun.map((q) => q.name).join(", ")}`);

  if (runPostgres) {
    await benchmarkDatabase(new PostgresRunner());
  }

  if (runClickHouse) {
    await benchmarkDatabase(new ClickHouseRunner());
  }

  if (runTrino) {
    await benchmarkDatabase(new TrinoRunner());
  }

  console.log("\n=== Done ===");
}

main().catch((error: unknown) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
