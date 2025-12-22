import { describe, it, expect } from "vitest";
import { formatDuration, calculateStats } from "../src/utils.js";
import { QUERIES } from "../src/queries.js";

describe("formatDuration", () => {
  it("formats milliseconds", () => {
    expect(formatDuration(500)).toBe("500ms");
  });

  it("formats seconds", () => {
    expect(formatDuration(1500)).toBe("1.50s");
    expect(formatDuration(45000)).toBe("45.00s");
  });

  it("formats minutes", () => {
    expect(formatDuration(90000)).toBe("1m 30s");
    expect(formatDuration(300000)).toBe("5m 0s");
  });

  it("formats hours", () => {
    expect(formatDuration(3661000)).toBe("1h 1m 1s");
  });
});

describe("calculateStats", () => {
  it("calculates stats for empty array", () => {
    const stats = calculateStats([]);
    expect(stats.min).toBe(0);
    expect(stats.max).toBe(0);
    expect(stats.avg).toBe(0);
  });

  it("calculates stats for single value", () => {
    const stats = calculateStats([100]);
    expect(stats.min).toBe(100);
    expect(stats.max).toBe(100);
    expect(stats.avg).toBe(100);
  });

  it("calculates stats for multiple values", () => {
    const stats = calculateStats([10, 20, 30, 40, 50]);
    expect(stats.min).toBe(10);
    expect(stats.max).toBe(50);
    expect(stats.avg).toBe(30);
    expect(stats.median).toBe(30);
  });
});

describe("QUERIES", () => {
  it("has query definitions", () => {
    expect(QUERIES.length).toBeGreaterThan(0);
  });

  it("each query has required fields", () => {
    for (const query of QUERIES) {
      expect(query.name).toBeTruthy();
      expect(query.description).toBeTruthy();
      expect(query.sql).toBeDefined();
    }
  });

  it("each query has at least one database SQL", () => {
    for (const query of QUERIES) {
      const hasSql = query.sql.postgres ?? query.sql.clickhouse ?? query.sql.trino;
      expect(hasSql).toBeTruthy();
    }
  });
});
