import math
import unittest

from prompt2cst.design import (
    DipoleInputs,
    MonopoleInputs,
    PatchInputs,
    calculate_center_fed_dipole,
    calculate_rectangular_patch,
    calculate_wire_monopole,
)


class PatchDesignTests(unittest.TestCase):
    def test_default_245_ghz_fr4_dimensions(self):
        design = calculate_rectangular_patch(PatchInputs())

        self.assertTrue(
            math.isclose(design.patch_width_mm, 37.583886, abs_tol=1e-5)
        )
        self.assertTrue(
            math.isclose(design.patch_length_mm, 29.138326, abs_tol=1e-5)
        )
        self.assertTrue(
            math.isclose(design.feed_width_mm, 3.111843, abs_tol=1e-5)
        )
        self.assertGreater(design.inset_depth_mm, 0)
        self.assertLess(
            design.inset_depth_mm,
            design.patch_length_mm / 2,
        )

    def test_higher_frequency_reduces_patch_size(self):
        low = calculate_rectangular_patch(PatchInputs(frequency_ghz=2.45))
        high = calculate_rectangular_patch(PatchInputs(frequency_ghz=5.8))

        self.assertLess(high.patch_width_mm, low.patch_width_mm)
        self.assertLess(high.patch_length_mm, low.patch_length_mm)

    def test_invalid_relative_permittivity_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_rectangular_patch(
                PatchInputs(relative_permittivity=1.0)
            )


class MonopoleDesignTests(unittest.TestCase):
    def test_default_monopole_coordinates(self):
        design = calculate_wire_monopole(MonopoleInputs())

        self.assertEqual(design.ground_xmin_mm, -30.6)
        self.assertEqual(design.ground_xmax_mm, 30.6)
        self.assertEqual(design.ground_zmin_mm, -0.5)
        self.assertEqual(design.ground_zmax_mm, 0.0)
        self.assertEqual(design.monopole_zmin_mm, 1.5)
        self.assertEqual(design.monopole_zmax_mm, 32.1)
        self.assertTrue(
            math.isclose(design.quarter_wavelength_mm, 30.590, abs_tol=0.01)
        )

    def test_monopole_frequency_must_be_inside_sweep(self):
        with self.assertRaises(ValueError):
            calculate_wire_monopole(
                MonopoleInputs(
                    frequency_ghz=5.8,
                    sweep_start_ghz=2.0,
                    sweep_stop_ghz=3.0,
                )
            )


class DipoleDesignTests(unittest.TestCase):
    def test_default_dipole_has_equal_arms_and_center_gap(self):
        design = calculate_center_fed_dipole(DipoleInputs())

        self.assertEqual(design.lower_zmin_mm, -31.35)
        self.assertEqual(design.lower_zmax_mm, -0.75)
        self.assertEqual(design.upper_zmin_mm, 0.75)
        self.assertEqual(design.upper_zmax_mm, 31.35)
        self.assertTrue(
            math.isclose(design.half_wavelength_mm, 61.182, abs_tol=0.01)
        )

    def test_dipole_frequency_must_be_inside_sweep(self):
        with self.assertRaises(ValueError):
            calculate_center_fed_dipole(
                DipoleInputs(
                    frequency_ghz=5.8,
                    sweep_start_ghz=2.0,
                    sweep_stop_ghz=3.0,
                )
            )


if __name__ == "__main__":
    unittest.main()
