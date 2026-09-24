from __future__ import annotations

import unittest

from prompt2cst.antenna_knowledge import family_evidence, load_antenna_knowledge_base
from prompt2cst.architect import AntennaTopology, RFArchitectureAgent
from prompt2cst.cli import main


class AntennaKnowledgeTests(unittest.TestCase):
    def test_catalogue_is_strict_and_covers_core_families(self) -> None:
        catalogue = load_antenna_knowledge_base()
        names = {family.family for family in catalogue.families}
        self.assertEqual(catalogue.schema_version, "1.0")
        self.assertGreaterEqual(len(names), 12)
        self.assertTrue(
            {
                "dipole",
                "monopole",
                "patch",
                "pifa",
                "loop",
                "slot",
                "helix",
                "horn",
                "yagi_uda",
                "vivaldi",
                "log_periodic",
                "spiral",
                "parabolic_reflector",
            }.issubset(names)
        )

    def test_alias_lookup_and_sources_are_resolved(self) -> None:
        catalogue = load_antenna_knowledge_base()
        family = catalogue.family("half-wave dipole")
        self.assertEqual(family.family, "dipole")
        self.assertTrue(catalogue.sources_for(family))
        self.assertTrue(all(rule.source_ids for rule in family.sizing_rules))

    def test_evidence_exposes_provenance_and_capability_status(self) -> None:
        evidence = family_evidence("vivaldi antenna")
        self.assertEqual(evidence["family"], "vivaldi")
        self.assertEqual(
            evidence["implementation_status"], "openems_generator_available"
        )
        self.assertTrue(evidence["sources"])
        self.assertTrue(
            all(str(source["url"]).startswith("https://") for source in evidence["sources"])
        )

    def test_architecture_output_carries_cited_knowledge(self) -> None:
        result = RFArchitectureAgent().full_evaluation(
            2.40, 2.50, topologies=[AntennaTopology.PATCH]
        )
        evidence = result["knowledge_evidence"]
        self.assertEqual(evidence["family"], "patch")
        self.assertEqual(evidence["implementation_status"], "cst_compiler_available")
        self.assertIn("patch_width", evidence["sizing_rule_ids"])

    def test_cli_can_query_alias(self) -> None:
        self.assertEqual(main(["antenna-knowledge", "--family", "yagi"]), 0)


if __name__ == "__main__":
    unittest.main()
