"""代码执行的静态安全校验：在真正执行前用 AST 拒绝危险构造。

为什么需要它：
- 旧版仅用正则黑名单（_RISKY）拦截 os/subprocess/open 等，但很容易被绕过：
  `import builtins`、`importlib.import_module`、`getattr(__builtins__, ...)`、
  `().__class__.__bases__[0].__subclasses__()` 等都不在正则覆盖范围内。
- 这里改用 AST 静态分析，覆盖：危险模块导入、dunder 属性访问/调用、危险内建名与调用。
  仍属「尽力而为」的沙箱，**真正的隔离必须依靠子进程 + 无特权容器**（见 code_tools）。

纯函数，不依赖 langchain，便于单测。
"""
import ast

# 禁止被 import 的模块（含潜在危险来源）
_FORBIDDEN_MODULES = {
    "os",
    "subprocess",
    "socket",
    "shutil",
    "sys",
    "pathlib",
    "multiprocessing",
    "ctypes",
    "signal",
    "pty",
    "pickle",
    "shelve",
    "mmap",
    "resource",
    "importlib",
    "builtins",
}

# 模块名前缀也禁止（如 os.path、importlib.machinery）
_FORBIDDEN_MODULE_PREFIXES = ("os.", "subprocess.", "importlib.")

# 禁止直接调用的危险内建 / 名称
_FORBIDDEN_NAMES = {
    "eval",
    "exec",
    "compile",
    "open",
    "input",
    "exit",
    "__import__",
    "breakpoint",
    "memoryview",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "hasattr",
}


class _SafetyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.reason: str = ""

    def _fail(self, msg: str) -> None:
        if not self.reason:
            self.reason = msg

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in _FORBIDDEN_MODULES or any(alias.name.startswith(p) for p in _FORBIDDEN_MODULE_PREFIXES):
                self._fail(f"禁止导入模块：{alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            top = node.module.split(".")[0]
            if top in _FORBIDDEN_MODULES or any(node.module.startswith(p) for p in _FORBIDDEN_MODULE_PREFIXES):
                self._fail(f"禁止导入模块：{node.module}")
            for alias in node.names:
                if alias.name in _FORBIDDEN_NAMES:
                    self._fail(f"禁止导入名称：{alias.name}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _FORBIDDEN_NAMES:
            self._fail(f"禁止使用：{node.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # 禁止访问双下划线属性/方法（如 __class__、__subclasses__、__import__），
        # 这是绕过沙箱最常见的手段（().__class__.__bases__[0].__subclasses__()）。
        attr = node.attr
        if attr.startswith("__") and attr.endswith("__"):
            self._fail(f"禁止访问魔术属性/方法：{attr}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # 调用层面的危险名（如 __import__('os')）
        func = node.func
        if isinstance(func, ast.Name) and func.id in _FORBIDDEN_NAMES:
            self._fail(f"禁止调用：{func.id}")
        self.generic_visit(node)


def is_safe_source(code: str) -> tuple[bool, str]:
    """静态校验源码是否安全。

    返回 (safe, reason)：safe=False 时 reason 说明原因（供拒绝消息使用）。
    语法错误也视为不安全（无法保证安全）。
    """
    if not code or not code.strip():
        return False, "代码为空"
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return False, f"代码语法错误：{e}"
    except ValueError as e:
        return False, f"代码无法解析：{e}"
    visitor = _SafetyVisitor()
    visitor.visit(tree)
    if visitor.reason:
        return False, visitor.reason
    return True, ""
