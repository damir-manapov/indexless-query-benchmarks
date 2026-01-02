#!/usr/bin/env npx tsx
/**
 * Generate synthetic e-commerce product dataset for Meilisearch benchmarks.
 *
 * Usage:
 *   npx tsx dataset.ts --count 500000 --output products.ndjson
 *   npx tsx dataset.ts --count 500000 --output products.json --format json
 */

import { createWriteStream, writeFileSync } from "fs";
import { parseArgs } from "util";

// Product categories and brands
const CATEGORIES = [
  "Laptops",
  "Smartphones",
  "Tablets",
  "Headphones",
  "Cameras",
  "TVs",
  "Gaming",
  "Wearables",
  "Audio",
  "Accessories",
] as const;

const BRANDS = [
  "Apple",
  "Samsung",
  "Sony",
  "LG",
  "Dell",
  "HP",
  "Lenovo",
  "Asus",
  "Acer",
  "Microsoft",
  "Google",
  "Bose",
  "JBL",
  "Canon",
  "Nikon",
  "Nintendo",
  "Razer",
  "Logitech",
  "Anker",
  "Belkin",
] as const;

const ADJECTIVES = [
  "Pro",
  "Ultra",
  "Max",
  "Plus",
  "Lite",
  "Mini",
  "Elite",
  "Premium",
  "Advanced",
  "Essential",
  "Compact",
  "Wireless",
  "Portable",
  "Smart",
  "Digital",
] as const;

// Product name templates per category
const PRODUCT_TEMPLATES: Record<string, string[]> = {
  Laptops: [
    "{brand} {adj} Laptop {num}",
    "{brand} Notebook {adj} {num}",
    "{brand} {adj} Book {num}",
  ],
  Smartphones: ["{brand} Phone {adj} {num}", "{brand} {adj} {num}", "{brand} Mobile {adj} {num}"],
  Tablets: ["{brand} Tab {adj} {num}", "{brand} Pad {adj} {num}", "{brand} {adj} Tablet {num}"],
  Headphones: [
    "{brand} {adj} Buds {num}",
    "{brand} {adj} Headphones",
    "{brand} {adj} Earbuds {num}",
  ],
  Cameras: [
    "{brand} {adj} Camera {num}",
    "{brand} {adj} DSLR {num}",
    "{brand} Mirrorless {adj} {num}",
  ],
  TVs: ['{brand} {num}" {adj} TV', '{brand} {adj} {num}" Smart TV', '{brand} OLED {num}" {adj}'],
  Gaming: ["{brand} {adj} Controller", "{brand} Gaming {adj} {num}", "{brand} {adj} Console"],
  Wearables: [
    "{brand} Watch {adj} {num}",
    "{brand} {adj} Band {num}",
    "{brand} Fitness {adj} {num}",
  ],
  Audio: ["{brand} {adj} Speaker", "{brand} Soundbar {adj}", "{brand} {adj} Home Audio"],
  Accessories: [
    "{brand} {adj} Charger",
    "{brand} {adj} Cable",
    "{brand} {adj} Case",
    "{brand} {adj} Stand",
  ],
};

// Description templates
const DESCRIPTION_TEMPLATES = [
  "The {title} delivers exceptional performance with cutting-edge technology. Features include {feature1}, {feature2}, and {feature3}. Perfect for {useCase}.",
  "Experience the next level of {category} with the {title}. Equipped with {feature1} and {feature2}, this device offers unmatched {benefit} for {useCase}.",
  "Introducing the {title} - designed for those who demand the best. With {feature1}, {feature2}, and {feature3}, enjoy superior {benefit}. Ideal for {useCase}.",
];

const FEATURES = [
  "fast charging",
  "long battery life",
  "high-resolution display",
  "noise cancellation",
  "wireless connectivity",
  "AI-powered features",
  "sleek design",
  "durable build",
  "water resistance",
  "voice control",
  "multi-device support",
  "cloud sync",
  "advanced sensors",
  "precision controls",
  "immersive sound",
];

const BENEFITS = [
  "performance",
  "quality",
  "experience",
  "productivity",
  "entertainment",
  "convenience",
  "reliability",
  "versatility",
];

const USE_CASES = [
  "professionals",
  "gamers",
  "content creators",
  "music lovers",
  "everyday use",
  "travel",
  "home entertainment",
  "fitness enthusiasts",
  "remote work",
  "students",
];

