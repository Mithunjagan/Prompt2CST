import unittest

from prompt2cst.calculations import (
    airbox_recommendation,
    convert_units,
    dipole_initial_length,
    effective_dielectric_constant,
    free_space_wavelength,
    guided_wavelength,
    half_wave,
    mesh_resolution_recommendation,
    microstrip_impedance,
    microstrip_width,
    monopole_initial_length,
    patch_initial_dimensions,
    quarter_wave,
    substrate_length_correction,
)


class CalculationTests(unittest.TestCase):
    def test_wavelength_formulas(self):
        wavelength = free_space_wavelength(2.45)
        self.assertAlmostEqual(wavelength.output_value, 122.3642686, places=5)
        self.assertAlmostEqual(
            quarter_wave(2.45).output_value, wavelength.output_value / 4
        )
        self.assertAlmostEqual(
            half_wave(2.45).output_value, wavelength.output_value / 2
        )
        self.assertLess(
            guided_wavelength(2.45, 4).output_value, wavelength.output_value
        )

    def test_microstrip_width_and_impedance_are_consistent(self):
        width = microstrip_width(50, 4.3, 1.6)
        impedance = microstrip_impedance(width.output_value, 1.6, 4.3)
        self.assertAlmostEqual(impedance.output_value, 50, places=5)
        epsilon_eff = effective_dielectric_constant(4.3, width.output_value, 1.6)
        self.assertGreater(epsilon_eff.output_value, 1)
        self.assertLess(epsilon_eff.output_value, 4.3)

    def test_initial_dimensions_and_recommendations(self):
        patch = patch_initial_dimensions(2.45, 4.3, 1.6)
        self.assertGreater(patch["width"].output_value, patch["length"].output_value)
        self.assertGreater(monopole_initial_length(2.45).output_value, 0)
        self.assertGreater(
            dipole_initial_length(2.45).output_value,
            monopole_initial_length(2.45).output_value,
        )
        self.assertGreater(substrate_length_correction(1.6, 3.7, 38).output_value, 0)
        self.assertGreater(airbox_recommendation(2).output_value, 0)
        self.assertGreater(mesh_resolution_recommendation(3, 4.3, 20).output_value, 0)

    def test_unit_conversion_is_dimension_safe(self):
        self.assertEqual(convert_units(1, "m", "mm").output_value, 1000)
        self.assertEqual(convert_units(1, "GHz", "MHz").output_value, 1000)
        with self.assertRaises(ValueError):
            convert_units(1, "m", "GHz")


if __name__ == "__main__":
    unittest.main()
