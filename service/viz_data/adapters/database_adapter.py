"""DatabaseAdapter：从数据库拉数据 → 落 parquet → 组装 VizDataset。

支持三种查询模式（db_config.multi_query_mode）：
- "single"    ：一条 SQL（默认，兼容 M2）
- "auto"      ：LLM 自主决定生成 1~N 条独立 SQL
- "per_table" ：每个表生成一条 SELECT *（无 LLM 兜底方案）

多条 SQL 时：第一个结果 → primary VizDataset，其余 → primary.related_datasets（复用 OPT-3 机制）。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pandas as pd

from service.introspection.df_stats import (
    dataframe_to_column_schemas,
    infer_semantic_hints,
)
from service.viz_data.adapters.base import AdapterError, VizDataAdapter
from service.viz_data.capabilities import AdapterCapabilities
from service.viz_data.db_drivers import create_db_driver
from service.viz_data.planning.query_planner import Query
from service.viz_data.schema import (
    DataAccessor,
    DataRef,
    RawDataBundle,
    TabularBlock,
    VizDataset,
)
from service.viz_data.source_descriptor import SourceDescriptor
from service.viz_data.storage import new_dataset_dir, save_dataframe_to_parquet

if TYPE_CHECKING:
    from service.query_engine import QueryEngine
    from service.viz_data.ports import QueryPlannerPort


# 敏感字段列表：source_meta 里不能出现明文
_SENSITIVE_KEYS = {"password", "pwd", "secret", "api_key", "token"}


def redact_db_config(cfg: dict) -> dict:
    """把 db_config 里的密码等替换为 '***'，用于日志/响应。"""
    if not isinstance(cfg, dict):
        return cfg
    redacted = {}
    for k, v in cfg.items():
        if k.lower() in _SENSITIVE_KEYS:
            redacted[k] = "***"
        else:
            redacted[k] = v
    return redacted


class DatabaseAdapter(VizDataAdapter):
    """数据库源 Adapter。"""

    def __init__(self, db_config: dict, user_prompt: str = "",
                 max_rows: int = 100000, max_queries: int = 5,
                 planner: "QueryPlannerPort | None" = None):
        self.db_config = db_config
        self.user_prompt = user_prompt or ""
        self.max_rows = max_rows
        # 查询模式：single / auto / per_table
        self.multi_query_mode = str(db_config.get("multi_query_mode", "single")).lower()
        self.max_queries = int(db_config.get("max_queries", max_queries))
        # 可选注入的查询规划器；未注入时 fetch 阶段用 QueryEngine 构造默认 LlmSqlPlanner
        self._planner = planner

    def source_kind(self) -> str:
        return "database"

    def capabilities(self) -> AdapterCapabilities:
        # explicit query 或 per_table 模式不需要 LLM；否则需要
        explicit = bool(self.db_config.get("query"))
        needs_llm = not (explicit or self.multi_query_mode == "per_table")
        return AdapterCapabilities(
            needs_llm=needs_llm,
            supports_multi_query=self.multi_query_mode in ("auto", "per_table"),
            max_rows_hint=self.max_rows,
            fetch_can_fail_gracefully=False,   # 数据库源失败即整体失败
        )

    def descriptor(self) -> SourceDescriptor:
        db_type = str(self.db_config.get("db_type", "unknown"))
        database = str(self.db_config.get("database", "db"))
        # 提取纯 db 名（去掉路径/host）
        db_name = database.split("/")[-1].split("\\")[-1] or "db"
        table = self.db_config.get("table")
        label = f"{db_type}: {db_name}"
        if table:
            label += f".{table}"
            logical_id = f"db_{_sanitize_id(db_name)}_{_sanitize_id(str(table))}"
        else:
            logical_id = f"db_{_sanitize_id(db_name)}"
        return SourceDescriptor(
            kind="database",
            label=label,
            logical_id=logical_id,
            tags=("database", db_type),
        )

    def validate(self) -> None:
        if not isinstance(self.db_config, dict):
            raise AdapterError("db_config 必须是 dict")
        db_type = self.db_config.get("db_type")
        if not db_type:
            raise AdapterError("db_config.db_type 必填")
        if not self.db_config.get("database"):
            raise AdapterError("db_config.database 必填")
        if self.multi_query_mode not in ("single", "auto", "per_table"):
            raise AdapterError(
                f"multi_query_mode 必须是 single/auto/per_table，当前: {self.multi_query_mode}"
            )

    async def fetch(self, engine: "QueryEngine | None") -> RawDataBundle:
        """1. introspect  2. 解析查询列表  3. 逐条执行  4. 落 parquet"""
        driver = create_db_driver(self.db_config)
        try:
            # Step 1: introspect
            print(f"🔍 探测数据库 schema (mode={self.multi_query_mode})...")
            hint_table = self.db_config.get("table")
            tables_filter = [hint_table] if hint_table else None
            introspection = driver.introspect(tables=tables_filter)
            schema_text = introspection.to_prompt_text()
            print(f"📋 Schema:\n{schema_text[:500]}...")

            # Step 2: 解析出所有 query
            queries = await self._resolve_queries(engine, schema_text, introspection)
            if not queries:
                raise AdapterError("未生成任何 SQL 查询")
            print(f"💬 待执行 {len(queries)} 条 SQL:")
            for q in queries:
                print(f"  - [{q.name}] {q.body[:80]}...")

            # Step 3+4: 逐条执行 → 落盘
            ds_id, ds_dir = new_dataset_dir()
            db_name = str(self.db_config.get("database", "db")).split("/")[-1].split("\\")[-1] or "db"

            tabular_files = []
            failed_queries = []
            used_names: set[str] = set()
            for idx, q in enumerate(queries):
                # 名称去重
                base_name = q.name or f"query_{idx}"
                name = base_name
                dup_idx = 1
                while name in used_names:
                    name = f"{base_name}_{dup_idx}"
                    dup_idx += 1
                used_names.add(name)

                try:
                    df = driver.execute_query(q.body, limit=self.max_rows)
                    parquet_path = save_dataframe_to_parquet(df, ds_dir, name=name)
                    tabular_files.append({
                        "name": name,
                        "path": str(parquet_path.resolve()),
                        "row_count": int(len(df)),
                        "col_count": int(len(df.columns)),
                        "original_source": f"{self.db_config.get('db_type')}://{db_name}#{name}",
                        "sql": q.body,
                        "explanation": q.explanation,
                    })
                    print(f"  ✅ [{name}] 拉取 {len(df)} 行 × {len(df.columns)} 列")
                except Exception as e:
                    print(f"  ❌ [{name}] 执行失败: {type(e).__name__}: {e}")
                    failed_queries.append({
                        "name": name,
                        "sql": q.body,
                        "error": f"{type(e).__name__}: {e}",
                    })

            if not tabular_files:
                raise AdapterError(
                    f"所有 SQL 都执行失败。失败详情：{failed_queries}"
                )

            return RawDataBundle(
                source_kind="database",
                source_meta=redact_db_config(self.db_config),
                tabular_files=tabular_files,
                array_files=[],
                fetch_context={
                    "dataset_id": ds_id,
                    "schema_text": schema_text,
                    # 保持向后兼容：以 dict 形式塞入 fetch_context（供审计/日志）
                    "queries": [q.to_legacy_dict() for q in queries],
                    "failed_queries": failed_queries,
                    "user_prompt": self.user_prompt,
                    "multi_query_mode": self.multi_query_mode,
                },
                temp_dir=str(ds_dir.resolve()),
            )
        finally:
            driver.close()

    def normalize(self, raw: RawDataBundle) -> VizDataset:
        """从 raw.tabular_files 组装 VizDataset。多条时首个为 primary，其余为 related。"""
        if not raw.tabular_files:
            raise AdapterError("DatabaseAdapter.normalize: 没有 tabular_files")

        primary_ds = self._build_dataset(raw, raw.tabular_files[0], is_primary=True)

        for extra in raw.tabular_files[1:]:
            related = self._build_dataset(raw, extra, is_primary=False)
            primary_ds.related_datasets.append(related)

        return primary_ds

    def _build_dataset(self, raw: RawDataBundle, file_info: dict,
                       is_primary: bool = True) -> VizDataset:
        """单个 tabular_file → VizDataset。"""
        parquet_path = file_info["path"]

        df = pd.read_parquet(parquet_path, engine="pyarrow")
        columns = dataframe_to_column_schemas(df)
        preview_rows = df.head(10).astype(str).values.tolist()

        data_ref = DataRef(
            kind="parquet",
            path=parquet_path,
            size_bytes=os.path.getsize(parquet_path),
        )

        tabular = TabularBlock(
            columns=columns,
            row_count=int(len(df)),
            preview_rows=preview_rows,
            data_ref=data_ref,
        )

        semantic_hints = infer_semantic_hints(
            df, columns=columns, user_intent=raw.fetch_context.get("user_prompt")
        )

        explanation = file_info.get("explanation", "")
        docstring = f"读取 {file_info['name']}（来自数据库查询）"
        if explanation:
            docstring += f"：{explanation}"

        accessor = DataAccessor(
            accessor_id="load_data",
            signature="def load_data() -> pd.DataFrame",
            docstring=docstring,
            returns_description=f"DataFrame with {len(df)} rows and columns {list(df.columns)}",
        )

        dataset_id = raw.fetch_context.get("dataset_id", "ds_unknown")
        if not is_primary:
            dataset_id = f"{dataset_id}__{file_info['name']}"

        return VizDataset(
            dataset_id=dataset_id,
            name=file_info["name"],
            source_kind="database",
            source_meta=raw.source_meta,
            primary_form="tabular",
            tabular=tabular,
            arrays={},
            semantic_hints=semantic_hints,
            accessors=[accessor],
            _temp_dir=raw.temp_dir if is_primary else None,
        )

    # -------- 查询解析 --------

    async def _resolve_queries(self, engine: "QueryEngine | None",
                               schema_text: str, introspection) -> list[Query]:
        """按 multi_query_mode 派发生成查询列表。"""
        # 优先级 1：用户显式指定 query
        explicit_query = self.db_config.get("query")
        if explicit_query:
            return [Query(
                body=str(explicit_query).strip().rstrip(";"),
                name="query_result",
                explanation="用户显式指定的查询",
                dialect="sql",
            )]

        # 优先级 2：per_table 模式（无 LLM，最简单兜底）
        if self.multi_query_mode == "per_table":
            return self._per_table_queries(introspection)

        # 优先级 3：LLM 规划路径（通过 QueryPlanner 端口）
        planner = self._planner or self._build_default_planner(engine)
        hint_table = self.db_config.get("table")

        if self.multi_query_mode == "auto":
            queries = await planner.plan(
                schema_text=schema_text,
                user_prompt=self.user_prompt,
                hint=hint_table,
                max_queries=self.max_queries,
            )
            if not queries:
                # planner 失败则退化到 per_table
                print("⚠️ QueryPlanner 未返回可用 query，回退到 per_table")
                return self._per_table_queries(introspection)
            return queries[:self.max_queries]

        # single 模式（默认，兼容 M2）
        return await planner.plan(
            schema_text=schema_text,
            user_prompt=self.user_prompt,
            hint=hint_table,
            max_queries=1,
        )

    def _build_default_planner(self, engine: "QueryEngine | None") -> "QueryPlannerPort":
        """未注入 planner 时的默认构造：基于 engine 的 LlmSqlPlanner。"""
        if engine is None:
            raise AdapterError(
                "未提供 QueryEngine，且 db_config.query 也为空，无法生成 SQL；"
                "请注入 planner 或提供 QueryEngine"
            )
        from service.viz_data.planning.llm_sql_planner import LlmSqlPlanner
        return LlmSqlPlanner(engine)

    def _per_table_queries(self, introspection) -> list[Query]:
        """无 LLM 兜底：为每个表生成一条 SELECT * LIMIT 1000。"""
        result: list[Query] = []
        hint_table = self.db_config.get("table")
        tables = introspection.tables
        # 若指定了 hint_table，只处理它
        if hint_table:
            tables = [t for t in tables if t.name == hint_table]

        for t in tables[:self.max_queries]:
            result.append(Query(
                body=f"SELECT * FROM {t.name} LIMIT 1000",
                name=t.name,
                explanation=f"表 {t.name} 的样本数据",
                dialect="sql",
            ))
        return result


# ============================================================
# 内部工具
# ============================================================

def _sanitize_id(raw: str) -> str:
    """把任意字符串转成安全的 logical_id：只保留字母/数字/下划线/中文。"""
    if not raw:
        return "db"
    return "".join(c if (c.isalnum() or c == "_") else "_" for c in raw).strip("_") or "db"
