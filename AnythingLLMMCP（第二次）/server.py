# -*- coding: utf-8 -*-
"""AnythingLLM MCP Server (MVP)

- MCP 2026-07-28 协议，Streamable HTTP 传输（非 stdio）
- 唯一工具：ask_anythingllm(question) —— 向本机 AnythingLLM 的唯一工作区提问，
  返回基于该工作区文档的 AI 回答（AnythingLLM RAG query 模式）

运行环境：需 Python 3.11+，且已安装官方 mcp SDK 2.x（对应 2026-07-28 协议）
运行方式：python server.py  （默认监听 http://127.0.0.1:8000/mcp）
"""
import json
import os
import urllib.request
import urllib.error

from mcp.server import MCPServer

# ---------------- AnythingLLM 配置 ----------------
ANYTHINGLLM_BASE = "http://localhost:3001"                 # 本机 AnythingLLM
ANYTHINGLLM_API_KEY = "YOUR_ANYTHINGLLM_API_KEY"    # 你在 AnythingLLM 创建的 API Key
WORKSPACE_SLUG = "48761e04-1893-49d9-83c0-fdd5ba180053"    # 唯一工作区「我的工作区」


server = MCPServer(
    name="anythingllm-mcp",
    title="AnythingLLM MCP",
    description="访问本机 AnythingLLM 唯一工作区进行 AI 问答",
    version="1.0.0",
)


def _call_anythingllm_chat(question: str) -> str:
    """调用 AnythingLLM 工作区 chat 接口（query 模式，基于工作区知识回答）。"""
    url = f"{ANYTHINGLLM_BASE}/api/v1/workspace/{WORKSPACE_SLUG}/chat"
    body = json.dumps({"message": question, "mode": "query"}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": "Bearer " + ANYTHINGLLM_API_KEY,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = data.get("textResponse")
    if text is None:
        raise RuntimeError("AnythingLLM 未返回 textResponse: " + str(data))
    return text


def _workspace_unique_docs() -> tuple[int, list[str]]:
    """返回工作区去重后的文档文件数量及文件名列表。"""
    url = f"{ANYTHINGLLM_BASE}/api/v1/workspace/{WORKSPACE_SLUG}"
    req = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + ANYTHINGLLM_API_KEY}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    ws = data["workspace"][0]
    docs = ws.get("documents", [])
    unique: dict[str, str] = {}
    for d in docs:
        path = d.get("docpath") or d.get("filename") or ""
        title = ""
        meta = d.get("metadata")
        if meta:
            try:
                title = json.loads(meta).get("title", "")
            except Exception:
                title = ""
        unique[path] = title or os.path.basename(path)
    return len(unique), sorted(unique.values())


COUNT_KEYWORDS = ("多少", "几个", "多少个", "文件数", "文档数", "数量")


@server.tool(
    description=(
        "向本机 AnythingLLM 的唯一工作区（我的工作区）提问，"
        "返回基于该工作区已嵌入文档的 AI 回答；若问题涉及文件/文档数量，则直接返回工作区文档统计。"
    )
)
async def ask_anythingllm(question: str) -> str:
    """Ask AnythingLLM the given question and return its answer."""
    if any(k in question for k in COUNT_KEYWORDS):
        n, names = _workspace_unique_docs()
        return f"我的工作区当前共有 {n} 个文档文件：" + "、".join(names) + "。"
    return _call_anythingllm_chat(question)


if __name__ == "__main__":
    import asyncio
    asyncio.run(
        server.run_streamable_http_async(
            host="127.0.0.1",
            port=8100,
            streamable_http_path="/mcp",
            stateless_http=True,   # 2026-07-28 无状态 Streamable HTTP
        )
    )
