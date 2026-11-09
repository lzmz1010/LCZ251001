"""配置装载。

配置来源优先级：命令行参数 > 环境变量 > config.ini > 默认值。
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from core.errors import ConfigCreatedError, ConfigError

# 项目根目录（core 的上一级），用于定位默认的 config.ini
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SYSTEM_PROMPT = (
    "你是一个本地命令行Agent，拥有以下工具能力，需要获取真实信息时必须调用对应工具，"
    "禁止自己猜测或拒绝。\n\n"
    "可用工具列表：\n"
    "1. getDate - 获取电脑当前日期和时间\n"
    "2. searchWeb - 联网搜索实时信息，返回搜索摘要与参考来源（标题、URL）\n"
    "3. fetchWeb - 抓取指定网页正文并转换为 Markdown（保留标题、段落、列表、表格和链接）\n"
    "4. RunCli - 执行本地命令行程序，返回标准输出、标准错误和退出码\n"
    "5. isLeapYear - 判断给定年份是否为闰年\n"
    "6. getCwd - 获取当前工作目录\n"
    "7. listDir - 列出目录下所有文件和子目录\n"
    "8. getFileType - 获取文件类型（扩展名、MIME、文本/二进制）\n"
    "9. readFile - 读取纯文本文件内容\n"
    "10. createFile - 创建新文件，可写入初始内容\n"
    "11. editFile - 编辑文本文件（append追加/overwrite覆盖/replace替换）\n"
    "12. mkdir - 创建新目录\n"
    "13. rmDir - 删除目录及其全部内容\n"
    "14. rmFile - 删除文件\n\n"
    "调用规则：\n"
    "- 问到时间、年份、文件、目录等本地信息时，必须先调用对应工具获取真实数据，再回答\n"
    "- 涉及实时新闻、最新消息、近期数据或你不确定的信息时，必须先调用 searchWeb 联网搜索\n"
    "- 使用 searchWeb 的结果回答时，应结合摘要并注明参考来源的标题和 URL\n"
    "- 当搜索结果摘要不足、需要阅读网页全文，或用户给出网页链接时，调用 fetchWeb 获取正文\n"
    "- 需要运行本地命令行程序时调用 RunCli：command 传程序名，args 传字符串参数列表，根据退出码和输出判断结果\n"
    "- 不要告诉用户让他自己敲命令或自己上网查，你自己调用工具完成\n"
    "- 回答保持简洁，结构清晰"
)


@dataclass(frozen=True)
class LLMConfig:
    """大模型连接参数。"""

    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str = ""
    model: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchConfig:
    """联网搜索参数（百度千帆百度搜索）。"""

    api_key: str = ""
    base_url: str = "https://qianfan.baidubce.com/v2/ai_search/web_search"
    edition: str = "standard"
    timeout: float = 60.0
    summary_max_chars: int = 4000


@dataclass(frozen=True)
class CliConfig:
    """本地命令行执行参数。"""

    timeout: float = 30.0
    max_output_chars: int = 20_000


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(frozen=True)
class FetchConfig:
    """网页正文抓取参数。"""

    timeout: float = 30.0
    max_html_bytes: int = 10 * 1024 * 1024
    user_agent: str = DEFAULT_USER_AGENT


@dataclass(frozen=True)
class McpClientConfig:
    """MCP 客户端连接参数与配置文件范围。

    ``files``：额外的 ``.mcp.json`` 路径列表（相对当前目录或绝对路径）。
    为空时只加载「启动时当前目录」下的 ``.mcp.json``；
    非空时按顺序合并依次加载，同名服务器后者覆盖。
    """

    default_timeout: float = 60.0
    connect_timeout: float = 30.0
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionsConfig:
    """会话保存目录。"""

    dir: str = ".agents/sessions"


@dataclass(frozen=True)
class AgentsConfig:
    """AGENTS.md 项目约定注入。"""

    inject: bool = True
    md_file: str = "AGENTS.md"


@dataclass(frozen=True)
class UIConfig:
    """界面刷新参数。"""

    render_interval: float = 0.08
    context_refresh_interval: float = 5.0


@dataclass(frozen=True)
class SkillsConfig:
    """技能目录配置。"""

    dirs: tuple[str, ...] = ()


DEFAULT_CONTEXT_WINDOW = 128_000


@dataclass(frozen=True)
class ContextConfig:
    """上下文管理与压缩配置。

    ``window_is_default``：为 True 表示未在配置中显式指定上下文窗口，
    界面应显示「默认」提示。
    """

    context_window: int = DEFAULT_CONTEXT_WINDOW
    window_is_default: bool = True
    warn_ratio: float = 0.7
    summary_tokens: int = 5_000
    archive_dir: str = ".agents/context"
    recall_limit: int = 8
    snippet_max_chars: int = 300


@dataclass(frozen=True)
class AgentConfig:
    """Agent 运行参数。"""

    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_tool_rounds: int = 8
    empty_response_retries: int = 2


@dataclass(frozen=True)
class AppConfig:
    """应用级配置。"""

    llm: LLMConfig = field(default_factory=LLMConfig)
    llm_backup: LLMConfig | None = None
    search: SearchConfig = field(default_factory=SearchConfig)
    cli: CliConfig = field(default_factory=CliConfig)
    fetch: FetchConfig = field(default_factory=FetchConfig)
    mcp: McpClientConfig = field(default_factory=McpClientConfig)
    sessions: SessionsConfig = field(default_factory=SessionsConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    source_path: Path | None = None

    def with_overrides(self, **kwargs: Any) -> "AppConfig":
        """返回覆盖了部分字段的新配置（配置对象不可变）。"""
        llm_overrides = {
            key[4:]: value
            for key, value in kwargs.items()
            if key.startswith("llm_") and value is not None
        }
        search_overrides = {
            key[7:]: value
            for key, value in kwargs.items()
            if key.startswith("search_") and value is not None
        }
        agent_overrides = {
            key[6:]: value
            for key, value in kwargs.items()
            if key.startswith("agent_") and value is not None
        }
        skills_overrides = {
            key[7:]: value
            for key, value in kwargs.items()
            if key.startswith("skills_") and value is not None
        }
        context_overrides = {
            key[8:]: value
            for key, value in kwargs.items()
            if key.startswith("context_") and value is not None
        }
        llm = replace(self.llm, **llm_overrides) if llm_overrides else self.llm
        search = (
            replace(self.search, **search_overrides)
            if search_overrides
            else self.search
        )
        agent = replace(self.agent, **agent_overrides) if agent_overrides else self.agent
        skills = (
            replace(self.skills, **skills_overrides)
            if skills_overrides
            else self.skills
        )
        context = (
            replace(self.context, **context_overrides)
            if context_overrides
            else self.context
        )
        return AppConfig(
            llm=llm,
            llm_backup=self.llm_backup,
            search=search,
            cli=self.cli,
            fetch=self.fetch,
            mcp=self.mcp,
            sessions=self.sessions,
            agents=self.agents,
            ui=self.ui,
            agent=agent,
            skills=skills,
            context=context,
            source_path=self.source_path,
        )


def find_default_config() -> Path | None:
    """按优先级寻找默认配置文件。

    「当前目录」优先：运行 xAgent 时若当前目录没有 config.ini，
    会触发自动生成示例配置（见 ``load_config``），而不是静默复用项目配置。
    """
    candidate = Path.cwd() / "config.ini"
    if candidate.is_file():
        return candidate
    return None


def _read_ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error as exc:  # pragma: no cover - 依赖外部文件
        raise ConfigError(f"配置文件解析失败: {path}: {exc}") from exc
    return parser


def _to_float(value: str | None, name: str) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"配置项 {name} 不是合法数字: {value}") from exc


def _to_int(value: str | None, name: str) -> int | None:
    if value is None or value.strip() == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"配置项 {name} 不是合法整数: {value}") from exc


def _split_dirs(value: str | None) -> tuple[str, ...]:
    """把多目录配置拆成元组，支持换行或分号分隔。"""
    if value is None or not value.strip():
        return ()
    normalized = value.replace("\r", "\n").replace(";", "\n")
    return tuple(
        part.strip() for part in normalized.split("\n") if part.strip()
    )


MOCK_CONFIG_TEXT = """\
; xAgent 示例配置（自动生成）。请按实际情况修改后重新启动程序。
; 主模型与备用模型均支持任意 OpenAI 兼容接口。

