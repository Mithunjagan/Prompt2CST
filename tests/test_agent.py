import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

from prompt2cst.agent import (
    OpenRouterAgent,
    filter_tool_capable_models,
    format_exception_details,
    is_write_tool,
    mcp_tool_to_openrouter,
    parse_tool_arguments,
    preview_arguments,
)


class FakeResponse:
    is_success = True
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeHTTPClient:
    def __init__(self, responses):
        self.responses = iter(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, _type, _value, _traceback):
        return None

    async def post(self, *_args, **_kwargs):
        return FakeResponse(next(self.responses))


class FakeMCPSession:
    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="preview_test_brick",
                    description="Preview",
                    inputSchema={"type": "object", "properties": {}},
                ),
                SimpleNamespace(
                    name="build_test_brick",
                    description="Build",
                    inputSchema={"type": "object", "properties": {}},
                ),
            ]
        )

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "preview_test_brick":
            return SimpleNamespace(
                structuredContent={
                    "write_performed": False,
                    "dimensions_mm": {"x": 10, "y": 10, "z": 1},
                }
            )
        return SimpleNamespace(
            structuredContent={
                "status": "created",
                "write_performed": True,
            }
        )


def agent_responses():
    return [
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "build_test_brick",
                                    "arguments": '{"project_name":"safe_test"}',
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": "Finished.",
                    }
                }
            ]
        },
    ]


class AgentSafetyTests(unittest.TestCase):
    def test_task_group_error_exposes_leaf_exception(self):
        error = ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [
                RuntimeError("OpenRouter HTTP 429: free-model rate limit"),
                ValueError("secondary detail"),
            ],
        )

        formatted = format_exception_details(error)

        self.assertIn(
            "RuntimeError: OpenRouter HTTP 429: free-model rate limit",
            formatted,
        )
        self.assertIn("ValueError: secondary detail", formatted)
        self.assertNotIn("ExceptionGroup", formatted)

    def test_filters_only_tool_capable_models(self):
        payload = {
            "data": [
                {"id": "vendor/tool-model", "supported_parameters": ["tools"]},
                {"id": "vendor/chat-only", "supported_parameters": ["temperature"]},
                {
                    "id": "vendor/tool-and-json",
                    "supported_parameters": ["tools", "structured_outputs"],
                },
            ]
        }
        self.assertEqual(
            filter_tool_capable_models(payload),
            ["vendor/tool-and-json", "vendor/tool-model"],
        )

    def test_mcp_schema_becomes_openrouter_function(self):
        tool = SimpleNamespace(
            name="preview_test_brick",
            description="Preview a brick",
            inputSchema={"type": "object", "properties": {}},
        )
        converted = mcp_tool_to_openrouter(tool)
        self.assertEqual(converted["type"], "function")
        self.assertEqual(
            converted["function"]["name"],
            "preview_test_brick",
        )
        self.assertEqual(
            converted["function"]["parameters"]["type"],
            "object",
        )

    def test_tool_arguments_must_be_json_object(self):
        self.assertEqual(
            parse_tool_arguments('{"frequency_ghz": 2.45}'), {"frequency_ghz": 2.45}
        )
        with self.assertRaises(ValueError):
            parse_tool_arguments(json.dumps([1, 2, 3]))

    def test_write_tools_are_explicitly_classified(self):
        self.assertTrue(is_write_tool("build_test_brick"))
        self.assertTrue(is_write_tool("build_rectangular_patch"))
        self.assertTrue(is_write_tool("build_wire_monopole"))
        self.assertTrue(is_write_tool("build_center_fed_dipole"))
        self.assertTrue(is_write_tool("build_parametric_antenna"))
        self.assertFalse(is_write_tool("preview_rectangular_patch"))
        self.assertFalse(is_write_tool("cst_status"))

    def test_build_arguments_are_reduced_for_preview(self):
        arguments = {
            "project_name": "demo",
            "frequency_ghz": 5.8,
            "relative_permittivity": 4.3,
            "include_boundary_setup": True,
            "overwrite": True,
            "confirm": True,
        }
        self.assertEqual(
            preview_arguments("build_rectangular_patch", arguments),
            {
                "frequency_ghz": 5.8,
                "relative_permittivity": 4.3,
            },
        )

    def test_monopole_build_arguments_are_reduced_for_preview(self):
        arguments = {
            "project_name": "monopole",
            "frequency_ghz": 2.45,
            "wire_length_mm": 30.6,
            "wire_radius_mm": 0.612,
            "include_port": True,
            "include_farfield_monitor": True,
            "overwrite": False,
            "confirm": True,
        }
        self.assertEqual(
            preview_arguments("build_wire_monopole", arguments),
            {
                "frequency_ghz": 2.45,
                "wire_length_mm": 30.6,
                "wire_radius_mm": 0.612,
            },
        )

    def test_parametric_build_keeps_only_complete_spec_for_preview(self):
        spec = {
            "title": "Simple dipole",
            "frequency_ghz": 2.45,
            "sweep_start_ghz": 2.0,
            "sweep_stop_ghz": 3.0,
            "solids": [
                {
                    "kind": "cylinder",
                    "name": "Arm",
                    "outer_radius_mm": 0.5,
                    "axis_min_mm": 0.75,
                    "axis_max_mm": 31.35,
                }
            ],
        }
        arguments = {
            "project_name": "custom",
            "spec": spec,
            "overwrite": True,
            "confirm": True,
        }
        self.assertEqual(
            preview_arguments("build_parametric_antenna", arguments),
            {"spec": spec},
        )


class AgentLoopSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_denial_prevents_cst_write(self):
        session = FakeMCPSession()

        @asynccontextmanager
        async def fake_session():
            yield session

        client = FakeHTTPClient(agent_responses())
        with (
            patch("prompt2cst.agent.prompt2cst_session", fake_session),
            patch("prompt2cst.agent.httpx.AsyncClient", return_value=client),
        ):
            result = await OpenRouterAgent("key", "model").run(
                "Build a test brick",
                approve_write=lambda *_args: False,
            )

        self.assertEqual(result, "Finished.")
        self.assertEqual(session.calls, [("preview_test_brick", {})])

    async def test_approval_forces_confirm_true_after_preview(self):
        session = FakeMCPSession()
        approval_requests = []

        @asynccontextmanager
        async def fake_session():
            yield session

        def approve(name, arguments, preview):
            approval_requests.append((name, arguments, preview))
            return True

        client = FakeHTTPClient(agent_responses())
        with (
            patch("prompt2cst.agent.prompt2cst_session", fake_session),
            patch("prompt2cst.agent.httpx.AsyncClient", return_value=client),
        ):
            result = await OpenRouterAgent("key", "model").run(
                "Build a test brick",
                approve_write=approve,
            )

        self.assertEqual(result, "Finished.")
        self.assertEqual(session.calls[0], ("preview_test_brick", {}))
        self.assertEqual(session.calls[1][0], "build_test_brick")
        self.assertTrue(session.calls[1][1]["confirm"])
        self.assertEqual(approval_requests[0][0], "build_test_brick")
        self.assertFalse(approval_requests[0][2]["write_performed"])


if __name__ == "__main__":
    unittest.main()
