"""SHA-256 parameter hashing result cache.

Caches simulation results keyed by a deterministic hash of the
input parameters, avoiding redundant simulation runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    param_hash TEXT PRIMARY KEY,
    parameters_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    runner_label TEXT NOT NULL,
    created_at REAL NOT NULL,
    hit_count INTEGER DEFAULT 0
);
"""


def _hash_parameters(parameters: dict[str, float], context: str = "") -> str:
    """Compute a deterministic SHA-256 key, scoped to simulation context."""
    canonical = json.dumps(
        {"parameters": {k: round(v, 10) for k, v in sorted(parameters.items())}, "context": context},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class ResultCache:
    """SQLite-backed simulation result cache with SHA-256 parameter hashing."""

    db_path: Path
    _conn: sqlite3.Connection | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.executescript(_CACHE_SCHEMA)
        self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
        return self._conn

    def get(self, parameters: dict[str, float], context: str = "") -> dict[str, float] | None:
        """Look up cached result by parameter hash."""
        param_hash = _hash_parameters(parameters, context)
        row = self.conn.execute(
            "SELECT result_json FROM cache WHERE param_hash = ?",
            (param_hash,),
        ).fetchone()
        if row is not None:
            self.conn.execute(
                "UPDATE cache SET hit_count = hit_count + 1 WHERE param_hash = ?",
                (param_hash,),
            )
            self.conn.commit()
            logger.debug("Cache hit for %s", param_hash[:12])
            return json.loads(row[0])
        return None

    def put(
        self,
        parameters: dict[str, float],
        result: dict[str, float],
        runner_label: str = "",
        context: str = "",
    ) -> str:
        """Store a result in the cache, returning the parameter hash."""
        param_hash = _hash_parameters(parameters, context)
        self.conn.execute(
            "INSERT OR REPLACE INTO cache "
            "(param_hash, parameters_json, result_json, runner_label, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                param_hash,
                json.dumps(parameters, sort_keys=True),
                json.dumps(result, sort_keys=True),
                runner_label,
                time.time(),
            ),
        )
        self.conn.commit()
        return param_hash

    def size(self) -> int:
        """Number of cached entries."""
        row = self.conn.execute("SELECT COUNT(*) FROM cache").fetchone()
        return row[0] if row else 0

    def stats(self) -> dict[str, Any]:
        """Cache statistics."""
        total = self.size()
        total_hits = self.conn.execute(
            "SELECT SUM(hit_count) FROM cache"
        ).fetchone()[0] or 0
        return {
            "entries": total,
            "total_hits": total_hits,
            "db_path": str(self.db_path),
        }

    def clear(self) -> int:
        """Clear all cached entries, returning count deleted."""
        count = self.size()
        self.conn.execute("DELETE FROM cache")
        self.conn.commit()
        return count

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


SimulationResultCache = ResultCache
