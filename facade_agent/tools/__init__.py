# -*- coding: utf-8 -*-
"""工具包。

**重要**：这里必须 import 各实现模块，否则 ``@register_component`` /
``@register_measure`` 装饰器不会执行，注册表就是空的。
新增工具模块时，记得在这里加一行 import（这是本包唯一的修改点）。
"""
from . import component_builders, measure_tools  # noqa: F401

__all__ = ["component_builders", "measure_tools"]