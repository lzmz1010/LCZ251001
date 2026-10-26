"""联网搜索工具：调用百度千帆「百度搜索」API（/v2/ai_search/web_search）。"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.config import SearchConfig
from core.errors import ToolError
from core.tools.base import Tool, ToolParameter

DEFAULT_BASE_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"
DEFAULT_EDITION = "standard"


class SearchWebTool(Tool):
    """联网搜索实时信息，返回搜索摘要与参考来源。"""

    name = "searchWeb"
    description = (
        "联网搜索互联网上的实时信息。当需要最新新闻、近期数据、实时动态，"
        "或自身知识无法确定的信息时使用。返回搜索摘要以及参考来源的标题和 URL。"
    )
    parameters = (
        ToolParameter(
            name="query",
            type="string",
            description="要搜索的关键词或问题，例如：2026 年诺贝尔物理学奖得主",
            required=True,
        ),
    )

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        edition: str = DEFAULT_EDITION,
        timeout: float = 60.0,
    ) -> None:
        env_key = os.getenv("XAGENT_SEARCH_API_KEY", "") if api_key is None else api_key
        self._api_key = env_key.strip()
        self._base_url = base_url
        self._edition = edition
        self._timeout = timeout

    @classmethod
    def from_config(cls, config: SearchConfig) -> "SearchWebTool":
        """依据配置创建工具实例。"""
        return cls(
            api_key=config.api_key,
            base_url=config.base_url,
            edition=config.edition,
            timeout=config.timeout,
        )

    def invoke(self, query: str) -> str:
        """搜索 query，整理摘要与参考来源后返回给模型。"""
        query = (query or "").strip()
        if not query:
            raise ToolError("搜索关键词不能为空")
        if not self._api_key:
            raise ToolError(
                "未配置百度千帆搜索 API Key，请在 config.ini 的 [search] 中设置 "
                "baidu_qianfan_api_key，或设置环境变量 XAGENT_SEARCH_API_KEY"
            )
        return self._format(self._request(query))

    def _request(self, query: str) -> dict[str, Any]:
        payload = {
            "messages": [{"role": "user", "content": query}],
            "search_source": "baidu_search_v2",
            "edition": self._edition,
            "resource_type_filter": [{"type": "web", "top_k": 20}],
        }
        request = Request(
            self._base_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise ToolError(
                f"百度千帆搜索接口返回 HTTP {exc.code}: {detail[:500] or exc.reason}"
            ) from exc
        except URLError as exc:
            raise ToolError(f"无法连接百度千帆搜索接口: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ToolError("百度千帆搜索请求超时，请稍后重试") from exc
        except OSError as exc:
            raise ToolError(f"百度千帆搜索网络请求失败: {exc}") from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ToolError(
                f"百度千帆搜索返回了非 JSON 内容: {body[:200]}"
            ) from exc
        if not isinstance(data, dict):
            raise ToolError("百度千帆搜索返回格式不正确")

        code = data.get("code")
        if code not in (None, 0, "0"):
            message = data.get("message") or data.get("msg") or "未知错误"
            request_id = data.get("request_id") or data.get("requestId")
            suffix = f"（request_id: {request_id}）" if request_id else ""
            raise ToolError(
                f"百度千帆搜索失败 [code={code}]: {message}{suffix}"
            )
        return data

    def _format(self, data: dict[str, Any]) -> str:
        references = [
            item for item in (data.get("references") or []) if isinstance(item, dict)
        ]

        if not references:
            return "未搜索到相关结果，请尝试更换关键词。"

        summary_parts: list[str] = []
        for ref in references:
            content = ref.get("content") or ref.get("snippet") or ""
            content = str(content).strip()
            if content:
                summary_parts.append(content)
        summary = "\n\n".join(summary_parts).strip()

        lines: list[str] = []
        if summary:
            lines.append("搜索摘要：")
            if len(summary) > 4000:
                summary = summary[:4000] + "..."
            lines.append(summary)

        if references:
            if lines:
                lines.append("")
            lines.append("参考来源：")
            for index, reference in enumerate(references, 1):
                title = str(
                    reference.get("title")
                    or reference.get("web_anchor")
                    or reference.get("website")
                    or "无标题"
                ).strip()
                url = str(reference.get("url") or "").strip()
                lines.append(f"{index}. {title}")
                if url:
                    lines.append(f"   URL: {url}")
        return "\n".join(lines)
