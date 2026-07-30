import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import data_preview

data_file = sys.argv[1] if len(sys.argv) > 1 else os.getenv("TEST_DATA_FILE", "")
if not data_file or not Path(data_file).exists():
    print(f"用法: python test.py <数据文件路径>")
    print(f"  或设置环境变量 TEST_DATA_FILE=<数据文件路径>")
    sys.exit(1)

data_preview.get_file_preview([data_file])
