"""Deterministic openEMS project generation for advanced antenna families.

The generated Python is an inspectable solver input, not an EM result.  This
module deliberately does not import openEMS while planning, allowing the
desktop application to create and review projects before a solver is installed.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections import deque
from hashlib import sha256
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

C0 = 299_792_458.0


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Material(_StrictModel):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    kind: Literal["metal", "dielectric"]
    epsilon_r: float = Field(default=1.0, ge=1.0)
    loss_tangent: float = Field(default=0.0, ge=0.0)


class Primitive(_StrictModel):
    name: str
    material: str
    kind: Literal["box", "cylinder", "curve"]
    start: tuple[float, float, float] | None = None
    stop: tuple[float, float, float] | None = None
    radius_mm: float | None = Field(default=None, gt=0)
    points: list[tuple[float, float, float]] | None = None
    priority: int = Field(default=10, ge=0)

    @model_validator(mode="after")
    def validate_shape(self) -> "Primitive":
        if self.kind == "box" and (self.start is None or self.stop is None):
            raise ValueError("box requires start and stop")
        if self.kind == "cylinder" and (
            self.start is None or self.stop is None or self.radius_mm is None
        ):
            raise ValueError("cylinder requires start, stop and radius_mm")
        if self.kind == "curve" and (self.points is None or len(self.points) < 2):
            raise ValueError("curve requires at least two points")
        return self


class Port(_StrictModel):
    kind: Literal["lumped", "rect_waveguide"]
    number: int = Field(default=1, ge=1)
    resistance_ohm: float = Field(default=50.0, gt=0)
    start: tuple[float, float, float]
    stop: tuple[float, float, float]
    direction: Literal["x", "y", "z"]
    waveguide_a_mm: float | None = Field(default=None, gt=0)
    waveguide_b_mm: float | None = Field(default=None, gt=0)
    mode_name: str | None = None

    @model_validator(mode="after")
    def validate_waveguide(self) -> "Port":
        if self.kind == "rect_waveguide" and (
            self.waveguide_a_mm is None
            or self.waveguide_b_mm is None
            or self.mode_name is None
        ):
            raise ValueError("rect_waveguide port requires a, b and mode")
        return self


class OpenEMSProject(_StrictModel):
    schema_version: Literal["openems-plan-1.0"] = "openems-plan-1.0"
    solver_recipe_version: Literal["openems-fdtd-v2"] = "openems-fdtd-v2"
    family: Literal["pifa", "helix", "yagi_uda", "horn", "vivaldi"]
    frequency_min_hz: float = Field(gt=0)
    frequency_max_hz: float = Field(gt=0)
    unit_m: float = Field(default=1e-3, gt=0)
    boundary: tuple[str, str, str, str, str, str] = (
        "PML_8", "PML_8", "PML_8", "PML_8", "PML_8", "PML_8"
    )
    mesh_max_mm: float = Field(gt=0)
    mesh_refinement_factor: float = Field(default=1.0, ge=1.0, le=3.0)
    simulation_box_mm: tuple[float, float, float]
    materials: list[Material]
    primitives: list[Primitive]
    port: Port
    nf2ff: bool = False
    assumptions: list[str]
    verification_required: list[str]
    source_urls: list[str]

    @model_validator(mode="after")
    def validate_project(self) -> "OpenEMSProject":
        if self.frequency_max_hz <= self.frequency_min_hz:
            raise ValueError("frequency_max_hz must exceed frequency_min_hz")
        materials = [item.name for item in self.materials]
        if len(materials) != len(set(materials)):
            raise ValueError("material names must be unique")
        missing = {item.material for item in self.primitives} - set(materials)
        if missing:
            raise ValueError(f"unknown primitive materials: {sorted(missing)}")
        return self

    @property
    def canonical_sha256(self) -> str:
        raw = self.model_dump_json(exclude_none=True).encode("utf-8")
        return sha256(raw).hexdigest()


def backend_status() -> dict[str, object]:
    root = configure_openems_environment()
    modules = {
        "openEMS": importlib.util.find_spec("openEMS") is not None,
        "CSXCAD": importlib.util.find_spec("CSXCAD") is not None,
    }
    executable = shutil.which("openEMS")
    if executable is None and root is not None:
        candidate = root / "openEMS.exe"
        executable = str(candidate) if candidate.is_file() else None
    available = all(modules.values()) and executable is not None
    return {
        "available": available,
        "python_modules": modules,
        "executable": executable,
        "install_root": str(root) if root is not None else None,
        "status": "READY" if available else "BACKEND_UNAVAILABLE",
    }


def configure_openems_environment() -> Path | None:
    """Discover the per-user free-solver install without changing user settings."""
    configured = os.environ.get("CSXCAD_INSTALL_PATH") or os.environ.get(
        "OPENEMS_INSTALL_PATH"
    )
    candidates = [Path(configured)] if configured else []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(
            Path(local_app_data) / "Prompt2CST" / "openEMS-v0.0.36" / "openEMS"
        )
    for candidate in candidates:
        if (candidate / "openEMS.exe").is_file():
            os.environ.setdefault("CSXCAD_INSTALL_PATH", str(candidate))
            os.environ.setdefault("OPENEMS_INSTALL_PATH", str(candidate))
            current_path = os.environ.get("PATH", "")
            if str(candidate) not in current_path.split(os.pathsep):
                os.environ["PATH"] = str(candidate) + os.pathsep + current_path
            return candidate
    return None


def build_project(
    family: str,
    center_frequency_hz: float,
    *,
    bandwidth_fraction: float = 0.20,
    include_far_field: bool = False,
    mesh_refinement_factor: float = 1.0,
    pifa_length_scale: float = 1.0,
    pifa_feed_fraction: float = 0.22,
) -> OpenEMSProject:
    if center_frequency_hz <= 0:
        raise ValueError("center_frequency_hz must be positive")
    if not 0 < bandwidth_fraction < 1:
        raise ValueError("bandwidth_fraction must be between zero and one")
    if not 1.0 <= mesh_refinement_factor <= 3.0:
        raise ValueError("mesh_refinement_factor must be between 1.0 and 3.0")
    if not 0.6 <= pifa_length_scale <= 1.6:
        raise ValueError("pifa_length_scale must be between 0.6 and 1.6")
    if not 0.05 <= pifa_feed_fraction <= 0.95:
        raise ValueError("pifa_feed_fraction must be between 0.05 and 0.95")
    builders = {
        "pifa": _pifa,
        "helix": _helix,
        "yagi": _yagi,
        "yagi_uda": _yagi,
        "horn": _horn,
        "vivaldi": _vivaldi,
    }
    normalized = family.strip().casefold().replace("-", "_").replace(" ", "_")
    try:
        builder = builders[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported openEMS family: {family}") from exc
    fmin = center_frequency_hz * (1 - bandwidth_fraction / 2)
    fmax = center_frequency_hz * (1 + bandwidth_fraction / 2)
    if normalized != "pifa" and (
        pifa_length_scale != 1.0 or pifa_feed_fraction != 0.22
    ):
        raise ValueError("PIFA tuning parameters require family=pifa")
    project = (
        _pifa(fmin, fmax, pifa_length_scale, pifa_feed_fraction)
        if normalized == "pifa"
        else builder(fmin, fmax)
    )
    return project.model_copy(update={
        "nf2ff": include_far_field,
        "mesh_refinement_factor": mesh_refinement_factor,
    })


def write_project(project: OpenEMSProject, output_dir: str | Path) -> dict[str, str]:
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    plan_path = root / "openems_plan.json"
    script_path = root / "run_openems.py"
    plan_path.write_text(
        json.dumps(project.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    script_path.write_text(render_python(project), encoding="utf-8")
    return {
        "plan": str(plan_path),
        "script": str(script_path),
        "sha256": project.canonical_sha256,
        "backend_status": str(backend_status()["status"]),
    }


def execute_project(
    project_dir: str | Path,
    *,
    timeout_seconds: int = 1800,
    minimum_free_bytes: int = 2_000_000_000,
) -> dict[str, object]:
    """Run a generated project with bounded time and disk preflight."""
    root = Path(project_dir).resolve()
    plan_path = root / "openems_plan.json"
    script_path = root / "run_openems.py"
    if not plan_path.is_file() or not script_path.is_file():
        raise FileNotFoundError("generated openEMS plan and script are required")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    project = OpenEMSProject.model_validate_json(
        plan_path.read_text(encoding="utf-8")
    )
    if script_path.read_text(encoding="utf-8") != render_python(project):
        raise RuntimeError(
            "OPENEMS_SCRIPT_HASH_MISMATCH: generated script differs from the "
            "validated plan; regenerate the project before execution"
        )
    status = backend_status()
    if not status["available"]:
        raise RuntimeError("openEMS backend is unavailable")
    free_bytes = shutil.disk_usage(root).free
    required = 8_000_000_000 if project.nf2ff else minimum_free_bytes
    if free_bytes < required:
        raise RuntimeError(
            f"OPENEMS_DISK_PREFLIGHT_FAILED: {free_bytes} bytes free; "
            f"{required} required for {'far-field' if project.nf2ff else 'port'} run"
        )
    run_started_ns = time.time_ns()
    log_path = root / "solver.log"
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-u", str(script_path), "--run"],
            cwd=root, stdout=log_file, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        try:
            process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, check=False,
                )
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise
    with log_path.open("rb") as log_file:
        log_file.seek(0, os.SEEK_END)
        log_file.seek(max(0, log_file.tell() - 4000))
        log_tail = log_file.read().decode("utf-8", errors="replace")
    if process.returncode != 0:
        raise RuntimeError(
            f"openEMS execution failed (see {log_path}): " + log_tail
        )
    _validate_solver_convergence(log_tail, log_path)
    result_path = root / "results.json"
    if not result_path.is_file() or result_path.stat().st_mtime_ns < run_started_ns:
        raise RuntimeError("openEMS completed without fresh results.json")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    validate_result(result, project)
    return {
        "status": "COMPLETED",
        "results": str(result_path),
        "result": result,
        "solver_log": str(log_path),
        "stdout_tail": log_tail[-2000:],
    }


def _validate_solver_convergence(log_tail: str, log_path: Path) -> None:
    """Require the FDTD energy to decay to the configured -40 dB criterion."""
    energy_db = re.findall(r"Energy:.*?\(-\s*([0-9.]+)dB\)", log_tail)
    if not energy_db or float(energy_db[-1]) < 40.0:
        raise RuntimeError(
            f"OPENEMS_NOT_CONVERGED: final energy did not reach -40 dB; "
            f"inspect {log_path}"
        )


def validate_result(result: dict[str, object], project: OpenEMSProject) -> None:
    """Reject incomplete or nonfinite solver output before reporting success."""
    if result.get("source") != "OPENEMS_FDTD":
        raise RuntimeError("unexpected openEMS result provenance")
    if result.get("project_sha256") != project.canonical_sha256:
        raise RuntimeError("OPENEMS_RESULT_PLAN_MISMATCH")
    names = ("frequency_hz", "s11_db", "z_real_ohm", "z_imag_ohm")
    arrays = [result.get(name) for name in names]
    if any(not isinstance(values, list) or len(values) != 501 for values in arrays):
        raise RuntimeError("OPENEMS_RESULT_INVALID: expected 501 samples")
    if any(
        not isinstance(value, (int, float)) or not math.isfinite(value)
        for values in arrays for value in values
    ):
        raise RuntimeError("OPENEMS_RESULT_INVALID: nonfinite or nonnumeric sample")
    frequency = arrays[0]
    if frequency[0] != project.frequency_min_hz or frequency[-1] != project.frequency_max_hz:
        raise RuntimeError("OPENEMS_RESULT_INVALID: frequency range mismatch")
    if any(b <= a for a, b in zip(frequency, frequency[1:])):
        raise RuntimeError("OPENEMS_RESULT_INVALID: frequencies are not increasing")
    best_index = min(range(501), key=lambda index: arrays[1][index])
    if not isinstance(result.get("best_s11_db"), (int, float)) or not math.isclose(result["best_s11_db"], arrays[1][best_index], abs_tol=1e-6):
        raise RuntimeError("OPENEMS_RESULT_INVALID: best S11 mismatch")
    if not isinstance(result.get("best_frequency_hz"), (int, float)) or not math.isclose(result["best_frequency_hz"], frequency[best_index], abs_tol=1):
        raise RuntimeError("OPENEMS_RESULT_INVALID: best frequency mismatch")
    if project.nf2ff:
        far_field = result.get("far_field")
        if not isinstance(far_field, dict):
            raise RuntimeError("OPENEMS_RESULT_INVALID: missing far-field result")
        required = (
            "directivity_dbi", "radiation_efficiency_percent",
            "realized_gain_dbi", "radiated_power_w", "accepted_power_w",
        )
        if any(
            not isinstance(far_field.get(name), (int, float))
            or not math.isfinite(far_field[name]) for name in required
        ):
            raise RuntimeError("OPENEMS_RESULT_INVALID: nonfinite far-field metric")
        if not 0 <= far_field["radiation_efficiency_percent"] <= 105:
            raise RuntimeError("OPENEMS_RESULT_INVALID: implausible radiation efficiency")


def pifa_dimensions(project: OpenEMSProject) -> dict[str, float]:
    """Extract build dimensions from the exact simulated PIFA geometry."""
    if project.family != "pifa":
        raise ValueError("PIFA dimensions require a PIFA project")
    parts = {primitive.name: primitive for primitive in project.primitives}
    ground, radiator, short = (parts[name] for name in ("ground", "radiator", "short"))
    return {
        "radiator_length_mm": radiator.stop[0] - radiator.start[0],
        "radiator_width_mm": radiator.stop[1] - radiator.start[1],
        "radiator_height_mm": radiator.start[2] - ground.start[2],
        "ground_length_mm": ground.stop[0] - ground.start[0],
        "ground_width_mm": ground.stop[1] - ground.start[1],
        "short_wall_width_mm": short.stop[0] - short.start[0],
        "feed_distance_from_short_edge_mm": project.port.start[0] - short.start[0],
        "feed_clearance_from_short_wall_mm": project.port.start[0] - short.stop[0],
    }


def sampled_s11_band(
    result: dict[str, object], target_frequency_hz: float, threshold_db: float = -10.0
) -> dict[str, object] | None:
    """Report the contiguous sampled match band containing the target frequency."""
    if not math.isfinite(target_frequency_hz) or target_frequency_hz <= 0:
        raise ValueError("target_frequency_hz must be positive and finite")
    if not math.isfinite(threshold_db):
        raise ValueError("threshold_db must be finite")
    frequency = result["frequency_hz"]
    s11 = result["s11_db"]
    if not frequency or not frequency[0] <= target_frequency_hz <= frequency[-1]:
        raise ValueError("target_frequency_hz must lie within the sampled sweep")
    center = min(range(len(frequency)), key=lambda i: abs(frequency[i] - target_frequency_hz))
    if s11[center] > threshold_db:
        return None
    low = high = center
    while low > 0 and s11[low - 1] <= threshold_db:
        low -= 1
    while high < len(frequency) - 1 and s11[high + 1] <= threshold_db:
        high += 1
    width = frequency[high] - frequency[low]
    return {
        "threshold_db": threshold_db,
        "sampled_lower_hz": frequency[low],
        "sampled_upper_hz": frequency[high],
        "sampled_bandwidth_hz": width,
        "fractional_percent": 100 * width / target_frequency_hz,
        "lower_edge_outside_sweep": low == 0,
        "upper_edge_outside_sweep": high == len(frequency) - 1,
    }


def _search_pifa_unlocked(
    center_frequency_hz: float,
    output_dir: str | Path,
    *,
    length_scales: tuple[float, ...] = (1.4, 1.2, 1.0),
    feed_fractions: tuple[float, ...] = (0.12, 0.22, 0.4),
    target_s11_db: float = -10.0,
    max_runs: int = 9,
    timeout_seconds: int = 600,
    mesh_refinement_factor: float = 1.5,
    on_candidate: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Resume a bounded grid search, ranking only validated FDTD results."""
    if not length_scales or not feed_fractions:
        raise ValueError("length_scales and feed_fractions cannot be empty")
    if not 1 <= max_runs <= 25:
        raise ValueError("max_runs must be between 1 and 25")
    if not math.isfinite(target_s11_db) or target_s11_db >= 0:
        raise ValueError("target_s11_db must be finite and negative")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    candidates: list[dict[str, object]] = []
    real_runs = 0
    queue = deque((length_scale, feed_fraction) for length_scale in length_scales for feed_fraction in feed_fractions)
    queued = set(queue)
    evaluated: set[tuple[float, float]] = set()
    while queue:
            length_scale, feed_fraction = queue.popleft()
            queued.discard((length_scale, feed_fraction))
            if (length_scale, feed_fraction) in evaluated:
                continue
            evaluated.add((length_scale, feed_fraction))
            project = build_project(
                "pifa", center_frequency_hz,
                pifa_length_scale=length_scale,
                pifa_feed_fraction=feed_fraction,
                mesh_refinement_factor=mesh_refinement_factor,
            )
            label = f"candidate_{project.canonical_sha256[:12]}"
            candidate_dir = root / label
            write_project(project, candidate_dir)
            result_path = candidate_dir / "results.json"
            result = None
            if result_path.is_file():
                try:
                    cached = json.loads(result_path.read_text(encoding="utf-8"))
                    validate_result(cached, project)
                except (RuntimeError, ValueError, TypeError):
                    pass
                else:
                    result = cached
            if result is None:
                if real_runs >= max_runs:
                    break
                result = execute_project(candidate_dir, timeout_seconds=timeout_seconds)["result"]
                real_runs += 1
            frequency = result["frequency_hz"]
            center_index = min(
                range(len(frequency)),
                key=lambda index: abs(frequency[index] - center_frequency_hz),
            )
            candidate = {
                "length_scale": length_scale,
                "feed_fraction": feed_fraction,
                "project_sha256": project.canonical_sha256,
                "results": str(result_path),
                "center_s11_db": result["s11_db"][center_index],
                "center_z_real_ohm": result["z_real_ohm"][center_index],
                "center_z_imag_ohm": result["z_imag_ohm"][center_index],
                "best_band_s11_db": result["best_s11_db"],
                "best_band_frequency_hz": result["best_frequency_hz"],
                "meets_target": result["s11_db"][center_index] <= target_s11_db,
                "dimensions_mm": pifa_dimensions(project),
            }
            candidates.append(candidate)
            best = min(candidates, key=lambda item: item["center_s11_db"])
            summary = {
                "source": "OPENEMS_FDTD",
                "status": "TARGET_MET" if best["meets_target"] else "TARGET_UNMET",
                "target_frequency_hz": center_frequency_hz,
                "target_s11_db": target_s11_db,
                "mesh_refinement_factor": mesh_refinement_factor,
                "real_runs_this_call": real_runs,
                "evaluated_candidates": len(candidates),
                "best": best,
                "candidates": candidates.copy(),
            }
            pending = root / "search_summary.pending.json"
            pending.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            pending.replace(root / "search_summary.json")
            if on_candidate is not None:
                on_candidate(candidate)
            if best["meets_target"]:
                return summary
            best_frequency = result["best_frequency_hz"]
            if (
                result["best_s11_db"] <= target_s11_db
                and project.frequency_min_hz < best_frequency < project.frequency_max_hz
                and abs(best_frequency - center_frequency_hz) >= 2e6
            ):
                # First-order resonance scaling: f is approximately inverse to length.
                corrected = round(length_scale * best_frequency / center_frequency_hz, 4)
                proposal = (corrected, feed_fraction)
                if (
                    0.6 <= corrected <= 1.6
                    and proposal not in evaluated
                    and proposal not in queued
                ):
                    queue.appendleft(proposal)
                    queued.add(proposal)
    return summary


