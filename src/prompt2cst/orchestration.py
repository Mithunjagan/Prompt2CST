from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError


class ModelRole(StrEnum):
    REQUIREMENTS = "requirements_model"
    CALCULATIONS = "calculations_model"
    PARAMETERS = "parameters_model"
    GEOMETRY = "geometry_model"
    SIMULATION = "simulation_model"
    CRITIC = "critic_model"
    CODE_REVIEW = "code_review_model"
    RESULTS_ANALYSIS = "results_analysis_model"


@dataclass(frozen=True)
class RoleConfig:
    role: ModelRole
    provider: str
    model: str
    fallback_models: tuple[str, ...] = ()
    timeout_seconds: float = 60
    enabled: bool = True


@dataclass
class ModelAccounting:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0
    fallbacks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ModelGeneration:
    value: BaseModel
    provider: str
    model: str
    duration_seconds: float
    accounting: ModelAccounting


class ModelProviderError(RuntimeError):
    def __init__(self, message: str, classification: str = "provider_error"):
        super().__init__(message)
        self.classification = classification


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class ModelProvider(Protocol):
    name: str

    async def generate_structured(
        self,
        role: ModelRole,
        messages: list[dict[str, str]],
        response_schema: type[SchemaT],
        timeout: float,
        metadata: dict[str, Any] | None = None,
        model: str = "",
    ) -> ModelGeneration: ...

    async def health(self) -> dict[str, Any]: ...


class OpenAICompatibleProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        name: str = "openai_compatible",
        max_retries: int = 2,
        log=None,
    ):
        if not api_key.strip():
            raise ValueError("provider API key is required")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.max_retries = max(0, min(max_retries, 4))
        self.log = log or (lambda _event: None)

    async def generate_structured(
        self,
        role: ModelRole,
        messages: list[dict[str, str]],
        response_schema: type[SchemaT],
        timeout: float,
        metadata: dict[str, Any] | None = None,
        model: str = "",
    ) -> ModelGeneration:
        accounting = ModelAccounting()
        last_error: Exception | None = None
        started = time.monotonic()
        schema_mode = 0
        for attempt in range(self.max_retries + 1):
            accounting.calls += 1
            self.log(
                {
                    "event": "model_call",
                    "provider": self.name,
                    "role": role,
                    "model": model,
                    "attempt": attempt + 1,
                }
            )
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(timeout, connect=min(15, timeout))
                ) as client:
                    payload: dict[str, Any] = {
                        "model": model,
                        "messages": messages,
                        "temperature": 0,
                    }
                    if schema_mode == 0:
                        payload["response_format"] = {
                            "type": "json_schema",
                            "json_schema": {
                                "name": response_schema.__name__,
                                "strict": True,
                                "schema": response_schema.model_json_schema(),
                            },
                        }
                    else:
                        schema_instruction = {
                            "role": "system",
                            "content": (
                                "Return only one JSON object that validates against "
                                "this schema: "
                                + json.dumps(response_schema.model_json_schema())
                            ),
                        }
                        payload["messages"] = [*messages, schema_instruction]
                        if schema_mode == 1:
                            payload["response_format"] = {"type": "json_object"}
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    if not response.is_success:
                        classification = _classify_http(response.status_code)
                        raise ModelProviderError(
                            f"Provider HTTP {response.status_code}", classification
                        )
                    payload = response.json()
                    choice = (payload.get("choices") or [{}])[0]
                    content = (choice.get("message") or {}).get("content")
                    if not isinstance(content, str) or not content.strip():
                        raise ModelProviderError(
                            "Model returned empty or non-text structured output",
                            "invalid_output",
                        )
                    parsed = json.loads(content)
                    value = response_schema.model_validate(parsed)
                    usage = payload.get("usage") or {}
                    accounting.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                    accounting.completion_tokens += int(
                        usage.get("completion_tokens") or 0
                    )
                    accounting.tool_calls += len(
                        (choice.get("message") or {}).get("tool_calls") or []
                    )
                    return ModelGeneration(
                        value, self.name, model, time.monotonic() - started, accounting
                    )
            except asyncio.CancelledError:
                raise
            except (json.JSONDecodeError, ValidationError):
                last_error = ModelProviderError(
                    "Model returned invalid structured output", "invalid_output"
                )
            except (httpx.TimeoutException, TimeoutError):
                last_error = ModelProviderError("Model request timed out", "timeout")
            except (httpx.HTTPError, ModelProviderError) as exc:
                last_error = exc
                if (
                    isinstance(exc, ModelProviderError)
                    and exc.classification == "request_rejected"
                ):
                    schema_mode = min(schema_mode + 1, 2)
            if attempt < self.max_retries:
                await asyncio.sleep(min(0.25 * 2**attempt, 1))
        if isinstance(last_error, ModelProviderError):
            raise last_error
        raise ModelProviderError("Structured generation failed")

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
            return {
                "provider": self.name,
                "healthy": response.is_success,
                "status_code": response.status_code,
            }
        except httpx.HTTPError as exc:
            return {
                "provider": self.name,
                "healthy": False,
                "error": type(exc).__name__,
            }


