# -*- coding: utf-8 -*-
"""命令行入口：VS Code 里直接跑的就是它。

三种用法
--------
    python -m facade_agent.cli --check      # 自检：配置 / 注册表 / 图 / MCP，不花额度
    python -m facade_agent.cli --demo       # 离线跑通建模子图闭环（不需要 Rhino 和密钥）
    python -m facade_agent.cli --run        # 跑主管图全流程

建议顺序：先 ``--check``，再 ``--demo``，最后 ``--run``。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import __version__
from .config import load_settings
from .mcp_client import build_hub
from .registry import list_components, list_measures

# ── 演示用的合成模型（一个三层、六开间、带门窗的体块）──────────────
DEMO_MODEL_INFO = {
    "face": "S",
    "bbox": {"x0": 0.0, "x1": 30000.0, "z0": 0.0, "z1": 10500.0},
    "floors": [0.0, 3500.0, 7000.0, 10500.0],
    "bays": [2500.0, 7500.0, 12500.0, 17500.0, 22500.0, 27500.0],
    "bay_width": 5000.0,
    "openings": [
        {"x0": 1500.0, "x1": 3500.0, "z0": 900.0, "z1": 2900.0},
        {"x0": 6500.0, "x1": 8500.0, "z0": 900.0, "z1": 2900.0},
        {"x0": 11500.0, "x1": 13500.0, "z0": 900.0, "z1": 2900.0},
        {"x0": 16500.0, "x1": 18500.0, "z0": 900.0, "z1": 2900.0},
        {"x0": 21500.0, "x1": 23500.0, "z0": 900.0, "z1": 2900.0},
        {"x0": 26500.0, "x1": 28500.0, "z0": 900.0, "z1": 2900.0},
    ],
    "coverage_tolerance": 1.0,
}

DEMO_SYSTEMS = [
    {"kind": "vertical_fin", "face": "S", "per_bay": 2,
     "width": 120.0, "depth": 200.0, "avoid_openings": True},
    {"kind": "band", "face": "S", "height": 150.0, "depth": 100.0, "z_offset": 0.0},
]


# ──────────────────────────────────────────────────────────────
# 自检
# ──────────────────────────────────────────────────────────────

async def cmd_check(settings) -> int:
    print("=" * 66)
    print(f"立面智能体 · 自检  v{__version__}")
    print("=" * 66)
    print(f"配置      {settings.describe()}")

    # 1) 注册表
    print("\n[1] 注册表")
    comps = list_components()
    for spec in comps:
        print(f"    构件  {spec.kind:<16} {spec.label}  {spec.note}")
    for spec in list_measures():
        target = "—" if spec.target is None else spec.target
        print(f"    指标  {spec.name:<16} {spec.label}  达标线 {target}")
    ok_registry = bool(comps) and bool(list_measures())
    print(f"    → {'OK' if ok_registry else 'FAIL'}")

    # 2) 图能否编译
    print("\n[2] 图编译")
    hub = build_hub(settings)
    try:
        from .graphs import build_build_subgraph, build_main_graph
        sub = build_build_subgraph(settings, hub)
        main = build_main_graph(settings, hub)
        print(f"    建模子图  节点 {sorted(sub.get_graph().nodes)}")
        print(f"    主管图    节点 {sorted(main.get_graph().nodes)}")
        ok_graph = True
    except Exception as exc:
        print(f"    FAIL  {type(exc).__name__}: {exc}")
        ok_graph = False
    print(f"    → {'OK' if ok_graph else 'FAIL'}")

    # 3) MCP 健康
    print("\n[3] MCP 连接")
    health = await hub.health()
    print(f"    模式 {health['mode']} ｜ 工具 {health['tools']}")
    if health.get("names"):
        for name in health["names"][:12]:
            print(f"      · {name}")
    if health.get("note"):
        print(f"    说明 {health['note']}")

    print("\n" + "=" * 66)
    ok = ok_registry and ok_graph
    print("结论：可以继续 --demo" if ok else "结论：存在必需项未通过，请先修上面标 FAIL 的项")
    print("=" * 66)
    return 0 if ok else 1


# ──────────────────────────────────────────────────────────────
# 离线跑通建模子图
# ──────────────────────────────────────────────────────────────

async def cmd_demo(settings) -> int:
    print("=" * 66)
    print(f"建模子图 · 离线演示  v{__version__}")
    print("=" * 66)

    from .graphs import build_build_subgraph

    settings.offline = True
    hub = build_hub(settings)
    sub = build_build_subgraph(settings, hub)

    print(f"模型：三层六开间，带 {len(DEMO_MODEL_INFO['openings'])} 个窗洞")
    print(f"系统：{len(DEMO_SYSTEMS)} 个（{', '.join(s['kind'] for s in DEMO_SYSTEMS)}）")
    print(f"轮次上限 {settings.max_attempts} ｜ 覆盖率目标 {settings.coverage_target}")
    print("-" * 66)

    result = await sub.ainvoke({
        "systems": DEMO_SYSTEMS,
        "model_info": DEMO_MODEL_INFO,
        "attempt": 0,
    })

    plan = result.get("plan") or {}
    built = result.get("built") or {}
    metrics = result.get("metrics") or {}
    history = result.get("history") or []

    print(f"规划：{len(plan.get('members') or [])} 个构件，"
          f"{len(plan.get('lines') or [])} 条规律线")
    if plan.get("errors"):
        for err in plan["errors"]:
            print(f"  ! {err}")
    print(f"落地：{built.get('created', '?')} 个（模式 {built.get('mode')}）")
    print("指标：")
    for key, value in metrics.items():
        if key.endswith("__error"):
            print(f"  {key} = {value}")
        else:
            print(f"  {key} = {value}")
    print(f"判定：{result.get('verdict')}  轮次 {len(history)}")

    # 打印前 3 根构件，方便肉眼核对
    print("\n构件样本（世界坐标 mm）：")
    for m in (plan.get("members") or [])[:3]:
        print(f"  {m['kind']:<14} x={m['x']:.1f} 宽={m['width']:.0f} "
              f"z={m['z0']:.1f}..{m['z1']:.1f}")

    print("=" * 66)
    print("闭环已跑通：规划 → 执行 → 测量 → 判定。")
    print("=" * 66)
    return 0


# ──────────────────────────────────────────────────────────────
# 跑主管图全流程
# ──────────────────────────────────────────────────────────────

async def cmd_run(settings, reference: str, view: str) -> int:
    print("=" * 66)
    print(f"主管图 · 全流程  v{__version__}")
    print("=" * 66)

    from .graphs import build_main_graph

    hub = build_hub(settings)
    graph = build_main_graph(settings, hub)

    state = {
        "reference_image": reference,
        "view": view,
        "styles": ["新中式石材"],
        "model_info": DEMO_MODEL_INFO,
    }
    result = await graph.ainvoke(state, config={"recursion_limit": 50})

    print(f"阶段     {result.get('stage')}")
    print(f"构件系统 {json.dumps(result.get('systems'), ensure_ascii=False)[:300]}")
    print(f"指标     {result.get('metrics')}")
    print(f"报告     {result.get('report')}")
    return 0


# ──────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="立面智能体 · 命令行入口")
    parser.add_argument("--check", action="store_true", help="自检（不花额度）")
    parser.add_argument("--demo", action="store_true", help="离线跑通建模子图")
    parser.add_argument("--run", action="store_true", help="跑主管图全流程")
    parser.add_argument("--offline", action="store_true", help="强制离线模式")
    parser.add_argument("--reference", default="", help="参考图路径（--run 用）")
    parser.add_argument("--view", default="ELEV_S", help="目标立面")
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.offline:
        settings.offline = True
    settings.ensure_dirs()

    if args.check:
        return asyncio.run(cmd_check(settings))
    if args.demo:
        return asyncio.run(cmd_demo(settings))
    if args.run:
        return asyncio.run(cmd_run(settings, args.reference, args.view))

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())