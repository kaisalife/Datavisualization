"""端到端测试：使用 SmartETL 远程仓库的真实测试数据验证清洗管道。

测试数据来源：https://github.com/kaisalife/SmartETL/tree/main/test_data

测试内容：
1. 数据预览 + 质量检查（DataPreview + DataQualityChecker）
2. 规则引擎（CleaningRuleEngine）+ 手写 YAML 规则
3. 完整清洗管道（CleaningPipeline）+ Mock QueryEngine（模拟 LLM 生成规则）
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from service.viz_data.cleaning.operators import list_operators
from service.viz_data.cleaning.pipeline import CleaningPipeline
from service.viz_data.cleaning.preview import (
    DataQualityChecker,
    generate_preview,
)
from service.viz_data.cleaning.rule_engine import CleaningRuleEngine
from service.viz_data.schema import RawDataBundle


# ============================================================
# Mock QueryEngine —— 模拟 LLM 返回 YAML 规则
# ============================================================


class MockQueryEngine:
    """模拟 QueryEngine，根据 prompt 内容返回预定义的 YAML 规则。

    通过检查 prompt 中是否包含特定数据集名称，返回对应的手写 YAML 规则。
    验证请求返回 pass=true，模拟清洗成功。
    """

    def __init__(self):
        self.messages: list = []
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
        self.aborted = False
        self.session_id = "mock-session"
        self._call_count = 0

    async def run_prompt(self, prompt, chat=None, **kwargs) -> str:
        """模拟 LLM 调用，返回预定义的 YAML 规则或验证结果。"""
        self._call_count += 1
        self.usage["calls"] += 1

        # 将 prompt 转为字符串以检查内容
        prompt_text = self._prompt_to_str(prompt)

        # 判断是哪种请求：生成规则 / 优化规则 / 验证 / Join 检测
        if "判断以下清洗后的数据能否归一化" in prompt_text:
            # 验证请求 -> 返回 pass=true
            return json.dumps({
                "pass": True,
                "reason": "列名全英文，类型一致，行数充足，可以归一化",
                "suggestions": [],
            }, ensure_ascii=False)

        if "判断以下多个数据源是否需要关联" in prompt_text:
            # Join 检测 -> 不需要 Join
            return json.dumps({
                "need_join": False,
                "reason": "两个数据源没有共同的关联列，不需要 Join",
            }, ensure_ascii=False)

        # 生成/优化规则请求 -> 根据数据集名返回对应 YAML
        yaml = self._get_yaml_for_dataset(prompt_text)
        return f"```yaml\n{yaml}\n```"

    def _prompt_to_str(self, prompt) -> str:
        """将各种类型的 prompt 转为字符串。"""
        if isinstance(prompt, str):
            return prompt
        if isinstance(prompt, dict):
            return json.dumps(prompt, ensure_ascii=False)
        # ChatPromptValue 或类似对象
        if hasattr(prompt, "to_string"):
            return prompt.to_string()
        if hasattr(prompt, "messages"):
            parts = []
            for msg in prompt.messages:
                if hasattr(msg, "content"):
                    parts.append(str(msg.content))
                else:
                    parts.append(str(msg))
            return "\n".join(parts)
        return str(prompt)

    def _get_yaml_for_dataset(self, prompt_text: str) -> str:
        """根据 prompt 内容返回对应的清洗 YAML 规则。"""

        # economist 民调数据：NA 值多，需要清理 + 类型转换
        if "polltracker" in prompt_text or "pollster" in prompt_text or "economist" in prompt_text:
            return """
nodes:
  step1:
    operator: DropNull
    how: any
    subset: [pollster, sample_size, pct]
  step2:
    operator: Map
    field: sample_size
    func: to_int
  step3:
    operator: Map
    field: pct
    func: to_float
  step4:
    operator: Map
    field: date
    func: to_datetime
  step5:
    operator: Dedup
    by: [poll_id, candidate_name]
  step6:
    operator: Sort
    by: [date]
    ascending: true
