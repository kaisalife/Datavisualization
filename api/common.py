"""
API 共享依赖

app.py 全局状态（_tasks/_executor/_UPLOAD_DIR/_CHARTS_DIR）
通过 init_app 注入到 Blueprint，避免蓝图直接引用 app.py 全局变量。
"""
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import request, jsonify, current_app
from Entity import ErrorResponse
from service.observability import get_logger as _get_struct_logger
from service.runtime.conversation_store import update_conversation_status, complete_conversation


_logger = _get_struct_logger("api.common")


# WebSocket 连接池：task_id -> set of ws connections
_ws_connections: dict[str, set] = {}


def register_ws_connection(task_id: str, ws):
    """注册 WebSocket 连接"""
    if task_id not in _ws_connections:
        _ws_connections[task_id] = set()
    _ws_connections[task_id].add(ws)


def unregister_ws_connection(task_id: str, ws):
    """注销 WebSocket 连接"""
    if task_id in _ws_connections:
        _ws_connections[task_id].discard(ws)
        if not _ws_connections[task_id]:
            del _ws_connections[task_id]


def notify_task_complete(task_id: str, data: dict):
    """通知所有监听该 task_id 的 WebSocket 连接"""
    if task_id in _ws_connections:
        msg = json.dumps(data, ensure_ascii=False)
        for ws in list(_ws_connections[task_id]):
            try:
                ws.send(msg)
            except Exception:
                _ws_connections[task_id].discard(ws)


def init_app(app, executor, tasks, tasks_lock, upload_dir, charts_dir, service_api_key, logger):
    """把 app.py 的全局依赖注入到 flask 应用上下文，供各蓝图取用。"""
    app.config["_EXECUTOR"] = executor
    app.config["_TASKS"] = tasks
    app.config["_TASKS_LOCK"] = tasks_lock
    app.config["_UPLOAD_DIR"] = upload_dir
    app.config["_CHARTS_DIR"] = charts_dir
    app.config["_SERVICE_API_KEY"] = service_api_key
    app.config["_LOGGER"] = logger


def get_executor():
    return current_app.config["_EXECUTOR"]


def get_tasks():
    return current_app.config["_TASKS"]


def get_tasks_lock():
    return current_app.config["_TASKS_LOCK"]


def get_upload_dir() -> Path:
    return current_app.config["_UPLOAD_DIR"]


def get_charts_dir() -> Path:
    return current_app.config["_CHARTS_DIR"]


def get_logger():
    return current_app.config["_LOGGER"]


def monitor_response(label: str = ""):
    """API 响应监控装饰器。

    自动计时 Flask 路由函数的完整执行 (含 model_dump + jsonify 序列化)，
    记录到结构化日志。超过 10ms 时打印 [SLOW] 警告。

    用法:
        @monitor_response("chart_api:generate")
        def generate_chart_with_prompt():
            return jsonify(ErrorResponse(detail="err").model_dump()), 400
    """
    import functools

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            status_code = 200
            try:
                result = func(*args, **kwargs)
                # 提取状态码 (Flask 返回 (response, status) 或直接 response)
                if isinstance(result, tuple) and len(result) >= 2:
                    status_code = result[1]
                return result
            finally:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                try:
                    logger = get_logger()
                    if elapsed_ms > 10:
                        logger.warning(
                            "api_response_slow",
                            label=label,
                            func=func.__name__,
                            status=status_code,
                            elapsed_ms=round(elapsed_ms, 3),
                            threshold_ms=10,
                        )
                    else:
                        logger.debug(
                            "api_response",
                            label=label,
                            func=func.__name__,
                            status=status_code,
                            elapsed_ms=round(elapsed_ms, 3),
                        )
                except Exception:
                    pass

        return wrapper

    return decorator


def check_api_key():
    """统一的 API Key 校验。"""
    key = current_app.config["_SERVICE_API_KEY"]
    if not key:
        return None
    provided = request.headers.get("X-API-Key") or request.form.get("api_key")
    if provided != key:
        return jsonify(ErrorResponse(detail="Invalid or missing API key").model_dump()), 401
    return None


