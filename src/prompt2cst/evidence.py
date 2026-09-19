"""Evidence database with local RAG and provenance hierarchy.

Stores claims and evidence with a strict hierarchy:
1. User papers > 2. Peer-reviewed research > 3. Standards >
4. App notes > 5. Secondary > 6. Engineering assumptions.

Provides local text chunking, vector index, and metadata-aware
retrieval without requiring any paid embedding service.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

from .papers import EvidenceType, ExtractedValue

logger = logging.getLogger(__name__)


class SourceTier(IntEnum):
    """Evidence source hierarchy (lower = higher trust)."""

    USER_PAPER = 1
    PEER_REVIEWED = 2
    STANDARD = 3
    APPLICATION_NOTE = 4
    SECONDARY = 5
    ASSUMPTION = 6


@dataclass(frozen=True)
class EvidenceClaim:
    """A single evidence claim with provenance."""

    claim_id: str
    parameter: str
    value: float
    unit: str
    source: str
    source_tier: SourceTier
    evidence_type: EvidenceType
    page: int | None = None
    section: str = ""
    confidence: float = 1.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "parameter": self.parameter,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "source_tier": self.source_tier.name,
            "evidence_type": self.evidence_type,
            "page": self.page,
            "section": self.section,
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class SearchCoverage:
    """Documents what was searched and found."""

    queries_performed: int
    sources_searched: int
    papers_found: int
    papers_accessible: int
    papers_considered_relevant: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "queries_performed": self.queries_performed,
            "sources_searched": self.sources_searched,
            "papers_found": self.papers_found,
            "papers_accessible": self.papers_accessible,
            "papers_considered_relevant": self.papers_considered_relevant,
        }


_EVIDENCE_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    parameter TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    source TEXT NOT NULL,
    source_tier INTEGER NOT NULL,
    evidence_type TEXT NOT NULL,
    page INTEGER,
    section TEXT DEFAULT '',
    confidence REAL DEFAULT 1.0,
    notes TEXT DEFAULT '',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    page INTEGER,
    text TEXT NOT NULL,
    embedding_json TEXT DEFAULT '',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS coverage (
    coverage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    queries_performed INTEGER NOT NULL DEFAULT 1,
    sources_searched INTEGER NOT NULL DEFAULT 0,
    papers_found INTEGER NOT NULL DEFAULT 0,
    papers_accessible INTEGER NOT NULL DEFAULT 0,
    papers_relevant INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claims_parameter ON claims(parameter);
CREATE INDEX IF NOT EXISTS idx_claims_source ON claims(source);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);
"""


