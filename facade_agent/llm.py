# -*- coding: utf-8 -*-
"""模型构造：全项目唯一创建 LLM 的地方。

设计原则（开闭原则）
--------------------
* **换模型只改这里**（或改 ``.env`` 里的 ``MODEL_MAIN`` / ``MODEL_BUILD``）；
* 节点代码一律通过 ``make_model(settings, role)`` 拿模型，不自己 new；
* 想接非 OpenAI 兼容的服务时，只在这里加一个分支。

为什么分两个角色
----------------
* ``main``  —— 主管图用：读参考图、转译、流程判断，要快、要便宜；
* ``build`` —— 建模子智能体用：写几何、迭代修正，要强、要准。
两者可以指向不同模型，这是提升建模质量最直接的杠杆。
"""
from __future__ import annotations

from typing import Any

from .config import Settings

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover
    ChatOpenAI = None  # type: ignore


ROLE_MAIN = "main"
ROLE_BUILD = "build"


def model_name_for(settings: Settings, role: str) -> str:
    """按角色取模型名。新增角色时只改这个映射。"""
    mapping = {
        ROLE_MAIN: settings.model_main,
        ROLE_BUILD: settings.model_build,
    }
    return mapping.get(role, settings.model_main)


def make_model(settings: Settings, role: str = ROLE_MAIN, **overrides: Any):
    """创建一个聊天模型。

    Args:
        settings: 全局配置。
        role: ``"main"`` 或 ``"build"``。
        **overrides: 临时覆盖参数（如 ``temperature=0``）。

    Returns:
        一个 LangChain ChatModel。所有模型都走 OpenAI 兼容接口，
        因此换服务商只需改 ``LLM_BASE_URL``。
    """
    if ChatOpenAI is None:  # pragma: no cover
        raise RuntimeError("未安装 langchain-openai，请先 pip install -r requirements.txt")

    params: dict[str, Any] = {
        "model": model_name_for(settings, role),
        "base_url": settings.llm_base_url or None,
        "api_key": settings.llm_api_key or "not-needed",
        "temperature": 0.2,
        "timeout": 120,
        "max_retries": 2,
    }
    params.update(overrides)
    return ChatOpenAI(**params)


def require_api_key(settings: Settings) -> None:
    """在真正要调模型前检查密钥，给出可执行的排查提示。"""
    if settings.llm_api_key:
        return
    raise RuntimeError(
        "还没有配置模型密钥。\n"
        "  请在项目根目录建立 .env（可复制 .env.example），填入：\n"
        "    LLM_BASE_URL=https://api.a6api.com/v1\n"
        "    LLM_API_KEY=sk-你的密钥\n"
        f"  当前 base_url = {settings.llm_base_url or '(空)'}"
    )