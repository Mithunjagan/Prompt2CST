from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
import json
import sys
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MAX_AGENT_STEPS = 8
MCP_TIMEOUT_SECONDS = 20

SYSTEM_PROMPT = """
You are the antenna-design assistant inside Prompt2CST.

Use the Prompt2CST tools for calculations and CST actions. Always preview a
design before requesting a build. Never invent dimensions that a preview tool
can calculate. Never call a test-brick tool for a different antenna type.
Call antenna_catalog if the requested antenna family or required capability is
unclear. Prefer dedicated family tools. Use the custom parametric tool only
when the design can be represented with its validated primitives. Never claim
that "any antenna" is supported. Clearly state that current builds do not run
the solver, optimize the antenna or validate S-parameters.

Only request a build when the user explicitly asks to create a CST project.
The desktop application independently asks the user for confirmation before
any CST-writing tool can execute.
""".strip()

WRITE_TOOLS = {
    "build_test_brick",
    "build_rectangular_patch",
    "build_wire_monopole",
    "build_center_fed_dipole",
    "build_parametric_antenna",
}
PREVIEW_FOR_WRITE = {
    "build_test_brick": "preview_test_brick",
    "build_rectangular_patch": "preview_rectangular_patch",
    "build_wire_monopole": "preview_wire_monopole",
    "build_center_fed_dipole": "preview_center_fed_dipole",
    "build_parametric_antenna": "preview_parametric_antenna",
}

LogCallback = Callable[[str], None]
ApprovalCallback = Callable[[str, dict[str, Any], dict[str, Any]], bool]


class Prompt2CSTAgentError(RuntimeError):
    pass


def format_exception_details(exc: BaseException) -> str:
    """Flatten TaskGroup exception wrappers into useful leaf errors."""

    details: list[str] = []

    def visit(current: BaseException) -> None:
        nested = getattr(current, "exceptions", None)
        if nested:
            for child in nested:
                visit(child)
            return

        message = str(current).strip()
        detail = type(current).__name__
        if message:
            detail = f"{detail}: {message}"
        if detail not in details:
            details.append(detail)

    visit(exc)
    return "\n".join(details) or type(exc).__name__


def is_write_tool(tool_name: str) -> bool:
    return tool_name in WRITE_TOOLS


def preview_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "build_test_brick":
        return {}
    if tool_name == "build_rectangular_patch":
        allowed = {
            "frequency_ghz",
            "relative_permittivity",
            "substrate_height_mm",
            "loss_tangent",
            "conductor_thickness_mm",
            "feed_impedance_ohm",
            "estimated_edge_resistance_ohm",
            "inset_gap_mm",
        }
        return {key: value for key, value in arguments.items() if key in allowed}
    if tool_name == "build_wire_monopole":
        allowed = {
            "frequency_ghz",
            "wire_length_mm",
            "wire_radius_mm",
            "ground_size_mm",
            "ground_thickness_mm",
            "feed_gap_mm",
            "port_impedance_ohm",
            "sweep_start_ghz",
            "sweep_stop_ghz",
        }
        return {key: value for key, value in arguments.items() if key in allowed}
    if tool_name == "build_center_fed_dipole":
        allowed = {
            "frequency_ghz",
            "total_conductor_length_mm",
            "wire_radius_mm",
            "feed_gap_mm",
            "port_impedance_ohm",
            "sweep_start_ghz",
            "sweep_stop_ghz",
        }
        return {key: value for key, value in arguments.items() if key in allowed}
    if tool_name == "build_parametric_antenna":
        if "spec" not in arguments:
            raise ValueError(
                "build_parametric_antenna requires a complete spec"
            )
        return {"spec": arguments["spec"]}
    raise ValueError(f"No preview mapping exists for {tool_name}")


def parse_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    if raw_arguments in (None, ""):
        return {}
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not isinstance(raw_arguments, str):
        raise ValueError("Tool arguments must be a JSON object")

    parsed = json.loads(raw_arguments)
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must decode to a JSON object")
    return parsed


def mcp_tool_to_openrouter(tool: Any) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }


def filter_tool_capable_models(payload: dict[str, Any]) -> list[str]:
    models = []
    for item in payload.get("data", []):
        model_id = item.get("id")
        supported = item.get("supported_parameters") or []
        if model_id and "tools" in supported:
            models.append(model_id)
    return sorted(set(models), key=str.casefold)


def _tool_result_to_python(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured

    text_parts = []
    for block in getattr(result, "content", []):
        text = getattr(block, "text", None)
        if text is not None:
            text_parts.append(text)

    combined = "\n".join(text_parts)
    if combined:
        try:
            parsed = json.loads(combined)
            if isinstance(parsed, dict):
                return parsed
            return {"result": parsed}
        except json.JSONDecodeError:
            return {"text": combined}

    return {"error": "The MCP tool returned no readable content."}


@asynccontextmanager
async def prompt2cst_session():
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "prompt2cst.server"],
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await _with_timeout(
                session.initialize(),
                MCP_TIMEOUT_SECONDS,
                "Local MCP initialization",
            )
            yield session