class MockProvider:
    name = "mock"

    def __init__(self, responses: list[dict | BaseModel] | None = None):
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    async def generate_structured(
        self,
        role: ModelRole,
        messages: list[dict[str, str]],
        response_schema: type[SchemaT],
        timeout: float,
        metadata: dict[str, Any] | None = None,
        model: str = "",
    ) -> ModelGeneration:
        self.calls.append(
            {"role": role, "messages": messages, "metadata": metadata, "model": model}
        )
        if not self.responses:
            raise ModelProviderError("Mock provider has no response", "mock_exhausted")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        value = (
            item
            if isinstance(item, response_schema)
            else response_schema.model_validate(item)
        )
        return ModelGeneration(
            value, self.name, model or "mock", 0, ModelAccounting(calls=1)
        )

    async def health(self) -> dict[str, Any]:
        return {"provider": self.name, "healthy": True}


class ProviderRouter:
    def __init__(
        self,
        providers: dict[str, ModelProvider],
        role_configs: dict[ModelRole, RoleConfig],
    ):
        self.providers = providers
        self.role_configs = role_configs

    async def generate(
        self,
        role: ModelRole,
        messages: list[dict[str, str]],
        response_schema: type[SchemaT],
        metadata: dict[str, Any] | None = None,
    ) -> ModelGeneration:
        config = self.role_configs[role]
        if not config.enabled:
            raise ModelProviderError(f"Role is disabled: {role}", "role_disabled")
        provider = self.providers.get(config.provider)
        if provider is None:
            raise ModelProviderError(
                f"Unknown provider: {config.provider}", "configuration"
            )
        errors = []
        for index, model in enumerate((config.model, *config.fallback_models)):
            if not model:
                continue
            try:
                result = await provider.generate_structured(
                    role,
                    messages,
                    response_schema,
                    config.timeout_seconds,
                    metadata,
                    model,
                )
                result.accounting.fallbacks.extend(
                    candidate
                    for candidate in (config.model, *config.fallback_models)[:index]
                )
                return result
            except ModelProviderError as exc:
                errors.append(f"{model}:{exc.classification}")
        raise ModelProviderError(
            f"All configured models failed ({', '.join(errors)})", "fallback_exhausted"
        )

    async def health(self) -> list[dict[str, Any]]:
        return await asyncio.gather(
            *(provider.health() for provider in self.providers.values())
        )


def role_configs_from_environment(
    default_model: str = "",
) -> dict[ModelRole, RoleConfig]:
    provider = os.getenv("MODEL_PROVIDER", "openrouter")
    timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))
    mapping = {
        ModelRole.REQUIREMENTS: "REQUIREMENTS",
        ModelRole.CALCULATIONS: "CALCULATIONS",
        ModelRole.PARAMETERS: "PARAMETERS",
        ModelRole.GEOMETRY: "GEOMETRY",
        ModelRole.SIMULATION: "SIMULATION",
        ModelRole.CRITIC: "CRITIC",
        ModelRole.CODE_REVIEW: "CODE_REVIEW",
        ModelRole.RESULTS_ANALYSIS: "RESULTS",
    }
    configs = {}
    for role, suffix in mapping.items():
        legacy_suffix = (
            "RF_REASONING"
            if role in {ModelRole.CALCULATIONS, ModelRole.PARAMETERS}
            else ""
        )
        model = os.getenv(f"MODEL_{suffix}", "")
        if not model and legacy_suffix:
            model = os.getenv(f"MODEL_{legacy_suffix}", "")
        fallback_text = os.getenv(f"MODEL_{suffix}_FALLBACKS", "")
        if not fallback_text and legacy_suffix:
            fallback_text = os.getenv(f"MODEL_{legacy_suffix}_FALLBACKS", "")
        configs[role] = RoleConfig(
            role=role,
            provider=provider,
            model=model or default_model,
            fallback_models=tuple(
                item.strip() for item in fallback_text.split(",") if item.strip()
            ),
            timeout_seconds=timeout,
            enabled=os.getenv(f"MODEL_{suffix}_ENABLED", "true").casefold() != "false",
        )
    return configs


_SECRET_PATTERN = re.compile(r"(sk-or-v1-|Bearer\s+)[A-Za-z0-9_.-]+", re.IGNORECASE)


def redact_secrets(value: str) -> str:
    return _SECRET_PATTERN.sub("[REDACTED]", value)


def _classify_http(status_code: int) -> str:
    if status_code in {401, 403}:
        return "authentication"
    if status_code == 429:
        return "rate_limit"
    if status_code >= 500:
        return "provider_unavailable"
    return "request_rejected"
