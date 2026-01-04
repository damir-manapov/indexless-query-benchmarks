"""Pydantic models for trial data."""

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


# ============================================================================
# Infrastructure Config
# ============================================================================


class InfraConfig(BaseModel):
    """Infrastructure configuration for a VM."""

    cpu: int = Field(ge=1, description="Number of vCPUs")
    ram_gb: int = Field(ge=1, description="RAM in GB")
    disk_type: str = Field(description="Disk type (e.g., 'fast', 'universal')")
    disk_size_gb: int = Field(ge=10, description="Disk size in GB")


# ============================================================================
# Service Configs
# ============================================================================


class MeilisearchConfig(BaseModel):
    """Meilisearch-specific configuration."""

    max_indexing_memory_mb: int = Field(
        default=0, ge=0, description="Max indexing memory (0=auto)"
    )
    max_indexing_threads: int = Field(
        default=0, ge=0, description="Max indexing threads (0=auto)"
    )


class RedisConfig(BaseModel):
    """Redis-specific configuration."""

    maxmemory_mb: int = Field(ge=0, description="Max memory in MB")
    maxmemory_policy: str = Field(default="noeviction", description="Eviction policy")
    io_threads: int = Field(default=1, ge=1, description="IO threads")
    persistence: str = Field(default="none", description="Persistence mode")


class PostgresConfig(BaseModel):
    """PostgreSQL-specific configuration."""

    shared_buffers_mb: int = Field(ge=0, description="Shared buffers in MB")
    work_mem_mb: int = Field(ge=0, description="Work memory in MB")
    effective_cache_size_mb: int = Field(ge=0, description="Effective cache size")
    max_connections: int = Field(default=100, ge=1, description="Max connections")


class MinioConfig(BaseModel):
    """MinIO-specific configuration."""

    nodes: int = Field(default=1, ge=1, description="Number of nodes")
    drives_per_node: int = Field(default=1, ge=1, description="Drives per node")


# ============================================================================
# Service Metrics
# ============================================================================


class MeilisearchMetrics(BaseModel):
    """Meilisearch benchmark metrics."""

    qps: float = Field(ge=0, description="Queries per second")
    p50_ms: float = Field(ge=0, description="50th percentile latency (ms)")
    p95_ms: float = Field(ge=0, description="95th percentile latency (ms)")
    p99_ms: float = Field(ge=0, description="99th percentile latency (ms)")
    indexing_time_s: float = Field(ge=0, description="Indexing time (seconds)")
    error_rate: float = Field(default=0.0, ge=0, le=1, description="Error rate")


class RedisMetrics(BaseModel):
    """Redis benchmark metrics."""

    ops_per_sec: float = Field(ge=0, description="Operations per second")
    latency_avg_ms: float = Field(ge=0, description="Average latency (ms)")
    latency_p99_ms: float = Field(ge=0, description="99th percentile latency (ms)")
    memory_used_mb: float = Field(ge=0, description="Memory used (MB)")


class PostgresMetrics(BaseModel):
    """PostgreSQL benchmark metrics."""

    tps: float = Field(ge=0, description="Transactions per second")
    latency_avg_ms: float = Field(ge=0, description="Average latency (ms)")
    latency_p95_ms: float = Field(ge=0, description="95th percentile latency (ms)")


class MinioMetrics(BaseModel):
    """MinIO benchmark metrics."""

    throughput_mbps: float = Field(ge=0, description="Throughput (MB/s)")
    latency_p50_ms: float = Field(ge=0, description="50th percentile latency (ms)")
    latency_p95_ms: float = Field(ge=0, description="95th percentile latency (ms)")
    objects_per_sec: float = Field(default=0, ge=0, description="Objects per second")


# ============================================================================
# Timings
# ============================================================================


class Timings(BaseModel):
    """Timing measurements for trial phases."""

    terraform_s: float = Field(default=0.0, ge=0, description="Terraform apply time")
    vm_ready_s: float = Field(default=0.0, ge=0, description="VM ready wait time")
    service_ready_s: float = Field(default=0.0, ge=0, description="Service ready time")
    benchmark_s: float = Field(default=0.0, ge=0, description="Benchmark duration")
    total_s: float = Field(default=0.0, ge=0, description="Total trial time")


# ============================================================================
# Trial
# ============================================================================

# Type aliases for Union types
ServiceConfig = Annotated[
    Union[MeilisearchConfig, RedisConfig, PostgresConfig, MinioConfig],
    Field(discriminator=None),
]

ServiceMetrics = Annotated[
    Union[MeilisearchMetrics, RedisMetrics, PostgresMetrics, MinioMetrics],
    Field(discriminator=None),
]

ServiceType = Literal["meilisearch", "redis", "postgres", "minio"]


class Trial(BaseModel):
    """A single benchmark trial result."""

    id: int | None = Field(default=None, description="Auto-assigned trial ID")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="When the trial was run"
    )
    service: ServiceType = Field(description="Service being benchmarked")
    cloud: str = Field(description="Cloud provider (e.g., 'selectel')")
    infra: InfraConfig = Field(description="Infrastructure configuration")
    config: MeilisearchConfig | RedisConfig | PostgresConfig | MinioConfig = Field(
        description="Service-specific configuration"
    )
    metrics: (
        MeilisearchMetrics | RedisMetrics | PostgresMetrics | MinioMetrics | None
    ) = Field(default=None, description="Benchmark metrics (None if failed)")
    timings: Timings | None = Field(default=None, description="Timing measurements")
    error: str | None = Field(default=None, description="Error message if failed")

    def is_successful(self) -> bool:
        """Check if trial completed successfully."""
        return self.error is None and self.metrics is not None
