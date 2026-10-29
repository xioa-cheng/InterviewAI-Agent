"""轻量 ReAct 运行器：把「工具循环」与「结构化终态」组合起来。

为什么不用 create_react_agent：
- 本项目需要在工具推理之后，用一份 Pydantic schema 产出**结构化**结果
  （question / score 等），以延续既有的评分契约、杜绝静默兜底污染。
- 手写循环版本对 LangGraph 版本零依赖、行为可控，且便于将来接入流式输出。

流程：
1. 用 bind_tools 把工具绑到 LLM，发起推理；
2. 若模型要求调用工具，则逐个执行（异步），把结果以 ToolMessage 回填后再次推理；
3. 直到模型不再请求工具（或达到最大轮次）；
4. 若有 schema，则再做一次 with_structured_output 调用，从完整上下文抽取结构化对象。
"""
import logging
from typing import List, Optional, Type

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel

from app.llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def run_react(
    model=None,
    tools: Optional[List] = None,
    system: str = "",
    human: str = "",
    schema: Optional[Type[BaseModel]] = None,
    max_iterations: int = 5,
):
    """运行 ReAct 工具循环，必要时返回结构化结果。

    Args:
        model: ChatOpenAI 实例；缺省时取全局单例。
        tools: BaseTool 列表（如 @tool 装饰的异步函数）。
        system/human: 系统 / 用户提示。
        schema: 结构化输出 schema；为 None 时返回最后一条 AI 消息文本。
        max_iterations: 工具循环最大轮次，防止死循环。
    """
    if model is None:
        model = get_llm_client()
    tools = tools or []
    bound = model.bind_tools(tools) if tools else model

    messages = [SystemMessage(content=system), HumanMessage(content=human)]
    tool_map = {t.name: t for t in tools}

    for _ in range(max_iterations):
        resp = await bound.ainvoke(messages)
        messages.append(resp)

        tool_calls = getattr(resp, "tool_calls", None)
        if not tool_calls:
            break

        for tc in tool_calls:
            name = tc.get("name")
            args = tc.get("args", {}) or {}
            tool = tool_map.get(name)
            try:
                if tool is None:
                    result = f"未知工具：{name}"
                else:
                    result = await tool.ainvoke(args)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"工具 {name} 执行失败: {e}")
                result = f"工具执行失败：{e}"
            messages.append(ToolMessage(content=str(result), tool_call_id=tc.get("id")))

    if schema is not None:
        # 用 function_calling 方式产出结构化结果：DeepSeek 等 OpenAI 兼容模型支持工具调用，
        # 但不支持 json_schema 类型的 response_format（会返回 400）。function_calling 走工具调用，
        # 兼容性最好，且能继续约束输出结构。
        structured = model.with_structured_output(schema, method="function_calling")
        final = await structured.ainvoke(messages)
        return final.model_dump() if hasattr(final, "model_dump") else dict(final)

    return getattr(messages[-1], "content", "")


async def run_react_stream(
    model=None,
    tools: Optional[List] = None,
    system: str = "",
    human: str = "",
    max_iterations: int = 5,
):
    """与 run_react 同逻辑的「流式版」：工具循环一致，但最后一步改用 astream，
    逐块 yield 最终答案文本（供 SSE 打字机 / 实时推送使用）。

    仅流式输出「最终答案」这一条消息；工具推理阶段不产生 token 流（属内部推理）。
    不返回结构化对象——调用方负责从流式文本中解析所需字段（如题型 / 评分标记）。
    """
    if model is None:
        model = get_llm_client()
    tools = tools or []
    bound = model.bind_tools(tools) if tools else model

    messages = [SystemMessage(content=system), HumanMessage(content=human)]
    tool_map = {t.name: t for t in tools}

    for _ in range(max_iterations):
        resp = await bound.ainvoke(messages)
        messages.append(resp)

        tool_calls = getattr(resp, "tool_calls", None)
        if not tool_calls:
            break

        for tc in tool_calls:
            name = tc.get("name")
            args = tc.get("args", {}) or {}
            tool = tool_map.get(name)
            try:
                if tool is None:
                    result = f"未知工具：{name}"
                else:
                    result = await tool.ainvoke(args)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"工具 {name} 执行失败: {e}")
                result = f"工具执行失败：{e}"
            messages.append(ToolMessage(content=str(result), tool_call_id=tc.get("id")))

    # 最终答案：逐块流式输出
    async for chunk in model.astream(messages):
        text = getattr(chunk, "content", None)
        if text:
            yield text
