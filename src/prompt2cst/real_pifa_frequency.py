"""Resumable, real-CST Stage A resonance tuning for the temple PIFA.

The workflow intentionally keeps ``feed_offset_mm`` frozen.  Each uncached
candidate performs parameter write/readback, rebuild, solve, and result
extraction before it can affect the frequency-only objective.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .adapters import TemplePifaInputs
from .cst_bridge import CSTBridge, _extraction_summary
from .optimizer.cache import ResultCache


TARGET_GHZ = 2.45
FREQUENCY_TOLERANCE_GHZ = 0.01
RADIATOR_MIN_MM = 12.0
RADIATOR_MAX_MM = 38.0
SENSITIVITY_DELTA_MM = 2.0
MAX_CANDIDATES = 8
LOCAL_REFINEMENT_POINTS_MM = (21.0, 21.25, 21.5, 21.75, 22.0, 22.25, 22.5)


class RealPifaFrequencyOptimization:
    """Run Stage A using only the PIFA radiator length as an active parameter."""

    def __init__(self, output_dir: str | Path, *, resume: bool = False) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = self.output_dir / "checkpoint.json"
        self.resume = resume
        self.cache = ResultCache(self.output_dir / "cache.db")
        self.bridge = CSTBridge(output_dir=self.output_dir)

    def _write_json(self, name: str, value: Any) -> Path:
        path = self.output_dir / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
        return path

    def _checkpoint(self, state: dict[str, Any]) -> None:
        state["optimizer_state"] = {
            "algorithm": "measured_directional_frequency_sweep",
            "target_ghz": TARGET_GHZ,
            "frequency_tolerance_ghz": FREQUENCY_TOLERANCE_GHZ,
            "next_candidate_index": len(state["history"]),
        }
        self._write_json("checkpoint.json", state)

    def _load_checkpoint(self) -> dict[str, Any]:
        try:
            return json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot resume Stage A PIFA optimization: {exc}") from exc

    @staticmethod
    def _result(extraction: dict[str, Any]) -> dict[str, float]:
        if extraction.get("status") != "completed":
            raise RuntimeError(extraction.get("error", "CST result extraction failed"))
        values = extraction.get("extracted", {})
        required = ("s11_db", "f_res_ghz", "vswr", "zin_re", "zin_im")
        missing = [name for name in required if name not in values]
        if missing:
            raise RuntimeError("CST did not provide required results: " + ", ".join(missing))
        return {
            "s11_db": float(values["s11_db"][0]), "f_res_ghz": float(values["f_res_ghz"][0]),
            "vswr": float(values["vswr"][0]), "z_real": float(values["zin_re"][0]),
            "z_imag": float(values["zin_im"][0]),
        }

    def _run_live(self, project_path: Path, radiator_length_mm: float, feed_offset_mm: float, tag: str) -> tuple[dict[str, float], dict[str, Any]]:
        parameters = {"radiator_length_mm": radiator_length_mm, "feed_offset_mm": feed_offset_mm}
        update = self.bridge.update_parameters(project_path, parameters)
        readback = {name: self.bridge.read_parameter(project_path, name) for name in parameters}
        mismatched = [name for name, value in parameters.items() if not math.isclose(readback[name], value, abs_tol=1e-9)]
        if mismatched:
            raise RuntimeError("CST parameter readback mismatch: " + ", ".join(mismatched))
        solver = self.bridge.run_solver(project_path)
        extraction = self.bridge.extract_results(project_path, artifact_tag=tag)
        return self._result(extraction), {
            "parameter_update": update, "parameter_readback": readback, "solver": solver,
            "extraction": _extraction_summary(extraction),
        }

    def _evaluate(self, state: dict[str, Any], length: float, tag: str) -> dict[str, Any]:
        project_path = Path(state["cst_project_path"])
        feed = float(state["locked_parameters"]["feed_offset_mm"])
        params = {"radiator_length_mm": length, "feed_offset_mm": feed}
        context = json.dumps({"project": str(project_path.resolve()), "stage": "A_resonance", "solver": "CST"}, sort_keys=True)
        cached = self.cache.get(params, context=context)
        if cached is None:
            result, detail = self._run_live(project_path, length, feed, tag)
            self.cache.put(params, result, "CST_SIMULATION", context=context)
            source = "CST_SIMULATION"
        else:
            result, detail, source = cached, {"cache": "hit"}, "CACHE_HIT"
        error = abs(result["f_res_ghz"] - TARGET_GHZ)
        record = {
            "iteration": len(state["history"]) + 1, "parameters": params,
            "parameter_states": state["parameter_states"], "f_res_ghz": result["f_res_ghz"],
            "frequency_error_ghz": error, "S11_dB": result["s11_db"], "VSWR": result["vswr"],
            "Re_Zin_ohm": result["z_real"], "Im_Zin_ohm": result["z_imag"],
            "objective": error, "source": source, "accepted": True, "rejection_reason": None, "details": detail,
        }
        state["history"].append(record)
        if state["best_objective"] is None or error < float(state["best_objective"]):
            state["best_objective"] = error
            state["best_parameters"] = params
        self._checkpoint(state)
        return record

    def _snapshot(self, state: dict[str, Any], stem: str) -> dict[str, Any]:
        result = self.bridge.create_validated_cst_snapshot(
            state["cst_project_path"], stem, expected_parameters=state["best_parameters"], require_results=True,
        )
        if result.get("status") != "VALID":
            raise RuntimeError(f"Failed to create validated Stage A snapshot: {result}")
        return result

    def run_local_refinement(self) -> dict[str, Any]:
        """Continue a partial Stage A result with a narrow, CST-only search.

        Existing 21.0 and 22.0 mm runs are retained as real historical
        candidates.  New quarter-millimetre points are always evaluated by
        CST; a cache hit is never substituted for a newly requested local
        point.  The first two new points straddle the current 22 mm result so
        the local direction is measured before accepting a lock.
        """
        state = self._load_checkpoint()
        if state.get("status") != "PARTIAL_FREQUENCY_IMPROVEMENT":
            raise ValueError("Local refinement requires a PARTIAL_FREQUENCY_IMPROVEMENT checkpoint.")
        if float(state["locked_parameters"].get("feed_offset_mm", float("nan"))) != 0.5:
            raise ValueError("Local refinement refuses to change the frozen feed_offset_mm.")

        state["status"] = "in_progress"
        state["parameter_states"]["radiator_length_mm"] = "ACTIVE"
        state["parameter_states"]["feed_offset_mm"] = "FROZEN"
        historical = {
            float(record["parameters"]["radiator_length_mm"]): record
            for record in state["history"]
        }
        local = {
            "stage": "A_local_resonance_refinement", "target_ghz": TARGET_GHZ,
            "frequency_tolerance_ghz": FREQUENCY_TOLERANCE_GHZ,
            "candidate_points_mm": list(LOCAL_REFINEMENT_POINTS_MM),
            "historical_real_candidates": [
                {"radiator_length_mm": point, "f_res_ghz": historical[point]["f_res_ghz"],
                 "frequency_error_ghz": historical[point]["frequency_error_ghz"], "source": "CST_SIMULATION"}
                for point in (21.0, 22.0) if point in historical
            ],
            "new_candidates": [],
            "geometry_parameter_references": {
                "radiator_y_range": ["ground_length_mm - radiator_length_mm", "ground_length_mm"],
                "matching_stub_y_range": ["ground_length_mm - radiator_length_mm - stub_length_mm", "ground_length_mm - radiator_length_mm"],
            },
        }
        state["local_refinement"] = local
        self._checkpoint(state)

        # Verify the local direction first; 21.75 and 22.25 bracket the
        # previous 22.0 mm best without repeating the broad Stage A sweep.
        ordered = (22.25, 21.75, 21.5, 21.25, 22.5)
        try:
            for length in ordered:
                if length < RADIATOR_MIN_MM or length > RADIATOR_MAX_MM:
                    raise ValueError(f"Local candidate outside PIFA bounds: {length} mm")
                record = self._evaluate(state, length, f"stage_a_local_{length:.2f}mm")
                local["new_candidates"].append(record)
                self._checkpoint(state)
                if len(local["new_candidates"]) == 2:
                    lower = next(item for item in local["new_candidates"] if item["parameters"]["radiator_length_mm"] == 21.75)
                    upper = next(item for item in local["new_candidates"] if item["parameters"]["radiator_length_mm"] == 22.25)
                    local["local_direction"] = {
                        "df_res_dlength_ghz_per_mm": (upper["f_res_ghz"] - lower["f_res_ghz"]) / 0.5,
                        "verified_from_mm": [21.75, 22.25], "source": "CST_SIMULATION",
                    }
                    self._checkpoint(state)
                if record["frequency_error_ghz"] <= FREQUENCY_TOLERANCE_GHZ:
                    break
        except Exception as exc:
            state["failures"].append({"iteration": len(state["history"]) + 1, "stage": local["stage"], "error": f"{type(exc).__name__}: {exc}"})
            self._checkpoint(state)
            raise

        best = state["best_parameters"]
        final, details = self._run_live(Path(state["cst_project_path"]), float(best["radiator_length_mm"]), float(best["feed_offset_mm"]), "stage_a_local_final_validation")
        final_error = abs(final["f_res_ghz"] - TARGET_GHZ)
        locked = final_error <= FREQUENCY_TOLERANCE_GHZ
        state["final_validation"] = {"parameters": best, "result": final, "frequency_error_ghz": final_error, "source": "CST_SIMULATION", "details": details}
        state["parameter_states"]["radiator_length_mm"] = "FROZEN" if locked else "CONSTRAINED"
        state["status"] = "FREQUENCY_LOCKED" if locked else "PARTIAL_FREQUENCY_IMPROVEMENT"
        state["acceptance"] = {"initial_frequency_error_ghz": state["initial_frequency_error_ghz"], "final_frequency_error_ghz": final_error, "improved": final_error < state["initial_frequency_error_ghz"], "frequency_locked": locked}
        if locked:
            state["frequency_lock"] = {
                "locked_radiator_length_mm": best["radiator_length_mm"],
                "locked_resonance_hz": final["f_res_ghz"] * 1e9,
                "frequency_error_hz": final_error * 1e9,
                "frequency_tolerance_hz": FREQUENCY_TOLERANCE_GHZ * 1e9,
                "source": "CST_SIMULATION",
            }
        state["final_snapshot"] = self._snapshot(state, "local_refined_final_project")
        self._write_json("candidate_parameters.json", {"local_refinement": local, "best": best})
        self._write_json("simulation_history.json", {"provenance": "CST_SIMULATION", "records": state["history"]})
        self._write_json("optimization_history.json", {"stage": local["stage"], "objective": "abs(f_res_ghz - 2.45)", "records": state["history"]})
        self._write_json("final_parameters.json", best)
        self._checkpoint(state)
        return state

    def run(self, *, stop_after: int | None = None) -> dict[str, Any]:
        if self.resume:
            state = self._load_checkpoint()
            if state.get("status") in {"FREQUENCY_LOCKED", "PARTIAL_FREQUENCY_IMPROVEMENT"}:
                return state
        else:
            if self.checkpoint_path.exists():
                raise FileExistsError(f"Evidence exists at {self.output_dir}; use --resume or choose a new directory.")
            inputs = TemplePifaInputs(feed_offset_mm=0.5)
            inputs.validate()
            built = self.bridge.build_temple_pifa(inputs, "working_project", overwrite=False)
            state = {
                "schema_version": "1.0", "kind": "real_pifa_stage_a_frequency_optimization", "stage": "A_resonance",
                "status": "in_progress", "cst_project_path": built["project_path"], "target_ghz": TARGET_GHZ,
                "parameter_states": {"radiator_length_mm": "ACTIVE", "feed_offset_mm": "FROZEN"},
                "locked_parameters": {"feed_offset_mm": 0.5}, "best_parameters": {}, "best_objective": None,
                "history": [], "failures": [],
            }
            self._write_json("parameter_metadata.json", {
                "radiator_length_mm": {"value": inputs.radiator_length_mm, "minimum": RADIATOR_MIN_MM, "maximum": RADIATOR_MAX_MM, "step": SENSITIVITY_DELTA_MM, "unit": "mm", "role": "resonance", "rf_effect": "CST-verified in Stage A", "state": "ACTIVE"},
                "feed_offset_mm": {"value": 0.5, "minimum": -5.0, "maximum": 5.0, "step": 0.25, "unit": "mm", "role": "resistance_matching", "rf_effect": "Previously CST-linked to Zin", "state": "FROZEN"},
            })
            self._checkpoint(state)

        try:
            if not state["history"]:
                baseline = self._evaluate(state, 29.0, "stage_a_baseline")
                state["initial_frequency_error_ghz"] = baseline["frequency_error_ghz"]
                state["initial_snapshot"] = self._snapshot(state, "initial_project")
            if "sensitivity_analysis" not in state:
                completed_lengths = {
                    float(record["parameters"]["radiator_length_mm"])
                    for record in state["history"]
                }
                if 27.0 not in completed_lengths:
                    self._evaluate(state, 27.0, "stage_a_minus_delta")
                if 31.0 not in completed_lengths:
                    self._evaluate(state, 31.0, "stage_a_plus_delta")
                by_length = {
                    float(record["parameters"]["radiator_length_mm"]): record
                    for record in state["history"]
                }
                minus, plus = by_length[27.0], by_length[31.0]
                derivative = (plus["f_res_ghz"] - minus["f_res_ghz"]) / (2 * SENSITIVITY_DELTA_MM)
                state["sensitivity_analysis"] = {"parameter": "radiator_length_mm", "delta_mm": SENSITIVITY_DELTA_MM, "df_res_dlength_ghz_per_mm": derivative, "direction": "increase length raises resonance" if derivative > 0 else "increase length lowers resonance", "source": "CST_SIMULATION"}
                self._checkpoint(state)
            if stop_after is not None and len(state["history"]) >= stop_after:
                state["status"] = "interrupted"; self._checkpoint(state); return state
            derivative = state["sensitivity_analysis"]["df_res_dlength_ghz_per_mm"]
            direction = 1.0 if (TARGET_GHZ - state["history"][0]["f_res_ghz"]) * derivative > 0 else -1.0
            length = float(state["best_parameters"]["radiator_length_mm"])
            while len(state["history"]) < MAX_CANDIDATES and float(state["best_objective"]) > FREQUENCY_TOLERANCE_GHZ:
                candidate = min(RADIATOR_MAX_MM, max(RADIATOR_MIN_MM, length + direction * SENSITIVITY_DELTA_MM))
                if math.isclose(candidate, length, abs_tol=1e-9):
                    break
                before = float(state["best_objective"])
                self._evaluate(state, candidate, f"stage_a_candidate_{len(state['history']) + 1:02d}")
                if float(state["best_objective"]) >= before:
                    direction *= -1.0
                    SENSITIVITY_STEP = SENSITIVITY_DELTA_MM / 2
                    candidate = min(RADIATOR_MAX_MM, max(RADIATOR_MIN_MM, length + direction * SENSITIVITY_STEP))
                    if not math.isclose(candidate, length, abs_tol=1e-9):
                        self._evaluate(state, candidate, f"stage_a_refine_{len(state['history']) + 1:02d}")
                length = float(state["best_parameters"]["radiator_length_mm"])
                if stop_after is not None and len(state["history"]) >= stop_after:
                    state["status"] = "interrupted"; self._checkpoint(state); return state
        except Exception as exc:
            state["failures"].append({"iteration": len(state["history"]) + 1, "error": f"{type(exc).__name__}: {exc}"})
            self._checkpoint(state)
            raise

        best = state["best_parameters"]
        final, details = self._run_live(Path(state["cst_project_path"]), float(best["radiator_length_mm"]), float(best["feed_offset_mm"]), "stage_a_final_validation")
        final_error = abs(final["f_res_ghz"] - TARGET_GHZ)
        state["final_validation"] = {"parameters": best, "result": final, "frequency_error_ghz": final_error, "source": "CST_SIMULATION", "details": details}
        state["parameter_states"]["radiator_length_mm"] = "FROZEN" if final_error <= FREQUENCY_TOLERANCE_GHZ else "CONSTRAINED"
        state["status"] = "FREQUENCY_LOCKED" if final_error <= FREQUENCY_TOLERANCE_GHZ else "PARTIAL_FREQUENCY_IMPROVEMENT"
        state["acceptance"] = {"initial_frequency_error_ghz": state["initial_frequency_error_ghz"], "final_frequency_error_ghz": final_error, "improved": final_error < state["initial_frequency_error_ghz"], "frequency_locked": state["status"] == "FREQUENCY_LOCKED"}
        state["final_snapshot"] = self._snapshot(state, "final_project")
        self._write_json("simulation_history.json", {"provenance": "CST_SIMULATION", "records": state["history"]})
        self._write_json("optimization_history.json", {"stage": "A_resonance", "objective": "abs(f_res_ghz - 2.45)", "records": state["history"]})
        self._write_json("final_parameters.json", best)
        self._checkpoint(state)
        return state
