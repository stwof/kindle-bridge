# -*- coding: utf-8 -*-
"""统一的路径：把「只读资源」和「用户可写数据」分开。

为什么必须分开：
  正常运行时两者都在项目目录下（web/、kindle/data/ 是资源；导出/、收书/、
  工具/ 是数据）。但打成单文件 exe 后，资源被 PyInstaller 解包到临时的
  sys._MEIPASS —— 那是只读、且程序退出就没了的临时目录。
  所以：
    resource_dir()  只读资源（web/、kindle/data/）—— 冻结时在 _MEIPASS
    data_dir()      用户数据（导出/、收书/、工具/）—— 冻结时在 exe 旁边
  两者在源码运行模式下是同一个目录，行为不变。
"""
from __future__ import annotations

import os
import sys


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> str:
    """只读资源根目录：web/、kindle/data/ 都在这下面。"""
    if _frozen():
        # PyInstaller onefile：解包出来的临时目录
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return meipass
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    """用户可写数据根目录：导出/、收书/、工具/ 都在这下面。"""
    if _frozen():
        # 冻结后：exe 所在目录（用户能看见、能放书的地方）
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sub(*parts: str) -> str:
    """data_dir 下的子目录，顺手建好。"""
    p = os.path.join(data_dir(), *parts)
    os.makedirs(p, exist_ok=True)
    return p
