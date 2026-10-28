"""Shared test fixtures.

The runtime application currently builds its store and engine at import time.
Until dependency injection lands (stage 3), every test starts from an empty
store so that cases cannot leak state into each other.
"""

from collections.abc import Iterator

import pytest

from apps.runtime_harness import main as runtime_main


@pytest.fixture(autouse=True)
def isolated_runtime_state() -> Iterator[None]:
    store = runtime_main.store
    for attribute in ("sessions", "runs", "tasks"):
        getattr(store, attribute, {}).clear()
    for attribute in ("events", "checkpoints"):
        mapping = getattr(store, attribute, None)
        if mapping is not None:
            mapping.clear()
    yield