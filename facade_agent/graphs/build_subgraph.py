# -*- coding: utf-8 -*-
"""建模子图：规划 → 执行 → 测量 → （不达标则回到执行）。

这个子图是整个系统里唯一"会自己迭代"的地方。
它的形状很简单，但有三个硬约束（缺一不可）：

1. **轮次上限**：由 ``settings.max_attempts`` 控制，防止无限循环；
2. **达标判据来自测量**：``measure`` 节点算数字，不看智能体的自我评价；
3. **失败有出口**：超限就走 ``escalate`` 交人工，绝不静默结束。

想换成别的智能体实现（如 deepseek-harness）：只改 ``nodes/build.py`` 里的
``make_act_node``，**本文件的图不用动**。
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..config import Settings
from ..mcp_client import McpHub
from ..nodes.build import (
    make_act_node,
    make_measure_node,
    make_plan_node,
    route_after_measure,
)
from ..state import BuildState


def build_build_subgraph(settings: Settings, hub: McpHub):
    """编译建模子图。"""
    graph = StateGraph(BuildState)

    graph.add_node("plan", make_plan_node())
    graph.add_node("act", make_act_node(settings, hub))
    graph.add_node("measure", make_measure_node(settings))

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "act")
    graph.add_edge("act", "measure")

    graph.add_conditional_edges(
        "measure",
        route_after_measure,
        {
            "ok": END,          # 达标 → 交付
            "retry": "act",     # 未达标且还有轮次 → 回到执行继续改
            "escalate": END,    # 超限 → 交人工
        },
    )

    return graph.compile()