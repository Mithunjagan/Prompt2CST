"""Environment-agnostic model routing for Prompt2CST.

Maps capability requests (``reasoning``, ``research``, ``coding``,
``classification``) to available execution environments.  The Python
application never directly calls a paid LLM API.  Instead it:

1. Uses deterministic rule-based fallback for tasks that can be solved
   algorithmically (sizing equations, topology scoring, etc.).
2. Supports *optional* local model providers (e.g. Ollama) if present.
3. Returns ``NEEDS_AGENT`` when a task genuinely requires LLM reasoning,
   signaling that the calling orchestration environment (Antigravity,
   or any external agent) should perform the inference.

This keeps the Python code model-provider-neutral.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .cost_guard import CostGuard, get_cost_guard

logger = logging.getLogger(__name__)


class ModelCapability(StrEnum):
    REASONING = "reasoning"
    RESEARCH = "research"
    CODING = "coding"
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    RF_ARCHITECT = "rf_architect"


class ProviderType(StrEnum):
    DETERMINISTIC = "deterministic"
    LOCAL_OLLAMA = "local_ollama"
    NEEDS_AGENT = "needs_agent"


class TaskStatus(StrEnum):
    COMPLETED = "completed"
    NEEDS_AGENT = "needs_agent"
    BLOCKED = "blocked"
    FAILED = "failed"


AgentRole = ModelCapability


@dataclass(frozen=True)
class ModelResponse:
    """Result from a model routing request."""

    status: TaskStatus
    result: Any = None
    provider: ProviderType = ProviderType.DETERMINISTIC
    detail: str = ""

    @property
    def mode(self) -> str:
        return "builtin" if self.provider == ProviderType.DETERMINISTIC else str(self.provider)

    @property
    def cost_usd(self) -> float:
        return 0.0


@dataclass
class ModelRouter:
    """Routes capability requests to available execution environments.

    The router NEVER calls paid APIs.  It checks for local Ollama
    availability, falls back to deterministic rule-based computation,
    or signals ``NEEDS_AGENT`` for tasks requiring genuine LLM reasoning.
    """

    cost_guard: CostGuard = field(default_factory=get_cost_guard)
    _ollama_available: bool | None = field(default=None, init=False)

    def route(
        self,
        capability: ModelCapability,
        task: dict[str, Any],
        deterministic_handler: Any | None = None,
    ) -> ModelResponse:
        """Route a task to the best available provider.

        Parameters
        ----------
        capability:
            The type of model capability needed.
        task:
            A dictionary describing the task.
        deterministic_handler:
            An optional callable that can solve the task without any model.
            If provided and succeeds, the result is returned immediately.
        """
        # Priority 1: Deterministic handler (no model needed)
        if deterministic_handler is not None:
            try:
                result = deterministic_handler(task)
                return ModelResponse(
                    status=TaskStatus.COMPLETED,
                    result=result,
                    provider=ProviderType.DETERMINISTIC,
                    detail="Solved deterministically without model inference.",
                )
            except Exception as exc:
                logger.debug(
                    "Deterministic handler failed for %s: %s", capability, exc
                )

        # Priority 2: Local Ollama (if available)
        if self._check_ollama():
            return ModelResponse(
                status=TaskStatus.NEEDS_AGENT,
                provider=ProviderType.LOCAL_OLLAMA,
                detail=(
                    "Task requires model inference. Local Ollama is available. "
                    "External orchestrator should invoke local model."
                ),
            )

        # Priority 3: Signal that an external agent is needed
        return ModelResponse(
            status=TaskStatus.NEEDS_AGENT,
            provider=ProviderType.NEEDS_AGENT,
            detail=(
                "Task requires model inference. No local model available. "
                "External orchestrator (Antigravity or other) should handle."
            ),
        )

    def _check_ollama(self) -> bool:
        """Check if Ollama is available locally (cached)."""
        if self._ollama_available is not None:
            return self._ollama_available

        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        try:
            import urllib.request

            req = urllib.request.Request(
                f"{ollama_host}/api/tags", method="GET"
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                self._ollama_available = resp.status == 200
        except Exception:
            self._ollama_available = False

        if self._ollama_available:
            logger.info("Local Ollama detected at %s", ollama_host)
        return self._ollama_available

    def status(self) -> dict[str, Any]:
        """Return routing status summary."""
        return {
            "zero_cost_mode": self.cost_guard.zero_cost_mode,
            "ollama_available": self._check_ollama(),
            "supported_capabilities": [c.value for c in ModelCapability],
            "primary_provider": (
                ProviderType.LOCAL_OLLAMA
                if self._check_ollama()
                else ProviderType.NEEDS_AGENT
            ),
        }


_GLOBAL_ROUTER: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """Return the global ``ModelRouter`` singleton."""
    global _GLOBAL_ROUTER
    if _GLOBAL_ROUTER is None:
        _GLOBAL_ROUTER = ModelRouter()
    return _GLOBAL_ROUTER


def reset_model_router() -> None:
    """Reset the global router (useful for testing)."""
    global _GLOBAL_ROUTER
    _GLOBAL_ROUTER = None
