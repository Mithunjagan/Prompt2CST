"""Checkpoint manager for optimization resumability.

Saves and loads state checkpoints (checkpoint.json) to allow interrupting
and resuming optimization runs without restarting from iteration zero.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CheckpointData:
    schema_version: str = "1.0"
    project_name: str = ""
    topology_name: str = ""
    status: str = "in_progress"
    current_iteration: int = 0
    completed_stages: list[str] = field(default_factory=list)
    current_stage: str = "initial"
    latest_parameters: dict[str, float] = field(default_factory=dict)
    latest_simulation_result: dict[str, float] = field(default_factory=dict)
    best_cost: float = float("inf")
    best_parameters: dict[str, float] = field(default_factory=dict)
    best_result: dict[str, float] = field(default_factory=dict)
    history_records: list[dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d["best_cost"] == float("inf"):
            d["best_cost"] = None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CheckpointData:
        cost = d.get("best_cost")
        if cost is None:
            d["best_cost"] = float("inf")
        return cls(**d)


class CheckpointManager:
    """Manages writing and reading checkpoint.json in the project directory."""

    def __init__(self, output_dir: Path | str) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_file = self.output_dir / "checkpoint.json"

    def save(self, data: CheckpointData) -> Path:
        data.timestamp = time.time()
        payload = data.to_dict()
        tmp_file = self.output_dir / "checkpoint.tmp"
        tmp_file.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        # Atomic replace
        tmp_file.replace(self.checkpoint_file)
        logger.info("Saved checkpoint at iteration %d to %s", data.current_iteration, self.checkpoint_file)
        return self.checkpoint_file

    def load(self) -> CheckpointData | None:
        if not self.checkpoint_file.exists():
            return None
        try:
            payload = json.loads(self.checkpoint_file.read_text(encoding="utf-8"))
            return CheckpointData.from_dict(payload)
        except Exception as exc:
            logger.error("Failed to load checkpoint from %s: %s", self.checkpoint_file, exc)
            return None
