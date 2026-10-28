# Remote Runtime Integration 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 接入 OpenAI-compatible Model Provider、远程 HTTP JSON MCP Transport，并让 Planner 生成的任务由 Runtime 按依赖顺序执行、记录事件和保存恢复状态。

**架构：** Model Gateway 通过可注入的 HTTP 函数调用 `/chat/completions`，MCP Remote Client 通过可注入的 HTTP 函数调用远程工具端点。RuntimeExecutor 接收 `TaskPlan`，按依赖顺序调用本地工具、远程 MCP 工具或模型 Provider，并把每个任务的状态写入 EventStore。

**技术栈：** Python 3.12、FastAPI、Pydantic v2、标准库 `urllib`、pytest。

---

### 任务 1：配置和模型 Provider

**文件：**
- 修改：`packages/shared_config/settings.py`
- 修改：`.env.example`
- 修改：`packages/model_gateway/base.py`
- 创建：`packages/model_gateway/openai_compatible.py`
- 修改：`packages/model_gateway/__init__.py`
- 测试：`tests/test_model_gateway.py`

- [ ] **步骤 1：编写失败测试**

覆盖三种行为：Provider 生成请求包含 model/messages/tools；兼容响应能提取文本；HTTP 错误抛出明确异常。

```python
def test_openai_compatible_provider_parses_chat_response():
    requests = []

    def fake_post(url, headers, payload, timeout):
        requests.append((url, headers, payload, timeout))
        return {"choices": [{"message": {"content": "plan result"}}]}

    provider = OpenAICompatibleGateway(
        base_url="https://example.test/v1",
        api_key="secret",
        model="demo-model",
        post_json=fake_post,
    )

    result = asyncio.run(provider.generate([{"role": "user", "content": "hello"}]))

    assert result == "plan result"
    assert requests[0][2]["model"] == "demo-model"
    assert requests[0][1]["Authorization"] == "Bearer secret"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest tests/test_model_gateway.py -q`

预期：因 `OpenAICompatibleGateway` 尚未定义而失败。

- [ ] **步骤 3：实现最小 Provider**

新增 `OpenAICompatibleGateway(ModelGateway)`，接受 `base_url`、`api_key`、`model`、`timeout_seconds` 和 `post_json`。默认 HTTP 函数使用 `urllib.request`，请求路径固定为 `/chat/completions`，响应只解析 `choices[0].message.content`，非成功响应和协议错误抛出 `ModelGatewayError`。

- [ ] **步骤 4：运行测试确认通过**

运行：`python -m pytest tests/test_model_gateway.py -q`

预期：Provider 单元测试通过。

### 任务 2：远程 MCP HTTP Transport

**文件：**
- 修改：`packages/mcp_server/server.py`
- 创建：`packages/mcp_server/remote.py`
- 创建：`packages/mcp_server/transport.py`
- 修改：`packages/mcp_server/__init__.py`
- 修改：`apps/runtime_harness/main.py`
- 测试：`tests/test_mcp_remote.py`

- [ ] **步骤 1：编写失败测试**

测试远程 Client 能发现工具并调用工具，且远程错误不会被吞掉。

```python
def test_remote_mcp_client_lists_and_calls_tools():
    def fake_request(method, url, headers, payload, timeout):
        if method == "GET":
            return [{"name": "read_context", "source": "mcp"}]
        return {"result": payload["query"]}

    client = MCPRemoteClient("http://mcp.test", request_json=fake_request)

    assert client.list_tools()[0]["name"] == "read_context"
    assert client.call_tool("read_context", {"query": "README"}) == {"result": "README"}
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest tests/test_mcp_remote.py -q`

预期：因远程 Client 尚未定义而失败。

- [ ] **步骤 3：实现 Client 和 Transport**

`MCPRemoteClient` 通过注入的 `request_json` 或标准库 HTTP 请求调用 `/mcp/tools` 和 `/mcp/tools/{name}`。`MCPTransportRouter` 将本地 `MCPServer` 暴露为 FastAPI 路由，并把缺参、未知工具和 Handler 异常转换为明确 HTTP 错误。

- [ ] **步骤 4：运行测试确认通过**

运行：`python -m pytest tests/test_mcp_remote.py -q`

预期：远程 Client 和 Transport 测试通过。

### 任务 3：Planner 驱动 Runtime 执行

**文件：**
- 修改：`apps/runtime_harness/engine.py`
- 修改：`apps/runtime_harness/planner.py`
- 修改：`apps/runtime_harness/main.py`
- 修改：`packages/event_store/models.py`
- 测试：`tests/test_runtime_execution.py`

- [ ] **步骤 1：编写失败测试**

验证两个有依赖关系的任务按顺序执行，事件包含开始和完成，失败任务保存 Checkpoint。

```python
def test_runtime_executes_plan_in_dependency_order():
    engine = RuntimeEngine(InMemoryEventStore())
    engine.register_tool(ToolDefinition(name="read_context"), lambda payload: {"text": payload["query"]})
    plan = TaskPlan(
        goal="read and analyze",
        tasks=[
            PlannedTask(task_id="t1", name="read", description="read"),
            PlannedTask(task_id="t2", name="analyze", description="analyze", depends_on=["t1"]),
        ],
    )
    run = engine.start_run(plan.goal)

    result = engine.execute_plan(run.run_id, plan)

    assert [item.name for item in result.tasks] == ["read", "analyze"]
    assert [event.event_type for event in engine.trace(run.run_id)] == [
        "run.created", "task.started", "task.completed", "task.started", "task.completed", "run.completed"
    ]
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest tests/test_runtime_execution.py -q`

预期：因 `execute_plan` 尚未定义而失败。

- [ ] **步骤 3：实现最小执行器**

新增执行结果模型和 `RuntimeEngine.execute_plan(run_id, plan)`。执行器校验依赖已完成，按计划顺序写入 TaskRecord 和事件；当前任务映射到同名本地工具时调用本地工具，否则把任务描述交给 ModelGateway。没有 Provider 时使用确定性结果，不阻塞既有测试。

- [ ] **步骤 4：接入远程 MCP 和模型配置**

`RuntimeEngine` 接受可选 `model_gateway` 和 `mcp_client`。任务对应远程工具时优先调用 MCP Client；远程调用失败时记录失败事件并保存 Checkpoint。`POST /runs/{run_id}/execute` 创建计划并返回执行结果。

- [ ] **步骤 5：运行测试确认通过**

运行：`python -m pytest tests/test_runtime_execution.py tests/test_runtime_api.py -q`

预期：Planner 执行和既有 API 测试全部通过。

### 任务 4：文档、环境变量和完整验证

**文件：**
- 修改：`README.md`
- 修改：`docs/architecture.md`
- 修改：`.env.example`

- [ ] **步骤 1：更新配置示例**

补充 Provider、MCP 远程地址、超时和 fallback 配置，并明确密钥只能通过环境变量注入。

- [ ] **步骤 2：更新运行说明**

说明如何启动 Runtime、如何启动 MCP Transport、如何配置兼容模型以及如何调用 `/runs/{run_id}/execute`。

- [ ] **步骤 3：运行完整验证**

运行：`python -m pytest tests -q`、`python -m compileall -q packages apps tests scripts`、`python scripts/check_skeleton.py`。

预期：全部测试通过、编译检查无输出、骨架检查输出 `skeleton ok`。
