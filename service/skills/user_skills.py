"""用户自定义技能：目录存储 + 组合注册表。

用户不改仓库、不写代码也能扩展场景技能：把一份 SKILL.md 交给
``UserSkillStore`` 校验后放进用户技能目录即可生效——规划索引、``load_skill``
工具与生成阶段的技能注入自动看到它（全部经 ``get_skill_registry``）。

结构（模块化，不散改既有代码，接线只有 registry.get_skill_registry 一行委托）：

- ``UserSkillStore``：用户技能目录的读写层。默认 ``<项目根>/skills_user``，
  可用 ``USER_SKILLS_DIR`` 覆盖；保存前做名称（slug）/ frontmatter / 大小校验，
  非法内容写不进目录。
- ``CompositeSkillRegistry``：内置目录 + 用户目录两个 ``SkillRegistry`` 的组合
  视图，接口与 ``SkillRegistry`` 一致；**用户技能与内置同名时用户覆盖**
  （删掉同名用户技能即恢复内置，便于微调内置场景而不动仓库）。
- ``build_default_registry``：构造组合注册表，由 ``get_skill_registry`` 委托调用。

复用原则：解析（``_parse_skill``）、匹配/评分（``Skill.matches/score``）与
选择/注入（``SkillRegistry.select/context_for_plan``）全部沿用原实现，
本模块只做存储校验和目录合并，不复制技能逻辑。
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from service.skills.registry import (
    Skill,
    SkillRegistry,
    _default_root,
    _parse_skill,
)

# 名称是目录名，必须是不含路径成分的小写 slug，从源头挡住路径穿越
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
# 单份技能正文上限（几百行 SKILL.md 远远够用，防误传大文件）
_MAX_SKILL_BYTES = 256 * 1024


def _user_root() -> Path:
    """用户技能目录：默认项目根/skills_user，可用 USER_SKILLS_DIR 覆盖。

    每次调用动态读取环境变量：测试可以把目录切到临时路径；
    生产里改了环境变量后再触发一次 reload 即可切换目录。
    """
    env = os.getenv("USER_SKILLS_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[2] / "skills_user"


class SkillValidationError(ValueError):
    """用户技能内容非法；错误信息要说明哪一条不满足、怎么改。"""


class UserSkillStore:
    """用户技能目录的读写层：保存 / 读取 / 删除 / 列表，全部经过校验。"""

    def __init__(self, root: str | Path | None = None):
        # 显式传 root 的场景（测试 / 备用部署）锁定目录；
        # 不传则动态跟随 USER_SKILLS_DIR。
        self._fixed_root = Path(root) if root is not None else None

    @property
    def root(self) -> Path:
        return self._fixed_root or _user_root()

    def skill_path(self, name: str) -> Path:
        """返回 <root>/<name>/SKILL.md；name 不是合法 slug 直接拒绝。"""
        name = str(name or "").strip()
        if not _NAME_RE.match(name):
            raise SkillValidationError(
                f"技能名称非法: {name!r}；要求 2–64 位小写字母/数字/连字符，"
                "例如 wind-turbine-kpi"
            )
        return self.root / name / "SKILL.md"

    # ---------- 读 ----------

    def list(self) -> list[dict[str, Any]]:
        """用户技能元数据列表（不含正文，供接口/前端展示）。"""
        items: list[dict[str, Any]] = []
        if not self.root.exists():
            return items
        for path in sorted(self.root.glob("*/SKILL.md")):
            skill = _parse_skill(path)
            if skill is None:
                # 坏文件不炸列表，标记出来让用户能看到并修正
                items.append({"name": path.parent.name, "invalid": True})
                continue
            item = self._meta(skill, path)
            items.append(item)
        return items

    def _meta(self, skill: Skill, path: Path) -> dict[str, Any]:
        try:
            updated_at = int(path.stat().st_mtime)
        except OSError:
            updated_at = 0
        return {
            "name": skill.name,
            "title": skill.title,
            "description": skill.description,
            "chart_types": list(skill.metadata.get("chart_types") or []),
            "analysis_tasks": list(skill.metadata.get("analysis_tasks") or []),
            "user_keywords": list(skill.metadata.get("user_keywords") or []),
            "require_keywords": bool(skill.metadata.get("require_keywords")),
            "updated_at": updated_at,
        }

    def read(self, name: str) -> str:
        """读一份用户技能的完整 SKILL.md 文本。"""
        path = self.skill_path(name)
        if not path.is_file():
            raise FileNotFoundError(f"用户技能不存在: {name}")
        return path.read_text(encoding="utf-8-sig")

    def exists(self, name: str) -> bool:
        path = self.skill_path(name)
        return path.is_file()

    # ---------- 写 ----------

    def save(self, name: str, content: str, *, builtin_registry: SkillRegistry | None = None) -> dict[str, Any]:
        """校验并保存一份天用户技能；返回元数据（含 overrides_builtin 标记）。"""
        content = str(content or "")
        if not content.strip():
            raise SkillValidationError("技能内容为空")
        encoded = content.encode("utf-8")
        if len(encoded) > _MAX_SKILL_BYTES:
            raise SkillValidationError(
                f"技能正文过大（{len(encoded)} 字节 > {_MAX_SKILL_BYTES} 上限）；"
                "把长范例挪进 RAG 知识库，技能只留工作流指南"
            )

        path = self.skill_path(name)  # 名称校验（含穿越拒绝）
        parsed = _parse_skill_text(content, expected_name=path.parent.name)

        # 落盘后用真实解析器再验一遍（与运行时完全同一条路径），失败即回滚
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(content, encoding="utf-8")
            probe = SkillRegistry(self.root)
            if probe.get(parsed.name) is None:
                raise SkillValidationError("技能写入后无法被解析（frontmatter 不完整）")
        except SkillValidationError:
            shutil.rmtree(path.parent, ignore_errors=True)
            raise
        except OSError as e:
            shutil.rmtree(path.parent, ignore_errors=True)
            raise SkillValidationError(f"写入失败: {e}") from e

        overrides = False
        if builtin_registry is not None and builtin_registry.get(parsed.name) is not None:
            overrides = True

        return {**self._meta(parsed, path), "overrides_builtin": overrides}

    def delete(self, name: str) -> None:
        """删除用户技能目录；不存在时报 404 语义。"""
        path = self.skill_path(name)
        if not path.is_file():
            raise FileNotFoundError(f"用户技能不存在: {name}")
        shutil.rmtree(path.parent, ignore_errors=True)


def _parse_skill_text(content: str, *, expected_name: str) -> "Skill":
    """在落盘前解析正文，frontmatter 问题在这里给用户可读的错误。"""
    stripped = content.lstrip("\ufeff")
    if not stripped.startswith("---"):
        raise SkillValidationError(
            "缺少 YAML frontmatter：SKILL.md 必须以 --- 开头，"
            "声明 name / description / chart_types 等字段"
        )
    parsed = _parse_skill_from_text(stripped)
    if parsed is None:
        raise SkillValidationError(
            "frontmatter 解析失败：需要 name 与 description 两个必填字段，"
            "格式为 `---\nname: xxx\n---\n正文`"
        )
    if parsed.name != expected_name:
        raise SkillValidationError(
            f"frontmatter 的 name（{parsed.name!r}）与提交的技能名（{expected_name!r}）不一致"
        )
    if not parsed.body.strip():
        raise SkillValidationError("正文为空：frontmatter 之后要写场景工作流指南")
    return parsed


def _parse_skill_from_text(text: str) -> "Skill | None":
    """复用 ``_parse_skill`` 的解析逻辑于内存文本（临时文件承接同一条路径）。"""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "SKILL.md"
        probe.write_text(text, encoding="utf-8")
        return _parse_skill(probe)


class CompositeSkillRegistry:
    """内置 + 用户目录的组合注册表；接口与 SkillRegistry 一致。

    合并视图：用户技能按名称覆盖内置同名（便于微调内置场景而不改仓库）。
    所有方法直接委托给一个由两个目录合并而成的 ``SkillRegistry``
    实例——匹配/评分/选择逻辑零复制，行为与单一目录注册表完全一致。
    """

    def __init__(self, *, builtin_root: str | Path | None = None, user_store: UserSkillStore | None = None):
        self._builtin_root = Path(builtin_root) if builtin_root is not None else _default_root()
        # 内置注册表必须落成实例：保存接口要做“是否覆盖内置”检查
        self._builtin = SkillRegistry(self._builtin_root)
        self.user_store = user_store or UserSkillStore()
        self._rebuild()

    def _rebuild(self) -> None:
        """重建合并视图；用户目录每次以当前 USER_SKILLS_DIR 为准（动态切换）。"""
        user_root = self.user_store.root
        view = SkillRegistry(user_root)
        merged = dict(self._builtin._skills)
        for key, skill in view._skills.items():
            merged[key] = skill  # 用户覆盖内置同名
        view._skills = merged
        self._view = view
        self._user_root = user_root

    def reload(self) -> None:
        """重新扫描两个目录；保存/删除用户技能后由 API 调用。"""
        self._builtin.reload()
        self._rebuild()

    # ---------- 委托至合并视图 ----------

    @property
    def skills(self) -> list[Skill]:
        return self._view.skills

    def get(self, name: str) -> Skill | None:
        return self._view.get(name)

    def index_text(self) -> str:
        return self._view.index_text()

    def select(self, **kwargs: Any) -> list[Skill]:
        return self._view.select(**kwargs)

    def context_for_plan(self, **kwargs: Any) -> str:
        return self._view.context_for_plan(**kwargs)

    # ---------- 用户技能辅助 ----------

    def is_user_skill(self, name: str) -> bool:
        """该名称是否来自用户目录（决定能否删除 / 编辑）。"""
        try:
            return self.user_store.exists(name)
        except SkillValidationError:
            return False

    def overrides_builtin(self, name: str) -> bool:
        return self.user_store.exists(name) and self._builtin.get(name) is not None


def build_default_registry() -> CompositeSkillRegistry:
    """构造默认组合注册表（内置 skills/ + 用户 skills_user/）。"""
    return CompositeSkillRegistry()
