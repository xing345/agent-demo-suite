import pytest

from packages.skill_registry import SkillDefinition, SkillRegistry


def test_skill_registry_registers_and_lists_skill() -> None:
    registry = SkillRegistry()
    skill = registry.register(
        SkillDefinition(
            name="repo_diagnosis",
            description="Diagnose a repository issue",
            prompt_template="Read {path} and summarize the issue.",
            tool_names=["read_context"],
        )
    )

    assert registry.get("repo_diagnosis") == skill
    assert registry.list()[0].name == "repo_diagnosis"


def test_skill_registry_rejects_duplicate_name() -> None:
    registry = SkillRegistry()
    registry.register(SkillDefinition(name="repo_diagnosis"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(SkillDefinition(name="repo_diagnosis"))
