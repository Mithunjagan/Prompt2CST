from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

from PySide6.QtCore import (
    QObject,
    Property,
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
from .ui_logic import (
    EXAMPLE_PROMPTS,
    FAMILY_OPTIONS,
    compose_user_request,
)


class AgentWorker(QObject):
    log = Signal(str)
    completed = Signal(str)
    failed = Signal(str)
    approval_requested = Signal(object)

    def __init__(self, api_key: str, model: str, prompt: str) -> None:
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.prompt = prompt

    @Slot()
    def run(self) -> None:
        try:
            self.log.emit("GUI worker started")
            agent = OpenRouterAgent(
                api_key=self.api_key,
                model=self.model,
                log=self.log.emit,
            )
            result = asyncio.run(
                agent.run(
                    user_prompt=self.prompt,
                    approve_write=self._request_approval,
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
    approvalRequested = Signal(str, str, str)
    showError = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._models = ["cohere/north-mini-code:free"]
        self._busy = False
        self._status = "Ready"
        self._assistant_text = ""
        self._activity_text = ""
        self._pending_approval: ApprovalRequest | None = None
        self._agent_thread: QThread | None = None
        self._agent_worker: AgentWorker | None = None
        self._model_thread: QThread | None = None
        self._model_worker: ModelWorker | None = None

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

    @Slot(str, result=str)
    def familyExample(self, family_id: str) -> str:
        return EXAMPLE_PROMPTS.get(family_id, EXAMPLE_PROMPTS["auto"])

    @Slot()
    def clearResults(self) -> None:
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
        self._set_status("Refreshing tool-capable models…")
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

    @Slot(str, str, str, str, str)
    def runAgent(
        self,
        api_key: str,
        model: str,
        family_id: str,
        prompt: str,
        mode: str,
    ) -> None:
        if self._busy:
            return
        if not api_key.strip():
            self.showError.emit("Enter your OpenRouter API key.")
            return
        if not model.strip():
            self.showError.emit(
                "Choose or type a tool-capable OpenRouter model ID."
            )
            return
        try:
            composed_prompt = compose_user_request(
                prompt,
                family_id or "auto",
                mode,
            )
        except ValueError as exc:
            self.showError.emit(str(exc))
            return

        self._set_assistant_text("")
        self._set_activity_text(
            f"Model: {model.strip()}\n"
            f"Family: {family_id or 'auto'}\n"
            f"Mode: {mode}\n"
        )
        self._set_busy(True)
        self._set_status(
            "Generating safe preview…"
            if mode == "preview"
            else "Preparing CST build…"
        )

        worker = AgentWorker(
            api_key.strip(),
            model.strip(),
            composed_prompt,
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
        self.modelsChanged.emit()
        self._set_busy(False)
        self._set_status(f"Loaded {len(models)} tool-capable models")

    @Slot(str)
    def _models_failed(self, error: str) -> None:
        self._set_busy(False)
        self._set_status("Model refresh failed")
        self.showError.emit(error)

    @Slot()
    def _clear_model_thread(self) -> None:
        self._model_worker = None
        self._model_thread = None

    @Slot(str)
    def _append_log(self, message: str) -> None:
        prefix = "\n" if self._activity_text else ""
        self._set_activity_text(
            f"{self._activity_text}{prefix}[agent] {message}"
        )

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

    @Slot(str)
    def _agent_completed(self, result: str) -> None:
        self._set_assistant_text(result)
        self._set_busy(False)
        self._set_status("Completed")

    @Slot(str)
    def _agent_failed(self, error: str) -> None:
        self._set_activity_text(
            f"{self._activity_text}\n\nERROR\n{error}"
        )
        self._set_assistant_text(
            "## Request failed\n\n"
            "Open **Activity** for the exact error and retry only after "
            "correcting it."
        )
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
