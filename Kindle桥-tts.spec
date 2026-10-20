# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 把 TTS（Coqui TTS + PyTorch）也打进单文件 exe。

⚠️ 这是「朗读」功能的**全内置**变体，和默认的 Kindle桥.spec 二选一：
    · 默认 spec：体积小（~10 MB），但「朗读」需要先 pip install -r requirements-tts.txt。
    · 本 spec ：把 Coqui TTS + PyTorch 全打进去，exe 双击即用、无需装 Python，
                但体积会变成几百 MB ~ 1 GB+，构建也更慢。

仅当你想要一个「什么依赖都不用装」的朗读版时才用：
    pyinstaller "Kindle桥-tts.spec"

注意：
  · Coqui TTS 只支持 Python 3.9 ~ 3.11，请用对应版本的解释器来打包。
  · 语音模型文件本身**不打进 exe**（太大且随版本变），仍是首次使用时自动下载缓存。
"""
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

BASE = os.path.abspath(os.getcwd())

_opencc_datas = collect_data_files("opencc")
_opencc_hidden = collect_submodules("opencc")

# Coqui TTS 与其依赖（PyTorch 等）的数据与子模块，必须收集，否则 exe 起来 import 失败。
_tts_datas = collect_data_files("TTS")
_tts_hidden = collect_submodules("TTS")

a = Analysis(
    ["app.py"],
    pathex=[BASE],
    binaries=[],
    datas=[
        (os.path.join(BASE, "web"), "web"),
        (os.path.join(BASE, "kindle", "data"), "kindle/data"),
    ] + _opencc_datas + _tts_datas,
    hiddenimports=_opencc_hidden + _tts_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "pytest", "setuptools",
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
    name="Kindle桥-带朗读",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
