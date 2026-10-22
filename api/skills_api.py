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
from service.skills.skill_polisher import (
    build_polish_chat,
    polish_skill_sync as polish_skill_draft,
)
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


@skills_bp.route("/skills/polish", methods=["POST"])
@monitor_response("skills_api:polish_skill")
def polish_skill():
    """把用户的一句话需求润色成规范 SKILL.md 草稿（**不保存**，前端确认后再 POST /api/skills）。

    请求（JSON）:
        ``prompt``（必填）：用户粗糙描述；
        ``name``（可选）：技能 slug，frontmatter 会使用它；
        ``model_url`` / ``model_api_key`` / ``model_type``（可选）：请求级模型凭证
        （缺省回落到 .env 的 SKILL_POLISH_* / BASE_URL / API_KEY / MODEL_NAME）。

    响应:
        ``{"content": SKILL.md 全文, "skill": {name,title,description,...}}``

    错误:
        400 输入/生成结果不合规（detail 带具体原因，可直接展示给用户）；
        502 模型调用失败。
    """
    auth_error = check_api_key()
    if auth_error:
        return auth_error

    payload = _payload()
    raw_prompt = str(payload.get("prompt") or "").strip()
    name_hint = str(payload.get("name") or "").strip()
    if not raw_prompt:
        return jsonify(ErrorResponse(detail="必须提供 prompt（你的需求描述）").model_dump()), 400
    if len(raw_prompt) > 4000:
        return jsonify(ErrorResponse(detail="prompt 过长（上限 4000 字符）").model_dump()), 400

    try:
        chat = build_polish_chat(
            model_url=str(payload.get("model_url") or ""),
            model_api_key=str(payload.get("model_api_key") or ""),
            model_type=str(payload.get("model_type") or ""),
        )
    except RuntimeError as e:
        return jsonify(ErrorResponse(detail=str(e)).model_dump()), 400

    try:
        draft = polish_skill_draft(chat, raw_prompt, name_hint)
    except SkillValidationError as e:
        return (
            jsonify(
                ErrorResponse(
                    detail=f"生成的技能不合规：{e}；可修改描述后重试，或手工编辑后保存"
                ).model_dump()
            ),
            400,
        )
    except Exception as e:  # 模型/网关错误
        logger.warning("技能润色失败", error=str(e), error_type=type(e).__name__)
        return (
            jsonify(
                ErrorResponse(detail=f"模型调用失败: {type(e).__name__}: {e}").model_dump()
            ),
            502,
        )

    logger.info("技能润色草稿已生成", name=draft["skill"].get("name"))
    return jsonify(draft), 200


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
