"""用户自定义技能 API

GET    /api/skills            列出全部技能（内置 + 用户，标注来源与覆盖关系）
GET    /api/skills/<name>     读一份技能的完整 SKILL.md（内置技能只读，可当模板用）
POST   /api/skills            保存一份用户技能（JSON: name + content），非法内容 400
PUT    /api/skills/<name>     更新一份用户技能正文
DELETE /api/skills/<name>     删除一份用户技能；删掉覆盖内置的同名技能即恢复内置

保存/删除即时生效：进程内组合注册表在写盘成功后 reload，
下一次规划/生成请求就能看到新技能，无需重启服务。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from Entity import ErrorResponse
from api.common import check_api_key, monitor_response

from service.observability import get_logger
from service.skills.user_skills import SkillValidationError, UserSkillStore

logger = get_logger("api.skills")

skills_bp = Blueprint("skills", __name__, url_prefix="/api")


def _store() -> UserSkillStore:
    return UserSkillStore()


def _registry():
    from service.skills.registry import get_skill_registry

    return get_skill_registry()


def _builtin_registry():
    """组合注册表的内置子注册表（覆盖关系判定 / 内置正文读取用）。"""
    composite = _registry()
    return getattr(composite, "_builtin", composite)


def _payload() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _skill_meta(skill, source: str, overrides_builtin: bool) -> dict:
    return {
        "name": skill.name,
        "title": skill.title,
        "description": skill.description,
        "source": source,
        "overrides_builtin": overrides_builtin,
        "chart_types": list(skill.metadata.get("chart_types") or []),
        "analysis_tasks": list(skill.metadata.get("analysis_tasks") or []),
        "user_keywords": list(skill.metadata.get("user_keywords") or []),
        "require_keywords": bool(skill.metadata.get("require_keywords")),
    }


@skills_bp.route("/skills", methods=["GET"])
@monitor_response("skills_api:list_skills")
def list_skills():
    """列出全部技能：内置 + 用户，附来源、覆盖关系与元数据摘要。"""
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    registry = _registry()
    composite = registry if hasattr(registry, "_builtin") else None
    builtin_names = {s.name for s in composite._builtin.skills} if composite else set()

    items: list[dict] = []
    for skill in registry.skills:
        is_user = (composite is not None and composite.is_user_skill(skill.name))
        source = "user" if is_user else "builtin"
        items.append(
            _skill_meta(skill, source, is_user and skill.name in builtin_names)
        )

    # 目录里有但解析失败的文件也要暴露出来，别让用户存了坏技能却查无此技能
    invalid = [item for item in composite.user_store.list() if item.get("invalid")] if composite else []

    return jsonify({"count": len(items), "skills": items, "invalid_user_skills": invalid}), 200


def _builtin_text(name: str) -> str:
    """内置技能的原始文件文本（含 frontmatter，前端可直接当编辑模板）。"""
    from service.skills.registry import _default_root

    path = _default_root() / name / "SKILL.md"
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


@skills_bp.route("/skills/<name>", methods=["GET"])
@monitor_response("skills_api:get_skill")
def get_skill(name: str):
    """读一份技能的完整 SKILL.md；内置技能只读。"""
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    store = _store()
    registry = _registry()
    try:
        if store.exists(name):
            return (
                jsonify(
                    {
                        "name": name,
                        "source": "user",
                        "overrides_builtin": registry.overrides_builtin(name)
                        if hasattr(registry, "overrides_builtin")
                        else False,
                        "content": store.read(name),
                    }
                ),
                200,
            )
    except SkillValidationError as e:
        return jsonify(ErrorResponse(detail=str(e)).model_dump()), 400

    builtin = _builtin_registry()
    if builtin.get(name) is not None:
        return jsonify({"name": name, "source": "builtin", "content": _builtin_text(name)}), 200

    return jsonify(ErrorResponse(detail=f"技能不存在: {name}").model_dump()), 404


@skills_bp.route("/skills", methods=["POST"])
@monitor_response("skills_api:save_skill")
def save_skill():
    """保存一份用户技能（name + content）；保存后立即 reload 生效。"""
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    payload = _payload()
    name = str(payload.get("name") or "").strip()
    content = payload.get("content")
    if not name or not isinstance(content, str) or not content.strip():
        return (
            jsonify(
                ErrorResponse(
                    detail="必须提供 name 与 content（content 为完整 SKILL.md 文本）"
                ).model_dump()
            ),
            400,
        )

    try:
        meta = _store().save(name, content, builtin_registry=_builtin_registry())
    except SkillValidationError as e:
        return jsonify(ErrorResponse(detail=str(e)).model_dump()), 400
    except OSError as e:
        return jsonify(ErrorResponse(detail=f"写入失败: {e}").model_dump()), 500

    _registry().reload()
    logger.info("用户技能已保存", name=meta.get("name"), overrides_builtin=meta.get("overrides_builtin"))
    return jsonify({"skill": meta}), 201


@skills_bp.route("/skills/<name>", methods=["PUT"])
@monitor_response("skills_api:update_skill")
def update_skill(name: str):
    """更新一份用户技能正文；技能第一次保存时等价于 POST。"""
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    payload = _payload()
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return jsonify(ErrorResponse(detail="必须提供 content（完整 SKILL.md 文本）").model_dump()), 400

    store = _store()
    existed = store.exists(name)
    try:
        meta = store.save(name, content, builtin_registry=_builtin_registry())
    except SkillValidationError as e:
        return jsonify(ErrorResponse(detail=str(e)).model_dump()), 400
    except OSError as e:
        return jsonify(ErrorResponse(detail=f"写入失败: {e}").model_dump()), 500

    _registry().reload()
    logger.info("用户技能已更新", name=name, existed=existed)
    return jsonify({"skill": meta, "existed": existed}), 200


@skills_bp.route("/skills/<name>", methods=["DELETE"])
@monitor_response("skills_api:delete_skill")
def delete_skill(name: str):
    """删除用户技能；删除覆盖内置的同名技能后自动恢复内置版本。"""
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    store = _store()
    try:
        if not store.exists(name):
            if _builtin_registry().get(name) is not None:
                return jsonify(
                    ErrorResponse(
                        detail=f"{name} 是内置技能，不能删除；"
                        "如果它被子目录里同名用户技能覆盖，删除该用户技能即可恢复"
                    ).model_dump()
                ), 400
            return jsonify(ErrorResponse(detail=f"用户技能不存在: {name}").model_dump()), 404
        store.delete(name)
    except SkillValidationError as e:
        return jsonify(ErrorResponse(detail=str(e)).model_dump()), 400

    _registry().reload()
    logger.info("用户技能已删除", name=name)
    return jsonify({"removed": True, "name": name}), 200
