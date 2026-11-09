"""会话保存与恢复（供 /new、/save、/resume 使用）。

会话以 JSONL 文件存储（每一行是一条消息，格式与上下文归档一致），
目录默认在 ``.agents/sessions/``。恢复时按原顺序还原全部消息，
包括系统提示词与注入的 AGENTS.md 上下文，实现「一次注入、全程复用、
随会话持久化」。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from core.config import PROJECT_ROOT
from core.models import Message, ToolCall
from core.session import Session

#: 会话存储目录默认位置（相对项目根目录）
DEFAULT_SESSION_DIR = ".agents/sessions"


def _resolve_dir(path: str | os.PathLike[str] | None) -> Path:
    """把会话目录解析成绝对路径（相对路径以项目根目录为基准）。"""
    if not path:
        return (PROJECT_ROOT / DEFAULT_SESSION_DIR).resolve()
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (PROJECT_ROOT / candidate).resolve()


@dataclass(frozen=True)
class SessionMeta:
    """一条已保存会话的摘要信息（供 /resume 面板展示）。"""

    id: str
    title: str
    count: int
    saved_at: str


class SessionStore:
    """保存 / 列出 / 恢复会话。"""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self._root = _resolve_dir(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        """会话目录的绝对路径。"""
        return self._root

    def next_id(self) -> str:
        """生成一个当前目录下唯一的新会话编号。"""
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = base
        suffix = 2
        while (self._root / f"{candidate}.jsonl").exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def session_path(self, session_id: str) -> Path:
        """会话编号对应的文件路径。"""
        return self._root / f"{session_id}.jsonl"

    def save(self, session: Session) -> SessionMeta:
        """把当前会话保存为 JSONL 文件，返回元数据。"""
        session_id = self.next_id()
        target = self.session_path(session_id)
        with open(target, "w", encoding="utf-8") as f:
            for message in session.messages:
                f.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")

        title = "（空会话）"
        for message in session.messages:
            if message.role == "user":
                title = " ".join(message.content.split())[:50]
                break
        return SessionMeta(
            id=session_id,
            title=title or "（空会话）",
            count=len(session.messages),
            saved_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def list(self) -> list[SessionMeta]:
        """按保存时间倒序（新→旧）返回全部会话摘要。"""
        metas: list[SessionMeta] = []
        for path in sorted(
            self._root.glob("*.jsonl"), key=lambda p: p.name, reverse=True
        ):
            if not path.is_file():
                continue
            first_user = "（空会话）"
            count = 0
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    count += 1
                    if first_user == "（空会话）":
                        try:
                            record = json.loads(line)
                            if record.get("role") == "user":
                                text = " ".join(str(record.get("content", "")).split())
                                if text:
                                    first_user = text[:50]
                        except json.JSONDecodeError:
                            continue
                    if count >= 2 and first_user != "（空会话）":
                        pass
            except OSError:
                continue
            metas.append(
                SessionMeta(
                    id=path.stem,
                    title=first_user,
                    count=count,
                    saved_at=datetime.strptime(
                        path.stem[:14], "%Y%m%d-%H%M%S"
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    if path.stem[:14].isdigit() and len(path.stem) >= 14
                    else path.stem,
                )
            )
        return metas

    def load(self, session_id: str) -> list[Message]:
        """恢复指定会话的全部消息（保持原顺序）。"""
        target = self.session_path(session_id)
        if not target.is_file():
            raise FileNotFoundError(f"会话不存在: {session_id}（可用: {', '.join(m.id for m in self.list()) or '无'}）")
        messages: list[Message] = []
        for line in target.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            messages.append(_message_from_dict(record))
        return messages

    def restore(self, session_id: str) -> Session:
        """恢复会话并返回一个新的 Session 实例。"""
        messages = self.load(session_id)
        session = Session()
        session.restore_messages(messages)
        return session


def _message_from_dict(record: dict) -> Message:
    tool_calls = [
        ToolCall(
            id=str(call.get("id", "")),
            name=str(call.get("function", {}).get("name", "")),
            arguments=str(call.get("function", {}).get("arguments", "")),
        )
        for call in record.get("tool_calls") or []
        if isinstance(call, dict) and isinstance(call.get("function"), dict)
    ]
    return Message(
        role=record.get("role", "user"),
        content=record.get("content", ""),
        tool_calls=tool_calls,
        tool_call_id=record.get("tool_call_id"),
        name=record.get("name"),
    )


__all__ = ["SessionMeta", "SessionStore", "DEFAULT_SESSION_DIR"]