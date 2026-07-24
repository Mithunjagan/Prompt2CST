import json
import tempfile
import unittest
from pathlib import Path

from prompt2cst.adapters import monopole_to_design_ir
from prompt2cst.design import MonopoleInputs, calculate_wire_monopole
from prompt2cst.plan_service import PlanService


class FakeBridge:
    calls = []

    def execute_compiled_design(
        self,
        compiled,
        project_name,
        overwrite=False,
        on_completed=None,
        is_cancelled=None,
    ):
        self.calls.append((compiled, project_name, overwrite))
        completed = []
        for operation in compiled.operations:
            item = {
                "index": operation.index,
                "operation_id": operation.operation_id,
                "label": operation.label,
            }
            completed.append(item)
            if on_completed:
                on_completed(item)
        return {
            "status": "completed",
            "write_performed": True,
            "project_path": f"C:/fake/{project_name}.cst",
            "completed_operations": completed,
            "solver_run": False,
        }


class PlanServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        FakeBridge.calls.clear()
        self.service = PlanService(self.temp.name, bridge_factory=FakeBridge)
        self.design = monopole_to_design_ir(calculate_wire_monopole(MonopoleInputs()))

    def tearDown(self):
        self.temp.cleanup()

    def test_preview_is_batched_and_immutable(self):
        preview = self.service.preview_design_plan(self.design)
        self.assertTrue(preview["approval_allowed"])
        self.assertEqual(preview["machine_preview"]["tool_call_count"], 1)
        self.assertGreater(preview["machine_preview"]["estimated_operation_count"], 0)
        plan_path = Path(self.temp.name) / "plans" / f"{preview['plan_id']}.json"
        self.assertTrue(plan_path.is_file())

    def test_approval_hash_prevents_modified_execution(self):
        preview = self.service.preview_design_plan(self.design)
        with self.assertRaises(PermissionError):
            self.service.execute_approved_plan(
                preview["plan_id"],
                "0" * 64,
                approved=True,
            )
        self.assertFalse(FakeBridge.calls)

    def test_stored_plan_tampering_is_detected(self):
        preview = self.service.preview_design_plan(self.design)
        plan_path = Path(self.temp.name) / "plans" / f"{preview['plan_id']}.json"
        payload = json.loads(plan_path.read_text())
        payload["design_ir"]["project"]["name"] = "Tampered"
        plan_path.write_text(json.dumps(payload))
        with self.assertRaises(PermissionError):
            self.service.get_design_plan(preview["plan_id"])

    def test_approved_plan_executes_exact_compiled_sequence(self):
        preview = self.service.preview_design_plan(self.design)
        result = self.service.execute_approved_plan(
            preview["plan_id"],
            preview["approval_hash"],
            approved=True,
            project_name="approved_monopole",
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(FakeBridge.calls), 1)
        status = self.service.get_execution_status(result["execution_id"])
        self.assertEqual(status["status"], "COMPLETED")
        self.assertEqual(
            len(status["completed_operations"]),
            preview["machine_preview"]["estimated_operation_count"],
        )

    def test_result_extraction_never_invents_values(self):
        preview = self.service.preview_design_plan(self.design)
        result = self.service.execute_approved_plan(
            preview["plan_id"], preview["approval_hash"], approved=True
        )
        extracted = self.service.extract_simulation_results(result["execution_id"])
        self.assertEqual(extracted["status"], "unavailable")
        self.assertEqual(extracted["values"], [])
        self.assertIn("s_parameters", extracted["missing_requested_outputs"])


if __name__ == "__main__":
    unittest.main()
