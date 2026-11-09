"""技能（Agent Skills）装载。

技能是一个包含 ``SKILL.md`` 的目录，文件头部可带 YAML frontmatter::

    ---
    name: notice
    description: 撰写公司内部通知
    version: 1.0.0
    ---

    ...技能正文...

本模块负责扫描技能目录、解析元数据，并生成注入系统提示词的技能目录。
技能正文由 ``loadSkill`` 工具在需要时按需加载，避免一次性占用上下文。
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析 ``SKILL.md`` 的 frontmatter，返回 (元数据, 正文)。"""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return {}, text

    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        metadata[key.strip()] = _strip_quotes(value)
    return metadata, text[match.end() :]


def _frontmatter_text(text: str) -> str:
    """返回文本中的 frontmatter 原文（不含开始/结束 ---）。"""
    match = _FRONTMATTER_RE.match(text)
    return match.group(1) if match else ""


@dataclass(frozen=True)
class Skill:
    """一个已装载的技能。"""

    name: str
    description: str
    version: str
    path: Path
    body: str
    source_dir: Path

    def render(self) -> str:
        """读取最新文件内容并生成给模型的完整技能说明。"""
        try:
            text = self.path.read_text(encoding="utf-8-sig")
        except OSError:
            text = self.body

        metadata, body = parse_frontmatter(text)
        description = metadata.get("description") or self.description
        lines = [f"# 技能: {self.name}"]
        if description:
            lines.append(f"描述: {description}")
        triggers = self.keywords()
        if triggers:
            lines.append(f"适合场景 / 触发词: {', '.join(triggers)}")
        if self._has_scripts():
            workdir = self.source_dir
            lines.append("")
            lines.append(
                "【本技能工作目录】"
                f"本技能的脚本和参考资料已解压到绝对路径: {workdir}。"
                "任何脚本、节点程序、数据文件都必须使用该绝对路径，"
                "不要使用相对路径（例如 cd 到该目录后再运行 node scripts/xxx.mjs）。"
            )
        lines.extend(["", body.strip() or self.body.strip()])
        return "\n".join(lines).strip()

    def _has_scripts(self) -> bool:
        """技能目录下是否含脚本或引用文件（SkillHub zip 解压包）。"""
        try:
            if self.source_dir.is_dir():
                for entry in self.source_dir.iterdir():
                    if entry.name.lower() in ("scripts", "references", "package.json"):
                        return True
        except OSError:
            pass
        return False

    def resolve_file(self, filename: str) -> str:
        """解析技能目录内的附加文件路径，返回读取到的内容或候选路径说明。

        按以下顺序（均被限制在技能目录内部，避免越界读取）：
        1. 绝对路径：必须位于技能目录内。
        2. 相对技能目录的路径：``source_dir / filename``。
        3. 项目相对路径：相对于项目根目录，再限定到技能目录内。
        4. 仅文件名：递归搜索技能目录，唯一命中则读取，多个则返回候选路径。

        返回值是对模型可用的文本内容；无法读取时返回说明而非抛异常。
        """
        if not filename:
            return ""
        source = self.source_dir.resolve()

        # 1) 绝对路径；2) 相对技能目录路径；3) 项目相对路径（回落到技能目录）
        p = Path(filename)
        if p.is_absolute():
            target = p.resolve()
        else:
            target = (source / filename.lstrip("/\\")).resolve()

        resolved = _within(source, target)
        if resolved is not None and resolved.is_file():
            return _read_text(resolved)

        # 4) 精确路径未命中则按文件名递归搜索（仅限技能目录内）
        matches = self._search_files(filename)
        if len(matches) == 1:
            return _read_text(matches[0])
        if len(matches) > 1:
            lines = ["找到多个同名文件，请选择其中一个:"]
            lines.extend(
                f"  - {os.path.relpath(m, self.source_dir)}" for m in matches
            )
            return "\n".join(lines)
        return f"在技能 {self.name} 目录中未找到文件: {filename}"

    def _search_files(self, filename: str) -> list[Path]:
        """在技能目录内递归搜索文件名，返回匹配路径列表。"""
        target_name = Path(filename).name.lower()
        matches: list[Path] = []
        if not self.source_dir.is_dir():
            return matches
        for p in self.source_dir.rglob("*"):
            if p.is_file() and p.name.lower() == target_name:
                matches.append(p)
        return matches

    def keywords(self) -> list[str]:
        """从 SKILL.md 的 frontmatter 中提取中文触发词，辅助模型匹配技能。

        只抓取含中文的短片段作为触发词列表；若抓不到则回退到描述里的中文词。
        """
        try:
            text = self.path.read_text(encoding="utf-8-sig")
        except OSError:
            text = self.body
        fm = _frontmatter_text(text)
        words: list[str] = []
        seen: set[str] = set()
        for piece in re.findall(r"[\u4e00-\u9fff][\u4e00-\u9fff，、；：·（）()\- ]{1,30}", fm):
            piece = piece.strip("，、；：·（）()- ")
            if not piece or len(piece) < 2:
                continue
            if piece not in seen:
                seen.add(piece)
                words.append(piece)
        return words[:12]


