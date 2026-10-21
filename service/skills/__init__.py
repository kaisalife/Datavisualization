"""按需加载的图表技能（渐进式披露）。"""
from .registry import Skill, SkillRegistry, get_skill_registry

__all__ = ["Skill", "SkillRegistry", "get_skill_registry"]
