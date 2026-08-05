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
from service.conversation_store import update_conversation_status, complete_conversation


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
                from service.service_main import service_main
                from Entity import GenerateChartWithPromptResponse
                clear_cancel(task_id)
                result = loop.run_until_complete(service_main(request_model, task_id=task_id))

                charts = [item["chart_path"] for item in result.get("successful_charts", [])]
                chart_types = [item["plan"].get("chart_type", "unknown") for item in result.get("successful_charts", [])]
                agent_logs = result.get("agent_logs", [])
                response = GenerateChartWithPromptResponse(
                    Charts=chart_types,
                    HtmlFilePaths=charts,
                    AgentLogs=agent_logs,
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
                if loop:
                    loop.close()
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
