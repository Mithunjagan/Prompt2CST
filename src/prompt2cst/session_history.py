from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .cst_bridge import default_output_dir


class PromptRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: str
    updated_at: str
    prompt: str
    family_id: str
    mode: str
    phase: str
    role: str
    model: str
    status: str
    session_id: str = ""
    plan_id: str = ""
    approval_hash: str = ""
    assistant_text: str = ""
    activity_text: str = ""

    @property
    def title(self) -> str:
        first = " ".join(self.prompt.split())
        return first[:72] + ("..." if len(first) > 72 else "")

    def to_summary(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "family_id": self.family_id,
            "mode": self.mode,
            "phase": self.phase,
            "role": self.role,
            "model": self.model,
            "status": self.status,
            "session_id": self.session_id,
            "plan_id": self.plan_id,
        }


class PromptHistoryStore:
    def __init__(self, root: str | Path | None = None, max_records: int = 200) -> None:
        configured = root or os.getenv("PROMPT2CST_STATE_DIR")
        base = (
            Path(configured)
            if configured
            else default_output_dir() / ".prompt2cst-state"
        )
        self.path = base / "prompt_history.json"
        self.max_records = max(1, max_records)

    def list_records(self) -> list[PromptRunRecord]:
        if not self.path.exists():
            return []
        raw = self.path.read_text(encoding="utf-8")
        if not raw.strip():
            return []
        return [PromptRunRecord.model_validate(item) for item in json.loads(raw)]

    def summaries(self) -> list[dict[str, str]]:
        return [item.to_summary() for item in reversed(self.list_records())]

    def create(
        self,
        *,
        prompt: str,
        family_id: str,
        mode: str,
        phase: str,
        role: str,
        model: str,
        activity_text: str,
        session_id: str = "",
    ) -> PromptRunRecord:
        now = datetime.now(UTC).isoformat()
        record = PromptRunRecord(
            id=uuid.uuid4().hex,
            created_at=now,
            updated_at=now,
            prompt=prompt,
            family_id=family_id,
            mode=mode,
            phase=phase,
            role=role,
            model=model,
            status="RUNNING",
            session_id=session_id,
            activity_text=activity_text,
        )
        records = [*self.list_records(), record][-self.max_records :]
        self._save(records)
        return record

    def get(self, record_id: str) -> PromptRunRecord:
        for record in self.list_records():
            if record.id == record_id:
                return record
        raise KeyError(record_id)

    def update(
        self,
        record_id: str,
        *,
        status: str,
        assistant_text: str,
        activity_text: str,
        session_id: str | None = None,
        plan_id: str | None = None,
        approval_hash: str | None = None,
    ) -> PromptRunRecord:
        now = datetime.now(UTC).isoformat()
        updated_records = []
        updated_record = None
        for record in self.list_records():
            if record.id == record_id:
                updated_record = record.model_copy(
                    update={
                        "updated_at": now,
                        "status": status,
                        "assistant_text": assistant_text,
                        "activity_text": activity_text,
                        "session_id": (
                            record.session_id if session_id is None else session_id
                        ),
                        "plan_id": record.plan_id if plan_id is None else plan_id,
                        "approval_hash": (
                            record.approval_hash
                            if approval_hash is None
                            else approval_hash
                        ),
                    }
                )
                updated_records.append(updated_record)
            else:
                updated_records.append(record)
        if updated_record is None:
            raise KeyError(record_id)
        self._save(updated_records[-self.max_records :])
        return updated_record

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def _save(self, records: list[PromptRunRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [item.model_dump(mode="json") for item in records],
            indent=2,
        )
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False, suffix=".tmp"
        ) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        temporary.replace(self.path)
