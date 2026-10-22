"""MCP tool: 数据视图暴露面（describe_dataset / run_view）

被 langchain_mcp_adapters 通过 stdio 协议启动为子进程；是
``service/data_view/session.py`` 的薄适配器——不保存状态、不实现逻辑、
不接触 DataFrame/路径（只传 dataset_id 与 ViewSpec 句柄）。

状态模型（docs/数据清洗工具集/04）::

    dataset_id (ds_<12hex>) → runtime/datasets/<ds>/ 会话目录（磁盘持久）
    view_id    (vw_<hash>)  → <会话>/views/<view_id>.parquet

失败返回结构化 JSON（ok/code/message），错误码与库层一致。
"""

import os
import sys

from dotenv import load_dotenv
from fastmcp import FastMCP

# 确保能导入项目根下的 service.*
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

mcp = FastMCP("data_view")

_RESULT_SAMPLE_ROWS = 3
_ERROR_SAMPLE_ROWS = 5


def _format(payload) -> str:
    """统一 JSON 文本返回（ensure_ascii=False，中文可读）。"""
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


@mcp.tool()
def describe_dataset(dataset_id: str) -> str:
    """List queryable tables, columns, sample rows and existing derived views.

    Args:
        dataset_id: 数据集会话 id（ds_<12hex>，来自预览响应）

    Returns:
        str: JSON {"tables": [{"alias","name","origin","rows","columns","sample"}],
        "views": [...] }；失败返回 JSON {"ok": false, "code", "message"}
    """
    try:
        from service.data_view.session import describe_dataset

        info = describe_dataset(dataset_id)
    except Exception as e:  # DataViewError 及环境类错误都收敛成结构化返回
        code = getattr(e, "code", "INPUT_INVALID")
        return _format({"ok": False, "code": code, "message": str(e)})
    return _format({"ok": True, **info})


@mcp.tool()
def run_view(dataset_id: str, spec: dict, mode: str = "materialize") -> str:
    """Run a deterministic read-only transform (SQL over the dataset tables).

    Args:
        dataset_id: 数据集会话 id
        spec: ViewSpec JSON：{"kind":"sql","inputs":["table_0"],"
            "sql":"select ... group by ... order by ..."} 或
            {"kind":"plugin","plugin":"名称","plugin_version":N,"inputs":[...],"params":{}}
        mode: materialize=落盘（可被 plan 引用）；preview=只回内存样例

    Returns:
        str: JSON {"view_id","rows","schema","sample","spec_summary"}，
        失败返回 {"ok": false, "code", "message", "hint"}
    """
    try:
        from service.data_view.session import run_view as _run_view

        payload = _run_view(dataset_id, spec, mode=mode)
        return _format({"ok": True, **payload})
    except Exception as e:
        code = getattr(e, "code", "SPEC_INVALID")
        message = str(e)
        hint = {
            "WRITE_STATEMENT_REJECTED": "请提交单条只读 SELECT/WITH 查询",
            "UNORDERED_OUTPUT": "SQL 必须带 ORDER BY（或声明 allow_unordered）",
            "EMPTY_RESULT": "检查筛选/聚合条件，或给 spec 加 allow_empty=true",
            "ROW_LIMIT_EXCEEDED": "在 SQL 里加 LIMIT 或进一步聚合",
            "INPUT_NOT_FOUND": "先调用 describe_dataset 确认可用别名",
        }.get(code, "按错误信息修正 spec 后重试一次")
        return _format({"ok": False, "code": code, "message": message, "hint": hint})


if __name__ == "__main__":
    mcp.run()
