"""图表技能注册表：主 prompt 只带索引，需要时再加载完整技能。

技能是 Markdown + YAML frontmatter，放在项目根目录 ``skills/`` 下。每个技能用
``description`` 暴露一句话用途；完整正文只在规划 agent 调用 ``load_skill`` 或
生成阶段按计划/数据形态命中时才进入上下文，避免把所有特殊场景规则塞进主 prompt。

frontmatter 支持（均为可选，除 name/description）：
- title: 展示名
- chart_types: 适用图表类型，如 [Line, Area]
- analysis_tasks: 适用分析任务，如 [trend]
- time_like: true 时只匹配时间序列
- min_rows: 最少行数
- min_series: 最少指标列数
- user_keywords: 用户需求关键词（用于规划/生成时的轻量匹配）
- require_keywords: true 时 user_keywords 变成硬门槛——用户没提场景词就不命中，
  用于防止形态撞车（如普通排行与帕累托同为 Bar+comparison）
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


def _default_root() -> Path:
    """技能目录：默认项目根/skills，可用 SKILLS_DIR 覆盖。"""
    env = os.getenv("SKILLS_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[2] / "skills"


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """解析简单的 key: value / 行内列表 frontmatter，不引入额外依赖。

    技能 frontmatter 只用于声明类型、任务、阈值和关键词，不承载复杂 YAML 结构；
    需要更复杂配置时应放进正文，而不是把 frontmatter 变成第二套 DSL。
    """
    meta: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        key = key.strip()
        raw = raw.strip()
        if not key:
            continue
        if raw.startswith("[") and raw.endswith("]"):
            items = []
            for item in raw[1:-1].split(","):
                item = item.strip().strip("'\"")
                if item:
                    items.append(item)
            meta[key] = items
        elif raw.lower() in {"true", "false"}:
            meta[key] = raw.lower() == "true"
        elif raw.isdigit():
            meta[key] = int(raw)
        else:
            meta[key] = raw.strip("'\"")
    return meta


def _parse_skill(path: Path) -> "Skill | None":
    """解析一个 SKILL.md；格式不完整时返回 None，不让单个坏文件拖垮流程。"""
    try:
        # utf-8-sig 兼容 Windows 编辑器保存的 BOM，避免 frontmatter 识别失败
        text = path.read_text(encoding="utf-8-sig").lstrip("\ufeff")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    meta = _parse_frontmatter(parts[1])
    if not meta:
        return None
    name = str(meta.get("name") or path.parent.name).strip()
    if not name:
        return None
    description = str(meta.get("description") or "").strip()
    if not description:
        return None
    body = parts[2].strip()
    return Skill(
        name=name,
        title=str(meta.get("title") or name).strip(),
        description=description,
        body=body,
        metadata=meta,
        path=path,
    )


@dataclass(frozen=True)
class Skill:
    """一个可渐进加载的图表技能。"""

    name: str
    title: str
    description: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    def matches(
        self,
        *,
        chart_type: str,
        analysis_task: str,
        time_like: bool,
        rows: int,
        series_count: int,
        user_prompt: str,
        source_kind: str = "",
    ) -> bool:
        """按 frontmatter 的通用约束判断是否适用，不在代码里写死场景。"""
        chart_types = {
            _normalize(item) for item in (self.metadata.get("chart_types") or [])
        }
        if chart_types and chart_type not in chart_types:
            return False

        tasks = {
            _normalize(item) for item in (self.metadata.get("analysis_tasks") or [])
        }
        if tasks and analysis_task not in tasks:
            return False

        required_time = self.metadata.get("time_like")
        if required_time is True and not time_like:
            return False
        if required_time is False and time_like:
            return False

        try:
            min_rows = int(self.metadata.get("min_rows") or 0)
        except (TypeError, ValueError):
            min_rows = 0
        if min_rows and rows < min_rows:
            return False

        try:
            min_series = int(self.metadata.get("min_series") or 0)
        except (TypeError, ValueError):
            min_series = 0
        if min_series and series_count < min_series:
            return False

        source_kinds = {
            _normalize(item) for item in (self.metadata.get("source_kinds") or [])
        }
        if source_kinds and _normalize(source_kind) not in source_kinds:
            return False

        # require_keywords: 只有用户提到场景词才命中（防止形态撞车——
        # 比如"城市销售额排行"和"不良项主次因素"都是 Bar+comparison，
        # 帕累托类技能只应在用户说出业务语义时生效）。
        if self.metadata.get("require_keywords"):
            keywords = [
                str(k) for k in (self.metadata.get("user_keywords") or []) if str(k)
            ]
            if keywords and not any(k in user_prompt for k in keywords):
                return False

        # user_keywords 只参与 score 排序，不是硬约束：
        # 同一张表的用户可能不写“股票/传感器”，但仍应命中数据约束。
        return True

    def score(
        self,
        *,
        chart_type: str,
        analysis_task: str,
        rows: int,
        series_count: int,
        user_prompt: str,
        source_kind: str = "",
    ) -> int:
        score = 0
        chart_types = {
            _normalize(item) for item in (self.metadata.get("chart_types") or [])
        }
        if chart_types and chart_type in chart_types:
            score += 3
        tasks = {
            _normalize(item) for item in (self.metadata.get("analysis_tasks") or [])
        }
        if tasks and analysis_task in tasks:
            score += 2
        try:
            min_rows = int(self.metadata.get("min_rows") or 0)
        except (TypeError, ValueError):
            min_rows = 0
        if min_rows and rows >= min_rows:
            score += 2
        try:
            min_series = int(self.metadata.get("min_series") or 0)
        except (TypeError, ValueError):
            min_series = 0
        if min_series and series_count >= min_series:
            score += 2
        source_kinds = {
            _normalize(item) for item in (self.metadata.get("source_kinds") or [])
        }
        if source_kinds and _normalize(source_kind) in source_kinds:
            score += 2
        for keyword in self.metadata.get("user_keywords") or []:
            if str(keyword) and str(keyword) in user_prompt:
                score += 1
        return score


class SkillRegistry:
    """从目录加载技能，提供索引、加载和按计划选择。"""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else _default_root()
        self._skills: dict[str, Skill] = {}
        self.reload()

    def reload(self) -> None:
        self._skills = {}
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("*/SKILL.md")):
            skill = _parse_skill(path)
            if skill is not None:
                self._skills[skill.name.lower()] = skill

    @property
    def skills(self) -> list[Skill]:
        return list(self._skills.values())

    def get(self, name: str) -> Skill | None:
        return self._skills.get(str(name or "").strip().lower())

    def index_text(self) -> str:
        """紧凑索引：只给名称、标题和一句话用途。"""
        if not self._skills:
            return "(无技能)"
        return "\n".join(
            f"- {skill.name}: {skill.title} — {skill.description}"
            for skill in self._skills.values()
        )

    def select(
        self,
        *,
        plan: dict[str, Any] | None,
        series: Any = None,
        user_prompt: str = "",
        max_skills: int = 2,
    ) -> list[Skill]:
        """按计划类型 + series 形态选择技能；没有命中就返回空列表。"""
        plan = plan if isinstance(plan, dict) else {}
        chart_type = _normalize(plan.get("chart_type"))
        analysis_task = _normalize(plan.get("analysis_task"))
        shape = {}
        extra: dict[str, Any] = {}
        if series is not None:
            extra = getattr(series, "extra_semantics", None) or {}
            shape = extra.get("shape") or {}
        source_kind = str(extra.get("source_kind") or shape.get("source_kind") or "")
        rows = int(shape.get("rows") or shape.get("row_labels") or 0)
        series_count = len(getattr(series, "column_label_columns", []) or []) if series else 0
        time_like = bool(shape.get("time_like")) or (
            str(getattr(series, "axis_kind", "")).lower() == "time_series"
        )

        candidates: list[tuple[int, Skill]] = []
        for skill in self._skills.values():
            if not skill.matches(
                chart_type=chart_type,
                analysis_task=analysis_task,
                time_like=time_like,
                rows=rows,
                series_count=series_count,
                user_prompt=user_prompt,
                source_kind=source_kind,
            ):
                continue
            score = skill.score(
                chart_type=chart_type,
                analysis_task=analysis_task,
                rows=rows,
                series_count=series_count,
                user_prompt=user_prompt,
                source_kind=source_kind,
            )
            if score > 0:
                candidates.append((score, skill))
        candidates.sort(key=lambda item: (-item[0], item[1].name))
        return [skill for _, skill in candidates[:max_skills]]

    def context_for_plan(
        self,
        *,
        plan: dict[str, Any] | None,
        series: Any = None,
        user_prompt: str = "",
        max_skills: int = 2,
    ) -> str:
        """生成阶段注入的完整技能文本；没有命中返回 '(无)'。"""
        selected = self.select(
            plan=plan, series=series, user_prompt=user_prompt, max_skills=max_skills
        )
        if not selected:
            return "(无)"
        return "\n\n".join(
            f"### 技能：{skill.title}\n{skill.body}" for skill in selected
        )


@lru_cache(maxsize=1)
def get_skill_registry() -> SkillRegistry:
    """进程内复用技能注册表（技能目录是静态资源）。"""
    return SkillRegistry()
