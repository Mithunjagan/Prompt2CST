"""Validated access to the bundled antenna-family research catalogue.

The catalogue contains engineering starting points, not certified designs. It
is kept separate from executable DesignIR so literature text can never become
CST commands without passing the normal compiler and approval boundary.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Source(_StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    title: str = Field(min_length=4)
    organization: str = Field(min_length=2)
    url: HttpUrl
    kind: Literal[
        "government_report", "official_documentation", "peer_reviewed_paper"
    ]


class SizingRule(_StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    output: str
    expression: str
    variables: dict[str, str]
    validity: list[str] = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    confidence: Literal["reference", "first_cut", "empirical_start"]


class AntennaFamily(_StrictModel):
    family: str = Field(pattern=r"^[a-z0-9_]+$")
    display_name: str
    aliases: list[str]
    geometry_class: Literal["wire", "planar", "aperture", "array", "reflector"]
    typical_use: list[str] = Field(min_length=1)
    required_inputs: list[str] = Field(min_length=1)
    key_parameters: list[str] = Field(min_length=1)
    sizing_rules: list[SizingRule] = Field(min_length=1)
    simulation_requirements: list[str] = Field(min_length=1)
    verification_metrics: list[str] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    implementation_status: Literal[
        "cst_compiler_available",
        "openems_generator_available",
        "research_only",
    ]
    source_ids: list[str] = Field(min_length=1)


class AntennaKnowledgeBase(_StrictModel):
    schema_version: Literal["1.0"]
    disclaimer: str
    sources: list[Source] = Field(min_length=1)
    families: list[AntennaFamily] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "AntennaKnowledgeBase":
        source_ids = [source.id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source ids must be unique")
        family_names = [family.family for family in self.families]
        if len(family_names) != len(set(family_names)):
            raise ValueError("antenna family names must be unique")
        known = set(source_ids)
        for family in self.families:
            referenced = set(family.source_ids)
            for rule in family.sizing_rules:
                referenced.update(rule.source_ids)
            missing = referenced - known
            if missing:
                raise ValueError(
                    f"{family.family} references unknown sources: {sorted(missing)}"
                )
        return self

    def family(self, name: str) -> AntennaFamily:
        normalized = name.strip().casefold().replace("-", "_").replace(" ", "_")
        for item in self.families:
            aliases = {
                alias.casefold().replace("-", "_").replace(" ", "_")
                for alias in item.aliases
            }
            if normalized == item.family or normalized in aliases:
                return item
        raise KeyError(f"Unknown antenna family: {name}")

    def sources_for(self, family: AntennaFamily) -> list[Source]:
        wanted = set(family.source_ids)
        for rule in family.sizing_rules:
            wanted.update(rule.source_ids)
        return [source for source in self.sources if source.id in wanted]


@lru_cache(maxsize=1)
def load_antenna_knowledge_base() -> AntennaKnowledgeBase:
    resource = files("prompt2cst").joinpath("knowledge/antenna_families.json")
    return AntennaKnowledgeBase.model_validate_json(
        resource.read_text(encoding="utf-8")
    )


def family_evidence(name: str) -> dict[str, object]:
    """Return a serializable, citation-bearing summary for planning artifacts."""
    kb = load_antenna_knowledge_base()
    family = kb.family(name)
    return {
        "family": family.family,
        "implementation_status": family.implementation_status,
        "sizing_rule_ids": [rule.id for rule in family.sizing_rules],
        "limitations": family.limitations,
        "sources": [
            {
                "id": source.id,
                "title": source.title,
                "organization": source.organization,
                "url": str(source.url),
            }
            for source in kb.sources_for(family)
        ],
    }