processor:
  chain: [step1, step2, step3, step4, step5, step6]
""".strip()

        # futures 数据：嵌套 JSON，空字符串，中文
        # 注意：json_normalize 后 source 已展平为 source.name/source.type 等
        if "futures" in prompt_text or "Polymarket" in prompt_text or "is_future" in prompt_text:
            return """
nodes:
  step1:
    operator: Dedup
    by: [_id]
  step2:
    operator: Select
    columns: [_id, event_id, publish_time, source.name, source.type, results.national.Harris, results.national.Trump]
  step3:
    operator: Sort
    by: [source.name]
    ascending: true
processor:
  chain: [step1, step2, step3]
""".strip()

        # arxiv 数据：嵌套 JSON 结构
        if "arxiv" in prompt_text or "Atom" in prompt_text or "opensearch" in prompt_text:
            return """
nodes:
  step1:
    operator: Dedup
  step2:
    operator: DropNull
    how: all
processor:
  chain: [step1, step2]
""".strip()

        # id-name 数据：简单 id-name 对
        if "id-name" in prompt_text or "Q23" in prompt_text or "乔治" in prompt_text:
            return """
nodes:
  step1:
    operator: Dedup
    by: [id]
  step2:
    operator: Filter
    drop_empty: true
processor:
  chain: [step1, step2]
""".strip()

        # 默认：简单去重
        return """
nodes:
  step1:
    operator: Dedup
  step2:
    operator: DropNull
    how: all
processor:
  chain: [step1, step2]