@dataclass
class EvidenceDatabase:
    """Local evidence store with text chunking and simple vector search."""

    db_path: Path | str = field(default_factory=lambda: Path("evidence.db"))
    _conn: sqlite3.Connection | None = field(default=None, init=False, repr=False)

    def add_paper_claims(self, extracted: dict[str, Any]) -> int:
        values = extracted.get("extracted_values", [])
        if values:
            typed_values = [
                ExtractedValue(
                    value=float(item["value"]), unit=str(item.get("unit", "")),
                    parameter=str(item["parameter"]),
                    source=str(item.get("source", extracted.get("title", "paper"))),
                    page=item.get("page"), section=str(item.get("section", "")),
                    evidence_type=EvidenceType(item.get("evidence_type", EvidenceType.LITERATURE_REPORTED)),
                    confidence=float(item.get("confidence", 1.0)),
                )
                for item in values
                if isinstance(item, dict) and isinstance(item.get("value"), (int, float))
            ]
            return self.add_from_extracted(typed_values)
        params = extracted.get("extracted_parameters", {})
        count = 0
        for k, v in params.items():
            if isinstance(v, (int, float)):
                claim_id = hashlib.sha256(f"{k}:{v}:{extracted.get('paper_id', '')}".encode()).hexdigest()[:16]
                self.add_claim(EvidenceClaim(
                    claim_id=claim_id,
                    parameter=k,
                    value=float(v),
                    unit="unit",
                    source=extracted.get("title", "paper"),
                    source_tier=SourceTier.USER_PAPER,
                    evidence_type=EvidenceType.LITERATURE_REPORTED,
                ))
                count += 1
        return count

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.executescript(_EVIDENCE_DB_SCHEMA)
        self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
        return self._conn

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------

    def add_claim(self, claim: EvidenceClaim) -> None:
        """Insert or update a claim."""
        now = time.time()
        self.conn.execute(
            "INSERT OR REPLACE INTO claims "
            "(claim_id, parameter, value, unit, source, source_tier, "
            "evidence_type, page, section, confidence, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                claim.claim_id,
                claim.parameter,
                claim.value,
                claim.unit,
                claim.source,
                int(claim.source_tier),
                claim.evidence_type,
                claim.page,
                claim.section,
                claim.confidence,
                claim.notes,
                now,
            ),
        )
        self.conn.commit()

    def add_from_extracted(
        self,
        values: list[ExtractedValue],
        source_tier: SourceTier = SourceTier.USER_PAPER,
    ) -> int:
        """Bulk-add claims from extracted paper values."""
        count = 0
        for v in values:
            claim_id = hashlib.sha256(
                f"{v.parameter}:{v.value}:{v.unit}:{v.source}:{v.page}".encode()
            ).hexdigest()[:16]
            claim = EvidenceClaim(
                claim_id=claim_id,
                parameter=v.parameter,
                value=v.value,
                unit=v.unit,
                source=v.source,
                source_tier=source_tier,
                evidence_type=v.evidence_type,
                page=v.page,
                section=v.section,
                confidence=v.confidence,
            )
            self.add_claim(claim)
            count += 1
        return count

    def query_claims(
        self,
        parameter: str | None = None,
        source_tier_max: SourceTier | None = None,
    ) -> list[EvidenceClaim]:
        """Query claims, optionally filtering by parameter and tier."""
        sql = "SELECT * FROM claims WHERE 1=1"
        params: list[Any] = []
        if parameter:
            sql += " AND parameter = ?"
            params.append(parameter)
        if source_tier_max is not None:
            sql += " AND source_tier <= ?"
            params.append(int(source_tier_max))
        sql += " ORDER BY source_tier ASC, confidence DESC"
        rows = self.conn.execute(sql, params).fetchall()
        return [
            EvidenceClaim(
                claim_id=r[0],
                parameter=r[1],
                value=r[2],
                unit=r[3],
                source=r[4],
                source_tier=SourceTier(r[5]),
                evidence_type=EvidenceType(r[6]),
                page=r[7],
                section=r[8],
                confidence=r[9],
                notes=r[10],
            )
            for r in rows
        ]

    def best_value(self, parameter: str) -> EvidenceClaim | None:
        """Return the highest-trust claim for a parameter."""
        claims = self.query_claims(parameter=parameter)
        return claims[0] if claims else None

    def detect_conflicts(self, parameter: str | None = None) -> list[dict[str, Any]]:
        """Detect conflicting literature claims for parameters.

        Returns a list of conflict reports if multiple claims for the same parameter
        differ by more than 5%.
        """
        conflicts = []
        sql = "SELECT DISTINCT parameter FROM claims"
        params = []
        if parameter:
            sql += " WHERE parameter = ?"
            params.append(parameter)

        param_rows = self.conn.execute(sql, params).fetchall()
        for (param,) in param_rows:
            claims = self.query_claims(parameter=param)
            if len(claims) >= 2:
                vals = [c.value for c in claims]
                min_v, max_v = min(vals), max(vals)
                if min_v > 0 and (max_v - min_v) / min_v > 0.05:
                    conflicts.append({
                        "status": "CONFLICT_DETECTED",
                        "parameter": param,
                        "difference_pct": round((max_v - min_v) / min_v * 100, 2),
                        "claims": [c.to_dict() for c in claims],
                    })
        return conflicts

    # ------------------------------------------------------------------
    # Text chunking and local RAG
    # ------------------------------------------------------------------

    def add_text_chunk(
        self,
        source: str,
        page: int | None,
        text: str,
    ) -> str:
        """Add a text chunk to the local index."""
        chunk_id = hashlib.sha256(
            f"{source}:{page}:{text[:100]}".encode()
        ).hexdigest()[:16]

        # Compute simple bag-of-words embedding (TF vector)
        embedding = self._compute_embedding(text)

        self.conn.execute(
            "INSERT OR REPLACE INTO chunks "
            "(chunk_id, source, page, text, embedding_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                chunk_id,
                source,
                page,
                text,
                json.dumps(embedding),
                time.time(),
            ),
        )
        self.conn.commit()
        return chunk_id

    def search_chunks(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search text chunks using cosine similarity on TF vectors."""
        query_emb = self._compute_embedding(query)

        rows = self.conn.execute(
            "SELECT chunk_id, source, page, text, embedding_json FROM chunks"
        ).fetchall()

        scored: list[tuple[float, dict[str, Any]]] = []
        for r in rows:
            chunk_emb = json.loads(r[4]) if r[4] else {}
            score = self._cosine_similarity(query_emb, chunk_emb)
            scored.append(
                (
                    score,
                    {
                        "chunk_id": r[0],
                        "source": r[1],
                        "page": r[2],
                        "text": r[3][:500],
                        "score": round(score, 4),
                    },
                )
            )

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]

    def record_coverage(
        self,
        query: str,
        coverage: SearchCoverage,
    ) -> None:
        """Record search coverage for transparency."""
        self.conn.execute(
            "INSERT INTO coverage "
            "(query, queries_performed, sources_searched, papers_found, "
            "papers_accessible, papers_relevant, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                query,
                coverage.queries_performed,
                coverage.sources_searched,
                coverage.papers_found,
                coverage.papers_accessible,
                coverage.papers_considered_relevant,
                time.time(),
            ),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Local embedding (bag-of-words TF)
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_embedding(text: str) -> dict[str, float]:
        """Compute a simple term-frequency vector."""
        words = re.findall(r"[a-z0-9]+", text.lower())
        if not words:
            return {}
        tf: dict[str, float] = {}
        for word in words:
            if len(word) > 2:  # skip very short words
                tf[word] = tf.get(word, 0) + 1.0
        # Normalize
        total = sum(tf.values())
        if total > 0:
            for key in tf:
                tf[key] /= total
        return tf

    @staticmethod
    def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
        """Compute cosine similarity between two sparse vectors."""
        if not a or not b:
            return 0.0
        keys = set(a.keys()) & set(b.keys())
        if not keys:
            return 0.0
        dot = sum(a[k] * b[k] for k in keys)
        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a summary of the evidence database."""
        claim_count = self.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        chunk_count = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        parameters = self.conn.execute(
            "SELECT DISTINCT parameter FROM claims ORDER BY parameter"
        ).fetchall()
        sources = self.conn.execute(
            "SELECT DISTINCT source FROM claims ORDER BY source"
        ).fetchall()
        return {
            "total_claims": claim_count,
            "total_chunks": chunk_count,
            "parameters": [r[0] for r in parameters],
            "sources": [r[0] for r in sources],
        }

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
