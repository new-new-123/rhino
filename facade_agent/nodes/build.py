# -*- coding: utf-8 -*-
"""建模子图的三个节点：规划 → 执行 → 测量。

节点用**工厂函数**返回（依赖注入），这样：
* 节点本身不 import 全局配置，测试时可以传假的 settings / hub；
* ``act`` 的内部实现可以整体替换（LangGraph ReAct / 外部 CLI / 将来的 dsh），
  而**图的形状不用动**——这是开闭原则在「换智能体」这件事上的落点。
"""
from __future__ import annotations

from typing import Any, Callable

from ..config import Settings
from ..mcp_client import McpHub
from ..registry import get_component, judge, run_measures
from ..tools.measure_tools import MEASURE_TOOLS

# ──────────────────────────────────────────────────────────────
# 节点 1：规划（纯计算，无 LLM）
# ──────────────────────────────────────────────────────────────

def make_plan_node() -> Callable:
    """把「构件系统 + 参数」展开成逐根构件的几何计划。

    完全确定性：同样的输入必然得到同样的输出。这是可复现的基础。
    """

    async def plan(state: dict) -> dict:
        systems = state.get("systems") or []
        model_info = state.get("model_info") or {}

        members: list[dict] = []
        lines: list[float] = []
        errors: list[str] = []

        for system in systems:
            kind = system.get("kind", "")
            try:
                spec = get_component(kind)          # 未注册的类型会在这里报错
            except KeyError as exc:
                errors.append(str(exc))
                continue
            out = spec.builder(system, model_info)
            members.extend(out.get("members") or [])
            lines.extend(out.get("lines") or [])

        return {
            "plan": {"members": members, "lines": lines, "errors": errors},
            "attempt": int(state.get("attempt", 0)),
        }

    return plan


# ──────────────────────────────────────────────────────────────
# 节点 2：执行（智能体，可整体替换）
# ──────────────────────────────────────────────────────────────

BUILD_PROMPT = """你是 Rhino 建模助手。你的任务：把给定的构件几何计划落进 Rhino。

规则（必须遵守）：
1. 只使用提供的工具，不要自己编造 API；
2. 每完成一批几何，**必须调用 measure_now** 查看指标；
3. 指标未达标时，优先调整参数（间距、数量、偏移），而不是大改结构；
4. 判断依据只能是 measure_now 返回的数字，**不要凭感觉说"看起来对了"**；
5. 洞口不能被构件糊住——conflicts 必须为 0。

完成后用一句话汇报：生成了什么、指标是多少。
"""


def make_act_node(settings: Settings, hub: McpHub) -> Callable:
    """执行节点：把几何计划落进 Rhino。

    这里是**唯一**与「用哪个智能体」耦合的地方：
    * 离线模式 → 确定性落地（不调模型，便于单测和没装 Rhino 的机器）；
    * 在线模式 → ReAct 智能体调 MCP 工具落地。

    将来想换成别的 harness（如 deepseek-harness），只改这个函数内部。
    """

    async def act(state: dict) -> dict:
        plan = state.get("plan") or {}

        # ── 离线：确定性落地，保证图能跑通 ──────────────────────
        if hub.offline:
            return {"built": {"plan": plan, "mode": "offline",
                              "created": len(plan.get("members") or [])}}

        # ── 在线：交给建模智能体 ────────────────────────────────
        from langgraph.prebuilt import create_react_agent

        from ..llm import ROLE_BUILD, make_model, require_api_key

        require_api_key(settings)
        tools = [*(await hub.tools()), *MEASURE_TOOLS]
        agent = create_react_agent(
            model=make_model(settings, ROLE_BUILD),
            tools=tools,
            prompt=BUILD_PROMPT,
        )

        instruction = (
            f"按下面的几何计划在 Rhino 里生成构件，然后调用 measure_now 自检。\n"
            f"模型信息：{state.get('model_info')}\n"
            f"几何计划：{plan}\n"
            f"这是第 {int(state.get('attempt', 0)) + 1} 轮。"
        )
        result = await agent.ainvoke({"messages": [("user", instruction)]})
        return {"built": {"plan": plan, "mode": "online", "messages": result.get("messages", [])}}

    return act


# ──────────────────────────────────────────────────────────────
# 节点 3：测量（裁判，纯计算）
# ──────────────────────────────────────────────────────────────

def make_measure_node(settings: Settings) -> Callable:
    """测量节点：算出指标并给出 verdict。

    verdict 只有三种，直接决定条件边走向：
        ok       → 交付
        retry    → 回到 act 继续改（受轮次上限约束）
        escalate → 交人工，附量化报告
    """

    async def measure(state: dict) -> dict:
        built = state.get("built") or {}
        model_info = state.get("model_info") or {}
        attempt = int(state.get("attempt", 0)) + 1

        metrics = run_measures(built, model_info)
        ok, failures = judge(metrics, settings.coverage_target)

        if ok:
            verdict = "ok"
        elif attempt >= settings.max_attempts:
            verdict = "escalate"
        else:
            verdict = "retry"

        record = {"attempt": attempt, "metrics": metrics,
                  "verdict": verdict, "failures": failures}
        history = list(state.get("history") or [])
        history.append(record)

        return {"metrics": metrics, "attempt": attempt,
                "verdict": verdict, "history": history}

    return measure


# ──────────────────────────────────────────────────────────────
# 条件边
# ──────────────────────────────────────────────────────────────

def route_after_measure(state: dict) -> str:
    """测量后的走向。加新分支时只改这里。"""
    verdict = state.get("verdict", "escalate")
    return verdict if verdict in {"ok", "retry", "escalate"} else "escalate"