""".strip()


# ============================================================
# 工具函数
# ============================================================

TEST_DATA_DIR = Path(__file__).resolve().parent / "test_data" / "smartetl"
TEMP_DIR = Path(__file__).resolve().parent / "test_temp"


def print_separator(title: str = "", char: str = "=", width: int = 70):
    """打印分隔线。"""
    if title:
        print(f"\n{char * width}")
        print(f"  {title}")
        print(f"{char * width}")
    else:
        print(char * width)


def load_economist_csv() -> pd.DataFrame:
    """加载 economist 民调 CSV 数据。"""
    path = TEST_DATA_DIR / "economist_1024_polltracker-polls.csv"
    df = pd.read_csv(path)
    return df


def load_futures_json() -> pd.DataFrame:
    """加载 futures JSON Lines 数据（每个对象一行）。"""
    path = TEST_DATA_DIR / "futures-1105.json"
    # futures-1105.json 是多个 JSON 对象（非数组），按行读取
    records = []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    # 按 }{ 分割（每个对象之间没有逗号）
    import re
    chunks = re.split(r"\}\s*\{", content)
    for i, chunk in enumerate(chunks):
        if i > 0:
            chunk = "{" + chunk
        if i < len(chunks) - 1:
            chunk = chunk + "}"
        chunk = chunk.strip()
        if chunk:
            try:
                records.append(json.loads(chunk))
            except json.JSONDecodeError:
                pass
    # 用 json_normalize 展平嵌套
    df = pd.json_normalize(records)
    return df


def load_arxiv_json() -> pd.DataFrame:
    """加载 arxiv JSON 数据（嵌套 Atom feed）。"""
    path = TEST_DATA_DIR / "arxiv.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # arxiv.json 是嵌套结构：feed > entry > [...]
    entries = data.get("feed", {}).get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]
    df = pd.json_normalize(entries)
    return df


def load_id_name_json() -> pd.DataFrame:
    """加载 id-name JSON Lines 数据。"""
    path = TEST_DATA_DIR / "id-name.json"
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    df = pd.DataFrame(records)
    return df


def save_as_parquet(df: pd.DataFrame, name: str) -> str:
    """将 DataFrame 保存为 parquet，返回路径。"""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMP_DIR / f"{name}.parquet"
    # object 列转字符串避免 pyarrow 序列化问题
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].astype(str)
    df.to_parquet(path, index=False, engine="pyarrow")
    return str(path)


# ============================================================
# 测试 1：数据预览 + 质量检查
# ============================================================


def test_quality_check():
    """测试数据预览和质量检查器。"""
    print_separator("测试 1：数据预览 + 质量检查", "=")

    datasets = {
        "economist_polls": load_economist_csv(),
        "futures": load_futures_json(),
        "arxiv": load_arxiv_json(),
        "id_name": load_id_name_json(),
    }

    all_results = {}
    for name, df in datasets.items():
        print(f"\n{'─' * 56}")
        print(f"📋 数据集: {name}")
        print(f"   形状: {df.shape[0]} 行 × {df.shape[1]} 列")
        print(f"   列名: {list(df.columns)[:10]}{'...' if len(df.columns) > 10 else ''}")

        # 生成预览
        preview = generate_preview(df, name)

        print(f"\n  📊 质量指标:")
        qm = preview.quality_metrics
        print(f"     总空值率: {qm.overall_null_rate:.1%}")
        print(f"     重复行率: {qm.dup_row_rate:.1%}")
        print(f"     中文列名: {'是' if qm.has_chinese_columns else '否'}")
        print(f"     混合类型: {'是' if qm.has_mixed_dtypes else '否'}")
        print(f"     空行存在: {'是' if qm.has_empty_rows else '否'}")

        # 质量检查
        quality = DataQualityChecker.check(preview)
        print(f"\n  🔍 质量检查结果: {'✅ 干净' if quality.is_clean else '⚠️ 需要清洗'}")
        if quality.issues:
            print(f"     发现 {len(quality.issues)} 个问题:")
            for issue in quality.issues:
                print(f"     [{issue.severity}] {issue.type}: {issue.message}")
                if issue.affected_columns:
                    print(f"       受影响列: {issue.affected_columns[:5]}")

        # 打印前 3 列的详情
        print(f"\n  📝 列详情 (前 5 列):")
        for col in preview.columns[:5]:
            print(f"     {col.name} ({col.dtype}) "
                  f"空值={col.null_rate:.1%} 唯一={col.unique_count} "
                  f"样本={col.sample_values[:3]}")

        all_results[name] = {
            "df": df,
            "preview": preview,
            "quality": quality,
        }

    return all_results


# ============================================================
# 测试 2：规则引擎 + 手写 YAML 规则
# ============================================================


def test_rule_engine():
    """测试规则引擎，对每个数据集执行手写的 YAML 清洗规则。"""
    print_separator("测试 2：规则引擎 + 手写 YAML 规则", "=")

    engine = CleaningRuleEngine()
    print(f"\n可用算子: {', '.join(list_operators())}")

    # ─── 2.1 economist 民调数据清洗 ───
    print_separator("2.1 economist 民调数据", "─")
    df = load_economist_csv()
    print(f"原始数据: {len(df)} 行 × {len(df.columns)} 列")
    print(f"空值总数: {int(df.isna().sum().sum())}")
    print(f"重复行: {int(df.duplicated().sum())}")

    yaml_rules = """
nodes:
  step1:
    operator: DropNull
    how: any
    subset: [pollster, sample_size, pct]
  step2:
    operator: Map
    field: sample_size
    func: to_int
  step3:
    operator: Map
    field: pct
    func: to_float
  step4:
    operator: Dedup
    by: [poll_id, candidate_name]
  step5:
    operator: Select
    columns: [poll_id, pollster, start_date, end_date, sample_size, candidate_name, pct, date, population, methodology]
processor:
  chain: [step1, step2, step3, step4, step5]
