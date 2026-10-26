"""配置装载。

配置来源优先级：命令行参数 > 环境变量 > config.ini > 默认值。
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from core.errors import ConfigError

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


@dataclass(frozen=True)
class AgentConfig:
    """Agent 运行参数。"""

    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_tool_rounds: int = 8


@dataclass(frozen=True)
class AppConfig:
    """应用级配置。"""

    llm: LLMConfig = field(default_factory=LLMConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
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
        llm = replace(self.llm, **llm_overrides) if llm_overrides else self.llm
        search = (
            replace(self.search, **search_overrides)
            if search_overrides
            else self.search
        )
        agent = replace(self.agent, **agent_overrides) if agent_overrides else self.agent
        return AppConfig(
            llm=llm, search=search, agent=agent, source_path=self.source_path
        )


def find_default_config() -> Path | None:
    """按优先级寻找默认配置文件。"""
    candidates = [
        Path.cwd() / "config.ini",
        PROJECT_ROOT / "config.ini",
    ]
    for candidate in candidates:
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


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    """读取配置文件并与环境变量合并，返回不可变的配置对象。"""
    config_path = Path(path) if path else find_default_config()
    if config_path is None:
        raise ConfigError("未找到 config.ini，请使用 --config 指定配置文件")
    if not config_path.is_file():
        raise ConfigError(f"配置文件不存在: {config_path}")

    parser = _read_ini(config_path)
    llm_section = parser["llm"] if parser.has_section("llm") else {}
    search_section = parser["search"] if parser.has_section("search") else {}
    agent_section = parser["agent"] if parser.has_section("agent") else {}

    llm = LLMConfig(
        base_url=os.getenv("XAGENT_LLM_BASE_URL") or llm_section.get("base_url", LLMConfig.base_url),
        api_key=os.getenv("XAGENT_LLM_API_KEY") or llm_section.get("api_key", ""),
        model=os.getenv("XAGENT_LLM_MODEL") or llm_section.get("model", ""),
        temperature=_to_float(llm_section.get("temperature"), "llm.temperature"),
        max_tokens=_to_int(llm_section.get("max_tokens"), "llm.max_tokens"),
        timeout=_to_float(llm_section.get("timeout"), "llm.timeout"),
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
    )
    agent = AgentConfig(
        system_prompt=agent_section.get("system_prompt", DEFAULT_SYSTEM_PROMPT),
        max_tool_rounds=_to_int(agent_section.get("max_tool_rounds"), "agent.max_tool_rounds")
        or AgentConfig.max_tool_rounds,
    )
    return AppConfig(llm=llm, search=search, agent=agent, source_path=config_path)
