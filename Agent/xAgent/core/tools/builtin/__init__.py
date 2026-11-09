"""内置工具集合。

每个工具一个文件，按业务领域拆分；新增工具时实现 ``Tool`` 并在
``builtin/__init__.py`` 的 ``build_default_registry`` 中注册即可。
"""

from __future__ import annotations

from core.config import SearchConfig
from core.tools.builtin.calendar_tool import IsLeapYearTool
from core.tools.builtin.cli_tool import (
    DEFAULT_TIMEOUT as CLI_DEFAULT_TIMEOUT,
    MAX_OUTPUT_CHARS as CLI_MAX_OUTPUT_CHARS,
)
from core.tools.builtin.cli_tool import RunCliTool
from core.tools.builtin.datetime_tool import GetDateTool
from core.tools.builtin.fetch_tool import (
    DEFAULT_TIMEOUT as FETCH_DEFAULT_TIMEOUT,
    MAX_HTML_BYTES as FETCH_MAX_HTML_BYTES,
    USER_AGENT as FETCH_USER_AGENT,
)
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
from core.tools.builtin.recall_tool import RecallContextTool
from core.tools.builtin.search_tool import SearchWebTool
from core.tools.builtin.skill_tool import ListSkillsTool, LoadSkillTool
from core.tools.registry import ToolRegistry


def build_default_registry(
    search_config: SearchConfig | None = None,
    skills: SkillRegistry | None = None,
    archive_dir: str | None = None,
    cli_config=None,
    fetch_config=None,
    recall_limit: int | None = None,
    snippet_max_chars: int | None = None,
) -> ToolRegistry:
    """构造默认工具注册表。

    :param archive_dir: 历史上下文归档目录，缺省使用项目内 ``.agents/context``。
    :param cli_config: RunCli 参数（超时、输出截断长度）。
    :param fetch_config: fetchWeb 参数（超时、HTML 大小上限、User-Agent）。
    :param recall_limit / snippet_max_chars: recallContext 检索参数。
    """
    search_tool = (
        SearchWebTool.from_config(search_config)
        if search_config is not None
        else SearchWebTool()
    )
    fetch_tool = FetchWebTool(
        timeout=(fetch_config.timeout if fetch_config else FETCH_DEFAULT_TIMEOUT),
        max_html_bytes=(
            getattr(fetch_config, "max_html_bytes", None) or FETCH_MAX_HTML_BYTES
        ),
        user_agent=getattr(fetch_config, "user_agent", None) or FETCH_USER_AGENT,
    )
    cli_tool = RunCliTool(
        timeout=(cli_config.timeout if cli_config else CLI_DEFAULT_TIMEOUT),
        max_output_chars=(
            getattr(cli_config, "max_output_chars", None) or CLI_MAX_OUTPUT_CHARS
        ),
    )
    tools = [
        GetDateTool(),
        search_tool,
        fetch_tool,
        cli_tool,
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
        RecallContextTool(
            archive_dir=archive_dir,
            recall_limit=recall_limit,
            snippet_max_chars=snippet_max_chars,
        ),
    ]
    if skills:
        root = skills.directories[0] if skills.directories else None
        tools.extend([ListSkillsTool(skills), LoadSkillTool(skills), CreateSkillTool(root)])
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
    "RecallContextTool",
    "build_default_registry",
]
