from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .capabilities import required_capabilities
from .cst_bridge import (
    CSTBridge,
    CSTExecutionCancelled,
    CSTExecutionError,
    default_output_dir,
)
from .cst_compiler import CompiledDesign, CompiledOperation, compile_design
from .design_ir import DesignIR
from .results import SimulationResult
from .validation import ValidationReport, validate_design
from .workflow import WorkflowState, WorkflowStore


class StoredPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    workflow_id: str
    created_at: str
    content_hash: str
    design_ir: dict[str, Any]
    validation: dict[str, Any]
    compiled: dict[str, Any] | None
    human_preview: str
    machine_preview: dict[str, Any]


class ExecutionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execution_id: str
    plan_id: str
    workflow_id: str
    status: str
    created_at: str
    updated_at: str
    project_name: str
    completed_operations: list[dict[str, Any]] = Field(default_factory=list)
    failed_operation: dict[str, Any] | None = None
    project_path: str | None = None
    cancel_requested: bool = False
    solver_run: bool = False
    error: str | None = None


class PlanService:
    def __init__(
        self,
        root: str | Path | None = None,
        bridge_factory=CSTBridge,
    ):
        configured = root or os.getenv("PROMPT2CST_STATE_DIR")
        self.root = (
            Path(configured)
            if configured
            else default_output_dir() / ".prompt2cst-state"
        )
        self.plan_root = self.root / "plans"
        self.execution_root = self.root / "executions"
        self.workflows = WorkflowStore(self.root / "workflows")
        self.bridge_factory = bridge_factory

    def validate_design_plan(self, design_ir: DesignIR) -> dict:
        return validate_design(design_ir).to_dict()

    def compile_design_plan(self, design_ir: DesignIR) -> dict:
        report = validate_design(design_ir)
        if report.blocking:
            return {"compiled": False, "validation": report.to_dict(), "operations": []}
        return {
            "compiled": True,
            "validation": report.to_dict(),
            **compile_design(design_ir).to_dict(),
        }

    def preview_design_plan(self, design_ir: DesignIR) -> dict:
        workflow = self.workflows.create()
        workflow = self.workflows.transition(workflow, WorkflowState.GEOMETRY_PLANNED)
        workflow = self.workflows.transition(workflow, WorkflowState.SIMULATION_PLANNED)
        report = validate_design(design_ir)
        compiled = None if report.blocking else compile_design(design_ir)
        if report.blocking:
            workflow = self.workflows.transition(
                workflow, WorkflowState.FAILED, "Blocking validation errors"
            )
        else:
            workflow = self.workflows.transition(workflow, WorkflowState.VALIDATED)
            workflow = self.workflows.transition(workflow, WorkflowState.PREVIEW_READY)
            workflow = self.workflows.transition(
                workflow, WorkflowState.AWAITING_APPROVAL
            )

        machine_preview = _machine_preview(design_ir, report, compiled)
        human_preview = _human_preview(design_ir, report, compiled)
        content = {
            "design_ir": design_ir.model_dump(mode="json"),
            "validation": report.to_dict(),
            "compiled": compiled.to_dict() if compiled else None,
        }
        content_hash = _hash(content)
        plan = StoredPlan(
            plan_id=uuid.uuid4().hex,
            workflow_id=workflow.id,
            created_at=datetime.now(UTC).isoformat(),
            content_hash=content_hash,
            design_ir=content["design_ir"],
            validation=content["validation"],
            compiled=content["compiled"],
            human_preview=human_preview,
            machine_preview=machine_preview,
        )
        self._write_new(
            self.plan_root / f"{plan.plan_id}.json", plan.model_dump_json(indent=2)
        )
        return {
            "plan_id": plan.plan_id,
            "workflow_id": workflow.id,
            "approval_hash": content_hash,
            "content_hash": content_hash,
            "approval_allowed": not report.blocking,
            "write_performed": False,
            "human_preview": human_preview,
            "machine_preview": machine_preview,
            "validation": report.to_dict(),
        }

    def get_design_plan(self, plan_id: str, approval_hash: str = "") -> dict:
        plan = self._load_plan(plan_id)
        return {
            "plan_id": plan.plan_id,
            "workflow_id": plan.workflow_id,
            "approval_hash_matches": not approval_hash
            or _constant_time_equal(approval_hash, plan.content_hash),
            "approval_hash": plan.content_hash,
            "write_performed": False,
            "human_preview": plan.human_preview,
            "machine_preview": plan.machine_preview,
            "validation": plan.validation,
        }

    def execute_approved_plan(
        self,
        plan_id: str,
        approval_hash: str,
        approved: bool,
        project_name: str | None = None,
        overwrite: bool = False,
    ) -> dict:
        if not approved:
            return {
                "status": "approval_required",
                "write_performed": False,
                "message": "Explicit human approval is required.",
            }
        plan = self._load_plan(plan_id)
        if not _constant_time_equal(approval_hash, plan.content_hash):
            raise PermissionError("Approval hash does not match the immutable plan")
        if plan.validation.get("blocking") or plan.compiled is None:
            raise PermissionError(
                "A plan with blocking validation errors cannot execute"
            )
        workflow = self.workflows.load(plan.workflow_id)
        if workflow.state != WorkflowState.AWAITING_APPROVAL:
            raise ValueError(f"Plan is not awaiting approval: {workflow.state}")
        workflow = self.workflows.transition(workflow, WorkflowState.APPROVED)

        execution_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat()
        record = ExecutionRecord(
            execution_id=execution_id,
            plan_id=plan_id,
            workflow_id=workflow.id,
            status="EXECUTING",
            created_at=now,
            updated_at=now,
            project_name=project_name
            or DesignIR.model_validate(plan.design_ir).project.name,
        )
        self._save_execution(record)
        workflow.execution_id = execution_id
        self.workflows.save(workflow)
        workflow = self.workflows.transition(workflow, WorkflowState.EXECUTING)
        compiled = _compiled_from_dict(plan.compiled)

        def completed(item: dict) -> None:
            current = self._load_execution(execution_id)
            current.completed_operations.append(item)
            current.updated_at = datetime.now(UTC).isoformat()
            self._save_execution(current)

        def cancelled() -> bool:
            return self._load_execution(execution_id).cancel_requested

        try:
            result = self.bridge_factory().execute_compiled_design(
                compiled=compiled,
                project_name=record.project_name,
                overwrite=overwrite,
                on_completed=completed,
                is_cancelled=cancelled,
            )
            record = self._load_execution(execution_id)
            record.status = "COMPLETED"
            record.project_path = result["project_path"]
            record.updated_at = datetime.now(UTC).isoformat()
            self._save_execution(record)
            self.workflows.transition(workflow, WorkflowState.COMPLETED)
            return {**result, "execution_id": execution_id, "plan_id": plan_id}
        except CSTExecutionCancelled as exc:
            record = self._load_execution(execution_id)
            record.status = "CANCELLED"
            record.error = str(exc)
            record.updated_at = datetime.now(UTC).isoformat()
            self._save_execution(record)
            self.workflows.transition(
                workflow, WorkflowState.FAILED, "Execution cancelled"
            )
            return record.model_dump(mode="json")
        except CSTExecutionError as exc:
            record = self._load_execution(execution_id)
            record.status = "FAILED"
            record.failed_operation = {
                "index": exc.operation_index,
                "operation_id": exc.operation_id,
                "label": exc.label,
                "cause_type": exc.cause_type,
            }
            record.error = str(exc)
            record.updated_at = datetime.now(UTC).isoformat()
            self._save_execution(record)
            self.workflows.transition(workflow, WorkflowState.FAILED, str(exc))
            return record.model_dump(mode="json")

    def get_execution_status(self, execution_id: str) -> dict:
        return self._load_execution(execution_id).model_dump(mode="json")

    def cancel_execution(self, execution_id: str) -> dict:
        record = self._load_execution(execution_id)
        if record.status != "EXECUTING":
            return {
                "execution_id": execution_id,
                "cancelled": False,
                "status": record.status,
            }
        record.cancel_requested = True
        record.updated_at = datetime.now(UTC).isoformat()
        self._save_execution(record)
        return {
            "execution_id": execution_id,
            "cancelled": True,
            "status": "CANCELLATION_REQUESTED",
        }

    def extract_simulation_results(self, execution_id: str) -> dict:
        record = self._load_execution(execution_id)
        plan = self._load_plan(record.plan_id)
        design = DesignIR.model_validate(plan.design_ir)
        result = SimulationResult(
            execution_id=execution_id,
            status="unavailable",
            missing_requested_outputs=design.requested_outputs,
            warnings=[
                "This execution created geometry but did not run the CST solver.",
                "No simulation values were invented or inferred.",
            ],
            raw_metadata={"project_path": record.project_path, "solver_run": False},
        )
        return result.model_dump(mode="json")

    def _load_plan(self, plan_id: str) -> StoredPlan:
        plan = StoredPlan.model_validate_json(
            self._safe_path(self.plan_root, plan_id).read_text(encoding="utf-8")
        )
        content = {
            "design_ir": plan.design_ir,
            "validation": plan.validation,
            "compiled": plan.compiled,
        }
        if not _constant_time_equal(_hash(content), plan.content_hash):
            raise PermissionError("Stored plan content hash verification failed")
        return plan

    def _load_execution(self, execution_id: str) -> ExecutionRecord:
        return ExecutionRecord.model_validate_json(
            self._safe_path(self.execution_root, execution_id).read_text(
                encoding="utf-8"
            )
        )

    def _save_execution(self, record: ExecutionRecord) -> None:
        self._atomic_write(
            self.execution_root / f"{record.execution_id}.json",
            record.model_dump_json(indent=2),
        )

    def _safe_path(self, root: Path, identifier: str) -> Path:
        if not identifier.isalnum():
            raise ValueError("invalid identifier")
        return root / f"{identifier}.json"

    def _write_new(self, target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            handle.write(content)

    def _atomic_write(self, target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, delete=False, suffix=".tmp"
        ) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        temporary.replace(target)


def _hash(content: dict[str, Any]) -> str:
    canonical = json.dumps(
        content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _constant_time_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _compiled_from_dict(value: dict[str, Any]) -> CompiledDesign:
    return CompiledDesign(
        schema_version=value["schema_version"],
        operations=tuple(
            CompiledOperation(
                index=item["index"],
                operation_id=item["operation_id"],
                category=item["category"],
                label=item["label"],
                history=item["history"],
            )
            for item in value["operations"]
        ),
    )


def _machine_preview(
    design: DesignIR, report: ValidationReport, compiled: CompiledDesign | None
) -> dict:
    return {
        "schema_version": design.schema_version,
        "requirements": design.project.model_dump(mode="json"),
        "parameters": {
            name: value.model_dump(mode="json")
            for name, value in design.parameters.items()
        },
        "materials": [item.model_dump(mode="json") for item in design.materials],
        "geometry": [item.model_dump(mode="json") for item in design.geometry],
        "operations": [item.model_dump(mode="json") for item in design.operations],
        "ports": [item.model_dump(mode="json") for item in design.excitations],
        "solver": design.solver.model_dump(mode="json") if design.solver else None,
        "boundaries": design.boundaries.model_dump(mode="json")
        if design.boundaries
        else None,
        "mesh": design.mesh.model_dump(mode="json") if design.mesh else None,
        "monitors": [item.model_dump(mode="json") for item in design.monitors],
        "sweeps": [item.model_dump(mode="json") for item in design.parameter_sweeps],
        "optimization_goals": [
            item.model_dump(mode="json") for item in design.optimization_goals
        ],
        "required_capabilities": sorted(required_capabilities(design)),
        "validation": report.to_dict(),
        "cst_operations": [item.to_dict() for item in compiled.operations]
        if compiled
        else [],
        "estimated_operation_count": len(compiled.operations) if compiled else 0,
        "estimated_mesh_count": report.estimated_mesh_cells,
        "simulation_case_count": report.sweep_case_count,
        "models_used": [],
        "model_fallbacks": [],
        "tool_call_count": 1,
    }


def _human_preview(
    design: DesignIR, report: ValidationReport, compiled: CompiledDesign | None
) -> str:
    findings = "\n".join(
        f"- [{item.severity}] {item.code}: {item.message}" for item in report.findings
    )
    operation_lines = (
        "\n".join(f"{item.index}. {item.label}" for item in compiled.operations)
        if compiled
        else "Compilation blocked."
    )
    return "\n".join(
        [
            f"# {design.project.name}",
            "## Requirements",
            f"Topology: {design.project.requested_topology or 'custom'}",
            f"Requested outputs: {', '.join(design.requested_outputs) or 'None'}",
            "",
            "## Calculations",
            f"Resolved parameters: {report.resolved_parameters or 'None supplied'}",
            "",
            "## Structure",
            f"Geometry objects: {len(design.geometry)}",
            f"Boolean/transform operations: {len(design.operations)}",
            f"Ports: {len(design.excitations)}",
            f"Materials: {len(design.materials)} plus built-in PEC",
            "",
            "## Simulation",
            f"Solver: {design.solver.type if design.solver else 'Not configured'}",
            f"Monitors: {len(design.monitors)}",
            f"Simulation cases: {report.sweep_case_count}",
            "",
            "## Validation",
            findings,
            "",
            "## CST operations",
            operation_lines,
            "",
            "## Model activity",
            "Model-role provenance is present only when supplied by the orchestrator.",
            "",
            "## Execution activity",
            "Read-only preview; no CST operation has executed.",
            "",
            "## Results",
            "No CST values exist before a separately approved simulation.",
        ]
    )
