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


# 允许被智能体调用的 Rhino 官方 MCP 工具白名单。
# 为什么需要白名单：官方 MCP 暴露了 run_command / 执行任意代码的能力，
# 绝不能让智能体自由发挥——只能走我们注册过的动作。
RHINO_TOOL_ALLOWLIST = {
    "run_command",          # 跑我们自己的脚本（步骤白名单在 facade 侧再校验）
    "capture_viewport",     # 截图，供测量裁判使用
    "get_objects",          # 读对象
    "get_object_info",      # 读对象详情
    "select_objects",
    "create_layer",
    "update_object_attributes",
    "get_document_summary",
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
        return {
            "rhino": {
                "command": self.settings.rhino_mcp_command,
                "args": list(self.settings.rhino_mcp_args),
                "transport": "stdio",
            },
            "facade": {
                "command": self.settings.facade_mcp_command,
                "args": list(self.settings.facade_mcp_args),
                "transport": "stdio",
            },
        }

    # ── 取工具 ──────────────────────────────────────────────────
    async def tools(self) -> list:
        """返回全部可用的 LangChain 工具（已按白名单过滤）。"""
        if self.offline:
            return []
        if self._loaded:
            return self._tools
        if MultiServerMCPClient is None:  # pragma: no cover
            raise RuntimeError(
                "未安装 langchain-mcp-adapters，请先 pip install -r requirements.txt"
            )
        client = MultiServerMCPClient(self._server_config())
        raw = await client.get_tools()
        self._tools = [t for t in raw if self._is_allowed(t)]
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