class SkillRegistry:
    """技能集合：按名称查找技能，并生成系统提示词片段。"""

    def __init__(
        self,
        skills: Iterable[Skill] = (),
        directories: Iterable[str | os.PathLike[str]] = (),
    ) -> None:
        self._skills: dict[str, Skill] = {}
        self._lower_names: dict[str, str] = {}
        self._directories = tuple(
            str(directory) for directory in directories if str(directory).strip()
        )
        for skill in skills:
            self.register(skill)

    def register(self, skill: Skill) -> Skill:
        """注册一个技能，名称重复会报错。"""
        if not skill.name:
            raise ValueError("技能必须提供 name")
        if skill.name.lower() in self._lower_names:
            raise ValueError(f"技能 {skill.name} 已注册")
        self._skills[skill.name] = skill
        self._lower_names[skill.name.lower()] = skill.name
        return skill

    def get(self, name: str) -> Skill | None:
        """按名称查找技能（不区分大小写）。"""
        resolved = self._skills.get(name) or self._skills.get(
            self._lower_names.get(name.lower(), "")
        )
        return resolved

    @property
    def directories(self) -> list[str]:
        """当前扫描的技能目录。"""
        return list(self._directories)

    @property
    def names(self) -> list[str]:
        """已装载的技能名称。"""
        return list(self._skills)

    def all(self) -> list[Skill]:
        """全部技能。"""
        return list(self._skills.values())

    def __len__(self) -> int:
        return len(self._skills)

    def render_prompt(self, base_prompt: str) -> str:
        """在系统提示词后追加技能目录与使用规则。"""
        if not self._skills:
            return base_prompt

        catalog = "\n".join(
            f"- {skill.name}: {skill.description}" for skill in self.all()
        )
        section = (
            "【技能（Skills）】\n"
            "你可以使用以下技能：\n"
            f"{catalog}\n\n"
            "使用规则：\n"
            "- 当用户任务与某技能描述匹配时，必须先调用 loadSkill 工具加载该技能的完整说明，"
            "再严格按照说明完成任务\n"
            "- 不确定技能名称、用户提到的技能不在清单中，或需要查看最新技能时，"
            "调用 listSkills 刷新技能目录\n"
            "- 技能目录会自动发现新增技能，无需用户手动注册\n"
            "- 技能说明中的要求优先级高于一般写作习惯"
        )
        base = base_prompt.rstrip()
        return f"{base}\n\n{section}" if base else section

    @classmethod
    def from_directories(
        cls, directories: Iterable[str | os.PathLike[str]]
    ) -> "SkillRegistry":
        """扫描若干技能目录并装载其中的 ``SKILL.md``。"""
        registry = cls(directories=directories)
        return registry.reload()

    def reload(self) -> "SkillRegistry":
        """重新扫描技能目录，自动发现新增或更新的技能。"""
        if not self._directories:
            return self

        fresh = type(self)()
        for directory in self._directories:
            root = Path(
                os.path.expandvars(os.path.expanduser(directory))
            ).resolve()
            if not root.is_dir():
                continue
            for path in _iter_skillhub_files(root):
                try:
                    skill = fresh._load_file(path)
                except (OSError, ValueError):
                    continue
                if fresh.get(skill.name) is None:
                    fresh.register(skill)

        self._skills = fresh._skills
        self._lower_names = fresh._lower_names
        return self

    @classmethod
    def _load_file(cls, path: Path) -> "Skill":
        text = path.read_text(encoding="utf-8-sig")
        metadata, body = parse_frontmatter(text)
        name = metadata.get("name") or path.parent.name
        return Skill(
            name=name,
            description=metadata.get("description", ""),
            version=metadata.get("version", ""),
            path=path,
            body=body,
            source_dir=path.parent,
        )


