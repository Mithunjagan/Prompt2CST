import io
import unittest
from contextlib import redirect_stdout
from subprocess import CompletedProcess
from unittest.mock import patch

from prompt2cst.cli import main
from prompt2cst.readiness import format_readiness, readiness_report


def _solver(available):
    return {
        "available": available,
        "executable": "/opt/openEMS/bin/openEMS" if available else None,
        "python_modules": {"openEMS": available, "CSXCAD": available},
    }


class ReadinessTests(unittest.TestCase):
    def test_missing_solver_keeps_planning_available(self):
        with patch("prompt2cst.readiness.backend_status", return_value=_solver(False)), patch(
            "prompt2cst.readiness.subprocess.run"
        ) as probe, patch("prompt2cst.readiness.platform.system", return_value="Linux"), patch(
            "prompt2cst.readiness.CSTBridge"
        ) as bridge:
            report = readiness_report()
        probe.assert_not_called()
        bridge.assert_not_called()
        self.assertTrue(report["modes"]["plan"])
        self.assertTrue(report["modes"]["openems_generate"])
        self.assertFalse(report["modes"]["openems_simulate"])
        self.assertEqual(report["cst"]["status"], "UNAVAILABLE")
        self.assertIn("Windows", format_readiness(report))

    def test_installed_but_unimportable_bindings_are_not_ready(self):
        with patch("prompt2cst.readiness.backend_status", return_value=_solver(True)), patch(
            "prompt2cst.readiness.subprocess.run",
            return_value=CompletedProcess([], 1),
        ), patch("prompt2cst.readiness.platform.system", return_value="Linux"):
            report = readiness_report()
        self.assertFalse(report["modes"]["openems_simulate"])
        self.assertIn("cannot be imported", report["openems"]["issue"])

    def test_backend_discovery_exception_is_reported_not_crashed(self):
        with patch("prompt2cst.readiness.backend_status", side_effect=ValueError("bad")), patch(
            "prompt2cst.readiness.platform.system", return_value="Linux"
        ):
            report = readiness_report()
        self.assertFalse(report["modes"]["openems_simulate"])
        self.assertIn("Solver discovery failed", report["openems"]["issue"])

    def test_macos_is_named_for_users_without_claiming_cst(self):
        with patch("prompt2cst.readiness.backend_status", return_value=_solver(False)), patch(
            "prompt2cst.readiness.platform.system", return_value="Darwin"
        ):
            report = readiness_report()
        self.assertEqual(report["platform"], "macOS")
        self.assertEqual(report["cst"]["status"], "UNAVAILABLE")

    def test_importable_solver_is_ready_without_claiming_cst_connection(self):
        with patch("prompt2cst.readiness.backend_status", return_value=_solver(True)), patch(
            "prompt2cst.readiness.subprocess.run",
            return_value=CompletedProcess([], 0),
        ), patch("prompt2cst.readiness.platform.system", return_value="Windows"), patch(
            "prompt2cst.readiness.CSTBridge"
        ) as bridge:
            bridge.return_value.status.return_value = {"registered": True}
            report = readiness_report()
        self.assertTrue(report["modes"]["openems_simulate"])
        self.assertEqual(report["cst"]["status"], "REGISTERED")
        bridge.return_value.status.assert_called_once_with(test_connection=False)
        self.assertFalse(report["cst"]["connection_tested"])

    def test_doctor_cli_supports_human_and_json_output(self):
        with patch("prompt2cst.cli.readiness_report", return_value={"modes": {"plan": True}}), patch(
            "prompt2cst.cli.format_readiness", return_value="Local planning: READY"
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["doctor"])
            self.assertEqual(code, 0)
            self.assertIn("Local planning: READY", output.getvalue())
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["doctor", "--json"])
            self.assertEqual(code, 0)
            self.assertIn('"plan": true', output.getvalue())


if __name__ == "__main__":
    unittest.main()
