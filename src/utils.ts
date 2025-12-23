import os from "node:os";

/**
 * Format duration in milliseconds to human-readable string
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${String(Math.round(ms))}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)}s`;
  if (ms < 3600_000) {
    const minutes = Math.floor(ms / 60_000);
    const seconds = Math.floor((ms % 60_000) / 1000);
    return `${String(minutes)}m ${String(seconds)}s`;
  }
  const hours = Math.floor(ms / 3600_000);
  const minutes = Math.floor((ms % 3600_000) / 60_000);
  const seconds = Math.floor((ms % 60_000) / 1000);
  return `${String(hours)}h ${String(minutes)}m ${String(seconds)}s`;
}

/**
 * Calculate statistics from an array of numbers
 */
export function calculateStats(values: number[]): {
  min: number;
  max: number;
  avg: number;
  median: number;
  p95: number;
} {
  if (values.length === 0) {
    return { min: 0, max: 0, avg: 0, median: 0, p95: 0 };
  }

  const sorted = [...values].sort((a, b) => a - b);
  const sum = sorted.reduce((a, b) => a + b, 0);

  return {
    min: sorted[0] ?? 0,
    max: sorted[sorted.length - 1] ?? 0,
    avg: sum / sorted.length,
    median: sorted[Math.floor(sorted.length / 2)] ?? 0,
    p95: sorted[Math.floor(sorted.length * 0.95)] ?? 0,
  };
}

/**
 * Environment information for reports
 */
export interface EnvironmentInfo {
  /** Memory profile used (16gb, 32gb, 64gb) - optional, user-specified */
  memoryProfile?: string;
  /** Total system memory in GB */
  totalMemoryGB: number;
  /** Available system memory in GB */
  freeMemoryGB: number;
  /** Number of CPU cores */
  cpuCores: number;
  /** CPU model */
  cpuModel: string;
  /** Operating system platform */
  platform: string;
  /** Operating system release */
  osRelease: string;
  /** Node.js version */
  nodeVersion: string;
}

/**
 * Detect environment information
 */
export function getEnvironmentInfo(memoryProfile?: string): EnvironmentInfo {
  const cpus = os.cpus();
  const result: EnvironmentInfo = {
    totalMemoryGB: Math.round(os.totalmem() / (1024 * 1024 * 1024)),
    freeMemoryGB: Math.round(os.freemem() / (1024 * 1024 * 1024)),
    cpuCores: cpus.length,
    cpuModel: cpus[0]?.model ?? "Unknown",
    platform: os.platform(),
    osRelease: os.release(),
    nodeVersion: process.version,
  };
  if (memoryProfile) {
    result.memoryProfile = memoryProfile;
  }
  return result;
}
