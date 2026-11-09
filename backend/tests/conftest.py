"""pytest 全局配置：把 backend 根目录加入模块搜索路径，使 `import app.*` 可用。

这样无论从哪个工作目录执行 `pytest`，都能正确导入 app 包。
"""
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
