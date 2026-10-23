"""后台预热重模块，缩短首个任务的等待时间。

`service/__init__.py` 改成惰性导入后，沙箱不再为每张图付 ~30s 的 import 成本；
但进程内**第一个任务**的 worker 线程仍要首次 import pipeline（agent / RAG / torch /
chromadb），实测约 25–30 秒。启动时用守护线程预热这些模块（只 import，不建
retriever、不连 MCP），服务可立即接受请求，用户真正提交任务时通常已预热完成。

**不要**在这里加载 embedding 模型（2.4GB / 数秒）——留给第一次图表生成按需加载，
否则启动内存与冷启动时间都会明显变差。
"""
from __future__ import annotations

import os
import threading

from service.observability import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_warmup_thread: threading.Thread | None = None


def _rag_warmup_enabled() -> bool:
    """是否预加载 RAG 检索器（SERVICE_WARMUP_RAG，默认关闭）。"""
    return os.getenv("SERVICE_WARMUP_RAG", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def warm_up() -> None:
    """导入核心重模块（幂等，失败只记日志）。"""
    try:
        # pipeline / agent：langchain、torch、chromadb 等重依赖的主要来源
        import service.pipeline.service_main  # noqa: F401
        import service.pipeline.agent_pipeline  # noqa: F401
        import service.pipeline.chart_generator  # noqa: F401
        import agent.basic_agent  # noqa: F401
        import service.data_ingestion  # noqa: F401

        logger.info("core_warmup_done")
    except Exception as e:
        # 预热失败不能影响服务启动；真实任务仍会按需导入并暴露原始错误
        logger.warning("core_warmup_failed", error=str(e), error_type=type(e).__name__)
        return

    # RAG 模型约 2.4GB / 首次加载几秒。默认不预热（避免启动即占内存）；
    # 明确以图表生成为主的部署可设 SERVICE_WARMUP_RAG=1，省掉首个任务的加载等待。
    if _rag_warmup_enabled():
        try:
            import time

            started = time.perf_counter()
            from RAG.RAG_main import get_default_retriever

            retriever = get_default_retriever()
            logger.info(
                "rag_warmup_done",
                elapsed_s=round(time.perf_counter() - started, 2),
                ready=retriever is not None,
            )
        except Exception as e:
            logger.warning(
                "rag_warmup_failed",
                error=str(e),
                error_type=type(e).__name__,
            )


def start_warmup() -> threading.Thread:
    """启动（或复用）后台预热线程。"""
    global _warmup_thread
    with _lock:
        if _warmup_thread is not None and _warmup_thread.is_alive():
            return _warmup_thread
        _warmup_thread = threading.Thread(
            target=warm_up,
            name="core-warmup",
            daemon=True,
        )
        _warmup_thread.start()
        return _warmup_thread
