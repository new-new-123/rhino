# -*- coding: utf-8 -*-
"""主管图：读参考图 → 出方案 →〔中断：选图〕→ 转译 → 建模子图 →〔中断：确认落地〕→ 冻结 → 报告。

三个设计要点
------------
1. **子图作为节点**：``build`` 节点内部调用建模子图。这里用一个薄包装函数
   做输入/输出投影，好处是父图状态不被子图的中间键污染，调试时边界清晰。
2. **两个人工中断点**：分别落在「该由人做的两件事」上——审美选择、落地确认。
   中断后状态由 checkpointer 保存，关掉电脑第二天接着跑。
3. **离线可跑**：``hub.offline=True`` 时全部节点走确定性分支，
   没有 Rhino、没有密钥也能把图跑通，便于在 VS Code 里先验证结构。
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..config import Settings
from ..mcp_client import McpHub
from ..nodes.main import (
    make_freeze_node,
    make_generate_schemes_node,
    make_read_reference_node,
    make_report_node,
    make_translate_reference_node,
)
from ..state import MainState
from .build_subgraph import build_build_subgraph

# 需要人工确认的节点（中断点）
HUMAN_IN_THE_LOOP = ["freeze"]


def build_main_graph(settings: Settings, hub: McpHub, checkpointer=None):
    """编译主管图。

    Args:
        settings: 全局配置。
        hub: MCP 连接hub。
        checkpointer: 检查点保存器；给了它才能中断/恢复。
    """
    sub = build_build_subgraph(settings, hub)

    async def build_node(state: dict) -> dict:
        """薄包装：把父图状态投影成子图输入，再把子图结果投影回父图。

        这样做而不是直接把子图 ``add_node``，是为了让两个图的状态
        **各自独立演化**——加子图字段不会污染父图。
        """
        result = await sub.ainvoke({
            "systems": state.get("systems") or [],
            "model_info": state.get("model_info") or {},
            "attempt": 0,
        })
        return {
            "build_result": result,
            "metrics": result.get("metrics") or {},
            "stage": f"build:{result.get('verdict', '?')}",
        }

    graph = StateGraph(MainState)

    graph.add_node("read_reference", make_read_reference_node(settings))
    graph.add_node("generate_schemes", make_generate_schemes_node(settings, hub))
    graph.add_node("translate_reference", make_translate_reference_node(settings))
    graph.add_node("build", build_node)
    graph.add_node("freeze", make_freeze_node(settings, hub))
    graph.add_node("report", make_report_node(settings))

    graph.add_edge(START, "read_reference")
    graph.add_edge("read_reference", "generate_schemes")
    graph.add_edge("generate_schemes", "translate_reference")
    graph.add_edge("translate_reference", "build")
    graph.add_edge("build", "freeze")
    graph.add_edge("freeze", "report")
    graph.add_edge("report", END)

    # 中断点需要 checkpointer 才能"停住并恢复"。
    # 没给 checkpointer 时（例如单测、快速冒烟）就不中断，让流程一次跑完，
    # 否则会停在 freeze 前且无法恢复。
    interrupts = HUMAN_IN_THE_LOOP if checkpointer is not None else []

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupts,
    )


def build_graph_with_sqlite(settings: Settings, hub: McpHub, db_path: str):
    """带 SQLite 检查点的主管图——支持「中断后关电脑，明天接着跑」。"""
    from langgraph.checkpoint.sqlite import SqliteSaver

    settings.dirs["runs"].mkdir(parents=True, exist_ok=True)
    saver = SqliteSaver.from_conn_string(db_path)
    return build_main_graph(settings, hub, checkpointer=saver)
