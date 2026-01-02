import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Counter } from "k6/metrics";

// Custom metrics
const searchLatency = new Trend("search_latency_ms");
const searchErrors = new Counter("search_errors");

// Configuration from environment
const MEILI_URL = __ENV.MEILI_URL || "http://10.0.0.40:7700";
const MEILI_KEY = __ENV.MEILI_KEY || "benchmark-master-key-change-in-production";
const INDEX_NAME = __ENV.INDEX_NAME || "products";

// Search query patterns
const SIMPLE_QUERIES = [
  "laptop",
  "phone",
  "tablet",
  "headphones",
  "camera",
  "tv",
  "gaming",
  "watch",
  "speaker",
  "charger",
  "apple",
  "samsung",
  "sony",
  "dell",
  "hp",
  "wireless",
  "portable",
  "smart",
  "pro",
  "ultra",
];

const TYPO_QUERIES = [
  "laptp",
  "phne",
  "tblet",
  "hedphones",
  "camra",
  "samsng",
  "wirless",
  "portble",
  "smat",
  "gamng",
];

const PHRASE_QUERIES = [
  "gaming laptop",
  "wireless headphones",
  "smart tv",
  "portable speaker",
  "digital camera",
  "fitness watch",
  "pro tablet",
  "ultra phone",
  "compact charger",
];

// Filter patterns
const CATEGORY_FILTERS = [
  'category = "Laptops"',
  'category = "Smartphones"',
  'category = "Headphones"',
  'category = "TVs"',
  'category = "Gaming"',
];

const PRICE_FILTERS = [
  "price < 100",
  "price < 500",
  "price > 1000",
  "price >= 200 AND price <= 800",
];

const COMBINED_FILTERS = [
  'category = "Laptops" AND price < 2000',
  'category = "Smartphones" AND brand = "Apple"',
  "in_stock = true AND rating >= 4.5",
  'category = "Headphones" AND price < 200 AND in_stock = true',
];

// Options from environment or defaults
export const options = {
  vus: parseInt(__ENV.VUS) || 10,
  duration: __ENV.DURATION || "60s",
  thresholds: {
    http_req_duration: ["p(95)<500", "p(99)<1000"],
    search_latency_ms: ["p(95)<100", "p(99)<200"],
    search_errors: ["count<100"],
  },
};

function randomChoice(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

function buildSearchRequest(queryType) {
  let query, filter, sort;

  switch (queryType) {
    case "simple":
      // 50% - Simple keyword search
      query = randomChoice(SIMPLE_QUERIES);
      break;

    case "typo":
      // 20% - Typo-tolerant search
      query = randomChoice(TYPO_QUERIES);
      break;

    case "filtered":
      // 20% - Filtered search
      query = randomChoice(SIMPLE_QUERIES);
      const filterType = Math.random();
      if (filterType < 0.3) {
        filter = randomChoice(CATEGORY_FILTERS);
      } else if (filterType < 0.6) {
        filter = randomChoice(PRICE_FILTERS);
      } else {
        filter = randomChoice(COMBINED_FILTERS);
      }
      break;

    case "phrase_sort":
      // 10% - Phrase + sort
      query = randomChoice(PHRASE_QUERIES);
      sort = Math.random() > 0.5 ? ["price:asc"] : ["rating:desc"];
      break;
  }

  const body = { q: query, limit: 20 };
  if (filter) body.filter = filter;
  if (sort) body.sort = sort;

  return body;
}

function selectQueryType() {
  const r = Math.random();
  if (r < 0.5) return "simple";
  if (r < 0.7) return "typo";
  if (r < 0.9) return "filtered";
  return "phrase_sort";
}

export default function () {
  const queryType = selectQueryType();
  const searchBody = buildSearchRequest(queryType);

  const startTime = Date.now();

  const response = http.post(
    `${MEILI_URL}/indexes/${INDEX_NAME}/search`,
    JSON.stringify(searchBody),
    {
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${MEILI_KEY}`,
      },
    }
  );

  const latency = Date.now() - startTime;
  searchLatency.add(latency);

  const success = check(response, {
    "status is 200": (r) => r.status === 200,
    "has hits": (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.hits !== undefined;
      } catch {
        return false;
      }
    },
  });

  if (!success) {
    searchErrors.add(1);
    console.error(`Search failed: ${response.status} - ${response.body}`);
  }

  // Small sleep to avoid overwhelming
  sleep(0.01);
}

// Setup function - can be used to verify connection
export function setup() {
  console.log(`Testing Meilisearch at ${MEILI_URL}`);

  const health = http.get(`${MEILI_URL}/health`);
  if (health.status !== 200) {
    throw new Error(`Meilisearch not healthy: ${health.status}`);
  }

  const stats = http.get(`${MEILI_URL}/indexes/${INDEX_NAME}/stats`, {
    headers: { Authorization: `Bearer ${MEILI_KEY}` },
  });

  if (stats.status === 200) {
    const data = JSON.parse(stats.body);
    console.log(`Index ${INDEX_NAME}: ${data.numberOfDocuments} documents`);
  }

  return { startTime: Date.now() };
}

export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;
  console.log(`Benchmark completed in ${duration.toFixed(1)}s`);
}
