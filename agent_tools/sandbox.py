"""沙箱化代码执行。

LLM 生成的 Python 代码不能直接在宿主机跑。
通过 AST 扫描禁止危险调用 + subprocess 隔离执行。
"""

import ast
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class RunResult:
    """代码执行结果。"""
    success: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    error: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False


# 沙箱输出上限：LLM 代码里一个失控的 print 循环会在 timeout 前把内存吃光。
# 默认保留末尾 512KB（错误堆栈和 __CHART_DATA_STATS__ 都在尾部）。
_DEFAULT_MAX_CAPTURE_BYTES = 512 * 1024
_MAX_CAPTURE_CEILING = 16 * 1024 * 1024

# 生成代码不需要任何凭证；子进程继承宿主环境时把这些变量剔除，
# 避免代码 print(os.environ) / 异常栈把 API Key 带进日志与调试反馈。
_SENSITIVE_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")
_SENSITIVE_ENV_NAMES = frozenset({"LLM_EXTRA_HEADERS"})


def _sanitize_env(env: dict) -> dict:
    """剔除凭证类环境变量（保留 PATH/PYTHONPATH/CHART_OUTPUT_* 等运行必需项）。"""
    cleaned = {}
    for name, value in env.items():
        upper = str(name).upper()
        if upper in _SENSITIVE_ENV_NAMES:
            continue
        if any(hint in upper for hint in _SENSITIVE_ENV_HINTS):
            continue
        cleaned[name] = value
    return cleaned


