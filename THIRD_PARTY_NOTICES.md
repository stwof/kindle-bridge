# 第三方组件与数据声明

本项目自身的代码采用 [MIT 许可证](LICENSE)。下列第三方组件与数据**各自遵循其原有许可**，
本项目不做任何破解，也不改变它们的授权条件。

## 随包分发

| 组件 | 用途 | 许可 | 位置 |
|---|---|---|---|
| [OpenCC](https://github.com/BYVoid/OpenCC) (BYVoid) | 简繁转换字典与算法 | Apache-2.0 | 桌面端经 `opencc-python-reimplemented` 依赖引入；小程序端 `miniprogram/vendor/t2cn.js`、`miniprogram/pkg-trad/vendor/cn2t.js` |
| [opencc-python-reimplemented](https://pypi.org/project/opencc-python-reimplemented/) | OpenCC 的纯 Python 移植（桌面端唯一第三方依赖） | MIT | 由 `pip install -r requirements.txt` 安装 |
| [fflate](https://github.com/101arrowz/fflate) | 小程序端 EPUB 的 zip 读写 | MIT | `miniprogram/vendor/fflate.js` |

## 可选功能依赖（pip 安装，不随包分发）

| 组件 | 用途 | 许可 | 获取方式 |
|---|---|---|---|
| [Coqui TTS](https://github.com/coqui-ai/TTS) | 「朗读」页的本地语音合成引擎（PyTorch 实现） | MPL-2.0 | `pip install -r requirements-tts.txt`（需 Python 3.9~3.11） |
| [PyTorch](https://github.com/pytorch/pytorch) | Coqui TTS 的深度学习框架 | BSD-3-Clause | 随 `TTS` 一并安装 |

> 「朗读」是**可选功能**：核心程序不依赖它，仓库里也不打包它的代码与模型。
> 语音模型（Baker / YourTTS / LJSpeech 等）在用户首次使用时由 Coqui 自动下载，
> 各自遵循其原有许可（多为 CC / 研究用途许可，详见 Coqui 官方模型卡），请按需合规使用。
> 模型文件默认缓存在本机 `~/.local/share/tts`，本项目不托管、不分发任何模型权重。

许可证原文：
- Coqui TTS：<https://github.com/coqui-ai/TTS/blob/main/LICENSE.txt>
- PyTorch：<https://github.com/pytorch/pytorch/blob/main/LICENSE>


- OpenCC / opencc-js：`miniprogram/vendor/LICENSES/opencc-js-LICENSE.txt`
- opencc-js 的第三方许可汇总：`miniprogram/vendor/LICENSES/opencc-js-THIRD_PARTY_LICENSES.md`
- fflate：`miniprogram/vendor/LICENSES/fflate-LICENSE.txt`

## 需要时自行下载（不随包分发）

| 数据 | 用途 | 许可 | 获取方式 |
|---|---|---|---|
| [CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cc-cedict) | 中英词典，用于生成 KOReader 划词查词的 StarDict 字典 | CC BY-SA 4.0 | `python kindle/dictbuild.py` 自行下载 |
| [chinese-poetry](https://github.com/chinese-poetry/chinese-poetry) | 中文诗词与四书五经语料，用于「中文经典」文库 | MIT | `python _tools/fetch-chinese-poetry.py` 自行下载 |

## 外部服务与工具

| 名称 | 用途 | 说明 |
|---|---|---|
| [Project Gutenberg](https://www.gutenberg.org/) | 英文/外文公版书检索与取回 | 遵守其使用条款，仅限个人阅读 |
| [Standard Ebooks](https://standardebooks.org/) | 精校公版书检索与取回 | GPL-3.0（其电子书内容多为公有领域） |
| [Calibre](https://calibre-ebook.com/) | EPUB → AZW3 转换 | 第三方独立软件，本项目只调用其命令行，不改动其代码 |
| 亚马逊 Send to Kindle | 官方云端投递 | 本项目只生成待发邮件或打开官方网页，不经手账号与密码 |

## 版权声明

本仓库**不包含任何受版权保护的书籍正文**。公版书由用户自行从上述公开书源获取，
本项目只提供检索与取回的工具。所有第三方商标归其各自所有者所有。
