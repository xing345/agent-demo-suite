# Agent Demo Suite

用于 Agent 开发工程师面试展示的项目骨架，包含两个相互独立的应用：

- `apps/runtime_harness`：Agent Runtime 与 Harness API 骨架
- `apps/multimodal_lora`：多模态数据处理与 LoRA 实验 API 骨架
- `packages/event_store`：Session、Run、Task、Event 和 Checkpoint 数据模型
- `packages/tool_registry`：普通工具、MCP 工具和 Skill 的统一描述接口
- `packages/model_gateway`：模型调用接口，当前不返回虚假模型结果

## 本阶段范围

当前已完成 Runtime 的可演示链路：创建 Run、Planner 生成任务计划、按依赖执行任务、注册工具、危险工具人工确认、工具执行、Event Trace 和 Checkpoint 恢复。Skill Registry、远程 HTTP JSON MCP Transport 和 OpenAI-compatible Model Provider 已接入；未配置 Provider 或远程 MCP 时仍使用确定性本地 fallback。音频转写、视频抽帧和 LoRA 训练仍未接入。

Runtime 已支持内存事件存储和 SQLite 事件存储。复制 `.env.example` 为 `.env` 后，将 `EVENT_STORE_BACKEND` 改为 `sqlite`，即可把 Run 和 Event 保存到 `data/runtime-events.sqlite3`。

配置真实模型时填写 `MODEL_PROVIDER=openai_compatible`、`MODEL_BASE_URL`、`MODEL_API_KEY` 和 `MODEL_NAME`。配置远程 MCP 时填写 `MCP_REMOTE_URL`，Runtime 会先发现远程工具，再按 Planner 任务名称调用对应工具。

## 运行测试

```powershell
Set-Location agent-demo-suite
python -m pytest tests -q
python scripts/check_skeleton.py
```

## 启动 API

```powershell
python -m uvicorn apps.runtime_harness.main:app --reload --port 8001
python -m uvicorn apps.multimodal_lora.main:app --reload --port 8002
```

## 后续扩展顺序

下一步实现模型驱动的动态重规划、MCP 认证与服务发现、多模态文件处理、数据集版本和 LoRA 实验。所有真实效果、耗时和评测数字必须来自实际运行。
