import unittest
from unittest.mock import patch

from pydantic import BaseModel, ConfigDict

from prompt2cst.orchestration import (
    MockProvider,
    ModelProviderError,
    ModelRole,
    OpenAICompatibleProvider,
    ProviderRouter,
    RoleConfig,
    redact_secrets,
)


class StructuredAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str


class FakeStructuredResponse:
    is_success = True
    status_code = 200

    def json(self):
        return {
            "choices": [{"message": {"content": "not valid json"}}],
            "usage": {},
        }


class FakeStructuredClient:
    def __init__(self):
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, *_args, **_kwargs):
        self.calls += 1
        return FakeStructuredResponse()


class OrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_model_is_used(self):
        provider = MockProvider(
            [
                ModelProviderError("primary failed", "provider_unavailable"),
                {"answer": "fallback"},
            ]
        )
        config = RoleConfig(
            role=ModelRole.GEOMETRY,
            provider="mock",
            model="primary",
            fallback_models=("fallback",),
        )
        router = ProviderRouter({"mock": provider}, {ModelRole.GEOMETRY: config})
        result = await router.generate(
            ModelRole.GEOMETRY,
            [{"role": "user", "content": "plan"}],
            StructuredAnswer,
        )
        self.assertEqual(result.value.answer, "fallback")
        self.assertEqual(result.model, "fallback")
        self.assertEqual(result.accounting.fallbacks, ["primary"])

    async def test_invalid_structured_output_is_rejected(self):
        provider = MockProvider([{"wrong": "field"}])
        config = RoleConfig(
            role=ModelRole.REQUIREMENTS,
            provider="mock",
            model="mock",
        )
        router = ProviderRouter({"mock": provider}, {ModelRole.REQUIREMENTS: config})
        with self.assertRaises(Exception):
            await router.generate(
                ModelRole.REQUIREMENTS,
                [{"role": "user", "content": "parse"}],
                StructuredAnswer,
            )

    async def test_invalid_provider_output_is_retried_then_rejected(self):
        client = FakeStructuredClient()
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://provider.invalid/v1",
            max_retries=1,
        )
        with patch(
            "prompt2cst.orchestration.httpx.AsyncClient",
            return_value=client,
        ):
            with self.assertRaisesRegex(
                ModelProviderError,
                "invalid structured output",
            ):
                await provider.generate_structured(
                    ModelRole.REQUIREMENTS,
                    [{"role": "user", "content": "parse"}],
                    StructuredAnswer,
                    timeout=1,
                    model="test-model",
                )
        self.assertEqual(client.calls, 2)

    def test_secret_redaction(self):
        redacted = redact_secrets(
            "Authorization: Bearer abc.def and " + "sk-or-" + "v1-supersecretvalue"
        )
        self.assertNotIn("abc.def", redacted)
        self.assertNotIn("supersecretvalue", redacted)


if __name__ == "__main__":
    unittest.main()
