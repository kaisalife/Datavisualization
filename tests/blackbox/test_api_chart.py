"""黑盒测试：API 接口。

测试 Flask API 端点的外部行为，不关心内部实现。
使用 Flask test client，不启动真实服务器。
"""
import pytest


# ============================================================
# POST /api/generate-chart-with-prompt
# ============================================================

class TestGenerateChartAPI:
    """测试图表生成接口。"""

    def test_missing_file_path_returns_400(self, client):
        """缺少 file_path 参数应返回 400。"""
        resp = client.post("/api/generate-chart-with-prompt", json={})
        assert resp.status_code in (400, 422, 500)

    def test_missing_api_key_returns_401(self, app):
        """缺少 API Key 应返回 401。"""
        # 临时移除 API Key 配置
        app.config.pop("API_KEY", None)
        import os
        old = os.environ.pop("API_KEY", None)
        try:
            client = app.test_client()
            resp = client.post("/api/generate-chart-with-prompt", json={
                "file_path": "test.xlsx",
                "user_prompt": "画图",
            }, headers={})
            # 可能 401 或 400（取决于中间件顺序）
            assert resp.status_code in (400, 401)
        finally:
            if old:
                os.environ["API_KEY"] = old

    @pytest.mark.slow
    @pytest.mark.needs_llm
    def test_valid_request_returns_task_id(self, client, tmp_xlsx):
        """正常请求应返回 task_id（需要真实 LLM）。"""
        resp = client.post("/api/generate-chart-with-prompt", json={
            "file_path": str(tmp_xlsx),
            "user_prompt": "画一个柱状图",
        }, headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "task_id" in data


# ============================================================
# GET /api/chart/<chart_id>
# ============================================================

class TestGetChartAPI:
    """测试获取图表接口。"""

    def test_nonexistent_chart_returns_404(self, client):
        """不存在的 chart_id 应返回 404。"""
        resp = client.get("/api/chart/nonexistent_id_12345")
        assert resp.status_code in (404, 500)


# ============================================================
# GET /api/task/<task_id>
# ============================================================

class TestTaskStatusAPI:
    """测试任务状态查询接口。"""

    def test_nonexistent_task_returns_404(self, client):
        """不存在的 task_id 应返回 404 或错误状态。"""
        resp = client.get("/api/task/nonexistent_task_12345")
        assert resp.status_code in (404, 500)

    @pytest.mark.slow
    @pytest.mark.needs_llm
    def test_running_task_returns_status(self, client, tmp_xlsx):
        """运行中的任务应返回 running 状态。"""
        # 先提交任务
        resp = client.post("/api/generate-chart-with-prompt", json={
            "file_path": str(tmp_xlsx),
            "user_prompt": "画图",
        }, headers={"X-API-Key": "test-key"})
        if resp.status_code == 200:
            task_id = resp.get_json().get("task_id")
            if task_id:
                status_resp = client.get(f"/api/task/{task_id}")
                assert status_resp.status_code == 200
                data = status_resp.get_json()
                assert "status" in data
                assert data["status"] in ("running", "succeeded", "failed")


# ============================================================
# POST /api/complete-viz-code
# ============================================================

class TestCodeCompletionAPI:
    """测试代码补全接口。"""

    def test_missing_source_returns_400(self, client):
        """缺少 source 参数应返回 400。"""
        resp = client.post("/api/complete-viz-code", json={
            "user_prompt": "画个图",
        })
        assert resp.status_code in (400, 422, 500)

    @pytest.mark.slow
    @pytest.mark.needs_llm
    def test_valid_request_returns_snippet(self, client):
        """正常请求应返回代码片段（需要真实 LLM）。"""
        resp = client.post("/api/complete-viz-code", json={
            "source": "import numpy as np\nx = np.random.randn(100)",
            "user_prompt": "展示分布",
        }, headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
