import tempfile
import unittest

from prompt2cst.adapters import monopole_to_design_ir
from prompt2cst.design import MonopoleInputs, calculate_wire_monopole
from prompt2cst.orchestration import MockProvider, ModelRole, ProviderRouter, RoleConfig
from prompt2cst.plan_service import PlanService
from prompt2cst.swarm import SwarmCoordinator, SwarmPhase, SwarmSessionStore


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


def specialist_responses():
    design = monopole_to_design_ir(calculate_wire_monopole(MonopoleInputs()))
    return [
        {
            "design_goal": "A 2.45 GHz wire monopole",
            "topology": "wire monopole",
            "center_frequency_ghz": 2.45,
            "sweep_start_ghz": 2.0,
            "sweep_stop_ghz": 3.0,
            "feed_impedance_ohm": 50,
            "requested_outputs": ["s_parameters", "farfield"],
            "constraints": [],
            "assumptions": [],
            "missing_information": [],
        },
        {
            "topology_rationale": "A quarter-wave monopole matches the request.",
            "formula_ids": [
                "c_over_f",
                "quarter_wave_monopole",
                "airbox_lambda_fraction",
            ],
            "assumptions": ["Free-space first-pass estimate."],
            "engineering_risks": [],
        },
        {
            "parameters": [
                {
                    "name": "frequency_ghz",
                    "value": 2.45,
                    "unit": "GHz",
                    "minimum": 2.0,
                    "maximum": 3.0,
                    "rationale": "Requested center frequency.",
                    "source": "requirement",
                }
            ],
            "material_choices": ["PEC"],
            "unresolved_items": [],
        },
        {
            "design_ir": design.model_dump(mode="json"),
            "modeling_notes": ["Wire, ground and discrete port are named."],
        },
        {
            "boundary": {
                "xmin": "expanded_open",
                "xmax": "expanded_open",
                "ymin": "expanded_open",
                "ymax": "expanded_open",
                "zmin": "expanded_open",
                "zmax": "expanded_open",
                "airbox_distance": 30,
            },
            "solver": {
                "type": "time_domain",
                "frequency_min": 2.0,
                "frequency_max": 3.0,
            },
            "mesh": {
                "lines_per_wavelength": 20,
                "local_refinements": [],
            },
            "monitors": [
                {
                    "id": "ff245",
                    "type": "farfield",
                    "frequency": 2.45,
                }
            ],
            "parameter_sweeps": [],
            "optimization_goals": [],
            "requested_outputs": ["s_parameters", "farfield"],
            "planning_notes": ["No solver run during preview."],
        },
        {
            "summary": "The deterministic validator accepts the plan.",
            "findings": [],
            "recommendations": [],
            "verdict": "ready",
        },
    ]


def role_configs():
    return {
        role: RoleConfig(
            role=role,
            provider="mock",
            model=f"{role.value}-primary",
            fallback_models=(f"{role.value}-fallback",),
        )
        for role in ModelRole
    }


class SwarmCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        FakeBridge.calls.clear()
        self.provider = MockProvider(specialist_responses())
        self.router = ProviderRouter({"mock": self.provider}, role_configs())
        self.plan_service = PlanService(self.temp.name, bridge_factory=FakeBridge)
        self.sessions = SwarmSessionStore(self.temp.name)
        self.coordinator = SwarmCoordinator(
            self.router,
            plan_service=self.plan_service,
            session_store=self.sessions,
        )

    def tearDown(self):
        self.temp.cleanup()

    async def test_preview_runs_typed_specialists_in_order(self):
        result = await self.coordinator.run(
            prompt="Design a 2.45 GHz wire monopole.",
            target_phase=SwarmPhase.PREVIEW,
        )

        self.assertFalse(result.write_performed)
        self.assertFalse(FakeBridge.calls)
        self.assertEqual(
            [call["role"] for call in self.provider.calls],
            [
                ModelRole.REQUIREMENTS,
                ModelRole.CALCULATIONS,
                ModelRole.PARAMETERS,
                ModelRole.GEOMETRY,
                ModelRole.SIMULATION,
                ModelRole.CRITIC,
            ],
        )
        session = self.sessions.load(result.session_id)
        self.assertEqual(session.last_phase, SwarmPhase.PREVIEW)
        self.assertGreaterEqual(len(session.calculations), 4)
        self.assertTrue(session.preview["approval_allowed"])
        self.assertEqual(len(session.model_activity), 6)
        self.assertIn("frequency_ghz", session.design_ir["parameters"])
        self.assertEqual(
            session.design_ir["project"]["requested_topology"],
            "wire monopole",
        )
        self.assertEqual(
            [message.role for message in session.messages],
            ["user", "assistant"],
        )
        self.assertIn("Immutable CST preview", result.assistant_text)
        self.assertEqual(
            len(session.preview["machine_preview"]["models_used"]),
            6,
        )

    async def test_same_request_resumes_from_last_completed_phase(self):
        prompt = "Design a 2.45 GHz wire monopole."
        first = await self.coordinator.run(
            prompt=prompt,
            target_phase="requirements",
        )
        second = await self.coordinator.run(
            prompt=prompt,
            target_phase="calculations",
            session_id=first.session_id,
        )

        session = self.sessions.load(second.session_id)
        self.assertEqual(session.revision, 1)
        self.assertEqual(
            [call["role"] for call in self.provider.calls],
            [ModelRole.REQUIREMENTS, ModelRole.CALCULATIONS],
        )
        self.assertEqual(session.last_phase, SwarmPhase.CALCULATIONS)

    async def test_unresolved_handoff_blocks_approval(self):
        responses = specialist_responses()
        responses[0]["missing_information"] = ["ground-plane size"]
        responses[-1]["verdict"] = "revise"
        self.provider.responses = responses

        result = await self.coordinator.run(
            prompt="Design an underspecified monopole.",
            target_phase="preview",
        )

        session = self.sessions.load(result.session_id)
        self.assertFalse(session.preview["approval_allowed"])
        self.assertTrue(session.preview["validation"]["blocking"])
        self.assertTrue(
            any(
                item["category"] == "orchestration"
                for item in session.preview["validation"]["findings"]
            )
        )

    async def test_new_prompt_invalidates_downstream_preview(self):
        preview = await self.coordinator.run(
            prompt="Design a 2.45 GHz wire monopole.",
            target_phase="preview",
        )
        self.provider.responses = specialist_responses()[:1]

        requirements = await self.coordinator.run(
            prompt="Keep it at 2.45 GHz but review requirements.",
            target_phase="requirements",
            session_id=preview.session_id,
        )

        session = self.sessions.load(requirements.session_id)
        self.assertEqual(session.revision, 2)
        self.assertIsNone(session.preview)
        self.assertIsNone(session.design_ir)
        self.assertEqual(session.last_phase, SwarmPhase.REQUIREMENTS)
        latest_requirement_call = self.provider.calls[-1]
        self.assertIn(
            "assistant",
            [message["role"] for message in latest_requirement_call["messages"]],
        )
        with self.assertRaisesRegex(ValueError, "not awaiting approval"):
            self.plan_service.execute_approved_plan(
                preview_id := self._preview_plan_id(preview.session_id),
                self.plan_service.get_design_plan(preview_id)["approval_hash"],
                approved=True,
            )

    async def test_build_executes_exact_preview_without_another_model_call(self):
        preview = await self.coordinator.run(
            prompt="Design a 2.45 GHz wire monopole.",
            target_phase="preview",
        )
        model_call_count = len(self.provider.calls)
        approvals = []

        def approve(tool_name, arguments, stored_preview):
            approvals.append((tool_name, arguments, stored_preview))
            return True

        result = await self.coordinator.run(
            prompt="",
            target_phase="build",
            session_id=preview.session_id,
            approve_build=approve,
        )

        self.assertTrue(result.write_performed)
        self.assertEqual(len(self.provider.calls), model_call_count)
        self.assertEqual(len(FakeBridge.calls), 1)
        session = self.sessions.load(preview.session_id)
        self.assertEqual(
            approvals[0][1]["plan_id"],
            session.preview["plan_id"],
        )
        self.assertEqual(
            approvals[0][1]["approval_hash"],
            session.preview["approval_hash"],
        )

    async def test_denied_build_preserves_preview_and_performs_no_write(self):
        preview = await self.coordinator.run(
            prompt="Design a 2.45 GHz wire monopole.",
            target_phase="preview",
        )

        result = await self.coordinator.run(
            prompt="",
            target_phase="build",
            session_id=preview.session_id,
            approve_build=lambda *_args: False,
        )

        self.assertEqual(result.status, "APPROVAL_DENIED")
        self.assertFalse(result.write_performed)
        self.assertFalse(FakeBridge.calls)
        self.assertIsNotNone(self.sessions.load(preview.session_id).preview)

    def _preview_plan_id(self, session_id):
        session_files = self.plan_service.plan_root.glob("*.json")
        plans = list(session_files)
        self.assertEqual(len(plans), 1)
        return plans[0].stem


class SwarmSessionStoreTests(unittest.TestCase):
    def test_session_is_persistent_until_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SwarmSessionStore(directory)
            created = store.create()

            self.assertEqual(
                SwarmSessionStore(directory).load(created.id).id, created.id
            )
            self.assertEqual(store.latest_id(), created.id)

            store.clear()

            self.assertEqual(store.latest_id(), "")


if __name__ == "__main__":
    unittest.main()
