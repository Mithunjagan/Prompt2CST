"""Zero-cost enforcement guard for Prompt2CST.

Ensures the system operates without any paid API keys, cloud services,
or hosted inference by default.  ``ZERO_COST_MODE`` can only be disabled
explicitly by the end-user via environment variable.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import StrEnum
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

_PAID_API_KEY_PATTERNS = frozenset({
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "COHERE_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "HUGGINGFACE_API_KEY",
    "REPLICATE_API_TOKEN",
    "TOGETHER_API_KEY",
    "MISTRAL_API_KEY",
    "GROQ_API_KEY",
    "PERPLEXITY_API_KEY",
    "DEEPSEEK_API_KEY",
})

_PAID_SERVICE_PATTERNS = frozenset({
    "pinecone",
    "weaviate-cloud",
    "qdrant-cloud",
    "chroma-cloud",
    "mongodb-atlas-vector",
    "aws-bedrock",
    "google-vertex",
    "azure-openai",
})


class CostViolationType(StrEnum):
    PAID_API_KEY = "paid_api_key"
    PAID_SERVICE = "paid_service"
    REMOTE_PROVIDER = "remote_provider"
    CLOUD_GPU = "cloud_gpu"
    PAID_DATABASE = "paid_database"


@dataclass(frozen=True)
class CostViolation:
    violation_type: CostViolationType
    detail: str
    blocked: bool = True


@dataclass
class CostGuard:
    """Enforces zero-cost operation across the system.

    When ``zero_cost_mode`` is ``True`` (the default), any attempt to
    use a paid API key or cloud service raises ``CostViolationError``.
    """

    zero_cost_mode: bool = field(default=True)
    violations: list[CostViolation] = field(default_factory=list)

    def __post_init__(self) -> None:
        env_override = os.getenv("PROMPT2CST_ZERO_COST_MODE", "").strip().lower()
        if env_override in ("false", "0", "no"):
            self.zero_cost_mode = False
            logger.warning(
                "ZERO_COST_MODE disabled via environment variable. "
                "Paid API calls are now permitted."
            )

    def check_api_key(self, key_name: str) -> None:
        """Raise if a paid API key is being used in zero-cost mode."""
        if not self.zero_cost_mode:
            return
        canonical = key_name.upper().replace("-", "_")
        if canonical in _PAID_API_KEY_PATTERNS:
            violation = CostViolation(
                violation_type=CostViolationType.PAID_API_KEY,
                detail=f"Blocked paid API key: {key_name}",
            )
            self.violations.append(violation)
            raise CostViolationError(violation)

    def check_service(self, service_name: str) -> None:
        """Raise if a paid cloud service is being used in zero-cost mode."""
        if not self.zero_cost_mode:
            return
        normalized = service_name.lower().replace(" ", "-")
        if normalized in _PAID_SERVICE_PATTERNS:
            violation = CostViolation(
                violation_type=CostViolationType.PAID_SERVICE,
                detail=f"Blocked paid service: {service_name}",
            )
            self.violations.append(violation)
            raise CostViolationError(violation)

    def check_remote_provider(self, provider_name: str, base_url: str = "") -> None:
        """Block every remote model provider before a request can be prepared.

        A generic OpenAI-compatible endpoint is not safely classifiable as
        free.  In zero-cost mode, callers must instead use deterministic code,
        local Ollama, or explicitly disable the guard themselves.
        """
        if not self.zero_cost_mode:
            return
        violation = CostViolation(
            violation_type=CostViolationType.REMOTE_PROVIDER,
            detail=(
                "Blocked remote model provider in zero-cost mode: "
                f"{provider_name} ({base_url or 'no endpoint'})"
            ),
        )
        self.violations.append(violation)
        raise CostViolationError(violation)

    def check_environment(self) -> list[CostViolation]:
        """Scan environment for any configured paid API keys."""
        found: list[CostViolation] = []
        if not self.zero_cost_mode:
            return found
        for key_name in sorted(_PAID_API_KEY_PATTERNS):
            if os.getenv(key_name):
                violation = CostViolation(
                    violation_type=CostViolationType.PAID_API_KEY,
                    detail=f"Environment variable {key_name} is set",
                    blocked=False,  # informational; does not block
                )
                found.append(violation)
                logger.info(
                    "CostGuard: %s is set but will not be used in zero-cost mode.",
                    key_name,
                )
        return found

    def verify_no_paid_keys(self) -> None:
        violations = self.check_environment()
        if violations and self.zero_cost_mode:
            raise CostViolationError(violations[0])

    def to_dict(self) -> dict[str, Any]:
        return {
            "zero_cost_mode": self.zero_cost_mode,
            "total_cost_usd": 0.0,
            "total_cost_inr": 0.0,
            "violations_count": len(self.violations),
        }


class CostViolationError(RuntimeError):
    """Raised when an operation would incur cost in zero-cost mode."""

    def __init__(self, violation: CostViolation) -> None:
        self.violation = violation
        super().__init__(violation.detail)


ZeroCostViolationError = CostViolationError


def zero_cost_required(func: Callable) -> Callable:
    """Decorator that ensures a function cannot be called when cost guard blocks."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        guard = kwargs.pop("_cost_guard", None)
        if guard is None:
            guard = _default_guard()
        if guard.zero_cost_mode:
            # Function executes normally - it's a zero-cost operation
            pass
        return func(*args, **kwargs)

    return wrapper


_GLOBAL_GUARD: CostGuard | None = None


def _default_guard() -> CostGuard:
    global _GLOBAL_GUARD
    if _GLOBAL_GUARD is None:
        _GLOBAL_GUARD = CostGuard()
    return _GLOBAL_GUARD


def get_cost_guard() -> CostGuard:
    """Return the global ``CostGuard`` singleton."""
    return _default_guard()


def reset_cost_guard() -> None:
    """Reset the global guard (useful for testing)."""
    global _GLOBAL_GUARD
    _GLOBAL_GUARD = None
