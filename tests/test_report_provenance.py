import unittest

from prompt2cst.reports import generate_optimization_report
from prompt2cst.wearable import WearableAntennaEvaluator


class ReportProvenanceTests(unittest.TestCase):
    def test_mock_and_sar_outputs_are_labeled_without_compliance_claim(self):
        report = generate_optimization_report(
            project_name="audit",
            topology_name="dipole",
            requirements={"center_frequency_hz": 2.45e9},
            initial_params={"length_mm": 30.0},
            optimized_params={"length_mm": 29.0},
            history_records=[{"iteration": 0, "results": {}, "cost": 1.0}],
            wearable_summary=WearableAntennaEvaluator().evaluate_sar(),
        )

        self.assertIn("`MOCK_SIMULATION`", report)
        self.assertIn("`ASSUMED`/`CALCULATED`", report)
        self.assertIn("NOT A COMPLIANCE DETERMINATION", report)
        self.assertNotIn("FCC Compliance", report)


if __name__ == "__main__":
    unittest.main()