class OpenRouterAgent:
    def __init__(
        self,
        api_key: str,
        model: str,
        log: LogCallback | None = None,
        base_url: str = OPENROUTER_BASE_URL,
    ) -> None:
        if not api_key.strip():
            raise ValueError("An OpenRouter API key is required")
        if not model.strip():
            raise ValueError("An OpenRouter model ID is required")

        self.api_key = api_key.strip()
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.log = log or (lambda _message: None)

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": "Prompt2CST",
        }

    async def list_models(self) -> list[str]:
        timeout = httpx.Timeout(30.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{self.base_url}/models",
                headers=self.headers,
            )
            await _raise_for_openrouter_error(response)
            return filter_tool_capable_models(response.json())

    async def run(
        self,
        user_prompt: str,
        approve_write: ApprovalCallback,
    ) -> str:
        if not user_prompt.strip():
            raise ValueError("Enter an antenna request")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt.strip()},
        ]

        self.log("Starting local Prompt2CST MCP server")
        async with prompt2cst_session() as session:
            self.log("MCP initialized; discovering tools")
            listed = await _with_timeout(
                session.list_tools(),
                MCP_TIMEOUT_SECONDS,
                "MCP tool discovery",
            )
            tools = [mcp_tool_to_openrouter(tool) for tool in listed.tools]
            self.log(f"Discovered {len(tools)} MCP tools")
            previews: dict[str, dict[str, Any]] = {}

            timeout = httpx.Timeout(75.0, connect=15.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                for step in range(1, MAX_AGENT_STEPS + 1):
                    self.log(
                        f"OpenRouter request {step}/{MAX_AGENT_STEPS} "
                        f"using {self.model}"
                    )
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self.headers,
                        json={
                            "model": self.model,
                            "messages": messages,
                            "tools": tools,
                            "tool_choice": "auto",
                            "temperature": 0.1,
                        },
                    )
                    await _raise_for_openrouter_error(response)
                    message = _extract_message(response.json())
                    tool_calls = message.get("tool_calls") or []

                    assistant_message: dict[str, Any] = {
                        "role": "assistant",
                        "content": message.get("content"),
                    }
                    if tool_calls:
                        assistant_message["tool_calls"] = tool_calls
                    messages.append(assistant_message)

                    if not tool_calls:
                        content = message.get("content")
                        if isinstance(content, str) and content.strip():
                            return content.strip()
                        return "The selected model returned an empty response."

                    for tool_call in tool_calls:
                        tool_call_id = tool_call.get("id", "")
                        function = tool_call.get("function") or {}
                        tool_name = function.get("name", "")

                        try:
                            arguments = parse_tool_arguments(
                                function.get("arguments")
                            )
                            result = await self._call_tool_safely(
                                session=session,
                                tool_name=tool_name,
                                arguments=arguments,
                                previews=previews,
                                approve_write=approve_write,
                            )
                        except Exception as exc:
                            result = {
                                "status": "tool_error",
                                "write_performed": False,
                                "error": f"{type(exc).__name__}: {exc}",
                            }

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "name": tool_name,
                                "content": json.dumps(
                                    result,
                                    ensure_ascii=False,
                                    default=str,
                                ),
                            }
                        )

        raise Prompt2CSTAgentError(
            f"The model exceeded {MAX_AGENT_STEPS} tool-use steps."
        )

    async def _call_tool_safely(
        self,
        session: ClientSession,
        tool_name: str,
        arguments: dict[str, Any],
        previews: dict[str, dict[str, Any]],
        approve_write: ApprovalCallback,
    ) -> dict[str, Any]:
        if is_write_tool(tool_name):
            preview_name = PREVIEW_FOR_WRITE[tool_name]
            preview_key = json.dumps(
                [preview_name, preview_arguments(tool_name, arguments)],
                sort_keys=True,
            )
            preview = previews.get(preview_key)
            if preview is None:
                self.log(f"Previewing before write: {preview_name}")
                preview_result = await _with_timeout(
                    session.call_tool(
                        preview_name,
                        arguments=preview_arguments(tool_name, arguments),
                    ),
                    MCP_TIMEOUT_SECONDS,
                    f"MCP tool {preview_name}",
                )
                preview = _tool_result_to_python(preview_result)
                previews[preview_key] = preview

            proposed_arguments = dict(arguments)
            proposed_arguments["confirm"] = True
            if not approve_write(tool_name, proposed_arguments, preview):
                self.log(f"User denied CST write: {tool_name}")
                return {
                    "status": "user_denied",
                    "write_performed": False,
                    "message": "The user denied the requested CST write.",
                    "preview": preview,
                }
            arguments = proposed_arguments

        self.log(f"Calling MCP tool: {tool_name}")
        result = await _with_timeout(
            session.call_tool(tool_name, arguments=arguments),
            MCP_TIMEOUT_SECONDS,
            f"MCP tool {tool_name}",
        )
        python_result = _tool_result_to_python(result)

        if tool_name.startswith("preview_"):
            preview_key = json.dumps([tool_name, arguments], sort_keys=True)
            previews[preview_key] = python_result
        return python_result


def _extract_message(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices") or []
    if not choices:
        raise Prompt2CSTAgentError("OpenRouter returned no response choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise Prompt2CSTAgentError("OpenRouter returned an invalid message")
    return message


async def _raise_for_openrouter_error(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        details = response.json()
    except ValueError:
        details = response.text
    raise Prompt2CSTAgentError(
        f"OpenRouter HTTP {response.status_code}: {details}"
    )


async def _with_timeout(awaitable, timeout_seconds: float, label: str):
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as exc:
        raise Prompt2CSTAgentError(
            f"{label} timed out after {timeout_seconds:g} seconds"
        ) from exc
