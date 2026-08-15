"""阶段计时监控：记录任务内每个流程阶段各自耗时，并实时推送当前阶段。

与 @trace（函数级细粒度追踪）互补，stage_timer 关注用户可感知的大阶段:
初始化 Agent -> 数据接入 -> 数据预览 -> 计划生成 -> 图表生成 ...

事件通过 ws_streamer 推送（type="stage"）:
- 开始: {"type":"stage","event":"start","stage":"ingest","label":"数据接入","ts":...}
- 结束: {"type":"stage","event":"end","stage":"ingest","label":"数据接入",
         "duration_s":1.23,"status":"success"}
- 汇总: {"type":"stage","event":"summary","stages":[...],"total_s":12.3}

用法（service_main 等编排层）:
    with stage_timer.stage(task_id, "ingest", "数据接入"):
        profile = await ingest_data_source(...)
"""

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class StageTimer:
    """按 task_id 记录阶段耗时 + 当前运行中的阶段。"""

    def __init__(self):
        # task_id -> {"current": {name,label,start}, "finished": [{name,label,duration_s,status}]}
        self._stages: dict[str, dict] = {}

    def _bucket(self, task_id: str) -> dict:
        return self._stages.setdefault(task_id, {"current": None, "finished": []})

    @contextmanager
    def stage(self, task_id: str, name: str, label: str = ""):
        """阶段上下文：进入推送 start，退出推送 end（含耗时秒数）。

        异常时 status=failed 一并推送后原样抛出，不吞错。
        task_id 为空时仅记日志，不入内存（防止泄漏）。
        """
        task_id = task_id or ""
        label = label or name
        status = "success"

        if task_id:
            self._bucket(task_id)["current"] = {
                "name": name, "label": label, "start": time.perf_counter()
            }
        self._broadcast(task_id, {
            "type": "stage", "event": "start", "task_id": task_id,
            "stage": name, "label": label,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        self._log("stage_start", task_id, name, label)

        start = time.perf_counter()
        try:
            yield
        except Exception:
            status = "failed"
            raise
        finally:
            duration_s = time.perf_counter() - start
            if task_id:
                bucket = self._bucket(task_id)
                if bucket["current"] and bucket["current"]["name"] == name:
                    bucket["current"] = None
                bucket["finished"].append({
                    "name": name, "label": label,
                    "duration_s": round(duration_s, 2), "status": status,
                })
            self._broadcast(task_id, {
                "type": "stage", "event": "end", "task_id": task_id,
                "stage": name, "label": label,
                "duration_s": round(duration_s, 2), "status": status,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            self._log("stage_end", task_id, name, label,
                      duration_s=round(duration_s, 2), status=status)

    def summary(self, task_id: str) -> dict:
        """阶段耗时汇总：各阶段列表 + 总耗时（不含未结束的当前阶段）。"""
        bucket = self._stages.get(task_id or "", {})
        stages = list(bucket.get("finished", []))
        return {
            "stages": stages,
            "total_s": round(sum(s["duration_s"] for s in stages), 2),
        }

    def flush(self, task_id: str, output_dir: str = "runtime/traces") -> dict:
        """落盘阶段耗时到 {task_id}_stages.json 并清理内存，返回汇总。"""
        data = self.summary(task_id)
        try:
            if data["stages"]:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                path = Path(output_dir) / f"{task_id}_stages.json"
                path.write_text(
                    json.dumps({"task_id": task_id, **data}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except Exception:
            pass
        self._stages.pop(task_id or "", None)
        return data

    # ── 内部 ────────────────────────────────────────────────

    @staticmethod
    def _broadcast(task_id: str, event: dict):
        if not task_id:
            return
        try:
            from .ws_streamer import ws_streamer
            ws_streamer.broadcast(task_id, event)
        except Exception:
            pass

    @staticmethod
    def _log(event: str, task_id: str, name: str, label: str, **extra):
        try:
            from service.observability import get_logger
            get_logger("monitoring").info(event, task_id=task_id,
                                          stage=name, label=label, **extra)
        except Exception:
            pass


stage_timer = StageTimer()
