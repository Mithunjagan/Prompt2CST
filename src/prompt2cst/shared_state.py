"""Shared project workspace and SQLite state management.

``ProjectWorkspace`` manages the directory layout and atomic JSON
artifact versioning for the swarm.  Every artifact is immutable
once written; newer versions get sequential version numbers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)


class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


class ArtifactType(StrEnum):
    REQUIREMENTS = "requirements"
    EVIDENCE = "evidence"
    CANDIDATE_ARCHITECTURES = "candidate_architectures"
    SELECTED_ARCHITECTURE = "selected_architecture"
    DESIGN_IR = "design_ir"
    PARAMETERS = "parameters"
    SIMULATION_RESULT = "simulation_result"
    OPTIMIZATION_ITERATION = "optimization_iteration"
    SENSITIVITY = "sensitivity"
    VALIDATION = "validation"
    REPORT = "report"


_WORKSPACE_DIRS = (
    "requirements",
    "research",
    "research/uploaded",
    "architecture",
    "design",
    "simulations",
    "optimization",
    "agents",
    "final",
)

_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    depends_on TEXT DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    detail TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    sha256 TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at REAL NOT NULL,
    created_by TEXT DEFAULT '',
    PRIMARY KEY (artifact_id, version)
);

CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT NOT NULL,
    agent_a TEXT NOT NULL,
    agent_b TEXT NOT NULL,
    description TEXT NOT NULL,
    resolution TEXT DEFAULT '',
    resolved_at REAL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS project_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class ProjectWorkspace:
    """Manages a project directory with structured subdirectories,
    SQLite state database, and versioned JSON artifacts.
    """

    root: Path
    _db: sqlite3.Connection | None = field(default=None, init=False, repr=False)
    _write_lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    def initialize(self) -> None:
        """Create the workspace directories and SQLite database."""
        self.root.mkdir(parents=True, exist_ok=True)
        for subdir in _WORKSPACE_DIRS:
            (self.root / subdir).mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info("ProjectWorkspace initialized at %s", self.root)

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        db_path = self.root / "state.db"
        self._db = sqlite3.connect(
            str(db_path), timeout=30, check_same_thread=False, isolation_level=None
        )
        self._db.execute("PRAGMA busy_timeout = 30000")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(_DB_SCHEMA)

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            self._init_db()
        assert self._db is not None
        return self._db

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    def create_task(
        self,
        task_id: str,
        agent: str,
        depends_on: list[str] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        now = time.time()
        self.db.execute(
            "INSERT OR REPLACE INTO tasks "
            "(task_id, agent, state, depends_on, created_at, updated_at, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                agent,
                TaskState.PENDING,
                json.dumps(depends_on or []),
                now,
                now,
                json.dumps(detail or {}),
            ),
        )
        self.db.commit()

    def update_task_state(
        self,
        task_id: str,
        state: TaskState,
        detail: dict[str, Any] | None = None,
    ) -> None:
        now = time.time()
        if detail is not None:
            self.db.execute(
                "UPDATE tasks SET state = ?, updated_at = ?, detail = ? "
                "WHERE task_id = ?",
                (state, now, json.dumps(detail), task_id),
            )
        else:
            self.db.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE task_id = ?",
                (state, now, task_id),
            )
        self.db.commit()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT task_id, agent, state, depends_on, created_at, "
            "updated_at, detail FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0],
            "agent": row[1],
            "state": row[2],
            "depends_on": json.loads(row[3]),
            "created_at": row[4],
            "updated_at": row[5],
            "detail": json.loads(row[6]),
        }

    def list_tasks(self, state: TaskState | None = None) -> list[dict[str, Any]]:
        if state is not None:
            rows = self.db.execute(
                "SELECT task_id, agent, state, depends_on, created_at, "
                "updated_at, detail FROM tasks WHERE state = ? ORDER BY created_at",
                (state,),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT task_id, agent, state, depends_on, created_at, "
                "updated_at, detail FROM tasks ORDER BY created_at"
            ).fetchall()
        return [
            {
                "task_id": r[0],
                "agent": r[1],
                "state": r[2],
                "depends_on": json.loads(r[3]),
                "created_at": r[4],
                "updated_at": r[5],
                "detail": json.loads(r[6]),
            }
            for r in rows
        ]

    def ready_tasks(self) -> list[dict[str, Any]]:
        """Return pending tasks whose dependencies are all completed."""
        pending = self.list_tasks(TaskState.PENDING)
        completed_ids = {
            t["task_id"] for t in self.list_tasks(TaskState.COMPLETED)
        }
        return [
            t
            for t in pending
            if all(dep in completed_ids for dep in t["depends_on"])
        ]

    # ------------------------------------------------------------------
    # Artifact versioning
    # ------------------------------------------------------------------

    def save_artifact(
        self,
        artifact_id: str,
        artifact_type: ArtifactType,
        data: dict[str, Any],
        created_by: str = "",
    ) -> Path:
        """Atomically write a new immutable artifact version.

        ``BEGIN IMMEDIATE`` serializes competing processes before a version is
        allocated.  The in-process lock also protects a shared connection from
        concurrent Python workers.  The JSON file is replaced atomically before
        its transaction is committed, so readers never observe a partial file.
        """
        content = json.dumps(data, indent=2, sort_keys=True, default=str)
        sha256 = hashlib.sha256(content.encode()).hexdigest()

        # Determine subdirectory from artifact type
        type_to_dir = {
            ArtifactType.REQUIREMENTS: "requirements",
            ArtifactType.EVIDENCE: "research",
            ArtifactType.CANDIDATE_ARCHITECTURES: "architecture",
            ArtifactType.SELECTED_ARCHITECTURE: "architecture",
            ArtifactType.DESIGN_IR: "design",
            ArtifactType.PARAMETERS: "design",
            ArtifactType.SIMULATION_RESULT: "simulations",
            ArtifactType.OPTIMIZATION_ITERATION: "optimization",
            ArtifactType.SENSITIVITY: "optimization",
            ArtifactType.VALIDATION: "final",
            ArtifactType.REPORT: "final",
        }
        subdir = type_to_dir.get(artifact_type, ".")
        target_dir = self.root / subdir
        target_dir.mkdir(parents=True, exist_ok=True)

        with self._write_lock:
            db = self.db
            temporary_path: Path | None = None
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT MAX(version) FROM artifacts WHERE artifact_id = ?",
                    (artifact_id,),
                ).fetchone()
                version = (row[0] or 0) + 1
                artifact_path = target_dir / f"{artifact_id}_v{version}.json"
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", delete=False, dir=target_dir,
                    prefix=f".{artifact_id}_", suffix=".tmp"
                ) as temporary:
                    temporary.write(content)
                    temporary_path = Path(temporary.name)
                os.replace(temporary_path, artifact_path)
                temporary_path = None
                db.execute(
                    "INSERT INTO artifacts "
                    "(artifact_id, artifact_type, version, sha256, path, created_at, created_by) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (artifact_id, artifact_type, version, sha256, str(artifact_path), time.time(), created_by),
                )
                db.commit()
            except Exception:
                db.rollback()
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
                raise

        logger.info(
            "Saved artifact %s v%d (%s) -> %s",
            artifact_id, version, sha256[:12], artifact_path,
        )
        return artifact_path

    def load_artifact(
        self,
        artifact_id: str,
        version: int | None = None,
    ) -> dict[str, Any] | None:
        """Load an artifact by ID.  If version is None, load the latest."""
        if version is not None:
            row = self.db.execute(
                "SELECT path FROM artifacts WHERE artifact_id = ? AND version = ?",
                (artifact_id, version),
            ).fetchone()
        else:
            row = self.db.execute(
                "SELECT path FROM artifacts WHERE artifact_id = ? "
                "ORDER BY version DESC LIMIT 1",
                (artifact_id,),
            ).fetchone()
        if row is None:
            return None
        path = Path(row[0])
        if not path.exists():
            logger.warning("Artifact file missing: %s", path)
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def artifact_versions(self, artifact_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT version, sha256, path, created_at, created_by "
            "FROM artifacts WHERE artifact_id = ? ORDER BY version",
            (artifact_id,),
        ).fetchall()
        return [
            {
                "version": r[0],
                "sha256": r[1],
                "path": r[2],
                "created_at": r[3],
                "created_by": r[4],
            }
            for r in rows
        ]

    def list_artifacts(self, artifact_id: str | None = None) -> list[dict[str, Any]]:
        """List immutable artifact versions, optionally for one artifact ID."""
        if artifact_id is not None:
            return self.artifact_versions(artifact_id)
        rows = self.db.execute(
            "SELECT artifact_id, artifact_type, version, sha256, path, created_at, "
            "created_by FROM artifacts ORDER BY artifact_id, version"
        ).fetchall()
        return [
            {
                "artifact_id": row[0],
                "artifact_type": row[1],
                "version": row[2],
                "sha256": row[3],
                "path": row[4],
                "created_at": row[5],
                "created_by": row[6],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Conflict management
    # ------------------------------------------------------------------

    def record_conflict(
        self,
        artifact_id: str,
        agent_a: str,
        agent_b: str,
        description: str,
    ) -> int:
        """Record a conflict between two agents on an artifact."""
        now = time.time()
        cursor = self.db.execute(
            "INSERT INTO conflicts "
            "(artifact_id, agent_a, agent_b, description, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (artifact_id, agent_a, agent_b, description, now),
        )
        self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def resolve_conflict(self, conflict_id: int, resolution: str) -> None:
        now = time.time()
        self.db.execute(
            "UPDATE conflicts SET resolution = ?, resolved_at = ? "
            "WHERE conflict_id = ?",
            (resolution, now, conflict_id),
        )
        self.db.commit()

    def list_conflicts(
        self, resolved: bool | None = None
    ) -> list[dict[str, Any]]:
        if resolved is True:
            rows = self.db.execute(
                "SELECT * FROM conflicts WHERE resolved_at IS NOT NULL "
                "ORDER BY created_at"
            ).fetchall()
        elif resolved is False:
            rows = self.db.execute(
                "SELECT * FROM conflicts WHERE resolved_at IS NULL "
                "ORDER BY created_at"
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM conflicts ORDER BY created_at"
            ).fetchall()
        return [
            {
                "conflict_id": r[0],
                "artifact_id": r[1],
                "agent_a": r[2],
                "agent_b": r[3],
                "description": r[4],
                "resolution": r[5],
                "resolved_at": r[6],
                "created_at": r[7],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Project metadata
    # ------------------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO project_meta (key, value) VALUES (?, ?)",
            (key, value),
        )
        self.db.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute(
            "SELECT value FROM project_meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def save_metadata(self, key: str, data: dict[str, Any]) -> None:
        self.set_meta(key, json.dumps(data))

    def load_metadata(self, key: str) -> dict[str, Any] | None:
        val = self.get_meta(key)
        return json.loads(val) if val else None

    # ------------------------------------------------------------------
    # Serialization / resumption
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the entire project state."""
        return {
            "root": str(self.root),
            "tasks": self.list_tasks(),
            "artifacts": {
                aid: self.artifact_versions(aid)
                for aid in {
                    row[0]
                    for row in self.db.execute(
                        "SELECT DISTINCT artifact_id FROM artifacts"
                    ).fetchall()
                }
            },
            "conflicts": self.list_conflicts(),
        }

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
