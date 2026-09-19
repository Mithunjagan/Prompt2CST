"""Offline contract tests for CST-native snapshot integrity."""

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from prompt2cst.cst_bridge import CSTBridge


class _Project:
    def __init__(self, parameters, *, busy=False):
        self.parameters = parameters
        self.busy = busy
        self.saved = 0
        self.saveas_paths = []

    def Save(self):
        self.saved += 1

    def SaveAs(self, target, _include_results):
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"CST-native-saveas")
        self.saveas_paths.append(path)

    def RestoreDoubleParameter(self, name):
        return self.parameters[name]

    def Solver(self):
        return self

    def IsBusy(self):
        return self.busy


class _App:
    def __init__(self, project):
        self.project = project
        self.opened = []

    def OpenFile(self, path):
        self.opened.append(path)

    def Active3D(self):
        return self.project


class CSTSnapshotTests(unittest.TestCase):
    def _bridge_with_apps(self, root, apps):
        bridge = CSTBridge(output_dir=root / "out")

        @contextmanager
        def fake_application():
            yield apps.pop(0)

        bridge._application = fake_application
        return bridge

    def test_snapshot_uses_unique_cst_saveas_then_reopens_and_reads_back(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "live.cst"
            source.write_bytes(b"known-good-live-project")
            source_project = _Project({"feed_offset_mm": 1.25})
            validation_project = _Project({"feed_offset_mm": 1.25})
            bridge = self._bridge_with_apps(root, [_App(source_project), _App(validation_project)])

            result = bridge.create_validated_cst_snapshot(
                source, "final", expected_parameters={"feed_offset_mm": 1.25}
            )

            self.assertEqual(result["status"], "VALID")
            snapshot = Path(result["snapshot_path"])
            self.assertTrue(snapshot.exists())
            self.assertNotEqual(snapshot, source)
            self.assertEqual(source.read_bytes(), b"known-good-live-project")
            self.assertEqual(source_project.saved, 1)
            self.assertEqual(validation_project.saved, 0)
            self.assertEqual(result["validation"]["parameter_readback"], {"feed_offset_mm": 1.25})

    def test_busy_solver_prevents_saveas_and_returns_invalid_snapshot(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "live.cst"
            source.write_bytes(b"live")
            source_project = _Project({"feed_offset_mm": 1.0}, busy=True)
            bridge = self._bridge_with_apps(root, [_App(source_project)])

            result = bridge.create_validated_cst_snapshot(source, "busy")

            self.assertEqual(result["status"], "SNAPSHOT_INVALID")
            self.assertIn("solver is busy", result["validation"]["error"])
            self.assertEqual(source_project.saveas_paths, [])
            self.assertTrue(source.exists())

    def test_invalid_parameter_readback_is_not_marked_valid_or_deleted(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "live.cst"
            source.write_bytes(b"live")
            source_project = _Project({"feed_offset_mm": 1.0})
            validation_project = _Project({"feed_offset_mm": 2.0})
            bridge = self._bridge_with_apps(root, [_App(source_project), _App(validation_project)])

            result = bridge.create_validated_cst_snapshot(
                source, "invalid", expected_parameters={"feed_offset_mm": 1.0}
            )

            self.assertEqual(result["status"], "SNAPSHOT_INVALID")
            self.assertTrue(Path(result["snapshot_path"]).exists())
            self.assertIn("readback mismatch", result["validation"]["error"])

    def test_result_readback_failure_is_invalid(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "live.cst"
            source.write_bytes(b"live")
            bridge = self._bridge_with_apps(
                root, [_App(_Project({"feed_offset_mm": 1.0})), _App(_Project({"feed_offset_mm": 1.0}))]
            )
            bridge.extract_results = lambda *_args, **_kwargs: {"status": "completed", "extracted": {"s11_db": (-10.0, "dB")}}

            result = bridge.create_validated_cst_snapshot(source, "no_results", require_results=True)

            self.assertEqual(result["status"], "SNAPSHOT_INVALID")
            self.assertIn("Snapshot S11 readback failed", result["validation"]["error"])


if __name__ == "__main__":
    unittest.main()
