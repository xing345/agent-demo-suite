import pytest

from packages.tool_registry import ToolDefinition, ToolRegistry


def test_registry_returns_registered_tool() -> None:
    registry = ToolRegistry()
    definition = registry.register(
        ToolDefinition(
            name="read_file",
            source="builtin",
            permission="read",
            input_schema={"type": "object"},
        )
    )

    assert registry.get("read_file") == definition


def test_registry_rejects_duplicate_name() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="read_file"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(ToolDefinition(name="read_file"))
