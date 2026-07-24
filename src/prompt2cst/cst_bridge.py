from __future__ import annotations

import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .adapters import (
    dipole_to_design_ir,
    monopole_to_design_ir,
    parametric_to_design_ir,
    patch_to_design_ir,
)
from .cst_compiler import CompiledDesign, compile_design
from .cst_macros import (
    test_brick_history,
)
from .design import DipoleDesign, MonopoleDesign, PatchDesign
from .parametric import ParametricAntennaSpec

DEFAULT_PROGID = "CSTStudio.Application.2026"


def default_output_dir() -> Path:
    """Use the checkout output folder, with a per-user installed fallback."""

    source_root = Path(__file__).resolve().parents[2]
    if (source_root / "pyproject.toml").is_file():
        return source_root / "outputs"

    documents = Path.home() / "Documents"
    return documents / "Prompt2CST" / "outputs"


DEFAULT_OUTPUT_DIR = default_output_dir()


class CSTBridge:
    def __init__(
        self,
        progid: str | None = None,
        output_dir: str | Path | None = None,
    ) -> None:
        self.progid = progid or os.getenv("PROMPT2CST_CST_PROGID", DEFAULT_PROGID)
        configured_output = output_dir or os.getenv(
            "PROMPT2CST_OUTPUT_DIR", DEFAULT_OUTPUT_DIR
        )
        self.output_dir = Path(configured_output)

    def status(self, test_connection: bool = False) -> dict:
        if os.name != "nt":
            return {
                "platform": os.name,
                "registered": False,
                "connection_tested": False,
                "error": "CST COM automation requires Windows.",
                "progid": self.progid,
            }

        import winreg

        registered = True
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, self.progid):
                pass
        except FileNotFoundError:
            registered = False

        result = {
            "platform": "Windows",
            "registered": registered,
            "connection_tested": False,
            "connected": False,
            "progid": self.progid,
            "output_directory": str(self.output_dir),
        }

        if test_connection and registered:
            try:
                with self._application():
                    result["connection_tested"] = True
                    result["connected"] = True
            except Exception as exc:
                result["connection_tested"] = True
                result["error"] = f"{type(exc).__name__}: {exc}"

        return result

    def build_test_brick(
        self,
        project_name: str,
        overwrite: bool = False,
    ) -> dict:
        output_path = self._output_path(project_name, overwrite)
        with self._application() as app:
            project = app.NewMWS()
            project.AddToHistory(
                "Prompt2CST: Create PEC probe brick",
                test_brick_history(),
            )
            project.SaveAs(str(output_path), True)

        return {
            "status": "created",
            "write_performed": True,
            "project_path": str(output_path),
            "object": "component1:MCP_Probe_Brick",
        }

    def build_rectangular_patch(
        self,
        design: PatchDesign,
        project_name: str,
        overwrite: bool = False,
        include_boundary_setup: bool = True,
    ) -> dict:
        design_ir = patch_to_design_ir(design, project_name)
        if not include_boundary_setup:
            design_ir.boundaries = None
            design_ir.solver = None
        result = self.execute_compiled_design(
            compile_design(design_ir),
            project_name,
            overwrite,
        )
        return {
            **result,
            "status": "created",
            "design": design.to_dict(),
            "design_ir_schema_version": design_ir.schema_version,
            "boundary_setup_included": include_boundary_setup,
            "warnings": [
                *result["warnings"],
                "The inset depth is a first-pass analytical estimate.",
                "No excitation port is created by the legacy patch adapter.",
            ],
        }

    def build_wire_monopole(
        self,
        design: MonopoleDesign,
        project_name: str,
        overwrite: bool = False,
        include_port: bool = True,
        include_boundary_setup: bool = True,
        include_farfield_monitor: bool = True,
    ) -> dict:
        design_ir = monopole_to_design_ir(design, project_name)
        if not include_port:
            design_ir.excitations = []
        if not include_boundary_setup:
            design_ir.boundaries = None
            design_ir.solver = None
            design_ir.monitors = []
        elif not include_farfield_monitor:
            design_ir.monitors = []
        result = self.execute_compiled_design(
            compile_design(design_ir),
            project_name,
            overwrite,
        )
        return {
            **result,
            "status": "created",
            "design": design.to_dict(),
            "design_ir_schema_version": design_ir.schema_version,
            "port_created": include_port,
            "boundary_setup_included": include_boundary_setup,
            "farfield_monitor_created": include_farfield_monitor,
            "warnings": [
                *result["warnings"],
                "The compiled CST 2026 monopole requires target-installation inspection.",
            ],
        }

    def build_center_fed_dipole(
        self,
        design: DipoleDesign,
        project_name: str,
        overwrite: bool = False,
    ) -> dict:
        design_ir = dipole_to_design_ir(design, project_name)
        result = self.execute_compiled_design(
            compile_design(design_ir),
            project_name,
            overwrite,
        )
        result["status"] = "created"
        result["family"] = "center_fed_dipole"
        result["design"] = design.to_dict()
        result["design_ir_schema_version"] = design_ir.schema_version
        result["warnings"].insert(
            0,
            "The center-fed dipole family is beta and requires CST inspection.",
        )
        return result

    def build_parametric_antenna(
        self,
        spec: ParametricAntennaSpec,
        project_name: str,
        overwrite: bool = False,
    ) -> dict:
        design_ir = parametric_to_design_ir(spec)
        design_ir.project.name = project_name
        result = self.execute_compiled_design(
            compile_design(design_ir),
            project_name,
            overwrite,
        )
        return {
            **result,
            "status": "created",
            "family": "custom_parametric",
            "spec": spec.model_dump(mode="json"),
            "summary": spec.summary(),
            "design_ir_schema_version": design_ir.schema_version,
            "warnings": [
                *result["warnings"],
                "The compatibility adapter is limited to validated DesignIR capabilities.",
            ],
        }

    def execute_compiled_design(
        self,
        compiled: CompiledDesign,
        project_name: str,
        overwrite: bool = False,
        on_completed=None,
        is_cancelled=None,
    ) -> dict:
        """Execute validated compiler output in a new CST project.

        Each history operation is recorded independently so a caller can
        persist progress and report the exact failure. The project is saved
        only after every operation completes.
        """

        output_path = self._output_path(project_name, overwrite)
        completed: list[dict] = []
        current = None
        try:
            with self._application() as app:
                project = app.NewMWS()
                for operation in compiled.operations:
                    current = operation
                    if is_cancelled and is_cancelled():
                        raise CSTExecutionCancelled(
                            f"Execution cancelled before operation {operation.index}"
                        )
                    project.AddToHistory(operation.label, operation.history)
                    item = {
                        "index": operation.index,
                        "operation_id": operation.operation_id,
                        "label": operation.label,
                    }
                    completed.append(item)
                    if on_completed:
                        on_completed(item)
                project.SaveAs(str(output_path), True)
        except CSTExecutionCancelled:
            raise
        except Exception as exc:
            raise CSTExecutionError(
                operation_index=current.index if current else 0,
                operation_id=current.operation_id
                if current
                else "project_initialization",
                label=current.label if current else "Create new CST project",
                completed_operations=completed,
                cause=exc,
            ) from exc

        return {
            "status": "completed",
            "write_performed": True,
            "project_path": str(output_path),
            "completed_operations": completed,
            "solver_run": False,
            "warnings": [
                "The approved plan was compiled and written; the solver was not started.",
                "Inspect the CST 2026 History List and geometry before simulation.",
            ],
        }

    def _output_path(self, project_name: str, overwrite: bool) -> Path:
        safe_name = sanitize_project_name(project_name)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = (self.output_dir / f"{safe_name}.cst").resolve()
        output_root = self.output_dir.resolve()

        if output_root not in output_path.parents:
            raise ValueError("Resolved project path escaped the output directory")
        if output_path.exists() and not overwrite:
            raise FileExistsError(
                f"{output_path} already exists; set overwrite=true to replace it"
            )
        return output_path

    @contextmanager
    def _application(self) -> Iterator[object]:
        if os.name != "nt":
            raise RuntimeError("CST COM automation requires Windows")

        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            app = win32com.client.Dispatch(self.progid)
            yield app
        finally:
            pythoncom.CoUninitialize()


def sanitize_project_name(project_name: str) -> str:
    candidate = project_name.strip()
    if candidate.lower().endswith(".cst"):
        candidate = candidate[:-4]
    candidate = re.sub(r"[^A-Za-z0-9_-]+", "_", candidate)
    candidate = candidate.strip("_")
    if not candidate:
        raise ValueError("project_name must contain a letter or number")
    return candidate[:80]


class CSTExecutionCancelled(RuntimeError):
    pass


class CSTExecutionError(RuntimeError):
    def __init__(
        self,
        operation_index: int,
        operation_id: str,
        label: str,
        completed_operations: list[dict],
        cause: Exception,
    ) -> None:
        self.operation_index = operation_index
        self.operation_id = operation_id
        self.label = label
        self.completed_operations = completed_operations
        self.cause_type = type(cause).__name__
        super().__init__(
            f"CST operation {operation_index} ({operation_id}, {label}) failed: "
            f"{self.cause_type}: {cause}"
        )
