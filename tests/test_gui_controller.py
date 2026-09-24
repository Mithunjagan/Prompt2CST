import os
import tempfile
import unittest
from unittest.mock import patch

from prompt2cst.adapters import monopole_to_design_ir
from prompt2cst.design import MonopoleInputs, calculate_wire_monopole

try:
    from prompt2cst.gui import LocalDesignWorker, Prompt2CSTController
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False

from prompt2cst.local_ai import LocalAIResult
from prompt2cst.plan_service import PlanService
from prompt2cst.workflow import WorkflowState


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class ControllerStateTests(unittest.TestCase):
    def test_local_worker_can_opt_into_guarded_ollama_check(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = LocalDesignWorker(
                "Design a PIFA at 868 MHz",
                os.path.join(directory, "project"),
                use_local_ai=True,
            )
            completed, failed = [], []
            worker.completed.connect(completed.append)
            worker.failed.connect(failed.append)
            with patch(
                "prompt2cst.autonomous.confirm_prompt_family",
                return_value=LocalAIResult("confirmed", "qwen3:0.6b", "pifa"),
            ):
                worker.run()
            self.assertEqual(failed, [])
            self.assertIn("Local AI family check", completed[0]["assistant_text"])
            self.assertIn("advisory only", completed[0]["assistant_text"])

    def test_local_worker_creates_zero_key_project(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = LocalDesignWorker(
                "Design a practical 2.45 GHz smart-glasses antenna",
                os.path.join(directory, "project"),
            )
            completed = []
            failed = []
            worker.completed.connect(completed.append)
            worker.failed.connect(failed.append)
            worker.run()
            self.assertEqual(failed, [])
            self.assertEqual(len(completed), 1)
            self.assertIn("Autonomous local design plan", completed[0]["assistant_text"])
            self.assertIn("No EM solver was run", completed[0]["assistant_text"])
            self.assertTrue(os.path.isfile(os.path.join(directory, "project", "state.db")))

    def test_local_worker_generates_openems_helix_project(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = LocalDesignWorker(
                "Design an axial-mode helix antenna at 2.45 GHz",
                os.path.join(directory, "project"),
                mode="openems",
            )
            completed = []
            failed = []
            worker.completed.connect(completed.append)
            worker.failed.connect(failed.append)
            worker.run()
            self.assertEqual(failed, [])
            self.assertEqual(len(completed), 1)
            self.assertIn("openEMS geometry", completed[0]["assistant_text"])
            self.assertTrue(
                os.path.isfile(
                    os.path.join(directory, "project", "openems", "run_openems.py")
                )
            )

    def test_local_worker_reports_actual_solver_status(self):
        frequencies = [2.2e9 + i * 1e6 for i in range(501)]
        solver_result = {
            "source": "OPENEMS_FDTD", "frequency_hz": frequencies,
            "s11_db": [-1.0] * 501, "z_real_ohm": [20.0] * 501,
            "z_imag_ohm": [100.0] * 501, "best_s11_db": -1.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            project = os.path.join(directory, "project")
            worker = LocalDesignWorker(
                "Design a 2.45 GHz PIFA with S11 < -10 dB",
                project, mode="openems-simulate",
            )
            completed, failed = [], []
            worker.completed.connect(completed.append)
            worker.failed.connect(failed.append)
            with patch(
                "prompt2cst.autonomous.execute_project",
                return_value={"result": solver_result, "results": os.path.join(project, "openems", "results.json")},
            ), patch(
                "prompt2cst.autonomous.search_pifa",
                return_value={"real_runs_this_call": 0, "best": {"center_s11_db": -1.0}},
            ):
                worker.run()
            self.assertEqual(failed, [])
            self.assertIn("S11 threshold at this mesh: No", completed[0]["assistant_text"])
            self.assertIn("openEMS FDTD completed", completed[0]["assistant_text"])
            self.assertIn("Simulated port verdict: **FAIL**", completed[0]["assistant_text"])
            self.assertIn("Air-domain convergence: NOT_RUN", completed[0]["assistant_text"])

    def test_clear_invalidates_pending_preview_before_removing_session(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {"PROMPT2CST_STATE_DIR": directory},
                clear=False,
            ):
                controller = Prompt2CSTController()
                service = PlanService(directory)
                design = monopole_to_design_ir(
                    calculate_wire_monopole(MonopoleInputs())
                )
                preview = service.preview_design_plan(design)
                session = controller._swarm_sessions.create()
                session.preview = preview
                session.status = "COMPLETED"
                controller._swarm_sessions.save(session)

                controller.clearResults()

                workflow = service.workflows.load(preview["workflow_id"])
                self.assertEqual(workflow.state, WorkflowState.FAILED)
                self.assertEqual(controller._swarm_sessions.list_sessions(), [])

    def test_loading_history_emits_prompt_restore_data(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {"PROMPT2CST_STATE_DIR": directory},
                clear=False,
            ):
                controller = Prompt2CSTController()
                record = controller._history.create(
                    prompt="Design a dipole",
                    family_id="center_fed_dipole",
                    mode="preview",
                    phase="parameters",
                    role="parameters_model",
                    model="parameter-model",
                    activity_text="",
                )
                restored = []
                controller.promptRestored.connect(
                    lambda prompt, family, phase: restored.append(
                        (prompt, family, phase)
                    )
                )

                controller.loadHistoryEntry(record.id)

                self.assertEqual(
                    restored,
                    [("Design a dipole", "center_fed_dipole", "parameters")],
                )


if __name__ == "__main__":
    unittest.main()
