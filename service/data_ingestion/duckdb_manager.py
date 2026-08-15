"""DuckDB 连接管理器。

每个数据接入会话使用一个独立的 .duckdb 文件，
沙箱进程通过同一文件路径连接查询。

核心职责:
- 管理 DuckDB 连接 (文件持久化, 跨进程共享)
- 注册各种数据源为 DuckDB 表/视图
- 提供 schema 推断 (DESCRIBE) 和统计 (SUMMARIZE) 查询
- 导出 parquet 标准化落盘
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from service.data_ingestion.models import DataProfile
from service.observability import get_logger


logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _get_temp_root() -> Path:
    """获取临时数据目录，可通过环境变量 TEMP_DATASETS_DIR 覆盖。"""
    override = os.getenv("TEMP_DATASETS_DIR")
    if override:
        return Path(override)
    return PROJECT_ROOT / "runtime" / "datasets"


def new_duckdb_path(session_id: str | None = None) -> tuple[str, Path]:
    """分配一个 DuckDB 文件路径。返回 (session_id, path)。

    每次调用时顺带清理超过 max_age_seconds 的旧 .duckdb 文件。
    """
    sid = session_id or f"ds_{uuid.uuid4().hex[:12]}"
    path = _get_temp_root() / sid / "data.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    cleanup_old_duckdb_files()
    return sid, path


def cleanup_old_duckdb_files(max_age_hours: float = 24.0) -> int:
    """清理超过 max_age_hours 的旧 .duckdb 会话目录。

    DuckDB 文件在会话结束后不再需要，定期清理避免磁盘膨胀。
    只删除 data.duckdb 和同目录的 .duckdb.wal 文件。

    Returns:
        清理的文件数量
    """
    import time

    t0 = time.perf_counter()
    temp_root = _get_temp_root()
    if not temp_root.exists():
        return 0

    now = time.time()
    max_age_seconds = max_age_hours * 3600
    cleaned = 0
    scanned = 0

    for session_dir in temp_root.iterdir():
        if not session_dir.is_dir():
            continue

        duckdb_file = session_dir / "data.duckdb"
        if not duckdb_file.exists():
            continue

        scanned += 1

        # 检查文件修改时间
        try:
            mtime = duckdb_file.stat().st_mtime
        except OSError:
            continue

        if (now - mtime) > max_age_seconds:
            t_del_start = time.perf_counter()
            try:
                # 删除 .duckdb 文件
                duckdb_file.unlink(missing_ok=True)
                cleaned += 1
                # 删除 .duckdb.wal 文件 (如果存在)
                wal_file = session_dir / "data.duckdb.wal"
                wal_file.unlink(missing_ok=True)
                # 删除空目录
                if not any(session_dir.iterdir()):
                    session_dir.rmdir()
                t_del = time.perf_counter()
                logger.info(
                    "cleanup 删除",
                    session_dir=session_dir.name,
                    age_hours=(now - mtime) / 3600,
                    del_time_s=t_del - t_del_start,
                )
            except OSError as e:
                t_del = time.perf_counter()
                logger.warning(
                    "cleanup 删除失败",
                    session_dir=session_dir.name,
                    error=str(e),
                    del_time_s=t_del - t_del_start,
                )

    t_total = time.perf_counter() - t0
    if cleaned > 0:
        logger.info(
            "cleanup 完成",
            scanned=scanned,
            cleaned=cleaned,
            total_time_s=t_total,
            max_age_hours=max_age_hours,
        )
    else:
        logger.info("cleanup 完成", scanned=scanned, cleaned=0, total_time_s=t_total)

    return cleaned


def _safe_table_name(name: str | None, fallback: str = "data") -> str:
    """把文件名/用户名转换为合法的 DuckDB 表名。"""
    if not name:
        return fallback
    # 取文件名 (去扩展名) 或直接用 name
    base = Path(name).stem if "." in name else name
    # 只保留字母数字下划线
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in base)
    safe = safe.strip("_") or fallback
    # 避免数字开头
    if safe[0].isdigit():
        safe = f"t_{safe}"
    return safe.lower()


class DuckDBManager:
    """管理一个 DuckDB 会话的连接和表注册。

    每个 ingest 调用创建一个 DuckDBManager，
    数据注册完后 .duckdb 文件路径传给沙箱。
    """

    def __init__(self, duckdb_path: str | Path | None = None):
        if duckdb_path is None:
            _, path = new_duckdb_path()
            duckdb_path = path
        self.duckdb_path = str(duckdb_path)
        self._conn: duckdb.DuckDBPyConnection = duckdb.connect(self.duckdb_path)

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ------------------------------------------------------------------
    # 表注册
    # ------------------------------------------------------------------

    def register_csv(self, table_name: str, path: str) -> None:
        """注册 CSV/TSV 文件为 DuckDB 表。DuckDB 自动推断分隔符和类型。"""
        safe_table = _safe_table_name(table_name, table_name)
        self._conn.execute(
            f'CREATE OR REPLACE TABLE "{safe_table}" AS SELECT * FROM read_csv_auto(?)',
            [path],
        )

    def register_json(self, table_name: str, path: str) -> None:
        """注册 JSON 文件为 DuckDB 表。支持嵌套 JSON 和 NDJSON。"""
        safe_table = _safe_table_name(table_name, table_name)
        self._conn.execute(
            f'CREATE OR REPLACE TABLE "{safe_table}" AS SELECT * FROM read_json_auto(?)',
            [path],
        )

    def register_parquet(self, table_name: str, path: str) -> None:
        """注册 Parquet 文件为 DuckDB 表。"""
        safe_table = _safe_table_name(table_name, table_name)
        self._conn.execute(
            f'CREATE OR REPLACE TABLE "{safe_table}" AS SELECT * FROM read_parquet(?)',
            [path],
        )

    def register_dataframe(self, table_name: str, df: pd.DataFrame) -> None:
        """注册 pandas DataFrame 为 DuckDB 表。用于 Excel/API 等需预处理的源。"""
        self._conn.register("_tmp_df", df)
        self._conn.sql(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM _tmp_df')
        self._conn.unregister("_tmp_df")

    def attach_database(self, alias: str, conn_str: str, db_type: str) -> None:
        """ATTACH 外部数据库 (PostgreSQL/MySQL/SQLite)。

        attach 后可通过 alias.table_name 跨源查询。
        """
        type_map = {
            "postgresql": "postgres",
            "mysql": "mysql",
            "sqlite": "sqlite",
        }
        duckdb_type = type_map.get(db_type.lower(), db_type.lower())
        self._conn.sql(f"""
            ATTACH IF NOT EXISTS '{conn_str}' AS {alias} (TYPE {duckdb_type})
        """)

    def register_db_table(self, table_name: str, db_alias: str, db_table: str) -> None:
        """将 ATTACH 的数据库中的表物化到本地 DuckDB 表。

        使用 CREATE TABLE AS SELECT 而非 CREATE VIEW，
        确保关闭连接后数据仍然可用 (VIEW 依赖 ATTACH，连接关闭后失效)。
        """
        self._conn.sql(f"""
            CREATE OR REPLACE TABLE "{table_name}" AS
            SELECT * FROM {db_alias}.{db_table}
        """)

    def register_view_from_sql(self, table_name: str, sql: str) -> None:
        """用自定义 SQL 创建视图 (用于数据库源的 LLM 生成 SQL 场景)。

        ⚠️ VIEW 定义若引用 ATTACH 的外部库，连接关闭/ATTACH 失效后不可查。
        跨连接持久化场景请改用 register_table_from_sql（物化）。
        """
        self._conn.sql(f'CREATE OR REPLACE VIEW "{table_name}" AS {sql}')

    def register_table_from_attached_query(self, table_name: str, db_alias: str, query: str) -> None:
        """在外部 ATTACH 库上下文执行用户 SQL，物化结果到本地持久化表。

        用户 query 可使用裸表名（自动解析到 db_alias catalog）。
        使用 CREATE TABLE AS SELECT 物化到默认 catalog，确保写连接关闭、
        ATTACH 失效后仍可被沙箱以 read_only 模式查询。

        Args:
            table_name: 目标表名（物化到默认 catalog 的 main schema）
            db_alias: ATTACH 的外部库别名
            query: 用户 SQL（裸表名，针对外部库）
        """
        default_catalog = self._conn.sql("SELECT current_catalog()").fetchone()[0]
        self._conn.sql(f"USE {db_alias}")
        try:
            self._conn.sql(f'CREATE OR REPLACE TABLE {default_catalog}.main."{table_name}" AS {query}')
        finally:
            self._conn.sql(f"USE {default_catalog}")

    # ------------------------------------------------------------------
    # 查询与元数据
    # ------------------------------------------------------------------

    def query(self, sql: str) -> pd.DataFrame:
        """执行 SQL 并返回 DataFrame。"""
        return self._conn.sql(sql).df()

    def query_arrow(self, sql: str):
        """执行 SQL 并返回 Arrow Table (大数据量时更高效)。"""
        return self._conn.sql(sql).arrow()

    def describe(self, table_name: str) -> list[dict[str, str]]:
        """获取表的 schema。返回 [{"name": "col1", "type": "VARCHAR"}, ...]"""
        result = self._conn.sql(f'DESCRIBE "{table_name}"').fetchall()
        return [{"name": row[0], "type": row[1]} for row in result]

    def count_rows(self, table_name: str) -> int:
        """获取表行数。"""
        result = self._conn.sql(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
        return result[0] if result else 0

    def preview(self, table_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """获取前 N 行数据，返回 JSON 可序列化的 list[dict]。"""
        df = self._conn.sql(f'SELECT * FROM "{table_name}" LIMIT {limit}').df()
        # 转 object 列为 str，确保 JSON 可序列化
        records = []
        for _, row in df.iterrows():
            record = {}
            for col in df.columns:
                val = row[col]
                if pd.isna(val):
                    record[col] = None
                elif isinstance(val, (pd.Timestamp,)):
                    record[col] = val.isoformat()
                else:
                    record[col] = val.item() if hasattr(val, "item") else val
            records.append(record)
        return records

    def summarize(self, table_name: str) -> dict[str, dict[str, Any]]:
        """获取列级统计信息。DuckDB SUMMARIZE 提供 min/max/mean/std 等。"""
        try:
            df = self._conn.sql(f'SUMMARIZE "{table_name}"').df()
        except Exception as e:
            logger.warning("SUMMARIZE 失败", table=table_name, error=str(e))
            return {}

        stats: dict[str, dict[str, Any]] = {}
        for _, row in df.iterrows():
            col_name = row["column_name"]
            col_stats: dict[str, Any] = {"type": row.get("column_type", "")}
            for field_name in ["min", "max", "approx_unique", "avg", "std", "q25", "q50", "q75"]:
                val = row.get(field_name)
                if pd.notna(val):
                    if hasattr(val, "item"):
                        col_stats[field_name] = val.item()
                    else:
                        col_stats[field_name] = str(val)
            stats[col_name] = col_stats
        return stats

    def list_tables(self) -> list[str]:
        """列出所有已注册的表和视图。"""
        result = self._conn.sql("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()
        return [row[0] for row in result]

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------

    def export_parquet(self, table_name: str, output_path: str | Path) -> str:
        """将表导出为 parquet 文件。返回绝对路径。"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        safe_table = _safe_table_name(table_name, table_name)
        self._conn.sql(f"""
            COPY "{safe_table}" TO '{output_path}' (FORMAT PARQUET)
        """)
        return str(output_path)

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def safe_table_name(name: str | None, fallback: str = "data") -> str:
        return _safe_table_name(name, fallback)
