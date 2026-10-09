# -*- coding: utf-8 -*-
"""测量工具：智能体的「眼睛」，也是系统的裁判。

为什么这是全项目最重要的文件
------------------------------
实测研究（LEGO-Bench, 2025）证明：**智能体判断不了自己做得对不对**——
让它从两个版本里挑哪个更接近原图，几何判断接近随机水平。
结论是：*refinement should rely on concrete measurements,
not the agent's own judgment.*

所以纠偏不能靠"智能体再看看"，只能靠这里算出来的**数字**。
两个用途：
1. 作为 ``measure`` 节点的裁判（子图的达标判据）；
2. 作为工具交给建模智能体，让它每改一次就能自己看到数字。

新增一个指标 = 加一个 ``@register_measure`` 函数，图不用改（开闭原则）。
"""
from __future__ import annotations

from typing import Any

from ..registry import register_measure, run_measures

try:
    from langchain_core.tools import tool
except ImportError:  # pragma: no cover - 允许无 langchain 时导入
    def tool(*_a, **_k):
        def deco(f):
            return f
        return deco


# ──────────────────────────────────────────────────────────────
# 指标 1：规律线覆盖率
# ──────────────────────────────────────────────────────────────

@register_measure("coverage", "规律线覆盖率", target=0.95)
def coverage(built: dict, model_info: dict) -> float:
    """参考图要求的每条规律线，是否被某根构件覆盖。

    做法：把规划出的构件投影到水平轴上，看每条规律线的位置
    是否落在某根构件的跨度内。这是"位置对不对"的直接度量，
    而不是让智能体"看图感觉"。

    Returns:
        0.0–1.0。1.0 表示每条规律线都有构件压在上面。
    """
    lines = _lines_of(built)
    spans = _spans_of(built)
    if not lines:
        return 1.0            # 没有规律线要求，视为通过
    if not spans:
        return 0.0            # 有要求但一根构件都没生成
    tol = float(model_info.get("coverage_tolerance", 1.0))
    hit = 0
    for x in lines:
        if any(lo - tol <= x <= hi + tol for lo, hi in spans):
            hit += 1
    return hit / len(lines)


# ──────────────────────────────────────────────────────────────
# 指标 2：洞口冲突数
# ──────────────────────────────────────────────────────────────

@register_measure("conflicts", "洞口冲突数", unit=" 处",
                  higher_is_better=False, target=0)
def conflicts(built: dict, model_info: dict) -> float:
    """有多少根构件压在了门窗洞口上。

    洞口是真实几何，绝不能被构件糊住——这是"能不能用"的底线。
    """
    openings = model_info.get("openings", []) or []
    members = _members_of(built)
    count = 0
    for m in members:
        mx0, mx1 = float(m.get("x", 0)) - float(m.get("width", 0)) / 2, \
                   float(m.get("x", 0)) + float(m.get("width", 0)) / 2
        mz0, mz1 = float(m.get("z0", 0)), float(m.get("z1", 0))
        for op in openings:
            ox0, ox1 = float(op.get("x0", 0)), float(op.get("x1", 0))
            oz0, oz1 = float(op.get("z0", 0)), float(op.get("z1", 0))
            if mx0 < ox1 and mx1 > ox0 and mz0 < oz1 and mz1 > oz0:
                count += 1
                break
    return float(count)


# ──────────────────────────────────────────────────────────────
# 指标 3：节奏偏差（构件间距与要求间距的最大偏差）
# ──────────────────────────────────────────────────────────────

@register_measure("rhythm_dev", "节奏偏差", unit=" mm",
                  higher_is_better=False, target=50.0)
def rhythm_dev(built: dict, model_info: dict) -> float:
    """同类构件之间，间距是否均匀（最疏与最密之差）。

    为什么这样定义：腰线和竖挺的间距天然不同，混在一起算没有意义。
    所以按构件类型分组，每组各算一次，取最差的一组。
    均匀 → 0；忽疏忽密 → 数值变大。新增构件类型时本函数不用改。
    """
    from collections import defaultdict

    groups: dict[str, list[float]] = defaultdict(list)
    for m in _members_of(built):
        groups[str(m.get("kind", "?"))].append(float(m.get("x", 0)))

    worst = 0.0
    for xs in groups.values():
        if len(xs) < 3:
            continue          # 少于 3 个谈不上"节奏"
        xs = sorted(xs)
        gaps = [b - a for a, b in zip(xs, xs[1:])]
        worst = max(worst, max(gaps) - min(gaps))
    return float(worst)


# ──────────────────────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────────────────────

def _members_of(built: dict) -> list[dict]:
    plan = built.get("plan") or {}
    return list(plan.get("members") or [])


def _lines_of(built: dict) -> list[float]:
    plan = built.get("plan") or {}
    return [float(x) for x in (plan.get("lines") or [])]


def _spans_of(built: dict) -> list[tuple[float, float]]:
    spans = []
    for m in _members_of(built):
        x = float(m.get("x", 0))
        w = float(m.get("width", 0))
        spans.append((x - w / 2, x + w / 2))
    return spans


# ──────────────────────────────────────────────────────────────
# 给智能体用的工具（「眼睛」）
# ──────────────────────────────────────────────────────────────

@tool
def measure_now(built_json: str, model_info_json: str) -> str:
    """测量当前几何方案是否达标。改完几何后**必须**调用它。

    输入是两段 JSON 字符串：
      * built_json     —— 当前生成的构件（plan.members / plan.lines）
      * model_info_json —— 模型信息（openings / bay_width）

    返回全部已注册指标的数值，以及是否达标。
    不要凭感觉判断，只依据这里返回的数字。
    """
    import json

    from ..registry import judge

    built = json.loads(built_json or "{}")
    model_info = json.loads(model_info_json or "{}")
    metrics = run_measures(built, model_info)
    ok, failures = judge(metrics, coverage_target=model_info.get("coverage_target", 0.95))
    lines = [f"{k} = {v}" for k, v in metrics.items() if not k.endswith("__error")]
    verdict = "达标" if ok else "未达标：" + "；".join(failures)
    return "\n".join(lines + [f"判定：{verdict}"])


MEASURE_TOOLS = [measure_now]
