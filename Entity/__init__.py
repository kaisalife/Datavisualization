import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 使用直接导入，避免循环导入
try:
    from .model import model
    from .ApiModels import (
        GenerateChartWithPromptRequest,
        GenerateChartWithPromptResponse,
        GetChartRequest,
        ErrorResponse,
        CompleteVizCodeRequest,
    )
except ImportError:
    from model import model
    from ApiModels import (
        GenerateChartWithPromptRequest,
        GenerateChartWithPromptResponse,
        GetChartRequest,
        ErrorResponse,
        CompleteVizCodeRequest,
    )

__all__ = [
    'model',
    'GenerateChartWithPromptRequest',
    'GenerateChartWithPromptResponse',
    'GetChartRequest',
    'ErrorResponse',
    'CompleteVizCodeRequest',
]
