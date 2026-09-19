"""Stage-B CST-only impedance matching for a frequency-locked temple PIFA.

The workflow starts from a validated Stage-A checkpoint. It never rebuilds a
default PIFA and never changes ``radiator_length_mm``: only ``feed_offset_mm``
is active. A point is eligible only when its measured resonance remains inside
the configured lock window.
"""

from __future__ import annotations

import json
import math
import multiprocessing
import os
from pathlib import Path
import time
from typing import Any

from .cst_bridge import CSTBridge, _extraction_summary
from .optimizer.cache import ResultCache
from .optimizer.schema import impedance_error

# Keep this deliberately local to the locked 0.5 mm Stage-A feed.  It is not
# a geometry redesign: radiator_length_mm is immutable throughout Stage B.
DEFAULT_OFFSETS_MM = (0.25, 0.375, 0.5, 0.625, 0.75, 1.0)
TARGET_FREQUENCY_GHZ = 2.45
FREQUENCY_TOLERANCE_GHZ = 0.010
COM_TIMEOUT_SECONDS = 45.0


class CSTComOperationBlocked(RuntimeError):
    """A real CST COM helper did not return within its bounded operation time."""

    def __init__(self, diagnostic: dict[str, Any]) -> None:
        self.diagnostic = diagnostic
        super().__init__(json.dumps(diagnostic, sort_keys=True))


def _bounded_com_worker(queue: Any, output_dir: str, operation: str,
                        project_path: str, kwargs: dict[str, Any], trace_path: str) -> None:
    """Child process used only for a single CST COM operation.

    On timeout the parent can terminate this helper without touching the
    user's CST Design Environment process.
    """
    os.environ["PROMPT2CST_COM_TRACE_PATH"] = trace_path
    started = time.monotonic()
    try:
        bridge = CSTBridge(output_dir=output_dir)
        method = getattr(bridge, operation)
        result = method(project_path, **kwargs)
        queue.put({"status": "completed", "result": result,
                   "elapsed_seconds": time.monotonic() - started})
    except BaseException as exc:
        queue.put({"status": "error", "error": f"{type(exc).__name__}: {exc}",
                   "elapsed_seconds": time.monotonic() - started})


