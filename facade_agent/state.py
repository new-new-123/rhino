# -*- coding: utf-8 -*-
"""状态定义：图与图之间传递的唯一数据结构。

设计原则（开闭原则）
--------------------
* 新增能力时**优先往 State 加字段**，而不是改图的形状；
* 加一个字段不会影响任何已有节点——它们只是读自己关心的键；
* ``total=False`` 让字段可选，便于增量构建。

两张图各有一个 State：
* ``MainState``  —— 主管图：管流程（选图、转译、落地、冻结）
* ``BuildState`` —— 建模子图：管迭代（规划 → 执行 → 测量 → 修正）
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

try:  # LangGraph 的消息合并器
    from langgraph.graph.message import add_messages
except Exception:  # pragma: no cover - 允许在未装 langgraph 时导入本模块
    def add_messages(left, right):
        return (left or []) + (right or [])


class BuildState(TypedDict, total=False):
    """建模子图的状态：一轮「规划 → 执行 → 测量」的全部输入输出。"""

    # 输入
    systems: list[dict[str, Any]]      # 构件系统 + 参数（由主管图转译节点产出）
    model_info: dict[str, Any]         # 体块信息：包围盒、楼板层线、开间中线、洞口

    # 过程
    attempt: int                       # 当前第几轮（从 1 开始）
    plan: dict[str, Any]               # 本轮几何规划结果
    built: dict[str, Any]              # 落地结果（生成了什么、放在哪）
    messages: Annotated[list, add_messages]   # 建模智能体的对话轨迹

    # 输出（测量裁判产出）
    metrics: dict[str, Any]            # 本轮量化指标：覆盖率、偏移、冲突
    history: list[dict[str, Any]]      # 历轮指标，供判断趋势
    verdict: str                       # ok / retry / escalate


class MainState(TypedDict, total=False):
    """主管图的状态：一次完整运行的全部输入输出。"""

    # 输入
    reference_image: str               # 设计师选定的效果图路径
    view: str                          # 目标立面（如 ELEV_S）
    styles: list[str]                  # 要生成的风格清单

    # 过程
    model_info: dict[str, Any]         # 体块信息
    schemes: list[dict[str, Any]]      # 生成出来的候选方案
    chosen: str                        # 设计师选定的方案文件名
    systems: list[dict[str, Any]]      # 转译出的构件系统与参数
    build_result: dict[str, Any]       # 建模子图回传的结果
    metrics: dict[str, Any]            # 最终指标
    report: str                        # 人话总结
    stage: str                         # 当前阶段（便于中断后恢复）