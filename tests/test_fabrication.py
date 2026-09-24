"""PIFA fabrication proposals must remain tied to the simulated geometry."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from prompt2cst.fabrication import write_pifa_fabrication_proposal
from prompt2cst.openems_backend import Port, build_project, pifa_dimensions


class PIFAFabricationTests(unittest.TestCase):
    def test_proposal_matches_exact_plan_and_discloses_model_limits(self):
        project = build_project(
            "pifa", 868e6, pifa_length_scale=1.4365,
            pifa_feed_fraction=0.10, mesh_refinement_factor=2.9296875,
        )
        with tempfile.TemporaryDirectory() as temp:
            artifacts = write_pifa_fabrication_proposal(project, temp)
            manifest = json.loads(Path(artifacts["fabrication_proposal"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["project_sha256"], project.canonical_sha256)
            self.assertEqual(manifest["dimensions_mm"], pifa_dimensions(project))
            self.assertEqual(manifest["feed_xyz_mm"], list(project.port.start))
            self.assertEqual(manifest["status"], "GEOMETRY_PROPOSAL_NOT_FABRICATION_VALIDATED")
            self.assertIn("not modeled", Path(artifacts["fabrication_bom"]).read_text(encoding="utf-8"))
            for key in ("fabrication_top_view", "fabrication_side_view"):
                drawing = Path(artifacts[key])
                self.assertIn("mm", drawing.read_text(encoding="utf-8"))
                self.assertEqual(ElementTree.parse(drawing).getroot().tag,
                                 "{http://www.w3.org/2000/svg}svg")
            first_bytes = {key: Path(path).read_bytes() for key, path in artifacts.items()}
            regenerated = write_pifa_fabrication_proposal(project, temp)
            self.assertEqual(first_bytes, {
                key: Path(path).read_bytes() for key, path in regenerated.items()
            })

    def test_rejects_feed_outside_radiator_footprint(self):
        project = build_project("pifa", 868e6)
        outside = project.model_copy(update={
            "port": Port(kind="lumped", start=(500, 0, 0), stop=(500, 0, 10), direction="z")
        })
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "within the radiator"):
                write_pifa_fabrication_proposal(outside, temp)


if __name__ == "__main__":
    unittest.main()
