# UPGRADE_PROMPT.md

面向**阶段二及以后**的扩展提示词。新增工具时应当遵循本文件约定，
复用既有 REST 客户端、日志与统一错误信封，不修改服务外壳。

## 现状

阶段一只实现 `list_pets`。基础设施已就绪，新增工具通常是“新增一个 `tools/` 模块 +
在 `server.py` 注册该工具”两步。

## 新增工具的通用步骤

1. 在 `src/pet_hospital_mcp/tools/` 新增模块，例如 `tools/get_pet_detail.py`。
2. 用 Pydantic 定义：
   - 输入模型（`extra="forbid"`、`strict=True`、`allow_inf_nan=False`），
   - 成功输出模型（对应 Go `data`，兼容 `records`/`charges` 为 `null` 或数组），
   - 错误输出即 `errors.error_envelope(...)`。
3. 写一个 `handle_<tool>(raw, client)` 工厂，返回 `CallToolResult`：
   - 先 `validate_arguments(raw)`，失败返回 `VALIDATION_ERROR` 信封；
   - 调用 `RestClient`；
   - 捕获 `BackendError`（`BACKEND_TIMEOUT / BACKEND_UNAVAILABLE / BACKEND_API_ERROR /
     BACKEND_INVALID_RESPONSE`），未知异常兜底 `INTERNAL_ERROR`；
   - 用 `_log_outcome` 结构（`timestamp / tool_name / params / status / duration_ms`）
     记录日志，`params` 必须经 `redact_pii` 脱敏。
4. 在 `server.py` 中注册：`self.add_tool(<stub>, name=..., title=..., description=...,
   structured_output=False)`，并在 `call_tool` 的短路分支里 `handle_<tool>` 转发，
   用 `WithJsonSchema` 挂参数 JSON Schema。
5. 在 `tools/__init__.py` 导出新符号，保持 `__all__` 与现有风格一致。

## 必须遵守的红线

- 不导入 `mcp.server.fastmcp.FastMCP`。
- 不使用旧协议 `initialize` / `Mcp-Session-Id` / 会话存储 / `max_sessions`。
- 工具名 snake_case，不新增 adapter 私有业务参数（参数应与后端查询参数一一对应）。
- 枚举值（species / status / sortBy / order …）一律取自后端 `GET /api/v1/meta`，勿猜测。
- 不把 httpx / Pydantic / SDK 堆栈异常原样暴露给客户端；一律返回统一错误信封。
- 日志 `params` 中 `ownerPhone / ownerAddr / chipNo`（及 snake_case）递归脱敏。

## 测试约定

- 新增 `tests/test_<module>.py`，用 `httpx.MockTransport`，禁止访问真实后端。
- 至少覆盖：正常调用（参数正确转发）、输入校验失败、后端 4xx/5xx、超时/连接异常、
  非法 JSON / 不符合数据模型、工具注册与 JSON Schema。
- 运行：`cd pet_hospital_mcp && pytest -q`，保持全绿。
