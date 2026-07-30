"""
Flask 应用入口

⚠️ 所有接口路由已按模块拆分到 `api/` 目录：
- api/chart_api.py      POST /api/generate-chart-with-prompt  GET /api/chart/<chart_id>
- api/task_api.py       GET /api/task/<task_id>
- api/code_api.py       POST /api/complete-viz-code
- api/common.py         共享依赖（_executor/_tasks 等）、API Key 校验
"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from flask_sock import Sock

from Entity import ErrorResponse
from service.exceptions import ConfigError, ServiceError
from service.observability.logger import configure_logging, get_logger
from service.conversation_store import init_db

load_dotenv()

_LOG_PATH = os.getenv("LOG_PATH", "logs/datavisual.jsonl")
configure_logging(log_path=_LOG_PATH, level=os.getenv("LOG_LEVEL", "INFO"))
_logger = get_logger("app")

app = Flask(__name__)
CORS(app)
sock = Sock(app)

_PROJECT_ROOT = Path(__file__).resolve().parent
_DEFAULT_UPLOAD_DIR = _PROJECT_ROOT / "temp_uploads"
_DEFAULT_CHARTS_DIR = _PROJECT_ROOT / "charts"

app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", str(50 * 1024 * 1024)))

_UPLOAD_DIR = Path(os.getenv("TEMP_UPLOAD_DIR", "")) if os.getenv("TEMP_UPLOAD_DIR", "") else _DEFAULT_UPLOAD_DIR
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_CHARTS_DIR = Path(os.getenv("CHARTS_DIR", "")) if os.getenv("CHARTS_DIR", "") else _DEFAULT_CHARTS_DIR
_CHARTS_DIR.mkdir(parents=True, exist_ok=True)

_SERVICE_API_KEY = os.getenv("SERVICE_API_KEY", "")

_executor = ThreadPoolExecutor(max_workers=int(os.getenv("TASK_MAX_WORKERS", "2")))
_tasks = {}
_tasks_lock = threading.Lock()


# ========== 全局错误处理器 ==========
@app.errorhandler(ConfigError)
def handle_config_error(e):
    return jsonify(ErrorResponse(detail=str(e)).dict()), 500


@app.errorhandler(ServiceError)
def handle_service_error(e):
    _logger.error("service_error", error=str(e), error_type=type(e).__name__)
    return jsonify(ErrorResponse(detail=str(e)).dict()), 500


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    _logger.error("unexpected_error", error=str(e), error_type=type(e).__name__)
    return jsonify(ErrorResponse(detail=f"内部错误: {type(e).__name__}: {e}").dict()), 500


# ========== 注入共享依赖到蓝图 ==========
from api.common import init_app as init_api_deps
init_api_deps(
    app=app,
    executor=_executor,
    tasks=_tasks,
    tasks_lock=_tasks_lock,
    upload_dir=_UPLOAD_DIR,
    charts_dir=_CHARTS_DIR,
    service_api_key=_SERVICE_API_KEY,
    logger=_logger,
)

# ========== 初始化对话日志数据库 ==========
init_db()

# ========== 注册蓝图 ==========
from api import chart_bp, task_bp, code_bp
from api.conversation_api import bp as conversation_bp
app.register_blueprint(chart_bp)
app.register_blueprint(task_bp)
app.register_blueprint(code_bp)
app.register_blueprint(conversation_bp)

# ========== WebSocket 端点 ==========
from api.common import register_ws_connection, unregister_ws_connection


@sock.route("/ws/task/<task_id>")
def ws_task(ws, task_id: str):
    """WebSocket 端点：前端连接后等待任务完成通知"""
    register_ws_connection(task_id, ws)
    try:
        while ws.connected:
            time.sleep(0.5)
    finally:
        unregister_ws_connection(task_id, ws)


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host=host, port=port, debug=debug)
