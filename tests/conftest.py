"""全局测试 fixture。

提供所有测试共用的基础设施：
- mock_llm：模拟 LLM 客户端（避免真实调用）
- client：Flask 测试客户端
- tmp_xlsx / tmp_csv：临时数据文件
- tmp_dir：隔离的临时目录
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

# 确保项目根目录在 sys.path 中
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ============================================================
# LLM Mock
# ============================================================

@pytest.fixture
def mock_llm():
    """模拟 LLM 客户端，ainvoke 返回固定 pyecharts 代码。"""
    llm = AsyncMock()
    llm.model = "mock-model"
    llm.ainvoke = AsyncMock(return_value=SimpleNamespace(
        content="""```python
import pandas as pd
from pyecharts.charts import Bar
from pyecharts import options as opts

df = pd.read_csv("data.csv")
bar = Bar()
bar.add_xaxis(df["month"].tolist())
bar.add_yaxis("销售额", df["sales"].tolist())
bar.set_global_opts(title_opts=opts.TitleOpts(title="测试图表"))
bar.render()
```"""
    ))
    return llm


@pytest.fixture
def mock_llm_json():
    """模拟 LLM 返回 JSON（用于 planner）。"""
    llm = AsyncMock()
    llm.model = "mock-model"
    llm.ainvoke = AsyncMock(return_value=SimpleNamespace(
        content='''```json
{
  "plans": [{
    "plan_id": "1",
    "plan_name": "测试计划",
    "plan_description": "柱状图",
    "data_file_path": "data.csv",
    "chart_type": "Bar",
    "chart_title": "销售额",
    "chart_reason": "适合对比",
    "use_column_names": true,
    "execution_order": 1,
    "data_interface": {"available": false},
    "overall_analysis": "测试分析"
  }]
}
```'''
    ))
    return llm


# ============================================================
# Flask 测试客户端
# ============================================================

@pytest.fixture
def app():
    """Flask 应用实例（测试模式）。"""
    import os
    os.environ.setdefault("API_KEY", "test-key")
    os.environ.setdefault("FLASK_TESTING", "1")

    from app import app as flask_app
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    """Flask 测试客户端。"""
    return app.test_client()


# ============================================================
# 临时数据文件
# ============================================================

@pytest.fixture
def tmp_xlsx(tmp_path):
    """生成临时 Excel 文件（3 行 2 列）。"""
    df = pd.DataFrame({
        "month": ["1月", "2月", "3月"],
        "sales": [100, 200, 150],
    })
    path = tmp_path / "test_data.xlsx"
    df.to_excel(path, index=False, engine="openpyxl")
    return path


@pytest.fixture
def tmp_csv(tmp_path):
    """生成临时 CSV 文件（5 行 3 列）。"""
    df = pd.DataFrame({
        "month": ["1月", "2月", "3月", "4月", "5月"],
        "sales": [100, 200, 150, 300, 250],
        "profit": [10, 20, 15, 30, 25],
    })
    path = tmp_path / "test_data.csv"
    df.to_csv(path, index=False, encoding="utf-8")
    return path


@pytest.fixture
def tmp_csv_gbk(tmp_path):
    """生成 GBK 编码的 CSV 文件（测试编码兼容性）。"""
    df = pd.DataFrame({
        "月份": ["1月", "2月", "3月"],
        "销售额": [100, 200, 150],
    })
    path = tmp_path / "gbk_data.csv"
    df.to_csv(path, index=False, encoding="gbk")
    return path


# ============================================================
# 临时目录
# ============================================================

@pytest.fixture
def tmp_charts_dir(tmp_path, monkeypatch):
    """隔离的 charts 输出目录。"""
    charts_dir = tmp_path / "charts"
    charts_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    return charts_dir


# ============================================================
# 沙箱 Mock
# ============================================================

@pytest.fixture
def mock_sandbox_success(monkeypatch):
    """mock 沙箱执行，直接返回成功。"""
    def _fake_run(code, **kwargs):
        return SimpleNamespace(returncode=0, stdout="OK", stderr="")
    monkeypatch.setattr(
        "agent_tools.sandbox.run_python_safely",
        _fake_run,
    )
    return _fake_run
