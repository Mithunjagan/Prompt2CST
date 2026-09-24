from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    Property,
    QObject,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from . import __version__
from .agent import OpenRouterAgent, format_exception_details
from .autonomous import DesignRun, run_design
from .capabilities import capability_browser
from .cst_bridge import default_output_dir
from .orchestration import (
    ModelRole,
    OpenAICompatibleProvider,
    ProviderRouter,
    RoleConfig,
    role_configs_from_environment,
)
from .plan_service import PlanService
from .session_history import PromptHistoryStore
from .swarm import SwarmCoordinator, SwarmRunResult, SwarmSessionStore
from .ui_logic import (
    EXAMPLE_PROMPTS,
    FAMILY_OPTIONS,
    PHASE_OPTIONS,
    compose_swarm_request,
    role_for_phase,
)


class AgentWorker(QObject):
    log = Signal(str)
    completed = Signal(object)
    failed = Signal(str)
    approval_requested = Signal(object)

    def __init__(
        self,
        api_key: str,
        prompt: str,
        phase: str,
        session_id: str,
        role_configs: dict[ModelRole, RoleConfig],
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.prompt = prompt
        self.phase = phase
        self.session_id = session_id
        self.role_configs = role_configs

    @Slot()
    def run(self) -> None:
        try:
            self.log.emit("GUI worker started")
            router = None
            if self.api_key:
                provider = OpenAICompatibleProvider(
                    api_key=self.api_key,
                    base_url="https://openrouter.ai/api/v1",
                    name="openrouter",
                    log=lambda event: self.log.emit(
                        "[provider] " + json.dumps(event, default=str)
                    ),
                )
                configs = {
                    role: RoleConfig(
                        role=role,
                        provider="openrouter",
                        model=config.model,
                        fallback_models=config.fallback_models,
                        timeout_seconds=config.timeout_seconds,
                        enabled=config.enabled,
                    )
                    for role, config in self.role_configs.items()
                }
                router = ProviderRouter({"openrouter": provider}, configs)
            coordinator = SwarmCoordinator(router, log=self.log.emit)
            result = asyncio.run(
                coordinator.run(
                    prompt=self.prompt,
                    target_phase=self.phase,
                    session_id=self.session_id,
                    approve_build=self._request_approval,
                )
            )
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(format_exception_details(exc))

    def _request_approval(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        preview: dict[str, Any],
    ) -> bool:
        request = ApprovalRequest(tool_name, arguments, preview)
        self.approval_requested.emit(request)
        request.wait()
        return request.approved


class ModelWorker(QObject):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, api_key: str) -> None:
        super().__init__()
        self.api_key = api_key

    @Slot()
    def run(self) -> None:
        try:
            agent = OpenRouterAgent(self.api_key, model="model-list")
            models = asyncio.run(agent.list_models())
            self.completed.emit(models)
        except Exception as exc:
            self.failed.emit(format_exception_details(exc))


class LocalDesignWorker(QObject):
    """Run the deterministic, zero-key design workflow off the GUI thread."""

    log = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        prompt: str,
        project_dir: str | Path,
        dataset_path: str = "",
        mode: str = "dry-run",
        use_local_ai: bool = False,
    ) -> None:
        super().__init__()
        self.prompt = prompt
        self.project_dir = Path(project_dir)
        self.dataset_path = dataset_path
        self.mode = mode
        self.use_local_ai = use_local_ai

    @Slot()
    def run(self) -> None:
        try:
            datasets = [self.dataset_path] if self.dataset_path else []
            self.log.emit("Extracting RF requirements locally")
            if datasets:
                self.log.emit(f"Validating dataset: {Path(datasets[0]).name}")
            result = run_design(
                self.prompt,
                self.project_dir,
                mode=self.mode,
                datasets=datasets,
                progress=self.log.emit,
                use_local_ai=self.use_local_ai,
            )
            self.completed.emit(_local_design_summary(result))
        except Exception as exc:
            self.failed.emit(format_exception_details(exc))


