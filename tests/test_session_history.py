import tempfile
import unittest
from pathlib import Path

from prompt2cst.session_history import PromptHistoryStore


class PromptHistoryStoreTests(unittest.TestCase):
    def test_history_persists_until_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PromptHistoryStore(Path(directory))
            record = store.create(
                prompt="Design a 2.45 GHz dipole",
                family_id="center_fed_dipole",
                mode="preview",
                phase="calculations",
                role="calculations_model",
                model="calc-model",
                activity_text="started",
            )
            store.update(
                record.id,
                status="COMPLETED",
                assistant_text="done",
                activity_text="trace",
            )

            reloaded = PromptHistoryStore(Path(directory))
            self.assertEqual(len(reloaded.summaries()), 1)
            self.assertEqual(reloaded.get(record.id).assistant_text, "done")

            reloaded.clear()
            self.assertEqual(reloaded.list_records(), [])

    def test_history_is_capped_and_returned_newest_first(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PromptHistoryStore(Path(directory), max_records=2)
            first = store.create(
                prompt="first",
                family_id="auto",
                mode="preview",
                phase="requirements",
                role="requirements_model",
                model="model-a",
                activity_text="",
            )
            second = store.create(
                prompt="second",
                family_id="auto",
                mode="preview",
                phase="preview",
                role="geometry_model",
                model="model-b",
                activity_text="",
            )
            third = store.create(
                prompt="third",
                family_id="auto",
                mode="preview",
                phase="validation",
                role="critic_model",
                model="model-c",
                activity_text="",
            )

            ids = [item["id"] for item in store.summaries()]
            self.assertEqual(ids, [third.id, second.id])
            with self.assertRaises(KeyError):
                store.get(first.id)

    def test_preview_identity_is_saved_with_the_history_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PromptHistoryStore(Path(directory))
            record = store.create(
                prompt="preview this",
                family_id="auto",
                mode="preview",
                phase="preview",
                role="swarm_coordinator",
                model="swarm",
                activity_text="",
                session_id="session1",
            )

            store.update(
                record.id,
                status="COMPLETED",
                assistant_text="ready",
                activity_text="previewed",
                session_id="session1",
                plan_id="plan1",
                approval_hash="a" * 64,
            )

            loaded = PromptHistoryStore(Path(directory)).get(record.id)
            self.assertEqual(loaded.session_id, "session1")
            self.assertEqual(loaded.plan_id, "plan1")
            self.assertEqual(loaded.approval_hash, "a" * 64)


if __name__ == "__main__":
    unittest.main()
