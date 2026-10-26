from __future__ import annotations

from app.domains.model_gateway.adapters.openai_compatible import OpenAICompatibleAdapter
from app.domains.model_gateway.contracts import ProviderRequest


class StubResponse:
    status_code = 200
    headers = {"x-oneapi-request-id": "oneapi-request-123"}

    @staticmethod
    def json():
        return {
            "choices": [{"message": {"content": '```json\n{"status":"ok"}\n```'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        }


def test_openai_compatible_protocol_and_oneapi_request_id(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return StubResponse()

    monkeypatch.setattr(
        "app.domains.model_gateway.adapters.openai_compatible.httpx.post",
        fake_post,
    )
    response = OpenAICompatibleAdapter().invoke(ProviderRequest(
        endpoint="https://example.test/v1",
        api_key="test-only-key",
        model_id="example-model",
        system_prompt="Return JSON.",
        user_prompt="Check protocol.",
        connect_timeout_seconds=2,
        timeout_seconds=10,
    ))

    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-only-key"
    assert captured["json"]["model"] == "example-model"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert response.provider_request_id == "oneapi-request-123"
    assert response.content == '{"status":"ok"}'
    assert response.input_tokens == 12
    assert response.output_tokens == 5


def test_openai_compatible_adapter_does_not_strip_non_object_fences(monkeypatch):
    class ArrayFenceResponse(StubResponse):
        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "```json\n[1, 2]\n```"}}]}

    monkeypatch.setattr(
        "app.domains.model_gateway.adapters.openai_compatible.httpx.post",
        lambda *args, **kwargs: ArrayFenceResponse(),
    )
    response = OpenAICompatibleAdapter().invoke(ProviderRequest(
        endpoint="https://example.test/v1",
        api_key="test-only-key",
        model_id="example-model",
        system_prompt="Return JSON.",
        user_prompt="Check protocol.",
        connect_timeout_seconds=2,
        timeout_seconds=10,
    ))

    assert response.content == "```json\n[1, 2]\n```"


def test_openai_compatible_adapter_accepts_one_valid_object_with_provider_preamble(monkeypatch):
    class PreambleResponse(StubResponse):
        @staticmethod
        def json():
            return {
                "choices": [{"message": {"content": (
                    "Here's the JSON object you requested:\n\n"
                    "```json\n{\"status\":\"ok\"}\n```"
                )}}],
            }

    monkeypatch.setattr(
        "app.domains.model_gateway.adapters.openai_compatible.httpx.post",
        lambda *args, **kwargs: PreambleResponse(),
    )
    response = OpenAICompatibleAdapter().invoke(ProviderRequest(
        endpoint="https://example.test/v1",
        api_key="test-only-key",
        model_id="example-model",
        system_prompt="Return JSON.",
        user_prompt="Check protocol.",
        connect_timeout_seconds=2,
        timeout_seconds=10,
    ))

    assert response.content == '{"status":"ok"}'


def test_openai_compatible_adapter_keeps_ambiguous_multi_object_output(monkeypatch):
    ambiguous = (
        '{"outside":"object"}\n'
        '```json\n{"status":"ok"}\n```'
    )

    class AmbiguousResponse(StubResponse):
        @staticmethod
        def json():
            return {"choices": [{"message": {"content": ambiguous}}]}

    monkeypatch.setattr(
        "app.domains.model_gateway.adapters.openai_compatible.httpx.post",
        lambda *args, **kwargs: AmbiguousResponse(),
    )
    response = OpenAICompatibleAdapter().invoke(ProviderRequest(
        endpoint="https://example.test/v1",
        api_key="test-only-key",
        model_id="example-model",
        system_prompt="Return JSON.",
        user_prompt="Check protocol.",
        connect_timeout_seconds=2,
        timeout_seconds=10,
    ))

    assert response.content == ambiguous
