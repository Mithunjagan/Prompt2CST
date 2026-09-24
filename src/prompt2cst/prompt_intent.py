"""Conservative, deterministic antenna-family recognition for local prompts.

This layer never infers a requested family from an LLM.  A named topology must
match a curated alias and a geometry-capable catalogue entry before planning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .antenna_knowledge import load_antenna_knowledge_base

_ALIASES: dict[str, tuple[str, ...]] = {
    "dipole": ("dipole", "half wave dipole", "wire dipole"),
    "monopole": ("monopole", "quarter wave monopole", "whip antenna"),
    "patch": ("patch", "patch antenna", "microstrip patch", "rectangular patch"),
    "pifa": ("pifa", "planar inverted f", "inverted f antenna"),
    "helix": ("helix", "helical", "axial mode helix"),
    "yagi_uda": ("yagi", "yagi uda"),
    "horn": ("horn", "horn antenna", "pyramidal horn", "waveguide horn"),
    "vivaldi": ("vivaldi", "tapered slot antenna", "tapered slot"),
    "loop": ("loop antenna", "small loop antenna", "resonant loop antenna"),
    "slot": ("slot antenna", "aperture slot antenna", "resonant slot antenna"),
    "log_periodic": ("log periodic", "lpda"),
    "spiral": ("spiral", "spiral antenna", "archimedean spiral", "equiangular spiral"),
    "parabolic_reflector": ("parabolic reflector", "parabolic dish", "dish antenna"),
}


@dataclass(frozen=True)
class FamilyMention:
    family: str
    quote: str
    start: int
    end: int


def _pattern(alias: str) -> re.Pattern[str]:
    words = re.split(r"[\s_-]+", alias)
    return re.compile(r"(?<!\w)" + r"[\s_-]+".join(map(re.escape, words)) + r"(?!\w)", re.I)


def family_mentions(prompt: str) -> list[FamilyMention]:
    """Find non-overlapping curated family names, preferring longer phrases."""
    candidates = [
        FamilyMention(family, match.group(), match.start(), match.end())
        for family, aliases in _ALIASES.items()
        for alias in aliases
        for match in _pattern(alias).finditer(prompt)
    ]
    chosen: list[FamilyMention] = []
    for mention in sorted(candidates, key=lambda item: (-(item.end - item.start), item.start)):
        if all(mention.end <= item.start or mention.start >= item.end for item in chosen):
            chosen.append(mention)
    return sorted(chosen, key=lambda item: item.start)


def resolve_explicit_family(prompt: str, spec_names: list[str] | None = None) -> str | None:
    """Return one build-capable requested family, or fail on known conflicts.

    An unspecified family remains ``None`` so existing deterministic candidate
    screening can recommend one. A named research-only family is never silently
    substituted with a different build-capable topology.
    """
    mentioned = {item.family for item in family_mentions(prompt)}
    kb = load_antenna_knowledge_base()
    specified: set[str] = set()
    for name in spec_names or []:
        try:
            specified.add(kb.family(name).family)
        except KeyError as exc:
            raise ValueError(f"Unknown antenna family in specification: {name}") from exc
    if len(mentioned) > 1:
        raise ValueError("Multiple antenna families were requested; choose one topology")
    if mentioned and specified and not mentioned.issubset(specified):
        raise ValueError("Prompt and specification request different antenna families")
    for family in mentioned | specified:
        if kb.family(family).implementation_status == "research_only":
            raise ValueError(f"{family} is research-only; no executable geometry generator exists")
    return next(iter(mentioned or specified), None) if len(mentioned or specified) == 1 else None
