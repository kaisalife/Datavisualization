import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 兼容性导入
try:
    from .agent_prompt import agent_chart_designer_prompt
except ImportError:
    from agent_prompt import agent_chart_designer_prompt

__all__ = ["agent_chart_designer_prompt"]