def _max_capture_bytes() -> int:
    try:
        value = int(os.getenv("SANDBOX_MAX_OUTPUT_BYTES", str(_DEFAULT_MAX_CAPTURE_BYTES)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_CAPTURE_BYTES
    return max(1024, min(value, _MAX_CAPTURE_CEILING))


def _read_capture(handle, label: str) -> tuple[str, bool]:
    """从临时文件读取输出，超过上限时只保留末尾一段（错误/统计标记在尾部）。"""
    handle.flush()
    size = handle.seek(0, os.SEEK_END)
    limit = _max_capture_bytes()
    handle.seek(max(0, size - limit))
    text = handle.read().decode("utf-8", errors="replace")
    if size > limit:
        text = (
            f"[沙箱 {label} 过长已截断：原 {size} 字节，仅保留末尾 {limit} 字节]\n" + text
        )
        return text, True
    return text, False


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """超时终止整棵进程树（Windows 的子进程不会随父进程一起退出）。"""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
            )
            return
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


DANGEROUS_CALLS = frozenset({
    "os.system", "os.popen",
    "os.execl", "os.execle", "os.execlp", "os.execlpe",
    "os.execv", "os.execve", "os.execvp", "os.execvpe",
    "os.spawnl", "os.spawnle", "os.spawnlp", "os.spawnlpe",
    "os.spawnv", "os.spawnve", "os.spawnvp", "os.spawnvpe",
    "os.fork", "os.forkpty",
    "subprocess.Popen", "subprocess.run", "subprocess.call",
    "subprocess.check_output", "subprocess.check_call",
    "shutil.rmtree", "shutil.move",
    "eval", "exec", "compile",
    "__import__",
    "pickle.loads", "pickle.load",
    "webbrowser.open",
})

DANGEROUS_MODULES = frozenset({
    "socket", "ctypes", "webbrowser", "http.server",
    "multiprocessing", "signal", "pty", "commands",
})

DANGEROUS_ATTR_CHAINS = frozenset({
    "os.system", "os.popen",
    "os.execl", "os.execle", "os.execlp", "os.execlpe",
    "os.execv", "os.execve", "os.execvp", "os.execvpe",
    "os.spawnl", "os.spawnle", "os.spawnlp", "os.spawnlpe",
    "os.spawnv", "os.spawnve", "os.spawnvp", "os.spawnvpe",
    "os.fork", "os.forkpty",
    "subprocess.Popen", "subprocess.run", "subprocess.call",
    "subprocess.check_output", "subprocess.check_call",
    "shutil.rmtree", "shutil.move",
    "pickle.loads", "pickle.load",
    "webbrowser.open",
})


def _get_attr_chain(node: ast.AST) -> str:
    """获取属性访问链，如 os.system -> 'os.system'。"""
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    parts.reverse()
    return ".".join(parts)


def scan_dangerous_code(code: str) -> List[str]:
    """AST 扫描代码，返回检测到的危险调用列表。

    检测：
    - import 危险模块（socket, ctypes, webbrowser, http.server 等）
    - from module import * 危险模块
    - 函数调用 os.system, subprocess.Popen, eval, exec 等
    - 属性访问链 os.system 等
    """
    dangers = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"语法错误: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_module = alias.name.split(".")[0]
                if root_module in DANGEROUS_MODULES:
                    dangers.append(f"禁止导入模块: {alias.name}")

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_module = node.module.split(".")[0]
                if root_module in DANGEROUS_MODULES:
                    dangers.append(f"禁止从模块导入: {node.module}")

        elif isinstance(node, ast.Call):
            chain = _get_attr_chain(node.func)
            if chain in DANGEROUS_ATTR_CHAINS:
                dangers.append(f"禁止调用: {chain}")
            elif isinstance(node.func, ast.Name) and node.func.id in DANGEROUS_CALLS:
                dangers.append(f"禁止调用函数: {node.func.id}")

    return dangers


def run_python_safely(
    code: str,
    cwd: Optional[str] = None,
    timeout: int = 60,
    env: Optional[dict] = None,
    extra_pythonpath: Optional[str] = None,
) -> RunResult:
    """安全执行 Python 代码。

    1. AST 扫描拦截危险调用
    2. 写临时文件
    3. subprocess.Popen（cwd=tmpdir 或指定目录；超时杀整棵进程树；
       输出写临时文件并限制保留长度，避免失控 print 吃内存）
    4. 返回 RunResult（stdout/stderr 只保留末尾一段，凭证类环境变量已剔除）

    Args:
        code: 要执行的 Python 代码
        cwd: 工作目录（None 则用临时目录）
        timeout: 超时秒数
        env: 环境变量（None 则继承宿主）
        extra_pythonpath: 额外 PYTHONPATH
    """
    dangers = scan_dangerous_code(code)
    if dangers:
        danger_msg = "; ".join(dangers)
        return RunResult(
            success=False,
            returncode=-1,
            error=f"安全检查失败: {danger_msg}",
        )

    run_env = _sanitize_env(dict(env) if env else dict(os.environ))
    # 子进程 stdout 默认跟随系统 locale（Windows 常是 GBK），父进程按 UTF-8 解码，
    # 中文日志/图表数据摘要会变成替换字符。统一让沙箱解释器用 UTF-8 输出。
    run_env["PYTHONIOENCODING"] = "utf-8"
    run_env["PYTHONUTF8"] = "1"
    if extra_pythonpath:
        existing = run_env.get("PYTHONPATH", "")
        run_env["PYTHONPATH"] = f"{extra_pythonpath}{os.pathsep}{existing}" if existing else extra_pythonpath

    use_temp_dir = cwd is None
    if use_temp_dir:
        tmp_dir = tempfile.mkdtemp(prefix="sandbox_")
        run_cwd = tmp_dir
    else:
        run_cwd = str(cwd)
        Path(run_cwd).mkdir(parents=True, exist_ok=True)

    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8", dir=run_cwd
        ) as f:
            f.write(code)
            temp_file = f.name

        # 用临时文件接 stdout/stderr（而不是 capture_output 管道）：
        # 管道 + communicate() 会把全部输出先读进内存，失控 print 能直接打爆进程。
        with tempfile.TemporaryFile() as out_handle, tempfile.TemporaryFile() as err_handle:
            popen_kwargs: dict = {
                "stdout": out_handle,
                "stderr": err_handle,
                "cwd": run_cwd,
                "env": run_env,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True

            proc = subprocess.Popen([sys.executable, temp_file], **popen_kwargs)
            timed_out = False
            try:
                returncode = proc.wait(timeout=max(1, int(timeout)))
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_process_tree(proc)
                try:
                    returncode = proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    returncode = -9

            stdout, stdout_truncated = _read_capture(out_handle, "stdout")
            stderr, stderr_truncated = _read_capture(err_handle, "stderr")

        if timed_out:
            return RunResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                returncode=-2,
                error=f"执行超时（{timeout}秒）",
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
            )

        return RunResult(
            success=returncode == 0,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )

    except Exception as e:
        return RunResult(
            success=False,
            returncode=-3,
            error=f"沙箱执行异常: {type(e).__name__}: {e}",
        )
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except OSError:
                pass
        if use_temp_dir and os.path.exists(run_cwd):
            try:
                import shutil
                shutil.rmtree(run_cwd, ignore_errors=True)
            except Exception:
                pass
