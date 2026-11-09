"""历史上下文检索工具。

``recallContext`` 让模型在压缩后需要查找历史细节时，从 ``.agents/context/``
下的归档文件中进行关键词检索。本实现只用 Python 标准库做全文关键词匹配，
不依赖向量数据库 / Embedding。
"""

from __future__ import annotations

from pathlib import Path

from core.context import ContextArchiver
from core.tools.base import Tool, ToolParameter


class RecallContextTool(Tool):
    """在历史上下文归档中检索原始对话内容。"""

    name = "recallContext"
    description = (
        "在历史上下文归档文件（.agents/context/）中进行关键词全文检索，"
        "返回相关的原始消息片段、归档编号与所在位置，用于找回上下文压缩时"
        "未包含进摘要的历史细节。"
    )
    parameters = (
        ToolParameter(
            name="text",
            description="需要查找的关键词或文本内容（可含空格，空格分隔多个关键词）",
            required=True,
        ),
        ToolParameter(
            name="id",
            description="指定归档编号（例如 20261022-153000）；不填时检索全部历史归档",
            required=False,
        ),
    )

    def __init__(
        self,
        archive_dir: str | Path | None = None,
        recall_limit: int | None = None,
        snippet_max_chars: int | None = None,
    ) -> None:
        self._archiver = ContextArchiver(
            archive_dir,
            recall_limit=recall_limit,
            snippet_max_chars=snippet_max_chars,
        )

    def invoke(self, text: str, id: str = "") -> str:
        """按关键词检索归档并返回格式化结果。"""
        return self._archiver.search(text=text, archive_id=id.strip() or None)


__all__ = ["RecallContextTool"]