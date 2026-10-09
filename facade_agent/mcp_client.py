# -*- coding: utf-8 -*-
"""MCP 接入层：全项目唯一与 MCP 打交道的地方。

设计原则（低耦合 + 开闭原则）
------------------------------
* 节点代码**永远不直接**连 MCP，只通过 ``McpHub``；
* 换 MCP 服务、加新 MCP 服务，只改 ``McpHub`` 的装配，节点不动；
* 内置**离线降级**：没有 Rhino / 没有 MCP 时，图依然能编译和跑单测。

两个 MCP 服务的分工
--------------------
* ``rhino``  —— Rhino 官方 MCP（MCPConnect 启动）：跑命令、建几何、截图；
* ``facade`` —— 我们自己的工具服务：控制图、转译、核对、落地、冻结。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import Settings

try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
except ImportError:  # pragma: no cover
    MultiServerMCPClient = None  # type: ignore


# ── Rhino MCP 工具白名单 ────────────────────────────────────────
# 为什么需要白名单：官方 MCP 暴露了 run_python / run_csharp（执行任意代码），
# 绝不能让 LLM 智能体自由发挥——只能走我们精选过的安全工具。
#
# 安全分级：
#   🟢 只读 / 查询类：安全，可放心开放
#   🟡 有副作用的操作类：较安全，但需要审慎使用
#   🔴 任意代码执行：**绝不开放给 LLM**（run_python, run_csharp）
#   ⚫ 内部/路由类：仅供 MCP 框架使用，不开放（_router_*）
# ──────────────────────────────────────────────────────────────────

RHINO_TOOL_ALLOWLIST = {
    # 🟢 只读 / 查询
    "get_context",           # 获取当前文档状态快照（对象/图层/视图）
    "get_viewport_image",    # 截图，供测量裁判 / 渲染验证使用
    "get_selection",         # 获取当前选中对象
    "list_objects",          # 按名称/图层/类型列出文档对象
    "get_commands",          # 查询 run_command 可用的 Rhino 命令列表

    # 🟡 有副作用的操作
    "run_command",           # 执行 Rhino 命令（立面脚本需要；facade 侧再校验步骤）
    "set_selection",         # 按 ID/名称/图层选择对象
    "save_doc",              # 保存当前文档
    "set_camera",            # 设置视口相机（位置/目标/焦距）
    "set_layer_material",    # 设置图层渲染材质（颜色/透明度等）
    "zoom_to_layer",         # 缩放到图层范围
    "zoom_to_object",        # 按 GUID 缩放到对象

    # ── 以下工具按需取消注释 ──────────────────────────────────
    # "open_doc",            # 打开 .3dm 文件（可能覆盖当前文档）
    # "close_doc",           # 关闭文档（有丢失未保存内容的风险）
    # "g1_start",            # 启动 Grasshopper
    # "g1_place_component",  # 在 GH1 画布上放置组件
    # "g1_solve_graph",      # 求解 GH 图
    # "g1_get_canvas_graph", # 获取 GH 画布结构快照
    # "g1_apply_graph",      # 一键放滑块+组件+连线
    # "g1_search_components",# 搜索 Grasshopper 组件库
    # "g1_describe_component",# 查询组件详情
    # "g1_connect",          # 连线一个输出→输入
    # "g1_connect_many",     # 批量连线
    # "g1_place_slider",     # 放置数字滑块
    # "g1_delete_component", # 删除 GH 组件
    # "g1_clear_canvas",     # 清空 GH 画布（破坏性操作！）
}


@dataclass
class McpHub:
    """管理全部 MCP 连接，并把工具交给 LangChain。

    Attributes:
        settings: 全局配置。
        offline: 离线模式（不连 MCP，返回空工具集）。
        _tools: 缓存的 LangChain 工具列表。
    """

    settings: Settings
    offline: bool = False
    _tools: list = field(default_factory=list, repr=False)
    _loaded: bool = False

    # ── 装配 ────────────────────────────────────────────────────
    def _server_config(self) -> dict[str, dict]:
        """MCP 服务清单。想加新服务，只改这里。"""
        config = {}

        # Rhino MCP 配置（支持 stdio 和 HTTP 模式）
        if self.settings.rhino_mcp_transport == "stdio":
            config["rhino"] = {
                "command": self.settings.rhino_mcp_command,
                "args": list(self.settings.rhino_mcp_args),
                "transport": "stdio",
            }
        else:
            # streamable_http 或 sse
            config["rhino"] = {
                "transport": self.settings.rhino_mcp_transport,
                "url": self.settings.rhino_mcp_url,
            }

        # facade MCP 配置（目前只用 stdio）
        config["facade"] = {
            "command": self.settings.facade_mcp_command,
            "args": list(self.settings.facade_mcp_args),
            "transport": "stdio",
        }

        return config

    # ── 取工具 ──────────────────────────────────────────────────
    async def tools(self) -> list:
        """返回全部可用的 LangChain 工具（已按白名单过滤）。

        策略：
        * 逐个连接 MCP 服务，某个服务连不上不影响其他服务；
        * Rhino MCP 和 facade MCP 的工具会合并返回。
        """
        if self.offline:
            return []
        if self._loaded:
            return self._tools
        if MultiServerMCPClient is None:  # pragma: no cover
            raise RuntimeError(
                "未安装 langchain-mcp-adapters，请先 pip install -r requirements.txt"
            )

        all_tools: list = []
        server_configs = self._server_config()

        for server_name, server_config in server_configs.items():
            try:
                client = MultiServerMCPClient({server_name: server_config})
                tools = await client.get_tools()
                all_tools.extend(tools)
            except Exception as exc:
                print(f"[MCP] ⚠️ {server_name} 连接失败: {type(exc).__name__}: {exc}")

        self._tools = [t for t in all_tools if self._is_allowed(t)]
        self._loaded = True
        return self._tools

    def _is_allowed(self, tool: Any) -> bool:
        """白名单过滤：facade 工具全放行，rhino 工具只放行白名单内的。"""
        name = getattr(tool, "name", "") or ""
        if name.startswith("facade_"):
            return True
        return name in RHINO_TOOL_ALLOWLIST

    # ── 健康检查 ────────────────────────────────────────────────
    async def health(self) -> dict[str, Any]:
        """给终端和 README 用的一句话体检。"""
        if self.offline:
            return {"mode": "offline", "tools": 0, "note": "离线模式，未连 MCP"}
        try:
            tools = await self.tools()
        except Exception as exc:
            return {"mode": "error", "tools": 0, "note": f"{type(exc).__name__}: {exc}"}
        names = sorted(getattr(t, "name", "?") for t in tools)
        return {"mode": "online", "tools": len(names), "names": names}


def build_hub(settings: Settings) -> McpHub:
    """按配置造一个 McpHub。"""
    return McpHub(settings=settings, offline=settings.offline)