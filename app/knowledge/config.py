"""Configuration for the knowledge layer."""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict


class KnowledgeConfigError(Exception):
    pass


@dataclass
class KnowledgeConfig:
    catalog_db: str = "catalog/catalog.sqlite3"      # first-layer catalog (read-only)
    knowledge_db: str = "state/knowledge.sqlite3"    # knowledge layer's own database
    snapshot_root: str = "state/snapshots"           # content-addressed blob store
    library_config: str = "config/config.json"       # library config (source roots)
    register_stages: tuple = ("snapshot",)
    sync_batch_size: int = 500
    job_lease_seconds: int = 900
    job_max_attempts: int = 5
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeConfig":
        stages = data.get("register_stages", ["snapshot"])
        if not isinstance(stages, list) or not stages:
            raise KnowledgeConfigError("'register_stages' must be a non-empty list")
        sync = data.get("sync") or {}
        jobs = data.get("jobs") or {}
        return cls(
            catalog_db=str(data.get("catalog_db", "catalog/catalog.sqlite3")),
            knowledge_db=str(data.get("knowledge_db", "state/knowledge.sqlite3")),
            snapshot_root=str(data.get("snapshot_root", "state/snapshots")),
            library_config=str(data.get("library_config", "config/config.json")),
            register_stages=tuple(str(s) for s in stages),
            sync_batch_size=max(1, int(sync.get("batch_size", 500))),
            job_lease_seconds=max(30, int(jobs.get("lease_seconds", 900))),
            job_max_attempts=max(1, int(jobs.get("max_attempts", 5))),
            extra={k: v for k, v in data.items()
                   if k not in ("catalog_db", "knowledge_db", "snapshot_root",
                                "library_config", "register_stages", "sync", "jobs")},
        )

    @classmethod
    def load(cls, path: str) -> "KnowledgeConfig":
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls.from_dict(data)

    def resolve(self, base: str) -> "KnowledgeConfig":
        """Return a copy with relative paths resolved against *base*."""
        clone = copy.deepcopy(self)
        for attr in ("catalog_db", "knowledge_db", "snapshot_root", "library_config"):
            value = getattr(clone, attr)
            if not os.path.isabs(value):
                setattr(clone, attr, os.path.normpath(os.path.join(base, value)))
        return clone


def load_knowledge_config(path: str) -> KnowledgeConfig:
    return KnowledgeConfig.load(path).resolve(os.path.dirname(os.path.abspath(path)))
