# -*- coding: utf-8 -*-
"""立面智能体：LangGraph 主管图 + 建模子图 + MCP 工具层。

分层（高内聚低耦合）
--------------------
    config.py        配置（唯一来源）
    state.py         状态（图的契约）
    llm.py           模型（换模型只改这里）
    registry.py      注册表（构件类型 / 测量指标，开闭原则的落点）
    mcp_client.py    MCP 接入（唯一与 MCP 打交道的地方）
    tools/           工具实现（构件 builder、测量工具）
    nodes/           节点（每个节点一个函数）
    graphs/          图（只管连线，不含业务）
    cli.py           命令行入口

快速自检::

    python -m facade_agent.cli --check
"""
__version__ = "0.1.0"

# 关键：导入 tools 包会执行 @register_component / @register_measure 装饰器，
# 注册表才不会是空的。放在包入口，任何 `import facade_agent` 都会自动注册。
from . import tools  # noqa: E402,F401
