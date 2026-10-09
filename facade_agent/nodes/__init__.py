# -*- coding: utf-8 -*-
"""节点包：每个节点一个工厂函数，依赖由外部注入。"""
from . import build, main  # noqa: F401

__all__ = ["build", "main"]