// Price ranges per category
const PRICE_RANGES: Record<string, [number, number]> = {
  Laptops: [500, 3500],
  Smartphones: [200, 1500],
  Tablets: [150, 1200],
  Headphones: [30, 500],
  Cameras: [300, 3000],
  TVs: [200, 5000],
  Gaming: [30, 600],
  Wearables: [50, 800],
  Audio: [50, 1500],
  Accessories: [10, 150],
};

// Seeded random number generator (Mulberry32)
function createRng(seed: number) {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function randomChoice<T>(arr: readonly T[], rng: () => number): T {
  return arr[Math.floor(rng() * arr.length)];
}

function randomSample<T>(arr: readonly T[], count: number, rng: () => number): T[] {
  const shuffled = [...arr].sort(() => rng() - 0.5);
  return shuffled.slice(0, count);
}

interface Product {
  id: number;
  title: string;
  description: string;
  brand: string;
  category: string;
  price: number;
  rating: number;
  reviews_count: number;
  in_stock: boolean;
}

function generateProduct(id: number, rng: () => number): Product {
  const category = randomChoice(CATEGORIES, rng);
  const brand = randomChoice(BRANDS, rng);
  const adj = randomChoice(ADJECTIVES, rng);
  const num = Math.floor(rng() * 20) + 1;

  // Generate title
  const template = randomChoice(PRODUCT_TEMPLATES[category], rng);
  const title = template
    .replace("{brand}", brand)
    .replace("{adj}", adj)
    .replace("{num}", String(num));

  // Generate description
  const descTemplate = randomChoice(DESCRIPTION_TEMPLATES, rng);
  const features = randomSample(FEATURES, 3, rng);
  const description = descTemplate
    .replace("{title}", title)
    .replace("{category}", category.toLowerCase())
    .replace("{feature1}", features[0])
    .replace("{feature2}", features[1])
    .replace("{feature3}", features[2])
    .replace("{benefit}", randomChoice(BENEFITS, rng))
    .replace("{useCase}", randomChoice(USE_CASES, rng));

  // Generate price
  const [minPrice, maxPrice] = PRICE_RANGES[category];
  const price = Math.round((minPrice + rng() * (maxPrice - minPrice)) * 100) / 100;

  return {
    id,
    title,
    description,
    brand,
    category,
    price,
    rating: Math.round((3 + rng() * 2) * 10) / 10,
    reviews_count: Math.floor(rng() * 5000),
    in_stock: rng() > 0.1, // 90% in stock
  };
}

async function generateDataset(
  count: number,
  output: string,
  format: "json" | "ndjson",
  seed: number
): Promise<void> {
  const rng = createRng(seed);
  console.log(`Generating ${count.toLocaleString()} products...`);

  if (format === "ndjson") {
    // Stream to file for memory efficiency
    const stream = createWriteStream(output);

    for (let i = 1; i <= count; i++) {
      const product = generateProduct(i, rng);
      stream.write(JSON.stringify(product) + "\n");

      if (i % 100000 === 0) {
        console.log(`  Generated ${i.toLocaleString()} products...`);
      }
    }

    await new Promise<void>((resolve, reject) => {
      stream.end(() => resolve());
      stream.on("error", reject);
    });
  } else {
    // JSON format - build array in memory
    const products: Product[] = [];

    for (let i = 1; i <= count; i++) {
      products.push(generateProduct(i, rng));

      if (i % 100000 === 0) {
        console.log(`  Generated ${i.toLocaleString()} products...`);
      }
    }

    writeFileSync(output, JSON.stringify(products));
  }

  const { statSync } = await import("fs");
  const sizeMb = statSync(output).size / (1024 * 1024);
  console.log(`Done! File: ${output} (${sizeMb.toFixed(1)} MB)`);
}

// Main
const { values } = parseArgs({
  options: {
    count: { type: "string", short: "c", default: "500000" },
    output: { type: "string", short: "o", default: "products.ndjson" },
    format: { type: "string", short: "f", default: "ndjson" },
    seed: { type: "string", short: "s", default: "42" },
  },
});

const count = parseInt(values.count!, 10);
const output = values.output!;
const format = values.format as "json" | "ndjson";
const seed = parseInt(values.seed!, 10);

generateDataset(count, output, format, seed).catch((err) => {
  console.error(err);
  process.exit(1);
});
