"""技能装载与技能工具测试。"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.bootstrap import build_agent, build_registry, build_skill_registry  # noqa: E402
from core.config import AppConfig, LLMConfig, SkillsConfig  # noqa: E402
from core.skills import Skill, SkillRegistry, parse_frontmatter  # noqa: E402

SKILL_TEXT = """---
name: notice
description: "撰写公司内部通知"
version: "1.0.0"
---

1. 标题必须包含部门名称。
2. 落款必须包含起草人姓名。
"""


class SkillParsingTests(unittest.TestCase):
    """SKILL.md 解析测试。"""

    def test_parse_frontmatter(self) -> None:
        metadata, body = parse_frontmatter(SKILL_TEXT)
        self.assertEqual(metadata["name"], "notice")
        self.assertEqual(metadata["description"], "撰写公司内部通知")
        self.assertIn("部门名称", body)
        self.assertNotIn("name: notice", body)

    def test_parse_without_frontmatter(self) -> None:
        metadata, body = parse_frontmatter("直接是正文")
        self.assertEqual(metadata, {})
        self.assertEqual(body, "直接是正文")


class SkillRegistryTests(unittest.TestCase):
    """技能目录扫描与查找测试。"""

    def test_from_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notice").mkdir()
            (root / "notice" / "SKILL.md").write_text(SKILL_TEXT, encoding="utf-8")
            (root / "root_skill").mkdir()
            (root / "root_skill" / "SKILL.md").write_text(
                "---\nname: root_skill\ndescription: 根目录技能\n---\n正文",
                encoding="utf-8",
            )

            skills = SkillRegistry.from_directories([root, root / "missing"])

        self.assertEqual(skills.names, ["notice", "root_skill"])
        self.assertIsNotNone(skills.get("NOTICE"))
        self.assertIsNone(skills.get("unknown"))

    def test_skillhub_package_zip_and_skillsets(self) -> None:
        """SkillHub 包：skills/*.zip 解压 + skillsets/*.md 编排说明均可加载。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "mysticism-zodiac-fortune"
            (package / "skills").mkdir(parents=True)
            (package / "skillsets").mkdir()
            (package / "manifest.json").write_text(
                "{\"type\":\"skillhub-expert-package\","
                "\"slug\":\"mysticism-zodiac-fortune\","
                "\"skillSlugs\":[\"aistro\"]}",
                encoding="utf-8",
            )
            (package / "skillsets" / "mysticism-zodiac-fortune.md").write_text(
                "---\nname: mysticism-zodiac-fortune\n"
                "description: 生肖星座运势专家包\n---\n编排正文",
                encoding="utf-8",
            )
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(
                    "SKILL.md",
                    "---\nname: aistro\ndescription: 占星咨询\n"
                    "keywords: 占星 本命盘 月相\n---\n本命盘解读\n",
                )
                zf.writestr("scripts/horoscope.mjs", "// script\n")
                zf.writestr("references/natal-report.md", "# natal\n")
            (package / "skills" / "aistro.zip").write_bytes(buf.getvalue())

            skills = SkillRegistry.from_directories([root])
            aistro = skills.get("aistro")
            workdir = aistro.source_dir

            self.assertEqual(
                sorted(skills.names), ["aistro", "mysticism-zodiac-fortune"]
            )
            self.assertIn("本命盘解读", aistro.render())
            self.assertIn(
                "编排正文", skills.get("mysticism-zodiac-fortune").render()
            )
            # 完整解压：附属脚本与参考文件应被解压出来
            self.assertTrue((workdir / "scripts" / "horoscope.mjs").is_file())
            self.assertTrue((workdir / "references" / "natal-report.md").is_file())
            # 中文触发词应被提取并注入渲染
            self.assertTrue(any("本命盘" in kw for kw in aistro.keywords()))
            self.assertIn("本命盘", aistro.render())

    def _skill_with_extra_files(self, root: Path) -> Skill:
        skill_dir = root / "astrology"
        (skill_dir / "references").mkdir(parents=True)
        (skill_dir / "scripts").mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: astrology\ndescription: 占星\n---\n正文",
            encoding="utf-8",
        )
        (skill_dir / "references" / "natal-report.md").write_text(
            "# natal 报告\n", encoding="utf-8"
        )
        (skill_dir / "references" / "predict-report.md").write_text(
            "# predict 报告\n", encoding="utf-8"
        )
        (skill_dir / "scripts" / "cal.mjs").write_text("// calc\n", encoding="utf-8")
        return SkillRegistry.from_directories([root]).get("astrology")

    def test_resolve_file_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = self._skill_with_extra_files(Path(tmp))
            content = skill.resolve_file("references/natal-report.md")

        self.assertIn("natal 报告", content)

    def test_resolve_file_by_unique_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = self._skill_with_extra_files(Path(tmp))
            content = skill.resolve_file("cal.mjs")

        self.assertIn("// calc", content)

    def test_resolve_file_multiple_matches_returns_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "astrology" / "references").mkdir(parents=True)
            (root / "astrology" / "notes").mkdir()
            (root / "astrology" / "SKILL.md").write_text(
                "---\nname: astrology\ndescription: 占星\n---\n正文",
                encoding="utf-8",
            )
            (root / "astrology" / "references" / "guide.md").write_text("A\n")
            (root / "astrology" / "notes" / "guide.md").write_text("B\n")
            skill = SkillRegistry.from_directories([root]).get("astrology")
            content = skill.resolve_file("guide.md")

        self.assertIn("多个同名", content)

    def test_resolve_file_outside_dir_blocked(self) -> None:
        # 绝对路径指向技能目录之外时，不得读取
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = self._skill_with_extra_files(root)
            secret = root / "secret.txt"
            secret.write_text("敏感内容\n", encoding="utf-8")
            content = skill.resolve_file(str(secret.resolve()))

        self.assertNotIn("敏感内容", content)

    def test_duplicate_names_keep_first(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for root, description in ((first, "第一个"), (second, "第二个")):
                (Path(root) / "notice").mkdir()
                (Path(root) / "notice" / "SKILL.md").write_text(
                    f"---\nname: notice\ndescription: {description}\n---\n正文",
                    encoding="utf-8",
                )
            skills = SkillRegistry.from_directories([first, second])

        self.assertEqual(skills.names, ["notice"])
        self.assertEqual(skills.get("notice").description, "第一个")


class SkillToolTests(unittest.TestCase):
    """技能工具测试。"""

    def _registry(self, root: Path):
        (root / "notice").mkdir()
        (root / "notice" / "SKILL.md").write_text(SKILL_TEXT, encoding="utf-8")
        return build_registry(None, SkillRegistry.from_directories([root]))

    def test_list_and_load_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self._registry(Path(tmp))

            listed = registry.execute("listSkills", "")
            loaded = registry.execute(
                "loadSkill", json.dumps({"name": "notice"}, ensure_ascii=False)
            )

        self.assertIn("listSkills", registry.names)
        self.assertIn("loadSkill", registry.names)
        self.assertFalse(listed.is_error)
        self.assertIn("notice", listed.content)
        self.assertFalse(loaded.is_error)
        self.assertIn("部门名称", loaded.content)

    def test_load_unknown_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self._registry(Path(tmp))
            result = registry.execute("loadSkill", '{"name": "missing"}')

        self.assertIn("未知技能", result.content)

    def test_load_skill_with_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            skill_dir = workdir / "astrology"
            (skill_dir / "references").mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: astrology\ndescription: 占星\n---\n正文",
                encoding="utf-8",
            )
            (skill_dir / "references" / "natal-report.md").write_text(
                "# natal 报告内容\n", encoding="utf-8"
            )
            registry = build_registry(
                None, SkillRegistry.from_directories([workdir])
            )

            result = registry.execute(
                "loadSkill",
                json.dumps(
                    {"name": "astrology", "filename": "references/natal-report.md"},
                    ensure_ascii=False,
                ),
            )

        self.assertFalse(result.is_error)
        self.assertIn("natal 报告内容", result.content)
        # 加载附加文件时不应把 SKILL.md 正文也带出来（只加载附加文件）
        self.assertNotIn("占星正文", result.content)


class SkillBootstrapTests(unittest.TestCase):
    """技能装配到 Agent 的测试。"""

    def test_build_agent_injects_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notice").mkdir()
            (root / "notice" / "SKILL.md").write_text(SKILL_TEXT, encoding="utf-8")
            config = AppConfig(
                llm=LLMConfig(model="demo-model"),
                skills=SkillsConfig(dirs=(str(root),)),
            )

            self.assertEqual(build_skill_registry(config).names, ["notice"])
            agent = build_agent(config)

        self.assertIn("loadSkill", agent.tools.names)
        self.assertIn("notice", agent.session.messages[0].content)
        self.assertIn("撰写公司内部通知", agent.session.messages[0].content)

    def test_build_agent_without_skills(self) -> None:
        agent = build_agent(AppConfig(llm=LLMConfig(model="demo-model")))
        self.assertNotIn("loadSkill", agent.tools.names)


if __name__ == "__main__":
    unittest.main()
