"""PDF paper ingestion and parameter extraction with strict provenance.

Copies uploaded PDFs into ``research/uploaded/``, extracts text,
and preserves strict provenance on every extracted value.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class EvidenceType(StrEnum):
    LITERATURE_REPORTED = "literature_reported"
    MEASURED = "measured"
    SIMULATED = "simulated"
    CALCULATED = "calculated"
    ASSUMED = "assumed"
    PREDICTED = "predicted"
    MOCK_SIMULATION = "mock_simulation"
    CST_SIMULATION = "cst_simulation"


@dataclass(frozen=True)
class ExtractedValue:
    """A numerical value extracted from a paper with provenance."""

    value: float
    unit: str
    parameter: str
    source: str
    page: int | None = None
    section: str = ""
    evidence_type: EvidenceType = EvidenceType.LITERATURE_REPORTED
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "parameter": self.parameter,
            "source": self.source,
            "page": self.page,
            "section": self.section,
            "evidence_type": self.evidence_type,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class PaperMetadata:
    """Metadata for an ingested paper."""

    filename: str
    sha256: str
    page_count: int
    title: str = ""
    authors: str = ""
    stored_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "sha256": self.sha256,
            "page_count": self.page_count,
            "title": self.title,
            "authors": self.authors,
            "stored_path": self.stored_path,
        }


# Regex patterns for common RF parameter extraction
_FREQUENCY_PATTERN = re.compile(
    r"(\d+\.?\d*)\s*(MHz|GHz|THz)", re.IGNORECASE
)
_S11_PATTERN = re.compile(
    r"S[_\s]?1[_\s]?1\s*[=:≈<>≤≥]\s*[−-]?\s*(\d+\.?\d*)\s*(dB)?", re.IGNORECASE
)
_DIMENSION_PATTERN = re.compile(
    r"(\d+\.?\d*)\s*(mm|cm|m|um|µm)", re.IGNORECASE
)
_GAIN_PATTERN = re.compile(
    r"gain\s*[=:≈]\s*[−-]?\s*(\d+\.?\d*)\s*(dBi|dBd|dB)?", re.IGNORECASE
)
_BANDWIDTH_PATTERN = re.compile(
    r"bandwidth\s*[=:≈]\s*(\d+\.?\d*)\s*(MHz|GHz|%)", re.IGNORECASE
)
_EFFICIENCY_PATTERN = re.compile(
    r"efficiency\s*[=:≈]\s*(\d+\.?\d*)\s*(%)?", re.IGNORECASE
)
_IMPEDANCE_PATTERN = re.compile(
    r"impedance\s*[=:≈]\s*(\d+\.?\d*)\s*([+−-]\s*j\s*\d+\.?\d*)?\s*(Ω|ohm)?",
    re.IGNORECASE,
)
_PERMITTIVITY_PATTERN = re.compile(
    r"(?:epsilon|permittivity|eps(?:ilon)?[_\s-]?r)\s*[=:≈]\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_LOSS_TANGENT_PATTERN = re.compile(
    r"(?:loss\s*tangent|tan\s*[δd])\s*[=:≈]\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _classify_evidence(text: str, start: int) -> EvidenceType:
    """Classify nearby wording without upgrading a claim's provenance."""
    context = text[max(0, start - 160): start + 160].lower()
    if any(word in context for word in ("measured", "measurement", "fabricated", "prototype")):
        return EvidenceType.MEASURED
    if any(word in context for word in ("simulated", "simulation", "full-wave")):
        return EvidenceType.SIMULATED
    if any(word in context for word in ("calculated", "computed", "analytical")):
        return EvidenceType.CALCULATED
    return EvidenceType.LITERATURE_REPORTED


def _extract_text_from_pdf(pdf_path: Path) -> list[tuple[int, str]]:
    """Extract text from PDF, returning list of (page_number, text).

    Uses PyMuPDF (fitz) if available, else falls back to basic pdfminer.
    If neither is available, returns empty list with a warning.
    """
    pages: list[tuple[int, str]] = []

    # Try PyMuPDF first
    try:
        import fitz  # PyMuPDF  # type: ignore[import-untyped]

        doc = fitz.open(str(pdf_path))
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            if text.strip():
                pages.append((page_num + 1, text))
        doc.close()
        return pages
    except ImportError:
        pass

    # Try pdfminer
    try:
        from pdfminer.high_level import extract_text  # type: ignore[import-untyped]

        text = extract_text(str(pdf_path))
        if text.strip():
            pages.append((1, text))
        return pages
    except ImportError:
        pass

    logger.warning(
        "No PDF parser available (install PyMuPDF or pdfminer.six). "
        "Cannot extract text from %s",
        pdf_path,
    )
    return pages


