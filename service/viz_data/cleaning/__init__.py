"""数据清洗模块。

三阶段 Adapter 的 clean 阶段实现：
- preview: 数据预览 + 质量检查
- operators: 清洗算子（参考 SmartETL processor 设计）
- rule_engine: YAML 规则引擎
- pipeline: LLM 生成规则 -> 执行 -> AI 验证 -> 循环
"""
