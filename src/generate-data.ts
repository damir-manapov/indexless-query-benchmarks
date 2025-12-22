import { parseArgs } from "node:util";
import {
  PostgresDataGenerator,
  ClickHouseDataGenerator,
  TrinoDataGenerator,
  type TableConfig,
  type BaseDataGenerator,
  type Scenario,
} from "@mkven/samples-generation";
import { formatDuration } from "./utils.js";
import {
  getEnglishMaleNames,
  getEnglishFemaleNames,
  getEnglishSurnames,
} from "@mkven/name-dictionaries";

const { values } = parseArgs({
  options: {
    postgres: { type: "boolean", default: false },
    clickhouse: { type: "boolean", default: false },
    trino: { type: "boolean", default: false },
    rows: { type: "string", short: "n", default: "100000000" },
    batch: { type: "string", short: "b" },
    help: { type: "boolean", short: "h", default: false },
  },
});

if (values.help) {
  console.log(`
Usage: pnpm generate [options]

Options:
  --postgres       Generate data for PostgreSQL
  --clickhouse     Generate data for ClickHouse
  --trino          Generate data for Trino/Iceberg
  -n, --rows <n>   Number of rows to generate (default: 100_000_000)
  -b, --batch <n>  Batch size (default: 10_000_000)
  -h, --help       Show this help message

If no database is specified, all databases are populated.

Examples:
  pnpm generate                          # All databases, 100M rows
  pnpm generate --postgres -n 1_000_000  # PostgreSQL only, 1M rows
  pnpm generate -n 10_000_000 -b 100_000 # Custom batch size
`);
  process.exit(0);
}

// Parse number with underscore separators (e.g., 1_000_000)
function parseNumber(value: string): number {
  return parseInt(value.replace(/_/g, ""), 10);
}

const ROW_COUNT = parseNumber(values.rows);
const BATCH_SIZE = values.batch ? parseNumber(values.batch) : 10_000_000;
const CATEGORY_COUNT = 10_000;

// If no database specified, run all
const noDbSelected = !values.postgres && !values.clickhouse && !values.trino;

// English names for realistic entity data
const FIRST_NAMES = [...getEnglishMaleNames(), ...getEnglishFemaleNames()];
const LAST_NAMES = getEnglishSurnames();

// Categories table (small lookup table for JOIN benchmarks)
const CATEGORIES_CONFIG: TableConfig = {
  name: "categories",
  columns: [
    { name: "id", type: "bigint", generator: { kind: "sequence", start: 1 } },
    { name: "name", type: "string", generator: { kind: "randomString", length: 20 } },
    { name: "code", type: "string", generator: { kind: "randomString", length: 6 } },
    {
      name: "priority",
      type: "string",
      generator: { kind: "choice", values: ["low", "medium", "high", "critical"] },
    },
    {
      name: "region",
      type: "string",
      generator: { kind: "choice", values: ["north", "south", "east", "west", "central"] },
    },
    { name: "weight", type: "float", generator: { kind: "randomFloat", min: 0, max: 100 } },
    {
      name: "is_active",
      type: "integer",
      generator: { kind: "randomInt", min: 0, max: 1 },
    },
    { name: "created_at", type: "datetime", generator: { kind: "datetime" } },
  ],
};

// Table schema matching the benchmark queries
const TABLE_CONFIG: TableConfig = {
  name: "samples",
  columns: [
    { name: "id", type: "bigint", generator: { kind: "sequence", start: 1 } },
    {
      name: "first_name",
      type: "string",
      generator: { kind: "choice", values: FIRST_NAMES },
    },
    {
      name: "last_name",
      type: "string",
      generator: { kind: "choice", values: LAST_NAMES },
    },
    {
      name: "email",
      type: "string",
      generator: { kind: "constant", value: "" }, // Placeholder, will be templated
    },
    { name: "value", type: "float", generator: { kind: "randomFloat", min: 0, max: 1000 } },
    {
      name: "status",
      type: "string",
      generator: {
        kind: "choice",
        values: ["active", "inactive", "pending", "completed"],
      },
    },
    {
      name: "category_id",
      type: "bigint",
      generator: { kind: "randomInt", min: 1, max: CATEGORY_COUNT },
    },
    { name: "created_at", type: "datetime", generator: { kind: "datetime" } },
  ],
};

// Corrupted table - same structure as samples, linked via sample_id
// Will have names/emails copied from samples then corrupted
// Temporarily disabled for faster generation
// const CORRUPTED_CONFIG: TableConfig = {
//   name: "corrupted",
//   columns: [
//     { name: "id", type: "bigint", generator: { kind: "sequence", start: 1 } },
//     {
//       name: "sample_id",
//       type: "bigint",
//       generator: { kind: "randomInt", min: 1, max: ROW_COUNT },
//     },
//     {
//       name: "first_name",
//       type: "string",
//       generator: { kind: "randomString", length: 30 }, // Placeholder, will be looked up
//     },
//     {
//       name: "last_name",
//       type: "string",
//       generator: { kind: "randomString", length: 30 }, // Placeholder, will be looked up
//     },
//     {
//       name: "email",
//       type: "string",
//       generator: { kind: "randomString", length: 50 }, // Placeholder, will be looked up
//     },
//     {
//       name: "corrupted_first_name",
//       type: "string",
//       generator: { kind: "randomString", length: 30 }, // Placeholder, will be looked up then mutated
//     },
//     {
//       name: "corrupted_last_name",
//       type: "string",
//       generator: { kind: "randomString", length: 30 }, // Placeholder, will be looked up then mutated
//     },
//     {
//       name: "corrupted_email",
//       type: "string",
//       generator: { kind: "randomString", length: 50 }, // Placeholder, will be looked up then mutated
//     },
//     { name: "created_at", type: "datetime", generator: { kind: "datetime" } },
//   ],
// };

