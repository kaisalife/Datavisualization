"""清洗管道。

LLM 生成 YAML 规则 -> Dry Run -> 正式执行 -> AI 验证 -> 循环（最多 3 次）。

流程：
1. 从 RawDataBundle 读取 DataFrame
2. 生成数据预览
3. LLM 生成 YAML 清洗规则
4. Dry Run（10 行采样，快速发现语法错误）
5. 正式执行
6. AI 验证（清洗结果能否归一化）
7. 不通过则优化规则重新执行（最多 3 次）
8. 3 次失败则 fallback 用原始数据
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

import pandas as pd
from langchain_core.prompts import ChatPromptTemplate

from service.viz_data.cleaning.operators import list_operators
from service.viz_data.cleaning.preview import (
    DataPreview,
    DataQualityChecker,
    QualityIssue,
    QualityResult,
    generate_preview,
)
from service.viz_data.cleaning.rule_engine import CleaningResult, CleaningRuleEngine
from service.viz_data.schema import RawDataBundle

if TYPE_CHECKING:
    from service.query_engine import QueryEngine


# ─────────────────────────── YAML 提取 ───────────────────────────


def extract_yaml_from_response(text: str) -> str:
    """从 LLM 响应中提取 YAML。

    支持:
    - ```yaml ... ``` 代码块
    - ```...``` 代码块
    - 直接 YAML 文本
    """
    # 尝试提取 ```yaml ... ``` 代码块
    match = re.search(r"```ya?ml\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # 尝试提取 ```...``` 代码块
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # 直接返回（假设整个响应就是 YAML）
    return text.strip()


def extract_json_from_response(text: str) -> dict:
    """从 LLM 响应中提取 JSON。"""
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if match:
        import json

        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    # 尝试整个文本
    import json

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return {"pass": False, "reason": "无法解析 LLM 响应", "suggestions": []}


# ─────────────────────────── 清洗管道 ───────────────────────────


class CleaningPipeline:
    """LLM 生成规则 -> 执行 -> AI 验证 -> 循环。

    对 RawDataBundle 中的每个 tabular_file 执行清洗。
    清洗后数据写回 parquet，更新 row_count。
    """

    MAX_RETRIES = 3
    DRY_RUN_SAMPLE_SIZE = 10

    def __init__(
        self,
        raw: RawDataBundle,
        engine: "QueryEngine",
        issues: list[QualityIssue],
        rule_engine: CleaningRuleEngine | None = None,
    ):
        self.raw = raw
        self.engine = engine
        self.issues = issues
        self.rule_engine = rule_engine or CleaningRuleEngine()

        # 加载 Prompt 模板
        from prompts.cleaning_prompt import (
            cleaning_generate_prompt,
            cleaning_multi_source_prompt,
            cleaning_optimize_prompt,
            cleaning_validate_prompt,
            join_detection_prompt,
        )

        self._generate_template = ChatPromptTemplate.from_template(cleaning_generate_prompt)
        self._optimize_template = ChatPromptTemplate.from_template(cleaning_optimize_prompt)
        self._validate_template = ChatPromptTemplate.from_template(cleaning_validate_prompt)
        self._join_detect_template = ChatPromptTemplate.from_template(join_detection_prompt)
        self._multi_source_template = ChatPromptTemplate.from_template(cleaning_multi_source_prompt)

    async def run(self) -> RawDataBundle:
        """执行清洗管道，返回更新后的 RawDataBundle。"""
        operator_list = ", ".join(list_operators())
        cleaning_logs: list[str] = []

        print("\n" + "═" * 60)
        print(f"🧹 清洗管道启动")
        print(f"   数据源数量: {len(self.raw.tabular_files)}")
        for tf in self.raw.tabular_files:
            print(f"   - {tf['name']} ({tf.get('row_count', '?')} 行)")
        print(f"   质量问题: {len(self.issues)} 个")
        for issue in self.issues:
            print(f"     [{issue.severity}] {issue.type}: {issue.message}")
        print(f"   可用算子: {operator_list}")
        print("═" * 60)

        # 多源 Join 检测：如果有多于 1 个 tabular_file，先判断是否需要 Join
        if len(self.raw.tabular_files) > 1:
            print("\n🔍 多源 Join 检测中...")
            join_result = await self._check_need_join(operator_list)
            print(f"   结果: need_join={join_result.get('need_join')}")
            print(f"   原因: {join_result.get('reason', '')}")

            if join_result.get("need_join"):
                cleaning_logs.append(
                    f"🔗 多源 Join 检测: {join_result.get('reason', '')}"
                )
                print(f"\n🔗 启动多源 Join 清洗: {join_result.get('left')} + {join_result.get('right')} on {join_result.get('on')}")
                cleaned_raw = await self._clean_multi_source(
                    join_result, operator_list, cleaning_logs
                )
                self.raw.fetch_context["cleaning_applied"] = True
                self.raw.fetch_context["cleaning_logs"] = cleaning_logs
                self.raw.fetch_context["join_applied"] = True

                print("\n" + "═" * 60)
                print(f"✅ 清洗管道完成（多源 Join 模式）")
                print(f"   最终数据源: {len(self.raw.tabular_files)} 个")
                for tf in self.raw.tabular_files:
                    print(f"   - {tf['name']} ({tf.get('row_count', '?')} 行)")
                print("═" * 60 + "\n")
                return cleaned_raw
            else:
                cleaning_logs.append(
                    f"多源 Join 检测: {join_result.get('reason', '不需要 Join')}"
                )
                print("   → 不需要 Join，逐个独立清洗")

        # 逐个清洗每个 tabular_file
        for idx, tabular_file in enumerate(self.raw.tabular_files):
            name = tabular_file["name"]
            path = tabular_file["path"]

            print(f"\n{'─' * 60}")
            print(f"📋 [{idx + 1}/{len(self.raw.tabular_files)}] 清洗: {name}")
            print(f"   路径: {path}")

            # 读取 DataFrame
            df = pd.read_parquet(path)
            if df is None or len(df) == 0:
                cleaning_logs.append(f"[{name}] 跳过：空 DataFrame")
                print(f"   ⚠️ 空 DataFrame，跳过")
                continue

            print(f"   原始数据: {len(df)} 行 × {len(df.columns)} 列")
            print(f"   列名: {list(df.columns)}")

            # 执行清洗
            cleaned_df, logs = await self._clean_single_df(df, name, operator_list)
            cleaning_logs.extend(logs)

            # 写回 parquet（覆盖）
            if cleaned_df is not df:
                print(f"\n💾 写回 parquet: {path}")
                # object 列转字符串避免 mixed type 报错
                for col in cleaned_df.columns:
                    if cleaned_df[col].dtype == "object":
                        cleaned_df[col] = cleaned_df[col].astype(str)
                cleaned_df.to_parquet(path, index=False, engine="pyarrow")
                tabular_file["row_count"] = int(len(cleaned_df))
                print(f"   写入完成: {len(cleaned_df)} 行 × {len(cleaned_df.columns)} 列")

        # 更新 metadata
        self.raw.fetch_context["cleaning_applied"] = True
        self.raw.fetch_context["cleaning_logs"] = cleaning_logs

        print("\n" + "═" * 60)
        print(f"✅ 清洗管道完成（逐个清洗模式）")
        print(f"   处理数据源: {len(self.raw.tabular_files)} 个")
        for tf in self.raw.tabular_files:
            print(f"   - {tf['name']} ({tf.get('row_count', '?')} 行)")
        print("═" * 60 + "\n")
        return self.raw

    async def _clean_single_df(
        self,
        df: pd.DataFrame,
        name: str,
        operator_list: str,
    ) -> tuple[pd.DataFrame, list[str]]:
        """清洗单个 DataFrame，返回 (结果df, 日志)。"""
        all_logs: list[str] = [f"=== 清洗开始: {name} ({len(df)} 行) ==="]
        preview = generate_preview(df, name)
        quality_text = self._format_issues()

        print(f"\n  📊 数据预览:")
        print(f"     行数: {preview.row_count}, 列数: {preview.column_count}")
        print(f"     质量指标: 空值率={preview.quality_metrics.overall_null_rate:.1%}, "
              f"重复率={preview.quality_metrics.dup_row_rate:.1%}, "
              f"中文列名={preview.quality_metrics.has_chinese_columns}, "
              f"混合类型={preview.quality_metrics.has_mixed_dtypes}")
        print(f"     列详情:")
        for col in preview.columns:
            print(f"       {col.name} ({col.dtype}) "
                  f"空值={col.null_rate:.1%} 唯一={col.unique_count} "
                  f"样本={col.sample_values[:3]}")

        prev_yaml = ""
        prev_error = ""
        prev_logs: list[str] = []

        for attempt in range(self.MAX_RETRIES):
            print(f"\n  {'─' * 56}")
            print(f"  🔄 循环 {attempt + 1}/{self.MAX_RETRIES}")
            all_logs.append(f"--- 尝试 {attempt + 1}/{self.MAX_RETRIES} ---")

            # 1. LLM 生成/优化规则
            if attempt == 0:
                print(f"  📝 调用 LLM 生成清洗规则...")
                rules_yaml = await self._generate_rules(preview, quality_text, operator_list)
            else:
                print(f"  📝 调用 LLM 优化规则（上次失败原因: {prev_error}）...")
                rules_yaml = await self._optimize_rules(
                    preview, prev_yaml, prev_error, prev_logs, operator_list
                )

            print(f"  📋 LLM 生成的 YAML 规则:")
            print(f"  {'─' * 56}")
            for line in rules_yaml.split('\n'):
                print(f"     {line}")
            print(f"  {'─' * 56}")
            all_logs.append(f"LLM 生成规则:\n{rules_yaml}")

            # 2. Dry Run（10 行采样）
            print(f"  🧪 Dry Run（{self.DRY_RUN_SAMPLE_SIZE} 行采样）...")
            dry_result = await asyncio.to_thread(
                self.rule_engine.dry_run,
                rules_yaml,
                df,
                self.DRY_RUN_SAMPLE_SIZE,
            )
            if not dry_result.success:
                prev_yaml = rules_yaml
                prev_error = dry_result.error or "Dry Run 失败"
                prev_logs = dry_result.logs
                print(f"  ❌ Dry Run 失败: {prev_error}")
                all_logs.append(f"Dry Run 失败: {prev_error}")
                continue

            print(f"  ✅ Dry Run 通过 -> {len(dry_result.df)} 行")
            all_logs.append("Dry Run 通过")

            # 3. 正式执行
            print(f"  ⚙️ 正式执行清洗规则...")
            result = await asyncio.to_thread(self.rule_engine.execute, rules_yaml, df)
            if not result.success or result.df is None or len(result.df) == 0:
                prev_yaml = rules_yaml
                prev_error = result.error or "执行后 DataFrame 为空"
                prev_logs = result.logs
                print(f"  ❌ 执行失败: {prev_error}")
                all_logs.append(f"执行失败: {prev_error}")
                continue

            print(f"  ✅ 执行成功: {len(df)} -> {len(result.df)} 行 × {len(result.df.columns)} 列")
            print(f"  📝 执行日志:")
            for log_line in result.logs:
                print(f"     {log_line}")
            all_logs.append(f"执行成功: {len(df)} -> {len(result.df)} 行")

            # 4. AI 验证
            print(f"  🔍 AI 验证清洗结果（能否归一化）...")
            validation = await self._validate(result.df, name)
            print(f"  {'✅' if validation['pass'] else '❌'} 验证结果: pass={validation['pass']}")
            print(f"     原因: {validation['reason']}")
            if validation.get('suggestions'):
                print(f"     建议: {validation['suggestions']}")
            all_logs.append(f"AI 验证: pass={validation['pass']}, reason={validation['reason']}")

            if validation["pass"]:
                print(f"\n  ✅ 清洗成功: {name} ({len(df)} -> {len(result.df)} 行)")
                all_logs.append(f"=== 清洗完成: {name} ({len(result.df)} 行) ===")
                return result.df, all_logs

            # 5. 不通过，准备下一轮
            print(f"  ⚠️ 验证未通过，准备下一轮优化...")
            prev_yaml = rules_yaml
            prev_error = validation["reason"]
            prev_logs = result.logs
            # 更新预览（用清洗后的数据重新预览）
            preview = generate_preview(result.df, name)

        # 6. Fallback：3 次失败，用原始数据
        print(f"\n  ⚠️ 3 次循环均未通过，使用原始数据")
        print(f"     最终质量标记: low")
        all_logs.append(f"=== 清洗失败（3次），使用原始数据: {name} ===")
        all_logs.append(f"最终质量标记: low")
        return df, all_logs

    async def _generate_rules(
        self, preview: DataPreview, quality_text: str, operator_list: str
    ) -> str:
        """LLM 生成 YAML 清洗规则。"""
        prompt = self._generate_template.invoke({
            "preview": preview.to_prompt_text(),
            "quality_issues": quality_text,
            "operator_list": operator_list,
        })
        response = await self.engine.run_prompt(prompt)
        return extract_yaml_from_response(response)

    async def _optimize_rules(
        self,
        preview: DataPreview,
        prev_yaml: str,
        prev_error: str,
        prev_logs: list[str],
        operator_list: str,
    ) -> str:
        """LLM 优化失败的 YAML 规则。"""
        prompt = self._optimize_template.invoke({
            "preview": preview.to_prompt_text(),
            "prev_yaml": prev_yaml,
            "prev_error": prev_error,
            "prev_logs": "\n".join(prev_logs[-10:]),  # 只取最后 10 行日志
            "operator_list": operator_list,
        })
        response = await self.engine.run_prompt(prompt)
        return extract_yaml_from_response(response)

    async def _validate(self, df: pd.DataFrame, name: str) -> dict:
        """AI 验证清洗结果能否归一化。"""
        preview = generate_preview(df, name)
        prompt = self._validate_template.invoke({
            "preview": preview.to_prompt_text(),
        })
        response = await self.engine.run_prompt(prompt)
        result = extract_json_from_response(response)
        # 确保返回格式正确
        return {
            "pass": result.get("pass", False),
            "reason": result.get("reason", "未知"),
            "suggestions": result.get("suggestions", []),
        }

    def _format_issues(self) -> str:
        """格式化质量问题为文本。"""
        if not self.issues:
            return "无明显质量问题（但数据可能需要规范化）"
        lines = []
        for issue in self.issues:
            lines.append(
                f"[{issue.severity}] {issue.type}: {issue.message}"
            )
            if issue.affected_columns:
                lines.append(f"  受影响列: {issue.affected_columns}")
        return "\n".join(lines)

    # ─── 多源 Join 支持 ───

    async def _check_need_join(self, operator_list: str) -> dict:
        """LLM 判断多个数据源是否需要关联。"""
        # 生成每个数据源的摘要
        sources = []
        for tf in self.raw.tabular_files:
            try:
                df = pd.read_parquet(tf["path"])
                preview = generate_preview(df, tf["name"])
                sources.append(
                    f"- {tf['name']} ({preview.row_count} 行 x {preview.column_count} 列): "
                    f"列名={list(c.name for c in preview.columns)}"
                )
            except Exception:
                sources.append(f"- {tf['name']} (读取失败)")

        prompt = self._join_detect_template.invoke({
            "sources": "\n".join(sources),
        })
        response = await self.engine.run_prompt(prompt)
        result = extract_json_from_response(response)
        # 确保返回格式正确
        return {
            "need_join": result.get("need_join", False),
            "left": result.get("left", ""),
            "right": result.get("right", ""),
            "on": result.get("on", ""),
            "how": result.get("how", "left"),
            "reason": result.get("reason", ""),
        }

    async def _clean_multi_source(
        self, join_config: dict, operator_list: str, cleaning_logs: list[str]
    ) -> RawDataBundle:
        """多源 Join + 清洗。

        1. 读取所有 DataFrame 作为 inputs
        2. LLM 生成含 Join 算子的 YAML 规则
        3. 规则引擎执行（传入 inputs）
        4. AI 验证
        5. 循环（最多 3 次）
        6. Join 后的结果替换 tabular_files
        """
        print("\n  " + "─" * 56)
        print(f"  🔗 多源 Join 清洗启动")
        print(f"     Join 配置: {join_config.get('left')} + {join_config.get('right')} "
              f"on '{join_config.get('on')}' ({join_config.get('how', 'left')})")

        # 读取所有 DataFrame
        inputs: dict[str, pd.DataFrame] = {}
        for tf in self.raw.tabular_files:
            inputs[tf["name"]] = pd.read_parquet(tf["path"])
            print(f"     数据源 {tf['name']}: {len(inputs[tf['name']])} 行 × {len(inputs[tf['name']].columns)} 列")

        # 生成数据源预览
        sources_preview = []
        for name, df in inputs.items():
            preview = generate_preview(df, name)
            sources_preview.append(preview.to_prompt_text())
        sources_preview_text = "\n---\n".join(sources_preview)

        # Join 配置文本
        join_config_text = (
            f"主表(left): {join_config.get('left', '')}\n"
            f"关联表(right): {join_config.get('right', '')}\n"
            f"关联列(on): {join_config.get('on', '')}\n"
            f"关联方式(how): {join_config.get('how', 'left')}"
        )

        prev_yaml = ""
        prev_error = ""
        prev_logs: list[str] = []

        for attempt in range(self.MAX_RETRIES):
            print(f"\n  {'─' * 56}")
            print(f"  🔄 多源清洗循环 {attempt + 1}/{self.MAX_RETRIES}")
            cleaning_logs.append(f"--- 多源清洗尝试 {attempt + 1}/{self.MAX_RETRIES} ---")

            # 1. LLM 生成/优化规则
            if attempt == 0:
                print(f"  📝 调用 LLM 生成多源清洗规则（含 Join）...")
                rules_yaml = await self._generate_multi_source_rules(
                    sources_preview_text, join_config_text, operator_list
                )
            else:
                print(f"  📝 调用 LLM 优化规则（上次失败原因: {prev_error}）...")
                rules_yaml = await self._optimize_rules(
                    generate_preview(next(iter(inputs.values())), "multi"),
                    prev_yaml,
                    prev_error,
                    prev_logs,
                    operator_list,
                )

            print(f"  📋 LLM 生成的 YAML 规则:")
            print(f"  {'─' * 56}")
            for line in rules_yaml.split('\n'):
                print(f"     {line}")
            print(f"  {'─' * 56}")
            cleaning_logs.append(f"LLM 生成规则:\n{rules_yaml}")

            # 2. Dry Run
            print(f"  🧪 Dry Run（{self.DRY_RUN_SAMPLE_SIZE} 行采样）...")
            dry_inputs = {k: v.head(self.DRY_RUN_SAMPLE_SIZE) for k, v in inputs.items()}
            first_df = next(iter(inputs.values()))
            dry_result = await asyncio.to_thread(
                self.rule_engine.dry_run,
                rules_yaml,
                first_df,
                self.DRY_RUN_SAMPLE_SIZE,
                dry_inputs,
            )
            if not dry_result.success:
                prev_yaml = rules_yaml
                prev_error = dry_result.error or "Dry Run 失败"
                prev_logs = dry_result.logs
                print(f"  ❌ Dry Run 失败: {prev_error}")
                cleaning_logs.append(f"Dry Run 失败: {prev_error}")
                continue

            print(f"  ✅ Dry Run 通过 -> {len(dry_result.df)} 行")
            cleaning_logs.append("Dry Run 通过")

            # 3. 正式执行
            print(f"  ⚙️ 正式执行多源清洗规则...")
            print(f"     输入数据源: {list(inputs.keys())}")
            result = await asyncio.to_thread(
                self.rule_engine.execute, rules_yaml, first_df, inputs
            )
            if not result.success or result.df is None or len(result.df) == 0:
                prev_yaml = rules_yaml
                prev_error = result.error or "执行后 DataFrame 为空"
                prev_logs = result.logs
                print(f"  ❌ 执行失败: {prev_error}")
                cleaning_logs.append(f"执行失败: {prev_error}")
                continue

            print(f"  ✅ 执行成功: Join 后 {len(result.df)} 行 × {len(result.df.columns)} 列")
            print(f"  📝 执行日志:")
            for log_line in result.logs:
                print(f"     {log_line}")
            cleaning_logs.append(f"执行成功: Join 后 {len(result.df)} 行")

            # 4. AI 验证
            print(f"  🔍 AI 验证清洗结果（能否归一化）...")
            validation = await self._validate(result.df, "joined")
            print(f"  {'✅' if validation['pass'] else '❌'} 验证结果: pass={validation['pass']}")
            print(f"     原因: {validation['reason']}")
            if validation.get('suggestions'):
                print(f"     建议: {validation['suggestions']}")
            cleaning_logs.append(
                f"AI 验证: pass={validation['pass']}, reason={validation['reason']}"
            )

            if validation["pass"]:
                # 成功：用 Join 后的结果替换 tabular_files
                print(f"\n  ✅ 多源 Join 清洗成功!")
                primary_path = self.raw.tabular_files[0]["path"]
                # object 列转字符串
                for col in result.df.columns:
                    if result.df[col].dtype == "object":
                        result.df[col] = result.df[col].astype(str)
                result.df.to_parquet(primary_path, index=False, engine="pyarrow")
                print(f"  💾 写回 parquet: {primary_path}")
                print(f"     最终数据: {len(result.df)} 行 × {len(result.df.columns)} 列")
                print(f"     列名: {list(result.df.columns)}")

                # 更新 tabular_files（只保留 Join 后的第一个）
                self.raw.tabular_files[0]["row_count"] = int(len(result.df))
                self.raw.tabular_files[0]["col_count"] = int(len(result.df.columns))
                # 删除其余 tabular_files（已合并）
                self.raw.tabular_files = [self.raw.tabular_files[0]]

                cleaning_logs.append(f"=== 多源清洗完成: {len(result.df)} 行 ===")
                return self.raw

            # 5. 不通过，准备下一轮
            print(f"  ⚠️ 验证未通过，准备下一轮优化...")
            prev_yaml = rules_yaml
            prev_error = validation["reason"]
            prev_logs = result.logs

        # 6. Fallback：3 次失败，逐个独立清洗
        print(f"\n  ⚠️ 3 次多源 Join 清洗均未通过，回退到逐个独立清洗")
        cleaning_logs.append("=== 多源 Join 清洗失败（3次），回退到逐个独立清洗 ===")
        for tabular_file in self.raw.tabular_files:
            name = tabular_file["name"]
            path = tabular_file["path"]
            df = pd.read_parquet(path)
            if df is None or len(df) == 0:
                continue
            cleaned_df, logs = await self._clean_single_df(df, name, operator_list)
            cleaning_logs.extend(logs)
            if cleaned_df is not df:
                for col in cleaned_df.columns:
                    if cleaned_df[col].dtype == "object":
                        cleaned_df[col] = cleaned_df[col].astype(str)
                cleaned_df.to_parquet(path, index=False, engine="pyarrow")
                tabular_file["row_count"] = int(len(cleaned_df))

        return self.raw

    async def _generate_multi_source_rules(
        self, sources_preview: str, join_config: str, operator_list: str
    ) -> str:
        """LLM 生成多源清洗 YAML 规则。"""
        prompt = self._multi_source_template.invoke({
            "sources_preview": sources_preview,
            "join_config": join_config,
            "quality_issues": self._format_issues(),
            "operator_list": operator_list,
            "first_source": self.raw.tabular_files[0]["name"] if self.raw.tabular_files else "main",
            "second_source": self.raw.tabular_files[1]["name"] if len(self.raw.tabular_files) > 1 else "aux",
        })
        response = await self.engine.run_prompt(prompt)
        return extract_yaml_from_response(response)