# 取消任务集合
_cancelled_tasks: set[str] = set()
_cancel_lock = threading.Lock()


def request_cancel(task_id: str):
    """请求取消任务"""
    with _cancel_lock:
        _cancelled_tasks.add(task_id)


def is_cancelled(task_id: str) -> bool:
    """检查任务是否已被取消"""
    with _cancel_lock:
        return task_id in _cancelled_tasks


def clear_cancel(task_id: str):
    """清除取消标志"""
    with _cancel_lock:
        _cancelled_tasks.discard(task_id)


# 终态：不再变化的任务状态
_TERMINAL_STATUSES = {"success", "failed", "cancelled"}
_ACTIVE_STATUSES = {"pending", "running"}


def shutdown_event_loop(loop) -> None:
    """关闭任务专用事件循环：取消未完成任务、清理异步生成器后再 close。

    ThreadPoolExecutor 会复用线程：不清理就 close 会留下
    "Task was destroyed but it is pending"，httpx 连接池也可能在循环关闭后
    才做清理（表现为 Event loop is closed）；关闭后把线程的当前循环置空。
    """
    import asyncio

    if loop is None:
        return
    try:
        if not loop.is_closed():
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
    except Exception:
        pass
    finally:
        try:
            if not loop.is_closed():
                loop.close()
        except Exception:
            pass
        try:
            asyncio.set_event_loop(None)
        except Exception:
            pass


def active_task_count(tasks=None) -> int:
    """进行中/排队任务数（pending + running）。"""
    tasks = get_tasks() if tasks is None else tasks
    with get_tasks_lock():
        return sum(
            1 for task in tasks.values()
            if str(task.get("status") or "") in _ACTIVE_STATUSES
        )


def ensure_queue_capacity():
    """任务队列过载保护：超过 TASK_QUEUE_LIMIT 时返回 429 响应，否则 None。

    ThreadPoolExecutor 的等待队列默认无界，短时间提交大量任务会无限堆积
    （每个任务都要打多轮 LLM）。上限按 pending+running 计算；设为 0 表示不限制。
    """
    limit = _env_int("TASK_QUEUE_LIMIT", 20)
    if limit <= 0:
        return None
    active = active_task_count()
    if active < limit:
        return None
    return (
        jsonify(
            ErrorResponse(
                detail=(
                    f"服务繁忙：当前排队/进行中任务 {active} 个，已达上限 {limit}；"
                    "请等待现有任务完成或调大 TASK_QUEUE_LIMIT"
                )
            ).model_dump()
        ),
        429,
    )


def record_task_metrics_safely(
    *,
    task_id: str,
    started_at: float,
    model: str,
    charts: int,
    failed_plans: int,
    tasks: dict,
    lock,
    stage_summary: dict | None = None,
) -> None:
    """把任务耗时/状态/阶段写入指标文件（旁路能力，任何异常都不外抛）。"""
    try:
        from service.runtime.task_metrics import record_task_metrics

        with lock:
            status = str((tasks.get(task_id) or {}).get("status") or "unknown")
        record_task_metrics(
            task_id=task_id,
            status=status,
            duration_s=time.time() - started_at,
            model=model,
            charts=charts,
            failed_plans=failed_plans,
            stages=(stage_summary or {}).get("stages") or [],
        )
    except Exception:
        pass


def _env_int(name: str, default: int) -> int:
    """读取非负整数环境变量，非法值回退默认。"""
    try:
        value = int(os.getenv(name, str(default)))
        return value if value >= 0 else default
    except (TypeError, ValueError):
        return default


def _task_timestamp(task: dict) -> float | None:
    """解析 created_at（ISO 字符串）为 epoch 秒；解析失败返回 None。"""
    raw = task.get("created_at")
    if not raw:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(raw)).timestamp()
    except (TypeError, ValueError):
        return None


