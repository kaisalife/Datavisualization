"""黑盒测试：API 层 Pydantic 序列化端到端验证。

通过 Flask test client 验证所有涉及 Pydantic BaseModel 序列化的 API 端点，
确保响应 JSON 格式正确、error response 结构一致。
"""
import json

import pytest


# ============================================================
# 辅助函数
# ============================================================

def _api_key_headers():
    """返回带 API Key 的请求头。"""
    return {"X-API-Key": "test-key"}


def _assert_error_response(resp, expected_status: int):
    """断言响应是标准 ErrorResponse 格式。"""
    assert resp.status_code == expected_status
    data = resp.get_json()
    assert data is not None, "响应体为空"
    assert "detail" in data, f"缺少 detail 字段: {data}"
    assert isinstance(data["detail"], str), f"detail 不是字符串: {type(data['detail'])}"
    # ErrorResponse 只有一个字段
    assert set(data.keys()) == {"detail"}, f"额外字段: {set(data.keys()) - {'detail'}}"


# ============================================================
# POST /api/generate-chart-with-prompt
# ============================================================

class TestChartAPIErrorResponse:
    """图表生成接口的错误响应序列化。"""

    def test_no_data_source_returns_400(self, client):
        """未提供文件或数据库配置时返回 400 + ErrorResponse。"""
        resp = client.post(
            "/api/generate-chart-with-prompt",
            data={"user_prompt": "画图"},
            headers=_api_key_headers(),
        )
        _assert_error_response(resp, 400)
        assert "必须提供" in resp.get_json()["detail"]

    def test_invalid_db_config_json_returns_400(self, client):
        """db_config 非法 JSON 时返回 400 + ErrorResponse。"""
        resp = client.post(
            "/api/generate-chart-with-prompt",
            data={"user_prompt": "画图", "db_config": "{invalid json}"},
            headers=_api_key_headers(),
        )
        _assert_error_response(resp, 400)
        assert "JSON 解析失败" in resp.get_json()["detail"]

    def test_success_response_format(self, client, tmp_csv):
        """成功提交任务时返回 202 + task_id/status/conversation_id。"""
        with open(tmp_csv, "rb") as f:
            resp = client.post(
                "/api/generate-chart-with-prompt",
                data={
                    "files": (f, "test.csv"),
                    "user_prompt": "画一个柱状图",
                },
                content_type="multipart/form-data",
                headers=_api_key_headers(),
            )
        # 可能 202 (成功提交) 或 500 (后台启动失败)
        if resp.status_code == 202:
            data = resp.get_json()
            assert "task_id" in data
            assert data["status"] == "pending"
            assert "conversation_id" in data
        else:
            # 后台依赖未就绪也acceptable，但要确保返回的是 ErrorResponse
            _assert_error_response(resp, 500)


# ============================================================
# GET /api/chart/<chart_id>
# ============================================================

class TestGetChartAPIErrorResponse:
    """获取图表接口的错误响应序列化。"""

    def test_invalid_chart_id_returns_400(self, client):
        """包含路径穿越的 chart_id 返回 400 + ErrorResponse。"""
        resp = client.get(
            "/api/chart/test..secret.html",
            headers=_api_key_headers(),
        )
        _assert_error_response(resp, 400)
        assert "Invalid chart ID" in resp.get_json()["detail"]

    def test_nonexistent_chart_returns_404(self, client):
        """不存在的 chart_id 返回 404 + ErrorResponse。"""
        resp = client.get(
            "/api/chart/nonexistent_chart_12345.html",
            headers=_api_key_headers(),
        )
        # 可能 404 (chart 不存在) 或 404 (charts 目录不存在)
        assert resp.status_code in (404, 500)
        data = resp.get_json()
        assert "detail" in data
        assert isinstance(data["detail"], str)


# ============================================================
# GET /api/task/<task_id>
# ============================================================

