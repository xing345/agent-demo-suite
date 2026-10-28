from pathlib import Path
import sys


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


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    if missing:
        print("missing:")
        print("\n".join(missing))
        return 1
    print(f"skeleton ok: {len(REQUIRED)} required files found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
