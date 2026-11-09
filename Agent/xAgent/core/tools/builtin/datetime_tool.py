"""日期时间工具。"""

from __future__ import annotations

import os
import subprocess

from core.tools.base import Tool


class GetDateTool(Tool):
    """获取当前电脑的日期和时间。"""

    name = "getDate"
    description = "获取当前电脑的日期和时间"
    parameters = ()

    def invoke(self) -> str:
        """调用本地 date 命令获取当前日期和时间（不使用 Python 的日期时间库）。"""
        if os.name == "nt":
            cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; date",
            ]
        else:
            cmd = ["date"]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = (result.stdout or result.stderr).strip()
        return output or "无法获取日期和时间"
