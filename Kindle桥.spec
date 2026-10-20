# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 打成一个可以直接双击的单文件 exe。

    pip install pyinstaller
    pyinstaller Kindle桥.spec

产物在 dist/。用户只需要这一个文件，不需要装 Python。

分界（由 kindle/paths.py 统一管）：
  只读资源 web/、kindle/data/  →  打进 exe，运行时解包到临时目录
  用户数据 收书/、导出/、工具/  →  不打包，运行时落在 exe 旁边
所以把 exe 放哪儿，用户就在那儿放书、拿结果。
"""
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

BASE = os.path.abspath(os.getcwd())

# OpenCC 的配置与词表是包内的 .json / .txt 数据文件，PyInstaller 不会自动收。
# opencc.py 里用 os.path.dirname(__file__) 定位它们，所以必须按包原样布局放进去，
# 否则 exe 起来会「找不到 dictionary/STCharacters.txt」。
_opencc_datas = collect_data_files("opencc")
_opencc_hidden = collect_submodules("opencc")

a = Analysis(
    ["app.py"],
    pathex=[BASE],
    binaries=[],
    datas=[
        (os.path.join(BASE, "web"), "web"),              # 前端资源
        (os.path.join(BASE, "kindle", "data"), "kindle/data"),  # 简繁词表（OpenCC 装不上时的兜底）
    ] + _opencc_datas,
    hiddenimports=_opencc_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 这些用不上，别让 exe 白胖
        "tkinter", "matplotlib", "numpy", "PIL", "pytest", "setuptools",
        "pip", "wheel", "sqlite3.test",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Kindle桥",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # 保留控制台：用户看得见启动信息与报错
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
