"""Small, auditable pilot data for local prompt extraction fine-tuning.

These are synthetic instruction examples, not faculty measurements or RF
simulation results.  Keep evaluation templates and frequencies disjoint from
training so the pilot can detect at least basic format/generalization failures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

SYSTEM_INSTRUCTION = (
    "Extract only antenna requirements explicitly stated by the user. "
    "Return exactly one JSON object with keys family, frequency_hz, and "
    "target_s11_db. Use null for missing or unsupported values. "
    "Supported families: pifa, helix, yagi_uda, horn, vivaldi. "
    "Never invent dimensions, simulated performance, gain, or efficiency."
)


@dataclass(frozen=True)
class ExtractionExample:
    prompt: str
    family: str | None
    frequency_hz: int | None
    target_s11_db: int | None

    def expected(self) -> dict[str, str | int | None]:
        return {
            "family": self.family,
            "frequency_hz": self.frequency_hz,
            "target_s11_db": self.target_s11_db,
        }

    def completion(self) -> str:
        return json.dumps(self.expected(), separators=(",", ":"))


_ALIASES = {
    "pifa": ("PIFA", "planar inverted-F"),
    "helix": ("helical", "axial-mode helix"),
    "yagi_uda": ("Yagi-Uda", "five-element Yagi"),
    "horn": ("pyramidal horn", "horn"),
    "vivaldi": ("Vivaldi", "tapered-slot Vivaldi"),
}

_TRAIN_MHZ = (433, 868, 915, 1575, 2450, 3500, 5800)
_EVAL_MHZ = (470, 920, 2400)
_S11_DB = (-10, -15, -20)


def build_pilot_dataset() -> tuple[list[ExtractionExample], list[ExtractionExample]]:
    """Return fixed synthetic train/holdout sets without measurement claims."""
    train: list[ExtractionExample] = []
    evaluation: list[ExtractionExample] = []
    for family, aliases in _ALIASES.items():
        for mhz in _TRAIN_MHZ:
            for s11 in _S11_DB:
                train.extend((
                    ExtractionExample(
                        f"Design a {aliases[0]} antenna at {mhz} MHz with S11 below {s11} dB.",
                        family, mhz * 1_000_000, s11,
                    ),
                    ExtractionExample(
                        f"I need a {aliases[1]} for {mhz / 1000:g} GHz; S11 < {s11} dB.",
                        family, mhz * 1_000_000, s11,
                    ),
                ))
            train.append(ExtractionExample(
                f"Plan a {aliases[0]} for {mhz} MHz. I have not chosen a matching target.",
                family, mhz * 1_000_000, None,
            ))
        for mhz in _EVAL_MHZ:
            for s11 in (-10, -15):
                evaluation.append(ExtractionExample(
                    f"Could you create a {aliases[1]} at {mhz} megahertz? "
                    f"The return-loss requirement is S11 less than {s11} dB.",
                    family, mhz * 1_000_000, s11,
                ))
    train.extend((
        ExtractionExample("What antenna should I use?", None, None, None),
        ExtractionExample("Make something for wireless communication.", None, None, None),
        ExtractionExample("Design a parabolic reflector at 2.45 GHz.", None, 2_450_000_000, None),
    ))
    evaluation.extend((
        ExtractionExample("Can you build any antenna for me?", None, None, None),
        ExtractionExample("Make a spiral antenna at 470 MHz.", None, 470_000_000, None),
        ExtractionExample("I need a Yagi but have not chosen a frequency.", "yagi_uda", None, None),
    ))
    return train, evaluation
