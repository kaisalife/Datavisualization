"""内存 trace 存储，按 task_id 组织，任务结束后落盘。"""

import json
from collections import defaultdict
from pathlib import Path


class TraceStore:
    """按 task_id 存储内存 trace + errors + tokens，任务结束后落盘。

    单任务上限 MAX_EVENTS_PER_TASK 条事件，防止内存膨胀。
    """

    MAX_EVENTS_PER_TASK = 2000

    def __init__(self):
        self._store: dict[str, list] = defaultdict(list)
        self._errors: dict[str, list] = defaultdict(list)
        self._tokens: dict[str, dict] = {}

    # ── trace 事件 ──────────────────────────────────────────

    def append(self, task_id: str, event: dict):
        """追加一条 trace 事件。"""
        if task_id and len(self._store[task_id]) < self.MAX_EVENTS_PER_TASK:
            self._store[task_id].append(event)

    def get_traces(self, task_id: str) -> list:
        return self._store.get(task_id, [])

    # ── 错误事件 ────────────────────────────────────────────

    def append_error(self, task_id: str, event: dict):
        """追加一条错误事件。"""
        if task_id:
            self._errors[task_id].append(event)

    def get_errors(self, task_id: str) -> list:
        return self._errors.get(task_id, [])

    # ── token 汇总 ──────────────────────────────────────────

    def add_tokens(self, task_id: str, usage: dict):
        """累加 token 用量。"""
        if not task_id:
            return
        t = self._tokens.setdefault(
            task_id,
            {
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_tokens": 0,
                "call_count": 0,
                "calls": [],
            },
        )
        t["total_prompt_tokens"] += usage.get("prompt_tokens", 0)
        t["total_completion_tokens"] += usage.get("completion_tokens", 0)
        t["total_tokens"] += usage.get("total_tokens", 0)
        t["call_count"] += 1
        t["calls"].append(usage)

    def get_tokens(self, task_id: str) -> dict:
        return self._tokens.get(task_id, {})

    # ── 落盘 + 清理 ─────────────────────────────────────────

    def flush(self, task_id: str, output_dir: str = "runtime/traces"):
        """任务结束后落盘到 JSON 文件，然后清理内存。"""
        if task_id not in self._store and task_id not in self._errors:
            return

        try:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            data = {
                "task_id": task_id,
                "traces": self._store.get(task_id, []),
                "errors": self._errors.get(task_id, []),
                "tokens": self._tokens.get(task_id, {}),
            }
            path = Path(output_dir) / f"{task_id}.json"
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

        # 清理内存
        self._store.pop(task_id, None)
        self._errors.pop(task_id, None)
        self._tokens.pop(task_id, None)


trace_store = TraceStore()