def extract_rf_parameters(
    text: str, source: str, page: int | None = None, section: str = "", confidence: float = 1.0,
) -> list[ExtractedValue]:
    """Extract RF claims while retaining location, confidence, and claim type."""
    values: list[ExtractedValue] = []

    def add(match: re.Match[str], parameter: str, value: float, unit: str) -> None:
        values.append(ExtractedValue(
            value=value, unit=unit, parameter=parameter, source=source, page=page,
            section=section, evidence_type=_classify_evidence(text, match.start()), confidence=confidence,
        ))

    for match in _FREQUENCY_PATTERN.finditer(text):
        add(match, "frequency", float(match.group(1)), match.group(2))
    for match in _S11_PATTERN.finditer(text):
        add(match, "s11", -abs(float(match.group(1))), "dB")
    for match in _GAIN_PATTERN.finditer(text):
        add(match, "gain", float(match.group(1).replace("−", "-").replace(" ", "")), match.group(2) or "dBi")
    for match in _BANDWIDTH_PATTERN.finditer(text):
        add(match, "bandwidth", float(match.group(1)), match.group(2))
    for match in _EFFICIENCY_PATTERN.finditer(text):
        add(match, "efficiency", float(match.group(1)), "%")
    for match in _DIMENSION_PATTERN.finditer(text):
        add(match, "dimension", float(match.group(1)), match.group(2))
    for match in _IMPEDANCE_PATTERN.finditer(text):
        add(match, "impedance", float(match.group(1)), match.group(3) or "ohm")
    for match in _PERMITTIVITY_PATTERN.finditer(text):
        add(match, "relative_permittivity", float(match.group(1)), "relative")
    for match in _LOSS_TANGENT_PATTERN.finditer(text):
        add(match, "loss_tangent", float(match.group(1)), "dimensionless")
    return values


@dataclass
class PaperIngestion:
    """Manages PDF paper ingestion into the project workspace."""

    research_dir: Path
    papers: list[PaperMetadata] = field(default_factory=list)
    all_values: list[ExtractedValue] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.research_dir = Path(self.research_dir)
        upload_dir = self.research_dir / "uploaded"
        upload_dir.mkdir(parents=True, exist_ok=True)

    def ingest(self, pdf_path: str | Path) -> dict[str, Any]:
        """Ingest a PDF, extract text and RF parameters.

        Returns a summary dict with metadata and extracted values.
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        if not pdf_path.suffix.lower() == ".pdf":
            raise ValueError(f"Expected a .pdf file, got: {pdf_path.suffix}")

        # Compute SHA-256
        content = pdf_path.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()

        # Copy to research/uploaded/
        dest = self.research_dir / "uploaded" / pdf_path.name
        if not dest.exists():
            shutil.copy2(pdf_path, dest)

        # Extract text. If no parser is installed, permit a text-like fallback
        # only with explicitly low confidence; binary PDFs remain unparsed.
        pages = _extract_text_from_pdf(pdf_path)
        parser_status = "parsed" if pages else "unavailable"
        if not pages:
            raw_text = content.decode("utf-8", errors="ignore")
            printable_ratio = sum(ch.isprintable() or ch.isspace() for ch in raw_text) / max(len(raw_text), 1)
            if printable_ratio > 0.9 and len(raw_text.strip()) > 20:
                pages = [(1, raw_text)]
                parser_status = "raw_text_fallback_low_confidence"
        page_count = len(pages)

        # Try to extract title from first page
        title = ""
        if pages:
            first_lines = pages[0][1].split("\n")[:5]
            for line in first_lines:
                stripped = line.strip()
                if len(stripped) > 10 and not stripped.startswith("http"):
                    title = stripped
                    break

        metadata = PaperMetadata(
            filename=pdf_path.name,
            sha256=sha256,
            page_count=page_count,
            title=title,
            stored_path=str(dest),
        )
        self.papers.append(metadata)

        # Extract RF parameters from each page
        extracted: list[ExtractedValue] = []
        for page_num, text in pages:
            values = extract_rf_parameters(
                text, source=pdf_path.name, page=page_num,
                section=_section_for_text(text),
                confidence=1.0 if parser_status == "parsed" else 0.25,
            )
            extracted.extend(values)
        self.all_values.extend(extracted)

        result = {
            "metadata": metadata.to_dict(),
            "extracted_values_count": len(extracted),
            "extracted_values": [v.to_dict() for v in extracted],
            "pages_parsed": page_count,
            "parser_status": parser_status,
        }
        logger.info(
            "Ingested %s: %d pages, %d values extracted",
            pdf_path.name,
            page_count,
            len(extracted),
        )
        return result

    def search_values(
        self,
        parameter: str | None = None,
        source: str | None = None,
    ) -> list[ExtractedValue]:
        """Search extracted values by parameter name or source."""
        results = self.all_values
        if parameter:
            results = [v for v in results if v.parameter == parameter]
        if source:
            results = [v for v in results if source.lower() in v.source.lower()]
        return results

    def ingest_paper(self, pdf_path: str | Path) -> dict[str, Any]:
        res = self.ingest(pdf_path)
        # Attach extracted_parameters dict for compatibility
        param_dict = {}
        for val in self.all_values:
            param_dict[val.parameter] = val.value
        res["extracted_parameters"] = param_dict
        res["paper_id"] = self.papers[-1].sha256 if self.papers else "paper_0"
        res["title"] = self.papers[-1].title if self.papers else str(pdf_path)
        return res


PaperIngestionEngine = PaperIngestion


def _section_for_text(text: str) -> str:
    """Return a retained section heading when a parser exposes one."""
    for line in text.splitlines()[:30]:
        candidate = line.strip()
        if re.match(r"^(?:[IVXLC]+\.?|\d+(?:\.\d+)*)\s+.{3,80}$", candidate):
            return candidate[:120]
        if candidate.isupper() and 3 < len(candidate) < 100:
            return candidate[:120]
    return ""
