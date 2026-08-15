"""对话日志持久化存储（SQLite）

以一轮对话为单位，记录用户提示词、文件路径、执行日志、图表结果。
支持前端历史对话列表查看和提示词修改重提。
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_DB_PATH = os.getenv("CONVERSATION_DB_PATH", "runtime/logs/conversations.db")


def _get_db() -> sqlite3.Connection:
    """获取数据库连接（每次调用创建新连接，线程安全）"""
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库表"""
    conn = _get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                task_id TEXT,
                user_prompt TEXT NOT NULL,
                file_paths TEXT,
                viz_mode TEXT DEFAULT 'auto',
                db_config TEXT,
                status TEXT DEFAULT 'pending',
                agent_logs TEXT,
                charts TEXT,
                html_file_paths TEXT,
                codes TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        # migration: 旧库无 codes 列时补上
        try:
            conn.execute("ALTER TABLE conversation_logs ADD COLUMN codes TEXT")
        except sqlite3.OperationalError:
            pass
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversation_id ON conversation_logs(conversation_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON conversation_logs(created_at DESC)")
        conn.commit()
    finally:
        conn.close()


def create_conversation(
    user_prompt: str,
    file_paths: list[str] | None = None,
    viz_mode: str = "auto",
    db_config: str | None = None,
    task_id: str | None = None,
) -> str:
    """创建对话记录，返回 conversation_id"""
    conv_id = uuid.uuid4().hex
    now = datetime.now().isoformat()
    conn = _get_db()
    try:
        conn.execute(
            """INSERT INTO conversation_logs
               (conversation_id, task_id, user_prompt, file_paths, viz_mode, db_config, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (conv_id, task_id, user_prompt,
             json.dumps(file_paths or [], ensure_ascii=False),
             viz_mode, db_config, now),
        )
        conn.commit()
    finally:
        conn.close()
    return conv_id


def update_conversation_status(conversation_id: str, status: str):
    """更新对话状态"""
    now = datetime.now().isoformat()
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE conversation_logs SET status = ?, updated_at = ? WHERE conversation_id = ?",
            (status, now, conversation_id),
        )
        conn.commit()
    finally:
        conn.close()


def complete_conversation(
    conversation_id: str,
    status: str,
    agent_logs: list[str] | None = None,
    charts: list[str] | None = None,
    html_file_paths: list[str] | None = None,
    codes: list[str] | None = None,
    error: str | None = None,
):
    """对话完成时更新结果"""
    now = datetime.now().isoformat()
    conn = _get_db()
    try:
        conn.execute(
            """UPDATE conversation_logs
               SET status = ?, agent_logs = ?, charts = ?, html_file_paths = ?,
                   codes = ?, error = ?, updated_at = ?
               WHERE conversation_id = ?""",
            (status,
             json.dumps(agent_logs or [], ensure_ascii=False),
             json.dumps(charts or [], ensure_ascii=False),
             json.dumps(html_file_paths or [], ensure_ascii=False),
             json.dumps(codes or [], ensure_ascii=False),
             error, now, conversation_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_conversations(limit: int = 50, offset: int = 0) -> list[dict]:
    """列出对话（按时间倒序）"""
    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT conversation_id, task_id, user_prompt, viz_mode, status,
                      created_at, updated_at,
                      length(agent_logs) as agent_logs_size,
                      length(charts) as charts_size
               FROM conversation_logs
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_conversation(conversation_id: str) -> Optional[dict]:
    """获取单个对话详情"""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM conversation_logs WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        # 解析 JSON 字段
        for field in ["file_paths", "agent_logs", "charts", "html_file_paths", "codes"]:
            if result.get(field):
                try:
                    result[field] = json.loads(result[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return result
    finally:
        conn.close()


def _safe_unlink(path) -> bool:
    """安全删除文件，失败不抛异常（不阻断删除流程）"""
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
            return True
    except Exception:
        pass
    return False


def delete_conversation(conversation_id: str) -> bool:
    """删除对话，联动删除关联的图表 HTML 和 trace 文件"""
    conv = get_conversation(conversation_id)
    if conv is None:
        return False
    # 联动删图表 HTML（html_file_paths 是完整路径列表）
    for html_path in (conv.get("html_file_paths") or []):
        _safe_unlink(html_path)
    # 联动删 trace（runtime/traces/<task_id>.json）
    task_id = conv.get("task_id")
    if task_id:
        _safe_unlink(Path("runtime/traces") / f"{task_id}.json")
    # 删 DB 行
    conn = _get_db()
    try:
        cursor = conn.execute(
            "DELETE FROM conversation_logs WHERE conversation_id = ?",
            (conversation_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def count_conversations() -> int:
    """返回对话总数"""
    conn = _get_db()
    try:
        row = conn.execute("SELECT COUNT(*) FROM conversation_logs").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def delete_oldest_conversations(n: int) -> int:
    """删除最早的 n 个对话（联动删图表+trace），返回实际删除数"""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT conversation_id FROM conversation_logs ORDER BY created_at ASC LIMIT ?",
            (n,),
        ).fetchall()
        ids = [r[0] for r in rows]
    finally:
        conn.close()
    deleted = 0
    for cid in ids:
        if delete_conversation(cid):
            deleted += 1
    return deleted


def batch_delete_conversations(conversation_ids: list[str]) -> int:
    """批量删除对话（联动删图表+trace），返回实际删除数"""
    deleted = 0
    for cid in conversation_ids:
        if delete_conversation(cid):
            deleted += 1
    return deleted


def update_prompt(conversation_id: str, new_prompt: str) -> bool:
    """修改提示词（用于重提）"""
    now = datetime.now().isoformat()
    conn = _get_db()
    try:
        cursor = conn.execute(
            "UPDATE conversation_logs SET user_prompt = ?, updated_at = ? WHERE conversation_id = ?",
            (new_prompt, now, conversation_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
