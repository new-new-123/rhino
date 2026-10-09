# -*- coding: utf-8 -*-
"""注册表与测量指标的回归测试（不需要 Rhino、不需要密钥）。

跑法：python3 tests/test_registry_and_measures.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from facade_agent.registry import (  # noqa: E402
    get_component,
    judge,
    list_components,
    list_measures,
    register_component,
    register_measure,
    run_measures,
)
from facade_agent.tools.component_builders import _bays  # noqa: E402

MODEL = {
    "face": "S",
    "bbox": {"x0": 0.0, "x1": 30000.0, "z0": 0.0, "z1": 10500.0},
    "floors": [0.0, 3500.0, 7000.0, 10500.0],
    "bays": [2500.0, 7500.0, 12500.0, 17500.0, 22500.0, 27500.0],
    "openings": [{"x0": 1500.0, "x1": 3500.0, "z0": 900.0, "z1": 2900.0}],
    "coverage_tolerance": 1.0,
}


def test_builtin_registrations():
    """内置构件与指标必须都已注册。"""
    kinds = {c.kind for c in list_components()}
    assert "vertical_fin" in kinds, "竖向格栅未注册"
    assert "band" in kinds, "腰线未注册"
    names = {m.name for m in list_measures()}
    assert {"coverage", "conflicts", "rhythm_dev"} <= names, f"指标缺失：{names}"
    print("  [OK] 内置构件 2 个、指标 3 个都已注册")


def test_open_closed_extension():
    """开闭原则：新增构件/指标不需要改主流程。"""

    @register_component("__test_kind__", "测试构件")
    def _builder(system, model_info):
        return {"members": [{"kind": "__test_kind__", "x": 1.0, "width": 1.0,
                             "z0": 0.0, "z1": 1.0}], "lines": [1.0]}

    @register_measure("__test_metric__", "测试指标", target=0.5)
    def _metric(built, model_info):
        return 1.0

    assert get_component("__test_kind__").label == "测试构件"
    metrics = run_measures({}, MODEL)
    assert metrics.get("__test_metric__") == 1.0, "新指标没有被自动执行"
    print("  [OK] 新增构件与指标后，主流程自动生效")


def test_coverage_detects_missing_member():
    """覆盖率必须能发现"少生成了一根"。"""
    model = {**MODEL, "coverage_tolerance": 1.0}
    full = {"plan": {"lines": [100.0, 200.0, 300.0],
                     "members": [{"x": 100.0, "width": 20, "z0": 0, "z1": 10},
                                 {"x": 200.0, "width": 20, "z0": 0, "z1": 10},
                                 {"x": 300.0, "width": 20, "z0": 0, "z1": 10}]}}
    missing = {"plan": {"lines": [100.0, 200.0, 300.0],
                        "members": [{"x": 100.0, "width": 20, "z0": 0, "z1": 10},
                                    {"x": 200.0, "width": 20, "z0": 0, "z1": 10}]}}
    c_full = run_measures(full, model)["coverage"]
    c_missing = run_measures(missing, model)["coverage"]
    assert abs(c_full - 1.0) < 1e-6, f"全覆盖应为 1.0，得到 {c_full}"
    assert abs(c_missing - 2 / 3) < 1e-6, f"缺一根应为 0.667，得到 {c_missing}"
    print(f"  [OK] 覆盖率：全生成 {c_full:.3f}，缺一根 {c_missing:.3f}")


def test_conflict_detection():
    """洞口冲突必须能被发现。"""
    model = {**MODEL}
    clean = {"plan": {"members": [{"kind": "vertical_fin", "x": 1000.0,
                                   "width": 100, "z0": 0, "z1": 10500}]}}
    clash = {"plan": {"members": [{"kind": "vertical_fin", "x": 2500.0,
                                   "width": 100, "z0": 0, "z1": 10500}]}}
    assert run_measures(clean, model)["conflicts"] == 0.0, "不该冲突"
    assert run_measures(clash, model)["conflicts"] == 1.0, "该报 1 处冲突"
    print("  [OK] 洞口冲突：避开 0 处，压上去 1 处")


def test_judge_thresholds():
    """达标判据：覆盖率够、冲突为 0 才算过。"""
    ok, failures = judge({"coverage": 0.99, "conflicts": 0.0, "rhythm_dev": 0.0}, 0.95)
    assert ok and not failures, f"应达标，却报 {failures}"
    ok2, failures2 = judge({"coverage": 0.90, "conflicts": 0.0}, 0.95)
    assert not ok2 and failures2, "覆盖率不足应判未达标"
    print(f"  [OK] 判据：达标通过；未达标给出说明「{failures2[0]}」")


def test_bay_fallback():
    """没有开间数据时，应能用包围盒均分兜底。"""
    bays = _bays({"bbox": {"x0": 0, "x1": 3000, "z0": 0, "z1": 100}, "bay_count": 3})
    assert len(bays) == 3 and abs(bays[0] - 500) < 1e-6, f"兜底分间不对：{bays}"
    print(f"  [OK] 开间兜底：{bays}")


def main() -> int:
    print("=" * 60)
    print("注册表与测量 · 回归测试")
    print("=" * 60)
    tests = [
        test_builtin_registrations,
        test_open_closed_extension,
        test_coverage_detects_missing_member,
        test_conflict_detection,
        test_judge_thresholds,
        test_bay_fallback,
    ]
    failed = 0
    for t in tests:
        try:
            t()
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
    sys.exit(main())