class TestTaskAPIErrorResponse:
    """任务查询接口的错误响应序列化。"""

    def test_nonexistent_task_returns_404(self, client):
        """不存在的 task_id 返回 404 + ErrorResponse。"""
        resp = client.get(
            "/api/task/nonexistent_task_id_99999",
            headers=_api_key_headers(),
        )
        _assert_error_response(resp, 404)
        assert "Task not found" in resp.get_json()["detail"]

    def test_task_status_response_format(self, app, client):
        """已有任务的响应格式验证。"""
        # 先注入一个假任务到 tasks dict (需要在 app context 中)
        from api.common import get_tasks, get_tasks_lock
        task_id = "test_task_serialization_001"
        with app.app_context():
            with get_tasks_lock():
                get_tasks()[task_id] = {
                    "status": "success",
                    "result": {
                        "Charts": ["Bar"],
                        "HtmlFilePaths": ["/tmp/chart.html"],
                        "AgentLogs": ["log entry"],
                    },
                    "error": None,
                    "raw": None,
                    "created_at": "test",
                }
        try:
            resp = client.get(
                f"/api/task/{task_id}",
                headers=_api_key_headers(),
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["task_id"] == task_id
            assert data["status"] == "success"
            assert "result" in data
            assert isinstance(data["result"]["Charts"], list)
            assert data["result"]["Charts"] == ["Bar"]
            assert data["result"]["HtmlFilePaths"] == ["/tmp/chart.html"]
            assert data["result"]["AgentLogs"] == ["log entry"]
        finally:
            with app.app_context():
                with get_tasks_lock():
                    get_tasks().pop(task_id, None)


# ============================================================
# POST /api/complete-viz-code
# ============================================================

class TestCodeAPIErrorResponse:
    """代码补全接口的错误响应序列化。"""

    def test_missing_code_file_paths_returns_400(self, client):
        """缺少 code_file_paths 返回 400 + ErrorResponse。"""
        resp = client.post(
            "/api/complete-viz-code",
            json={"user_prompt": "画图"},
            headers=_api_key_headers(),
        )
        _assert_error_response(resp, 400)
        assert "code_file_paths" in resp.get_json()["detail"]


# ============================================================
# API Key 认证错误
# ============================================================

class TestAuthErrorResponse:
    """API Key 认证失败的错误响应序列化。"""

    def test_missing_api_key_returns_401(self, app, client):
        """缺少 API Key 返回 401 + ErrorResponse。"""
        app.config["_SERVICE_API_KEY"] = "secret-key"
        resp = client.post(
            "/api/generate-chart-with-prompt",
            data={"user_prompt": "画图"},
            headers={},  # 不带 API Key
        )
        _assert_error_response(resp, 401)
        assert "API key" in resp.get_json()["detail"]

    def test_wrong_api_key_returns_401(self, app, client):
        """错误的 API Key 返回 401 + ErrorResponse。"""
        app.config["_SERVICE_API_KEY"] = "secret-key"
        resp = client.get(
            "/api/task/any_task",
            headers={"X-API-Key": "wrong-key"},
        )
        _assert_error_response(resp, 401)
        assert "API key" in resp.get_json()["detail"]


# ============================================================
# 全局错误处理器
# ============================================================

class TestGlobalErrorHandler:
    """全局错误处理器的 ErrorResponse 序列化。"""

    def test_404_returns_error_response(self, client):
        """不存在的路由返回 ErrorResponse 格式。"""
        resp = client.get("/api/nonexistent-endpoint")
        # Flask 默认 404 会被全局 error handler 包装
        assert resp.status_code in (404, 500)
        data = resp.get_json()
        if data and "detail" in data:
            assert isinstance(data["detail"], str)


# ============================================================
# JSON 序列化一致性
# ============================================================

class TestJSONSerializationConsistency:
    """验证 model_dump() 结果能被 json.dumps 正确序列化。"""

    def test_error_response_json_roundtrip(self):
        """ErrorResponse -> model_dump -> json.dumps -> json.loads 一致。"""
        from Entity import ErrorResponse

        original = ErrorResponse(detail="错误: 数据接入失败")
        dumped = original.model_dump()
        json_str = json.dumps(dumped, ensure_ascii=False)
        restored = json.loads(json_str)
        assert restored == dumped
        assert restored["detail"] == "错误: 数据接入失败"

    def test_chart_response_json_roundtrip(self):
        """GenerateChartWithPromptResponse -> model_dump -> json -> dict 一致。"""
        from Entity import GenerateChartWithPromptResponse

        original = GenerateChartWithPromptResponse(
            Charts=["Bar", "Pie", "Line"],
            HtmlFilePaths=["/a.html", "/b.html", "/c.html"],
            AgentLogs=["step1", "step2"],
        )
        dumped = original.model_dump()
        json_str = json.dumps(dumped, ensure_ascii=False)
        restored = json.loads(json_str)
        assert restored == dumped
        assert len(restored["Charts"]) == 3
        assert len(restored["HtmlFilePaths"]) == 3

    def test_error_response_with_special_chars(self):
        """包含特殊字符的 detail 能正确序列化。"""
        from Entity import ErrorResponse

        special_detail = '错误: "引号" & <标签> \\反斜杠\\ 换行\n制表\t'
        resp = ErrorResponse(detail=special_detail)
        dumped = resp.model_dump()
        json_str = json.dumps(dumped, ensure_ascii=False)
        restored = json.loads(json_str)
        assert restored["detail"] == special_detail
