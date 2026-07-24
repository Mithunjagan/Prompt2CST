import os
import tempfile
import unittest
from unittest.mock import patch

from prompt2cst.adapters import monopole_to_design_ir
from prompt2cst.design import MonopoleInputs, calculate_wire_monopole
from prompt2cst.gui import Prompt2CSTController
from prompt2cst.plan_service import PlanService
from prompt2cst.workflow import WorkflowState


class ControllerStateTests(unittest.TestCase):
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
