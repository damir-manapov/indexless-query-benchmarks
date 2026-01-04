"""Tests for TrialStore."""

from datetime import datetime
from pathlib import Path

import pytest

from storage.models import (
    InfraConfig,
    MeilisearchConfig,
    MeilisearchMetrics,
    MinioConfig,
    MinioMetrics,
    PostgresConfig,
    PostgresMetrics,
    RedisConfig,
    RedisMetrics,
    Timings,
    Trial,
)
from storage.store import TrialStore


@pytest.fixture
def temp_store(tmp_path: Path) -> TrialStore:
    """Create a temporary store for testing."""
    return TrialStore(tmp_path / "results.json")


@pytest.fixture
def sample_infra() -> InfraConfig:
    """Sample infrastructure config."""
    return InfraConfig(cpu=4, ram_gb=8, disk_type="fast", disk_size_gb=100)


@pytest.fixture
def sample_meilisearch_trial(sample_infra: InfraConfig) -> Trial:
    """Sample Meilisearch trial."""
    return Trial(
        service="meilisearch",
        cloud="selectel",
        infra=sample_infra,
        config=MeilisearchConfig(max_indexing_memory_mb=1024, max_indexing_threads=4),
        metrics=MeilisearchMetrics(
            qps=3000.5,
            p50_ms=30.0,
            p95_ms=40.0,
            p99_ms=50.0,
            indexing_time_s=15.5,
        ),
        timings=Timings(terraform_s=120, benchmark_s=60, total_s=200),
    )


@pytest.fixture
def sample_redis_trial(sample_infra: InfraConfig) -> Trial:
    """Sample Redis trial."""
    return Trial(
        service="redis",
        cloud="selectel",
        infra=sample_infra,
        config=RedisConfig(
            maxmemory_mb=4096,
            maxmemory_policy="allkeys-lru",
            io_threads=4,
            persistence="none",
        ),
        metrics=RedisMetrics(
            ops_per_sec=150000,
            latency_avg_ms=0.5,
            latency_p99_ms=1.2,
            memory_used_mb=2048,
        ),
    )


class TestTrialStore:
    """Tests for TrialStore basic operations."""

    def test_empty_store(self, temp_store: TrialStore):
        """Empty store should have no trials."""
        assert temp_store.count() == 0
        assert temp_store.trials == []

    def test_add_trial(self, temp_store: TrialStore, sample_meilisearch_trial: Trial):
        """Adding a trial should assign ID and persist."""
        assert sample_meilisearch_trial.id is None

        added = temp_store.add(sample_meilisearch_trial)

        assert added.id == 1
        assert temp_store.count() == 1
        assert temp_store.path.exists()

    def test_auto_increment_id(
        self,
        temp_store: TrialStore,
        sample_meilisearch_trial: Trial,
        sample_redis_trial: Trial,
    ):
        """Trial IDs should auto-increment."""
        t1 = temp_store.add(sample_meilisearch_trial)
        t2 = temp_store.add(sample_redis_trial)

        assert t1.id == 1
        assert t2.id == 2

    def test_persistence(self, tmp_path: Path, sample_meilisearch_trial: Trial):
        """Trials should persist across store instances."""
        path = tmp_path / "results.json"

        # Add trial
        store1 = TrialStore(path)
        store1.add(sample_meilisearch_trial)

        # Load in new store
        store2 = TrialStore(path)
        assert store2.count() == 1
        assert store2.trials[0].id == 1
        assert store2.trials[0].service == "meilisearch"

    def test_reload(self, temp_store: TrialStore, sample_meilisearch_trial: Trial):
        """Reload should refresh from disk."""
        temp_store.add(sample_meilisearch_trial)
        temp_store._trials = []  # Clear in-memory

        temp_store.reload()
        assert temp_store.count() == 1

    def test_clear(self, temp_store: TrialStore, sample_meilisearch_trial: Trial):
        """Clear should remove all trials and delete file."""
        temp_store.add(sample_meilisearch_trial)
        assert temp_store.path.exists()

        temp_store.clear()
        assert temp_store.count() == 0
        assert not temp_store.path.exists()