[llm]
; 主模型（必填）：任选一个 OpenAI 兼容服务
; 示例：本地 LM Studio / Ollama:
base_url = http://127.0.0.1:1234/v1
api_key = lm-studio
model = qwen2.5-7b-instruct-gguf
temperature = 0.7
; max_tokens = 2048

[llm_backup]
; 备用模型：主模型请求失败时自动回退（可为空，留空表示不启用备用）
base_url = http://127.0.0.1:1234/v1
api_key = lm-studio
model = qwen2.5-7b-instruct-gguf

[search]
; 联网搜索（百度千帆「百度搜索」），baidu_qianfan_api_key 为必填
baidu_qianfan_api_key =
; base_url = https://qianfan.baidubce.com/v2/ai_search/web_search
edition = standard
timeout = 60
; summary_max_chars = 4000

[agent]
system_prompt = 你是本地Agent。需要真实信息/实时数据/文件/命令时，必须调用工具，禁止凭空猜测或编造；工具返回结果后用自然语言整理回答用户。回答必须严格只针对用户最新发来的这一条消息，禁止复读、复述上一轮的回答，禁止把历史对话里的旧内容当答案；若拿不出可靠答案，就说缺少什么信息、需要哪些输入。
max_tool_rounds = 8
empty_response_retries = 2

