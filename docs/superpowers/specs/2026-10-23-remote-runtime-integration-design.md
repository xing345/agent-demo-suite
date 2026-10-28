# Remote Runtime Integration Design

## 目标

把当前本地 Agent Runtime 骨架扩展成一条可演示的完整链路：Planner 生成任务，Runtime 按依赖执行，工具可以来自本地或远程 MCP Server，模型可以通过 OpenAI-compatible Provider 生成下一步决策或结构化结果。

## 设计选择

采用配置驱动的 OpenAI-compatible Provider 和 HTTP JSON MCP Transport。这样不绑定某一家模型服务，OpenAI、DeepSeek、通义千问和本地兼容服务都可以通过 `MODEL_BASE_URL`、`MODEL_API_KEY` 和 `MODEL_NAME` 接入；没有配置 Provider 时继续使用确定性 Planner，测试不需要真实密钥或网络。

## 组件边界

`packages/model_gateway` 负责模型调用协议、响应解析和错误边界。`packages/mcp_server` 保留本地注册能力，并新增远程 Client 与 FastAPI Transport。`apps/runtime_harness/planner.py` 负责生成计划；`apps/runtime_harness/engine.py` 新增计划执行器，只负责依赖排序、任务状态、工具调用和事件记录，不把模型协议写入 Runtime。

## 数据流

```text
goal
  -> Planner
  -> TaskPlan
  -> RuntimeExecutor
  -> local tool / MCPRemoteClient / ModelGateway
  -> TaskRecord + EventRecord + Checkpoint
```

每个任务开始时记录 `task.started`，成功时记录 `task.completed`，失败时记录 `task.failed`。遇到人工确认或异常时保存可恢复状态。远程 MCP 调用失败不得静默降级为成功；只有显式配置 `MCP_FALLBACK_TO_LOCAL=true` 时才使用同名本地工具。

## API 与配置

新增 Provider 配置：`MODEL_PROVIDER`、`MODEL_BASE_URL`、`MODEL_API_KEY`、`MODEL_NAME`、`MODEL_TIMEOUT_SECONDS`。

新增 MCP 配置：`MCP_REMOTE_URL`、`MCP_REMOTE_TOKEN`、`MCP_FALLBACK_TO_LOCAL`。

新增 Runtime 接口：`POST /runs/{run_id}/execute`。接口触发计划执行并返回每个任务的状态和输出摘要。远程 MCP Server 提供 `GET /mcp/tools` 和 `POST /mcp/tools/{tool_name}`。

## 错误处理

Provider 对非 2xx 响应、超时、无效 JSON、缺少 choices/message/content 和鉴权失败抛出明确异常。MCP Client 对非 2xx、网络错误、未知工具和远程错误返回结构化异常。Runtime 将异常写入 `task.failed`，运行状态设为 `failed`，并保存包含当前任务索引和已完成输出的 Checkpoint。

## 测试边界

单元测试使用 Fake Provider、Fake HTTP Transport 和本地 MCP FastAPI handler；不在默认测试中访问公网。集成测试验证 OpenAI-compatible 请求体、MCP 工具列表/调用、Planner 依赖执行、失败 Checkpoint 和恢复后的继续执行。