class TestTrialStoreFind:
    """Tests for TrialStore.find()."""

    def test_find_by_service(
        self,
        temp_store: TrialStore,
        sample_meilisearch_trial: Trial,
        sample_redis_trial: Trial,
    ):
        """Find should filter by service."""
        temp_store.add(sample_meilisearch_trial)
        temp_store.add(sample_redis_trial)

        meili = temp_store.find(service="meilisearch")
        redis = temp_store.find(service="redis")

        assert len(meili) == 1
        assert meili[0].service == "meilisearch"
        assert len(redis) == 1
        assert redis[0].service == "redis"

    def test_find_by_cloud(self, temp_store: TrialStore, sample_infra: InfraConfig):
        """Find should filter by cloud."""
        trial1 = Trial(
            service="meilisearch",
            cloud="selectel",
            infra=sample_infra,
            config=MeilisearchConfig(),
            metrics=MeilisearchMetrics(
                qps=1000, p50_ms=10, p95_ms=20, p99_ms=30, indexing_time_s=10
            ),
        )
        trial2 = Trial(
            service="meilisearch",
            cloud="timeweb",
            infra=sample_infra,
            config=MeilisearchConfig(),
            metrics=MeilisearchMetrics(
                qps=900, p50_ms=12, p95_ms=22, p99_ms=32, indexing_time_s=12
            ),
        )

        temp_store.add(trial1)
        temp_store.add(trial2)

        selectel = temp_store.find(cloud="selectel")
        timeweb = temp_store.find(cloud="timeweb")

        assert len(selectel) == 1
        assert selectel[0].cloud == "selectel"
        assert len(timeweb) == 1
        assert timeweb[0].cloud == "timeweb"

    def test_find_successful_only(
        self, temp_store: TrialStore, sample_infra: InfraConfig
    ):
        """Find with successful_only should exclude failed trials."""
        success = Trial(
            service="meilisearch",
            cloud="selectel",
            infra=sample_infra,
            config=MeilisearchConfig(),
            metrics=MeilisearchMetrics(
                qps=1000, p50_ms=10, p95_ms=20, p99_ms=30, indexing_time_s=10
            ),
        )
        failed = Trial(
            service="meilisearch",
            cloud="selectel",
            infra=sample_infra,
            config=MeilisearchConfig(),
            error="Benchmark failed",
        )

        temp_store.add(success)
        temp_store.add(failed)

        all_trials = temp_store.find(service="meilisearch")
        successful = temp_store.find(service="meilisearch", successful_only=True)

        assert len(all_trials) == 2
        assert len(successful) == 1
        assert successful[0].error is None


class TestTrialStoreFindByConfig:
    """Tests for TrialStore.find_by_config()."""

    def test_find_exact_match(
        self, temp_store: TrialStore, sample_meilisearch_trial: Trial
    ):
        """Should find trial with exact config match."""
        temp_store.add(sample_meilisearch_trial)

        result = temp_store.find_by_config(
            service="meilisearch",
            cloud="selectel",
            infra={"cpu": 4, "ram_gb": 8, "disk_type": "fast", "disk_size_gb": 100},
            config={"max_indexing_memory_mb": 1024, "max_indexing_threads": 4},
        )

        assert result is not None
        assert result.id == 1

    def test_find_partial_match(
        self, temp_store: TrialStore, sample_meilisearch_trial: Trial
    ):
        """Should find trial with partial config match."""
        temp_store.add(sample_meilisearch_trial)

        # Only specify some config fields
        result = temp_store.find_by_config(
            service="meilisearch",
            cloud="selectel",
            infra={"cpu": 4, "ram_gb": 8},
            config={"max_indexing_memory_mb": 1024},
        )

        assert result is not None

    def test_no_match(self, temp_store: TrialStore, sample_meilisearch_trial: Trial):
        """Should return None when no match found."""
        temp_store.add(sample_meilisearch_trial)

        result = temp_store.find_by_config(
            service="meilisearch",
            cloud="selectel",
            infra={"cpu": 8, "ram_gb": 16},  # Different config
            config={},
        )

        assert result is None

    def test_skip_failed_trials(
        self, temp_store: TrialStore, sample_infra: InfraConfig
    ):
        """Should skip failed trials even if config matches."""
        failed = Trial(
            service="meilisearch",
            cloud="selectel",
            infra=sample_infra,
            config=MeilisearchConfig(max_indexing_memory_mb=1024),
            error="Failed",
        )
        temp_store.add(failed)

        result = temp_store.find_by_config(
            service="meilisearch",
            cloud="selectel",
            infra={"cpu": 4, "ram_gb": 8},
            config={"max_indexing_memory_mb": 1024},
        )

        assert result is None


class TestTrialStoreGetById:
    """Tests for TrialStore.get_by_id()."""

    def test_get_existing(
        self, temp_store: TrialStore, sample_meilisearch_trial: Trial
    ):
        """Should return trial with matching ID."""
        added = temp_store.add(sample_meilisearch_trial)

        assert added.id is not None
        result = temp_store.get_by_id(added.id)

        assert result is not None
        assert result.id == added.id

    def test_get_nonexistent(self, temp_store: TrialStore):
        """Should return None for non-existent ID."""
        result = temp_store.get_by_id(999)
        assert result is None