def prune_tasks(tasks=None, lock=None, retention_seconds=None, max_entries=None) -> int:
    """清理已完成任务，防止服务长期运行时任务表无限增长。

    只淘汰终态任务（success/failed/cancelled）：
    1. created_at 早于 TASK_RETENTION_SECONDS（默认 3600 秒）
    2. 总数超过 TASK_MAX_ENTRIES（默认 500）时，按 created_at 从旧到新淘汰

    进行中的任务永不清理。清理同时会清掉对应的取消标志。

    Args:
        tasks: 任务字典，默认取 current_app 注入的
        lock: 任务锁，默认取 current_app 注入的
        retention_seconds: 保留秒数，None 时读 TASK_RETENTION_SECONDS
        max_entries: 任务数上限，None 时读 TASK_MAX_ENTRIES

    Returns:
        被清理的任务数
    """
    tasks = get_tasks() if tasks is None else tasks
    lock = get_tasks_lock() if lock is None else lock
    retention = _env_int("TASK_RETENTION_SECONDS", 3600) if retention_seconds is None else retention_seconds
    limit = _env_int("TASK_MAX_ENTRIES", 500) if max_entries is None else max_entries

    now = time.time()
    removed: list[str] = []

    with lock:
        for tid, task in tasks.items():
            if task.get("status") not in _TERMINAL_STATUSES:
                continue
            ts = _task_timestamp(task)
            if ts is not None and now - ts >= retention:
                removed.append(tid)

        overflow = (len(tasks) - len(removed)) - limit
        if overflow > 0:
            candidates = sorted(
                (_task_timestamp(t) or 0.0, tid)
                for tid, t in tasks.items()
                if t.get("status") in _TERMINAL_STATUSES and tid not in removed
            )
            removed.extend(tid for _, tid in candidates[:overflow])

        for tid in removed:
            tasks.pop(tid, None)

    for tid in removed:
        clear_cancel(tid)

    if removed:
        _logger.info("tasks_pruned", count=len(removed))
    return len(removed)