class RealPifaImpedanceSweep:
    """A resumable, constrained real-CST feed-offset sweep."""

    def __init__(self, output_dir: str | Path, *, resume: bool = False,
                 stage_a_checkpoint: str | Path | None = None,
                 use_bounded_com: bool = True) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = self.output_dir / "checkpoint.json"
        self.resume = resume
        self.stage_a_checkpoint = Path(stage_a_checkpoint) if stage_a_checkpoint else None
        self.use_bounded_com = use_bounded_com
        self.cache = ResultCache(self.output_dir / "cache.db")
        self.bridge = CSTBridge(output_dir=self.output_dir)

    def _write_json(self, name: str, value: Any) -> None:
        path = self.output_dir / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def _load_checkpoint(self) -> dict[str, Any]:
        try:
            return json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot resume Stage B: {exc}") from exc

    @staticmethod
    def _result(extraction: dict[str, Any]) -> dict[str, float]:
        if extraction.get("status") != "completed":
            raise RuntimeError(extraction.get("error", "CST result extraction failed"))
        values = extraction.get("extracted", {})
        required = ("s11_db", "f_res_ghz", "vswr", "zin_re", "zin_im")
        missing = [name for name in required if name not in values]
        if missing:
            raise RuntimeError("CST did not provide required results: " + ", ".join(missing))
        return {"s11_db": float(values["s11_db"][0]), "f_res_ghz": float(values["f_res_ghz"][0]),
                "vswr": float(values["vswr"][0]), "z_real": float(values["zin_re"][0]),
                "z_imag": float(values["zin_im"][0])}

    def _checkpoint(self, state: dict[str, Any]) -> None:
        state["optimizer_state"] = {"algorithm": "bounded_constrained_feed_offset_sweep",
            "candidate_offsets_mm": list(DEFAULT_OFFSETS_MM), "next_candidate_index": state["next_candidate_index"],
            "target_frequency_ghz": TARGET_FREQUENCY_GHZ, "frequency_tolerance_ghz": FREQUENCY_TOLERANCE_GHZ}
        self._write_json("checkpoint.json", state)

    def _mark_blocked(self, state: dict[str, Any], diagnostic: dict[str, Any]) -> None:
        """Persist a non-green stop state before control returns to the caller."""
        state["status"] = "blocked_cst_com"
        state["blocker"] = diagnostic
        self._write_json("validation_matrix.json", {
            "stage": "B_impedance", "status": "BLOCKED_CST_COM",
            "stage_a_source": "PASS" if state.get("stage_a_reopen_validation") else "NOT_REVALIDATED",
            "radiator_length_frozen": "PASS (21.75 mm checkpoint lock)",
            "candidate_real_cst_solves": "NOT_RUN" if not state.get("history") else "INCOMPLETE",
            "frequency_constraint": "NOT_EVALUATED", "impedance_improved": "NOT_EVALUATED",
            "final_saveas_reopen": "NOT_RUN", "com_diagnosis": diagnostic,
        })
        self._checkpoint(state)

    def _com_call(self, operation: str, project_path: Path, *, timeout_seconds: float = COM_TIMEOUT_SECONDS,
                  **kwargs: Any) -> Any:
        """Run one CST COM operation with structured tracing and fail-closed timeout."""
        started = time.monotonic()
        diagnostic = {"operation": operation, "project_path": str(project_path.resolve()),
                      "parameter": kwargs.get("name") or kwargs.get("parameters"),
                      "timeout_seconds": timeout_seconds, "started_at": self._timestamp()}
        if not self.use_bounded_com:
            try:
                result = getattr(self.bridge, operation)(project_path, **kwargs)
            except Exception as exc:
                diagnostic.update({"classification": "COM_OPERATION_ERROR", "elapsed_seconds": time.monotonic() - started,
                                   "error": f"{type(exc).__name__}: {exc}"})
                raise CSTComOperationBlocked(diagnostic) from exc
            diagnostic.update({"classification": "COM_OPERATION_COMPLETED", "elapsed_seconds": time.monotonic() - started})
            return result
        trace_path = self.output_dir / "com_operation_trace.jsonl"
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        worker = context.Process(target=_bounded_com_worker,
                                 args=(queue, str(self.output_dir), operation, str(project_path), kwargs, str(trace_path)))
        worker.start()
        worker.join(timeout_seconds)
        diagnostic["elapsed_seconds"] = time.monotonic() - started
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
            diagnostic.update({"classification": "COM_TIMEOUT", "helper_pid": worker.pid,
                               "com_call": "see last started event in com_operation_trace.jsonl"})
            raise CSTComOperationBlocked(diagnostic)
        if queue.empty():
            diagnostic.update({"classification": "COM_HELPER_NO_RESULT", "helper_exitcode": worker.exitcode})
            raise CSTComOperationBlocked(diagnostic)
        response = queue.get()
        if response.get("status") != "completed":
            diagnostic.update({"classification": "COM_OPERATION_ERROR", "helper_exitcode": worker.exitcode,
                               "error": response.get("error"), "worker_elapsed_seconds": response.get("elapsed_seconds")})
            raise CSTComOperationBlocked(diagnostic)
        return response["result"]

    @staticmethod
    def _timestamp() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _cache_context(self, project_path: Path, state: dict[str, Any]) -> str:
        """Identify every input that can change a CST RF result.

        The project archive hash makes a resumed run distinct from a run based
        on another CST snapshot even when its path and parameter names match.
        """
        import hashlib

        project_bytes = project_path.read_bytes()
        return json.dumps({
            "stage": "B_impedance",
            "topology": "PIFA",
            "project_path": str(project_path.resolve()),
            "project_sha256": hashlib.sha256(project_bytes).hexdigest(),
            "solver": "CSTStudio.Application.2026/Solver.Start",
            "s_parameter": "S1,1",
            "reference_impedance_ohm": 50.0,
            "target_frequency_ghz": TARGET_FREQUENCY_GHZ,
            "frequency_tolerance_ghz": FREQUENCY_TOLERANCE_GHZ,
            "radiator_length_mm": state["locked_parameters"]["radiator_length_mm"],
        }, sort_keys=True)

    def _snapshot_project(self, project_path: Path, stem: str, parameters: dict[str, float]) -> dict[str, Any]:
        result = self._com_call("create_validated_cst_snapshot", project_path, snapshot_name=stem,
                                expected_parameters=parameters, require_results=True,
                                timeout_seconds=120.0)
        if result["status"] != "VALID":
            raise RuntimeError(f"Failed to create validated CST snapshot: {result}")
        return result

    def _run_live(self, project_path: Path, radiator_length_mm: float, offset: float, tag: str) -> tuple[dict[str, float], dict[str, Any]]:
        parameters = {"radiator_length_mm": radiator_length_mm, "feed_offset_mm": offset}
        started_at = self._timestamp()
        before_mtime = project_path.stat().st_mtime_ns
        update = self._com_call("update_parameters", project_path, parameters=parameters)
        if update.get("status") != "completed" or not update.get("updated", False):
            raise RuntimeError(f"CST parameter update did not complete: {update}")
        readback = {name: self._com_call("read_parameter", project_path, name=name) for name in parameters}
        if any(not math.isclose(readback[name], value, abs_tol=1e-9) for name, value in parameters.items()):
            raise RuntimeError(f"CST parameter readback mismatch: expected {parameters}, got {readback}")
        solver = self._com_call("run_solver", project_path, timeout_seconds=180.0)
        if solver.get("status") != "completed" or not solver.get("solver_run", False):
            raise RuntimeError(f"CST solver did not complete: {solver}")
        if project_path.stat().st_mtime_ns < before_mtime:
            raise RuntimeError("CST project timestamp moved backwards after solver run")
        extraction = self._com_call("extract_results", project_path, artifact_tag=tag)
        result = self._result(extraction)
        raw = extraction.get("raw_extracted", {})
        required_artifacts = ("ascii_path", "touchstone_path", "raw_results_path")
        missing_artifacts = [key for key in required_artifacts if not raw.get(key) or not Path(str(raw[key])).is_file()]
        if missing_artifacts:
            raise RuntimeError("CST extraction is incomplete; missing fresh artifacts: " + ", ".join(missing_artifacts))
        return result, {"started_at": started_at, "finished_at": self._timestamp(),
            "parameter_update": update, "parameter_readback": readback, "solver": solver,
            "project_mtime_ns_before": before_mtime, "project_mtime_ns_after": project_path.stat().st_mtime_ns,
            "extraction": _extraction_summary(extraction),
            "raw_artifacts": {key: raw[key] for key in required_artifacts}}

    def _start_from_stage_a(self) -> dict[str, Any]:
        if self.stage_a_checkpoint is None:
            raise ValueError("Stage B requires --stage-a-checkpoint; it must be a validated FREQUENCY_LOCKED checkpoint.")
        stage_a = json.loads(self.stage_a_checkpoint.read_text(encoding="utf-8"))
        if stage_a.get("status") != "FREQUENCY_LOCKED" or not stage_a.get("acceptance", {}).get("frequency_locked"):
            raise ValueError("Stage B requires a FREQUENCY_LOCKED Stage-A checkpoint.")
        parameters = stage_a.get("best_parameters", {})
        length, feed = float(parameters["radiator_length_mm"]), float(parameters["feed_offset_mm"])
        if not math.isclose(length, 21.75, abs_tol=1e-9):
            raise ValueError(f"Stage B is scoped to the 21.75 mm Stage-A lock; checkpoint has {length} mm.")
        source = Path(stage_a["final_snapshot"]["snapshot_path"])
        source_readback = {name: self._com_call("read_parameter", source, name=name) for name in ("radiator_length_mm", "feed_offset_mm")}
        if not math.isclose(source_readback["radiator_length_mm"], length, abs_tol=1e-9):
            raise RuntimeError(f"Stage-A snapshot radiator readback mismatch: {source_readback}")
        # Extraction is a read-only CST reopen/export check: source evidence
        # must be usable before making the Stage-B SaveAs working copy.
        source_extraction = self._com_call("extract_results", source, artifact_tag="stage_a_reopen_check")
        self._result(source_extraction)
        working = self._snapshot_project(source, "stage_b_working", {"radiator_length_mm": length, "feed_offset_mm": feed})
        return {"schema_version": "2.0", "kind": "real_pifa_stage_b_impedance_optimization", "stage": "B_impedance",
            "status": "in_progress", "iteration": 0, "stage_a_checkpoint": str(self.stage_a_checkpoint.resolve()),
            "cst_project_path": working["snapshot_path"], "working_snapshot": working,
            "stage_a_reopen_validation": {"parameter_readback": source_readback,
                "result": self._result(source_extraction), "raw_artifacts": source_extraction.get("raw_extracted", {})},
            "parameter_states": {"radiator_length_mm": "FROZEN", "feed_offset_mm": "ACTIVE"},
            "locked_parameters": {"radiator_length_mm": length}, "initial_parameters": {"feed_offset_mm": feed},
            "best_parameter": {}, "best_objective": None, "history": [], "failures": [],
            "completed_simulation_ids": [], "next_candidate_index": 0}

    def _revalidate_stage_a_source(self, state: dict[str, Any]) -> None:
        """Reopen the locked source on resume; never infer it from old evidence."""
        if not state.get("stage_a_checkpoint"):
            raise RuntimeError("Stage-B checkpoint has no Stage-A provenance path")
        stage_a = json.loads(Path(state["stage_a_checkpoint"]).read_text(encoding="utf-8"))
        source = Path(stage_a["final_snapshot"]["snapshot_path"])
        expected = {"radiator_length_mm": 21.75, "feed_offset_mm": 0.5}
        readback = {name: self._com_call("read_parameter", source, name=name) for name in expected}
        if any(not math.isclose(readback[name], value, abs_tol=1e-9) for name, value in expected.items()):
            raise RuntimeError(f"Stage-A source readback changed: expected {expected}, got {readback}")
        state["stage_a_resume_reopen_validation"] = {"timestamp": self._timestamp(),
            "source_project": str(source), "parameter_readback": readback}

    def run(self, *, stop_after: int | None = None) -> dict[str, Any]:
        if self.resume:
            state = self._load_checkpoint()
            if state.get("status") == "completed":
                return state
            try:
                self._revalidate_stage_a_source(state)
            except CSTComOperationBlocked as exc:
                self._mark_blocked(state, exc.diagnostic)
                raise
        else:
            if self.checkpoint_path.exists():
                raise FileExistsError(f"Evidence exists at {self.output_dir}; use --resume or choose a new directory.")
            state = self._start_from_stage_a()
            self._checkpoint(state)
        project_path = Path(state["cst_project_path"])
        length = float(state["locked_parameters"]["radiator_length_mm"])
        if not math.isclose(length, 21.75, abs_tol=1e-9):
            raise RuntimeError(f"Stage B radiator length is not frozen to 21.75 mm: {length}")
        try:
            reopen_length = self._com_call("read_parameter", project_path, name="radiator_length_mm")
        except CSTComOperationBlocked as exc:
            self._mark_blocked(state, exc.diagnostic)
            raise
        if not math.isclose(reopen_length, length, abs_tol=1e-9):
            raise RuntimeError(f"Stage-B working project readback mismatch: expected {length}, got {reopen_length}")
        state.pop("blocker", None)
        state["working_project_reopen_validation"] = {"timestamp": self._timestamp(), "radiator_length_mm": reopen_length}
        self._checkpoint(state)
        for index in range(int(state["next_candidate_index"]), len(DEFAULT_OFFSETS_MM)):
            offset = float(DEFAULT_OFFSETS_MM[index])
            params = {"radiator_length_mm": length, "feed_offset_mm": offset}
            context = self._cache_context(project_path, state)
            # Cache entries are forensic/restart metadata only.  A Stage-B
            # candidate is never accepted from cache: every listed offset gets
            # a fresh CST parameter update, solve, and S11/Touchstone export.
            try:
                result, detail = self._run_live(project_path, length, offset, f"stage_b_{index + 1:02d}")
            except Exception as exc:
                state["failures"].append({"iteration": index + 1, "parameters": params, "error": f"{type(exc).__name__}: {exc}"})
                if isinstance(exc, CSTComOperationBlocked):
                    self._mark_blocked(state, exc.diagnostic)
                    raise
                self._checkpoint(state)
                raise
            self.cache.put(params, result, "CST_SIMULATION", context=context)
            source, simulation_id = "CST_SIMULATION", f"cst-{index + 1:03d}"
            state["completed_simulation_ids"].append(simulation_id)
            if index == 0:
                state["cache_validation"] = {"identical_candidate": params,
                    "same_configuration": "CACHE_HIT" if self.cache.get(params, context=context) else "CACHE_MISS",
                    "policy": "cache entries are not used to replace required CST solves"}
            frequency_error = abs(result["f_res_ghz"] - TARGET_FREQUENCY_GHZ)
            objective = impedance_error(result["z_real"], result["z_imag"], 50.0)
            accepted = frequency_error <= FREQUENCY_TOLERANCE_GHZ
            reason = None if accepted else "impedance result rejected: resonance moved outside the +/-10 MHz frequency lock"
            record = {"stage": "B_impedance", "iteration": index + 1, "timestamp": self._timestamp(),
                "feed_offset_mm": offset, "radiator_length_mm": length,
                "resonance_GHz": result["f_res_ghz"], "frequency_error_MHz": frequency_error * 1e3,
                "S11_dB": result["s11_db"], "Zin_real_ohm": result["z_real"], "Zin_imag_ohm": result["z_imag"],
                "impedance_error_ohm": objective, "constraint_status": "FREQUENCY_LOCKED" if accepted else "REJECTED_FREQUENCY",
                "resonance_hz": result["f_res_ghz"] * 1e9, "frequency_error_hz": frequency_error * 1e9,
                "Re_Zin_ohm": result["z_real"], "Im_Zin_ohm": result["z_imag"], "VSWR": result["vswr"],
                "parameter_state": state["parameter_states"], "accepted": accepted, "rejection_reason": reason,
                "source": source, "CST_project": str(project_path), "CST_result_path": detail.get("raw_artifacts", {}).get("raw_results_path"),
                "cache_status": source, "simulation_id": simulation_id, "details": detail}
            state["history"].append(record)
            if accepted and (state["best_objective"] is None or objective < float(state["best_objective"])):
                state["best_objective"], state["best_parameter"] = objective, params
            state["iteration"], state["next_candidate_index"] = index + 1, index + 1
            self._checkpoint(state)
            if stop_after is not None and state["iteration"] >= stop_after:
                state["status"] = "interrupted"
                self._checkpoint(state)
                return state
        if not state["best_parameter"]:
            state["status"] = "failed_frequency_constraint"
            self._checkpoint(state)
            return state
        best = state["best_parameter"]
        final, final_detail = self._run_live(project_path, length, float(best["feed_offset_mm"]), "stage_b_final_validation")
        final_error = impedance_error(final["z_real"], final["z_imag"], 50.0)
        final_frequency_error = abs(final["f_res_ghz"] - TARGET_FREQUENCY_GHZ)
        state["final_snapshot"] = self._snapshot_project(project_path, "stage_b_final_project", best)
        baseline = next(record for record in state["history"] if record["feed_offset_mm"] == float(state["initial_parameters"]["feed_offset_mm"]))
        state["final_validation"] = {"result": final, "impedance_error_ohm": final_error, "frequency_error_hz": final_frequency_error * 1e9,
            "source": "CST_SIMULATION", "details": final_detail, "parameter_matches": final_detail["parameter_readback"] == best}
        state["acceptance"] = {"initial_impedance_error_ohm": baseline["impedance_error_ohm"], "final_impedance_error_ohm": final_error,
            "improved": final_error < baseline["impedance_error_ohm"], "frequency_locked": final_frequency_error <= FREQUENCY_TOLERANCE_GHZ,
            "radiator_length_confirmed_mm": self._com_call("read_parameter", Path(state["final_snapshot"]["snapshot_path"]), name="radiator_length_mm")}
        state["validation_matrix"] = {
            "stage_a_source": "PASS", "stage_a_reopen": "PASS", "radiator_length_frozen": "PASS",
            "every_candidate_real_cst": "PASS" if all(row["source"] == "CST_SIMULATION" for row in state["history"]) else "FAIL",
            "frequency_constraint": "PASS" if state["acceptance"]["frequency_locked"] else "FAIL",
            "impedance_improved": "PASS" if state["acceptance"]["improved"] else "FAIL",
            "final_saveas_reopen": "PASS" if state["final_snapshot"]["status"] == "VALID" else "FAIL",
        }
        state["status"] = "completed" if state["acceptance"]["improved"] and state["acceptance"]["frequency_locked"] else "failed_acceptance"
        self._write_json("simulation_history.json", {"provenance": "CST_SIMULATION", "records": state["history"]})
        self._write_json("validation_matrix.json", state["validation_matrix"])
        self._write_json("best_parameters.json", best)
        self._write_json("final_parameters.json", best)
        self._checkpoint(state)
        return state
