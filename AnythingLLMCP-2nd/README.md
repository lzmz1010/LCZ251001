# AnythingLLM MCP Server（第二次）

访问本机 AnythingLLM 的 MCP Server（MVP 版）。

- **协议**：MCP 2026-07-28（mcp Python SDK 2.x）
- **传输**：Streamable HTTP（非 stdio）
- **唯一工具**：`ask_anythingllm(question)` —— 向本机 AnythingLLM 唯一工作区（我的工作区）提问，返回基于工作区已嵌入文档的 AI 回答

## 运行要求
- Python 3.11+，已安装 `mcp` SDK 2.x：`pip install mcp`
- 本机 AnythingLLM 运行在 `http://localhost:3001`

## 启动
```bash
python server.py
```
服务监听 `http://127.0.0.1:8100/mcp`。

## 项目级 MCP 配置
`.mcp.json` 已配置项目级 MCP，指向上述 HTTP 地址。IDE 加载该配置后即可通过本 MCP 调用 `ask_anythingllm`。

## 配置项（server.py 顶部）
- `ANYTHINGLLM_BASE`：AnythingLLM 地址
- `ANYTHINGLLM_API_KEY`：AnythingLLM API Key
- `WORKSPACE_SLUG`：唯一工作区 slug
