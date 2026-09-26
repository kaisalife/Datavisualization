"""LLM 表格化 prompt（P2：非表格源 -> 结构化表格）。

LLM 从 HTML/Markdown/日志等非表格文本中识别并抽取结构化表格数据，
输出 columns + rows 的统一 JSON。守护层负责解析与入 DuckDB。
"""
from langchain_core.prompts import ChatPromptTemplate

tabularize_prompt = """
你是数据提取专家。给定一段文本（HTML / Markdown / 日志 / 自由文本），
从中提取**结构化表格数据**，供后续写入数据库做可视化。

## 输入
{text}

## 任务
1. 分析文本，找出可表格化的数据，常见形态：
   - HTML 表格 / Markdown 表格（直接用其行列）
   - 日志中的重复记录（如每行"时间 级别 模块 消息"）
   - 键值对列表 / 清单（转成 键/值 或 名称/数值 两列）
   - 结构化文本块（如"城市: 北京 人口: 2000万" -> [城市, 人口]）
   - 嵌套数据（li/div/自定义结构）中隐含的重复字段
2. 输出**一张**最能支撑可视化的表：columns（列名数组）+ rows（每行一个对象，键=列名）
3. 无法提取结构化数据时输出空表 {{"columns": [], "rows": []}}

## 硬性约束
1. 列名用清晰的中文语义命名（如 时间/指标/数值/名称/类别）
2. 数值字段保持数值类型（如 2000 不要写成 "2000"）
3. 最多输出 200 行；多行重复记录合并成表，不要逐条堆砌
4. 只输出严格 JSON，无其他文字
5. 若一段文本与数据无关（纯叙述/标题），忽略它，不要硬造列

## 输出格式（严格 JSON）
{{"columns": ["列1", "列2"], "rows": [{{"列1": "值A", "列2": 123}}, {{"列1": "值B", "列2": 456}}]}}
"""


def get_tabularize_prompt() -> ChatPromptTemplate:
    """LLM 表格化 prompt 工厂。"""
    return ChatPromptTemplate([
        ("system", tabularize_prompt),
        ("human", "文本内容（截断后）:\n{text}"),
    ]).partial(text="(空)")
