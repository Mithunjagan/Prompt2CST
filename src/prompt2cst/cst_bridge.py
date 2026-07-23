from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
from typing import Iterator

from .cst_macros import (
    complete_parametric_preview,
    dipole_parametric_spec,
    farfield_monitor_history,
    frequency_and_boundary_history,
    fr4_material_history,
    patch_geometry_history,
    test_brick_history,
    units_history,
    wire_monopole_geometry_history,
    wire_monopole_port_history,
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
        self.progid = progid or os.getenv(
            "PROMPT2CST_CST_PROGID", DEFAULT_PROGID
        )
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
        output_path = self._output_path(project_name, overwrite)

        with self._application() as app:
            project = app.NewMWS()
            project.AddToHistory("Prompt2CST: Set units", units_history())
            project.AddToHistory(
                "Prompt2CST: Define FR4",
                fr4_material_history(design),
            )
            project.AddToHistory(
                "Prompt2CST: Build patch geometry",
                patch_geometry_history(design),
            )
            if include_boundary_setup:
                project.AddToHistory(
                    "Prompt2CST: Frequency and boundaries",
                    frequency_and_boundary_history(design),
                )
            project.SaveAs(str(output_path), True)

        return {
            "status": "created",
            "write_performed": True,
            "project_path": str(output_path),
            "design": design.to_dict(),
            "boundary_setup_included": include_boundary_setup,
            "solver_run": False,
            "warnings": [
                "The inset depth is a first-pass analytical estimate.",
                "No excitation port has been created in v0.1.",
                "The solver has not been run.",
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
        output_path = self._output_path(project_name, overwrite)

        with self._application() as app:
            project = app.NewMWS()
            project.AddToHistory("Prompt2CST: Set units", units_history())
            project.AddToHistory(
                "Prompt2CST: Build wire monopole geometry",
                wire_monopole_geometry_history(design),
            )
            if include_port:
                project.AddToHistory(
                    "Prompt2CST: Create 50 ohm discrete port",
                    wire_monopole_port_history(design),
                )
            if include_boundary_setup:
                project.AddToHistory(
                    "Prompt2CST: Frequency and open boundaries",
                    frequency_and_boundary_history(design),
                )
            if include_farfield_monitor:
                project.AddToHistory(
                    "Prompt2CST: Farfield monitor",
                    farfield_monitor_history(design),
                )
            project.SaveAs(str(output_path), True)

        return {
            "status": "created",
            "write_performed": True,
            "project_path": str(output_path),
            "design": design.to_dict(),
            "port_created": include_port,
            "boundary_setup_included": include_boundary_setup,
            "farfield_monitor_created": include_farfield_monitor,
            "solver_run": False,
            "warnings": [
                "The CST 2026 monopole macro requires validation on the target installation.",
                "No solver was run and no S-parameter or far-field results were extracted.",
                "Mesh-cell count has not been verified against the Learning Edition limit.",
            ],
        }

    def build_center_fed_dipole(
        self,
        design: DipoleDesign,
        project_name: str,
        overwrite: bool = False,
    ) -> dict:
        result = self.build_parametric_antenna(
            spec=dipole_parametric_spec(design),
            project_name=project_name,
            overwrite=overwrite,
        )
        result["family"] = "center_fed_dipole"
        result["design"] = design.to_dict()
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
        output_path = self._output_path(project_name, overwrite)
        history = complete_parametric_preview(spec)

        with self._application() as app:
            project = app.NewMWS()
            labels = {
                "units": "Prompt2CST: Set units",
                "materials": "Prompt2CST: Define custom materials",
                "geometry": "Prompt2CST: Build parametric geometry",
                "discrete_ports": "Prompt2CST: Create discrete ports",
                "frequency_and_boundaries": (
                    "Prompt2CST: Frequency and open boundaries"
                ),
                "farfield_monitor": "Prompt2CST: Farfield monitor",
            }
            for key, commands in history.items():
                project.AddToHistory(labels[key], commands)
            project.SaveAs(str(output_path), True)

        return {
            "status": "created",
            "write_performed": True,
            "project_path": str(output_path),
            "family": "custom_parametric",
            "spec": spec.model_dump(mode="json"),
            "summary": spec.summary(),
            "solver_run": False,
            "warnings": [
                "The parametric builder is limited to validated primitives.",
                "No solver was run and no results were extracted.",
                "Mesh-cell count has not been verified against the Learning Edition limit.",
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
