"""Cheap structural smoke check used by CI and by the README quickstart."""

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "pyproject.toml",
    "packages/event_store/models.py",
    "packages/event_store/store.py",
    "packages/tool_registry/registry.py",
    "packages/model_gateway/base.py",
    "apps/runtime_harness/main.py",
    "apps/multimodal_lora/main.py",
    "tests/test_runtime_api.py",
    "tests/test_multimodal_api.py",
]
MODULES = [
    "packages.event_store",
    "packages.tool_registry",
    "packages.skill_registry",
    "packages.model_gateway",
    "packages.mcp_server",
    "packages.shared_config",
    "apps.runtime_harness.main",
    "apps.multimodal_lora.main",
]


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    if missing:
        print("missing:")
        print("\n".join(missing))
        return 1

    sys.path.insert(0, str(ROOT))
    failures: list[str] = []
    for module in MODULES:
        try:
            importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 - report every import failure
            failures.append(f"{module}: {type(exc).__name__}: {exc}")
    if failures:
        print("unimportable:")
        print("\n".join(failures))
        return 1

    print(
        f"skeleton ok: {len(REQUIRED)} required files found, "
        f"{len(MODULES)} modules importable"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())