def _run_service_main_in_executor(app, task_id, request_model, conversation_id=None):
    """
    在 executor 线程里跑 service_main（和原 app.py 行为一致）。

    由于 ThreadPoolExecutor 线程和请求线程是不同的 asyncio 事件循环，
    这里自己 new_event_loop 并 set_event_loop。

    注意：线程池中没有 Flask 应用上下文，必须通过 app.app_context() 手动推入，
    否则 get_tasks()/get_tasks_lock()/get_logger() 等依赖 current_app 的函数会报 RuntimeError。
    """
    with app.app_context():
        from service.monitoring import TraceContext, trace_store, error_monitor, ws_streamer

        with TraceContext(task_id=task_id, conversation_id=conversation_id or ""):
            tasks = get_tasks()
            lock = get_tasks_lock()
            logger = get_logger()
            started_at = time.time()
            charts: list[str] = []
            failed_count = 0

            with lock:
                if task_id not in tasks:
                    return
                tasks[task_id].update(status="running")

            if conversation_id:
                update_conversation_status(conversation_id, "running")

            logger.info("task_start", task_id=task_id, model=request_model.model_type)
            loop = None
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                from service.pipeline.service_main import service_main
                from Entity import GenerateChartWithPromptResponse
                clear_cancel(task_id)
                result = loop.run_until_complete(service_main(request_model, task_id=task_id))

                charts = [item["chart_path"] for item in result.get("successful_charts", [])]
                chart_types = [item["plan"].get("chart_type", "unknown") for item in result.get("successful_charts", [])]
                codes = [item.get("code", "") for item in result.get("successful_charts", [])]
                failed_count = len(result.get("failed_plans", []))
                agent_logs = result.get("agent_logs", [])
                response = GenerateChartWithPromptResponse(
                    Charts=chart_types,
                    HtmlFilePaths=charts,
                    AgentLogs=agent_logs,
                    Codes=codes,
                    ContextCards=result.get("context_cards", []),
                )
                if is_cancelled(task_id):
                    with lock:
                        tasks[task_id].update(status="cancelled", error="Cancelled by user")
                    logger.info("task_cancelled", task_id=task_id)
                    notify_task_complete(task_id, {
                        "status": "cancelled",
                        "error": "Cancelled by user",
                    })
                    return
                with lock:
                    tasks[task_id].update(
                        status="success",
                        result=response.model_dump(),
                        raw={
                            "successful_charts": result.get("successful_charts", []),
                            "failed_plans": result.get("failed_plans", []),
                        },
                    )
                if conversation_id:
                    complete_conversation(
                        conversation_id, "success",
                        agent_logs=agent_logs,
                        charts=chart_types,
                        html_file_paths=charts,
                        codes=codes,
                        context_cards=result.get("context_cards", []),
                    )
                logger.info("task_success", task_id=task_id,
                            charts_count=len(charts), failed_count=len(result.get("failed_plans", [])))
                notify_task_complete(task_id, {
                    "status": "success",
                    "result": response.model_dump(),
                    "agent_logs": agent_logs,
                })
            except Exception as e:
                if is_cancelled(task_id):
                    with lock:
                        tasks[task_id].update(status="cancelled", error="Cancelled by user")
                    if conversation_id:
                        complete_conversation(conversation_id, "cancelled", error="Cancelled by user")
                    logger.info("task_cancelled", task_id=task_id)
                    notify_task_complete(task_id, {
                        "status": "cancelled",
                        "error": "Cancelled by user",
                    })
                else:
                    with lock:
                        tasks[task_id].update(status="failed", error=f"{type(e).__name__}: {e}")
                    if conversation_id:
                        complete_conversation(conversation_id, "failed", error=f"{type(e).__name__}: {e}")
                    logger.error("task_failed", task_id=task_id, error=str(e), error_type=type(e).__name__)
                    notify_task_complete(task_id, {
                        "status": "failed",
                        "error": f"{type(e).__name__}: {e}",
                    })
            finally:
                shutdown_event_loop(loop)
                # 错误汇总 + trace 落盘
                try:
                    err_summary = error_monitor.get_summary(task_id)
                    if err_summary.get("total_errors", 0) > 0:
                        ws_streamer.broadcast(task_id, {
                            "type": "error_summary",
                            "task_id": task_id,
                            **err_summary,
                        })
                except Exception:
                    pass
                try:
                    trace_store.flush(task_id)
                except Exception:
                    pass
                # 阶段耗时汇总推送 + 落盘清理
                stage_summary: dict = {}
                try:
                    from service.monitoring import stage_timer
                    stage_summary = stage_timer.flush(task_id)
                    if stage_summary.get("stages"):
                        ws_streamer.broadcast(task_id, {
                            "type": "stage", "event": "summary",
                            "task_id": task_id, **stage_summary,
                        })
                except Exception:
                    pass
                # 任务级指标（成功率/耗时分位/慢任务/阶段瓶颈）
                record_task_metrics_safely(
                    task_id=task_id,
                    started_at=started_at,
                    model=request_model.model_type,
                    charts=len(charts),
                    failed_plans=failed_count,
                    tasks=tasks,
                    lock=lock,
                    stage_summary=stage_summary,
                )


