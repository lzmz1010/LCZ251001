"""内置工具集合。

每个工具一个文件，按业务领域拆分；新增工具时实现 ``Tool`` 并在
``builtin/__init__.py`` 的 ``build_default_registry`` 中注册即可。
"""

from __future__ import annotations

from core.config import SearchConfig
from core.tools.builtin.calendar_tool import IsLeapYearTool
from core.tools.builtin.cli_tool import RunCliTool
from core.tools.builtin.datetime_tool import GetDateTool
from core.tools.builtin.fetch_tool import FetchWebTool
from core.tools.builtin.file_tools import (
    CreateFileTool,
    EditFileTool,
    GetCwdTool,
    GetFileTypeTool,
    ListDirTool,
    MkdirTool,
    ReadFileTool,
    RmDirTool,
    RmFileTool,
)
from core.skills import SkillRegistry
from core.tools.builtin.create_skill_tool import CreateSkillTool
from core.tools.builtin.search_tool import SearchWebTool
from core.tools.builtin.skill_tool import ListSkillsTool, LoadSkillTool
from core.tools.registry import ToolRegistry


def build_default_registry(
    search_config: SearchConfig | None = None,
    skills: SkillRegistry | None = None,
) -> ToolRegistry:
    """构造默认工具注册表。"""
    search_tool = (
        SearchWebTool.from_config(search_config)
        if search_config is not None
        else SearchWebTool()
    )
    tools = [
        GetDateTool(),
        search_tool,
        FetchWebTool(),
        RunCliTool(),
        IsLeapYearTool(),
        GetCwdTool(),
        ListDirTool(),
        GetFileTypeTool(),
        ReadFileTool(),
        CreateFileTool(),
        EditFileTool(),
        MkdirTool(),
        RmDirTool(),
        RmFileTool(),
    ]
    if skills:
        tools.extend([ListSkillsTool(skills), LoadSkillTool(skills), CreateSkillTool()])
    return ToolRegistry(tools)


__all__ = [
    "GetDateTool",
    "SearchWebTool",
    "FetchWebTool",
    "RunCliTool",
    "IsLeapYearTool",
    "GetCwdTool",
    "ListDirTool",
    "GetFileTypeTool",
    "ReadFileTool",
    "CreateFileTool",
    "EditFileTool",
    "MkdirTool",
    "RmDirTool",
    "RmFileTool",
    "ListSkillsTool",
    "LoadSkillTool",
    "CreateSkillTool",
    "build_default_registry",
]
