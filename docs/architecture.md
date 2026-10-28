# 当前骨架架构

```text
runtime_harness ─┐
                 ├─ event_store
                 ├─ tool_registry
                 ├─ model_gateway
                 └─ shared_config
multimodal_lora ─┘
```

当前 Runtime 应用已经支持 Planner 生成任务计划、创建 Run、按依赖执行任务、注册内置工具、危险工具人工确认、工具执行、Event Trace 和 Checkpoint 恢复。Skill Registry 负责登记可复用能力，MCP Server 同时提供本地注册能力和 HTTP JSON Transport，Runtime 可通过 MCPRemoteClient 调用远程工具。Model Gateway 提供 OpenAI-compatible Provider，未配置时保留确定性 fallback。事件存储可以使用内存版或 SQLite 版，具体由 `EVENT_STORE_BACKEND` 配置决定。多模态应用目前仍只提供数据集任务接口。

下一阶段可以在不改变 API 边界的前提下增加模型驱动的动态重规划、MCP 认证与服务发现、文件处理流水线和真实数据集/LoRA 实验。
