import unittest

from pydantic import ValidationError

from prompt2cst.cst_macros import complete_parametric_preview
from prompt2cst.parametric import ParametricAntennaSpec


def simple_spec() -> dict:
    return {
        "title": "Safe primitive test",
        "frequency_ghz": 2.45,
        "sweep_start_ghz": 2.0,
        "sweep_stop_ghz": 3.0,
        "materials": [
            {
                "name": "Substrate",
                "relative_permittivity": 4.3,
                "loss_tangent": 0.02,
            }
        ],
        "solids": [
            {
                "kind": "brick",
                "name": "Ground",
                "material": "PEC",
                "x_min_mm": -10,
                "x_max_mm": 10,
                "y_min_mm": -10,
                "y_max_mm": 10,
                "z_min_mm": -0.1,
                "z_max_mm": 0,
            },
            {
                "kind": "cylinder",
                "name": "Radiator",
                "material": "PEC",
                "axis": "z",
                "outer_radius_mm": 0.5,
                "axis_min_mm": 1,
                "axis_max_mm": 30,
            },
        ],
        "ports": [
            {
                "number": 1,
                "label": "Feed",
                "impedance_ohm": 50,
                "p1_x_mm": 0,
                "p1_y_mm": 0,
                "p1_z_mm": 0,
                "p2_x_mm": 0,
                "p2_y_mm": 0,
                "p2_z_mm": 1,
            }
        ],
    }


class ParametricSafetyTests(unittest.TestCase):
    def test_valid_spec_generates_only_typed_history_blocks(self):
        spec = ParametricAntennaSpec.model_validate(simple_spec())
        preview = complete_parametric_preview(spec)
        combined = "\n".join(preview.values())

        self.assertIn('With Brick', combined)
        self.assertIn('With Cylinder', combined)
        self.assertIn('With DiscretePort', combined)
        self.assertIn('.Name "Substrate"', combined)
        self.assertNotIn("Solver.Start", combined)
        self.assertNotIn("Shell", combined)

    def test_unknown_material_is_rejected(self):
        payload = simple_spec()
        payload["solids"][0]["material"] = "Undefined"

        with self.assertRaises(ValidationError):
            ParametricAntennaSpec.model_validate(payload)

    def test_extra_fields_are_rejected(self):
        payload = simple_spec()
        payload["arbitrary_vba"] = "Solver.Start"

        with self.assertRaises(ValidationError):
            ParametricAntennaSpec.model_validate(payload)

    def test_degenerate_port_is_rejected(self):
        payload = simple_spec()
        payload["ports"][0]["p2_z_mm"] = 0

        with self.assertRaises(ValidationError):
            ParametricAntennaSpec.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
