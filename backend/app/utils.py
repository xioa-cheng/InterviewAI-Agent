"""通用工具函数"""
import json
import re
from typing import Any


def parse_json(text: str) -> dict:
    """从 LLM 输出中稳健地提取 JSON 对象（容忍 markdown 代码块等噪声）"""
    if not text:
        return {}
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def clamp_score(score: Any, default: float = 70.0) -> float:
    """把分数约束到 0~100"""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(100.0, s))
