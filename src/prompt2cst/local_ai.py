"""Opt-in, localhost-only Ollama advice for prompt-family confirmation.

The model never supplies frequency arithmetic, geometry, RF predictions, paths,
or executable actions. Its output is accepted only when independently supported
by a curated family mention in the user's original prompt.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .prompt_intent import family_mentions

SupportedFamily = Literal[
    "dipole", "monopole", "patch", "pifa", "helix", "yagi_uda", "horn", "vivaldi"
]


class FamilyHint(BaseModel):
    """The only fields accepted from the local model."""

    model_config = ConfigDict(extra="forbid", strict=True)
    family: SupportedFamily | None
    quote: str | None = Field(max_length=160)


@dataclass(frozen=True)
class LocalAIResult:
    status: Literal["confirmed", "abstained", "unavailable", "invalid", "mismatch"]
    model: str
    confirmed_family: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "model": self.model,
            "confirmed_family": self.confirmed_family,
            "role": "advisory_only_no_rf_or_geometry_authority",
        }


def _endpoint() -> str:
    raw = os.getenv("PROMPT2CST_OLLAMA_URL", "http://127.0.0.1:11434")
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Ollama endpoint must be http://127.0.0.1:<port>")
    return f"http://127.0.0.1:{parsed.port}"


def _model_name() -> str:
    model = os.getenv("PROMPT2CST_OLLAMA_MODEL", "qwen3:0.6b")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", model):
        raise ValueError("Invalid local Ollama model name")
    return model


def _server_healthy(client: httpx.Client, endpoint: str) -> bool:
    try:
        response = client.get(f"{endpoint}/api/version", timeout=1.5)
        return response.status_code == 200 and isinstance(response.json().get("version"), str)
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


def _start_local_server(client: httpx.Client, endpoint: str) -> bool:
    if _server_healthy(client, endpoint):
        return True
    configured = os.getenv("PROMPT2CST_OLLAMA_EXE")
    executable = configured or shutil.which("ollama")
    if not executable or not Path(executable).is_file():
        return False
    environment = os.environ.copy()
    environment["OLLAMA_HOST"] = f"127.0.0.1:{urlsplit(endpoint).port}"
    environment["OLLAMA_NO_CLOUD"] = "1"
    try:
        subprocess.Popen(
            [str(Path(executable).resolve()), "serve"],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False
    for _ in range(25):
        time.sleep(0.2)
        if _server_healthy(client, endpoint):
            return True
    return False


def confirm_prompt_family(
    prompt: str,
    expected_family: str | None,
    *,
    client: httpx.Client | None = None,
) -> LocalAIResult:
    """Request one model hint, then independently validate it against input.

    Network and model errors safely fall back to the deterministic plan. A bad
    endpoint configuration fails closed instead of allowing a remote request.
    """
    endpoint = _endpoint()
    model = _model_name()
    if not prompt.strip() or len(prompt) > 4000:
        return LocalAIResult("invalid", model)
    owned = client is None
    if owned:
        client = httpx.Client(trust_env=False, timeout=httpx.Timeout(20.0, connect=2.0))
    assert client is not None
    try:
        if owned and not _start_local_server(client, endpoint):
            return LocalAIResult("unavailable", model)
        payload = {
            "model": model,
            "prompt": prompt,
            "system": (
                "Identify only an explicitly named antenna family. Return family as one "
                "of dipole, monopole, patch, pifa, helix, yagi_uda, horn, vivaldi, "
                "or null. Quote the exact words in the request naming that family, "
                "or null. Never infer a topology or calculate frequency, dimensions, "
                "gain, efficiency, or S11. Return only the specified JSON object."
            ),
            "format": FamilyHint.model_json_schema(),
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_ctx": 1024, "num_predict": 96, "num_gpu": 0},
        }
        response = client.post(f"{endpoint}/api/generate", json=payload)
        response.raise_for_status()
    except httpx.HTTPError:
        return LocalAIResult("unavailable", model)
    finally:
        if owned:
            client.close()

    try:
        body = response.json()
        if not isinstance(body, dict) or body.get("done") is not True:
            return LocalAIResult("invalid", model)
        raw = body.get("response")
        if not isinstance(raw, str) or len(raw) > 2048:
            return LocalAIResult("invalid", model)
        hint = FamilyHint.model_validate_json(raw)
    except (ValueError, ValidationError, AttributeError):
        return LocalAIResult("invalid", model)

    if hint.family is None and hint.quote is None:
        return LocalAIResult("abstained", model)
    if not hint.family or not hint.quote:
        return LocalAIResult("invalid", model)
    if hint.quote.casefold() not in prompt.casefold():
        return LocalAIResult("invalid", model)
    cited = any(
        mention.family == hint.family and mention.quote.casefold() in hint.quote.casefold()
        for mention in family_mentions(prompt)
    )
    if not cited:
        return LocalAIResult("invalid", model)
    if hint.family != expected_family:
        return LocalAIResult("mismatch", model)
    return LocalAIResult("confirmed", model, hint.family)