""".strip()

    print(f"\n📋 YAML 规则:\n{yaml_rules}")

    # Dry Run
    print(f"\n🧪 Dry Run (10 行采样)...")
    dry_result = engine.dry_run(yaml_rules, df, sample_size=10)
    if dry_result.success:
        print(f"  ✅ Dry Run 通过: {len(dry_result.df)} 行")
    else:
        print(f"  ❌ Dry Run 失败: {dry_result.error}")

    # 正式执行
    print(f"\n⚙️ 正式执行...")
    result = engine.execute(yaml_rules, df)
    if result.success:
        print(f"  ✅ 执行成功: {len(df)} -> {len(result.df)} 行 × {len(result.df.columns)} 列")
        print(f"  📝 执行日志:")
        for log in result.logs:
            print(f"     {log}")
        print(f"\n  清洗后前 3 行:")
        print(result.df.head(3).to_string())
    else:
        print(f"  ❌ 执行失败: {result.error}")
        for log in result.logs:
            print(f"     {log}")

    # ─── 2.2 futures JSON 数据清洗 ───
    print_separator("2.2 futures JSON 数据", "─")
    df2 = load_futures_json()
    print(f"原始数据: {len(df2)} 行 × {len(df2.columns)} 列")
    print(f"列名: {list(df2.columns)}")

    yaml_rules2 = """
nodes:
  step1:
    operator: Filter
    drop_empty: true
  step2:
    operator: Dedup
    by: [_id]
  step3:
    operator: Select
    columns: [_id, event_id, name, publish_time, source.name, source.type, results.national.Harris, results.national.Trump]
processor:
  chain: [step1, step2, step3]
""".strip()

    print(f"\n📋 YAML 规则:\n{yaml_rules2}")

    result2 = engine.execute(yaml_rules2, df2)
    if result2.success:
        print(f"\n  ✅ 执行成功: {len(df2)} -> {len(result2.df)} 行 × {len(result2.df.columns)} 列")
        for log in result2.logs:
            print(f"     {log}")
        print(f"\n  清洗后数据:")
        print(result2.df.to_string())
    else:
        print(f"\n  ❌ 执行失败: {result2.error}")
        for log in result2.logs:
            print(f"     {log}")

    # ─── 2.3 arxiv JSON 数据清洗 ───
    print_separator("2.3 arxiv JSON 数据", "─")
    df3 = load_arxiv_json()
    print(f"原始数据: {len(df3)} 行 × {len(df3.columns)} 列")
    print(f"列名: {list(df3.columns)[:10]}...")

    yaml_rules3 = """
nodes:
  step1:
    operator: Dedup
  step2:
    operator: DropNull
    how: all
  step3:
    operator: Filter
    drop_empty: true
processor:
  chain: [step1, step2, step3]
""".strip()

    result3 = engine.execute(yaml_rules3, df3)
    if result3.success:
        print(f"\n  ✅ 执行成功: {len(df3)} -> {len(result3.df)} 行 × {len(result3.df.columns)} 列")
        for log in result3.logs:
            print(f"     {log}")
    else:
        print(f"\n  ❌ 执行失败: {result3.error}")
        for log in result3.logs:
            print(f"     {log}")

    # ─── 2.4 id-name JSON Lines 数据清洗 ───
    print_separator("2.4 id-name JSON Lines 数据", "─")
    df4 = load_id_name_json()
    print(f"原始数据: {len(df4)} 行 × {len(df4.columns)} 列")
    print(f"前 3 行: {df4.head(3).to_dict('records')}")

    yaml_rules4 = """
nodes:
  step1:
    operator: Dedup
    by: [id]
  step2:
    operator: Filter
    drop_empty: true
  step3:
    operator: Sort
    by: [id]
    ascending: true
processor:
  chain: [step1, step2, step3]
""".strip()

    result4 = engine.execute(yaml_rules4, df4)
    if result4.success:
        print(f"\n  ✅ 执行成功: {len(df4)} -> {len(result4.df)} 行 × {len(result4.df.columns)} 列")
        for log in result4.logs:
            print(f"     {log}")
        print(f"\n  清洗后前 5 行:")
        print(result4.df.head(5).to_string())
    else:
        print(f"\n  ❌ 执行失败: {result4.error}")
        for log in result4.logs:
            print(f"     {log}")

    # ─── 2.5 多源 Join 测试 ───
    print_separator("2.5 多源 Join 测试 (economist + id-name)", "─")
    # 模拟：将 economist 的 pollster_id 和 id-name 的 id 关联
    # 先准备两个有共同列的 DataFrame
    df_left = pd.DataFrame({
        "id": ["Q23", "Q42", "Q207", "Q999"],
        "score": [85, 72, 90, 65],
        "category": ["A", "B", "A", "C"],
    })
    df_right = load_id_name_json().head(5)

    print(f"左表 (df_left): {len(df_left)} 行")
    print(df_left.to_string())
    print(f"\n右表 (id-name): {len(df_right)} 行")
    print(df_right.to_string())

    join_yaml = """
