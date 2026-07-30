# DataVisualServer 测试标准

本文件定义了项目的测试规范，所有贡献者提交代码前必须确保测试通过。

## 一、测试分层架构

```
┌─────────────────────────────────────────────┐
│  黑盒测试（Black Box）                       │
│  ├── API 接口测试（Flask test client）        │
│  └── 端到端测试（E2E，真实数据 -> HTML 报告） │
├─────────────────────────────────────────────┤
│  集成测试（Integration）                     │
│  ├── Adapter 契约测试（统一接口校验）         │
│  └── 管线集成测试（多模块协作）               │
├─────────────────────────────────────────────┤
│  白盒单元测试（White Box Unit）              │
│  ├── 纯函数测试（utils, constants, schema）  │
│  ├── 沙箱安全测试（AST 扫描 + 执行拦截）     │
│  └── LLM Mock 测试（mock ainvoke）           │
└─────────────────────────────────────────────┘
```

## 二、目录结构

```
tests/                          # 测试根目录
├── conftest.py                 # 全局 fixture（LLM mock、临时目录等）
├── whitebox/                   # 白盒单元测试
│   ├── test_sandbox.py         # 沙箱安全扫描
│   ├── test_utils.py           # JSON 解析、路径处理
│   ├── test_schema.py          # VizDataset / TabularBlock 数据模型
│   ├── test_constants.py       # CSV_ENCODINGS 等常量
│   └── test_chart_generator.py # 图表生成逻辑（mock LLM）
├── integration/                # 集成测试
│   ├── test_adapter_contract.py  # Adapter 契约（从 test_env 迁移）
│   └── test_pipeline.py        # Adapter -> Planner -> Generator 管线
├── blackbox/                   # 黑盒测试
│   ├── test_api_chart.py       # POST /api/generate-chart-with-prompt
│   ├── test_api_task.py        # GET /api/task/<id>
│   └── test_e2e_excel.py       # Excel 上传 -> 图表 HTML 输出
└── fixtures/                   # 测试数据
    ├── sample_data/            # 固定测试数据文件
    └── mock_responses/         # LLM mock 响应
```

## 三、白盒测试标准

### 3.1 命名规范

```python
# 文件名：test_<模块名>.py
# 函数名：test_<被测函数>_<场景>_<预期结果>
def test_extract_json_from_response_valid_json_returns_dict():
    ...
def test_extract_json_from_response_with_markdown_fence_strips_fence():
    ...
def test_sandbox_blocks_os_system_raises_security_error():
    ...
```

### 3.2 必须覆盖的白盒测试点

| 模块 | 测试文件 | 必测场景 |
|------|---------|---------|
| `agent_tools/sandbox.py` | `test_sandbox.py` | AST 扫描拦截危险调用（os.system/subprocess/eval/exec）；安全代码正常执行；超时终止 |
| `service/utils.py` | `test_utils.py` | JSON 提取（正常/markdown围栏/贪婪正则/栈匹配）；路径处理 |
| `service/constants.py` | `test_constants.py` | CSV_ENCODINGS 非空且含 utf-8/gbk |
| `service/viz_data/schema.py` | `test_schema.py` | VizDataset/TabularBlock 字段校验；DataRef 路径解析 |
| `service/chart_generator.py` | `test_chart_generator.py` | mock LLM 返回代码后执行成功；debug 重试逻辑；max_retries 边界 |
| `service/data_preview.py` | `test_data_preview.py` | _run_preview_step 两步流程（mock LLM）；沙箱调用 |
| `RAG/RAG_main.py` | `test_rag.py` | chunk_size 配置；query 构建；检索结果格式 |
| `service/viz_data/adapters/stats_gov_data.py` | `test_stats_gov_data.py` | 每个指标数据非空；年份范围正确；字段完整 |

### 3.3 白盒测试编写规则

1. **禁止真实 LLM 调用**：所有 LLM 交互必须 mock
2. **禁止真实网络请求**：WorldBank API、外部 URL 必须 mock
3. **测试隔离**：每个测试用 fixture 创建临时目录，不依赖共享状态
4. **断言明确**：禁止 `assert True`，必须断言具体值/类型/行为
5. **AAA 结构**：Arrange -> Act -> Assert

```python
# 标准白盒测试模板
def test_sandbox_blocks_subprocess_run():
    """白盒：sandbox AST 扫描应拦截 subprocess.run。"""
    # Arrange
    code = "import subprocess\nsubprocess.run(['ls'])"

    # Act & Assert
    with pytest.raises(SecurityError, match="subprocess"):
        run_python_safely(code, timeout=5)
```

## 四、黑盒测试标准

### 4.1 API 接口测试

| 接口 | 测试文件 | 必测场景 |
|------|---------|---------|
| `POST /api/generate-chart-with-prompt` | `test_api_chart.py` | 正常请求返回 task_id；缺少 file_path 返回 400；API Key 校验 |
| `GET /api/chart/<chart_id>` | `test_api_chart.py` | 存在的 chart_id 返回 HTML；不存在的返回 404 |
| `GET /api/task/<task_id>` | `test_api_task.py` | 任务进行中返回 running；完成后返回 succeeded + results |
| `POST /api/complete-viz-code` | `test_api_code.py` | 正常请求返回 snippet；缺少 source 返回 400 |