def _local_design_summary(result: DesignRun) -> dict[str, str]:
    requirements = json.loads(Path(result.artifacts["requirements"]).read_text(encoding="utf-8"))
    selected = json.loads(Path(result.artifacts["selected_architecture"]).read_text(encoding="utf-8"))
    design_ir = json.loads(Path(result.artifacts["design_ir"]).read_text(encoding="utf-8"))
    evidence = json.loads(Path(result.artifacts["evidence"]).read_text(encoding="utf-8"))
    lines = [
        "# Autonomous local design plan",
        "",
        f"- **Selected topology:** `{selected['topology']}`",
        f"- **Target band:** {requirements['frequency_min_ghz']:.4f}–{requirements['frequency_max_ghz']:.4f} GHz",
        f"- **Target S11:** {requirements['target_s11_db']:.1f} dB",
        f"- **Execution readiness:** `{design_ir['execution_readiness']}`",
        f"- **Project:** `{result.project_dir}`",
    ]
    local_ai = requirements.get("local_ai")
    if isinstance(local_ai, dict):
        lines.append(
            f"- **Local AI family check:** `{local_ai.get('status', 'invalid')}` "
            "(advisory only; deterministic requirements retained)"
        )
    datasets = evidence.get("datasets", [])
    if datasets:
        assessment = datasets[0].get("target_assessment") or {}
        lines.extend([
            "",
            "## Faculty dataset assessment",
            "",
            f"- Status: `{assessment.get('status', 'NOT_EVALUATED')}`",
            f"- Designs: {datasets[0].get('design_count', 0)}",
            f"- Samples: {datasets[0].get('sample_count', 0)}",
            f"- Best S11 near target: {assessment.get('best_s11_at_target_db', 'n/a')} dB",
            f"- Safe as optimizer seed: {'Yes' if assessment.get('use_as_optimizer_seed') else 'No'}",
            f"- Manufacturing use: `{datasets[0].get('manufacturing_use', 'UNKNOWN')}`",
        ])
    lines.extend([
        "",
        "## Validation boundary",
        "",
        (
            "A deterministic openEMS geometry and solver project was generated. "
            "No EM solver was run, and no simulated or measured performance was invented."
            if result.mode == "openems" else (
                "openEMS FDTD completed and produced port S11 and impedance. "
                "Gain, efficiency, pattern, tolerances, and fabrication remain unverified."
                if result.mode == "openems-simulate"
                else "This run created a deterministic engineering plan only. No EM solver was run, and no simulated or measured performance was invented."
            )
        ),
    ])
    if result.mode == "openems-simulate":
        measured = json.loads(Path(result.artifacts["simulation_result"]).read_text(encoding="utf-8"))
        lines.extend([
            "", "## Simulated by openEMS FDTD", "",
            f"- S11 at target: {measured['s11_db']:.2f} dB",
            f"- Input impedance: {measured['z_real_ohm']:.2f} + j{measured['z_imag_ohm']:.2f} Ω",
            f"- S11 threshold at this mesh: {'Yes' if measured['target_met'] else 'No'}",
            f"- Mesh convergence: {measured['mesh_convergence']}",
            f"- Full sweep: `{measured['raw_results']}`",
        ])
    activity = "\n".join([
        "Architecture: autonomous local engine",
        "Cost: zero remote API calls",
        f"Status: {result.status}",
        f"Selected topology: {result.selected_topology}",
        f"Project directory: {result.project_dir}",
        "Artifacts:",
        *[f"  {name}: {path}" for name, path in result.artifacts.items()],
    ])
    return {
        "assistant_text": "\n".join(lines),
        "activity_text": activity,
        "project_dir": str(result.project_dir),
    }


