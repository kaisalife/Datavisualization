"""用户自定义技能回归（无 LLM）：存储校验 / 组合注册表 / REST API 三层。

设计约束：新逻辑全部在 service/skills/user_skills.py 与 api/skills_api.py，
原 registry 只有一行委托接线；用户技能与内置同名时用户覆盖，
删除用户技能即恢复内置。目录经 USER_SKILLS_DIR 切换，测试不碰仓库内置目录。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.skills.registry import get_skill_registry
from service.skills.user_skills import (
    CompositeSkillRegistry,
    SkillValidationError,
    UserSkillStore,
)

pytestmark = pytest.mark.whitebox

VALID_SKILL = """---
name: wind-turbine-kpi
title: 风机 KPI 达成
description: 单值达成率用仪表盘呈现，而不是柱状图
chart_types: [Gauge]
analysis_tasks: [comparison]
require_keywords: true
user_keywords: [风机, 台量, 达成率, 发电量完成]
---

# 风机 KPI 达成

## 适用判断
- 单个或少数几个完成率指标，用户关心“完成没”。

## 要点
- Gauge 需要显式 min/max 域。
"""


@pytest.fixture
def store(tmp_path: Path) -> UserSkillStore:
    return UserSkillStore(root=tmp_path / "skills_user")


@pytest.fixture
def composite(tmp_path: Path) -> CompositeSkillRegistry:
    return CompositeSkillRegistry(
        user_store=UserSkillStore(root=tmp_path / "skills_user")
    )


# ---------- UserSkillStore：校验与读写 ----------


class TestUserSkillStore:
    def test_save_and_list_roundtrip(self, store: UserSkillStore):
        meta = store.save("wind-turbine-kpi", VALID_SKILL)

        assert meta["name"] == "wind-turbine-kpi"
        assert meta["overrides_builtin"] is False
        assert meta["require_keywords"] is True
        assert (store.root / "wind-turbine-kpi" / "SKILL.md").is_file()

        listed = {item["name"]: item for item in store.list()}
        # 列表能读回元数据（含 chart_types 关键字段）
        assert listed["wind-turbine-kpi"]["title"] == "风机 KPI 达成"

        content = store.read("wind-turbine-kpi")
        assert "min/max 域" in content

    def test_save_rejects_illegal_names(self, store: UserSkillStore):
        # 名称即目录名：穿越、大写、空着一律拒绝，文件不会被创建
        for bad in ("../evil", "a/b", "Bad Name", "A", "", "x" * 100):
            with pytest.raises(SkillValidationError):
                store.save(bad, VALID_SKILL)
        if store.root.exists():
            assert not list(store.root.glob("**/SKILL.md"))

    def test_save_rejects_body_without_frontmatter(self, store: UserSkillStore):
        with pytest.raises(SkillValidationError, match="frontmatter"):
            store.save("no-front", "正文没有 frontmatter")

    def test_save_rejects_missing_description(self, store: UserSkillStore):
        text = "---\nname: no-desc\n---\n正文"
        with pytest.raises(SkillValidationError, match="解析失败"):
            store.save("no-desc", text)
        assert not store.exists("no-desc")

    def test_save_rejects_name_mismatch(self, store: UserSkillStore):
        with pytest.raises(SkillValidationError, match="不一致"):
            store.save("target-name", VALID_SKILL.replace("wind-turbine-kpi", "other-name"))

    def test_save_rejects_empty_body(self, store: UserSkillStore):
        text = "---\nname: empty-body\ndescription: 只有 frontmatter\n---\n"
        with pytest.raises(SkillValidationError, match="正文"):
            store.save("empty-body", text)
        assert not store.exists("empty-body")

    def test_save_rejects_oversized_content(
        self, store: UserSkillStore, monkeypatch: pytest.MonkeyPatch
    ):
        import service.skills.user_skills as mod

        monkeypatch.setattr(mod, "_MAX_SKILL_BYTES", 200)
        with pytest.raises(SkillValidationError, match="过大"):
            store.save("too-big", VALID_SKILL)

    def test_delete_and_exists(self, store: UserSkillStore):
        store.save("wind-turbine-kpi", VALID_SKILL)
        assert store.exists("wind-turbine-kpi")

        store.delete("wind-turbine-kpi")
        assert not store.exists("wind-turbine-kpi")
        assert not (store.root / "wind-turbine-kpi").exists()

        with pytest.raises(FileNotFoundError):
            store.delete("wind-turbine-kpi")


# ---------- CompositeSkillRegistry：合并选择与覆盖 ----------


class TestCompositeSkillRegistry:
    def test_user_skill_enters_index_and_select(
        self, composite: CompositeSkillRegistry, tmp_path: Path
    ):
        composite.user_store.save("wind-turbine-kpi", VALID_SKILL)
        composite.reload()

        assert "wind-turbine-kpi" in composite.index_text()

        from service.data_ingestion.series.models import SemanticSeries

        series = SemanticSeries(
            series_id="kpi.风机",
            name="kpi.风机",
            axis_kind="category",
            row_label_column="指标",
            column_label_columns=["达成率"],
            data_path=str(tmp_path / "kpi.parquet"),
            source_table="kpi",
            description="单指标 KPI",
            extra_semantics={
                "shape": {"rows": 1, "time_like": False},
                "source_kind": "file",
            },
        )
        # 关键词命中 → 选中；require_keywords 门控同样作用于用户技能
        selected = composite.select(
            plan={"chart_type": "Gauge", "analysis_task": "comparison"},
            series=series,
            user_prompt="看看3号风机的达成率",
        )
        assert any(s.name == "wind-turbine-kpi" for s in selected)

        plain = composite.select(
            plan={"chart_type": "Gauge", "analysis_task": "comparison"},
            series=series,
            user_prompt="仪表盘显示当前水位",
        )
        assert all(s.name != "wind-turbine-kpi" for s in plain)

        context = composite.context_for_plan(
            plan={"chart_type": "Gauge", "analysis_task": "comparison"},
            series=series,
            user_prompt="看看3号风机的达成率",
        )
        assert "风机 KPI 达成" in context

    def test_user_skill_overrides_builtin_then_restores(
        self, composite: CompositeSkillRegistry
    ):
        override = VALID_SKILL.replace(
            "name: wind-turbine-kpi", "name: financial-candlestick"
        ).replace("风机 KPI 达成", "我的 K 线微调版")
        composite.user_store.save("financial-candlestick", override)
        composite.reload()

        skill = composite.get("financial-candlestick")
        assert skill.title == "我的 K 线微调版"
        assert composite.is_user_skill("financial-candlestick")
        assert composite.overrides_builtin("financial-candlestick")

        composite.user_store.delete("financial-candlestick")
        composite.reload()
        restored = composite.get("financial-candlestick")
        assert restored.title != "我的 K 线微调版"
        assert not composite.is_user_skill("financial-candlestick")

    def test_builtin_skills_still_selected(self, composite: CompositeSkillRegistry):
        assert composite.get("pareto-quality") is not None
        assert len(composite.skills) >= 5


# ---------- REST API（真实 app 蓝图） ----------


class TestSkillsApi:
    @pytest.fixture
    def client(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import app as app_module

        monkeypatch.setenv("USER_SKILLS_DIR", str(tmp_path / "skills_user_api"))
        monkeypatch.delenv("SERVICE_API_KEY", raising=False)
        # 用户目录经 env 切换，组合注册表是进程单例——清缓存让它按新目录重建
        get_skill_registry.cache_clear()
        yield app_module.app.test_client()
        get_skill_registry.cache_clear()

    def test_list_contains_builtin_skills(self, client):
        resp = client.get("/api/skills")
        assert resp.status_code == 200
        body = resp.get_json()
        names = {item["name"] for item in body["skills"]}
        assert "pareto-quality" in names
        assert all(item["source"] == "builtin" for item in body["skills"])

    def test_post_get_update_delete_roundtrip(self, client):
        resp = client.post(
            "/api/skills",
            data=json.dumps({"name": "wind-turbine-kpi", "content": VALID_SKILL}),
            content_type="application/json",
        )
        assert resp.status_code == 201, resp.get_json()
        assert resp.get_json()["skill"]["name"] == "wind-turbine-kpi"

        # 保存后进程内注册表立即生效：index 里有它
        assert "wind-turbine-kpi" in get_skill_registry().index_text()

        listed = client.get("/api/skills").get_json()
        mine = next(item for item in listed["skills"] if item["name"] == "wind-turbine-kpi")
        assert mine["source"] == "user"
        assert mine["overrides_builtin"] is False

        got = client.get("/api/skills/wind-turbine-kpi")
        assert got.status_code == 200
        assert "min/max 域" in got.get_json()["content"]

        updated = client.put(
            "/api/skills/wind-turbine-kpi",
            data=json.dumps(
                {"content": VALID_SKILL.replace("风机 KPI 达成", "风机 KPI 二版")}
            ),
            content_type="application/json",
        )
        assert updated.status_code == 200
        assert updated.get_json()["existed"] is True

        removed = client.delete("/api/skills/wind-turbine-kpi")
        assert removed.status_code == 200
        assert removed.get_json()["removed"] is True
        assert "wind-turbine-kpi" not in get_skill_registry().index_text()

        assert client.get("/api/skills/wind-turbine-kpi").status_code == 404

    def test_post_invalid_skill_returns_400_with_reason(self, client):
        resp = client.post(
            "/api/skills",
            data=json.dumps({"name": "bad-skill", "content": "没有 frontmatter 的正文"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "frontmatter" in resp.get_json()["detail"]
        # 失败内容不落盘：目录里没有残留
        registry = get_skill_registry()
        assert registry.is_user_skill("bad-skill") is False

    def test_post_missing_fields_returns_400(self, client):
        for payload in ({}, {"name": "x"}, {"content": VALID_SKILL}):
            resp = client.post(
                "/api/skills",
                data=json.dumps(payload),
                content_type="application/json",
            )
            assert resp.status_code == 400

    def test_delete_builtin_rejected_and_missing_404(self, client):
        resp = client.delete("/api/skills/pareto-quality")
        assert resp.status_code == 400
        assert "内置" in resp.get_json()["detail"]

        assert client.delete("/api/skills/never-existed").status_code == 404

    def test_get_builtin_content_for_template(self, client):
        resp = client.get("/api/skills/pareto-quality")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["source"] == "builtin"
        assert body["content"].startswith("---")
