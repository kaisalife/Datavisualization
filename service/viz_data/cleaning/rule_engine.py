"""YAML 清洗规则引擎。

解析 LLM 生成的 YAML 清洗规则，构建算子链，执行清洗。

YAML 格式:
    nodes:
      step1:
        operator: Dedup
        by: [id, date]
      step2:
        operator: RenameFields
        mapping:
          销售额: amount
          日期: date
      step3:
        operator: Map
        field: amount
        func: to_float
    processor:
      chain: [step1, step2, step3]

多源 Join 格式:
    inputs:
      main: orders
      aux: products
    nodes:
      join1:
        operator: Join
        left: main
        right: aux
        on: product_id
        how: left
      step1:
        operator: Dedup
    processor:
      chain: [join1, step1]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import yaml

from service.viz_data.cleaning.operators import (
    OPERATOR_REGISTRY,
    BaseOperator,
    get_operator,
)


@dataclass
class CleaningResult:
    """清洗执行结果。"""

    success: bool
    df: pd.DataFrame | None = None
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    rules_yaml: str | None = None


class CleaningRuleEngine:
    """YAML 清洗规则引擎。

    解析 YAML -> 构建算子链 -> 执行 -> 返回结果
    """

    def __init__(self, extra_operators: dict[str, type[BaseOperator]] | None = None):
        """初始化规则引擎。

        Args:
            extra_operators: 额外算子注册（扩展用）
        """
        self.operators = {**OPERATOR_REGISTRY}
        if extra_operators:
            self.operators.update(extra_operators)

    def execute(
        self,
        yaml_str: str,
        df: pd.DataFrame,
        inputs: dict[str, pd.DataFrame] | None = None,
    ) -> CleaningResult:
        """执行 YAML 清洗规则。

        Args:
            yaml_str: YAML 格式的清洗规则
            df: 输入 DataFrame
            inputs: 多源 DataFrame（Join 用）

        Returns:
            CleaningResult
        """
        all_logs: list[str] = []

        # 1. 解析 YAML
        try:
            spec = yaml.safe_load(yaml_str)
        except yaml.YAMLError as e:
            return CleaningResult(
                success=False,
                df=df,
                logs=all_logs,
                error=f"YAML 解析失败: {e}",
                rules_yaml=yaml_str,
            )

        if not isinstance(spec, dict):
            return CleaningResult(
                success=False,
                df=df,
                logs=all_logs,
                error="YAML 根节点必须是 dict",
                rules_yaml=yaml_str,
            )

        # 2. 解析多源 inputs（如果有）
        input_specs = spec.get("inputs", {})
        if input_specs and inputs:
            # inputs 是 {name: df} 的映射
            # input_specs 是 {alias: source_name} 的映射
            resolved_inputs = {}
            for alias, source_name in input_specs.items():
                if source_name in inputs:
                    resolved_inputs[alias] = inputs[source_name]
                else:
                    all_logs.append(f"WARNING: input '{source_name}' (alias '{alias}') not found")
            inputs = resolved_inputs

        # 3. 构建算子实例
        nodes_spec = spec.get("nodes", {})
        if not nodes_spec:
            return CleaningResult(
                success=False,
                df=df,
                logs=all_logs,
                error="YAML 中没有 nodes 定义",
                rules_yaml=yaml_str,
            )

        operators: dict[str, BaseOperator] = {}
        for node_name, node_def in nodes_spec.items():
            if not isinstance(node_def, dict):
                return CleaningResult(
                    success=False,
                    df=df,
                    logs=all_logs,
                    error=f"节点 '{node_name}' 定义必须是 dict",
                    rules_yaml=yaml_str,
                )

            op_name = node_def.get("operator")
            if not op_name:
                return CleaningResult(
                    success=False,
                    df=df,
                    logs=all_logs,
                    error=f"节点 '{node_name}' 缺少 operator 字段",
                    rules_yaml=yaml_str,
                )

            op_cls = self.operators.get(op_name)
            if op_cls is None:
                return CleaningResult(
                    success=False,
                    df=df,
                    logs=all_logs,
                    error=f"未知算子: '{op_name}'（节点: {node_name}）。可用: {sorted(self.operators.keys())}",
                    rules_yaml=yaml_str,
                )

            # 提取算子参数（排除 operator 字段）
            # YAML 1.1 会把 on/off/yes/no 解析为 bool，这里把非字符串键转回字符串
            _yaml_bool_map = {True: "on", False: "off", None: "null"}
            params = {}
            for k, v in node_def.items():
                if k == "operator":
                    continue
                key = _yaml_bool_map.get(k, k) if not isinstance(k, str) else k
                params[key] = v

            try:
                operators[node_name] = op_cls(**params)
            except TypeError as e:
                return CleaningResult(
                    success=False,
                    df=df,
                    logs=all_logs,
                    error=f"算子 '{op_name}' 参数错误（节点: {node_name}）: {e}",
                    rules_yaml=yaml_str,
                )

        # 4. 解析 processor（算子链）
        processor_spec = spec.get("processor", {})
        chain_steps = processor_spec.get("chain", [])

        if isinstance(chain_steps, str):
            chain_steps = [chain_steps]

        if not chain_steps:
            # 如果没有 processor，按 nodes 顺序执行
            chain_steps = list(nodes_spec.keys())

        # 5. 执行算子链
        result_df = df.copy()
        for step_name in chain_steps:
            if step_name not in operators:
                all_logs.append(f"WARNING: step '{step_name}' not found in nodes, skipping")
                continue

            op = operators[step_name]
            all_logs.append(f"--- {step_name}: {op} ---")

            try:
                result_df, step_logs = op.run(result_df, inputs=inputs)
                all_logs.extend(step_logs)
            except Exception as e:
                all_logs.append(f"ERROR: {e}")
                return CleaningResult(
                    success=False,
                    df=df,  # 返回原始 df
                    logs=all_logs,
                    error=f"算子 '{step_name}' ({op}) 执行失败: {e}",
                    rules_yaml=yaml_str,
                )

            # 检查结果是否为空
            if result_df is None or len(result_df) == 0:
                all_logs.append(f"WARNING: step '{step_name}' produced empty DataFrame")

        all_logs.append(f"=== 清洗完成: {len(df)} -> {len(result_df)} 行 ===")
        return CleaningResult(
            success=True,
            df=result_df,
            logs=all_logs,
            rules_yaml=yaml_str,
        )

    def dry_run(
        self,
        yaml_str: str,
        df: pd.DataFrame,
        sample_size: int = 10,
        inputs: dict[str, pd.DataFrame] | None = None,
    ) -> CleaningResult:
        """Dry Run：用采样数据试跑，快速发现语法/逻辑错误。

        Args:
            yaml_str: YAML 规则
            df: 输入 DataFrame
            sample_size: 采样行数

        Returns:
            CleaningResult（df 是采样后的结果）
        """
        sampled = df.head(sample_size)
        sampled_inputs = None
        if inputs:
            sampled_inputs = {k: v.head(sample_size) for k, v in inputs.items()}
        return self.execute(yaml_str, sampled, inputs=sampled_inputs)
