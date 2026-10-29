"""代码执行工具：在受限沙箱中运行 Python，验证候选人代码回答的正确性。

安全分层（纵深防御）：
1. 静态校验（sandbox_guard）：用 AST 拒绝危险模块导入、双下划线属性访问、危险内建/调用；
2. 执行隔离：在子进程中以 `python -I`（隔离模式，不加载 site / 忽略环境变量）运行，
   并通过受限 __builtins__ 进一步剥夺 open/eval/exec/__import__ 等危险能力；
3. 资源限制：超时 5 秒、在临时目录运行、捕获 stdout/stderr。

即便如此，本工具仍是「尽力而为」的沙箱。**生产环境务必在独立容器 / 无特权环境中运行本服务，
切勿在宿主直接暴露**。默认禁用（ENABLE_CODE_TOOLS=false），需显式开启。
"""
import logging
import subprocess
import sys

from langchain_core.tools import tool

from app.agent.tools.sandbox_guard import is_safe_source
from app.config import settings

logger = logging.getLogger(__name__)

# 子进程执行用的「安全内建」集合：仅保留无害的计算/容器/格式化类内建。
_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "ascii": ascii, "bin": bin, "bool": bool,
    "bytearray": bytearray, "bytes": bytes, "callable": callable, "chr": chr,
    "complex": complex, "dict": dict, "divmod": divmod, "enumerate": enumerate,
    "filter": filter, "float": float, "format": format, "frozenset": frozenset,
    "hex": hex, "int": int, "isinstance": isinstance, "issubclass": issubclass,
    "iter": iter, "len": len, "list": list, "map": map, "max": max, "min": min,
    "next": next, "object": object, "oct": oct, "ord": ord, "pow": pow,
    "print": print, "range": range, "repr": repr, "reversed": reversed,
    "round": round, "set": set, "slice": slice, "sorted": sorted, "str": str,
    "sum": sum, "tuple": tuple, "type": type, "zip": zip,
    "True": True, "False": False, "None": None,
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError, "ZeroDivisionError": ZeroDivisionError,
    "AttributeError": AttributeError, "RuntimeError": RuntimeError, "StopIteration": StopIteration,
}

# 在子进程中执行的包装脚本：读取用户代码（经 argv 传入），用受限内建 exec。
_WRAPPER = (
    "import sys\n"
    "_SAFE = sys.modules[__name__].__dict__\n"
    "code = sys.argv[1]\n"
    "globals_ = {'__builtins__': {\n"
    "    'abs': abs,'all': all,'any': any,'ascii': ascii,'bin': bin,'bool': bool,\n"
    "    'bytearray': bytearray,'bytes': bytes,'callable': callable,'chr': chr,\n"
    "    'complex': complex,'dict': dict,'divmod': divmod,'enumerate': enumerate,\n"
    "    'filter': filter,'float': float,'format': format,'frozenset': frozenset,\n"
    "    'hex': hex,'int': int,'isinstance': isinstance,'issubclass': issubclass,\n"
    "    'iter': iter,'len': len,'list': list,'map': map,'max': max,'min': min,\n"
    "    'next': next,'object': object,'oct': oct,'ord': ord,'pow': pow,'print': print,\n"
    "    'range': range,'repr': repr,'reversed': reversed,'round': round,'set': set,\n"
    "    'slice': slice,'sorted': sorted,'str': str,'sum': sum,'tuple': tuple,\n"
    "    'type': type,'zip': zip,'True': True,'False': False,'None': None,\n"
    "    'Exception': Exception,'ValueError': ValueError,'TypeError': TypeError,\n"
    "    'KeyError': KeyError,'IndexError': IndexError,'ZeroDivisionError': ZeroDivisionError,\n"
    "    'AttributeError': AttributeError,'RuntimeError': RuntimeError,'StopIteration': StopIteration,\n"
    "}}\n"
    "exec(compile(code, '<user>', 'exec'), globals_)\n"
)


@tool
async def run_python_code(code: str) -> str:
    """在受限沙箱中执行 Python 代码，验证候选人代码回答是否能正确运行，返回 stdout / stderr。

    仅在内置开关 ENABLE_CODE_TOOLS=true 时可用，默认禁用。
    执行前会做 AST 静态安全校验，并在隔离子进程中以受限内建运行。

    Args:
        code: 待执行的 Python 源代码。
    """
    if not settings.ENABLE_CODE_TOOLS:
        return "代码执行工具当前已禁用（ENABLE_CODE_TOOLS=false），如需验证代码请开启该开关并在隔离环境中运行。"

    if not code or not code.strip():
        return "未提供代码。"

    safe, reason = is_safe_source(code)
    if not safe:
        return f"出于安全考虑，该代码被拒绝执行：{reason}。"

    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _WRAPPER, code],
            capture_output=True,
            text=True,
            timeout=5,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return (out.strip()[:2000] or "(无输出)")
    except subprocess.TimeoutExpired:
        return "代码执行超时（>5 秒），已终止。"
    except Exception as e:  # noqa: BLE001
        logger.warning(f"代码执行工具异常: {e}")
        return f"执行异常：{e}"
