"""SSE parsing and stream assembly."""

from packages.model_gateway.streaming import StreamAssembler, iter_sse_events


def test_sse_parser_ignores_comments_and_stops_at_done() -> None:
    lines = [
        ": keepalive",
        "",
        'data: {"a": 1}',
        "",
        "event: ping",
        'data: {"b": 2}',
        "",
        "data: [DONE]",
        "",
        'data: {"c": 3}',
    ]

    assert list(iter_sse_events(lines)) == [{"a": 1}, {"b": 2}]


def test_assembler_concatenates_content_and_usage() -> None:
    assembler = StreamAssembler()
    assembler.feed({"model": "demo", "choices": [{"delta": {"content": "Hel"}}]})
    assembler.feed({"choices": [{"delta": {"content": "lo"}}]})
    assembler.feed(
        {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
    )

    result = assembler.result()

    assert result.content == "Hello"
    assert result.model == "demo"
    assert result.usage.input_tokens == 3
    assert result.usage.output_tokens == 2
    assert result.usage.total_tokens == 5
    assert result.usage.source == "provider"


def test_assembler_merges_tool_call_deltas() -> None:
    assembler = StreamAssembler()
    assembler.feed(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_context", "arguments": '{"q":'},
                            }
                        ]
                    }
                }
            ]
        }
    )
    assembler.feed(
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]}}
            ]
        }
    )

    calls = assembler.result().tool_calls

    assert len(calls) == 1
    assert calls[0].id == "call_1"
    assert calls[0].name == "read_context"
    assert calls[0].arguments == {"q": 1}


def test_assembler_without_usage_reports_unavailable() -> None:
    assembler = StreamAssembler()
    assembler.feed({"choices": [{"delta": {"content": "x"}}]})

    assert assembler.result().usage.source == "unavailable"
    assert assembler.result().usage.cost_usd is None