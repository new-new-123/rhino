# -*- coding: utf-8 -*-
"""配置：全项目唯一的配置来源。

设计原则（开闭原则 + 低耦合）
------------------------------
* 想换模型、换 MCP 地址、换工作区，**只改这一个文件或环境变量**；
* 其它模块一律通过 ``load_settings()`` 拿配置，**不自己读环境变量**；
* 新增配置项时，只在 ``Settings`` 加一个字段 + 在 ``load_settings()`` 加一行，
  调用方不受影响。

环境变量与默认值见同目录上级的 ``.env.example``。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # dotenv 是可选的，没装也能跑
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_args, **_kwargs):
        return False


def _as_bool(text: str, default: bool = False) -> bool:
    if text is None or text == "":
        return default
    return text.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_json_list(text: str, default: list) -> list:
    """把 ``'["a","b"]'`` 解析成 list；解析失败就用默认值。"""
    if not text:
        return list(default)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return list(default)
    return value if isinstance(value, list) else list(default)


@dataclass
class Settings:
    """一次运行的全部参数。"""

    # ── 工作区 ──────────────────────────────────────────────────
    workspace: Path = Path(".")

    # ── 模型 ────────────────────────────────────────────────────
    llm_base_url: str = ""
    llm_api_key: str = ""
    model_main: str = "gemini-2.5-flash"
    model_build: str = "claude-sonnet-4-5"

    # ── Rhino 官方 MCP ──────────────────────────────────────────
    rhino_mcp_transport: str = "streamable_http"  # stdio | streamable_http | sse
    rhino_mcp_url: str = "http://localhost:10500/"  # HTTP 模式下的地址
    rhino_mcp_command: str = "uvx"  # stdio 模式下的命令
    rhino_mcp_args: list = field(default_factory=lambda: ["rhinomcp@latest"])  # stdio 模式下的参数

    # ── facade MCP（我们的工具服务）─────────────────────────────
    facade_mcp_command: str = "python"
    facade_mcp_args: list = field(default_factory=lambda: ["-m", "facade_mcp_server"])

    # ── 运行参数 ────────────────────────────────────────────────
    max_attempts: int = 3
    coverage_target: float = 0.95
    offline: bool = False

    # ── 派生目录（与已有工具链的目录约定保持一致）────────────────
    @property
    def dirs(self) -> dict:
        root = Path(self.workspace)
        return {
            "root": root,
            "skin": root / "01_skin",
            "views": root / "02_views",
            "control": root / "03_control",
            "ai_input": root / "04_ai_input",
            "material": root / "05_material",
            "reference": root / "11_reference",
            "components": root / "components.json",
            "logs": root / "logs",
            "runs": root / "runs",
        }

    def ensure_dirs(self) -> None:
        """把需要的目录都建出来（幂等）。"""
        for key in ("skin", "views", "control", "ai_input", "material", "reference", "logs", "runs"):
            self.dirs[key].mkdir(parents=True, exist_ok=True)

    def describe(self) -> str:
        """给终端看的一行摘要。"""
        return (
            f"工作区 {self.workspace} ｜ 主管模型 {self.model_main} ｜ "
            f"建模模型 {self.model_build} ｜ 轮次上限 {self.max_attempts} ｜ "
            f"覆盖率目标 {self.coverage_target} ｜ 离线 {self.offline}"
        )


def load_settings(env_file: str | os.PathLike | None = None) -> Settings:
    """从 ``.env`` + 环境变量装载配置。

    优先级：显式环境变量 > ``.env`` 文件 > 代码默认值。
    """
    load_dotenv(dotenv_path=env_file, override=False)

    workspace = os.getenv("FACADE_WORKSPACE", "").strip()
    settings = Settings(
        workspace=Path(workspace) if workspace else Path("."),
        llm_base_url=os.getenv("LLM_BASE_URL", "").strip(),
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        model_main=os.getenv("MODEL_MAIN", "gemini-2.5-flash").strip(),
        model_build=os.getenv("MODEL_BUILD", "claude-sonnet-4-5").strip(),
        rhino_mcp_transport=os.getenv("RHINO_MCP_TRANSPORT", "streamable_http").strip(),
        rhino_mcp_url=os.getenv("RHINO_MCP_URL", "http://localhost:10500/").strip(),
        rhino_mcp_command=os.getenv("RHINO_MCP_COMMAND", "uvx").strip(),
        rhino_mcp_args=_as_json_list(os.getenv("RHINO_MCP_ARGS"), ["rhinomcp@latest"]),
        facade_mcp_command=os.getenv("FACADE_MCP_COMMAND", "python").strip(),
        facade_mcp_args=_as_json_list(os.getenv("FACADE_MCP_ARGS"), ["-m", "facade_mcp_server"]),
        max_attempts=int(os.getenv("MAX_ATTEMPTS", "3")),
        coverage_target=float(os.getenv("COVERAGE_TARGET", "0.95")),
        offline=_as_bool(os.getenv("FACADE_OFFLINE"), False),
    )
    return settings