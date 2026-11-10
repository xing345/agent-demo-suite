"""Shared test fixtures.

The runtime application currently builds its store and engine at import time.
Until dependency injection lands (stage 3), every test starts from an empty
store so that cases cannot leak state into each other.

测试必须与开发者的 ``.env`` 隔离
------------------------------
``apps.runtime_harness.main`` 在**模块导入时**读 Settings 决定用哪个 planner：
配了模型就 ``ModelPlanner``，没配就 ``DeterministicPlanner``。

于是本机一旦存在配了 API Key 的 ``.env``，测试就会去调真实模型，
"读取代码" 这种任务被模型拆成四步，断言 ``== ["completed"]`` 就地失败——
**测试通过与否取决于这台机器上有没有 .env**，这比测试失败本身更糟。

所以这里在 import 应用之前先把模型相关环境变量钉死。

注意 ``Settings`` 用的是 ``SettingsConfigDict(env_file=".env")``，
**pydantic-settings 的优先级是：进程环境变量 > .env 文件**。
因此只要在这里注入环境变量，``.env`` 就盖不掉它。
"""
from collections.abc import Iterator
import os

import pytest

# 必须在导入应用之前执行——planner 是导入期决定的
for _key in (
    "MODEL_PROVIDER",
    "MODEL_BASE_URL",
    "MODEL_API_KEY",
    "MODEL_NAME",
):
    os.environ[_key] = ""
os.environ["MODEL_PROVIDER"] = "none"

from apps.runtime_harness import main as runtime_main  # noqa: E402


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