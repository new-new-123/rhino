# -*- coding: utf-8 -*-
"""图结构冒烟测试：验证两张图能编译、子图闭环能跑通、轮次上限生效。

跑法：python3 tests/test_graph_smoke.py
不需要 Rhino、不需要密钥（全程离线）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from facade_agent.config import Settings  # noqa: E402
from facade_agent.graphs import build_build_subgraph, build_main_graph  # noqa: E402
from facade_agent.mcp_client import build_hub  # noqa: E402

MODEL = {
    "face": "S",
    "bbox": {"x0": 0.0, "x1": 30000.0, "z0": 0.0, "z1": 10500.0},
    "floors": [0.0, 3500.0, 7000.0, 10500.0],
    "bays": [2500.0, 7500.0, 12500.0, 17500.0, 22500.0, 27500.0],
    "openings": [{"x0": 1500.0, "x1": 3500.0, "z0": 900.0, "z1": 2900.0}],
    "coverage_tolerance": 1.0,
}

GOOD_SYSTEMS = [
    {"kind": "vertical_fin", "face": "S", "per_bay": 1, "width": 120.0,
     "depth": 200.0, "avoid_openings": True},
]

# 故意用一个"生成不出任何构件"的系统，触发未达标 → 重试 → 超限
BAD_SYSTEMS = [
    {"kind": "vertical_fin", "face": "S", "per_bay": 1, "width": 120.0,
     "depth": 200.0, "avoid_openings": True, "z0": 0, "z1": 0},
]


def _settings(offline=True, max_attempts=3):
    s = Settings(offline=offline, max_attempts=max_attempts, coverage_target=0.95)
    return s


async def test_subgraph_ok():
    s = _settings()
    sub = build_build_subgraph(s, build_hub(s))
    out = await sub.ainvoke({"systems": GOOD_SYSTEMS, "model_info": MODEL, "attempt": 0})
    assert out["verdict"] == "ok", f"应达标，得到 {out['verdict']}"
    assert out["metrics"]["coverage"] == 1.0
    assert out["metrics"]["conflicts"] == 0.0
    assert len(out["history"]) == 1, "达标应只跑 1 轮"
    print(f"  [OK] 达标路径：{out['verdict']}，{len(out['history'])} 轮，指标 {out['metrics']}")


async def test_subgraph_retry_then_escalate():
    """未达标时必须重试到上限，然后交人工——不能无限循环，也不能静默结束。"""
    s = _settings(max_attempts=3)
    sub = build_build_subgraph(s, build_hub(s))
    # 构造一个"有要求但一根也生成不出来"的场景：整面墙都被洞口占满，
    # 竖挺被逐根裁掉 → 规律线有 3 条，实际构件 0 根 → 覆盖率 0。
    blocked_model = {
        "face": "S",
        "bbox": {"x0": 0.0, "x1": 3000.0, "z0": 0.0, "z1": 100.0},
        "bays": [500.0, 1500.0, 2500.0],
        "openings": [{"x0": 0.0, "x1": 3000.0, "z0": 0.0, "z1": 100.0}],
        "coverage_tolerance": 1.0,
    }
    out = await sub.ainvoke({
        "systems": [{"kind": "vertical_fin", "face": "S", "per_bay": 1,
                     "width": 120.0, "avoid_openings": True}],
        "model_info": blocked_model,
        "attempt": 0,
    })
    assert out["verdict"] == "escalate", f"应升级交人工，得到 {out['verdict']}"
    assert len(out["history"]) == 3, f"应跑满 3 轮，实际 {len(out['history'])}"
    assert out["metrics"]["coverage"] == 0.0, f"覆盖率应为 0，得到 {out['metrics']}"
    print(f"  [OK] 未达标路径：{out['verdict']}，{len(out['history'])} 轮后交人工")


async def test_unknown_kind_is_reported():
    """未注册的构件类型要被记录，而不是静默丢弃。"""
    s = _settings()
    sub = build_build_subgraph(s, build_hub(s))
    out = await sub.ainvoke({
        "systems": [{"kind": "__不存在__"}], "model_info": MODEL, "attempt": 0})
    errors = (out.get("plan") or {}).get("errors") or []
    assert errors, "未注册类型应报错"
    print(f"  [OK] 未注册类型被记录：{errors[0][:40]}…")


async def test_main_graph_compiles_and_runs():
    s = _settings(offline=True)
    hub = build_hub(s)
    graph = build_main_graph(s, hub)
    nodes = set(graph.get_graph().nodes)
    for expect in ("read_reference", "generate_schemes", "translate_reference",
                   "build", "freeze", "report"):
        assert expect in nodes, f"主管图缺少节点 {expect}"
    out = await graph.ainvoke({
        "reference_image": "", "view": "ELEV_S", "styles": ["新中式石材"],
        "model_info": MODEL,
    })
    assert out.get("report"), "报告节点没有产出"
    print(f"  [OK] 主管图跑通：{out['report']}")


async def main() -> int:
    print("=" * 60)
    print("图结构 · 冒烟测试")
    print("=" * 60)
    tests = [
        test_subgraph_ok,
        test_subgraph_retry_then_escalate,
        test_unknown_kind_is_reported,
        test_main_graph_compiles_and_runs,
    ]
    failed = 0
    for t in tests:
        try:
            await t()
        except AssertionError as exc:
            failed += 1
            print(f"  [FAIL] {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [ERROR] {t.__name__}: {type(exc).__name__}: {exc}")
    print("-" * 60)
    print(f"共 {len(tests)} 项，失败 {failed} 项")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