def _iter_skill_files(root: Path) -> Iterable[Path]:
    """收集传统的“目录 + SKILL.md”技能。"""
    direct = root / "SKILL.md"
    if direct.is_file():
        yield direct
    try:
        children = sorted(root.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return
    for child in children:
        if not child.is_dir():
            continue
        candidate = child / "SKILL.md"
        if candidate.is_file():
            yield candidate


def _iter_skillhub_files(root: Path) -> Iterable[Path]:
    """收集 SkillHub 技能包（zip 压缩技能 + skillsets 编排说明）。"""
    try:
        children = sorted(root.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return

    # 直接子目录：既有 SKILL.md 的普通技能，也可能是 SkillHub 包目录
    for child in children:
        if not child.is_dir():
            continue
        direct = child / "SKILL.md"
        if direct.is_file():
            yield direct
            continue
        # SkillHub expert-package：skills/*.zip 与 skillsets/*.md
        is_package = (
            (child / "manifest.json").is_file()
            and (child / "skills").is_dir()
        )
        if is_package:
            yield from _extract_zip_skills(child)
            yield from _iter_skillsets(child)

    # 根目录本身也可能是 SkillHub 包
    if (root / "manifest.json").is_file() and (root / "skills").is_dir():
        yield from _extract_zip_skills(root)
        yield from _iter_skillsets(root)


def _iter_skillsets(package: Path) -> Iterable[Path]:
    """收集 skillsets/ 下的编排说明（meta-skill），文件名可为任意 .md。"""
    skillsets_dir = package / "skillsets"
    if not skillsets_dir.is_dir():
        return
    try:
        files = sorted(
            skillsets_dir.iterdir(), key=lambda item: item.name.lower()
        )
    except OSError:
        return
    for item in files:
        if item.is_file() and item.suffix.lower() == ".md":
            yield item


def _extract_zip_skills(package: Path) -> Iterable[Path]:
    """把 skills/ 下各 skill zip 里的 SKILL.md 解压到缓存目录后逐一产出。"""
    skills_dir = package / "skills"
    if not skills_dir.is_dir():
        return
    cache = package / ".xagent_skillhub_cache"
    try:
        cache.mkdir(exist_ok=True)
    except OSError:
        return
    try:
        archives = sorted(
            skills_dir.iterdir(), key=lambda item: item.name.lower()
        )
    except OSError:
        return
    for archive in archives:
        if not (archive.is_file() and archive.suffix.lower() == ".zip"):
            continue
        yield from _extract_zip(archive, cache)


def _extract_zip(archive: Path, cache: Path) -> Iterable[Path]:
    """完整解压 skill zip 到工作目录，返回其中的 SKILL.md 路径。

    SkillHub 的 zip 不仅包含 SKILL.md，还包含脚本（scripts/）、参考资料
    （references/）、package.json 等。脚本运行时依赖这些附属文件，因此必须
    整体解压，而不能只取 SKILL.md。
    """
    base = cache / archive.stem
    marker = base / ".extracted"
    try:
        if not base.is_dir():
            base.mkdir(parents=True, exist_ok=True)
        if not marker.exists() or _maybe_stale(marker, archive):
            _unzip_quiet(archive, base)
            marker.write_text("ok", encoding="utf-8")
    except (OSError, zipfile.BadZipFile):
        return

    out = base / "SKILL.md"
    if out.is_file():
        yield out


def _unzip_quiet(archive: Path, dest: Path) -> None:
    """安全解压 zip 到 dest，跳过 SKILL.md 之外的文件，避免路径穿越。"""
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if (info.filename or "").endswith("/"):
                continue
            target = _safe_target(dest, info.filename)
            if target is None:
                continue
            try:
                with zf.open(info) as src, open(target, "wb") as dst:
                    dst.write(src.read())
            except OSError:
                continue


def _safe_target(dest: Path, name: str) -> Path | None:
    """把压缩包里的条目名解析为 dest 下的安全路径，杜绝目录穿越。"""
    clean = name.replace("\\\\", "/")
    target = (dest / clean).resolve()
    if not target.is_relative_to(dest.resolve()):
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _find_skill_entry(zf: zipfile.ZipFile) -> str | None:
    """返回压缩包里 SKILL.md 的条目名（区分大小写优先，其次忽略大小写）。"""
    names = zf.namelist()
    for name in names:
        if name == "SKILL.md" or name.endswith("/SKILL.md"):
            return name
    for name in names:
        if name.lower().endswith("skill.md") or name.lower().endswith("skills.md"):
            return name
    return None


def _maybe_stale(cached: Path, archive: Path) -> bool:
    """缓存文件比原 zip 旧则视为失效，需要重新解压。"""
    try:
        archive_mtime = archive.stat().st_mtime_ns
        cached_mtime = cached.stat().st_mtime_ns
        return cached_mtime < archive_mtime
    except OSError:
        return False


def _within(source: Path, target: Path) -> Path | None:
    """若 ``target`` 位于 ``source`` 目录内则返回之，否则返回 None。"""
    rel = os.path.relpath(target, source)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return None
    return target


def _read_text(path: Path) -> str:
    """读取文本文件内容，失败时返回错误说明。"""
    try:
        data = path.read_bytes()
    except OSError as exc:
        return f"无法读取文件: {path} ({exc})"
    if b"\x00" in data:
        return f"文件是二进制文件，无法以文本读取: {path}"
    for encoding in ("utf-8-sig", "gbk", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    return f"无法解码文件: {path}"


__all__ = ["Skill", "SkillRegistry", "parse_frontmatter"]
