"""图表沙箱执行层（从 chart_generator.py 拆出）。

职责：
- _RENDER_HEADER: monkey-patch pyecharts render 路径 + DuckDB 连接注入（环境变量驱动）
- execute_chart_code: 沙箱执行 + 环境变量 + 产物重命名兜底

读取代码（read_code）由 chart_generator 从方法库物化后拼在代码正文前，
本层只负责执行与产物校验，不感知 recipe。
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from agent_tools.sandbox import run_python_safely
from service.observability import get_logger

try:
    from pydantic import BaseModel, ConfigDict
except ImportError:
    BaseModel = None  # type: ignore
    ConfigDict = None  # type: ignore

logger = get_logger(__name__)

# 项目根（沙箱进程 extra_pythonpath，保证能 import 项目包）
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 通过 header 注入 monkey-patch pyecharts 渲染路径，
# LLM 生成代码中 chart.render(...) 的 path 会被强制重定向到
# 环境变量 CHART_OUTPUT_DIR / CHART_OUTPUT_NAME 指定的位置。
_RENDER_HEADER = '''# --- auto-injected by chart_sandbox (unified render path) ---
import os as _os
from pathlib import Path as _Path

_CHART_OUTPUT_DIR = _os.environ.get("CHART_OUTPUT_DIR", ".")
_CHART_OUTPUT_NAME = _os.environ.get("CHART_OUTPUT_NAME", "render.html")
_os.makedirs(_CHART_OUTPUT_DIR, exist_ok=True)

try:
    from pyecharts.charts.base import Base as _PyBase
    _orig_render = _PyBase.render

    def _patched_render(self, *args, **kwargs):
        target = _Path(_CHART_OUTPUT_DIR) / _CHART_OUTPUT_NAME
        # 丢弃 path 参数，统一改写为目标路径
        if args:
            args = (str(target),) + args[1:]
        else:
            kwargs["path"] = str(target)
        return _orig_render(self, *args, **kwargs)

    _PyBase.render = _patched_render
except Exception as _e:
    print(f"[chart_sandbox header] pyecharts patch skipped: {_e}")

# --- end header ---

'''


if BaseModel is not None:
    class SandboxResult(BaseModel):
        """一次沙箱执行的 outcome（统一用 Pydantic 模型）。

        支持位置参数向后兼容（继承方显式实现 __init__）。
        """
        model_config = ConfigDict(arbitrary_types_allowed=True)

        success: bool
        output: str
        chart_path: str
        chart_filename: str
        parse_seconds: float = 0.0

        def __init__(
            self,
            success: bool,
            output: str,
            chart_path: str,
            chart_filename: str,
            parse_seconds: float = 0.0,
        ) -> None:
            super().__init__(
                success=success,
                output=output,
                chart_path=chart_path,
                chart_filename=chart_filename,
                parse_seconds=parse_seconds,
            )
else:
    class SandboxResult:  # type: ignore[no-redef]
        """Pydantic 不可用时的回退实现（不推荐，结构不一致）。"""
        def __init__(self, success, output, chart_path, chart_filename, parse_seconds=0.0):
            self.success = success
            self.output = output
            self.chart_path = chart_path
            self.chart_filename = chart_filename
            self.parse_seconds = parse_seconds


def execute_chart_code(
    code_body: str,
    *,
    charts_folder: Path,
    plan_id: str,
    timeout: int = 60,
) -> SandboxResult:
    """沙箱执行图表代码并做产物校验/重命名兜底。

    Args:
        code_body: 已完成 series 注入的代码正文（不含 _RENDER_HEADER）
        charts_folder: HTML 输出目录
        plan_id: 计划ID（产物命名）
        timeout: 沙箱超时秒数

    Returns:
        SandboxResult（success 含产物存在且非空校验）
    """
    attempt_start_ts = time.time()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chart_filename = f"chart_{plan_id}_{timestamp}.html"
    # 绝对路径，避免 subprocess cwd 与相对 CHART_OUTPUT_DIR 叠加导致嵌套目录
    charts_folder_abs = str(Path(charts_folder).resolve())

    modified_code = _RENDER_HEADER + code_body
    run_env = dict(os.environ)
    run_env["CHART_OUTPUT_DIR"] = charts_folder_abs
    run_env["CHART_OUTPUT_NAME"] = chart_filename

    try:
        proc = run_python_safely(
            modified_code,
            cwd=str(charts_folder),
            timeout=timeout,
            env=run_env,
            extra_pythonpath=str(PROJECT_ROOT),
        )
        if proc.success:
            output = proc.stdout
            logger.info("沙箱执行成功", output=output)
        else:
            output = f"Error: {proc.error}" if proc.error else f"Error:\nStderr: {proc.stderr}\nStdout: {proc.stdout}"
            logger.warning("沙箱执行失败", output=output)
            return SandboxResult(False, output, "", chart_filename)
    except Exception as e:
        import traceback
        output = f"Exception: {traceback.format_exc()}"
        logger.warning("沙箱执行异常", output=output)
        return SandboxResult(False, output, "", chart_filename)

    chart_path = str(charts_folder / chart_filename)
    if not Path(chart_path).exists():
        # 兜底：LLM 未走 patched render 时，取本轮新增的第一个 html 重命名
        new_files = [
            p for p in charts_folder.glob("*.html")
            if p.stat().st_mtime >= attempt_start_ts and p.name != chart_filename
        ]
        if new_files:
            fallback = sorted(new_files, key=lambda p: p.stat().st_mtime)[-1]
            try:
                fallback.rename(charts_folder / chart_filename)
                logger.info("兜底重命名", fallback=fallback.name, target=chart_filename)
            except OSError as move_err:
                chart_path = str(fallback)
                logger.warning("兜底重命名失败，使用原路径", chart_path=chart_path, error=str(move_err))

    # 最终校验：HTML 必须真实存在且非空
    if not Path(chart_path).exists() or Path(chart_path).stat().st_size == 0:
        return SandboxResult(
            False, f"{output}\nHTML 未生成或为空（{chart_path}，代码可能未调用 render）",
            chart_path, chart_filename,
        )
    return SandboxResult(True, output, chart_path, chart_filename)
