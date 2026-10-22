"""单图二次优化：资产登记 / 优化器 / API 早失败路径（无需 LLM）。

- chart_assets：登记、反查、版本号、路径穿越防护；
- chart_optimizer：设计消息 / 读取片段合成 / 优化主循环（沙箱与 agent 打桩）；
- optimize-chart API：参数与资产早失败校验（不进 executor）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.runtime.chart_assets import (
    ASSETS_FILENAME,
    find_asset_by_chart_id,
    load_assets,
    next_optimize_version,
    record_chart,
)

pytestmark = pytest.mark.whitebox


PLAN = {
    "plan_id": "p1",
    "plan_name": "销售额趋势",
    "chart_type": "Line",
    "series_id": "销售明细.月度销售额",
}


@pytest.fixture
def output_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    (folder / "charts").mkdir(parents=True)
    (folder / "code").mkdir()
    (folder / "plans").mkdir()
    return folder


def _make_chart(output_folder: Path, name: str = "chart_p1_20260101_000000.html") -> Path:
    p = output_folder / "charts" / name
    p.write_text("<html><body>echarts</body></html>", encoding="utf-8")
    return p


class TestChartAssets:
    def test_record_and_load(self, output_folder):
        chart = _make_chart(output_folder)
        rec = record_chart(
            output_folder, task_id="t1", plan=PLAN,
            chart_path=str(chart), code_path="c.py", data_path="d.parquet",
        )

        assert rec is not None and rec["chart_id"] == chart.name
        assets = load_assets(output_folder)
        assert len(assets) == 1
        assert assets[0]["plan_id"] == "p1"
        assert assets[0]["chart_type"] == "Line"
        assert assets[0]["version"] == 0

    def test_record_appends(self, output_folder):
        c1 = _make_chart(output_folder, "chart_p1_a.html")
        c2 = _make_chart(output_folder, "chart_p2_b.html")
        record_chart(output_folder, plan=PLAN, chart_path=str(c1))
        record_chart(output_folder, plan=PLAN, chart_path=str(c2))

        assert len(load_assets(output_folder)) == 2

    def test_find_by_chart_id(self, output_folder, tmp_path):
        chart = _make_chart(output_folder)
        record_chart(output_folder, plan=PLAN, chart_path=str(chart))

        root = tmp_path  # charts 根目录 = output_folder 的上级
        found = find_asset_by_chart_id(chart.name, charts_root=root)
        assert found is not None
        assert found["chart_id"] == chart.name
        assert found["output_folder"] == str(output_folder)

    def test_find_ignores_missing_chart_file(self, output_folder, tmp_path):
        chart = _make_chart(output_folder)
        record_chart(output_folder, plan=PLAN, chart_path=str(chart))
        chart.unlink()

        assert find_asset_by_chart_id(chart.name, charts_root=tmp_path) is None

    def test_find_rejects_traversal(self, output_folder):
        assert find_asset_by_chart_id("../x.html", charts_root=output_folder) is None
        assert find_asset_by_chart_id("a\\b.html", charts_root=output_folder) is None
        assert find_asset_by_chart_id("", charts_root=output_folder) is None

    def test_next_optimize_version(self, output_folder):
        c1 = _make_chart(output_folder, "chart_p1_a.html")
        c2 = _make_chart(output_folder, "chart_p1_opt1_x.html")
        record_chart(output_folder, plan=PLAN, chart_path=str(c1))
        record_chart(
            output_folder, plan={**PLAN, "plan_id": "p1_opt1"},
            chart_path=str(c2), origin_chart_id="chart_p1_a.html", version=1,
        )

        assert next_optimize_version(load_assets(output_folder), "chart_p1_a.html") == 2
        assert next_optimize_version(load_assets(output_folder), "不存在.html") == 1

    def test_corrupted_assets_file_returns_empty(self, output_folder):
        (output_folder / ASSETS_FILENAME).write_text("not json", encoding="utf-8")

        assert load_assets(output_folder) == []


class TestOptimizerUnits:
    def test_read_code_uses_absolute_fallback(self, tmp_path):
        from service.pipeline.chart_optimizer import _read_code_from_data_path

        data_path = tmp_path / "销售明细.月度销售额.parquet"
        read_code = _read_code_from_data_path(str(data_path))

        assert "df = _pd.read_parquet" in read_code
        assert str(data_path) in read_code  # 绝对路径兜底（产物可拷走独立运行）

    def test_read_code_empty_for_no_data(self):
        from service.pipeline.chart_optimizer import _read_code_from_data_path

        assert _read_code_from_data_path("") == ""

    def test_build_message_sections(self):
        from service.pipeline.chart_optimizer import _build_optimize_message

        msg = _build_optimize_message(
            user_prompt="标题改成X",
            original_code="chart.set_global_opts()",
            chart_id="chart_p1.html",
            plan_details='{"plan_id": "p1"}',
            dataset_summary='{"rows": 12}',
            series_hint="禁止 read_parquet",
            reference_docs="",
        )

        assert "标题改成X" in msg
        assert "chart.set_global_opts()" in msg
        assert "chart_p1.html" in msg
        assert "read_parquet" in msg
        assert "上一轮失败" not in msg  # 无错误时不带错误段

    def test_build_message_error_section(self):
        from service.pipeline.chart_optimizer import _build_optimize_message

        msg = _build_optimize_message(
            user_prompt="x", original_code="c", chart_id="a",
            plan_details="", dataset_summary="", series_hint="",
            reference_docs="", error="NameError: y",
        )

        assert "NameError: y" in msg


class TestOptimizeSingleChart:
    @pytest.fixture
    def data_file(self, tmp_path: Path) -> Path:
        import pandas as pd

        p = tmp_path / "data.parquet"
        pd.DataFrame({"月份": [f"{i}月" for i in range(1, 13)], "销售额": range(12)}).to_parquet(p)
        return p

    @pytest.fixture
    def plan_file(self, output_folder: Path) -> dict:
        plan = dict(PLAN)
        (output_folder / "plans" / "plan_p1.json").write_text(
            json.dumps(plan, ensure_ascii=False), encoding="utf-8"
        )
        return plan

    @pytest.fixture
    def original_code(self, output_folder: Path):
        code_file = output_folder / "code" / "code_p1_success.py"
        code_file.write_text("print('original')", encoding="utf-8")
        return code_file

    def _patch_pipeline(self, monkeypatch, output_folder: Path, ok: bool):
        """打桩 agent 循环与沙箱执行（写一个含 echarts 的 HTML 产物）。"""
        import service.pipeline.chart_optimizer as opt

        calls = {"attempts": 0, "errors": []}

        async def fake_debug_with_agent(chat, *, tools, message, max_rounds=5):
            calls["attempts"] += 1
            if message and "NameError" in message:
                calls["errors"].append(True)
            return "chart.render('x.html')", []

        def fake_exec(code_body, *, charts_folder, plan_id, timeout=60):
            if ok:
                plan_html = charts_folder / f"chart_{plan_id}_t.html"
                plan_html.write_text("<html>echarts</html>", encoding="utf-8")
                return opt.SandboxResult(
                    success=True, output="", chart_path=str(plan_html),
                    chart_filename=plan_html.name,
                )
            return opt.SandboxResult(
                success=False, output="NameError: boom", chart_path="",
                chart_filename="x.html",
            )

        monkeypatch.setattr(opt, "debug_with_agent", fake_debug_with_agent)
        monkeypatch.setattr(opt, "execute_chart_code", fake_exec)
        monkeypatch.setattr(opt, "_build_tools", lambda folder, data_path: [])
        return calls

    @pytest.mark.asyncio
    async def test_success_creates_new_version_and_keeps_original(
        self, monkeypatch, output_folder, data_file, plan_file, original_code
    ):
        from service.pipeline.chart_optimizer import optimize_single_chart

        self._patch_pipeline(monkeypatch, output_folder, ok=True)
        ok, chart_path, code, new_plan_id, err = await optimize_single_chart(
            None, user_prompt="改标题", plan=dict(plan_file),
            original_code=original_code.read_text(encoding="utf-8"),
            chart_id="chart_p1.html",
            data_path=str(data_file), output_folder=output_folder,
        )

        assert ok and err == ""
        assert new_plan_id == "p1_opt1"  # 命名版本化
        assert Path(chart_path).is_file()
        # 原 success 代码不被覆盖（另有文件）
        orig_file = output_folder / "code" / "code_p1_success.py"
        assert orig_file.read_text(encoding="utf-8") == "print('original')"
        assert (output_folder / "code" / "code_p1_opt1_success.py").is_file()

    @pytest.mark.asyncio
    async def test_failure_retries_with_error_feedback(
        self, monkeypatch, output_folder, data_file, plan_file
    ):
        from service.pipeline.chart_optimizer import optimize_single_chart

        # 第一轮 NameError（可修复）→ 第二轮仍失败 → 走满 2 次 max_attempts
        import service.pipeline.chart_optimizer as opt
        self._patch_pipeline(monkeypatch, output_folder, ok=False)
        monkeypatch.setattr(opt, "OPTIMIZE_MAX_ATTEMPTS", 2)

        ok, chart_path, code, new_plan_id, err = await optimize_single_chart(
            None, user_prompt="改标题", plan=dict(plan_file),
            original_code="c", chart_id="chart_p1.html",
            data_path=str(data_file), output_folder=output_folder,
            max_attempts=2,
        )

        assert not ok and "NameError" in err
        assert (output_folder / "code" / "code_p1_opt2_failed.py").is_file()

    @pytest.mark.asyncio
    async def test_static_safety_rejection_stops_early(
        self, monkeypatch, output_folder, data_file, plan_file
    ):
        """安全检查拒绝（不可修复）应直接终止，不再重试。"""
        import service.pipeline.chart_optimizer as opt
        from service.pipeline.chart_optimizer import optimize_single_chart

        def fake_exec(code_body, *, charts_folder, plan_id, timeout=60):
            return opt.SandboxResult(
                success=False, output="安全检查失败: 禁止 os.system", chart_path="",
                chart_filename="x.html",
            )

        async def fake_debug(chat, *, tools, message, max_rounds=5):
            return "os.system('x')", []

        monkeypatch.setattr(opt, "debug_with_agent", fake_debug)
        monkeypatch.setattr(opt, "execute_chart_code", fake_exec)
        monkeypatch.setattr(opt, "_build_tools", lambda folder, data_path: [])

        ok, _, _, _, err = await optimize_single_chart(
            None, user_prompt="x", plan=dict(plan_file), original_code="c",
            chart_id="a", data_path=str(data_file), output_folder=output_folder,
            max_attempts=3,
        )

        assert not ok
        assert "安全检查失败" in err
        # 只写过一轮的 failed 代码
        assert len(list((output_folder / "code").glob("code_p1_opt*"))) == 1


class TestOptimizeChartApiRoutes:
    @pytest.fixture
    def client(self):
        import app as app_module

        return app_module.app.test_client()

    @pytest.fixture(autouse=True)
    def _stub_conversation(self, monkeypatch):
        """不落真实对话库（route 处 create_conversation 是模块级绑定）。"""
        import api.chart_api as chart_api

        monkeypatch.setattr(chart_api, "create_conversation", lambda **kw: "conv_test")

    def test_requires_chart_id(self, client):
        resp = client.post("/api/optimize-chart", data={"user_prompt": "改标题"})

        assert resp.status_code == 400

    def test_rejects_traversal_chart_id(self, client):
        resp = client.post(
            "/api/optimize-chart",
            data={"chart_id": "../evil.html", "user_prompt": "x"},
        )

        assert resp.status_code == 400

    def test_unknown_chart_404(self, client, monkeypatch):
        # route 内是局部 import，打桩到源头模块
        import service.runtime.chart_assets as assets

        monkeypatch.setattr(assets, "find_asset_by_chart_id", lambda *_a, **_k: None)
        resp = client.post(
            "/api/optimize-chart",
            data={"chart_id": "chart_no.html", "user_prompt": "x"},
        )

        assert resp.status_code == 404

    def test_valid_asset_returns_202(self, client, monkeypatch, output_folder):
        """资产存在即建任务（executor 打桩，只验证 API 层契约）。"""
        import api.chart_api as chart_api
        import service.runtime.chart_assets as assets

        asset = {
            "chart_id": "chart_p1.html",
            "output_folder": str(output_folder),
            "plan_id": "p1",
            "plan_name": "趋势",
            "chart_type": "Line",
            "data_path": "x.parquet",
            "version": 0,
        }
        monkeypatch.setattr(assets, "find_asset_by_chart_id", lambda *_a, **_k: asset)
        submitted = {}
        # route 用的 _run_optimize_in_executor 是 chart_api 模块级绑定
        monkeypatch.setattr(
            chart_api, "_run_optimize_in_executor",
            lambda *a, **k: submitted.update(task=a[1], model=a[2]),
        )

        resp = client.post(
            "/api/optimize-chart",
            data={"chart_id": "chart_p1.html", "user_prompt": "只显示 Top5"},
        )

        assert resp.status_code == 202
        body = resp.get_json()
        assert body["status"] == "pending"
        assert body["task_id"] == submitted["task"]
        assert submitted["model"].chart_id == "chart_p1.html"
        assert submitted["model"].user_prompt == "只显示 Top5"


class TestTaskAssetsApi:
    @pytest.fixture
    def client(self):
        import app as app_module

        return app_module.app.test_client()

    def _set_task(self, monkeypatch, tasks: dict):
        import api.chart_api as chart_api

        lock = __import__("threading").Lock()
        monkeypatch.setattr(chart_api, "get_tasks", lambda: tasks)
        monkeypatch.setattr(chart_api, "get_tasks_lock", lambda: lock)

    def test_unknown_task_404(self, client, monkeypatch):
        self._set_task(monkeypatch, {})
        resp = client.get("/api/task-assets/nope")

        assert resp.status_code == 404

    def test_cards_from_registry(self, client, monkeypatch, output_folder):
        chart = _make_chart(output_folder, "chart_p1_a.html")
        record_chart(
            output_folder, task_id="task1", plan=PLAN, chart_path=str(chart),
            origin_chart_id="", version=0,
        )

        # find_task_assets 在函数内从 constants 导入 get_charts_dir
        import service.runtime.constants as constants

        monkeypatch.setattr(constants, "get_charts_dir", lambda: output_folder.parent)
        self._set_task(monkeypatch, {"task1": {"status": "success", "raw": {}}})
        resp = client.get("/api/task-assets/task1")

        assert resp.status_code == 200
        cards = resp.get_json()["assets"]
        assert len(cards) == 1
        assert cards[0]["chart_id"] == "chart_p1_a.html"
        assert cards[0]["chart_type"] == "Line"
        assert "output_folder" not in cards[0]  # 不暴露路径细节

    def test_fallback_from_raw_success(self, client, monkeypatch):
        old = {
            "task2": {
                "status": "success",
                "raw": {"successful_charts": [{
                    "plan": {"plan_id": "p9", "plan_name": "旧图",
                             "chart_title": "月度销售额", "chart_type": "Bar"},
                    "chart_path": "C:\\x\\chart_p9_1.html",
                }], "failed_plans": []},
            },
        }
        self._set_task(monkeypatch, old)

        resp = client.get("/api/task-assets/task2")

        assert resp.status_code == 200
        cards = resp.get_json()["assets"]
        assert cards[0]["chart_id"] == "chart_p9_1.html"
        assert cards[0]["title"] == "月度销售额"
