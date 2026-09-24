from __future__ import annotations

import json
import unittest

from prompt2cst.local_ai_dataset import SYSTEM_INSTRUCTION, build_pilot_dataset


class LocalAIDatasetTests(unittest.TestCase):
    def test_pilot_data_is_explicit_synthetic_extraction_only(self) -> None:
        train, evaluation = build_pilot_dataset()
        self.assertGreater(len(train), 200)
        self.assertGreater(len(evaluation), 20)
        self.assertTrue("Never invent" in SYSTEM_INSTRUCTION)
        self.assertTrue(set(example.prompt for example in train).isdisjoint(
            example.prompt for example in evaluation
        ))
        for example in train + evaluation:
            expected = json.loads(example.completion())
            self.assertEqual(set(expected), {"family", "frequency_hz", "target_s11_db"})
            self.assertEqual(expected, example.expected())
            self.assertNotIn("gain_dbi", expected)
            self.assertNotIn("simulated_s11_db", expected)

    def test_holdout_frequencies_are_not_in_training(self) -> None:
        train, evaluation = build_pilot_dataset()
        train_frequencies = {item.frequency_hz for item in train if item.frequency_hz}
        eval_frequencies = {item.frequency_hz for item in evaluation if item.frequency_hz}
        self.assertFalse(train_frequencies & eval_frequencies)


if __name__ == "__main__":
    unittest.main()
