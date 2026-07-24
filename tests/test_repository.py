import re
import tomllib
import unittest
from pathlib import Path

from prompt2cst.cst_bridge import default_output_dir

ROOT = Path(__file__).resolve().parents[1]


class RepositoryReleaseTests(unittest.TestCase):
    def test_release_versions_match(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        init_text = (ROOT / "src/prompt2cst/__init__.py").read_text()
        declared = re.search(r'__version__ = "([^"]+)"', init_text)
        self.assertIsNotNone(declared)
        self.assertEqual(project["project"]["version"], declared.group(1))

    def test_qml_resources_are_packaged(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        patterns = project["tool"]["setuptools"]["package-data"]["prompt2cst"]
        self.assertIn("qml/*.qml", patterns)
        self.assertIn("assets/*.svg", patterns)
        self.assertTrue((ROOT / "src/prompt2cst/qml/Main.qml").is_file())
        self.assertTrue((ROOT / "src/prompt2cst/qml/GlassPanel.qml").is_file())
        self.assertTrue((ROOT / "src/prompt2cst/qml/LiquidButton.qml").is_file())
        self.assertTrue((ROOT / "src/prompt2cst/qml/ChevronIndicator.qml").is_file())
        self.assertTrue((ROOT / "src/prompt2cst/assets/prompt2cst.svg").is_file())

    def test_double_click_setup_and_launch_exist(self) -> None:
        for name in (
            "setup.bat",
            "setup.ps1",
            "Prompt2CST.bat",
            "launch.ps1",
        ):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_editable_checkout_uses_local_output_directory(self) -> None:
        self.assertEqual(default_output_dir(), ROOT / "outputs")

    def test_no_openrouter_key_is_committed(self) -> None:
        key_pattern = re.compile(r"sk-or-v1-[A-Za-z0-9_-]{16,}")
        allowed_suffixes = {
            ".md",
            ".py",
            ".ps1",
            ".bat",
            ".toml",
            ".qml",
            ".yml",
            ".txt",
        }
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
                continue
            self.assertIsNone(
                key_pattern.search(path.read_text(errors="ignore")),
                str(path),
            )


if __name__ == "__main__":
    unittest.main()
