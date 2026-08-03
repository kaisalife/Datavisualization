"""白盒测试：清洗管道。

测试 service/viz_data/cleaning/pipeline.py 的：
- extract_yaml_from_response(): 从 LLM 响应提取 YAML
- extract_json_from_response(): 从 LLM 响应提取 JSON
- CleaningPipeline: 完整流程（Mock QueryEngine 模拟 LLM）
  - 单数据源清洗成功
  - 干净数据跳过（由 adapter._try_clean 控制，pipeline 聚焦清洗本身）
  - 3 次循环失败后 fallback
  - 多源 Join 检测
"""
from __future__ import annotations

import json
import re
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from service.viz_data.cleaning.pipeline import (
    CleaningPipeline,
    extract_json_from_response,
    extract_yaml_from_response,
)
from service.viz_data.cleaning.preview import (
    DataQualityChecker,
    generate_preview,
)
from service.viz_data.schema import RawDataBundle


# ============================================================
# extract_yaml_from_response
# ============================================================

class TestExtractYaml:
    """测试从 LLM 响应中提取 YAML。"""

    def test_yaml_code_block(self):
        """```yaml ... ``` 代码块。"""
        text = "这是规则：\n```yaml\nnodes:\n  step1:\n    operator: Dedup\n```\n完成"
        result = extract_yaml_from_response(text)
        assert "nodes:" in result
        assert "Dedup" in result

    def test_yml_code_block(self):
        """```yml ... ``` 代码块。"""
        text = "```yml\nnodes:\n  step1:\n    operator: Dedup\n```"
        result = extract_yaml_from_response(text)
        assert "nodes:" in result

    def test_plain_code_block(self):
        """```...``` 代码块（无语言标记）。"""
        text = "```\nnodes:\n  step1:\n    operator: Dedup\n```"
        result = extract_yaml_from_response(text)
        assert "nodes:" in result

    def test_raw_yaml(self):
        """直接 YAML 文本。"""
        text = "nodes:\n  step1:\n    operator: Dedup"
        result = extract_yaml_from_response(text)
        assert "nodes:" in result

    def test_empty_response(self):
        """空响应返回空字符串。"""
        result = extract_yaml_from_response("")
        assert result == ""


# ============================================================
# extract_json_from_response
# ============================================================

class TestExtractJson:
    """测试从 LLM 响应中提取 JSON。"""

    def test_valid_json(self):
        """有效的 JSON 对象。"""
        text = '结果：{"pass": true, "reason": "OK"}'
        result = extract_json_from_response(text)
        assert result["pass"] is True
        assert result["reason"] == "OK"

    def test_nested_json(self):
        """嵌套 JSON。"""
        text = '{"pass": true, "data": {"score": 95}}'
        result = extract_json_from_response(text)
        assert result["pass"] is True
        assert result["data"]["score"] == 95

    def test_invalid_json(self):
        """无效 JSON 返回默认失败结果。"""
        text = "这不是JSON"
        result = extract_json_from_response(text)
        assert result["pass"] is False
        assert "无法解析" in result["reason"]

    def test_json_with_code_fence(self):
        """带代码围栏的 JSON。"""
        text = '```json\n{"pass": false, "reason": "bad"}\n```'
        result = extract_json_from_response(text)
        assert result["pass"] is False

    def test_empty_text(self):
        """空文本返回默认失败结果。"""
        result = extract_json_from_response("")
        assert result["pass"] is False


# ============================================================
# Mock QueryEngine
# ============================================================

class MockQueryEngine:
    """模拟 QueryEngine，根据 prompt 内容返回预定义响应。

    - 生成规则请求 -> 返回 YAML
    - 验证请求 -> 返回 pass=true/false
    - Join 检测请求 -> 返回 need_join=true/false
    """

    def __init__(self, yaml_response: str, validation_pass: bool = True,
                 need_join: bool = False, join_config: dict | None = None):
        self.yaml_response = yaml_response
        self.validation_pass = validation_pass
        self.need_join = need_join
        self.join_config = join_config or {}
        self.call_count = 0

    async def run_prompt(self, prompt, **kwargs) -> str:
        self.call_count += 1
        prompt_text = str(prompt)

        # 验证请求
        if "判断以下清洗后的数据能否归一化" in prompt_text:
            return json.dumps({
                "pass": self.validation_pass,
                "reason": "验证通过" if self.validation_pass else "验证失败",
                "suggestions": [],
            }, ensure_ascii=False)

        # Join 检测
        if "判断以下多个数据源是否需要关联" in prompt_text:
            return json.dumps({
                "need_join": self.need_join,
                **self.join_config,
            }, ensure_ascii=False)

        # 生成/优化规则
        return f"```yaml\n{self.yaml_response}\n```"


