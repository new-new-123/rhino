# -*- coding: utf-8 -*-
"""构件类型实现：把「构件系统 + 参数」展开成逐根构件的几何计划。

设计原则（开闭原则的实际演示）
------------------------------
要**新增一种立面构件**（例如曲面雨棚、栏杆、种植池）：

1. 在本文件写一个函数；
2. 加上 ``@register_component("你的类型", "中文名")``；
3. 完事——主管图、子图、测量、落地**都不需要改**。

这就是「对扩展开放、对修改关闭」在代码里的样子。
"""
from __future__ import annotations

from typing import Any

from ..registry import register_component


# ──────────────────────────────────────────────────────────────
# 公共小工具
# ──────────────────────────────────────────────────────────────

def _bays(model_info: dict) -> list[float]:
    """取开间中线（世界坐标 X）。没有就用包围盒均分。"""
    bays = model_info.get("bays") or []
    if bays:
        return [float(x) for x in bays]
    bbox = model_info.get("bbox") or {}
    x0, x1 = float(bbox.get("x0", 0)), float(bbox.get("x1", 0))
    n = int(model_info.get("bay_count", 0) or 0)
    if n <= 0 or x1 <= x0:
        return []
    step = (x1 - x0) / n
    return [x0 + step * (i + 0.5) for i in range(n)]


def _bbox(model_info: dict) -> tuple[float, float, float, float]:
    b = model_info.get("bbox") or {}
    return (float(b.get("x0", 0)), float(b.get("x1", 0)),
            float(b.get("z0", 0)), float(b.get("z1", 0)))


# ──────────────────────────────────────────────────────────────
# 构件 1：竖向格栅 / 竖挺
# ──────────────────────────────────────────────────────────────

@register_component("vertical_fin", "竖向格栅", "通高竖挺，按开间等距排布，可避让洞口")
def build_vertical_fin(system: dict, model_info: dict) -> dict[str, Any]:
    """在指定立面上排布竖向构件。

    参数（``system`` 里读）：
        per_bay      每个开间几根（默认 1）
        width        构件宽度 mm（默认 120）
        depth        出挑厚度 mm（默认 200）
        face_offset  距墙面距离 mm（默认 0）
        avoid_openings 是否避让洞口（默认 True）
    """
    per_bay = int(system.get("per_bay", 1) or 1)
    width = float(system.get("width", 120) or 120)
    depth = float(system.get("depth", 200) or 200)
    offset = float(system.get("face_offset", 0) or 0)
    avoid = bool(system.get("avoid_openings", True))

    x0, x1, z0, z1 = _bbox(model_info)
    bay_centers = _bays(model_info)
    openings = model_info.get("openings", []) or []
    face = str(system.get("face", "") or model_info.get("face", "S"))

    members: list[dict] = []
    lines: list[float] = []

    for center in bay_centers:
        for i in range(per_bay):
            # 单开间内均匀分布
            if per_bay == 1:
                x = center
            else:
                span = (x1 - x0) / max(1, len(bay_centers))
                x = center + (i - (per_bay - 1) / 2) * (span / per_bay)
            lines.append(x)

            z_start, z_end = z0, z1
            if avoid:
                # 竖直方向被洞口切断：遇到洞口就断开（这里取洞口的上下界裁剪）
                for op in openings:
                    ox0, ox1 = float(op.get("x0", 0)), float(op.get("x1", 0))
                    if ox0 - width / 2 <= x <= ox1 + width / 2:
                        # 该洞口正好压在竖挺上：把构件下移，避免糊住洞口
                        z_start = max(z_start, float(op.get("z1", z_start)))
            if z_end - z_start <= 1.0:
                continue

            members.append({
                "kind": "vertical_fin",
                "face": face,
                "x": x,
                "width": width,
                "depth": depth,
                "offset": offset,
                "z0": z_start,
                "z1": z_end,
            })

    return {"members": members, "lines": lines}


# ──────────────────────────────────────────────────────────────
# 构件 2：水平腰线
# ──────────────────────────────────────────────────────────────

@register_component("band", "水平腰线", "按楼板层线通长，可设层内偏移")
def build_band(system: dict, model_info: dict) -> dict[str, Any]:
    """在每条楼板层线上生成一道通长水平构件。

    参数：
        height       腰线高度 mm（默认 150）
        depth        出挑 mm（默认 100）
        z_offset     层内竖直偏移 mm（默认 0）
        at_floors    用哪几条层线（默认全部）
    """
    height = float(system.get("height", 150) or 150)
    depth = float(system.get("depth", 100) or 100)
    z_offset = float(system.get("z_offset", 0) or 0)
    x0, x1, _, _ = _bbox(model_info)
    floors = [float(z) for z in (model_info.get("floors") or [])]
    if not floors:
        floors = [_bbox(model_info)[3]]      # 没有层线就用顶面

    pick = system.get("at_floors")
    if isinstance(pick, list) and pick:
        floors = [floors[int(i)] for i in pick if 0 <= int(i) < len(floors)]

    members, lines = [], []
    for z in floors:
        zc = z + z_offset
        lines.append(x0)
        lines.append(x1)
        members.append({
            "kind": "band",
            "face": str(system.get("face", "") or model_info.get("face", "S")),
            "x": (x0 + x1) / 2,
            "width": abs(x1 - x0),
            "height": height,
            "depth": depth,
            "z0": zc - height / 2,
            "z1": zc + height / 2,
        })
    return {"members": members, "lines": lines}