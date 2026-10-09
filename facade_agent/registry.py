# -*- coding: utf-8 -*-
"""注册表：构件类型与测量指标的扩展点。

设计原则（开闭原则的落点）
--------------------------
* **新增一种构件**（如曲面雨棚）：写一个 builder 函数 + ``@register_component``，
  主管图、子图、其它节点**一行都不用改**；
* **新增一个测量指标**（如「竖挺垂直度」）：写一个函数 + ``@register_measure``，
  测量裁判自动就会算它，并出现在指标里；
* 两个注册表都在这里集中管理，避免扩展点散落各处（高内聚）。

约定
----
* builder 签名：``(system: dict, model_info: dict) -> dict``，返回该系统的几何计划；
* measure 签名：``(built: dict, model_info: dict) -> float``，返回一个数。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# ──────────────────────────────────────────────────────────────
# 构件类型注册表
# ──────────────────────────────────────────────────────────────

@dataclass
class ComponentSpec:
    """一种构件类型的登记信息。"""

    kind: str                       # 类型标识，如 "vertical_fin"
    label: str                      # 中文名，给人看
    builder: Callable[..., dict]    # 几何计划函数
    note: str = ""                  # 备注（能力边界等）


_COMPONENTS: dict[str, ComponentSpec] = {}


def register_component(kind: str, label: str, note: str = ""):
    """装饰器：把一个 builder 函数登记为某种构件类型。

    用法::

        @register_component("vertical_fin", "竖向格栅", "通高竖挺，可避让洞口")
        def build_vertical_fin(system, model_info):
            ...
    """
    def decorator(func: Callable[..., dict]) -> Callable[..., dict]:
        _COMPONENTS[kind] = ComponentSpec(kind=kind, label=label, builder=func, note=note)
        return func
    return decorator


def get_component(kind: str) -> ComponentSpec:
    if kind not in _COMPONENTS:
        known = "、".join(sorted(_COMPONENTS)) or "(还没有注册任何构件)"
        raise KeyError(f"未注册的构件类型：{kind}。已注册：{known}")
    return _COMPONENTS[kind]


def list_components() -> list[ComponentSpec]:
    return [_COMPONENTS[k] for k in sorted(_COMPONENTS)]


# ──────────────────────────────────────────────────────────────
# 测量指标注册表
# ──────────────────────────────────────────────────────────────

@dataclass
class MeasureSpec:
    """一个测量指标的登记信息。"""

    name: str                       # 指标键名，如 "coverage"
    label: str                      # 中文名
    unit: str = ""                  # 单位（可为空）
    higher_is_better: bool = True   # 越大越好还是越小越好
    target: float | None = None     # 达标线（None 表示只报告不判定）
    func: Callable[..., float] | None = None


_MEASURES: dict[str, MeasureSpec] = {}


def register_measure(name: str, label: str, unit: str = "",
                     higher_is_better: bool = True, target: float | None = None):
    """装饰器：登记一个测量指标。

    用法::

        @register_measure("coverage", "规律线覆盖率", target=0.95)
        def coverage(built, model_info):
            ...
    """
    def decorator(func: Callable[..., float]) -> Callable[..., float]:
        _MEASURES[name] = MeasureSpec(
            name=name, label=label, unit=unit,
            higher_is_better=higher_is_better, target=target, func=func,
        )
        return func
    return decorator


def list_measures() -> list[MeasureSpec]:
    return [_MEASURES[k] for k in sorted(_MEASURES)]


def run_measures(built: dict, model_info: dict) -> dict[str, Any]:
    """跑一遍所有已注册指标，返回 ``{指标名: 数值}``。

    任何一个指标算失败都不会影响其它指标（互不阻塞）。
    """
    results: dict[str, Any] = {}
    for spec in list_measures():
        if spec.func is None:
            continue
        try:
            results[spec.name] = float(spec.func(built, model_info))
        except Exception as exc:  # 单点失败不影响整体
            results[spec.name] = None
            results[f"{spec.name}__error"] = f"{type(exc).__name__}: {exc}"
    return results


def judge(metrics: dict[str, Any], coverage_target: float) -> tuple[bool, list[str]]:
    """按已登记指标的达标线判断本轮是否通过。

    Returns:
        (是否全部达标, 未达标说明列表)
    """
    failures: list[str] = []
    for spec in list_measures():
        value = metrics.get(spec.name)
        if value is None:
            continue
        target = spec.target
        if spec.name == "coverage":       # 覆盖率目标可由配置覆盖
            target = coverage_target
        if target is None:
            continue
        ok = value >= target if spec.higher_is_better else value <= target
        if not ok:
            arrow = "应 ≥" if spec.higher_is_better else "应 ≤"
            failures.append(f"{spec.label} {value:.3f}{spec.unit}（{arrow} {target}）")
    return (len(failures) == 0), failures