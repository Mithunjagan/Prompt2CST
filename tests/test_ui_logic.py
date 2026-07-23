import unittest

from prompt2cst.ui_logic import compose_user_request


class UILogicTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
