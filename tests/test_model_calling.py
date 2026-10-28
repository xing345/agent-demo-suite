"""Tool schema generation and tool-call parsing."""

from packages.model_gateway.calling import parse_tool_calls, tools_from_definitions
from packages.tool_registry import ToolDefinition


def test_tools_from_definitions_uses_function_shape() -> None:
    payload = tools_from_definitions(
        [
            ToolDefinition(
                name="read_context",
                description="Read context",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )
        ]
    )

    function = payload[0]["function"]
    assert payload[0]["type"] == "function"
    assert function["name"] == "read_context"
    assert function["description"] == "Read context"
    assert function["parameters"]["properties"]["query"]["type"] == "string"


def test_tools_from_definitions_defaults_to_object_schema() -> None:
    payload = tools_from_definitions([ToolDefinition(name="ping", input_schema={})])

    assert payload[0]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_parse_tool_calls_decodes_json_arguments() -> None:
    message = {
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_context", "arguments": '{"query": "README"}'},
            }
        ],
    }

    calls = parse_tool_calls(message)

    assert len(calls) == 1
    assert calls[0].name == "read_context"
    assert calls[0].arguments == {"query": "README"}
    assert calls[0].parse_error is None


def test_parse_tool_calls_keeps_malformed_arguments_raw() -> None:
    message = {
        "tool_calls": [
            {"id": "call_2", "function": {"name": "write", "arguments": "{not json"}}
        ]
    }

    calls = parse_tool_calls(message)

    assert calls[0].arguments == {}
    assert calls[0].raw_arguments == "{not json"
    assert calls[0].parse_error


def test_parse_tool_calls_handles_missing_arguments() -> None:
    message = {"tool_calls": [{"function": {"name": "ping"}}]}

    calls = parse_tool_calls(message)

    assert calls[0].arguments == {}
    assert calls[0].parse_error is None
    assert calls[0].id.startswith("call_")


def test_parse_tool_calls_returns_empty_for_plain_message() -> None:
    assert parse_tool_calls({"content": "hello"}) == []