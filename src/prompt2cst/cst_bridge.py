from __future__ import annotations

import os
import re
import json
import math
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .adapters import (
    dipole_to_design_ir,
    monopole_to_design_ir,
    parametric_to_design_ir,
    patch_to_design_ir,
    TemplePifaInputs,
    temple_pifa_to_design_ir,
)
from .cst_compiler import CompiledDesign, compile_design
from .cst_macros import (
    test_brick_history,
)
from .design import (
    DipoleDesign,
    DipoleInputs,
    MonopoleDesign,
    PatchDesign,
    calculate_center_fed_dipole,
)
from .parametric import ParametricAntennaSpec

DEFAULT_PROGID = "CSTStudio.Application.2026"


def default_output_dir() -> Path:
    """Use the checkout output folder, with a per-user installed fallback."""

    configured = os.getenv("PROMPT2CST_OUTPUT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

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

    def build_temple_pifa(
        self,
        inputs: TemplePifaInputs,
        project_name: str,
        overwrite: bool = False,
    ) -> dict:
        """Build a parameterized free-space temple PIFA without starting CST."""
        design_ir = temple_pifa_to_design_ir(inputs, project_name)
        result = self.execute_compiled_design(compile_design(design_ir), project_name, overwrite)
        return {
            **result,
            "status": "created",
            "family": "temple_pifa",
            "design_ir": design_ir.model_dump(mode="json"),
            "warnings": [*result["warnings"], *design_ir.warnings],
        }

    def run_controlled_dipole_link_test(
        self,
        project_name: str,
        length_a_mm: float,
        length_b_mm: float,
        frequency_ghz: float = 2.45,
        overwrite: bool = False,
    ) -> dict:
        """Run the real CST parameter-to-geometry-to-response dipole test.

        The compiled model refers to ``dipole_length_mm`` in both cylindrical
        arm ranges and its discrete-port endpoints.  Each candidate therefore
        uses the verified ``StoreParameter -> Rebuild -> Solver`` path.  A
        failed solve or extraction remains failed; no nominal RF values are
        generated as a fallback.
        """
        if length_a_mm <= 0 or length_b_mm <= 0:
            raise ValueError("Controlled dipole lengths must be positive.")
        if length_a_mm == length_b_mm:
            raise ValueError("Controlled dipole lengths must differ.")

        inputs = DipoleInputs(
            frequency_ghz=frequency_ghz,
            total_conductor_length_mm=length_a_mm,
            sweep_start_ghz=max(0.01, frequency_ghz * 0.55),
            sweep_stop_ghz=frequency_ghz * 1.45,
        )
        project = self.build_center_fed_dipole(
            calculate_center_fed_dipole(inputs), project_name, overwrite=overwrite
        )
        project_path = project["project_path"]
        candidates: list[dict[str, object]] = []

        for label, length in (("p1", length_a_mm), ("p2", length_b_mm)):
            update = self.update_parameters(
                project_path, {"dipole_length_mm": float(length)}
            )
            solver = self.run_solver(project_path)
            extraction = self.extract_results(project_path, artifact_tag=label)
            candidate: dict[str, object] = {
                "id": label,
                "parameters": {"dipole_length_mm": float(length)},
                "parameter_update": update,
                "solver": solver,
                "extraction": _extraction_summary(extraction),
            }
            if extraction.get("status") == "completed":
                resonance = extraction.get("extracted", {}).get("f_res_ghz")
                if resonance is not None:
                    candidate["resonance_ghz"] = resonance[0]
            candidates.append(candidate)

        resonances = [item.get("resonance_ghz") for item in candidates]
        response_changed = (
            all(isinstance(value, (int, float)) for value in resonances)
            and not math.isclose(float(resonances[0]), float(resonances[1]), abs_tol=1e-6)
        )
        evidence = {
            "schema_version": "1.0",
            "kind": "controlled_dipole_parameter_response_link",
            "provenance": "CST_SIMULATION" if response_changed else "CST_SIMULATION_INCOMPLETE",
            "project_path": project_path,
            "geometry_parameter": "dipole_length_mm",
            "geometry_references": {
                "lower_arm_zrange": [
                    "-feed_gap_mm / 2 - dipole_length_mm / 2",
                    "-feed_gap_mm / 2",
                ],
                "upper_arm_zrange": [
                    "feed_gap_mm / 2",
                    "feed_gap_mm / 2 + dipole_length_mm / 2",
                ],
            },
            "candidates": candidates,
            "response_changed": response_changed,
            "claim": (
                "Two real CST runs produced different extracted resonances."
                if response_changed
                else "The real response-link criterion was not demonstrated."
            ),
        }
        evidence_path = Path(project_path).with_name(
            f"{Path(project_path).stem}_parameter_response_link.json"
        )
        evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        evidence["evidence_path"] = str(evidence_path)
        return evidence

    def run_temple_pifa_impedance_link_test(
        self,
        project_name: str,
        feed_offset_a_mm: float,
        feed_offset_b_mm: float,
        *,
        inputs: TemplePifaInputs | None = None,
        overwrite: bool = False,
        meaningful_change_ohm: float = 1.0,
    ) -> dict:
        """Prove a PIFA feed-offset changes real CST input impedance.

        ``feed_offset_mm`` is deliberately used because it is present in both
        the matching-stub x-range and the discrete-port endpoints.  The method
        accepts only extracted CST values; unavailable output makes the
        experiment incomplete instead of creating a nominal impedance.
        """
        if feed_offset_a_mm == feed_offset_b_mm:
            raise ValueError("Controlled feed offsets must differ.")
        if meaningful_change_ohm <= 0:
            raise ValueError("meaningful_change_ohm must be positive.")

        base = inputs or TemplePifaInputs()
        initial = TemplePifaInputs(**{**base.__dict__, "feed_offset_mm": float(feed_offset_a_mm)})
        initial.validate()
        TemplePifaInputs(**{**base.__dict__, "feed_offset_mm": float(feed_offset_b_mm)}).validate()
        project = self.build_temple_pifa(initial, project_name, overwrite=overwrite)
        project_path = project["project_path"]
        candidates: list[dict[str, object]] = []

        for label, offset in (("p1", feed_offset_a_mm), ("p2", feed_offset_b_mm)):
            update = self.update_parameters(project_path, {"feed_offset_mm": float(offset)})
            solver = self.run_solver(project_path)
            extraction = self.extract_results(project_path, artifact_tag=label)
            candidate: dict[str, object] = {
                "id": label,
                "parameters": {"feed_offset_mm": float(offset)},
                "parameter_update": update,
                "solver": solver,
                "extraction": _extraction_summary(extraction),
            }
            extracted = extraction.get("extracted", {})
            zin_re = extracted.get("zin_re")
            zin_im = extracted.get("zin_im")
            if (
                extraction.get("status") == "completed"
                and isinstance(zin_re, tuple)
                and isinstance(zin_im, tuple)
                and isinstance(zin_re[0], (int, float))
                and isinstance(zin_im[0], (int, float))
            ):
                candidate["zin_ohm"] = {"re": zin_re[0], "im": zin_im[0]}
            candidates.append(candidate)

        zins = [candidate.get("zin_ohm") for candidate in candidates]
        impedance_change = None
        if all(isinstance(value, dict) for value in zins):
            first, second = zins
            impedance_change = math.hypot(
                float(second["re"]) - float(first["re"]),
                float(second["im"]) - float(first["im"]),
            )
        response_changed = impedance_change is not None and impedance_change >= meaningful_change_ohm
        evidence = {
            "schema_version": "1.0",
            "kind": "temple_pifa_feed_offset_impedance_link",
            "provenance": "CST_SIMULATION" if response_changed else "CST_SIMULATION_INCOMPLETE",
            "project_path": project_path,
            "geometry_parameter": "feed_offset_mm",
            "geometry_references": {
                "matching_stub_xrange": [
                    "feed_offset_mm - feed_width_mm / 2",
                    "feed_offset_mm + feed_width_mm / 2",
                ],
                "port_p1_x": "feed_offset_mm",
                "port_p2_x": "feed_offset_mm",
            },
            "meaningful_change_threshold_ohm": meaningful_change_ohm,
            "impedance_change_ohm": impedance_change,
            "candidates": candidates,
            "response_changed": response_changed,
            "claim": (
                "Two real CST feed-offset candidates produced a meaningful complex input-impedance change."
                if response_changed
                else "The real feed-offset impedance-link criterion was not demonstrated."
            ),
        }
        evidence_path = Path(project_path).with_name(f"{Path(project_path).stem}_impedance_link.json")
        temporary_path = evidence_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        temporary_path.replace(evidence_path)
        evidence["evidence_path"] = str(evidence_path)
        return evidence

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

    def run_solver(self, project_path: str | Path) -> dict:
        """Open a CST project and trigger the transient solver."""
        path = Path(project_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Project not found: {path}")

        if os.name != "nt":
            return {
                "status": "mock",
                "message": "CST COM solver execution requires Windows with CST installed.",
                "project_path": str(path),
            }

        with self._application() as app:
            # CST Studio Suite 2026 exposes OpenFile and Active3D() on its
            # IApplication COM interface.  OpenDocument is not a CST method.
            app.OpenFile(str(path))
            project = app.Active3D()
            solver = project.Solver()
            solver.Start()
            project.Save()

        return {
            "status": "completed",
            "project_path": str(path),
            "solver_run": True,
        }

    def update_parameters(
        self,
        project_path: str | Path,
        parameters: dict[str, float],
    ) -> dict:
        """Modify CST parameters using StoreParameter, rebuild, and save."""
        path = Path(project_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Project not found: {path}")

        if os.name != "nt":
            return {
                "status": "mock",
                "updated": False,
                "message": "Real parameter update requires Windows with CST COM interface.",
            }

        with self._application() as app:
            app.OpenFile(str(path))
            project = app.Active3D()
            for name, value in parameters.items():
                project.StoreParameter(str(name), float(value))
            project.Rebuild()
            project.Save()

        return {
            "status": "completed",
            "updated": True,
            "parameters": parameters,
            "project_path": str(path),
        }

    def read_parameter(self, project_path: str | Path, name: str) -> float:
        """Reopen a CST project and read one stored design parameter.

        ``RestoreDoubleParameter`` is the CST 2026 COM readback API.  The
        superficially plausible ``GetParameter`` is not exposed on Active3D.
        """
        path = Path(project_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Project not found: {path}")
        if os.name != "nt":
            raise RuntimeError("Real parameter readback requires Windows with CST COM interface.")
        self._trace_com("Dispatch", "started", project_path=str(path), parameter=name)
        with self._application() as app:
            app.OpenFile(str(path))
            self._trace_com("OpenFile", "completed", project_path=str(path), parameter=name)
            project = app.Active3D()
            self._trace_com("Active3D", "completed", project_path=str(path), parameter=name)
            self._trace_com("RestoreDoubleParameter", "started", project_path=str(path), parameter=name)
            if hasattr(project, "RestoreDoubleParameter"):
                value = float(project.RestoreDoubleParameter(str(name)))
            elif hasattr(project, "GetParameter"):
                value = float(project.GetParameter(str(name)))
            else:
                value = float(getattr(project, "RestoreDoubleParameter", getattr(project, "GetParameter"))(str(name)))
            self._trace_com("RestoreDoubleParameter", "completed", project_path=str(path), parameter=name, value=value)
            return value

    @staticmethod
    def _trace_com(call: str, phase: str, **detail: object) -> None:
        """Append a minimal, crash-surviving COM operation trace when enabled."""
        trace_path = os.getenv("PROMPT2CST_COM_TRACE_PATH")
        if not trace_path:
            return
        event = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "com_call": call, "phase": phase, **detail}
        with Path(trace_path).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def extract_results(
        self,
        project_path: str | Path,
        artifact_tag: str = "",
    ) -> dict:
        """Export and normalize the solved one-port S11 result.

        The two CST 2026 History/VBA operations below were verified against the
        installed COM server: ``ASCIIExport`` exports the curve selected in the
        CST result tree and ``Touchstone.Write`` exports its complex S11.  CST's
        direct ``Z-Parameters`` tree is *not* assumed to exist: input impedance
        is derived only when the complex Touchstone sample is available.
        """
        path = Path(project_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Project not found: {path}")

        extracted: dict[str, tuple[object, str]] = {}
        raw_extracted: dict[str, object] = {}
        unavailable: list[str] = []

        if os.name != "nt":
            return {
                "status": "mock",
                "extracted": extracted,
                "raw_extracted": raw_extracted,
                "unavailable": ["s11_db", "f_res_ghz", "vswr", "zin_re", "zin_im"],
                "warning": "Real extraction requires Windows + CST COM interface.",
            }

        try:
            out_dir = path.parent
            safe_tag = re.sub(r"[^A-Za-z0-9_-]+", "_", artifact_tag).strip("_")
            result_stem = f"{path.stem}_{safe_tag}" if safe_tag else path.stem
            s11_txt = out_dir / f"{result_stem}_s11_extracted.txt"
            s11_s1p = out_dir / f"{result_stem}_s11_extracted.s1p"
            s11_touchstone_base = s11_s1p.with_suffix("")
            raw_json = out_dir / f"{result_stem}_raw_results.json"

            export_vba = f"""
Sub Main()
    SelectTreeItem("1D Results\\S-Parameters\\S1,1")
    With ASCIIExport
        .Reset
        .FileName "{s11_txt.resolve()}"
        .Execute
    End With
    SelectTreeItem("1D Results\\S-Parameters\\S1,1")
    With Touchstone
        .Reset
        .FileName "{s11_touchstone_base.resolve()}"
        .Format "MA"
        .Impedance "50"
        .Write
    End With
End Sub
"""
            mcs_file = out_dir / f"{result_stem}_export.mcs"
            mcs_file.write_text(export_vba, encoding="utf-8")

            self._trace_com("ExtractResults.Dispatch", "started", project_path=str(path), artifact_tag=safe_tag)
            with self._application() as app:
                self._trace_com("ExtractResults.Dispatch", "completed", project_path=str(path), artifact_tag=safe_tag)
                app.OpenFile(str(path))
                self._trace_com("ExtractResults.OpenFile", "completed", project_path=str(path), artifact_tag=safe_tag)
                project = app.Active3D()
                self._trace_com("ExtractResults.Active3D", "completed", project_path=str(path), artifact_tag=safe_tag)
                self._trace_com("ExtractResults.RunScript", "started", project_path=str(path), artifact_tag=safe_tag)
                project.RunScript(str(mcs_file.resolve()))
                self._trace_com("ExtractResults.RunScript", "completed", project_path=str(path), artifact_tag=safe_tag)
            s11_points = parse_cst_ascii_curve(s11_txt) if s11_txt.exists() else []
            touchstone = parse_touchstone_s1p(s11_s1p) if s11_s1p.exists() else []
            raw_extracted = {
                "source": "CST 2026 1D Results/S-Parameters/S1,1",
                "ascii_s11_db": s11_points,
                "touchstone_s11": touchstone,
                "ascii_path": str(s11_txt),
                "touchstone_path": str(s11_s1p),
            }
            # Persist unmodified exported samples before deriving any metric.
            raw_json.write_text(json.dumps(raw_extracted, indent=2), encoding="utf-8")

            if not s11_points:
                unavailable.extend(["s11_db", "f_res_ghz", "frequency_samples"])
            else:
                resonance = min(s11_points, key=lambda point: point["value"])
                f_res = resonance["frequency_ghz"]
                s11_min = resonance["value"]
                extracted["s11_db"] = (s11_min, "dB")
                extracted["f_res_ghz"] = (f_res, "GHz")
                extracted["frequency_samples"] = (
                    [point["frequency_ghz"] for point in s11_points], "GHz"
                )

                # Touchstone is complex S11 from that same selected CST curve.
                # It is required for calculated VSWR and Zin; no defaults are used.
                if touchstone:
                    sample = min(touchstone, key=lambda point: abs(point["frequency_ghz"] - f_res))
                    gamma = complex(sample["gamma_re"], sample["gamma_im"])
                    gamma_abs = abs(gamma)
                    if gamma_abs >= 1.0:
                        unavailable.extend(["vswr", "zin_re", "zin_im"])
                    else:
                        z0 = sample["reference_impedance_ohm"]
                        zin = z0 * (1 + gamma) / (1 - gamma)
                        extracted["vswr"] = ((1 + gamma_abs) / (1 - gamma_abs), "1")
                        extracted["zin_re"] = (zin.real, "Ohm")
                        extracted["zin_im"] = (zin.imag, "Ohm")
                else:
                    unavailable.extend(["vswr", "zin_re", "zin_im"])

            raw_extracted["raw_results_path"] = str(raw_json)

        except Exception as exc:
            self._trace_com("ExtractResults", "error", project_path=str(path), artifact_tag=artifact_tag,
                            error=f"{type(exc).__name__}: {exc}")
            return {
                "status": "error",
                "error": str(exc),
                "extracted": extracted,
                "raw_extracted": raw_extracted,
                "unavailable": unavailable,
            }

        return {
            "status": "completed",
            "extracted": extracted,
            "raw_extracted": raw_extracted,
            "unavailable": unavailable,
        }

    def create_validated_cst_snapshot(
        self,
        source_project_path: str | Path,
        snapshot_name: str,
        *,
        expected_parameters: dict[str, float] | None = None,
        require_results: bool = False,
        overwrite: bool = False,
    ) -> dict:
        """Create an independently reopened, CST-native project snapshot.

        This deliberately never copies a live ``.cst`` archive at the file
        level.  CST owns both saving and SaveAs, and the result is reopened
        before it can be reported as valid.  A failed validation is retained
        for forensic inspection and returned as ``SNAPSHOT_INVALID``.

        ``overwrite`` is retained for source compatibility but intentionally
        has no effect: every snapshot has a new unique directory.
        """
        source_path = Path(source_project_path).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Source project not found: {source_path}")

        safe_name = sanitize_project_name(snapshot_name)
        # CST has a much shorter practical project-path limit than Windows.
        # Keep snapshots outside the often deeply nested workspace by default;
        # callers can select another short local root through the environment.
        snapshot_root = Path(os.getenv("PROMPT2CST_SNAPSHOT_DIR", r"C:\p2cst"))
        snapshot_dir = (snapshot_root / f"{safe_name[:12]}_{uuid.uuid4().hex[:12]}").resolve()
        snapshot_path = snapshot_dir / f"{safe_name}.cst"
        if source_path == snapshot_path:
            raise ValueError("Snapshot source and destination must differ")

        if os.name != "nt":
            raise RuntimeError("CST COM snapshot requires Windows with CST installed.")

        snapshot_dir.mkdir(parents=True, exist_ok=False)
        validation: dict[str, object] = {
            "source_project": str(source_path),
            "snapshot_path": str(snapshot_path),
            "expected_parameters": expected_parameters or {},
            "require_results": require_results,
            "overwrite_ignored": overwrite,
        }
        try:
            # Saving is performed by CST, never by a file-system copy.  CST's
            # solver Start call is synchronous in the supported bridge; probe
            # explicit busy APIs too when a build exposes them.
            with self._application() as app:
                app.OpenFile(str(source_path))
                project = app.Active3D()
                validation["solver_idle"] = self._solver_idle_status(project)
                project.Save()
                project.SaveAs(str(snapshot_path), True)

            if not snapshot_path.exists():
                raise RuntimeError("CST SaveAs returned without creating the snapshot archive")

            # Reopen in a separate COM application context.  This catches the
            # corrupt-archive failure rather than trusting SaveAs return.
            readback: dict[str, float] = {}
            with self._application() as validation_app:
                validation_app.OpenFile(str(snapshot_path))
                validation_project = validation_app.Active3D()
                for name, expected in (expected_parameters or {}).items():
                    actual = float(validation_project.RestoreDoubleParameter(str(name)))
                    readback[str(name)] = actual
                    if not math.isclose(actual, float(expected), rel_tol=0.0, abs_tol=1e-9):
                        raise RuntimeError(
                            f"Snapshot parameter readback mismatch for {name}: "
                            f"expected {expected}, got {actual}"
                        )
            validation["parameter_readback"] = readback

            if require_results:
                result_check = self.extract_results(snapshot_path, artifact_tag="snapshot_validation")
                values = result_check.get("extracted", {})
                required = {"s11_db", "f_res_ghz", "zin_re", "zin_im"}
                missing = sorted(required - set(values))
                if result_check.get("status") != "completed" or missing:
                    raise RuntimeError(
                        "Snapshot S11 readback failed" + (f"; missing {', '.join(missing)}" if missing else "")
                    )
                validation["result_readback"] = {
                    "status": result_check["status"],
                    "metrics": {name: values[name][0] for name in sorted(required)},
                    "raw_artifacts": {
                        key: result_check.get("raw_extracted", {})[key]
                        for key in ("ascii_path", "touchstone_path", "raw_results_path")
                        if key in result_check.get("raw_extracted", {})
                    },
                }
        except Exception as exc:
            validation["error"] = f"{type(exc).__name__}: {exc}"
            return {
                "status": "SNAPSHOT_INVALID",
                "snapshot_path": str(snapshot_path),
                "source_project": str(source_path),
                "validation": validation,
            }

        return {
            "status": "VALID",
            "snapshot_path": str(snapshot_path),
            "source_project": str(source_path),
            "validation": validation,
        }

    @staticmethod
    def _solver_idle_status(project: object) -> dict[str, object]:
        """Fail if the installed CST COM object exposes an active solver.

        CST 2026's synchronous ``Solver.Start`` API normally returns only once
        it is idle.  Some installations additionally expose a status method;
        inspect those without assuming an undocumented method exists.
        """
        probes: list[tuple[str, object]] = [("project", project)]
        try:
            probes.append(("solver", project.Solver()))  # type: ignore[attr-defined]
        except Exception:
            pass
        for owner, target in probes:
            for name in ("IsBusy", "IsRunning", "GetSolverStatus"):
                try:
                    value = getattr(target, name)()
                except (AttributeError, TypeError):
                    continue
                if isinstance(value, str):
                    busy = value.strip().lower() in {"busy", "running", "solving"}
                else:
                    busy = bool(value)
                if busy:
                    raise RuntimeError(f"CST solver is busy ({owner}.{name}={value!r})")
                return {"checked": True, "method": f"{owner}.{name}", "value": value}
        return {"checked": False, "method": "synchronous Solver.Start contract"}

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


def parse_cst_ascii_curve(path: str | Path) -> list[dict[str, float]]:
    """Read a CST ASCIIExport two-column 1D curve without inventing values."""

    source = Path(path)
    header = ""
    points: list[dict[str, float]] = []
    for line in source.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if "Frequency /" in stripped:
            header = stripped
            continue
        fields = stripped.split()
        if len(fields) != 2:
            continue
        try:
            frequency = float(fields[0])
            value = float(fields[1])
        except ValueError:
            continue
        points.append({"frequency_ghz": _frequency_to_ghz(frequency, header), "value": value})
    return points


def _extraction_summary(response: dict) -> dict:
    """Keep the controlled-test ledger compact while preserving raw artifacts.

    Full sampled ASCII and Touchstone data stay in their per-candidate files;
    embedding them again in the experiment ledger makes it needlessly large
    and obscures which raw export belongs to which parameter point.
    """
    raw = response.get("raw_extracted", {})
    extracted = dict(response.get("extracted", {}))
    frequency_samples = extracted.pop("frequency_samples", None)
    return {
        "status": response.get("status"),
        "error": response.get("error"),
        "extracted": extracted,
        "frequency_sample_count": (
            len(frequency_samples[0])
            if isinstance(frequency_samples, tuple)
            and frequency_samples
            and isinstance(frequency_samples[0], list)
            else 0
        ),
        "unavailable": response.get("unavailable", []),
        "raw_artifacts": {
            key: raw[key]
            for key in ("ascii_path", "touchstone_path", "raw_results_path")
            if key in raw
        },
    }


def parse_touchstone_s1p(path: str | Path) -> list[dict[str, float]]:
    """Read a one-port Touchstone file exported by CST in MA, DB, or RI form."""

    frequency_unit = "ghz"
    data_format = "ma"
    reference_impedance = 50.0
    points: list[dict[str, float]] = []
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("!"):
            continue
        if stripped.startswith("#"):
            tokens = stripped[1:].lower().split()
            if tokens:
                frequency_unit = tokens[0]
            if len(tokens) >= 3:
                data_format = tokens[2]
            if "r" in tokens:
                index = tokens.index("r")
                if index + 1 < len(tokens):
                    reference_impedance = float(tokens[index + 1])
            continue
        fields = stripped.split()
        if len(fields) != 3:
            continue
        try:
            frequency, first, second = (float(item) for item in fields)
        except ValueError:
            continue
        if data_format == "ma":
            gamma = first * complex(math.cos(math.radians(second)), math.sin(math.radians(second)))
        elif data_format == "db":
            magnitude = 10 ** (first / 20.0)
            gamma = magnitude * complex(math.cos(math.radians(second)), math.sin(math.radians(second)))
        elif data_format == "ri":
            gamma = complex(first, second)
        else:
            raise ValueError(f"Unsupported Touchstone data format: {data_format}")
        points.append(
            {
                "frequency_ghz": _frequency_to_ghz(frequency, frequency_unit),
                "gamma_re": gamma.real,
                "gamma_im": gamma.imag,
                "reference_impedance_ohm": reference_impedance,
            }
        )
    return points


def _frequency_to_ghz(value: float, unit_text: str) -> float:
    normalized = unit_text.lower()
    if "thz" in normalized:
        return value * 1_000.0
    if "ghz" in normalized:
        return value
    if "mhz" in normalized:
        return value / 1_000.0
    if "khz" in normalized:
        return value / 1_000_000.0
    if "hz" in normalized:
        return value / 1_000_000_000.0
    raise ValueError(f"Unsupported frequency unit in CST export: {unit_text}")


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
