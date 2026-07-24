from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .cst_bridge import default_output_dir


class WorkflowState(StrEnum):
    RECEIVED = "RECEIVED"
    REQUIREMENTS_PARSED = "REQUIREMENTS_PARSED"
    CALCULATIONS_COMPLETED = "CALCULATIONS_COMPLETED"
    GEOMETRY_PLANNED = "GEOMETRY_PLANNED"
    SIMULATION_PLANNED = "SIMULATION_PLANNED"
    VALIDATED = "VALIDATED"
    PREVIEW_READY = "PREVIEW_READY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


_ALLOWED = {
    WorkflowState.RECEIVED: {
        WorkflowState.REQUIREMENTS_PARSED,
        WorkflowState.GEOMETRY_PLANNED,
        WorkflowState.FAILED,
    },
    WorkflowState.REQUIREMENTS_PARSED: {
        WorkflowState.CALCULATIONS_COMPLETED,
        WorkflowState.FAILED,
    },
    WorkflowState.CALCULATIONS_COMPLETED: {
        WorkflowState.GEOMETRY_PLANNED,
        WorkflowState.FAILED,
    },
    WorkflowState.GEOMETRY_PLANNED: {
        WorkflowState.SIMULATION_PLANNED,
        WorkflowState.FAILED,
    },
    WorkflowState.SIMULATION_PLANNED: {WorkflowState.VALIDATED, WorkflowState.FAILED},
    WorkflowState.VALIDATED: {WorkflowState.PREVIEW_READY, WorkflowState.FAILED},
    WorkflowState.PREVIEW_READY: {
        WorkflowState.AWAITING_APPROVAL,
        WorkflowState.FAILED,
    },
    WorkflowState.AWAITING_APPROVAL: {WorkflowState.APPROVED, WorkflowState.FAILED},
    WorkflowState.APPROVED: {WorkflowState.EXECUTING, WorkflowState.FAILED},
    WorkflowState.EXECUTING: {WorkflowState.COMPLETED, WorkflowState.FAILED},
    WorkflowState.COMPLETED: set(),
    WorkflowState.FAILED: set(),
}


class WorkflowEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: WorkflowState
    at: str
    detail: str = Field(default="", max_length=1000)


class WorkflowRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    state: WorkflowState
    created_at: str
    updated_at: str
    plan_id: str | None = None
    execution_id: str | None = None
    events: list[WorkflowEvent] = Field(default_factory=list)


class WorkflowStore:
    def __init__(self, root: str | Path | None = None):
        self.root = (
            Path(root)
            if root
            else default_output_dir() / ".prompt2cst-state" / "workflows"
        )

    def create(self) -> WorkflowRecord:
        now = datetime.now(UTC).isoformat()
        record = WorkflowRecord(
            id=uuid.uuid4().hex,
            state=WorkflowState.RECEIVED,
            created_at=now,
            updated_at=now,
            events=[WorkflowEvent(state=WorkflowState.RECEIVED, at=now)],
        )
        self.save(record)
        return record

    def load(self, workflow_id: str) -> WorkflowRecord:
        return WorkflowRecord.model_validate_json(
            self._path(workflow_id).read_text(encoding="utf-8")
        )

    def transition(
        self, record: WorkflowRecord, state: WorkflowState, detail: str = ""
    ) -> WorkflowRecord:
        if state not in _ALLOWED[record.state]:
            raise ValueError(f"Invalid workflow transition: {record.state} -> {state}")
        now = datetime.now(UTC).isoformat()
        updated = record.model_copy(
            update={
                "state": state,
                "updated_at": now,
                "events": [
                    *record.events,
                    WorkflowEvent(state=state, at=now, detail=detail),
                ],
            }
        )
        self.save(updated)
        return updated

    def save(self, record: WorkflowRecord) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self._path(record.id)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.root, delete=False, suffix=".tmp"
        ) as handle:
            handle.write(record.model_dump_json(indent=2))
            temp = Path(handle.name)
        temp.replace(target)

    def _path(self, workflow_id: str) -> Path:
        if not workflow_id.isalnum():
            raise ValueError("invalid workflow ID")
        return self.root / f"{workflow_id}.json"
