"""M3 CodeCompleter 冒烟测试（不调 LLM）。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from service.introspection.py_ast import analyze_python_source
from service.code_completer.completer import (
    CodeCompletionError,
    _validate_path,
    _extract_completion_json,
)


def test_ast_analysis():
    source = (Path(__file__).parent / "code_files" / "signal_fft.py").read_text(encoding="utf-8")
    summary = analyze_python_source(source)
    print("=== AST 摘要 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    assert len(summary["functions"]) == 2, f"应识别 2 个函数, 实际 {len(summary['functions'])}"
    fn_names = {f["name"] for f in summary["functions"]}
    assert fn_names == {"generate_signal", "compute_fft"}
    top_vars = {v["name"] for v in summary["top_level_vars"]}
    assert "signal" in top_vars
    assert "fft_freqs" in top_vars
    assert "sample_rate" in top_vars
    assert any(imp["module"] == "numpy" for imp in summary["imports"])
    print("✅ AST 分析通过")


def test_path_validation():
    print("\n=== 路径校验 ===")
    p = _validate_path("test_env/code_files/signal_fft.py")
    print("✅ 白名单内路径:", p)

    try:
        _validate_path("C:/Windows/System32/notepad.exe")
        raise AssertionError("未拦截越权路径")
    except CodeCompletionError as e:
        print("✅ 拦截越权:", str(e)[:80])

    try:
        _validate_path("test_env/data_files/季度数据.csv")
        raise AssertionError("未拦截 .csv")
    except CodeCompletionError as e:
        print("✅ 拦截非 .py:", str(e)[:80])


def test_json_extraction():
    print("\n=== JSON 提取 ===")
    mock = (
        "some noise before\n"
        "```json\n"
        + json.dumps({
            "snippet": "import matplotlib.pyplot as plt\nplt.plot(signal)\nplt.show()",
            "explanation": "绘制信号波形",
            "libs": ["matplotlib"],
        }, ensure_ascii=False)
        + "\n```\ntrailing noise\n"
    )
    parsed = _extract_completion_json(mock)
    print(parsed)
    assert parsed["snippet"].startswith("import matplotlib")
    assert parsed["libs"] == ["matplotlib"]
    print("✅ JSON 提取通过")


if __name__ == "__main__":
    test_ast_analysis()
    test_path_validation()
    test_json_extraction()
    print("\n=== 所有测试通过 ===")
