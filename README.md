# Agent Demo Suite

面向 Agent 开发工程师岗位的综合演示项目：Agent Runtime + Planner + Tool Use + MCP +
Skill Registry + Model Provider + HITL + Checkpoint + RAG + 多模态数据处理 + Observability。

## 组成

| 模块 | 职责 |
|---|---|
| `apps/runtime_harness` | Runtime API：Planner、执行器、审批、取消、恢复、观测端点 |
| `apps/multimodal_lora` | 数据集上传/版本/划分、LoRA 实验记录 API |
| `packages/planner` | `Planner` 协议、确定性 Planner、`ModelPlanner`、计划校验、有界重规划 |
| `packages/runtime` | 状态机、任务执行器（超时/重试/并发）、事件溯源审批、检查点 |
| `packages/event_store` | Session/Run/Task/Event/Checkpoint 模型，内存与 SQLite 适配器 |
| `packages/mcp_server` | MCP 服务端（REST legacy + JSON-RPC）、Bearer 认证、SSRF 策略、熔断 |
| `packages/model_gateway` | OpenAI 兼容 Provider、SSE 流式、Function Calling、用量/成本、多模型路由 |
| `packages/observability` | Span 树、运行摘要、JSONL 导出、Prometheus 指标 |
| `packages/rag` | 切分、嵌入、检索、Recall@K/MRR/nDCG 评测 |
| `packages/multimodal` | 内容寻址存储、模态适配器、去重、数据集版本、划分、LoRA 实验 |
| `packages/skill_registry` | Skill 定义与登记（元数据） |
| `packages/tool_registry` | 工具描述、权限、版本、注册表 |

## 快速开始

```powershell
python -m pip install -e ".[dev]"
python -m pytest tests -q                 # 195 tests
python -m ruff check .                    # lint
python -m mypy                            # types
python scripts/check_skeleton.py          # 结构 + 导入冒烟
python scripts/eval_rag.py                # RAG 评测 -> reports/rag-eval.json
```

```powershell
python -m uvicorn apps.runtime_harness.main:app --reload --port 8001
python -m uvicorn apps.multimodal_lora.main:app --reload --port 8002
```

## 可演示链路

1. **计划与执行**：`POST /runs` → `POST /runs/{id}/execute`，依赖按拓扑序执行，事件全程可查。
2. **人工审批**：危险工具触发 `waiting_approval` → `POST /runs/{id}/approvals/{aid}` 批准 /
   `.../reject` 拒绝；审批存于事件日志，进程重启仍可继续。
3. **失败恢复**：任务失败自动写检查点 → `POST /runs/{id}/resume` → 只重跑剩余任务；
   若配置了 `Replanner`，会按 `MAX_REPLANS` 预算做有界重规划。
4. **取消与并发**：`POST /runs/{id}/cancel`；`EXECUTOR_CONCURRENCY>1` 时独立任务并行执行。
5. **观测**：`GET /runs/{id}/trace`（span 树）、`/summary`、`/events/export`（JSONL）、`/metrics`。
6. **MCP**：`GET /mcp/tools`（legacy）、`POST /mcp`（JSON-RPC `initialize`/`tools/list`/`tools/call`）；
   配置 `MCP_SERVER_TOKEN` 后需 Bearer 认证；客户端可切 `MCP_PROTOCOL=jsonrpc`。
7. **多模态**：`POST /datasets/{id}/files`（base64）→ `/versions` → `/split` → `POST /experiments`。

## 配置

复制 `.env.example` 为 `.env`。关键项：

- `EVENT_STORE_BACKEND=sqlite` + `EVENT_STORE_PATH`：把 Run/Event 落盘。
- `MODEL_PROVIDER=openai_compatible` + `MODEL_BASE_URL/MODEL_API_KEY/MODEL_NAME`：接入真实模型；
  `MODEL_PRICE_TABLE` 为 `{"model":[输入价, 输出价]}`（USD/1M tokens），未配置则成本为 `null`。
- `MCP_REMOTE_URL` / `MCP_PROTOCOL` / `MCP_RETRIES`；服务端 `MCP_SERVER_TOKEN`。
- `EXECUTOR_CONCURRENCY`、`MAX_REPLANS`、`APPROVAL_TTL_SECONDS`、`UPLOAD_DIR`、`MAX_UPLOAD_BYTES`。

## 明确的限制

- **不伪造任何指标**：未配置 provider 时不产生 token/成本；无 GPU 时 LoRA 实验记为
  `unavailable`、`metrics=null`；RAG 评测语料为**合成**数据且嵌入器是词法基线，指标已饱和，
  只证明流水线可运行，不代表检索质量。
- 音频转写（faster-whisper）、视频抽帧（ffmpeg）、图片处理（Pillow）为可注入适配器，
  缺少依赖时抛 `DependencyMissing`，不会返回假数据。
- MCP 实现了 HTTP JSON-RPC，不含 stdio/SSE 传输；SSRF 策略不解析 DNS（存在 rebinding 风险）。
- 超时无法强杀 Python 线程，只停止等待并将任务标记为 timeout。