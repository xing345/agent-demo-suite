from .models import SkillDefinition


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, definition: SkillDefinition) -> SkillDefinition:
        if definition.name in self._skills:
            raise ValueError(f"skill already registered: {definition.name}")
        self._skills[definition.name] = definition
        return definition

    def get(self, name: str) -> SkillDefinition:
        return self._skills[name]

    def list(self) -> list[SkillDefinition]:
        return list(self._skills.values())
