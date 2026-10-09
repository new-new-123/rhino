# -*- coding: utf-8 -*-
"""主管图的节点：读参考图 → 出方案 → 转译 → （子图）→ 冻结 → 报告。

约定
----
* 每个节点都是「工厂函数 → 节点函数」，依赖由外部注入（可测试、可替换）；
* 每个节点都有**离线分支**：没有 Rhino / 没有密钥时图依然能跑通，
  这样 VS Code 里第一次运行就能看到完整流程，不必先解决所有环境问题。
"""
from __future__ import annotations

import json
from typing import Callable

from ..config import Settings
from ..mcp_client import McpHub

# ──────────────────────────────────────────────────────────────
# 1) 读参考图：效果图 → 结构化描述
# ──────────────────────────────────────────────────────────────

READ_PROMPT = """你在读一张建筑立面效果图。请只输出 JSON，不要解释。

输出格式：
{
  "floors": 层数（整数）,
  "bays": 每层开间数（整数）,
  "systems": [
    {"kind": "构件类型", "label": "中文名", "reason": "为什么这样判断"}
  ],
  "materials": ["主材描述"],
  "note": "一句话总结设计语言"
}

注意：只描述你**确实看到**的内容；看不清的字段填 null，不要猜。
"""


def make_read_reference_node(settings: Settings) -> Callable:
    async def read_reference(state: dict) -> dict:
        path = state.get("reference_image", "")
        if settings.offline or not path:
            return {"model_info": {**(state.get("model_info") or {}),
                                   "read_mode": "offline",
                                   "read_note": "离线模式：跳过读图，沿用已有模型信息"}}

        from ..llm import ROLE_MAIN, make_model, require_api_key

        require_api_key(settings)
        import base64
        import pathlib

        raw = pathlib.Path(path).read_bytes()
        b64 = base64.b64encode(raw).decode()
        model = make_model(settings, ROLE_MAIN, temperature=0)
        msg = model.invoke([
            ("system", READ_PROMPT),
            ("user", [
                {"type": "text", "text": "这是参考图："},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]),
        ])
        try:
            desc = json.loads(_strip_fence(msg.content))
        except Exception:
            desc = {"raw": str(msg.content)[:2000]}
        return {"model_info": {**(state.get("model_info") or {}), "reference_read": desc}}

    return read_reference


# ──────────────────────────────────────────────────────────────
# 2) 出风格方案（这一步用生图模型，交给已有 06 脚本 / facade MCP）
# ──────────────────────────────────────────────────────────────

def make_generate_schemes_node(settings: Settings, hub: McpHub) -> Callable:
    async def generate_schemes(state: dict) -> dict:
        if hub.offline:
            return {"schemes": [{"name": "（离线）跳过出图", "path": ""}]}
        # 在线时走 facade MCP 的 facade_generate_schemes 工具
        tools = {getattr(t, "name", ""): t for t in await hub.tools()}
        tool = tools.get("facade_generate_schemes")
        if tool is None:
            return {"schemes": [], "stage": "generate:no-tool"}
        out = await tool.ainvoke({
            "view": state.get("view", "ELEV_S"),
            "styles": state.get("styles") or [],
        })
        return {"schemes": out if isinstance(out, list) else [out]}

    return generate_schemes


# ──────────────────────────────────────────────────────────────
# 3) 参考图 → 构件系统与参数
# ──────────────────────────────────────────────────────────────

TRANSLATE_PROMPT = """你把一张立面效果图翻译成「构件系统 + 参数」，供程序在 Rhino 里生成几何。

只输出 JSON：
{
  "systems": [
    {
      "kind": "vertical_fin 或 band",
      "face": "S",
      "per_bay": 2,
      "width": 120,
      "depth": 200,
      "avoid_openings": true
    }
  ],
  "note": "一句话说明"
}

可用的 kind 只有：vertical_fin（竖向格栅）、band（水平腰线）。
参数含义：per_bay 每开间根数、width 构件宽度 mm、depth 出挑 mm。
不要输出坐标——坐标由程序按模型真实尺寸计算。
"""


def make_translate_reference_node(settings: Settings) -> Callable:
    async def translate_reference(state: dict) -> dict:
        if settings.offline:
            # 离线：给一份能跑通的默认系统，用于验证链路
            systems = [{
                "kind": "vertical_fin", "face": state.get("view", "ELEV_S"),
                "per_bay": 1, "width": 120, "depth": 200, "avoid_openings": True,
            }]
            return {"systems": systems, "stage": "translate:offline"}

        from ..llm import ROLE_MAIN, make_model, require_api_key

        require_api_key(settings)
        model = make_model(settings, ROLE_MAIN, temperature=0)
        msg = model.invoke([
            ("system", TRANSLATE_PROMPT),
            ("user", json.dumps({
                "立面": state.get("view", "ELEV_S"),
                "读图结果": (state.get("model_info") or {}).get("reference_read"),
            }, ensure_ascii=False)),
        ])
        try:
            data = json.loads(_strip_fence(msg.content))
        except Exception:
            data = {"systems": [], "error": "模型没有返回合法 JSON"}
        return {"systems": data.get("systems") or [], "stage": "translate:done"}

    return translate_reference


# ──────────────────────────────────────────────────────────────
# 4) 冻结（需人工确认，在图上用中断点实现）
# ──────────────────────────────────────────────────────────────

def make_freeze_node(settings: Settings, hub: McpHub) -> Callable:
    async def freeze(state: dict) -> dict:
        if hub.offline:
            return {"stage": "freeze:offline"}
        tools = {getattr(t, "name", ""): t for t in await hub.tools()}
        tool = tools.get("facade_freeze")
        if tool is None:
            return {"stage": "freeze:no-tool"}
        await tool.ainvoke({"system": state.get("view", ""), "mode": "freeze"})
        return {"stage": "freeze:done"}

    return freeze


# ──────────────────────────────────────────────────────────────
# 5) 报告：给人看的一句话总结
# ──────────────────────────────────────────────────────────────

def make_report_node(settings: Settings) -> Callable:
    async def report(state: dict) -> dict:
        metrics = state.get("metrics") or {}
        build = state.get("build_result") or {}
        attempts = len((build.get("history") or [])) or 1
        head = (
            f"立面 {state.get('view', '?')}："
            f"生成构件 {(build.get('built') or {}).get('created', '?')} 个，"
            f"迭代 {attempts} 轮，"
            f"覆盖率 {_fmt(metrics.get('coverage'))}，"
            f"洞口冲突 {_fmt(metrics.get('conflicts'))}。"
        )
        verdict = (build.get("verdict") or "").lower()
        tail = {
            "ok": "已达标，可交付。",
            "retry": "未达标，已用完轮次，建议人工检查参数。",
            "escalate": "未达标，已交人工，详见 runs 下的指标记录。",
        }.get(verdict, "")
        text = head + tail
        return {"report": text, "stage": "report:done"}

    return report


# ──────────────────────────────────────────────────────────────
# 小工具
# ──────────────────────────────────────────────────────────────

def _strip_fence(text: str) -> str:
    """去掉模型爱加的 ```json 围栏。"""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _fmt(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)