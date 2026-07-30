"""Path B: 代码可视化补全模块。

服务：/api/complete-viz-code
- 输入：code_file_paths + user_prompt + scientific_lib (可选)
- 输出：completed_code + inserted_snippet + explanation + recommended_libs
- **不执行代码**，只静态分析 + LLM 生成片段
"""

from service.code_completer.completer import (
    CodeCompletionError,
    complete_visualization_code,
)

__all__ = ["CodeCompletionError", "complete_visualization_code"]
