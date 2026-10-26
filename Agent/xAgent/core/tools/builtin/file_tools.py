"""文件操作工具集。"""

from __future__ import annotations

import mimetypes
import os
import shutil

from core.tools.base import Tool, ToolParameter


class GetCwdTool(Tool):
    """获取当前工作目录。"""

    name = "getCwd"
    description = "获取当前工作目录的绝对路径"
    parameters = ()

    def invoke(self) -> str:
        return os.getcwd()


class ListDirTool(Tool):
    """列出目录内容。"""

    name = "listDir"
    description = "列出指定目录下所有文件和子目录"
    parameters = (
        ToolParameter(name="path", description="要列出的目录路径，默认当前目录", required=False),
    )

    def invoke(self, path: str = ".") -> str:
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(path):
            return f"目录不存在: {path}"
        entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        if not entries:
            return f"目录为空: {path}"
        lines = [f"目录: {path}"]
        for entry in entries:
            if entry.is_dir():
                lines.append(f"[目录] {entry.name}")
            else:
                lines.append(f"[文件] {entry.name} ({entry.stat().st_size} 字节)")
        return "\n".join(lines)


class GetFileTypeTool(Tool):
    """获取文件类型。"""

    name = "getFileType"
    description = "获取指定文件的扩展名、MIME类型和内容类型（纯文本/二进制）"
    parameters = (
        ToolParameter(name="path", description="文件的完整路径"),
    )

    def invoke(self, path: str) -> str:
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(path):
            return f"文件不存在: {path}"
        ext = os.path.splitext(path)[1].lower()
        mime, _ = mimetypes.guess_type(path)
        with open(path, "rb") as f:
            sample = f.read(8192)
        is_text = b"\x00" not in sample
        kind = "纯文本" if is_text else "二进制"
        return (
            f"文件: {path}\n"
            f"扩展名: {ext or '(无)'}\n"
            f"MIME类型: {mime or '未知'}\n"
            f"内容类型: {kind}"
        )


class ReadFileTool(Tool):
    """读取文本文件内容。"""

    name = "readFile"
    description = "读取纯文本文件的内容，二进制文件不可读取"
    parameters = (
        ToolParameter(name="path", description="要读取的文本文件路径"),
    )

    def invoke(self, path: str) -> str:
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(path):
            return f"文件不存在: {path}"
        if os.path.getsize(path) == 0:
            return "(空文件)"
        with open(path, "rb") as f:
            sample = f.read(8192)
        if b"\x00" in sample:
            return f"该文件不是纯文本文件，无法读取: {path}"
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                with open(path, "r", encoding=encoding) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
        else:
            return "无法识别的文件编码"
        if len(content) > 20000:
            content = content[:20000] + f"\n...(内容过长，已截断，共 {len(content)} 字符)"
        return content


class CreateFileTool(Tool):
    """创建新文件。"""

    name = "createFile"
    description = "在指定目录下创建新文件，可选写入初始内容"
    parameters = (
        ToolParameter(name="directory", description="新文件所在目录路径"),
        ToolParameter(name="filename", description="文件名，例如 note.txt"),
        ToolParameter(name="content", description="初始内容，可为空", required=False),
    )

    def invoke(self, directory: str, filename: str, content: str = "") -> str:
        directory = os.path.abspath(os.path.expanduser(directory))
        full_path = os.path.join(directory, filename)
        if os.path.exists(full_path):
            return f"文件已存在，未创建: {full_path}"
        os.makedirs(directory, exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content or "")
        return f"创建成功: {full_path} ({os.path.getsize(full_path)} 字节)"


class EditFileTool(Tool):
    """编辑文本文件。"""

    name = "editFile"
    description = "编辑纯文本文件，支持追加、替换、覆盖三种模式"
    parameters = (
        ToolParameter(name="path", description="要编辑的文本文件路径"),
        ToolParameter(name="mode", description="编辑方式：append/overwrite/replace", enum=("append", "overwrite", "replace")),
        ToolParameter(name="content", description="append 或 overwrite 模式下写入的内容", required=False),
        ToolParameter(name="old_text", description="replace 模式下要替换的原文本", required=False),
        ToolParameter(name="new_text", description="replace 模式下替换成的新文本", required=False),
    )

    def invoke(self, path: str, mode: str, content: str = "", old_text: str = "", new_text: str = "") -> str:
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(path):
            return f"文件不存在: {path}"
        with open(path, "rb") as f:
            sample = f.read(8192)
        if b"\x00" in sample:
            return f"该文件不是纯文本文件，无法编辑: {path}"

        if mode == "append":
            with open(path, "a", encoding="utf-8") as f:
                f.write(content or "")
            return f"已追加内容: {path}"

        if mode == "overwrite":
            with open(path, "w", encoding="utf-8") as f:
                f.write(content or "")
            return f"已覆盖内容: {path}"

        if mode == "replace":
            if not old_text:
                return "replace 模式必须提供 old_text"
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            count = text.count(old_text)
            if count == 0:
                return f"未找到要替换的文本: {path}"
            text = text.replace(old_text, new_text or "")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return f"已替换 {count} 处: {path}"

        return f"不支持的模式: {mode}"


class MkdirTool(Tool):
    """创建目录。"""

    name = "mkdir"
    description = "创建新目录（包括多级父目录）"
    parameters = (
        ToolParameter(name="path", description="要创建的目录路径"),
    )

    def invoke(self, path: str) -> str:
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isdir(path):
            return f"目录已存在: {path}"
        os.makedirs(path, exist_ok=True)
        return f"目录创建成功: {path}"


class RmDirTool(Tool):
    """删除目录。"""

    name = "rmDir"
    description = "删除指定目录及其全部内容（支持非空目录）"
    parameters = (
        ToolParameter(name="path", description="要删除的目录路径"),
    )

    def invoke(self, path: str) -> str:
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(path):
            return f"目录不存在: {path}"
        if os.path.ismount(path) or os.path.dirname(path) == path:
            return f"出于安全考虑，拒绝删除磁盘根目录: {path}"
        shutil.rmtree(path)
        return f"目录已删除（含全部内容）: {path}"


class RmFileTool(Tool):
    """删除文件。"""

    name = "rmFile"
    description = "删除指定的文件"
    parameters = (
        ToolParameter(name="path", description="要删除的文件路径"),
    )

    def invoke(self, path: str) -> str:
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(path):
            return f"文件不存在: {path}"
        os.remove(path)
        return f"文件已删除: {path}"
