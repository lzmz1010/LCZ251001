"""上下文管理：归档、压缩摘要与历史检索。

本模块负责三件事：
1. ``ContextArchiver``：把原始会话保存成 JSONL 归档文件（``.agents/context/``），
   并提供基于关键词的全文检索（供 ``recallContext`` 工具调用）；
2. ``COMPRESSION_PROMPT``：专门用于上下文压缩的提示词；
3. ``ContextStats`` / ``CompressionResult``：上下文状态与压缩结果的领域模型。

这里不使用向量数据库 / Embedding，全部采用 Python 标准库实现，便于理解与维护。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from core.config import PROJECT_ROOT
from core.session import Session

#: 归档目录默认位置（相对项目根目录）
DEFAULT_ARCHIVE_DIR = ".agents/context"

#: 单条检索结果片段的最大字符数
SNIPPET_MAX_CHARS = 300
#: 单次检索最多返回的命中条数
RECALL_LIMIT = 8


@dataclass(frozen=True)
class ContextStats:
    """当前会话上下文占用情况。"""

    used_tokens: int = 0
    window_tokens: int = 0
    ratio: float = 0.0
    window_is_default: bool = True
    blocked: bool = False


@dataclass(frozen=True)
class CompressionResult:
    """一次上下文压缩的结果。"""

    success: bool
    message: str = ""
    archive_id: str | None = None
    summary: str = ""


COMPRESSION_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、药品名称、病状、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 `recallContext` 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。"""


def _resolve_dir(path: str | os.PathLike[str] | None) -> Path:
    """把归档目录解析成绝对路径（相对路径以项目根目录为基准）。"""
    if not path:
        return (PROJECT_ROOT / DEFAULT_ARCHIVE_DIR).resolve()
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (PROJECT_ROOT / candidate).resolve()


def _record_haystack(record: dict) -> str:
    """把一条归档消息展开成可检索的文本。"""
    parts = [
        str(record.get("role", "")),
        str(record.get("content", "")),
        str(record.get("name", "")),
    ]
    if record.get("tool_calls"):
        parts.append(json.dumps(record["tool_calls"], ensure_ascii=False))
    return "\n".join(parts)


def _snippet(text: str, max_chars: int = SNIPPET_MAX_CHARS) -> str:
    """把文本压缩成单行检索片段。"""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "（空）"
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


class ContextArchiver:
    """负责把会话原始上下文保存为 JSONL 归档，并支持关键词检索。

    归档命名格式：``YYYYMMDD-HHMMSS.jsonl``（冲突时追加 ``-2``、``-3``…）。
    每一行是一条消息，保存顺序即消息顺序，保留角色、内容、
    工具调用参数与工具返回结果的完整字段。
    """

    def __init__(
        self,
        root: str | os.PathLike[str] | None = None,
        recall_limit: int = RECALL_LIMIT,
        snippet_max_chars: int = SNIPPET_MAX_CHARS,
    ) -> None:
        self._root = _resolve_dir(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._recall_limit = (
            recall_limit if recall_limit is not None else RECALL_LIMIT
        )
        self._snippet_max_chars = (
            snippet_max_chars if snippet_max_chars is not None else SNIPPET_MAX_CHARS
        )

    @property
    def root(self) -> Path:
        """归档目录的绝对路径。"""
        return self._root

    def next_archive_id(self) -> str:
        """生成一个当前目录下唯一的新归档编号。"""
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = base
        suffix = 2
        while (self._root / f"{candidate}.jsonl").exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def archive_path(self, archive_id: str) -> Path:
        """归档编号对应的文件路径。"""
        return self._root / f"{archive_id}.jsonl"

    def list_archive_ids(self) -> list[str]:
        """按时间倒序（新→旧）返回全部归档编号。"""
        ids = [
            path.stem
            for path in self._root.glob("*.jsonl")
            if path.is_file()
        ]
        return sorted(ids, reverse=True)

    def save_session(self, session: Session) -> str:
        """把整个会话保存为归档文件，返回归档编号。"""
        archive_id = self.next_archive_id()
        target = self.archive_path(archive_id)
        with open(target, "w", encoding="utf-8") as f:
            for message in session.messages:
                f.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")
        return archive_id

    def search(
        self,
        text: str,
        archive_id: str | None = None,
        limit: int | None = None,
    ) -> str:
        """在归档中进行关键词全文检索，返回格式化结果。

        :param text: 需要查找的关键词或文本（可含空格，按空白拆分为多个关键词）。
        :param archive_id: 指定归档编号；不指定则检索全部历史归档。
        :param limit: 最多返回的命中条数。
        """
        if limit is None:
            limit = self._recall_limit
        keywords = [k for k in re.split(r"\s+", text.strip()) if k]
        if not keywords:
            return "recallContext 的参数 text 不能为空"

        files: list[Path] = []
        if archive_id:
            target = self.archive_path(archive_id)
            if target.is_file():
                files = [target]
            else:
                return f"归档不存在: {archive_id}（可用的编号: {', '.join(self.list_archive_ids()) or '无'}）"
        else:
            files = [self.archive_path(i) for i in self.list_archive_ids()]
        if not files:
            return "当前没有任何历史上下文归档（.agents/context/ 为空）"

        lower_keywords = [k.lower() for k in keywords]
        total_hits = 0
        shown: list[str] = []
        for path in files:
            if len(shown) >= limit:
                break
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                continue
            for line_no, line in enumerate(lines, start=1):
                if len(shown) >= limit:
                    break
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                haystack = _record_haystack(record).lower()
                if not any(keyword in haystack for keyword in lower_keywords):
                    continue
                total_hits += 1
                if len(shown) < limit:
                    role = record.get("role", "?")
                    name = record.get("name", "")
                    label = f"[{role}]" + (f" {name}" if name else "")
                    content = _snippet(
                        str(record.get("content", "")),
                        self._snippet_max_chars,
                    )
                    shown.append(
                        f"- 归档 {path.stem} 第 {line_no} 行 {label}: {content}"
                    )

        if total_hits == 0:
            return f"未找到与「{text}」相关的内容。"

        head = (
            f"在 {len(files)} 个归档中找到与「{text}」相关的内容共 {total_hits} 处：\n"
            + "\n".join(shown)
        )
        if total_hits > len(shown):
            head += (
                f"\n（匹配较多，仅显示前 {len(shown)} 条。"
                "如需精确定位，请提供归档编号 id 或使用更精确的关键词。）"
            )
        return head


def render_readable_history(messages: Iterable[object]) -> str:
    """把会话消息转换成给压缩 LLM 阅读的易读文本（保留消息顺序）。"""
    lines = ["=== 历史对话记录（按时间顺序） ==="]
    for message in messages:
        role = getattr(message, "role", "")
        content = getattr(message, "content", "") or ""
        tool_calls = getattr(message, "tool_calls", ()) or ()
        name = getattr(message, "name", "") or ""
        if role == "system":
            lines.append("[system]")
            lines.append(content)
        elif role == "user":
            lines.append("[user]")
            lines.append(content)
        elif role == "assistant":
            if tool_calls:
                lines.append("[assistant] 请求调用工具:")
                for call in tool_calls:
                    lines.append(f"  - {call.name}({call.arguments})")
            if content:
                lines.append("[assistant]")
                lines.append(content)
        elif role == "tool":
            lines.append(f"[tool] {name}")
            lines.append(content)
    return "\n".join(lines)


__all__ = [
    "COMPRESSION_PROMPT",
    "ContextArchiver",
    "ContextStats",
    "CompressionResult",
    "DEFAULT_ARCHIVE_DIR",
    "render_readable_history",
]