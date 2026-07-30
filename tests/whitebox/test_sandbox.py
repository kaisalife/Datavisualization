"""白盒测试：沙箱安全扫描。

测试 agent_tools/sandbox.py 的 AST 扫描和代码执行。
"""
import pytest

from agent_tools.sandbox import (
    DANGEROUS_CALLS,
    DANGEROUS_MODULES,
    RunResult,
    run_python_safely,
    scan_dangerous_code,
)


# ============================================================
# AST 扫描：危险调用拦截
# ============================================================

class TestScanDangerousCalls:
    """测试 scan_dangerous_code 的危险调用检测。"""

    def test_blocks_os_system(self):
        """os.system 应被拦截。"""
        code = "import os\nos.system('rm -rf /')"
        dangers = scan_dangerous_code(code)
        assert len(dangers) >= 1
        assert any("os.system" in d for d in dangers)

    def test_blocks_subprocess_run(self):
        """subprocess.run 应被拦截。"""
        code = "import subprocess\nsubprocess.run(['ls'])"
        dangers = scan_dangerous_code(code)
        assert any("subprocess.run" in d for d in dangers)

    def test_blocks_subprocess_popen(self):
        """subprocess.Popen 应被拦截。"""
        code = "import subprocess\nsubprocess.Popen(['ls'])"
        dangers = scan_dangerous_code(code)
        assert any("subprocess.Popen" in d for d in dangers)

    def test_blocks_eval(self):
        """eval 应被拦截。"""
        code = "eval('__import__(\"os\").system(\"ls\")')"
        dangers = scan_dangerous_code(code)
        assert any("eval" in d for d in dangers)

    def test_blocks_exec(self):
        """exec 应被拦截。"""
        code = "exec('print(1)')"
        dangers = scan_dangerous_code(code)
        assert any("exec" in d for d in dangers)

    def test_blocks_shutil_rmtree(self):
        """shutil.rmtree 应被拦截。"""
        code = "import shutil\nshutil.rmtree('/tmp')"
        dangers = scan_dangerous_code(code)
        assert any("shutil.rmtree" in d for d in dangers)

    def test_blocks_os_execv_family(self):
        """os.execv 系列（任务10修复）应被拦截。"""
        code = "import os\nos.execv('/bin/ls', ['ls'])"
        dangers = scan_dangerous_code(code)
        assert any("os.execv" in d for d in dangers)

    def test_blocks_os_spawnv_family(self):
        """os.spawnv 系列应被拦截。"""
        code = "import os\nos.spawnv(os.P_NOWAIT, '/bin/ls', ['ls'])"
        dangers = scan_dangerous_code(code)
        assert any("os.spawnv" in d for d in dangers)

    def test_blocks_os_fork(self):
        """os.fork 应被拦截。"""
        code = "import os\nos.fork()"
        dangers = scan_dangerous_code(code)
        assert any("os.fork" in d for d in dangers)


# ============================================================
# AST 扫描：危险模块导入拦截
# ============================================================

class TestScanDangerousModules:
    """测试危险模块导入检测。"""

    def test_blocks_socket_import(self):
        """socket 模块应被拦截。"""
        code = "import socket"
        dangers = scan_dangerous_code(code)
        assert any("socket" in d for d in dangers)

    def test_blocks_ctypes_import(self):
        """ctypes 模块应被拦截。"""
        code = "import ctypes"
        dangers = scan_dangerous_code(code)
        assert any("ctypes" in d for d in dangers)

    def test_blocks_from_import(self):
        """from socket import * 应被拦截。"""
        code = "from socket import *"
        dangers = scan_dangerous_code(code)
        assert any("socket" in d for d in dangers)

    def test_blocks_multiprocessing(self):
        """multiprocessing 应被拦截。"""
        code = "import multiprocessing"
        dangers = scan_dangerous_code(code)
        assert any("multiprocessing" in d for d in dangers)


# ============================================================
# AST 扫描：安全代码放行
# ============================================================

class TestScanSafeCode:
    """测试安全代码不会被误报。"""

    def test_safe_pandas_code_passes(self):
        """pandas + pyecharts 代码应通过。"""
        code = """
import pandas as pd
from pyecharts.charts import Bar
df = pd.read_csv("data.csv")
bar = Bar()
bar.add_xaxis(df["month"].tolist())
bar.add_yaxis("sales", df["sales"].tolist())
bar.render("output.html")
"""
        dangers = scan_dangerous_code(code)
        assert dangers == []

    def test_safe_math_code_passes(self):
        """纯数学计算应通过。"""
        code = "x = 1 + 2\nprint(x)"
        dangers = scan_dangerous_code(code)
        assert dangers == []

    def test_safe_pathlib_passes(self):
        """pathlib 应通过（非危险模块）。"""
        code = "from pathlib import Path\np = Path('.')\nprint(p.resolve())"
        dangers = scan_dangerous_code(code)
        assert dangers == []


# ============================================================
# run_python_safely：执行测试
# ============================================================

class TestRunPythonSafely:
    """测试 run_python_safely 的执行逻辑。"""

    def test_safe_code_executes_successfully(self):
        """安全代码应正常执行。"""
        result = run_python_safely("print('hello')", timeout=5)
        assert result.success
        assert "hello" in result.stdout

    def test_dangerous_code_returns_error(self):
        """危险代码应返回失败，不执行。"""
        result = run_python_safely("import os\nos.system('echo hacked')", timeout=5)
        assert not result.success
        assert "安全检查失败" in result.error

    def test_syntax_error_handled(self):
        """语法错误应被捕获，不崩溃。"""
        result = run_python_safely("print(", timeout=5)
        assert not result.success

    def test_timeout_handled(self):
        """超时应在指定秒数后终止。"""
        code = "import time\ntime.sleep(10)"
        result = run_python_safely(code, timeout=2)
        assert not result.success


# ============================================================
# DANGEROUS_CALLS 常量完整性
# ============================================================

class TestDangerousCallsConstants:
    """测试危险调用常量集的完整性（任务10修复）。"""

    def test_os_exec_family_expanded(self):
        """os.exec* 家族应完整展开（不再是无效的 'os.exec' 前缀）。"""
        exec_family = [c for c in DANGEROUS_CALLS if c.startswith("os.exec")]
        assert len(exec_family) >= 4  # execl, execv, execve, execvp 等

    def test_os_spawn_family_expanded(self):
        """os.spawn* 家族应完整展开。"""
        spawn_family = [c for c in DANGEROUS_CALLS if c.startswith("os.spawn")]
        assert len(spawn_family) >= 4

    def test_no_invalid_os_exec_prefix(self):
        """不应存在无效的 'os.exec' 空前缀。"""
        assert "os.exec" not in DANGEROUS_CALLS
