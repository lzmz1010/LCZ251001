# pet-hospital-mcp

独立 MCP 服务，将现有 Go 宠物医院 REST API（`GET /api/v1/pets`）的能力暴露给 AI Agent。

- **Python** 3.11+
- **官方 Python SDK** `mcp==2.0.0`
- **MCP 协议版本** `2026-07-28`
- **服务基类** `mcp.server.mcpserver.MCPServer`（不使用/不兼容 1.x 的 `FastMCP`）
- **传输方式**：无状态 Stateless **Streamable HTTP**
- 不实现旧协议的 `initialize` 握手、`Mcp-Session-Id`、会话存储/过期、`max_sessions` 或有状态 SSE 恢复

阶段一只实现一个工具：**`list_pets`**。

> 本服务只做「阶段一」。阶段二工具**未实现**。

---

## 架构

```
Go 宠物医院 REST API  ← HTTP ←  pet-hospital-mcp (MCPServer)  ← MCP ←  AI Agent
  http://127.0.0.1:8080      (只读 GET /api/v1/pets)          (无状态 Streamable HTTP)
```

- 现有 Go 服务**不修改**，是唯一业务后端。
- MCP 服务是独立 Python 进程，只能通过 HTTP 调用 Go REST API。
- 上游地址默认 `http://127.0.0.1:8080`，用 `PET_HOSPITAL_BASE_URL` 覆盖。

## 模块结构

```text
pet_hospital_mcp/
├── pyproject.toml
├── README.md
├── UPGRADE_PROMPT.md
├── src/
│   └── pet_hospital_mcp/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config.py          # 环境变量配置
│       ├── server.py          # MCPServer 装配 + /health
│       ├── rest_client.py     # 对 Go 后端的 HTTP 客户端（超时 + 有限重试）
│       ├── errors.py          # 统一错误信封
│       ├── logging_config.py  # 结构化 JSON 日志 + PII 脱敏
│       └── tools/
│           ├── __init__.py
│           └── list_pets.py
└── tests/                     # pytest + httpx.MockTransport（不访问真实后端）
```

后续阶段新增工具时，只需在 `tools/` 增加模块并复用 `rest_client`、日志与错误约定，无需改动服务外壳。

---

## 安装与启动命令

**前置条件**：`PET_HOSPITAL_BASE_URL` 指向的 Go 服务**必须先启动**，
否则调用 `list_pets` 会返回 `BACKEND_UNAVAILABLE`。

```bash
# 1) 创建虚拟环境并安装（在 pet_hospital_mcp/ 目录下）
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2) 启动 MCP 服务（默认 127.0.0.1:8000）
pet-hospital-mcp
# 或 python -m pet_hospital_mcp
```

启动后可用 MCP Inspector 连接 `http://127.0.0.1:8000/mcp`。

### 配置环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PET_HOSPITAL_BASE_URL` | `http://127.0.0.1:8080` | Go 后端上游地址 |
| `PET_HOSPITAL_TIMEOUT` | `10` | 每次请求超时（秒） |
| `PET_HOSPITAL_RETRIES` | `2` | 失败后的重试次数（总尝试=重试+1） |
| `MCP_HOST` | `127.0.0.1` | MCP 绑定地址 |
| `MCP_PORT` | `8000` | MCP 绑定端口 |
| `MCP_LOG_LEVEL` | `INFO` | 日志级别 |

```bash
MCP_HOST=127.0.0.1 MCP_PORT=8000 PET_HOSPITAL_BASE_URL=http://127.0.0.1:8080 pet-hospital-mcp
```

## MCP 端点

- MCP 流式 HTTP 端点：`http://127.0.0.1:8000/mcp`
- 健康检查：`http://127.0.0.1:8000/health`

## 实际版本

- 运行库：`mcp==2.0.0`
- 协议版本：`2026-07-28`
- 实现基类：`MCPServer`（`mcp.server.mcpserver.MCPServer`）
- 传输：无状态 Streamable HTTP（`stateless_http=True`）
- 连接协商：现代 `server/discover`，不走旧 `initialize`

## 实现语言与协议要求落实

- 不得导入 `mcp.server.fastmcp.FastMCP`。✓
- 不发送旧 `initialize`；Stateless HTTP 不要求也不返回 `Mcp-Session-Id`。✓
- 工具错误用统一错误信封 `{"error":{"code","message","details"}}`，
  以 `structured_content` + `is_error=True` 返回（SDK 2.x 的 `CallToolResult`）。✓
