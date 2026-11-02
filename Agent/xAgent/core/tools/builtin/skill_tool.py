"""技能工具：列出技能并按需加载技能说明。"""

from __future__ import annotations

from core.skills import SkillRegistry
from core.tools.base import Tool, ToolParameter


class ListSkillsTool(Tool):
    """列出当前可用的技能。"""

    name = "listSkills"
    description = "列出当前可用的技能及其用途。不确定该使用哪个技能时先调用。"
    parameters = ()

    def __init__(self, skills: SkillRegistry) -> None:
        self._skills = skills

    def invoke(self) -> str:
        self._skills.reload()
        if not self._skills:
            return "当前没有加载任何技能。"
        lines = [f"可用技能（共 {len(self._skills)} 个）："]
        lines.extend(
            f"- {skill.name}: {skill.description}" for skill in self._skills.all()
        )
        lines.append("需要使用时请调用 loadSkill(name) 加载完整说明。")
        return "\n".join(lines)


class LoadSkillTool(Tool):
    """按名称加载技能的完整说明，或加载技能附加文件。"""

    name = "loadSkill"
    description = (
        "加载指定技能的完整说明。当用户任务与技能描述匹配时必须先调用，"
        "然后严格按照技能说明执行。若不提供 filename 则加载该技能的 SKILL.md 全文；"
        "若提供 filename 则加载技能目录内对应的附加文件（如 references、scripts 等），"
        "不重复加载 SKILL.md。filename 支持相对技能目录的路径、或仅文件名（自动递归搜索）。"
    )
    parameters = (
        ToolParameter(name="name", description="技能名称，例如 notice"),
        ToolParameter(
            name="filename",
            description="可选。需要加载的技能附加文件路径或名称，例如 references/natal-report.md",
            required=False,
        ),
    )

    def __init__(self, skills: SkillRegistry) -> None:
        self._skills = skills

    def invoke(self, name: str, filename: str = "") -> str:
        skill = self._skills.get(name)
        if skill is None:
            self._skills.reload()
            skill = self._skills.get(name)
        if skill is None:
            available = ", ".join(self._skills.names) or "无"
            return f"未知技能: {name}。可用技能: {available}"
        if filename:
            content = skill.resolve_file(filename)
            return (
                f"技能 {skill.name} 的附加文件 [{filename}]:\n\n"
                f"{content}"
            )
        return skill.render()


__all__ = ["ListSkillsTool", "LoadSkillTool"]
