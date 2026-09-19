"""Iteration history logger for optimization runs.

Logs each optimization iteration in JSON and CSV formats for
analysis and reproducibility.
"""

from __future__ import annotations

import csv
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IterationRecord:
    """Record of a single optimization iteration."""

    iteration: int
    parameters: dict[str, float]
    results: dict[str, float]
    cost: float
    stage: str = ""
    timestamp: float = 0.0
    is_best: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "parameters": self.parameters,
            "results": self.results,
            "cost": round(self.cost, 6),
            "stage": self.stage,
            "timestamp": self.timestamp,
            "is_best": self.is_best,
        }


@dataclass
class IterationHistory:
    """Logs and persists optimization iteration history."""

    output_dir: Path
    records: list[IterationRecord] = field(default_factory=list)
    _best_cost: float = field(default=float("inf"), init=False)
    _best_iteration: int = field(default=-1, init=False)

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        iteration: int,
        parameters: dict[str, float],
        results: dict[str, float],
        cost: float,
        stage: str = "",
    ) -> IterationRecord:
        """Log a single iteration."""
        is_best = cost < self._best_cost
        if is_best:
            self._best_cost = cost
            self._best_iteration = iteration

        record = IterationRecord(
            iteration=iteration,
            parameters=parameters,
            results=results,
            cost=cost,
            stage=stage,
            timestamp=time.time(),
            is_best=is_best,
        )
        self.records.append(record)
        return record

    @property
    def best_record(self) -> IterationRecord | None:
        """Return the best iteration record."""
        if not self.records:
            return None
        return min(self.records, key=lambda r: r.cost)

    def save_json(self, filename: str = "optimization_history.json") -> Path:
        """Save history to a JSON file."""
        path = self.output_dir / filename
        data = {
            "total_iterations": len(self.records),
            "best_iteration": self._best_iteration,
            "best_cost": round(self._best_cost, 6),
            "records": [r.to_dict() for r in self.records],
        }
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.info("Saved optimization history to %s", path)
        return path

    def save_csv(self, filename: str = "optimization_history.csv") -> Path:
        """Save history to a CSV file."""
        path = self.output_dir / filename
        if not self.records:
            path.write_text("", encoding="utf-8")
            return path

        # Collect all parameter and result keys
        param_keys = sorted(
            set().union(*(r.parameters.keys() for r in self.records))
        )
        result_keys = sorted(
            set().union(*(r.results.keys() for r in self.records))
        )

        fieldnames = (
            ["iteration", "stage", "cost", "is_best"]
            + [f"param_{k}" for k in param_keys]
            + [f"result_{k}" for k in result_keys]
        )

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in self.records:
                row: dict[str, Any] = {
                    "iteration": r.iteration,
                    "stage": r.stage,
                    "cost": round(r.cost, 6),
                    "is_best": r.is_best,
                }
                for k in param_keys:
                    val = r.parameters.get(k, 0)
                    row[f"param_{k}"] = round(val, 6) if isinstance(val, (int, float)) else str(val)
                for k in result_keys:
                    val = r.results.get(k, 0)
                    row[f"result_{k}"] = round(val, 6) if isinstance(val, (int, float)) else str(val)
                writer.writerow(row)

        logger.info("Saved optimization CSV to %s", path)
        return path

    def log_iteration(
        self,
        iteration: int,
        stage: str,
        parameters: dict[str, float],
        results: dict[str, float],
        cost: float,
    ) -> IterationRecord:
        return self.log(iteration, parameters, results, cost, stage)


OptimizationHistoryLogger = IterationHistory