### 4.2 端到端测试

| 场景 | 测试文件 | 验证点 |
|------|---------|-------|
| Excel -> 图表 | `test_e2e_excel.py` | 上传 xlsx -> 生成 HTML 文件 -> 文件 > 1KB -> 含 echarts 关键字 |
| CSV -> 图表 | `test_e2e_csv.py` | 同上，CSV 格式 |
| 国家统计局报告 | `test_e2e_china_macro.py` | prompt -> report HTML -> 含免责声明 -> 含图表 |
| 世界银行报告 | `test_e2e_worldbank.py` | prompt -> report HTML -> 含数据来源标注 |

### 4.3 黑盒测试编写规则

1. **使用 Flask test client**：不启动真实服务器
2. **LLM 必须 mock**：E2E 测试中 mock LLM 返回固定代码
3. **验证最终产物**：HTML 文件存在性、大小、关键内容
4. **超时控制**：每个 E2E 测试不超过 60 秒

```python
# 标准黑盒 API 测试模板
def test_generate_chart_returns_task_id(client, mock_llm, tmp_xlsx):
    """黑盒：正常上传 Excel 应返回 task_id。"""
    # Act
    resp = client.post("/api/generate-chart-with-prompt", json={
        "file_path": str(tmp_xlsx),
        "user_prompt": "画一个柱状图",
    })

    # Assert
    assert resp.status_code == 200
    data = resp.get_json()
    assert "task_id" in data
    assert data["task_id"]  # 非空
```

## 五、Mock 策略

### 5.1 LLM Mock

```python
# conftest.py 中的全局 fixture
@pytest.fixture
def mock_llm():
    """返回 mock 的 LLM 客户端，ainvoke 返回固定代码。"""
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=SimpleNamespace(
        content='''```python
import pandas as pd
from pyecharts.charts import Bar
df = pd.read_csv("data.csv")
bar = Bar()
bar.add_xaxis(df["month"].tolist())
bar.add_yaxis("sales", df["sales"].tolist())
bar.render("output.html")
```'''
    ))
    return llm
```

### 5.2 网络 Mock

```python
@pytest.fixture
def mock_worldbank_api(monkeypatch):
    """mock 世界银行 API 返回固定 JSON。"""
    async def _fake_fetch(self, **kwargs):
        return VizDataset(name="GDP", ...)
    monkeypatch.setattr(WorldBankAdapter, "fetch", _fake_fetch)
```

### 5.3 沙箱 Mock

```python
@pytest.fixture
def mock_sandbox(monkeypatch):
    """mock 沙箱执行，直接返回成功。"""
    monkeypatch.setattr("service.chart_generator.run_python_safely",
                        lambda code, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
```

## 六、测试运行

### 6.1 运行命令

```bash
# 运行全部测试
python -m pytest tests/ -v

# 只运行白盒测试
python -m pytest tests/whitebox/ -v

# 只运行黑盒测试
python -m pytest tests/blackbox/ -v

# 运行单个文件
python -m pytest tests/whitebox/test_sandbox.py -v

# 生成覆盖率报告
python -m pytest tests/ --cov=service --cov=agent_tools --cov-report=term-missing
```

### 6.2 提交前检查清单

```bash
# 提交前必须全部通过
python -m pytest tests/whitebox/ -v          # 白盒全过
python -m pytest tests/blackbox/ -v          # 黑盒全过
python -m pytest tests/integration/ -v       # 集成全过
python -m py_compile $(git diff --name-only --cached | grep '\.py$')  # 语法检查
```

## 七、覆盖率要求

| 模块 | 最低覆盖率 | 说明 |
|------|-----------|------|
| `agent_tools/sandbox.py` | 90% | 安全核心，必须高覆盖 |
| `service/utils.py` | 85% | 工具函数 |
| `service/viz_data/schema.py` | 85% | 数据模型 |
| `service/viz_data/adapters/` | 75% | 每个 Adapter 至少有契约测试 |
| `service/chart_generator.py` | 70% | LLM 部分可 mock |
| `service/report_pipeline.py` | 60% | E2E 覆盖主流程 |
| `api/` | 80% | 接口层 |
| **整体** | **70%** | 不含 RAG 知识库数据 |

## 八、测试标记（Markers）

```python
# pytest.ini 中注册
# [pytest]
# markers =
#     whitebox: 白盒单元测试
#     blackbox: 黑盒接口/E2E测试
#     integration: 集成测试
#     slow: 耗时超过 10 秒的测试
#     needs_llm: 需要真实 LLM（默认 skip）

@pytest.mark.whitebox
def test_sandbox_blocks_os_system():
    ...

@pytest.mark.blackbox
@pytest.mark.slow
def test_e2e_excel_to_chart():
    ...
```

运行指定标记：
```bash
python -m pytest -m whitebox          # 只跑白盒
python -m pytest -m "not slow"        # 跳过慢测试
python -m pytest -m "not needs_llm"   # 跳过需要真实 LLM 的测试
```
