"""Gateway I/O: usage capture, structured output and streaming."""

from pydantic import BaseModel

from packages.model_gateway import OpenAICompatibleGateway
from packages.model_gateway.usage import PriceTable


class Answer(BaseModel):
    answer: int


def _gateway(**kwargs):
    defaults = dict(
        base_url="https://example.test/v1",
        api_key="secret",
        model="demo",
    )
    defaults.update(kwargs)
    return OpenAICompatibleGateway(**defaults)


def test_complete_captures_usage_tool_calls_and_cost() -> None:
    def fake_post(url, headers, payload, timeout):
        return {
            "model": "demo",
            "choices": [
                {
                    "message": {
                        "content": "hi",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"name": "read_context", "arguments": '{"q": 1}'},
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        }

    result = _gateway(post_json=fake_post, prices=PriceTable({"demo": (1.0, 2.0)})).complete(
        [{"role": "user", "content": "hi"}]
    )

    assert result.content == "hi"
    assert result.usage.total_tokens == 1500
    assert result.usage.cost_usd == 0.002
    assert result.tool_calls[0].arguments == {"q": 1}


def test_complete_with_response_model_returns_structured_payload() -> None:
    def fake_post(url, headers, payload, timeout):
        assert payload["response_format"]["type"] == "json_schema"
        return {"choices": [{"message": {"content": '{"answer": 42}'}}]}

    result = _gateway(post_json=fake_post).complete(
        [{"role": "user", "content": "hi"}], response_model=Answer
    )

    assert isinstance(result.structured, Answer)
    assert result.structured.answer == 42


def test_stream_sync_yields_text_deltas_and_final_usage() -> None:
    lines = [
        'data: {"model": "demo", "choices": [{"delta": {"content": "Hel"}}]}',
        "",
        'data: {"choices": [{"delta": {"content": "lo"}}]}',
        "",
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], '
        '"usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}',
        "",
        "data: [DONE]",
        "",
    ]

    gateway = _gateway(post_stream=lambda url, headers, payload, timeout: iter(lines))

    deltas = list(gateway.stream_sync([{"role": "user", "content": "hi"}]))

    assert "".join(delta.text for delta in deltas) == "Hello"
    assert gateway.last_stream_result is not None
    assert gateway.last_stream_result.usage.total_tokens == 5


def test_stream_falls_back_when_provider_does_not_support_it() -> None:
    def fake_post(url, headers, payload, timeout):
        return {"choices": [{"message": {"content": "plain"}}]}

    gateway = _gateway(post_json=fake_post, supports_streaming=False)

    deltas = list(gateway.stream_sync([{"role": "user", "content": "hi"}]))

    assert [delta.text for delta in deltas] == ["plain"]