def search_pifa(
    center_frequency_hz: float,
    output_dir: str | Path,
    *,
    length_scales: tuple[float, ...] = (1.4, 1.2, 1.0),
    feed_fractions: tuple[float, ...] = (0.12, 0.22, 0.4),
    target_s11_db: float = -10.0,
    max_runs: int = 9,
    timeout_seconds: int = 600,
    mesh_refinement_factor: float = 1.5,
    on_candidate: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Serialize searches in one directory so candidates cannot race."""
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".search.lock").open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("PIFA_SEARCH_ALREADY_RUNNING") from exc
        try:
            return _search_pifa_unlocked(
                center_frequency_hz, root,
                length_scales=length_scales,
                feed_fractions=feed_fractions,
                target_s11_db=target_s11_db,
                max_runs=max_runs,
                timeout_seconds=timeout_seconds,
                mesh_refinement_factor=mesh_refinement_factor,
                on_candidate=on_candidate,
            )
        finally:
            lock_file.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def verify_mesh_convergence(
    project_dir: str | Path,
    *,
    refinement_factor: float = 1.5,
    timeout_seconds: int = 1200,
    s11_tolerance_db: float = 1.0,
    impedance_tolerance_ohm: float = 10.0,
) -> dict[str, object]:
    """Compare two independently solved meshes at the centre frequency."""
    if not 1.0 < refinement_factor <= 3.0:
        raise ValueError("refinement_factor must be greater than 1 and at most 3")
    root = Path(project_dir).resolve()
    plan_path = root / "openems_plan.json"
    if not plan_path.is_file():
        raise FileNotFoundError("generated openEMS plan is required")
    project = OpenEMSProject.model_validate_json(plan_path.read_text(encoding="utf-8"))
    if project.mesh_refinement_factor * refinement_factor > 3.0:
        raise ValueError("combined mesh refinement exceeds 3.0")
    baseline_path = root / "results.json"
    baseline = None
    real_runs = 0
    if baseline_path.is_file():
        try:
            cached = json.loads(baseline_path.read_text(encoding="utf-8"))
            validate_result(cached, project)
        except (RuntimeError, ValueError, TypeError):
            pass
        else:
            baseline = cached
    if baseline is None:
        baseline = execute_project(root, timeout_seconds=timeout_seconds)["result"]
        real_runs += 1
    refined = OpenEMSProject.model_validate({
        **project.model_dump(mode="python"),
        "mesh_refinement_factor": project.mesh_refinement_factor * refinement_factor,
    })
    refined_dir = root / f"mesh_refined_{refinement_factor:.2f}"
    write_project(refined, refined_dir)
    refined_path = refined_dir / "results.json"
    refined_result = None
    if refined_path.is_file():
        try:
            cached = json.loads(refined_path.read_text(encoding="utf-8"))
            validate_result(cached, refined)
        except (RuntimeError, ValueError, TypeError):
            pass
        else:
            refined_result = cached
    if refined_result is None:
        try:
            refined_result = execute_project(refined_dir, timeout_seconds=timeout_seconds)["result"]
        except subprocess.TimeoutExpired:
            report = {
                "source": "OPENEMS_FDTD",
                "real_runs_this_call": real_runs + 1,
                "status": "INCONCLUSIVE_TIMEOUT",
                "center_frequency_hz": (project.frequency_min_hz + project.frequency_max_hz) / 2,
                "baseline_project_sha256": project.canonical_sha256,
                "refined_project_sha256": refined.canonical_sha256,
                "baseline_results": str(baseline_path),
                "refined_results": None,
                "timeout_seconds": timeout_seconds,
            }
            (root / "mesh_convergence.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            return report
        real_runs += 1
    center_hz = (project.frequency_min_hz + project.frequency_max_hz) / 2
    baseline_index = min(range(501), key=lambda i: abs(baseline["frequency_hz"][i] - center_hz))
    refined_index = min(range(501), key=lambda i: abs(refined_result["frequency_hz"][i] - center_hz))
    s11_delta = abs(baseline["s11_db"][baseline_index] - refined_result["s11_db"][refined_index])
    impedance_delta = abs(complex(
        baseline["z_real_ohm"][baseline_index] - refined_result["z_real_ohm"][refined_index],
        baseline["z_imag_ohm"][baseline_index] - refined_result["z_imag_ohm"][refined_index],
    ))
    report = {
        "source": "OPENEMS_FDTD",
        "real_runs_this_call": real_runs,
        "status": "CONVERGED" if s11_delta <= s11_tolerance_db and impedance_delta <= impedance_tolerance_ohm else "NOT_CONVERGED",
        "center_frequency_hz": center_hz,
        "baseline_project_sha256": project.canonical_sha256,
        "refined_project_sha256": refined.canonical_sha256,
        "baseline_results": str(baseline_path),
        "refined_results": str(refined_path),
        "baseline_s11_db": baseline["s11_db"][baseline_index],
        "refined_s11_db": refined_result["s11_db"][refined_index],
        "s11_delta_db": s11_delta,
        "impedance_delta_ohm": impedance_delta,
        "s11_tolerance_db": s11_tolerance_db,
        "impedance_tolerance_ohm": impedance_tolerance_ohm,
    }
    (root / "mesh_convergence.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def render_python(project: OpenEMSProject) -> str:
    """Render a self-contained Python/CSXCAD input from validated operations."""
    payload = json.dumps(project.model_dump(mode="json"), indent=2, sort_keys=True)
    return f'''"""Generated by Prompt2CST. Review openems_plan.json before execution."""
import json
import os
from pathlib import Path

_local = os.environ.get("LOCALAPPDATA")
_bundled = Path(_local) / "Prompt2CST" / "openEMS-v0.0.36" / "openEMS" if _local else None
if _bundled is not None and (_bundled / "openEMS.exe").is_file():
    os.environ.setdefault("CSXCAD_INSTALL_PATH", str(_bundled))
    os.environ.setdefault("OPENEMS_INSTALL_PATH", str(_bundled))
    os.environ["PATH"] = str(_bundled) + os.pathsep + os.environ.get("PATH", "")

import numpy as np
from CSXCAD import CSXCAD
from openEMS import openEMS
from openEMS.physical_constants import EPS0

PLAN = json.loads({payload!r})
PROJECT_SHA256 = {project.canonical_sha256!r}
ROOT = Path(__file__).resolve().parent
SIM_PATH = ROOT / "simulation"
F0 = (PLAN["frequency_min_hz"] + PLAN["frequency_max_hz"]) / 2
FC = max((PLAN["frequency_max_hz"] - PLAN["frequency_min_hz"]) / 2, F0 / 2)

fdtd = openEMS(NrTS=30000, EndCriteria=1e-4)
fdtd.SetGaussExcite(F0, FC)
fdtd.SetBoundaryCond(PLAN["boundary"])
csx = CSXCAD.ContinuousStructure()
fdtd.SetCSX(csx)
grid = csx.GetGrid()
grid.SetDeltaUnit(PLAN["unit_m"])

sx, sy, sz = PLAN["simulation_box_mm"]
step = min(PLAN["mesh_max_mm"], sx/20, sy/20, sz/20) / PLAN["mesh_refinement_factor"]
grid.SetLines("x", [-sx/2, sx/2])
grid.SetLines("y", [-sy/2, sy/2])
grid.SetLines("z", [-sz/2, sz/2])

# Force every solid and port boundary onto the Yee grid. Without these lines,
# sub-cell sheets and feeds can disappear and produce a zero-energy run.
axis_names = ("x", "y", "z")
edge_lines = {{"x": [], "y": [], "z": []}}
for primitive in PLAN["primitives"]:
    if primitive["kind"] in ("box", "cylinder"):
        for axis, lo, hi in zip(axis_names, primitive["start"], primitive["stop"]):
            edge_lines[axis].extend((lo, hi))
    if primitive["kind"] == "cylinder":
        radius = primitive["radius_mm"]
        for index, axis in enumerate(axis_names):
            center = (primitive["start"][index] + primitive["stop"][index]) / 2
            edge_lines[axis].extend((center-radius, center, center+radius))
    if primitive["kind"] == "curve":
        points = np.asarray(primitive["points"], dtype=float)
        for index, axis in enumerate(axis_names):
            edge_lines[axis].extend((points[:, index].min(), points[:, index].max()))
for axis, lo, hi in zip(axis_names, PLAN["port"]["start"], PLAN["port"]["stop"]):
    edge_lines[axis].extend((lo, hi))
for axis in axis_names:
    grid.AddLine(axis, sorted(set(edge_lines[axis])))
    grid.SmoothMeshLines(axis, step, ratio=1.4)

properties = {{}}
for material in PLAN["materials"]:
    if material["kind"] == "metal":
        properties[material["name"]] = csx.AddMetal(material["name"])
    else:
        prop = csx.AddMaterial(material["name"])
        kappa = 2*np.pi*F0*EPS0*material["epsilon_r"]*material["loss_tangent"]
        prop.SetMaterialProperty(epsilon=material["epsilon_r"], mue=1, kappa=kappa)
        properties[material["name"]] = prop

for primitive in PLAN["primitives"]:
    prop = properties[primitive["material"]]
    if primitive["kind"] == "box":
        prop.AddBox(priority=primitive["priority"], start=primitive["start"], stop=primitive["stop"])
    elif primitive["kind"] == "cylinder":
        prop.AddCylinder(priority=primitive["priority"], start=primitive["start"], stop=primitive["stop"], radius=primitive["radius_mm"])
    elif primitive["kind"] == "curve":
        prop.AddCurve(np.asarray(primitive["points"], dtype=float).T)

p = PLAN["port"]
if p["kind"] == "lumped":
    port = fdtd.AddLumpedPort(p["number"], p["resistance_ohm"], p["start"], p["stop"], p["direction"], 1.0, priority=20)
else:
    port = fdtd.AddRectWaveGuidePort(p["number"], p["start"], p["stop"], p["direction"], p["waveguide_a_mm"]*PLAN["unit_m"], p["waveguide_b_mm"]*PLAN["unit_m"], p["mode_name"], 1)

if PLAN["nf2ff"]:
    nf2ff_resolution = 299792458.0 / PLAN["frequency_max_hz"] / PLAN["unit_m"] / 15
    nf2ff = fdtd.CreateNF2FFBox(opt_resolution=[nf2ff_resolution]*3)

SIM_PATH.mkdir(parents=True, exist_ok=True)
csx.Write2XML(str(ROOT / "geometry.xml"))
if "--run" in __import__("sys").argv:
    fdtd.Run(str(SIM_PATH), cleanup=True)
    freq = np.linspace(PLAN["frequency_min_hz"], PLAN["frequency_max_hz"], 501)
    port.CalcPort(str(SIM_PATH), freq)
    s11 = port.uf_ref / port.uf_inc
    zin = port.uf_tot / port.if_tot
    idx = int(np.argmin(np.abs(s11)))
    result = {{
        "source": "OPENEMS_FDTD",
        "project_sha256": PROJECT_SHA256,
        "frequency_hz": freq.tolist(),
        "s11_db": (20*np.log10(np.maximum(np.abs(s11), 1e-15))).tolist(),
        "z_real_ohm": np.real(zin).tolist(),
        "z_imag_ohm": np.imag(zin).tolist(),
        "best_frequency_hz": float(freq[idx]),
        "best_s11_db": float(20*np.log10(max(abs(s11[idx]), 1e-15))),
    }}
    if PLAN["nf2ff"]:
        theta = np.arange(0.0, 181.0, 5.0)
        phi = np.arange(-180.0, 180.0, 5.0)
        far = nf2ff.CalcNF2FF(str(SIM_PATH), F0, theta, phi)
        accepted = float(np.interp(F0, freq, port.P_acc))
        radiated = float(far.Prad[0])
        directivity = float(far.Dmax[0])
        if accepted <= 0 or radiated < 0 or directivity <= 0:
            raise RuntimeError("invalid NF2FF power or directivity")
        efficiency = radiated / accepted
        center_index = int(np.argmin(np.abs(freq-F0)))
        mismatch_efficiency = max(0.0, 1.0-abs(s11[center_index])**2)
        realized_gain = directivity * efficiency * mismatch_efficiency
        if realized_gain <= 0:
            raise RuntimeError("invalid realized gain")
        result["far_field"] = {{
            "source": "OPENEMS_NF2FF",
            "frequency_hz": F0,
            "directivity_dbi": float(10*np.log10(directivity)),
            "radiation_efficiency_percent": float(100*efficiency),
            "realized_gain_dbi": float(10*np.log10(realized_gain)),
            "radiated_power_w": radiated,
            "accepted_power_w": accepted,
        }}
    (ROOT / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
'''


def _common(fmin: float, fmax: float) -> dict[str, object]:
    wavelength_mm = C0 / fmin * 1000
    return {
        "frequency_min_hz": fmin,
        "frequency_max_hz": fmax,
        "mesh_max_mm": wavelength_mm / 25,
        "materials": [Material(name="pec", kind="metal")],
        "verification_required": [
            "mesh convergence",
            "S11 and complex input impedance",
            "radiation and total efficiency",
            "realized gain and radiation pattern",
            "fabrication tolerance sweep",
        ],
    }


def _pifa(
    fmin: float, fmax: float,
    length_scale: float = 1.0,
    feed_fraction: float = 0.22,
) -> OpenEMSProject:
    f0 = (fmin + fmax) / 2
    q = C0 / f0 * 1000 / 4
    length, width, height = 0.64 * q * length_scale, 0.36 * q, max(3.0, 0.08 * q)
    ground_l, ground_w = length + 20, max(width + 20, 35)
    feed_x = -length / 2 + feed_fraction * length
    common = _common(fmin, fmax)
    base_materials = common.pop("materials")
    return OpenEMSProject(
        family="pifa", **common,
        simulation_box_mm=(ground_l + 80, ground_w + 80, 2 * (height + 40)),
        materials=base_materials,
        primitives=[
            Primitive(name="ground", material="pec", kind="box", start=(-ground_l/2,-ground_w/2,0.0), stop=(ground_l/2,ground_w/2,0.0)),
            Primitive(name="radiator", material="pec", kind="box", start=(-length/2,-width/2,height), stop=(length/2,width/2,height)),
            Primitive(name="short", material="pec", kind="box", start=(-length/2,-width/2,0), stop=(-length/2+1.0,width/2,height)),
        ],
        port=Port(kind="lumped", resistance_ohm=50, start=(feed_x,0,0), stop=(feed_x,0,height), direction="z"),
        assumptions=["quarter-wave PIFA initial sizing", f"radiator length scale {length_scale}", f"feed fraction from shorted edge {feed_fraction}", "finite ground included", "enclosure and user phantom not included"],
        source_urls=["https://www.mdpi.com/2079-9292/10/21/2576", "https://docs.openems.de/en/latest/concepts/sar.html"],
    )


def _helix(fmin: float, fmax: float) -> OpenEMSProject:
    f0 = (fmin + fmax) / 2
    wavelength = C0 / f0 * 1000
    radius, pitch, turns, feed_h = wavelength/(2*math.pi), wavelength/4, 8, 3.0
    points = []
    for i in range(turns * 24 + 1):
        angle = 2 * math.pi * i / 24
        points.append((radius*math.cos(angle), radius*math.sin(angle), feed_h + pitch*i/24))
    common = _common(fmin, fmax)
    return OpenEMSProject(
        family="helix", **common,
        simulation_box_mm=(3*wavelength, 3*wavelength, turns*pitch + 2*wavelength),
        primitives=[
            Primitive(name="ground", material="pec", kind="cylinder", start=(0,0,-0.1), stop=(0,0,0.1), radius_mm=wavelength/2),
            Primitive(name="helix", material="pec", kind="curve", points=points),
        ],
        port=Port(kind="lumped", resistance_ohm=120, start=(radius,0,0), stop=(radius,0,feed_h), direction="z"),
        assumptions=["eight-turn axial-mode starting design", "circumference approximately one wavelength", "wire curve uses zero-thickness PEC representation"],
        source_urls=["https://docs.openems.de/en/latest/python/openEMS/Tutorials/Helical_Antenna.html"],
    )


def _yagi(fmin: float, fmax: float) -> OpenEMSProject:
    f0 = (fmin + fmax) / 2
    wavelength = C0 / f0 * 1000
    radius, gap = 0.00425*wavelength, 0.01*wavelength
    xs = [-0.20*wavelength, 0, 0.20*wavelength, 0.40*wavelength, 0.60*wavelength]
    lengths = [0.482*wavelength, 0.47*wavelength, 0.43*wavelength, 0.42*wavelength, 0.41*wavelength]
    parts: list[Primitive] = [
        Primitive(name="boom", material="fiberglass", kind="cylinder", start=(xs[0]-0.1*wavelength,0,0), stop=(xs[-1]+0.1*wavelength,0,0), radius_mm=radius, priority=5)
    ]
    for index, (x, length) in enumerate(zip(xs, lengths)):
        if index == 1:
            parts.extend([
                Primitive(name="driven_a", material="pec", kind="cylinder", start=(x,-length/2,0), stop=(x,-gap/2,0), radius_mm=radius),
                Primitive(name="driven_b", material="pec", kind="cylinder", start=(x,gap/2,0), stop=(x,length/2,0), radius_mm=radius),
            ])
        else:
            parts.append(Primitive(name=f"element_{index}", material="pec", kind="cylinder", start=(x,-length/2,0), stop=(x,length/2,0), radius_mm=radius))
    common = _common(fmin, fmax)
    base_materials = common.pop("materials")
    return OpenEMSProject(
        family="yagi_uda", **common,
        simulation_box_mm=(2*wavelength, 2*wavelength, 1.5*wavelength),
        materials=base_materials + [
            Material(name="fiberglass", kind="dielectric", epsilon_r=4.5, loss_tangent=0.01)
        ],
        primitives=parts,
        port=Port(kind="lumped", resistance_ohm=50, start=(0,-gap/2,0), stop=(0,gap/2,0), direction="y"),
        assumptions=["five-element initial array", "dimensions initialized from NBS normalized design data", "insulating fiberglass boom keeps the driven-feed gap open", "boom and mounting corrections require optimization"],
        source_urls=["https://nvlpubs.nist.gov/nistpubs/Legacy/TN/nbstechnicalnote688.pdf"],
    )


def _horn(fmin: float, fmax: float) -> OpenEMSProject:
    f0 = (fmin + fmax) / 2
    wavelength = C0 / f0 * 1000
    a, b = 0.75*wavelength, 0.375*wavelength
    length, aperture_w, aperture_h, wall = 1.5*wavelength, 1.5*wavelength, wavelength, 0.5
    feed_l, segments = 0.5*wavelength, 24
    parts: list[Primitive] = [
        Primitive(name="wg_left", material="pec", kind="box", start=(-a/2-wall,-b/2,-feed_l), stop=(-a/2,b/2,0)),
        Primitive(name="wg_right", material="pec", kind="box", start=(a/2,-b/2,-feed_l), stop=(a/2+wall,b/2,0)),
        Primitive(name="wg_bottom", material="pec", kind="box", start=(-a/2-wall,-b/2-wall,-feed_l), stop=(a/2+wall,-b/2,0)),
        Primitive(name="wg_top", material="pec", kind="box", start=(-a/2-wall,b/2,-feed_l), stop=(a/2+wall,b/2+wall,0)),
    ]
    dz = length / segments
    for i in range(segments):
        z0, z1 = i*dz, (i+1)*dz
        w0 = a + (aperture_w-a)*i/segments
        w1 = a + (aperture_w-a)*(i+1)/segments
        h0 = b + (aperture_h-b)*i/segments
        h1 = b + (aperture_h-b)*(i+1)/segments
        parts.extend([
            Primitive(name=f"flare_l_{i}", material="pec", kind="box", start=(-w1/2-wall,-h1/2,z0), stop=(-w0/2,h1/2,z1)),
            Primitive(name=f"flare_r_{i}", material="pec", kind="box", start=(w0/2,-h1/2,z0), stop=(w1/2+wall,h1/2,z1)),
            Primitive(name=f"flare_b_{i}", material="pec", kind="box", start=(-w1/2,-h1/2-wall,z0), stop=(w1/2,-h0/2,z1)),
            Primitive(name=f"flare_t_{i}", material="pec", kind="box", start=(-w1/2,h0/2,z0), stop=(w1/2,h1/2+wall,z1)),
        ])
    common = _common(fmin, fmax)
    return OpenEMSProject(
        family="horn", **common,
        simulation_box_mm=(aperture_w+2*wavelength, aperture_h+2*wavelength, length+feed_l+2*wavelength),
        primitives=parts,
        port=Port(kind="rect_waveguide", start=(-a/2,-b/2,-feed_l), stop=(a/2,b/2,-feed_l/2), direction="z", waveguide_a_mm=a, waveguide_b_mm=b, mode_name="TE10"),
        assumptions=["pyramidal horn initialized for TE10", "flare is a 24-section staircase approximation and must pass mesh refinement"],
        source_urls=["https://docs.openems.de/en/latest/octave/Tutorials/Horn_Antenna.html"],
    )


def _vivaldi(fmin: float, fmax: float) -> OpenEMSProject:
    wavelength_low = C0 / fmin * 1000
    board_l, board_w, h = 0.65*wavelength_low, 0.55*wavelength_low, 0.8
    strips = 48
    parts: list[Primitive] = [
        Primitive(name="substrate", material="substrate", kind="box", start=(-board_l/2,-board_w/2,0), stop=(board_l/2,board_w/2,h))
    ]
    dx = board_l / strips
    slot_min, slot_max = 0.5, board_w*0.82
    rate = math.log(slot_max/slot_min)
    feed_gap = slot_min * math.exp(rate/strips)
    for i in range(strips):
        x0, x1 = -board_l/2+i*dx, -board_l/2+(i+1)*dx
        slot = slot_min * math.exp(rate*(i+1)/strips)
        parts.extend([
            Primitive(name=f"lower_{i}", material="pec", kind="box", start=(x0,-board_w/2,h), stop=(x1,-slot/2,h)),
            Primitive(name=f"upper_{i}", material="pec", kind="box", start=(x0,slot/2,h), stop=(x1,board_w/2,h)),
        ])
    common = _common(fmin, fmax)
    base_materials = common.pop("materials")
    return OpenEMSProject(
        family="vivaldi", **common,
        simulation_box_mm=(board_l+2*wavelength_low, board_w+2*wavelength_low, 1.5*wavelength_low),
        materials=base_materials + [
            Material(name="substrate", kind="dielectric", epsilon_r=4.3, loss_tangent=0.02)
        ],
        primitives=parts,
        port=Port(kind="lumped", resistance_ohm=50, start=(-board_l/2+dx/2,-feed_gap/2,h), stop=(-board_l/2+dx/2,feed_gap/2,h), direction="y"),
        assumptions=["exponential tapered-slot initial geometry", "48-section staircase taper", "idealized lumped slot feed; production design requires a broadband transition"],
        source_urls=["https://www.mdpi.com/1424-8220/24/16/5368"],
    )