[skills]
; 技能（Agent Skills）目录，可多个，用分号或换行分隔
dirs =

[context]
; 模型上下文窗口（tokens）；留空时按默认 128000 处理
; context_window = 131072
warn_ratio = 0.7
summary_tokens = 5000
archive_dir = .agents/context
recall_limit = 8
snippet_max_chars = 300

[cli]
; 本地命令行工具 RunCli 参数
timeout = 30
max_output_chars = 20000

[fetch]
; 网页正文抓取 fetchWeb 参数
timeout = 30
max_html_bytes = 10485760
user_agent = Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36

[mcp]
; MCP 客户端连接参数
default_timeout = 60
connect_timeout = 30
; 加载范围：默认只加载「启动时当前目录」的 .mcp.json；
; 需要额外加载其它 .mcp.json 时在此指定（可多个，分号或换行分隔，同名服务器后者覆盖）
; files = D:/LLM/Agent/.mcp.json

[sessions]
; 会话保存/恢复目录（/new /save /resume）
dir = .agents/sessions

[agents]
; AGENTS.md 项目约定注入：会话首次加载时注入一次，全程复用
inject = true
md_file = AGENTS.md

[ui]
render_interval = 0.08
context_refresh_interval = 5.0
"""


def _ensure_config_template(target: Path) -> ConfigCreatedError:
    """在当前目录生成一份示例 config.ini，并返回对应的提示异常。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not target.exists():
            target.write_text(MOCK_CONFIG_TEXT, encoding="utf-8")
    except OSError as exc:
        return ConfigCreatedError(
            target,
            f"未找到配置文件，且自动生成失败（{target}: {exc}）。"
            "请手动创建 config.ini 后再启动。",
        )
    return ConfigCreatedError(
        target,
        f"当前目录没有 config.ini，已自动生成示例配置：{target}\n"
        "请打开该文件，按注释填写模型地址、API Key 等必要信息后，重新启动程序。",
    )


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    """读取配置文件并与环境变量合并，返回不可变的配置对象。

    当前目录（或项目目录）没有 config.ini 时，自动生成一份完整示例配置，
    并通过 ``ConfigCreatedError`` 提示用户修改后重新启动。
    """
    config_path = Path(path) if path else find_default_config()
    if config_path is None:
        raise _ensure_config_template(Path.cwd() / "config.ini")
    if not config_path.is_file():
        raise ConfigError(f"配置文件不存在: {config_path}")

    parser = _read_ini(config_path)
    llm_section = parser["llm"] if parser.has_section("llm") else {}
    backup_section = parser["llm_backup"] if parser.has_section("llm_backup") else {}
    search_section = parser["search"] if parser.has_section("search") else {}
    cli_section = parser["cli"] if parser.has_section("cli") else {}
    fetch_section = parser["fetch"] if parser.has_section("fetch") else {}
    mcp_section = parser["mcp"] if parser.has_section("mcp") else {}
    sessions_section = parser["sessions"] if parser.has_section("sessions") else {}
    agents_section = parser["agents"] if parser.has_section("agents") else {}
    ui_section = parser["ui"] if parser.has_section("ui") else {}
    agent_section = parser["agent"] if parser.has_section("agent") else {}
    skills_section = parser["skills"] if parser.has_section("skills") else {}
    context_section = parser["context"] if parser.has_section("context") else {}

    llm = LLMConfig(
        base_url=os.getenv("XAGENT_LLM_BASE_URL") or llm_section.get("base_url", LLMConfig.base_url),
        api_key=os.getenv("XAGENT_LLM_API_KEY") or llm_section.get("api_key", ""),
        model=os.getenv("XAGENT_LLM_MODEL") or llm_section.get("model", ""),
        temperature=_to_float(llm_section.get("temperature"), "llm.temperature"),
        max_tokens=_to_int(llm_section.get("max_tokens"), "llm.max_tokens"),
        timeout=_to_float(llm_section.get("timeout"), "llm.timeout"),
    )
    backup_model = os.getenv("XAGENT_LLM_BACKUP_MODEL") or backup_section.get("model", "")
    llm_backup: LLMConfig | None = None
    if backup_model:
        llm_backup = LLMConfig(
            base_url=os.getenv("XAGENT_LLM_BACKUP_BASE_URL")
            or backup_section.get("base_url", LLMConfig.base_url),
            api_key=os.getenv("XAGENT_LLM_BACKUP_API_KEY")
            or backup_section.get("api_key", ""),
            model=backup_model,
            temperature=_to_float(
                backup_section.get("temperature"), "llm_backup.temperature"
            ),
            max_tokens=_to_int(backup_section.get("max_tokens"), "llm_backup.max_tokens"),
            timeout=_to_float(backup_section.get("timeout"), "llm_backup.timeout"),
        )
    search = SearchConfig(
        api_key=os.getenv("XAGENT_SEARCH_API_KEY")
        or search_section.get("baidu_qianfan_api_key", ""),
        base_url=os.getenv("XAGENT_SEARCH_BASE_URL")
        or search_section.get("base_url", SearchConfig.base_url),
        edition=os.getenv("XAGENT_SEARCH_EDITION")
        or search_section.get("edition", SearchConfig.edition),
        timeout=_to_float(search_section.get("timeout"), "search.timeout")
        or SearchConfig.timeout,
        summary_max_chars=(
            _to_int(search_section.get("summary_max_chars"), "search.summary_max_chars")
            or SearchConfig.summary_max_chars
        ),
    )
    cli = CliConfig(
        timeout=_to_float(cli_section.get("timeout"), "cli.timeout")
        or CliConfig.timeout,
        max_output_chars=(
            _to_int(cli_section.get("max_output_chars"), "cli.max_output_chars")
            or CliConfig.max_output_chars
        ),
    )
    fetch = FetchConfig(
        timeout=_to_float(fetch_section.get("timeout"), "fetch.timeout")
        or FetchConfig.timeout,
        max_html_bytes=(
            _to_int(fetch_section.get("max_html_bytes"), "fetch.max_html_bytes")
            or FetchConfig.max_html_bytes
        ),
        user_agent=(
            fetch_section.get("user_agent", "") or FetchConfig.user_agent
        ),
    )
    mcp = McpClientConfig(
        default_timeout=(
            _to_float(mcp_section.get("default_timeout"), "mcp.default_timeout")
            or McpClientConfig.default_timeout
        ),
        connect_timeout=(
            _to_float(mcp_section.get("connect_timeout"), "mcp.connect_timeout")
            or McpClientConfig.connect_timeout
        ),
        files=_split_dirs(mcp_section.get("files", "")),
    )
    sessions = SessionsConfig(
        dir=sessions_section.get("dir", SessionsConfig.dir)
    )
    agents = AgentsConfig(
        inject=(
            agents_section.get("inject", "true").strip().lower()
            not in ("false", "0", "no")
        ),
        md_file=agents_section.get("md_file", AgentsConfig.md_file),
    )
    ui = UIConfig(
        render_interval=(
            _to_float(ui_section.get("render_interval"), "ui.render_interval")
            or UIConfig.render_interval
        ),
        context_refresh_interval=(
            _to_float(
                ui_section.get("context_refresh_interval"),
                "ui.context_refresh_interval",
            )
            or UIConfig.context_refresh_interval
        ),
    )
    agent = AgentConfig(
        system_prompt=agent_section.get("system_prompt", DEFAULT_SYSTEM_PROMPT),
        max_tool_rounds=_to_int(agent_section.get("max_tool_rounds"), "agent.max_tool_rounds")
        or AgentConfig.max_tool_rounds,
        empty_response_retries=(
            _to_int(agent_section.get("empty_response_retries"), "agent.empty_response_retries")
            or AgentConfig.empty_response_retries
        ),
    )
    skills = SkillsConfig(
        dirs=_split_dirs(
            os.getenv("XAGENT_SKILLS_DIRS") or skills_section.get("dirs", "")
        )
    )
    window = _to_int(context_section.get("context_window"), "context.context_window")
    context = ContextConfig(
        # 空白/未填 → 默认 128k，并标记为「默认」，界面据此显示提示
        context_window=window if window is not None else DEFAULT_CONTEXT_WINDOW,
        window_is_default=(window is None),
        warn_ratio=(
            _to_float(context_section.get("warn_ratio"), "context.warn_ratio")
            or ContextConfig.warn_ratio
        ),
        summary_tokens=(
            _to_int(context_section.get("summary_tokens"), "context.summary_tokens")
            or ContextConfig.summary_tokens
        ),
        archive_dir=context_section.get("archive_dir", ContextConfig.archive_dir),
        recall_limit=(
            _to_int(context_section.get("recall_limit"), "context.recall_limit")
            or ContextConfig.recall_limit
        ),
        snippet_max_chars=(
            _to_int(
                context_section.get("snippet_max_chars"),
                "context.snippet_max_chars",
            )
            or ContextConfig.snippet_max_chars
        ),
    )
    return AppConfig(
        llm=llm,
        llm_backup=llm_backup,
        search=search,
        cli=cli,
        fetch=fetch,
        mcp=mcp,
        sessions=sessions,
agents=agents,
        ui=ui,
        agent=agent,
        skills=skills,
        context=context,
        source_path=config_path,
    )
