import pytest

from packages.model_gateway import OpenAICompatibleGateway
from packages.model_gateway.openai_compatible import ModelGatewayError


def test_openai_compatible_provider_parses_chat_response() -> None:
    requests = []

    def fake_post(url, headers, payload, timeout):
        requests.append((url, headers, payload, timeout))
        return {"choices": [{"message": {"content": "plan result"}}]}

    provider = OpenAICompatibleGateway(
        base_url="https://example.test/v1",
        api_key="secret",
        model="demo-model",
        post_json=fake_post,
    )

    result = provider.generate_sync([{"role": "user", "content": "hello"}])

    assert result == "plan result"
    assert requests[0][0] == "https://example.test/v1/chat/completions"
    assert requests[0][1]["Authorization"] == "Bearer secret"
    assert requests[0][2]["model"] == "demo-model"


def test_openai_compatible_provider_raises_on_invalid_response() -> None:
    provider = OpenAICompatibleGateway(
        base_url="https://example.test/v1",
        api_key="secret",
        model="demo-model",
        post_json=lambda *args, **kwargs: {"error": {"message": "bad request"}},
    )

    with pytest.raises(ModelGatewayError, match="choices"):
        provider.generate_sync([])
