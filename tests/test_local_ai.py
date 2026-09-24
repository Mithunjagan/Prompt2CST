from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import httpx

from prompt2cst.local_ai import confirm_prompt_family
from prompt2cst.prompt_intent import family_mentions, resolve_explicit_family


def _client(response_text: str, *, status: int = 200, capture: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return httpx.Response(
            status, json={"done": True, "response": response_text}
        )

    return httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)


class PromptIntentTests(unittest.TestCase):
    def test_supported_family_phrasings_resolve_without_model(self):
        examples = {
            "wire dipole": "dipole",
            "quarter-wave monopole": "monopole",
            "patch": "patch",
            "planar inverted-F": "pifa",
            "axial-mode helix": "helix",
            "five-element Yagi": "yagi_uda",
            "horn": "horn",
            "tapered-slot Vivaldi": "vivaldi",
        }
        for phrase, expected in examples.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    resolve_explicit_family(f"Build a {phrase} antenna at 915 MHz"),
                    expected,
                )

    def test_longer_family_alias_wins_over_overlapping_slot(self):
        mentions = family_mentions("Build a tapered-slot Vivaldi antenna")
        self.assertEqual({mention.family for mention in mentions}, {"vivaldi"})

    def test_supported_alias_and_spec_are_canonical(self):
        self.assertEqual(resolve_explicit_family("A Yagi-Uda at 915 MHz"), "yagi_uda")
        self.assertEqual(resolve_explicit_family("A directional antenna", ["yagi"]), "yagi_uda")

    def test_research_only_and_ambiguous_requests_fail_closed(self):
        for prompt in (
            "Build a spiral antenna at 868 MHz",
            "Build a spiral at 868 MHz",
            "Build a parabolic reflector at 2.4 GHz",
            "Build a PIFA or a helix at 915 MHz",
        ):
            with self.subTest(prompt=prompt), self.assertRaises(ValueError):
                resolve_explicit_family(prompt)


class LocalAIValidationTests(unittest.TestCase):
    def test_confirmed_local_hint_is_advisory_and_no_arithmetic_is_requested(self):
        requests: list[httpx.Request] = []
        with _client('{"family":"pifa","quote":"PIFA"}', capture=requests) as client:
            result = confirm_prompt_family(
                "Design a PIFA at 868 MHz", "pifa", client=client
            )
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.confirmed_family, "pifa")
        sent = json.loads(requests[0].content)
        self.assertEqual(requests[0].url.host, "127.0.0.1")
        self.assertEqual(sent["options"]["num_gpu"], 0)
        self.assertEqual(sent["format"]["additionalProperties"], False)
        self.assertNotIn("frequency_hz", sent["format"]["properties"])

    def test_injected_fields_and_wrong_quotes_are_rejected(self):
        bad = (
            '{"family":"pifa","quote":"PIFA","python":"run me"}',
            '{"family":"pifa","quote":"not present"}',
            '{"family":"pifa","quote":"antenna"}',
        )
        for text in bad:
            with self.subTest(text=text), _client(text) as client:
                result = confirm_prompt_family(
                    "Design a PIFA antenna", "pifa", client=client
                )
                self.assertEqual(result.status, "invalid")

    def test_mismatch_and_abstention_cannot_change_selected_family(self):
        with _client('{"family":"pifa","quote":"PIFA"}') as client:
            self.assertEqual(
                confirm_prompt_family("PIFA antenna", "helix", client=client).status,
                "mismatch",
            )
        with _client('{"family":null,"quote":null}') as client:
            self.assertEqual(
                confirm_prompt_family("PIFA antenna", "pifa", client=client).status,
                "abstained",
            )

    def test_remote_endpoint_is_rejected_before_network_access(self):
        requests: list[httpx.Request] = []
        with patch.dict("os.environ", {"PROMPT2CST_OLLAMA_URL": "https://example.com"}):
            with _client('{"family":"pifa","quote":"PIFA"}', capture=requests) as client:
                with self.assertRaises(ValueError):
                    confirm_prompt_family("PIFA antenna", "pifa", client=client)
        self.assertEqual(requests, [])

    def test_http_failure_falls_back_without_prompt_or_response_in_result(self):
        with _client("", status=503) as client:
            result = confirm_prompt_family("PIFA antenna", "pifa", client=client)
        self.assertEqual(result.status, "unavailable")
        self.assertNotIn("PIFA antenna", str(result.to_dict()))