- 错误码至少区分：
  `VALIDATION_ERROR`、`BACKEND_TIMEOUT`、`BACKEND_UNAVAILABLE`、
  `BACKEND_API_ERROR`、`BACKEND_INVALID_RESPONSE`、`INTERNAL_ERROR`。✓
- 后端调用有超时与有限重试。✓
- 不把 httpx / Pydantic / SDK 堆栈原样暴露给客户端。✓

## 工具描述：`list_pets`

等价于 `GET /api/v1/pets`。支持且仅支持以下查询参数：

`q` `name` `ownerName` `ownerPhone` `species` `doctor` `disease`
`status` `min` `max` `sortBy` `order` `page` `pageSize`

校验规则（Pydantic 严格模式）：
- `species` / `status` / `sortBy` / `order` 使用真实后端枚举值；
- `page >= 1`；`1 <= pageSize <= 500`；
- `min`、`max` 非负；同时给出时 `min <= max`；
- 拒绝未知字段、`NaN`、`Infinity` 与类型不正确输入。

成功输出对应 Go 响应信封中的 `data`：

```
items, total, page, pageSize, totalPages, totalCost
```

`items[].records` 与 `items[].charges` 兼容后端 `null` 或数组两种真实表现。

### list_pets 调用示例

```json
{
  "q": "汤圆",
  "species": "犬",
  "status": "已康复",
  "min": 1000,
  "sortBy": "totalCost",
  "order": "desc",
  "page": 1,
  "pageSize": 10
}
```

### /health 示例

```json
{
  "status": "ok",
  "service": "pet-hospital-mcp",
  "version": "0.1.0",
  "backend_base_url": "http://127.0.0.1:8080"
}
```

## 日志

标准库结构化 JSON 日志，每行包含 `timestamp`、`tool_name`、`params`、
`status`、`duration_ms`。

`ownerPhone`、`ownerAddr`、`chipNo`（含 snake_case 写法）在日志中**递归脱敏**，
不会把完整敏感数据写入日志（`params` 中的 PII 被替换为 `***`）。

## 验证步骤（MCP Inspector 或 SDK 2.x 客户端）

### 方法一：MCP Inspector

```bash
npx @modelcontextprotocol/inspector
# 或按 Inspector 交互提示，连接到 http://127.0.0.1:8000/mcp
```

在 Inspector 的「Servers」填入端点 `http://127.0.0.1:8000/mcp`，
连接后应看到 `list_pets` 工具及其 JSON Schema，可发起一次调用。

### 方法二：curl 无状态发现/调用（Streamable HTTP）

先发现工具（Streamable HTTP 返回 SSE）：

```bash
curl -i -N -X POST http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

调用 `list_pets`：

```bash
curl -i -N -X POST http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_pets","arguments":{"page":1,"pageSize":10}}}'
```

健康检查：

```bash
curl -s http://127.0.0.1:8000/health
```

> 上述请求为一次性、无会话状态请求；响应不包含要求回传的 `Mcp-Session-Id`，
> 体现「无状态 Stateless Streamable HTTP」。

## 单元测试

运行命令（在 `pet_hospital_mcp/` 下）：

```bash
pytest -q
```

覆盖：
- 正常调用：请求路径与全部过滤/排序/分页参数正确转发，`None` 过滤项不上线；
- 输入校验失败（枚举、范围、类型、未知字段、NaN/Infinity、min/max）；
- 后端返回 4xx/5xx、超时、连接异常、非法 JSON、缺失/非法 `data`；
- 有限重试与「先失败后成功」；
- MCP 工具注册、工具名与 JSON Schema；
- SDK 2.x 无状态连接：走 `server/discover`（协议 `2026-07-28`），不使用旧 `initialize`，
  不要求 `Mcp-Session-Id`，通过真实 HTTP 端点发现与调用工具；
- `/health`；
- 结构化日志字段与 PII 递归脱敏。

全部测试使用 `httpx.MockTransport`，**不会访问真实 Go 服务**。预期结果：`全部通过`。

## Go 服务与 MCP 服务启动顺序

1. 启动 Go 后端：`pethospital.exe`（或 `go run .`），监听 `http://127.0.0.1:8080`。
2. 确认后端健康：`curl http://127.0.0.1:8080/health`。
3. 启动 MCP：`pet-hospital-mcp`（见上文）。
4. 用 Inspector / curl / SDK 2.x 客户端验证 `http://127.0.0.1:8000/mcp`。

---

## 阶段二

**未实现**。当前仅提供 `list_pets` 一个工具。
后续将按 `UPGRADE_PROMPT.md` 的约定扩展更多工具。