# ============================================================
# 测试 fixture
# ============================================================

@pytest.fixture
def dirty_df():
    """脏数据：重复行 + 空值。"""
    return pd.DataFrame({
        "id": [1, 1, 2, 3, None],
        "name": ["Alice", "Alice", "Bob", None, "Eve"],
        "amount": [100, 100, 200, 300, None],
    })


@pytest.fixture
def parquet_file(tmp_path, dirty_df):
    """生成 parquet 临时文件。"""
    path = tmp_path / "test_data.parquet"
    # object 列转字符串避免 pyarrow 序列化问题
    for col in dirty_df.columns:
        if dirty_df[col].dtype == "object":
            dirty_df[col] = dirty_df[col].astype(str)
    dirty_df.to_parquet(path, index=False, engine="pyarrow")
    return path


@pytest.fixture
def raw_bundle(tmp_path, parquet_file):
    """构造 RawDataBundle。"""
    return RawDataBundle(
        source_kind="file",
        source_meta={"original_source": "test.csv"},
        tabular_files=[{
            "name": "test_data",
            "path": str(parquet_file),
            "row_count": 5,
            "original_source": "test.csv",
        }],
        temp_dir=str(tmp_path),
    )


@pytest.fixture
def quality_issues(dirty_df):
    """生成质量问题列表。"""
    preview = generate_preview(dirty_df, "test_data")
    result = DataQualityChecker.check(preview)
    return result.issues


# ============================================================
# CleaningPipeline: 单数据源清洗
# ============================================================

class TestPipelineSingleSource:
    """测试单数据源清洗管道。"""

    @pytest.mark.asyncio
    async def test_clean_success(self, raw_bundle, quality_issues):
        """清洗成功流程。"""
        yaml_rule = """
nodes:
  step1:
    operator: DropNull
    how: any
  step2:
    operator: Dedup
processor:
  chain: [step1, step2]
""".strip()

        engine = MockQueryEngine(yaml_response=yaml_rule, validation_pass=True)
        pipeline = CleaningPipeline(raw_bundle, engine, quality_issues)

        result = await pipeline.run()

        assert result.fetch_context.get("cleaning_applied") is True
        assert len(result.tabular_files) == 1
        # 清洗后行数应减少
        assert result.tabular_files[0]["row_count"] < 5

    @pytest.mark.asyncio
    async def test_clean_fallback_after_retries(self, raw_bundle, quality_issues):
        """3 次验证失败后 fallback 用原始数据。"""
        yaml_rule = """
nodes:
  step1:
    operator: Dedup
processor:
  chain: [step1]
""".strip()

        engine = MockQueryEngine(yaml_response=yaml_rule, validation_pass=False)
        pipeline = CleaningPipeline(raw_bundle, engine, quality_issues)

        result = await pipeline.run()

        # fallback 后仍标记为 cleaning_applied
        assert result.fetch_context.get("cleaning_applied") is True
        # LLM 应被调用至少 3 次（3 次生成 + 3 次验证）
        assert engine.call_count >= 3
        # 日志中应有 fallback 记录
        logs = result.fetch_context.get("cleaning_logs", [])
        assert any("3次" in log or "原始数据" in log for log in logs)

    @pytest.mark.asyncio
    async def test_dry_run_failure_triggers_retry(self, raw_bundle, quality_issues):
        """Dry Run 失败应触发重试。"""
        # 返回未知算子的 YAML -> Dry Run 会失败
        bad_yaml = """
nodes:
  step1:
    operator: NonExistent
processor:
  chain: [step1]
""".strip()

        engine = MockQueryEngine(yaml_response=bad_yaml, validation_pass=True)
        pipeline = CleaningPipeline(raw_bundle, engine, quality_issues)

        result = await pipeline.run()

        # 3 次都失败 -> fallback
        logs = result.fetch_context.get("cleaning_logs", [])
        assert any("3次" in log or "原始数据" in log for log in logs)

    @pytest.mark.asyncio
    async def test_empty_dataframe_skipped(self, tmp_path, quality_issues):
        """空 DataFrame 应被跳过。"""
        # 创建空的 parquet
        empty_path = tmp_path / "empty.parquet"
        pd.DataFrame().to_parquet(empty_path, index=False, engine="pyarrow")

        raw = RawDataBundle(
            source_kind="file",
            tabular_files=[{
                "name": "empty",
                "path": str(empty_path),
                "row_count": 0,
            }],
            temp_dir=str(tmp_path),
        )

        engine = MockQueryEngine(yaml_response="nodes:\n  step1:\n    operator: Dedup\nprocessor:\n  chain: [step1]")
        pipeline = CleaningPipeline(raw, engine, quality_issues)

        result = await pipeline.run()
        # 空文件跳过，不崩溃
        assert result.fetch_context.get("cleaning_applied") is True


