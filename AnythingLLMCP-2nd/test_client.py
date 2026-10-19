# -*- coding: utf-8 -*-
"""验证 MCP Server 端到端：连接 http://127.0.0.1:8000/mcp，
列出工具并调用 ask_anythingllm 问「我的工作区有多少个文件」。"""
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    async with streamable_http_client("http://127.0.0.1:8100/mcp") as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            listed = await session.list_tools()
            tools = getattr(listed, "tools", listed)
            if isinstance(tools, tuple):
                tools = tools[0]
            print("可用工具:", [getattr(t, "name", t) for t in tools])
            res = await session.call_tool(
                "ask_anythingllm", {"question": "我的工作区有多少个文件"}
            )
            print("---回答---")
            for item in res.content:
                if hasattr(item, "text"):
                    print(item.text)


if __name__ == "__main__":
    asyncio.run(main())