def _run_optimize_in_executor(app, task_id, request_model, conversation_id=None):
    """
    在 executor 线程里跑单图优化（optimize_chart_main），与 _run_service_main_in_executor 同构。

    流程与产物契约完全对齐：任务状态机 / TraceContext / WS 推送 / 对话日志，
    只是编排函数换成 chart 优化（不重跑数据接入与规划）。
    """
    with app.app_context():
        from service.monitoring import TraceContext, trace_store, error_monitor, ws_streamer

        with TraceContext(task_id=task_id, conversation_id=conversation_id or ""):
            tasks = get_tasks()
            lock = get_tasks_lock()
            logger = get_logger()
            started_at = time.time()
            charts: list[str] = []
            failed_count = 0

            with lock:
                if task_id not in tasks:
                    return
                tasks[task_id].update(status="running")

            if conversation_id:
                update_conversation_status(conversation_id, "running")

            logger.info("optimize_task_start", task_id=task_id, chart_id=request_model.chart_id)
            loop = None
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                from service.pipeline.optimize_flow import optimize_chart_main
                from Entity import GenerateChartWithPromptResponse
                clear_cancel(task_id)
                result = loop.run_until_complete(
                    optimize_chart_main(request_model, task_id=task_id)
                )

                charts = [item["chart_path"] for item in result.get("successful_charts", [])]
                chart_types = [
                    item["plan"].get("chart_type", "unknown")
                    for item in result.get("successful_charts", [])
                ]
                codes = [item.get("code", "") for item in result.get("successful_charts", [])]
                agent_logs = result.get("agent_logs", [])
                response = GenerateChartWithPromptResponse(
                    Charts=chart_types,
                    HtmlFilePaths=charts,
                    AgentLogs=agent_logs,
                    Codes=codes,
                    ContextCards=[],
                )
                if is_cancelled(task_id):
                    with lock:
                        tasks[task_id].update(status="cancelled", error="Cancelled by user")
                    logger.info("optimize_task_cancelled", task_id=task_id)
                    notify_task_complete(task_id, {
                        "status": "cancelled",
                        "error": "Cancelled by user",
                    })
                    return
                # 优化跑完但没产出新版本也算 failed（前端需要明确信号）
                final_status = "success" if charts else "failed"
                final_error = "" if charts else "图表优化未产出新版本"
                with lock:
                    tasks[task_id].update(
                        status=final_status,
                        result=response.model_dump(),
                        raw={
                            "successful_charts": result.get("successful_charts", []),
                            "failed_plans": result.get("failed_plans", []),
                        },
                        error=final_error,
                    )
                if conversation_id:
                    complete_conversation(
                        conversation_id, final_status,
                        agent_logs=agent_logs,
                        charts=chart_types,
                        html_file_paths=charts,
                        codes=codes,
                        error=final_error,
                    )
                logger.info(
                    "optimize_task_success", task_id=task_id,
                    charts_count=len(charts), status=final_status,
                )
                notify_task_complete(task_id, {
                    "status": final_status,
                    "result": response.model_dump(),
                    "agent_logs": agent_logs,
                    "error": final_error,
                })
            except Exception as e:
                if is_cancelled(task_id):
                    with lock:
                        tasks[task_id].update(status="cancelled", error="Cancelled by user")
                    if conversation_id:
                        complete_conversation(conversation_id, "cancelled", error="Cancelled by user")
                    logger.info("optimize_task_cancelled", task_id=task_id)
                    notify_task_complete(task_id, {
                        "status": "cancelled",
                        "error": "Cancelled by user",
                    })
                else:
                    with lock:
                        tasks[task_id].update(status="failed", error=f"{type(e).__name__}: {e}")
                    if conversation_id:
                        complete_conversation(conversation_id, "failed", error=f"{type(e).__name__}: {e}")
                    logger.error(
                        "optimize_task_failed", task_id=task_id,
                        error=str(e), error_type=type(e).__name__,
                    )
                    notify_task_complete(task_id, {
                        "status": "failed",
                        "error": f"{type(e).__name__}: {e}",
                    })
            finally:
                shutdown_event_loop(loop)
                # 错误汇总 + trace 落盘
                try:
                    err_summary = error_monitor.get_summary(task_id)
                    if err_summary.get("total_errors", 0) > 0:
                        ws_streamer.broadcast(task_id, {
                            "type": "error_summary",
                            "task_id": task_id,
                            **err_summary,
                        })
                except Exception:
                    pass
                try:
                    trace_store.flush(task_id)
                except Exception:
                    pass
                # 阶段耗时汇总推送 + 落盘清理
                stage_summary: dict = {}
                try:
                    from service.monitoring import stage_timer
                    stage_summary = stage_timer.flush(task_id)
                    if stage_summary.get("stages"):
                        ws_streamer.broadcast(task_id, {
                            "type": "stage", "event": "summary",
                            "task_id": task_id, **stage_summary,
                        })
                except Exception:
                    pass
                # 任务级指标（成功率/耗时分位/慢任务/阶段瓶颈）
                record_task_metrics_safely(
                    task_id=task_id,
                    started_at=started_at,
                    model=request_model.model_type,
                    charts=len(charts),
                    failed_plans=failed_count,
                    tasks=tasks,
                    lock=lock,
                    stage_summary=stage_summary,
                )
