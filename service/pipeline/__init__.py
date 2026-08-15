"""图表生成管线：数据接入 -> 计划生成 -> 并发图表生成。

模块：
- service_main:     主管线编排
- data_source:      请求 -> DataSource 构建 + DuckDB 接入
- plan_generator:   LLM 计划生成、解析、落盘
- chart_executor:   并发图表执行与结果汇总
- chart_generator:  单图表生成 + 沙箱执行 + 调试循环
- agent_pipeline:   viz_mode=agent 自主流水线
- data_preview:     智能数据预览（LLM 生成读取接口代码）
"""
