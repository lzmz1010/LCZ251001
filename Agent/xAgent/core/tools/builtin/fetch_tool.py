"""网页正文抓取工具：调用本地 curl 下载 HTML，再用 trafilatura 提取 Markdown。"""

from __future__ import annotations

import shutil
import subprocess
from urllib.parse import urlparse

import trafilatura

from core.errors import ToolError
from core.tools.base import Tool, ToolParameter

DEFAULT_TIMEOUT = 30.0
MAX_HTML_BYTES = 10 * 1024 * 1024
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class FetchWebTool(Tool):
    """获取网页正文并转换为 Markdown，去除导航、广告、页脚等无关内容。"""

    name = "fetchWeb"
    description = (
        "抓取指定网页的正文并转换为 Markdown，保留标题、段落、列表、表格和链接，"
        "去除导航栏、广告、页脚等无关内容。当搜索结果只有摘要、需要阅读网页全文，"
        "或用户给出网页链接时使用。"
    )
    parameters = (
        ToolParameter(
            name="url",
            type="string",
            description="要抓取的网页地址，必须以 http:// 或 https:// 开头",
            required=True,
        ),
    )

    def __init__(
        self,
        curl_path: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_html_bytes: int = MAX_HTML_BYTES,
        user_agent: str = USER_AGENT,
    ) -> None:
        self._curl_path = (
            curl_path or shutil.which("curl") or shutil.which("curl.exe")
        )
        self._timeout = timeout
        self._max_html_bytes = max_html_bytes
        self._user_agent = user_agent

    def invoke(self, url: str) -> str:
        """抓取 url 的正文，返回 Markdown 与原始 URL。"""
        url = (url or "").strip()
        self._validate_url(url)
        html = self._fetch(url)
        markdown = self._extract(html, url)
        return f"来源 URL: {url}\n\n{markdown}"

    @staticmethod
    def _validate_url(url: str) -> None:
        if not url:
            raise ToolError("网页 URL 不能为空")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ToolError(f"网页 URL 无效，仅支持 http/https 地址: {url}")

    def _fetch(self, url: str) -> bytes:
        if not self._curl_path:
            raise ToolError("未找到本地 curl 程序，请安装 curl 并确保其在 PATH 中")

        args = [
            self._curl_path,
            "--location",
            "--silent",
            "--show-error",
            "--compressed",
            "--fail",
            "--max-time",
            f"{self._timeout:g}",
            "--connect-timeout",
            f"{min(self._timeout, 10.0):g}",
            "--max-filesize",
            str(self._max_html_bytes),
            "--proto",
            "=http,https",
            "--proto-redir",
            "=http,https",
            "--user-agent",
            self._user_agent,
            "--url",
            url,
        ]
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                timeout=self._timeout + 5,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f"获取网页超时（超过 {self._timeout:g} 秒）: {url}") from exc
        except FileNotFoundError as exc:
            raise ToolError("未找到本地 curl 程序，请安装 curl 并确保其在 PATH 中") from exc
        except OSError as exc:
            raise ToolError(f"调用 curl 失败: {exc}") from exc

        if completed.returncode != 0:
            detail = (
                completed.stderr or completed.stdout or b""
            ).decode("utf-8", errors="replace").strip()
            detail = detail[:500] or "无错误输出"
            raise ToolError(
                f"curl 获取网页失败（退出码 {completed.returncode}）: {detail}"
            )
        if not completed.stdout:
            raise ToolError(f"网页返回内容为空: {url}")
        return completed.stdout

    def _extract(self, html: bytes, url: str) -> str:
        try:
            document = trafilatura.load_html(html, max_size=self._max_html_bytes)
        except Exception as exc:  # noqa: BLE001 - 解析库可能抛出多种异常
            raise ToolError(f"HTML 解析失败: {exc}") from exc
        if document is None:
            raise ToolError("HTML 解析失败：无法解析网页内容")

        try:
            markdown = trafilatura.extract(
                document,
                url=url,
                output_format="markdown",
                include_links=True,
                include_tables=True,
                include_formatting=True,
                include_comments=False,
            )
        except Exception as exc:  # noqa: BLE001 - 提取库可能抛出多种异常
            raise ToolError(f"网页正文提取失败: {exc}") from exc
        if not markdown or not markdown.strip():
            raise ToolError(
                "未能从网页中提取正文（页面可能是动态渲染、需要登录，或没有可读正文）"
            )
        return markdown.strip()
