# 架构

```text
                    ┌──────────────── apps/runtime_harness ────────────────┐
                    │  API 路由（run / plan / trace / metrics / approvals） │
                    └───────┬───────────────┬───────────────┬──────────────┘
                            │               │               │
                     packages/planner  packages/runtime  packages/observability
                            │               │               │
                            └───────┬───────┴───────┬───────┘
                                    │               │
                            packages/event_store   │
                                    │               │
                    ┌───────────────┴───────┬───────┴────────┐
             packages/tool_registry  packages/mcp_server  packages/model_gateway
                    │                       │                    │
                    └───────────────┬───────┴────────────────────┘
                                    │
                    ┌───────────────┴────────────────┐
            apps/multimodal_lora            packages/rag
                    │
            packages/multimodal
```

## 依赖方向

- `apps/*` 只做 HTTP 编排，依赖 `packages/*`；`packages/*` 之间不允许反向依赖 `apps`。
- `RuntimeEngine` 依赖端口：`EventStore`、`Planner`、`SyncModelGateway`、`MCPRemoteClient`、
  `Replanner`、`TaskExecutor`，全部可注入。
- `packages/runtime` 只负责状态机、执行、审批、检查点，不含 HTTP 与模型协议细节。
- `packages/mcp_server` 自带认证、SSRF 策略与熔断，不依赖 Runtime。
- `packages/observability` 与 `packages/rag` 是纯函数库，输入事件/文本，无全局状态。

## 关键数据流

```text
goal → Planner（校验：重复 id / 悬空依赖 / 环 / 深度 / 工具）
     → TaskPlan（plan_id, planner_version, replan_count）
     → RuntimeEngine（拓扑序 + 就绪批 + 并发 + 超时 + 重试）
     → 本地工具 / MCP / Model（可注入）
     → TaskRecord + EventRecord（含 latency / attempts / error_code）
     → Checkpoint（completed ids / outputs / attempts / 版本快照）
     → 失败时 Replanner（受 MAX_REPLANS 约束）或暂停待恢复
```

## 服务边界

- 事件存储：内存 / SQLite，`EventStore` 协议保证两者行为一致（契约测试 ×2）。
- 模型：OpenAI 兼容 Provider → `ModelRouter`（fallback + 重试 + 安全钩子）。
- MCP：REST legacy + `POST /mcp` JSON-RPC，Bearer 认证，出站 SSRF 白名单。
- 观测：全部由事件派生（span 树、摘要、JSONL、Prometheus），不额外写状态。

## 已知边界

- 超时无法中断 Python 线程；SSRF 不解析 DNS；MCP 无 stdio/SSE；
  RAG 为词法基线 + 合成评测集；无 GPU 时 LoRA 记为 unavailable。