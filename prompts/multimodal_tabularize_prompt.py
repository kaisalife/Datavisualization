"""多模态表格化 prompt（图片 / 扫描件 / 图表截图 -> 结构化表格）。

与 ``tabularize_prompt`` 的区别：这里的输入不是文本，而是一张图片。
因此输出约束更强调"不要臆造""看不清用 null"，并要求从坐标轴图表中估读数据。
"""
from langchain_core.messages import HumanMessage, SystemMessage

MULTIMODAL_TABULARIZE_PROMPT = """
你是表格与图表数据提取专家。输入是一张图片（截图 / 扫描件 / 照片 / PDF 页面 / 统计图）。
请从中提取**一张**最适合做可视化的结构化表格。

## 任务
1. 识别图片中的表格、清单、报表、键值对、统计图坐标轴。
2. 还原行列关系；合并单元格向下/向右填充后再输出。
3. 若图片是折线图 / 柱状图 / 饼图，按坐标轴刻度估读数据点，数值列名后加"（估算）"。
4. 图片中有多张表时：优先取数据最完整、最适合做图的一张；若多张同构，合并为一张并在首列标注来源。
5. 图片中没有可用数据时，输出空表 {{"columns": [], "rows": []}}。

## 硬性约束
1. 列名优先**逐字沿用图中表头**（含单位、百分号、括号）；图中没有表头时才按内容命名。
   不得补全、改写或添加图中没有的业务含义（例如表头是"2023 年"，不要写成"2023年销售额"）。
2. 数值列必须是 JSON number，不要千分位、不要百分号；百分比可写成小数或把单位放进列名。
3. 缺失或看不清的单元格用 null，**禁止臆造数据**。
4. 最多输出 200 行。
5. 只输出严格 JSON，不要解释文字，不要 Markdown 代码块。

## 输出格式
{{"columns": ["年份", "销售额（万元）"], "rows": [{{"年份": 2023, "销售额（万元）": 1200}}]}}
"""


MULTIMODAL_MULTI_TABLE_PROMPT = """
你是表格与图表数据提取专家。输入是一张图片（截图 / 扫描件 / 照片 / PDF 页面 / 统计图）。
图中可能有多张**互不相同**的表格，请逐张提取。

## 任务
1. 识别图片中的所有结构化表格（含清单、报表、统计图、独立的键值对区块）。
2. 还原行列关系；合并单元格向下/向右填充后再输出。
3. 若图片是折线图 / 柱状图 / 饼图，按坐标轴刻度估读数据点，数值列名后加"（估算）"。
4. 同构且连续的续表（列结构一致）合并为一张；标题、页眉页脚、图例、注释不是表格，不要输出。
5. 每张表各自独立，不要把不同主题、不同列结构的表拼在一起。
6. 最多输出 5 张表；图片中没有可用数据时输出 {{"tables": []}}。

## 硬性约束
1. 列名优先**逐字沿用图中表头**（含单位、百分号、括号）；图中没有表头时才按内容命名。
   不得补全、改写或添加图中没有的业务含义（例如表头是"2023 年"，不要写成"2023年销售额"）。
2. 数值列必须是 JSON number，不要千分位、不要百分号；百分比可写成小数或把单位放进列名。
3. 缺失或看不清的单元格用 null，**禁止臆造数据**。
4. 每张表最多输出 200 行。
5. 只输出严格 JSON，不要解释文字，不要 Markdown 代码块。

## 输出格式
{{"tables": [
  {{"title": "2024 年区域销售", "columns": ["城市", "销售额（万元）"],
    "rows": [{{"城市": "北京", "销售额（万元）": 1200}}]}},
  {{"title": "库存", "columns": ["产品", "库存"],
    "rows": [{{"产品": "A", "库存": 30}}]}}
]}}
"""


def build_multimodal_tabularize_messages(
    image_url: str, hint: str = "", multi_table: bool = False
) -> list:
    """构造带图片的消息列表。

    Args:
        image_url: data URL（data:image/png;base64,...）
        hint: 用户的分析意图，用于从多张表中选主表（可为空）
        multi_table: True 时要求逐张输出图中所有表（``{"tables": [...]}``），
            False（默认）只输出一张主表（``{"columns","rows"}``）

    Returns:
        [SystemMessage, HumanMessage]
    """
    text = "请提取这张图片中的表格数据。"
    if hint and hint.strip():
        text += f"\n用户的分析意图（用于选择最合适的表）：{hint.strip()}"

    system_prompt = (
        MULTIMODAL_MULTI_TABLE_PROMPT if multi_table else MULTIMODAL_TABULARIZE_PROMPT
    )
    return [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=[
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
        ),
    ]