interface DatabaseConfig {
  name: string;
  createGenerator: () => BaseDataGenerator;
}

const DATABASES: DatabaseConfig[] = [
  {
    name: "PostgreSQL",
    createGenerator: () =>
      new PostgresDataGenerator({
        host: "localhost",
        port: 5432,
        database: "benchmarks",
        username: "postgres",
        password: "postgres",
      }),
  },
  {
    name: "ClickHouse",
    createGenerator: () =>
      new ClickHouseDataGenerator({
        host: "localhost",
        port: 8123,
        username: "default",
        password: "clickhouse",
        database: "benchmarks",
      }),
  },
  {
    name: "Trino/Iceberg",
    createGenerator: () =>
      new TrinoDataGenerator({
        host: "localhost",
        port: 8080,
        catalog: "iceberg",
        schema: "benchmarks",
        user: "trino",
      }),
  },
];

async function generateForDatabase(config: DatabaseConfig): Promise<void> {
  console.log(`\n=== ${config.name} ===`);
  const generator = config.createGenerator();

  const scenario: Scenario = {
    name: "Entity resolution benchmark",
    steps: [
      // Step 1: Generate categories
      { table: CATEGORIES_CONFIG, rowCount: CATEGORY_COUNT },
      // Step 2: Generate samples (email generation disabled for faster generation)
      { table: TABLE_CONFIG, rowCount: ROW_COUNT },
      // {
      //   table: TABLE_CONFIG,
      //   rowCount: ROW_COUNT,
      //   transformations: [
      //     {
      //       description: "Generate email from first_name and last_name",
      //       transformations: [
      //         {
      //           kind: "template",
      //           column: "email",
      //           template: "{first_name}.{last_name}@example.com",
      //           lowercase: true,
      //         },
      //       ],
      //     },
      //   ],
      // },
      // Step 3: Generate corrupted table (disabled temporarily for faster generation)
      // { table: CORRUPTED_CONFIG, rowCount: ROW_COUNT },
      // Step 4: Lookup values from samples to corrupted
      // {
      //   tableName: "corrupted",
      //   transformations: [
      //     {
      //       description: "Copy names and email from linked sample",
      //       transformations: [
      //         {
      //           kind: "lookup",
      //           column: "first_name",
      //           fromTable: "samples",
      //           fromColumn: "first_name",
      //           joinOn: { targetColumn: "sample_id", lookupColumn: "id" },
      //         },
      //         {
      //           kind: "lookup",
      //           column: "last_name",
      //           fromTable: "samples",
      //           fromColumn: "last_name",
      //           joinOn: { targetColumn: "sample_id", lookupColumn: "id" },
      //         },
      //         {
      //           kind: "lookup",
      //           column: "email",
      //           fromTable: "samples",
      //           fromColumn: "email",
      //           joinOn: { targetColumn: "sample_id", lookupColumn: "id" },
      //         },
      //         {
      //           kind: "lookup",
      //           column: "corrupted_first_name",
      //           fromTable: "samples",
      //           fromColumn: "first_name",
      //           joinOn: { targetColumn: "sample_id", lookupColumn: "id" },
      //         },
      //         {
      //           kind: "lookup",
      //           column: "corrupted_last_name",
      //           fromTable: "samples",
      //           fromColumn: "last_name",
      //           joinOn: { targetColumn: "sample_id", lookupColumn: "id" },
      //         },
      //         {
      //           kind: "lookup",
      //           column: "corrupted_email",
      //           fromTable: "samples",
      //           fromColumn: "email",
      //           joinOn: { targetColumn: "sample_id", lookupColumn: "id" },
      //         },
      //       ],
      //     },
      //     {
      //       description: "Corrupt the corrupted_* columns",
      //       transformations: [
      //         {
      //           kind: "mutate",
      //           column: "corrupted_first_name",
      //           probability: 0.3,
      //           operations: ["replace", "delete", "insert"],
      //         },
      //         {
      //           kind: "mutate",
      //           column: "corrupted_last_name",
      //           probability: 0.3,
      //           operations: ["replace", "delete", "insert"],
      //         },
      //         {
      //           kind: "mutate",
      //           column: "corrupted_email",
      //           probability: 0.3,
      //           operations: ["replace", "delete", "insert"],
      //         },
      //       ],
      //     },
      //   ],
      // },
    ],
  };

  try {
    await generator.connect();

    console.log(`Generating ${ROW_COUNT.toLocaleString()} rows per table...`);
    const result = await generator.runScenario({
      scenario,
      batchSize: BATCH_SIZE,
      dropFirst: true,
    });

    const durationStr = formatDuration(result.durationMs);
    console.log(
      `Generated ${result.totalRowsInserted.toLocaleString()} total rows in ${durationStr}`
    );
  } finally {
    await generator.disconnect();
  }
}

async function main(): Promise<void> {
  console.log(`Generating ${ROW_COUNT.toLocaleString()} rows...`);

  const dbsToRun = noDbSelected
    ? DATABASES
    : DATABASES.filter(
        (db) =>
          (values.postgres && db.name === "PostgreSQL") ||
          (values.clickhouse && db.name === "ClickHouse") ||
          (values.trino && db.name === "Trino/Iceberg")
      );

  for (const db of dbsToRun) {
    await generateForDatabase(db);
  }

  console.log("\nDone!");
}

main().catch((err: unknown) => {
  console.error("Error:", err);
  process.exit(1);
});
