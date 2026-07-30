"""沙箱化代码执行。

LLM 生成的 Python 代码不能直接在宿主机跑。
通过 AST 扫描禁止危险调用 + subprocess 隔离执行。
"""

import ast
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
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
    3. subprocess.run（cwd=tmpdir 或指定目录, timeout）
    4. 返回 RunResult

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

    run_env = dict(env) if env else dict(os.environ)
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

        result = subprocess.run(
            [sys.executable, temp_file],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=run_cwd,
            env=run_env,
            encoding="utf-8",
            errors="replace",
        )

        return RunResult(
            success=result.returncode == 0,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            returncode=result.returncode,
        )

    except subprocess.TimeoutExpired:
        return RunResult(
            success=False,
            returncode=-2,
            error=f"执行超时（{timeout}秒）",
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
