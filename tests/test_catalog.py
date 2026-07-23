import unittest

from prompt2cst.catalog import capability_catalog


class CatalogTests(unittest.TestCase):
    def test_catalog_is_honest_about_supported_families(self):
        catalog = capability_catalog()
        family_ids = {
            family["id"]
            for family in catalog["families"]
        }

        self.assertIn("wire_monopole", family_ids)
        self.assertIn("center_fed_dipole", family_ids)
        self.assertIn("rectangular_patch", family_ids)
        self.assertIn("custom_parametric", family_ids)
        self.assertIn(
            "solver execution and automatic result extraction",
            catalog["unsupported_capabilities"],
        )
        self.assertFalse(catalog["solver_run"])


if __name__ == "__main__":
    unittest.main()