class ApprovalRequest:
    def __init__(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        preview: dict[str, Any],
    ) -> None:
        import threading

        self.tool_name = tool_name
        self.arguments = arguments
        self.preview = preview
        self.approved = False
        self._event = threading.Event()

    def resolve(self, approved: bool) -> None:
        self.approved = approved
        self._event.set()

    def wait(self) -> None:
        self._event.wait()


class Prompt2CSTController(QObject):
    modelsChanged = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    assistantTextChanged = Signal()
    activityTextChanged = Signal()
    promptHistoryChanged = Signal()
    canBuildChanged = Signal()
    modelSettingsChanged = Signal()
    approvalRequested = Signal(str, str, str)
    promptRestored = Signal(str, str, str)
    showError = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._models = ["cohere/north-mini-code:free"]
        self._busy = False
        self._status = "Ready"
        self._assistant_text = ""
        self._activity_text = ""
        self._history = PromptHistoryStore()
        self._swarm_sessions = SwarmSessionStore()
        self._active_history_id = ""
        self._running_history_id = ""
        self._active_swarm_session_id = self._swarm_sessions.latest_id()
        self._active_preview_prompt = ""
        self._active_preview_plan_id = ""
        self._reviewing_preview = False
        self._running_prompt = ""
        self._running_phase = ""
        self._pending_approval: ApprovalRequest | None = None
        self._agent_thread: QThread | None = None
        self._agent_worker: AgentWorker | None = None
        self._model_thread: QThread | None = None
        self._model_worker: ModelWorker | None = None
        self._local_thread: QThread | None = None
        self._local_worker: LocalDesignWorker | None = None
        self._role_configs = role_configs_from_environment(self._models[0])
        self._explicit_role_models: set[ModelRole] = {
            role
            for role, suffix in {
                ModelRole.REQUIREMENTS: "REQUIREMENTS",
                ModelRole.CALCULATIONS: "CALCULATIONS",
                ModelRole.PARAMETERS: "PARAMETERS",
                ModelRole.GEOMETRY: "GEOMETRY",
                ModelRole.SIMULATION: "SIMULATION",
                ModelRole.CRITIC: "CRITIC",
                ModelRole.CODE_REVIEW: "CODE_REVIEW",
                ModelRole.RESULTS_ANALYSIS: "RESULTS",
            }.items()
            if os.getenv(f"MODEL_{suffix}")
            or (
                role in {ModelRole.CALCULATIONS, ModelRole.PARAMETERS}
                and os.getenv("MODEL_RF_REASONING")
            )
        }
        self._provider_health = "Not checked"

    @Property(str, constant=True)
    def version(self) -> str:
        return __version__

    @Property("QVariantList", constant=True)
    def familyOptions(self) -> list[dict[str, str]]:
        return [
            {
                "display": display,
                "id": family_id,
                "description": description,
            }
            for display, family_id, description in FAMILY_OPTIONS
        ]

    @Property("QVariantList", constant=True)
    def phaseOptions(self) -> list[dict[str, str]]:
        return [
            {
                "display": display,
                "id": phase_id,
                "description": description,
                "role": role_for_phase(phase_id),
            }
            for display, phase_id, description in PHASE_OPTIONS
        ]

    @Property("QVariantList", constant=True)
    def roleOptions(self) -> list[dict[str, str]]:
        return [
            {
                "display": role.value.replace("_", " ").title(),
                "id": role.value,
            }
            for role in ModelRole
        ]

    @Property("QStringList", notify=modelsChanged)
    def models(self) -> list[str]:
        return self._models

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(str, notify=assistantTextChanged)
    def assistantText(self) -> str:
        return self._assistant_text

    @Property(str, notify=activityTextChanged)
    def activityText(self) -> str:
        return self._activity_text

    @Property("QVariantList", notify=promptHistoryChanged)
    def promptHistory(self) -> list[dict[str, str]]:
        return self._history.summaries()

    @Property(bool, notify=canBuildChanged)
    def canBuild(self) -> bool:
        if not self._active_swarm_session_id or not self._reviewing_preview:
            return False
        try:
            session = self._swarm_sessions.load(self._active_swarm_session_id)
        except (FileNotFoundError, ValueError):
            return False
        return bool(
            session.preview
            and session.preview.get("approval_allowed")
            and session.preview.get("plan_id") == self._active_preview_plan_id
            and session.execution is None
        )

    @Property(str, notify=canBuildChanged)
    def activePreviewPrompt(self) -> str:
        return self._active_preview_prompt

    @Property(str, notify=modelSettingsChanged)
    def modelOrchestrationText(self) -> str:
        lines = ["ROLE | PROVIDER | MODEL | FALLBACKS | TIMEOUT | ENABLED | HEALTH"]
        for role in ModelRole:
            config = self._role_configs[role]
            fallbacks = ", ".join(config.fallback_models) or "None"
            lines.append(
                f"{role.value} | {config.provider} | "
                f"{config.model or 'Unconfigured'} | {fallbacks} | "
                f"{config.timeout_seconds:g}s | "
                f"{'Yes' if config.enabled else 'No'} | "
                f"{self._provider_health}"
            )
        return "\n".join(lines)

    @Property(str, constant=True)
    def capabilityText(self) -> str:
        lines = [
            "CAPABILITY | STATUS | CLOSEST ALTERNATIVE | EXTENSIBLE",
        ]
        for item in capability_browser():
            lines.append(
                f"{item['id']} | "
                f"{'SUPPORTED' if item['supported'] else 'UNSUPPORTED'} | "
                f"{item['closest_alternative'] or 'None'} | "
                f"{'Yes' if item['extensible'] else 'No'}"
            )
            if item["limitations"]:
                lines.append(f"  Limitation: {item['limitations'][0]}")
        return "\n".join(lines)

    @Slot(str, result=str)
    def familyExample(self, family_id: str) -> str:
        return EXAMPLE_PROMPTS.get(family_id, EXAMPLE_PROMPTS["auto"])

    @Slot(str, str)
    def runLocalAutonomous(self, prompt: str, dataset_url: str) -> None:
        self._run_local(prompt, dataset_url, "dry-run")

    @Slot(str, str)
    def runLocalAutonomousAI(self, prompt: str, dataset_url: str) -> None:
        self._run_local(prompt, dataset_url, "dry-run", use_local_ai=True)

    @Slot(str, str)
    def runLocalOpenEMS(self, prompt: str, dataset_url: str) -> None:
        self._run_local(prompt, dataset_url, "openems")

    @Slot(str, str)
    def runLocalOpenEMSSimulate(self, prompt: str, dataset_url: str) -> None:
        self._run_local(prompt, dataset_url, "openems-simulate")

    def _run_local(
        self, prompt: str, dataset_url: str, mode: str, *, use_local_ai: bool = False
    ) -> None:
        if self._busy:
            return
        request = prompt.strip()
        if not request:
            self.showError.emit("Describe the antenna you want to design.")
            return
        dataset_path = ""
        if dataset_url.strip():
            url = QUrl(dataset_url.strip())
            dataset_path = url.toLocalFile() if url.isLocalFile() else dataset_url.strip()
            if not Path(dataset_path).is_file():
                self.showError.emit("The selected dataset ZIP was not found.")
                return
        slug = re.sub(r"[^a-z0-9]+", "-", request.lower()).strip("-")[:36] or "antenna"
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        project_dir = default_output_dir() / "autonomous-projects" / f"{timestamp}-{slug}"
        self._active_preview_prompt = ""
        self._active_preview_plan_id = ""
        self._reviewing_preview = False
        self.canBuildChanged.emit()
        self._set_assistant_text("")
        activity = "\n".join([
            "Architecture: autonomous local engine",
            "Remote model/API: disabled",
            f"Local Ollama advisory: {'enabled' if use_local_ai else 'disabled'}",
            f"Dataset: {dataset_path or 'none'}",
            f"Project: {project_dir}",
        ])
        self._set_activity_text(activity)
        record = self._history.create(
            prompt=request,
            family_id="auto",
            mode=mode,
            phase=("openems_simulation" if mode == "openems-simulate" else "openems_generation" if mode == "openems" else "planning"),
            role="deterministic_local_engine",
            model="zero-key local engine",
            activity_text=activity,
        )
        self._running_history_id = record.id
        self._running_prompt = request
        self._running_phase = "openems_simulation" if mode == "openems-simulate" else "openems_generation" if mode == "openems" else "planning"
        self.promptHistoryChanged.emit()
        self._set_busy(True)
        self._set_status(
            "Running local openEMS simulation…"
            if mode == "openems-simulate"
            else "Generating autonomous openEMS project…"
            if mode == "openems"
            else "Running autonomous local design…"
        )

        worker = LocalDesignWorker(
            request, project_dir, dataset_path, mode=mode, use_local_ai=use_local_ai
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log.connect(self._append_log)
        worker.completed.connect(self._local_completed)
        worker.failed.connect(self._local_failed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_local_thread)
        self._local_worker = worker
        self._local_thread = thread
        thread.start()

    @Slot()
    def clearResults(self) -> None:
        if self._busy:
            self.showError.emit(
                "Wait for the active swarm run to finish before clearing."
            )
            return
        plan_service = PlanService()
        for session in self._swarm_sessions.list_sessions():
            if session.preview and not session.execution:
                try:
                    plan_service.invalidate_plan(
                        str(session.preview["plan_id"]),
                        "Conversation history cleared by user",
                    )
                except (FileNotFoundError, KeyError, PermissionError, ValueError):
                    continue
        self._history.clear()
        self._swarm_sessions.clear()
        self._active_history_id = ""
        self._running_history_id = ""
        self._active_swarm_session_id = ""
        self._active_preview_prompt = ""
        self._active_preview_plan_id = ""
        self._reviewing_preview = False
        self._running_prompt = ""
        self._running_phase = ""
        self.promptHistoryChanged.emit()
        self.canBuildChanged.emit()
        self._set_assistant_text("")
        self._set_activity_text("")
        self._set_status("Ready")

    @Slot(str)
    def copyText(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self._set_status("Copied to clipboard")

    @Slot(str)
    def loadModels(self, api_key: str) -> None:
        if self._busy:
            return
        if not api_key.strip():
            self.showError.emit("Enter your OpenRouter API key first.")
            return
        if self._model_thread is not None:
            self.showError.emit("Model discovery is already running.")
            return

        self._set_busy(True)
        self._set_status("Refreshing structured/tool models…")
        worker = ModelWorker(api_key.strip())
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._models_loaded)
        worker.failed.connect(self._models_failed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_model_thread)
        self._model_worker = worker
        self._model_thread = thread
        thread.start()

    @Slot(str)
    def useModelForAllRoles(self, model: str) -> None:
        selected = model.strip()
        if not selected:
            self.showError.emit("Choose or type a model ID first.")
            return
        self._role_configs = {
            role: config.__class__(
                role=role,
                provider=config.provider,
                model=selected,
                fallback_models=config.fallback_models,
                timeout_seconds=config.timeout_seconds,
                enabled=config.enabled,
            )
            for role, config in self._role_configs.items()
        }
        self._explicit_role_models = set(ModelRole)
        self.modelSettingsChanged.emit()
        self._set_status("Assigned selected model to all roles")

    @Slot(str, str)
    def setRoleModel(self, role_value: str, model: str) -> None:
        selected = model.strip()
        if not selected:
            self.showError.emit("Choose or type a model ID first.")
            return
        try:
            role = ModelRole(role_value)
        except ValueError:
            self.showError.emit("Unknown model role.")
            return
        config = self._role_configs[role]
        self._role_configs[role] = config.__class__(
            role=role,
            provider=config.provider,
            model=selected,
            fallback_models=config.fallback_models,
            timeout_seconds=config.timeout_seconds,
            enabled=config.enabled,
        )
        self._explicit_role_models.add(role)
        self.modelSettingsChanged.emit()
        self._set_status(f"Assigned {selected} to {role.value}")

    @Slot(str)
    def loadHistoryEntry(self, record_id: str) -> None:
        if self._busy:
            self.showError.emit(
                "Wait for the active swarm run before changing history."
            )
            return
        try:
            record = self._history.get(record_id)
        except KeyError:
            self.showError.emit("History item was not found.")
            return
        self._active_history_id = record.id
        self._active_swarm_session_id = record.session_id
        self._active_preview_prompt = record.prompt
        self._active_preview_plan_id = record.plan_id
        self._reviewing_preview = bool(
            record.plan_id and record.phase in {"preview", "build"}
        )
        self.canBuildChanged.emit()
        self._set_assistant_text(record.assistant_text)
        self._set_activity_text(record.activity_text)
        self._set_status(f"Loaded {record.phase} history")
        self.promptRestored.emit(record.prompt, record.family_id, record.phase)

    @Slot(str, str, str, str, str, str)
    def runAgent(
        self,
        api_key: str,
        model: str,
        family_id: str,
        prompt: str,
        mode: str,
        phase: str,
    ) -> None:
        if self._busy:
            return
        active_phase = "build" if mode == "build" else phase or "preview"
        if active_phase != "build" and not api_key.strip():
            self.showError.emit("Enter your OpenRouter API key.")
            return
        if active_phase != "build" and not model.strip():
            self.showError.emit("Choose or type a structured-output model ID.")
            return
        if active_phase == "build":
            composed_prompt = prompt.strip()
            if not self._active_swarm_session_id:
                self.showError.emit("Create and review a preview before building.")
                return
            if prompt.strip() != self._active_preview_prompt:
                self.showError.emit(
                    "The prompt changed after preview. Preview this revision before "
                    "building."
                )
                return
        else:
            try:
                composed_prompt = compose_swarm_request(
                    prompt,
                    family_id or "auto",
                )
            except ValueError as exc:
                self.showError.emit(str(exc))
                return
            if not self._active_swarm_session_id:
                self._active_swarm_session_id = self._swarm_sessions.create().id
            self._reviewing_preview = False
            self._active_preview_prompt = ""
            self._active_preview_plan_id = ""
            self.canBuildChanged.emit()

        selected_model = model.strip()
        role_configs = {
            role: (
                config
                if role in self._explicit_role_models
                else RoleConfig(
                    role=role,
                    provider=config.provider,
                    model=selected_model,
                    fallback_models=config.fallback_models,
                    timeout_seconds=config.timeout_seconds,
                    enabled=config.enabled,
                )
            )
            for role, config in self._role_configs.items()
        }
        configured_models = [
            config.model for config in role_configs.values() if config.model
        ]
        history_model = (
            "deterministic executor"
            if active_phase == "build"
            else f"swarm · {len(set(configured_models))} configured model(s)"
        )

        self._set_assistant_text("")
        activity_text = (
            f"Architecture: specialist swarm\n"
            f"Phase: {active_phase}\n"
            f"Family: {family_id or 'auto'}\n"
            f"Mode: {mode}\n"
        )
        self._set_activity_text(activity_text)
        record = self._history.create(
            prompt=prompt.strip(),
            family_id=family_id or "auto",
            mode=mode,
            phase=active_phase,
            role=role_for_phase(active_phase),
            model=history_model,
            activity_text=activity_text,
            session_id=self._active_swarm_session_id,
        )
        self._running_history_id = record.id
        self._running_prompt = prompt.strip()
        self._running_phase = active_phase
        self.promptHistoryChanged.emit()
        self._set_busy(True)
        self._set_status(
            "Generating safe preview…" if mode == "preview" else "Preparing CST build…"
        )

        worker = AgentWorker(
            api_key.strip(),
            composed_prompt,
            active_phase,
            self._active_swarm_session_id,
            role_configs,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log.connect(self._append_log)
        worker.approval_requested.connect(self._handle_approval)
        worker.completed.connect(self._agent_completed)
        worker.failed.connect(self._agent_failed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_agent_thread)
        self._agent_worker = worker
        self._agent_thread = thread
        thread.start()

    @Slot(bool)
    def resolveApproval(self, approved: bool) -> None:
        request = self._pending_approval
        if request is None:
            return
        self._pending_approval = None
        request.resolve(approved)
        self._set_status(
            "CST build approved…"
            if approved
            else "CST build denied · finalizing response…"
        )

    @Slot()
    def cancelPendingApproval(self) -> None:
        self.resolveApproval(False)

    @Slot(list)
    def _models_loaded(self, models: list[str]) -> None:
        self._models = models
        self._provider_health = "Healthy"
        self.modelsChanged.emit()
        self.modelSettingsChanged.emit()
        self._set_busy(False)
        self._set_status(f"Loaded {len(models)} structured/tool models")

    @Slot(str)
    def _models_failed(self, error: str) -> None:
        self._provider_health = "Unhealthy"
        self.modelSettingsChanged.emit()
        self._set_busy(False)
        self._set_status("Model refresh failed")
        self.showError.emit(error)

    @Slot()
    def _clear_model_thread(self) -> None:
        self._model_worker = None
        self._model_thread = None

    @Slot(object)
    def _local_completed(self, summary: dict[str, str]) -> None:
        self._set_assistant_text(summary["assistant_text"])
        self._set_activity_text(summary["activity_text"])
        self._save_local_history("COMPLETED")
        self._set_busy(False)
        self._set_status("Local autonomous plan completed")

    @Slot(str)
    def _local_failed(self, error: str) -> None:
        self._set_activity_text(f"{self._activity_text}\n\nERROR\n{error}")
        self._set_assistant_text(
            "## Local autonomous run failed\n\nOpen **Activity** for the exact error."
        )
        self._save_local_history("FAILED")
        self._set_busy(False)
        self._set_status("Local autonomous run failed")
        self.showError.emit(error)

    @Slot()
    def _clear_local_thread(self) -> None:
        self._local_worker = None
        self._local_thread = None

    @Slot(str)
    def _append_log(self, message: str) -> None:
        prefix = "\n" if self._activity_text else ""
        self._set_activity_text(f"{self._activity_text}{prefix}[agent] {message}")

    @Slot(object)
    def _handle_approval(self, request: ApprovalRequest) -> None:
        if self._pending_approval is not None:
            request.resolve(False)
            return
        self._pending_approval = request
        self._set_status("Review required before CST write")
        self.approvalRequested.emit(
            request.tool_name,
            json.dumps(request.arguments, indent=2, default=str),
            json.dumps(request.preview, indent=2, default=str),
        )

    @Slot(object)
    def _agent_completed(self, result: SwarmRunResult) -> None:
        self._active_swarm_session_id = result.session_id
        if result.phase.value == "preview":
            self._active_preview_prompt = self._running_prompt
            self._reviewing_preview = True
            try:
                session = self._swarm_sessions.load(result.session_id)
                self._active_preview_plan_id = str(session.preview["plan_id"])
            except (FileNotFoundError, KeyError, TypeError):
                self._active_preview_plan_id = ""
                self._reviewing_preview = False
        elif result.phase.value != "build":
            self._active_preview_prompt = ""
            self._active_preview_plan_id = ""
            self._reviewing_preview = False
        self.canBuildChanged.emit()
        self._set_assistant_text(result.assistant_text)
        self._set_activity_text(result.activity_text)
        self._save_active_history("COMPLETED")
        self._set_busy(False)
        self._set_status("Completed")

    @Slot(str)
    def _agent_failed(self, error: str) -> None:
        if self._running_phase != "build":
            self._active_preview_prompt = ""
            self._active_preview_plan_id = ""
            self._reviewing_preview = False
            self.canBuildChanged.emit()
        self._set_activity_text(f"{self._activity_text}\n\nERROR\n{error}")
        self._set_assistant_text(
            "## Request failed\n\n"
            "Open **Activity** for the exact error and retry only after "
            "correcting it."
        )
        self._save_active_history("FAILED")
        self._set_busy(False)
        self._set_status("Failed")
        self.showError.emit(error)

    @Slot()
    def _clear_agent_thread(self) -> None:
        self._agent_worker = None
        self._agent_thread = None

    def _set_busy(self, value: bool) -> None:
        if value == self._busy:
            return
        self._busy = value
        self.busyChanged.emit()

    def _set_status(self, value: str) -> None:
        if value == self._status:
            return
        self._status = value
        self.statusChanged.emit()

    def _set_assistant_text(self, value: str) -> None:
        if value == self._assistant_text:
            return
        self._assistant_text = value
        self.assistantTextChanged.emit()

    def _set_activity_text(self, value: str) -> None:
        if value == self._activity_text:
            return
        self._activity_text = value
        self.activityTextChanged.emit()

    def _save_active_history(self, status: str) -> None:
        if not self._running_history_id:
            return
        try:
            plan_id = ""
            approval_hash = ""
            if self._active_swarm_session_id:
                session = self._swarm_sessions.load(self._active_swarm_session_id)
                if session.preview:
                    plan_id = str(session.preview.get("plan_id", ""))
                    approval_hash = str(session.preview.get("approval_hash", ""))
            self._history.update(
                self._running_history_id,
                status=status,
                assistant_text=self._assistant_text,
                activity_text=self._activity_text,
                session_id=self._active_swarm_session_id,
                plan_id=plan_id,
                approval_hash=approval_hash,
            )
        except (FileNotFoundError, KeyError, ValueError):
            self._running_history_id = ""
            return
        self._active_history_id = self._running_history_id
        self._running_history_id = ""
        self._running_prompt = ""
        self._running_phase = ""
        self.promptHistoryChanged.emit()

    def _save_local_history(self, status: str) -> None:
        if not self._running_history_id:
            return
        try:
            self._history.update(
                self._running_history_id,
                status=status,
                assistant_text=self._assistant_text,
                activity_text=self._activity_text,
                session_id="",
                plan_id="",
                approval_hash="",
            )
        except (FileNotFoundError, KeyError, ValueError):
            pass
        self._active_history_id = self._running_history_id
        self._running_history_id = ""
        self._running_prompt = ""
        self._running_phase = ""
        self.promptHistoryChanged.emit()


def _enable_windows_backdrop(window: QObject) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            20,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        corner = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            33,
            ctypes.byref(corner),
            ctypes.sizeof(corner),
        )
        backdrop = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            38,
            ctypes.byref(backdrop),
            ctypes.sizeof(backdrop),
        )
    except Exception:
        # The QML translucency remains usable if Windows rejects Mica.
        return


def main() -> None:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    QQuickStyle.setStyle("Basic")

    app = QGuiApplication(sys.argv)
    app.setApplicationName("Prompt2CST")
    app.setOrganizationName("Prompt2CST")
    icon_path = Path(__file__).resolve().parent / "assets" / "prompt2cst.svg"
    app.setWindowIcon(QIcon(str(icon_path)))

    controller = Prompt2CSTController()
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        raise SystemExit(f"Unable to load Prompt2CST UI: {qml_path}")

    window = engine.rootObjects()[0]
    QTimer.singleShot(100, lambda: _enable_windows_backdrop(window))
    app.aboutToQuit.connect(controller.cancelPendingApproval)
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
