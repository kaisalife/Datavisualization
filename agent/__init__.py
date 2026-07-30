"""
Base trading agent module
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 使用直接导入，避免循环导入
try:
    from .basic_agent import BaseAgent
except ImportError:
    from basic_agent import BaseAgent

__all__ = ["BaseAgent"]