# ============================================================
# CleaningPipeline: 多源 Join
# ============================================================

class TestPipelineMultiSource:
    """测试多源 Join 清洗管道。"""

    @pytest.mark.asyncio
    async def test_multi_source_no_join(self, tmp_path, dirty_df):
        """多源但不需要 Join -> 逐个独立清洗。"""
        # 两个 parquet 文件
        path1 = tmp_path / "data1.parquet"
        path2 = tmp_path / "data2.parquet"
        df1 = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
        df2 = pd.DataFrame({"category": ["x", "y"], "count": [10, 20]})
        df1.to_parquet(path1, index=False, engine="pyarrow")
        df2.to_parquet(path2, index=False, engine="pyarrow")

        raw = RawDataBundle(
            source_kind="file",
            tabular_files=[
                {"name": "data1", "path": str(path1), "row_count": 2},
                {"name": "data2", "path": str(path2), "row_count": 2},
            ],
            temp_dir=str(tmp_path),
        )

        yaml_rule = """
nodes:
  step1:
    operator: Dedup
processor:
  chain: [step1]
""".strip()

        engine = MockQueryEngine(
            yaml_response=yaml_rule,
            validation_pass=True,
            need_join=False,
        )
        pipeline = CleaningPipeline(raw, engine, [])

        result = await pipeline.run()

        # 不需要 Join，逐个清洗
        assert len(result.tabular_files) == 2
        assert result.fetch_context.get("cleaning_applied") is True
        assert not result.fetch_context.get("join_applied", False)

    @pytest.mark.asyncio
    async def test_multi_source_with_join(self, tmp_path):
        """多源需要 Join -> 合并清洗。"""
        path1 = tmp_path / "left.parquet"
        path2 = tmp_path / "right.parquet"
        df1 = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
        df2 = pd.DataFrame({"id": [1, 2], "value": [10, 20]})
        df1.to_parquet(path1, index=False, engine="pyarrow")
        df2.to_parquet(path2, index=False, engine="pyarrow")

        raw = RawDataBundle(
            source_kind="file",
            tabular_files=[
                {"name": "left", "path": str(path1), "row_count": 2},
                {"name": "right", "path": str(path2), "row_count": 2},
            ],
            temp_dir=str(tmp_path),
        )

        join_yaml = """
inputs:
  main: left
  aux: right
nodes:
  join1:
    operator: Join
    left: main
    right: aux
    on: id
    how: inner
processor:
  chain: [join1]
""".strip()

        engine = MockQueryEngine(
            yaml_response=join_yaml,
            validation_pass=True,
            need_join=True,
            join_config={
                "left": "left",
                "right": "right",
                "on": "id",
                "how": "inner",
                "reason": "有共同列 id",
            },
        )
        pipeline = CleaningPipeline(raw, engine, [])

        result = await pipeline.run()

        # Join 后应只剩 1 个 tabular_file
        assert len(result.tabular_files) == 1
        assert result.fetch_context.get("join_applied") is True
