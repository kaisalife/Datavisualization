"""LlmSqlPlanner：基于 LLM 的 SQL 规划器实现。

从原 DatabaseAdapter._llm_single_query / _llm_multi_query 迁移而来。
只依赖 QueryEngine（通过接口）和 prompts 模块，与具体 Adapter 解耦。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from service.viz_data.adapters.base import AdapterError
from service.viz_data.planning.query_planner import Query

if TYPE_CHECKING:
    from service.query_engine import QueryEngine


class LlmSqlPlanner:
    """基于 LLM 的 SQL 规划器。实现 QueryPlannerPort（隐式）。

    plan(max_queries=1)  → 走 single-query prompt
    plan(max_queries>1)  → 走 multi-query prompt
    """

    dialect = "sql"

    def __init__(self, engine: "QueryEngine"):
        self._engine = engine

    async def plan(
        self,
        *,
        schema_text: str,
        user_prompt: str,
        hint: Optional[str] = None,
        max_queries: int = 1,
    ) -> list[Query]:
        if max_queries <= 0:
            raise AdapterError(f"max_queries 必须 >0，当前: {max_queries}")

        if max_queries == 1:
            sql = await self._plan_single(schema_text, user_prompt, hint)
            return [Query(body=sql, name="query_result",
                          explanation="LLM 生成的单条查询", dialect="sql")]
        return await self._plan_multi(schema_text, user_prompt, max_queries)

    # -------- 内部：单条 --------

    async def _plan_single(
        self,
        schema_text: str,
        user_prompt: str,
        hint: Optional[str],
    ) -> str:
        from prompts.agent_prompt import get_agent_db_query_prompt
        from service.utils import extract_json_from_response

        prompt = get_agent_db_query_prompt()
        response = await self._engine.run_prompt(prompt.invoke({
            "db_schema": schema_text,
            "user_prompt": user_prompt,
            "hint_table": hint or "(未指定)",
        }))

        parsed = extract_json_from_response(response)
        if not parsed or "sql" not in parsed:
            raise AdapterError(f"LLM 未返回可解析的 SQL，原始响应：{response[:500]}")
        return parsed["sql"].strip().rstrip(";")

    # -------- 内部：多条 --------

    async def _plan_multi(
        self,
        schema_text: str,
        user_prompt: str,
        max_queries: int,
    ) -> list[Query]:
        from prompts.agent_prompt import get_agent_db_multi_query_prompt
        from service.utils import extract_json_from_response

        prompt = get_agent_db_multi_query_prompt()
        response = await self._engine.run_prompt(prompt.invoke({
            "db_schema": schema_text,
            "user_prompt": user_prompt,
            "max_queries": str(max_queries),
        }))

        parsed = extract_json_from_response(response)
        if not parsed or "queries" not in parsed:
            print(f"⚠️ LLM 未返回 queries 字段，响应：{response[:300]}")
            return []

        raw_queries = parsed.get("queries") or []
        cleaned: list[Query] = []
        for i, q in enumerate(raw_queries):
            if not isinstance(q, dict) or not q.get("sql"):
                continue
            cleaned.append(Query(
                body=str(q["sql"]).strip().rstrip(";"),
                name=str(q.get("name") or f"query_{i}").strip(),
                explanation=str(q.get("explanation", "")),
                dialect="sql",
            ))
        return cleaned[:max_queries]