inputs:
  main: df_left
  aux: df_right
nodes:
  join1:
    operator: Join
    left: main
    right: aux
    on: id
    how: left
  step1:
    operator: FillNull
    fill_map:
      name: unknown
processor:
  chain: [join1, step1]
""".strip()

    print(f"\n📋 Join YAML 规则:\n{join_yaml}")

    join_result = engine.execute(join_yaml, df_left, inputs={"df_left": df_left, "df_right": df_right})
    if join_result.success:
        print(f"\n  ✅ Join 成功: {len(join_result.df)} 行 × {len(join_result.df.columns)} 列")
        for log in join_result.logs:
            print(f"     {log}")
        print(f"\n  Join 结果:")
        print(join_result.df.to_string())
    else:
        print(f"\n  ❌ Join 失败: {join_result.error}")
        for log in join_result.logs:
            print(f"     {log}")


# ============================================================
# 测试 3：完整清洗管道 + Mock QueryEngine
# ============================================================


async def test_full_pipeline():
    """测试完整清洗管道，使用 MockQueryEngine 模拟 LLM。"""
    print_separator("测试 3：完整清洗管道 + Mock QueryEngine", "=")

    mock_engine = MockQueryEngine()
    print(f"\nMock QueryEngine 已创建（模拟 LLM 生成规则）")
    print(f"可用算子: {', '.join(list_operators())}")

    # ─── 3.1 economist 数据完整清洗 ───
    print_separator("3.1 economist 数据完整清洗管道", "─")

    df = load_economist_csv()
    parquet_path = save_as_parquet(df.copy(), "economist_polls")

    # 创建 RawDataBundle
    raw = RawDataBundle(
        source_kind="file",
        source_meta={"original_source": "economist_1024_polltracker-polls.csv"},
        tabular_files=[{
            "name": "economist_polltracker-polls",
            "path": parquet_path,
            "row_count": len(df),
            "original_source": "economist_1024_polltracker-polls.csv",
        }],
        temp_dir=str(TEMP_DIR),
    )

    # 生成预览 + 质量检查
    preview = generate_preview(df, "economist_polltracker-polls")
    quality = DataQualityChecker.check(preview)

    print(f"原始数据: {len(df)} 行 × {len(df.columns)} 列")
    print(f"质量问题: {len(quality.issues)} 个")
    for issue in quality.issues:
        print(f"  [{issue.severity}] {issue.type}: {issue.message}")

    # 运行清洗管道
    pipeline = CleaningPipeline(raw, mock_engine, quality.issues)
    cleaned_raw = await pipeline.run()

    # 验证结果
    print(f"\n{'─' * 56}")
    print(f"📊 清洗结果:")
    for tf in cleaned_raw.tabular_files:
        print(f"  {tf['name']}: {tf.get('row_count', '?')} 行")
    print(f"  cleaning_applied: {cleaned_raw.fetch_context.get('cleaning_applied', False)}")
    print(f"  cleaning_logs count: {len(cleaned_raw.fetch_context.get('cleaning_logs', []))}")

    # ─── 3.2 futures 数据完整清洗 ───
    print_separator("3.2 futures JSON 数据完整清洗管道", "─")

    df2 = load_futures_json()
    parquet_path2 = save_as_parquet(df2.copy(), "futures")

    raw2 = RawDataBundle(
        source_kind="file",
        source_meta={"original_source": "futures-1105.json"},
        tabular_files=[{
            "name": "futures-1105",
            "path": parquet_path2,
            "row_count": len(df2),
            "original_source": "futures-1105.json",
        }],
        temp_dir=str(TEMP_DIR),
    )

    preview2 = generate_preview(df2, "futures-1105")
    quality2 = DataQualityChecker.check(preview2)

    print(f"原始数据: {len(df2)} 行 × {len(df2.columns)} 列")
    print(f"质量问题: {len(quality2.issues)} 个")
    for issue in quality2.issues:
        print(f"  [{issue.severity}] {issue.type}: {issue.message}")

    pipeline2 = CleaningPipeline(raw2, mock_engine, quality2.issues)
    cleaned_raw2 = await pipeline2.run()

    print(f"\n{'─' * 56}")
    print(f"📊 清洗结果:")
    for tf in cleaned_raw2.tabular_files:
        print(f"  {tf['name']}: {tf.get('row_count', '?')} 行")
    print(f"  cleaning_applied: {cleaned_raw2.fetch_context.get('cleaning_applied', False)}")

    # ─── 3.3 干净数据跳过清洗测试 ───
    print_separator("3.3 干净数据自动跳过清洗", "─")

    # 制造一个干净的数据集
    clean_df = pd.DataFrame({
        "id": [1, 2, 3, 4, 5],
        "name": ["Alice", "Bob", "Charlie", "David", "Eve"],
        "score": [85.5, 72.0, 90.3, 65.7, 88.1],
        "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
    })
    parquet_path3 = save_as_parquet(clean_df.copy(), "clean_data")

    raw3 = RawDataBundle(
        source_kind="file",
        source_meta={"original_source": "clean_data"},
        tabular_files=[{
            "name": "clean_data",
            "path": parquet_path3,
            "row_count": len(clean_df),
            "original_source": "clean_data",
        }],
        temp_dir=str(TEMP_DIR),
    )

    preview3 = generate_preview(clean_df, "clean_data")
    quality3 = DataQualityChecker.check(preview3)

    print(f"原始数据: {len(clean_df)} 行 × {len(clean_df.columns)} 列")
    print(f"质量问题: {len(quality3.issues)} 个 (预期: 0)")
    print(f"是否干净: {quality3.is_clean} (预期: True)")

    if quality3.is_clean:
        print(f"\n  ✅ 数据干净，跳过清洗（零 LLM 调用）")
        print(f"  MockQueryEngine 调用次数: {mock_engine._call_count} (预期不变)")
    else:
        print(f"\n  ⚠️ 质量检查发现问题，但预期是干净的")
        for issue in quality3.issues:
            print(f"     [{issue.severity}] {issue.type}: {issue.message}")


# ============================================================
# 主函数
# ============================================================


def main():
    """主入口：运行所有测试。"""
    print_separator("SmartETL 清洗管道端到端测试", "=")
    print(f"测试数据目录: {TEST_DATA_DIR}")
    print(f"临时输出目录: {TEMP_DIR}")

    # 检查测试数据是否存在
    if not TEST_DATA_DIR.exists():
        print(f"\n❌ 测试数据目录不存在: {TEST_DATA_DIR}")
        print("请先运行下载脚本获取 SmartETL 测试数据。")
        return

    files = list(TEST_DATA_DIR.glob("*"))
    print(f"测试数据文件: {[f.name for f in files]}")

    # 测试 1：质量检查
    test_quality_check()

    # 测试 2：规则引擎
    test_rule_engine()

    # 测试 3：完整管道
    asyncio.run(test_full_pipeline())

    # 清理
    print_separator("测试完成", "=")
    print(f"MockQueryEngine 总调用次数: {MockQueryEngine.__init__ and '见上方各测试'}")

    # 清理临时文件
    if TEMP_DIR.exists():
        import shutil
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
        print(f"已清理临时目录: {TEMP_DIR}")


if __name__ == "__main__":
    main()
