import unittest

from prompt2cst.ui_logic import (
    compose_swarm_request,
    compose_user_request,
    role_for_phase,
)


class UILogicTests(unittest.TestCase):
    def test_swarm_request_is_stable_across_execution_phases(self):
        self.assertEqual(
            compose_swarm_request("Design a dipole", "center_fed_dipole"),
            ("Design a dipole\n\nRequested antenna family: center_fed_dipole."),
        )

    def test_preview_mode_forces_non_writing_request(self):
        result = compose_user_request(
            "Design a dipole",
            "center_fed_dipole",
            "preview",
        )

        self.assertIn(
            "Requested antenna family: center_fed_dipole.",
            result,
        )
        self.assertIn("Preview only.", result)
        self.assertIn("Do not build", result)

    def test_build_mode_preserves_confirmation_boundary(self):
        result = compose_user_request(
            "Design a dipole",
            "center_fed_dipole",
            "build",
        )

        self.assertIn("Build the validated preview in CST.", result)
        self.assertIn("interactive approval", result)
        self.assertIn("Do not run a solver", result)

    def test_empty_request_is_rejected(self):
        with self.assertRaises(ValueError):
            compose_user_request("", "auto", "preview")

    def test_phase_instruction_is_included(self):
        result = compose_user_request(
            "Design a patch",
            "rectangular_patch",
            "preview",
            "calculations",
        )

        self.assertIn("Run only the calculations phase.", result)
        self.assertIn("Do not build or write to CST.", result)

    def test_build_mode_forces_build_phase(self):
        result = compose_user_request(
            "Build the last preview",
            "wire_monopole",
            "build",
            "calculations",
        )

        self.assertIn("Run the build phase", result)
        self.assertNotIn("Run only the calculations phase.", result)

    def test_phase_maps_to_model_role(self):
        self.assertEqual(role_for_phase("calculations"), "calculations_model")
        self.assertEqual(role_for_phase("parameters"), "parameters_model")
        self.assertEqual(role_for_phase("modeling"), "geometry_model")
        self.assertEqual(role_for_phase("simulation"), "simulation_model")
        self.assertEqual(role_for_phase("preview"), "swarm_coordinator")


if __name__ == "__main__":
    unittest.main()