class TestTrialModels:
    """Tests for Trial model validation."""

    def test_meilisearch_trial_valid(self, sample_infra: InfraConfig):
        """Valid Meilisearch trial should pass validation."""
        trial = Trial(
            service="meilisearch",
            cloud="selectel",
            infra=sample_infra,
            config=MeilisearchConfig(),
            metrics=MeilisearchMetrics(
                qps=1000, p50_ms=10, p95_ms=20, p99_ms=30, indexing_time_s=5
            ),
        )
        assert trial.service == "meilisearch"
        assert trial.is_successful()

    def test_redis_trial_valid(self, sample_infra: InfraConfig):
        """Valid Redis trial should pass validation."""
        trial = Trial(
            service="redis",
            cloud="selectel",
            infra=sample_infra,
            config=RedisConfig(maxmemory_mb=4096),
            metrics=RedisMetrics(
                ops_per_sec=100000,
                latency_avg_ms=0.5,
                latency_p99_ms=1.0,
                memory_used_mb=2000,
            ),
        )
        assert trial.service == "redis"
        assert trial.is_successful()

    def test_postgres_trial_valid(self, sample_infra: InfraConfig):
        """Valid PostgreSQL trial should pass validation."""
        trial = Trial(
            service="postgres",
            cloud="selectel",
            infra=sample_infra,
            config=PostgresConfig(
                shared_buffers_mb=2048,
                work_mem_mb=256,
                effective_cache_size_mb=6144,
            ),
            metrics=PostgresMetrics(
                tps=5000,
                latency_avg_ms=2.0,
                latency_p95_ms=5.0,
            ),
        )
        assert trial.service == "postgres"
        assert trial.is_successful()

    def test_minio_trial_valid(self, sample_infra: InfraConfig):
        """Valid MinIO trial should pass validation."""
        trial = Trial(
            service="minio",
            cloud="selectel",
            infra=sample_infra,
            config=MinioConfig(nodes=4, drives_per_node=4),
            metrics=MinioMetrics(
                throughput_mbps=500,
                latency_p50_ms=5,
                latency_p95_ms=15,
            ),
        )
        assert trial.service == "minio"
        assert trial.is_successful()

    def test_failed_trial(self, sample_infra: InfraConfig):
        """Failed trial should have error and no metrics."""
        trial = Trial(
            service="meilisearch",
            cloud="selectel",
            infra=sample_infra,
            config=MeilisearchConfig(),
            error="Terraform apply failed",
        )
        assert not trial.is_successful()
        assert trial.error == "Terraform apply failed"
        assert trial.metrics is None

    def test_invalid_service_rejected(self, sample_infra: InfraConfig):
        """Invalid service type should raise validation error."""
        with pytest.raises(ValueError):
            Trial(
                service="unknown",  # type: ignore
                cloud="selectel",
                infra=sample_infra,
                config=MeilisearchConfig(),
            )

    def test_timestamp_auto_generated(self, sample_infra: InfraConfig):
        """Timestamp should be auto-generated if not provided."""
        trial = Trial(
            service="meilisearch",
            cloud="selectel",
            infra=sample_infra,
            config=MeilisearchConfig(),
        )
        assert trial.timestamp is not None
        assert isinstance(trial.timestamp, datetime)

    def test_login_optional(self, sample_infra: InfraConfig):
        """Login should be optional and default to None."""
        trial = Trial(
            service="meilisearch",
            cloud="selectel",
            infra=sample_infra,
            config=MeilisearchConfig(),
        )
        assert trial.login is None

    def test_login_stored(self, sample_infra: InfraConfig):
        """Login should be stored when provided."""
        trial = Trial(
            service="meilisearch",
            cloud="selectel",
            infra=sample_infra,
            config=MeilisearchConfig(),
            login="damir",
        )
        assert trial.login == "damir"

    def test_schema_version_default(self, sample_infra: InfraConfig):
        """Schema version should default to 1."""
        trial = Trial(
            service="meilisearch",
            cloud="selectel",
            infra=sample_infra,
            config=MeilisearchConfig(),
        )
        assert trial.schema_version == 1


class TestTrialCount:
    """Tests for TrialStore.count()."""

    def test_count_all(
        self,
        temp_store: TrialStore,
        sample_meilisearch_trial: Trial,
        sample_redis_trial: Trial,
    ):
        """Count without filter should return all trials."""
        temp_store.add(sample_meilisearch_trial)
        temp_store.add(sample_redis_trial)

        assert temp_store.count() == 2

    def test_count_by_service(
        self,
        temp_store: TrialStore,
        sample_meilisearch_trial: Trial,
        sample_redis_trial: Trial,
    ):
        """Count with service filter should return filtered count."""
        temp_store.add(sample_meilisearch_trial)
        temp_store.add(sample_redis_trial)

        assert temp_store.count(service="meilisearch") == 1
        assert temp_store.count(service="redis") == 1
        assert temp_store.count(service="postgres") == 0
