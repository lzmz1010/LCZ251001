"""本地命令行工具：以当前用户权限执行已安装的 CLI 程序。"""

from __future__ import annotations

import locale
import subprocess

from core.errors import ToolError
from core.tools.base import Tool, ToolParameter

DEFAULT_TIMEOUT = 30.0
MAX_OUTPUT_CHARS = 20_000

class RunCliTool(Tool):
    """执行本地命令行程序，并将 stdout、stderr 和退出码返回给模型。"""

    name = "RunCli"
    description = (
        "执行本地已安装的命令行程序，返回标准输出、标准错误和退出码。"
        "命令名与参数需要分开传入：command 是程序名（如 python、git、ls），"
        "args 是字符串参数列表（如 [\"--version\"]）。"
        "命令以运行 Agent 的当前用户权限执行，请根据退出码和输出判断执行结果。"
    )
    parameters = (
        ToolParameter(
            name="command",
            type="string",
            description="要执行的命令行程序名称或路径，例如 python、git、curl",
            required=True,
        ),
        ToolParameter(
            name="args",
            type="array",
            description="传给程序的参数列表，每个参数都是字符串，例如 [\"--version\"]",
            required=False,
            items="string",
        ),
    )

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        max_output_chars: int = MAX_OUTPUT_CHARS,
    ) -> None:
        self._timeout = timeout
        self._max_output_chars = max_output_chars

    def invoke(self, command: str, args: list[str] | None = None) -> str:
        """执行 command 与 args，返回格式化后的执行结果。"""
        if not isinstance(command, str) or not command.strip():
            raise ToolError("command 必须是非空的程序名称")
        command = command.strip()
        arguments = self._normalize_args(args)
        argv = [command, *arguments]
        display = subprocess.list2cmdline(argv)

        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                timeout=self._timeout,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = self._format_stream("标准输出（超时前）", exc.stdout or b"")
            stderr = self._format_stream("标准错误（超时前）", exc.stderr or b"")
            raise ToolError(
                f"命令执行超时（超过 {self._timeout:g} 秒）: {display}\n\n"
                f"{stdout}\n\n{stderr}"
            ) from exc
        except FileNotFoundError as exc:
            raise ToolError(
                f"未找到命令: {command}（请确认已安装并位于 PATH 中）"
            ) from exc
        except PermissionError as exc:
            raise ToolError(f"没有权限执行命令: {command}: {exc}") from exc
        except (OSError, ValueError) as exc:
            raise ToolError(f"执行命令失败: {display}: {exc}") from exc

        return "\n".join(
            [
                f"命令: {display}",
                f"退出码: {completed.returncode}",
                "",
                self._format_stream("标准输出", completed.stdout or b""),
                "",
                self._format_stream("标准错误", completed.stderr or b""),
            ]
        )

    @staticmethod
    def _normalize_args(args: list[str] | None) -> list[str]:
        if args is None:
            return []
        if not isinstance(args, (list, tuple)):
            raise ToolError("args 必须是字符串数组，例如 [\"--version\"]")
        normalized: list[str] = []
        for item in args:
            if not isinstance(item, str):
                raise ToolError(
                    f"args 中的每个参数都必须是字符串，收到 {type(item).__name__}"
                )
            normalized.append(item)
        return normalized

    def _format_stream(self, title: str, data: bytes) -> str:
        text = self._decode(data).strip()
        if not text:
            return f"{title}:（无输出）"
        max_chars = self._max_output_chars
        if len(text) > max_chars:
            original_length = len(text)
            text = (
                text[:max_chars]
                + f"\n...（{title}过长，已截断：仅保留前 {max_chars} 字符，"
                f"原始长度 {original_length} 字符）"
            )
        return f"{title}:\n{text}"

    @staticmethod
    def _decode(data: bytes) -> str:
        if not data:
            return ""
        encodings = ["utf-8", locale.getpreferredencoding(False), "gb18030"]
        for encoding in encodings:
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode("utf-8", errors="replace")
