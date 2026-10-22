"""沙箱执行核心回归（无 LLM / 无网络）。

覆盖生成代码执行的三个真实风险：

- 子进程不能读到宿主机的 API Key（环境变量净化）；
- 失控输出不能把父进程内存吃光（保留末尾 + 截断标记）；
- 超时必须杀整棵进程树，且不留下临时 .py 文件。
"""
from __future__ import annotations

import os
from pathlib import Path

from agent_tools.sandbox import _sanitize_env, run_python_safely


def test_normal_code_runs_and_cleans_temp_file(tmp_path: Path):
    result = run_python_safely("print('hello sandbox')", cwd=str(tmp_path), timeout=20)

    assert result.success is True
    assert "hello sandbox" in result.stdout
    assert result.returncode == 0
    assert list(tmp_path.glob("*.py")) == []


def test_secrets_are_stripped_from_child_environment():
    env = {
        "PATH": os.environ.get("PATH", ""),
        "OPENAI_API_KEY": "sk-live-should-not-leak",
        "SERVICE_API_KEY": "svc-should-not-leak",
        "LLM_EXTRA_HEADERS": '{"x-opencode-session": "secret"}',
        "SAFE_FLAG": "visible",
    }

    result = run_python_safely(
        "import os\n"
        "print(os.environ.get('OPENAI_API_KEY', 'MISSING'))\n"
        "print(os.environ.get('SERVICE_API_KEY', 'MISSING'))\n"
        "print(os.environ.get('LLM_EXTRA_HEADERS', 'MISSING'))\n"
        "print(os.environ.get('SAFE_FLAG', 'MISSING'))\n"
        "print(bool(os.environ.get('PATH')))",
        env=env,
        timeout=20,
    )

    assert result.success is True, result.error
    assert "sk-live-should-not-leak" not in result.stdout
    assert "svc-should-not-leak" not in result.stdout
    assert "x-opencode-session" not in result.stdout
    assert "MISSING" in result.stdout
    assert "visible" in result.stdout
    assert "True" in result.stdout  # PATH 保留，解释器/依赖仍可运行


def test_sanitize_env_keeps_runtime_variables():
    cleaned = _sanitize_env(
        {
            "PATH": "p",
            "PYTHONPATH": "q",
            "CHART_OUTPUT_DIR": "r",
            "TEMP": "t",
            "HF_TOKEN": "nope",
            "DB_PASSWORD": "nope",
        }
    )

    assert set(cleaned) == {"PATH", "PYTHONPATH", "CHART_OUTPUT_DIR", "TEMP"}


def test_huge_output_is_truncated_to_tail(monkeypatch):
    monkeypatch.setenv("SANDBOX_MAX_OUTPUT_BYTES", "1200")

    result = run_python_safely("print('A' * 8000)", timeout=20)

    assert result.success is True
    assert result.stdout_truncated is True
    assert "截断" in result.stdout
    assert len(result.stdout) < 2000
    assert "A" in result.stdout


def test_timeout_returns_failure(monkeypatch):
    result = run_python_safely("import time\ntime.sleep(5)", timeout=1)

    assert result.success is False
    assert result.returncode == -2
    assert "超时" in result.error


def test_dangerous_code_is_blocked_before_execution(tmp_path: Path):
    marker = tmp_path / "should_not_exist.txt"

    result = run_python_safely(
        f"open(r'{marker}', 'w').write('executed')\n",
        cwd=str(tmp_path),
        timeout=20,
    )
    # 普通文件写入不在危险列表里（图表代码需要落盘）；确认沙箱仍允许正常执行
    assert result.success is True
    assert marker.is_file()

    blocked = run_python_safely("import os\nos.system('echo hi')", timeout=20)
    assert blocked.success is False
    assert "安全检查失败" in blocked.error

def test_chart_sandbox_timeout_is_env_configurable(monkeypatch, tmp_path: Path):
    """图表沙箱超时可用 SANDBOX_TIMEOUT 调整（默认 90s）。"""
    from service.pipeline.chart_sandbox import execute_chart_code

    monkeypatch.setenv("SANDBOX_TIMEOUT", "1")
    result = execute_chart_code(
        "import time\ntime.sleep(5)",
        charts_folder=tmp_path,
        plan_id="timeout-case",
    )

    assert result.success is False
    assert "超时" in result.output
