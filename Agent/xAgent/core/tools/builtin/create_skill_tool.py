"""创建技能工具：根据用户自然语言需求生成新的 Agent Skill。"""

from __future__ import annotations

import os
import re
from pathlib import Path

from core.skills import parse_frontmatter
from core.tools.base import Tool, ToolParameter

#: 合法的技能名称：小写字母、数字、连字符。
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: 项目根目录（xAgent）下约定的技能存放目录: <项目>/.agents/skills
_SKILLS_ROOT = (
    Path(__file__).resolve().parents[3] / ".agents" / "skills"
)


def normalize_name(name: str) -> str:
    """校验并规范技能名称，返回小写规范名，非法时抛出 ValueError。"""
    name = (name or "").strip().lower()
    if not _NAME_RE.match(name):
        raise ValueError(
            f"技能名称 {name!r} 不符合规范：仅允许小写字母、数字和连字符，"
            "且不能以连字符开头/结尾。"
        )
    return name


def _derive_description(body: str) -> str:
    """从正文中提取一段简短的描述文本。"""
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"[*_`>]+", "", line).strip()
        if line:
            return line[:80]
    return body.strip()[:80] or "（无描述）"


def ensure_markdown(name: str, context: str) -> str:
    """确保 markdown 文本包含符合 Agent Skills 规范的 Frontmatter。

    若 context 已有 Frontmatter，则保证 name 正确并补上缺失的 description；
    若缺省则自动生成包含 name 与 description 的 Frontmatter。
    """
    context = (context or "").strip("\ufeff \r\n")
    trailing = "\n" if context.endswith("\n") else ""
    metadata, body = parse_frontmatter(context)

    if metadata:  # 已存在 Frontmatter，仅修正/补全字段
        metadata["name"] = name
        metadata.setdefault("description", _derive_description(body))
        front = "\n".join(f"{k}: {v}" for k, v in metadata.items())
        head = f"---\n{front}\n---"
        return f"{head}\n\n{body}".rstrip() + trailing

    # 无 Frontmatter，自动生成
    front = f"---\nname: {name}\ndescription: {_derive_description(context)}\n---"
    return f"{front}\n\n{context}".rstrip() + trailing


class CreateSkillTool(Tool):
    """创建新的 Agent Skill。"""

    name = "createSkill"
    description = (
        "根据用户的自然语言要求创建新的本地技能（Skill）。在 <项目>/.agents/skills/ 下"
        "创建与 name 对应的目录，并写入符合 Agent Skills 规范的 SKILL.md（含 YAML "
        "Frontmatter 的 name 与 description）。name 使用小写字母、数字和连字符；若技能"
        "已存在则返回提示而不覆盖。创建后如需额外参考文献或脚本，请再调用 mkdir / "
        "createFile 等文件操作工具完成。"
    )
    parameters = (
        ToolParameter(name="name", description="技能名称（小写字母、数字、连字符）"),
        ToolParameter(
            name="skillContext",
            description="需要写入 SKILL.md 的完整正文内容（可带或不带 Frontmatter）",
        ),
    )

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        """root 指定技能写入目录，应传 Agent 实际扫描的技能目录。"""
        self._root = Path(root) if root else _SKILLS_ROOT

    def invoke(self, name: str, skillContext: str = "") -> str:
        try:
            safe_name = normalize_name(name)
        except ValueError as exc:
            return str(exc)

        target_directory = self._root / safe_name
        target_file = target_directory / "SKILL.md"
        if target_file.exists():
            return (
                f"技能 {safe_name} 已存在，未创建：{target_file}。"
                "如需更新请改用 editFile / overwrite 修改其内容。"
            )

        try:
            content = ensure_markdown(safe_name, skillContext)
            os.makedirs(target_directory, exist_ok=True)
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            return f"创建技能失败：{exc}"
        return (
            f"创建成功：{target_file}（{os.path.getsize(target_file)} 字节）。\n"
            "该技能已写入规范 Frontmatter，会被技能系统自动发现（listSkills 可见）。"
        )


__all__ = ["CreateSkillTool", "normalize_name", "ensure_markdown"]
