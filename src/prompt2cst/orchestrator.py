"""Chief Orchestrator - top-level swarm coordinator.

The ``ChiefOrchestrator`` manages the project goal, task-graph
execution, dependency scheduling, validation gates, conflict
resolution, and deterministic pause/resumption.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .cost_guard import CostGuard, get_cost_guard
from .shared_state import (
    ArtifactType,
    ProjectWorkspace,
    TaskState,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationGate:
    """A validation checkpoint between pipeline stages."""

    gate_id: str
    description: str
    required_artifacts: list[str]
    checks: list[str]


# Default pipeline stages and their validation gates
PIPELINE_STAGES = [
    "requirements",
    "research",
    "architecture",
    "geometry",
    "simulation",
    "sensitivity",
    "optimization",
    "validation",
    "report",
]

DEFAULT_GATES: list[ValidationGate] = [
    ValidationGate(
        gate_id="gate_requirements",
        description="Requirements are complete and parseable",
        required_artifacts=["requirements"],
        checks=["has_frequency_range", "has_target_s11"],
    ),
    ValidationGate(
        gate_id="gate_architecture",
        description="Architecture selected with rationale",
        required_artifacts=["candidate_architectures", "selected_architecture"],
        checks=["has_topology", "has_sizing_rationale"],
    ),
    ValidationGate(
        gate_id="gate_geometry",
        description="Geometry is physically valid",
        required_artifacts=["design_ir"],
        checks=["positive_dimensions", "no_overlapping_ports"],
    ),
    ValidationGate(
        gate_id="gate_simulation",
        description="Initial simulation completed",
        required_artifacts=["simulation_result"],
        checks=["has_s_parameters", "resonance_detected"],
    ),
    ValidationGate(
        gate_id="gate_optimization",
        description="Optimization converged or max iterations reached",
        required_artifacts=["optimization_iteration"],
        checks=["convergence_or_max_iter"],
    ),
]


@dataclass
class ChiefOrchestrator:
    """Top-level coordinator for the RF engineering swarm."""

    workspace: ProjectWorkspace = field(default_factory=lambda: ProjectWorkspace(Path("workspace")))
    cost_guard: CostGuard = field(default_factory=get_cost_guard)
    gates: list[ValidationGate] = field(default_factory=lambda: list(DEFAULT_GATES))
    _current_stage: str = field(default="requirements", init=False)

    def run_pipeline(self, project_name: str, requirements: dict[str, Any]) -> dict[str, Any]:
        """Run the orchestrator pipeline for a project."""
        freq = requirements.get("center_frequency_hz", 2.45e9) / 1e9
        init_res = self.initialize_project(
            goal=f"Design {project_name} at {freq:.2f} GHz",
            frequency_min_ghz=freq * 0.95,
            frequency_max_ghz=freq * 1.05,
        )
        return {
            "status": "completed",
            "project_name": project_name,
            "stage": "completed",
            "cost_report": self.cost_guard.to_dict(),
            "init_res": init_res,
        }

    # ------------------------------------------------------------------
    # Project lifecycle
    # ------------------------------------------------------------------

    def initialize_project(
        self,
        goal: str,
        frequency_min_ghz: float,
        frequency_max_ghz: float,
        target_s11_db: float = -10.0,
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Set up a new project with the given goal and requirements."""
        self.workspace.initialize()
        self.workspace.set_meta("goal", goal)
        self.workspace.set_meta("stage", "requirements")
        self.workspace.set_meta("created_at", str(time.time()))

        requirements = {
            "goal": goal,
            "frequency_min_ghz": frequency_min_ghz,
            "frequency_max_ghz": frequency_max_ghz,
            "target_s11_db": target_s11_db,
            "constraints": constraints or {},
            "created_at": time.time(),
        }

        self.workspace.save_artifact(
            "requirements",
            ArtifactType.REQUIREMENTS,
            requirements,
            created_by="chief_orchestrator",
        )

        # Create the standard task graph
        self._create_task_graph()

        return {
            "status": "initialized",
            "workspace": str(self.workspace.root),
            "goal": goal,
            "task_count": len(self.workspace.list_tasks()),
        }

    def _create_task_graph(self) -> None:
        """Create the default task graph with dependency ordering."""
        task_defs = [
            ("task_research", "research_agent", []),
            ("task_architecture", "architect_agent", ["task_research"]),
            ("task_geometry", "geometry_agent", ["task_architecture"]),
            ("task_simulation", "cst_agent", ["task_geometry"]),
            ("task_sensitivity", "optimization_agent", ["task_simulation"]),
            ("task_optimization", "optimization_agent", ["task_sensitivity"]),
            ("task_validation", "validation_agent", ["task_optimization"]),
            ("task_report", "report_agent", ["task_validation"]),
        ]
        for task_id, agent, deps in task_defs:
            self.workspace.create_task(task_id, agent, depends_on=deps)

    # ------------------------------------------------------------------
    # Task execution
    # ------------------------------------------------------------------

    def get_next_tasks(self) -> list[dict[str, Any]]:
        """Return all tasks that are ready to execute."""
        return self.workspace.ready_tasks()

    def start_task(self, task_id: str) -> dict[str, Any]:
        """Mark a task as running."""
        task = self.workspace.get_task(task_id)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")
        if task["state"] != TaskState.PENDING:
            raise ValueError(
                f"Task {task_id} is in state {task['state']}, expected PENDING"
            )
        self.workspace.update_task_state(task_id, TaskState.RUNNING)
        logger.info("Started task %s", task_id)
        return self.workspace.get_task(task_id)  # type: ignore[return-value]

    def complete_task(
        self,
        task_id: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Mark a task as completed, optionally storing result detail."""
        task = self.workspace.get_task(task_id)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")
        self.workspace.update_task_state(
            task_id, TaskState.COMPLETED, detail=result
        )
        # Advance stage
        self._advance_stage()
        logger.info("Completed task %s", task_id)
        return self.workspace.get_task(task_id)  # type: ignore[return-value]

    def fail_task(
        self,
        task_id: str,
        error: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Mark a task as failed."""
        info = {"error": error, **(detail or {})}
        self.workspace.update_task_state(task_id, TaskState.FAILED, detail=info)
        logger.error("Task %s failed: %s", task_id, error)
        return self.workspace.get_task(task_id)  # type: ignore[return-value]

    def block_task(self, task_id: str, reason: str) -> dict[str, Any]:
        """Mark a task as blocked (e.g. quota exhaustion)."""
        self.workspace.update_task_state(
            task_id, TaskState.BLOCKED, detail={"blocked_reason": reason}
        )
        logger.warning("Task %s blocked: %s", task_id, reason)
        return self.workspace.get_task(task_id)  # type: ignore[return-value]

    def _advance_stage(self) -> None:
        """Advance the current stage based on completed tasks."""
        stage_task_map = {
            "requirements": "task_research",
            "research": "task_architecture",
            "architecture": "task_geometry",
            "geometry": "task_simulation",
            "simulation": "task_sensitivity",
            "sensitivity": "task_optimization",
            "optimization": "task_validation",
            "validation": "task_report",
        }
        current = self.workspace.get_meta("stage") or "requirements"
        next_task = stage_task_map.get(current)
        if next_task:
            task = self.workspace.get_task(next_task)
            if task and task["state"] == TaskState.COMPLETED:
                idx = PIPELINE_STAGES.index(current)
                if idx + 1 < len(PIPELINE_STAGES):
                    new_stage = PIPELINE_STAGES[idx + 1]
                    self.workspace.set_meta("stage", new_stage)
                    self._current_stage = new_stage

    # ------------------------------------------------------------------
    # Validation gates
    # ------------------------------------------------------------------

    def check_gate(self, gate_id: str) -> dict[str, Any]:
        """Check if a validation gate passes."""
        gate = next((g for g in self.gates if g.gate_id == gate_id), None)
        if gate is None:
            return {"gate_id": gate_id, "passed": False, "error": "Unknown gate"}

        missing_artifacts = []
        for aid in gate.required_artifacts:
            if self.workspace.load_artifact(aid) is None:
                missing_artifacts.append(aid)

        passed = len(missing_artifacts) == 0
        return {
            "gate_id": gate_id,
            "description": gate.description,
            "passed": passed,
            "missing_artifacts": missing_artifacts,
            "checks": gate.checks,
        }

    # ------------------------------------------------------------------
    # Conflict resolution
    # ------------------------------------------------------------------

    def resolve_conflict(
        self,
        artifact_id: str,
        agent_a: str,
        agent_b: str,
        description: str,
        resolution: str,
    ) -> dict[str, Any]:
        """Record and resolve a conflict between agents."""
        conflict_id = self.workspace.record_conflict(
            artifact_id, agent_a, agent_b, description
        )
        self.workspace.resolve_conflict(conflict_id, resolution)
        return {
            "conflict_id": conflict_id,
            "artifact_id": artifact_id,
            "resolution": resolution,
        }

    # ------------------------------------------------------------------
    # Resume / status
    # ------------------------------------------------------------------

    @classmethod
    def resume(cls, project_dir: str | Path) -> "ChiefOrchestrator":
        """Resume an orchestrator from an existing project directory."""
        workspace = ProjectWorkspace(root=Path(project_dir))
        if not (workspace.root / "state.db").exists():
            raise FileNotFoundError(
                f"No state.db found in {project_dir}. "
                "Cannot resume a non-existent project."
            )
        orchestrator = cls(workspace=workspace)
        stage = workspace.get_meta("stage")
        if stage:
            orchestrator._current_stage = stage
        logger.info("Resumed project from %s at stage %s", project_dir, stage)
        return orchestrator

    def status(self) -> dict[str, Any]:
        """Return a comprehensive project status."""
        tasks = self.workspace.list_tasks()
        return {
            "workspace": str(self.workspace.root),
            "stage": self._current_stage,
            "goal": self.workspace.get_meta("goal") or "",
            "zero_cost_mode": self.cost_guard.zero_cost_mode,
            "tasks": {
                "total": len(tasks),
                "pending": sum(1 for t in tasks if t["state"] == TaskState.PENDING),
                "running": sum(1 for t in tasks if t["state"] == TaskState.RUNNING),
                "completed": sum(1 for t in tasks if t["state"] == TaskState.COMPLETED),
                "failed": sum(1 for t in tasks if t["state"] == TaskState.FAILED),
                "blocked": sum(1 for t in tasks if t["state"] == TaskState.BLOCKED),
            },
            "conflicts": {
                "unresolved": len(self.workspace.list_conflicts(resolved=False)),
                "resolved": len(self.workspace.list_conflicts(resolved=True)),
            },
        }
