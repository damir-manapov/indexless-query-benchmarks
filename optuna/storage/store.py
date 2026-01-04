"""Trial store for persisting benchmark results."""

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from .models import (
    MeilisearchConfig,
    MeilisearchMetrics,
    MinioConfig,
    MinioMetrics,
    PostgresConfig,
    PostgresMetrics,
    RedisConfig,
    RedisMetrics,
    ServiceType,
    Trial,
)

# Mapping from service name to config/metrics types
SERVICE_CONFIG_TYPES: dict[str, type] = {
    "meilisearch": MeilisearchConfig,
    "redis": RedisConfig,
    "postgres": PostgresConfig,
    "minio": MinioConfig,
}

SERVICE_METRICS_TYPES: dict[str, type] = {
    "meilisearch": MeilisearchMetrics,
    "redis": RedisMetrics,
    "postgres": PostgresMetrics,
    "minio": MinioMetrics,
}


class TrialStore:
    """Store for benchmark trial results.

    Handles loading, saving, and querying trial data from a JSON file.
    Trial IDs are auto-incremented.

    Example:
        store = TrialStore(Path("results.json"))

        # Add a trial
        trial = Trial(
            service="meilisearch",
            cloud="selectel",
            infra=InfraConfig(cpu=4, ram_gb=8, disk_type="fast", disk_size_gb=100),
            config=MeilisearchConfig(),
            metrics=MeilisearchMetrics(qps=3000, p50_ms=30, p95_ms=40, p99_ms=50, indexing_time_s=15),
        )
        store.add(trial)

        # Find trials
        results = store.find(service="meilisearch", cloud="selectel")
    """

    def __init__(self, path: Path):
        """Initialize store with path to JSON file."""
        self.path = path
        self._trials: list[Trial] | None = None

    @property
    def trials(self) -> list[Trial]:
        """Lazy-load trials from disk."""
        if self._trials is None:
            self._trials = self._load()
        return self._trials

    def _load(self) -> list[Trial]:
        """Load trials from JSON file."""
        if not self.path.exists():
            return []

        with open(self.path) as f:
            data = json.load(f)

        trials = []
        for item in data:
            trial = self._parse_trial(item)
            if trial:
                trials.append(trial)
        return trials

    def _parse_trial(self, data: dict[str, Any]) -> Trial | None:
        """Parse a dict into a Trial, handling service-specific types."""
        try:
            service = data.get("service")
            if service not in SERVICE_CONFIG_TYPES:
                return None

            # Parse config with correct type
            config_type = SERVICE_CONFIG_TYPES[service]
            if "config" in data and data["config"] is not None:
                data["config"] = config_type.model_validate(data["config"])

            # Parse metrics with correct type
            metrics_type = SERVICE_METRICS_TYPES[service]
            if "metrics" in data and data["metrics"] is not None:
                data["metrics"] = metrics_type.model_validate(data["metrics"])

            return Trial.model_validate(data)
        except Exception:
            # Skip invalid entries
            return None

    def _save(self) -> None:
        """Save trials to JSON file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Use TypeAdapter for proper serialization
        adapter = TypeAdapter(list[Trial])
        data = adapter.dump_python(self.trials, mode="json")

        with open(self.path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _next_id(self) -> int:
        """Get next available trial ID."""
        if not self.trials:
            return 1
        return max(t.id or 0 for t in self.trials) + 1

    def add(self, trial: Trial) -> Trial:
        """Add a trial to the store.

        Auto-assigns an ID if not set.
        Saves to disk immediately.
        """
        if trial.id is None:
            trial.id = self._next_id()

        self.trials.append(trial)
        self._save()
        return trial

    def find(
        self,
        *,
        service: ServiceType | None = None,
        cloud: str | None = None,
        successful_only: bool = False,
    ) -> list[Trial]:
        """Find trials matching criteria.

        Args:
            service: Filter by service type
            cloud: Filter by cloud provider
            successful_only: Only return trials without errors

        Returns:
            List of matching trials
        """
        results = self.trials

        if service:
            results = [t for t in results if t.service == service]

        if cloud:
            results = [t for t in results if t.cloud == cloud]

        if successful_only:
            results = [t for t in results if t.is_successful()]

        return results

    def find_by_config(
        self,
        service: ServiceType,
        cloud: str,
        infra: dict[str, Any],
        config: dict[str, Any],
    ) -> Trial | None:
        """Find a trial with matching infrastructure and service config.

        Useful for checking if a configuration has already been tested.
        Returns the first successful match, or None.
        """
        for trial in self.trials:
            if trial.service != service:
                continue
            if trial.cloud != cloud:
                continue
            if not trial.is_successful():
                continue

            # Compare infra
            trial_infra = trial.infra.model_dump()
            if not self._dict_matches(trial_infra, infra):
                continue

            # Compare config
            trial_config = trial.config.model_dump()
            if not self._dict_matches(trial_config, config):
                continue

            return trial

        return None

    def _dict_matches(self, full: dict, subset: dict) -> bool:
        """Check if all keys in subset match values in full dict."""
        for key, value in subset.items():
            if key not in full:
                return False
            if full[key] != value:
                return False
        return True

    def get_by_id(self, trial_id: int) -> Trial | None:
        """Get a trial by its ID."""
        for trial in self.trials:
            if trial.id == trial_id:
                return trial
        return None

    def count(self, service: ServiceType | None = None) -> int:
        """Count trials, optionally filtered by service."""
        if service:
            return len([t for t in self.trials if t.service == service])
        return len(self.trials)

    def clear(self) -> None:
        """Remove all trials and delete the file."""
        self._trials = []
        if self.path.exists():
            self.path.unlink()

    def reload(self) -> None:
        """Reload trials from disk, discarding in-memory changes."""
        self._trials = None
