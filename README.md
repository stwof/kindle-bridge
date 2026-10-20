# Kindle 桥

> 把 Kindle 里的书、标注、生词，搬到你自己的电脑和常用阅读器里。
> 纯本地运行，数据不出机器，MIT 开源。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![OpenCC](https://img.shields.io/badge/OpenCC-BYVoid-green.svg)](https://github.com/BYVoid/OpenCC)

---

## 这是什么

Kindle 是很好的阅读器，但封闭：标注锁在设备里，生词进不了其他 App，EPUB 也不认。
Kindle 桥在你本机开一个小服务，用数据线连上 Kindle 后，把这些内容整理成
**Markdown / CSV / JSON / AZW3 / 微信读书可读的格式**，直接落在你的硬盘上。

一句话：**数据还在你手里，只是换个更好用的格式。**

## 它能做什么

| 模块 | 干什么 | 产物落在哪 |
|---|---|---|
| **书库** | 扫描 Kindle 上的书，筛出「微信读书不兼容」的，一键导出 | `导出/微信读书/` |
| **书籍投递** | EPUB/MOBI/AZW3 投进设备，四条路线任选 | `收书/` → 设备 `documents/` |
| **简繁转换** | EPUB / TXT 在**简体 ↔ 繁体**之间互转 | 下载或 `导出/简繁转换/` |
| **公版书库** | 检索并取回 Gutenberg / Standard Ebooks / 中文经典 | `收书/` |
| **标注** | 解析 `My Clippings.txt`，导出笔记 | `导出/标注/` |
| **生词** | 解析 `vocab.db`，导出 CSV / Anki 词库 | `导出/生词/` |
| **使用说明** | 页面内图文教程 | — |

### 简繁转换（内置 OpenCC 字典）

古登堡的中文藏书几乎全是**繁体**（古典小说居多，多由港台或海外志愿者数字化）。
这个模块用 [OpenCC](https://github.com/BYVoid/OpenCC) —— 中文简繁转换的事实标准 ——
做双向转换：

- **繁 → 简**：标准 `t2s`
- **简 → 繁**：台湾正体 `s2twp`（输出「裡面 / 網路 / 軟體 / 資訊」，最贴近繁体读物习惯）

除了 OpenCC 自带的数据表，还额外补了它漏掉的**冷僻字与异体字**：

| 异体 | 简体 | 说明 |
|---|---|---|
| 擡 | 抬 | 扛擡 |
| 舖 | 铺 | 粮食舖子 |
| 薴 | 苎 | 补上 OpenCC 断掉的第二跳 |
| 恠 / 竝 / 靑 / 羣 / 秌 / 僊 | 怪 / 并 / 青 / 群 / 秋 / 仙 | 古典常见异体 |
| 乾坤 / 乾红 | **保持「乾」** | 转成「干坤」是错的 |
| 變徵 | **保持「徵」** | 五声音阶「宫商角徵羽」的徵(zhǐ)不是「征」 |

效果：以《警世通言》《红楼梦》为例，转换后残留的繁体**只剩「乾坤」这类本就应当保留的字**。

TXT 会自动嗅探编码（UTF-8 / GB18030 / Big5），不用先转码。
EPUB 转换**只动文本节点**，标签、样式、脚本、图片、字体一律原样，产出仍是结构合法的容器。

## 快速开始

### Windows

1. 双击 **`启动 Kindle桥.bat`**
   （首次运行会自动装依赖；没装 Python 会提示你去官网下载）
2. 浏览器自动打开 `http://127.0.0.1:8765/`
3. 用数据线把 Kindle 连上，**点一下 Kindle 上的「允许 USB 连接」**

### macOS / Linux

```bash
chmod +x start.sh
./start.sh            # 指定端口： ./start.sh 9000
```

### 手动启动

```bash
pip install -r requirements.txt
python app.py --port 8765 --host 127.0.0.1
```

参数：`--port` 端口（默认 8765）、`--host` 绑定地址（默认仅本机）、`--no-browser` 不自动开浏览器。

### 微信小程序

`miniprogram/` 下有一个**纯端内运行**的微信小程序，功能与网页版的「简繁转换 / 标注 / 生词」对应。
详见 [`miniprogram/README.md`](miniprogram/README.md)。

> 小程序跑在手机上，**碰不到插在电脑上的 Kindle**，所以「投递到设备」这类操作仍然只能在桌面端做。
> 小程序的价值是：手机上一键转简繁、随手解析标注和生词。

## 目录结构

```
kindle-bridge/
├── app.py                  # 主服务（标准库 http.server，无 Web 框架）
├── kindle/                 # 各功能模块
│   ├── paths.py            # 资源目录 / 数据目录分离（为单文件 exe 准备）
│   ├── hanzi.py            # 简繁转换内核（OpenCC + 异体补丁 + 短语保护）
│   ├── epub.py             # EPUB 容器读写、简繁转换、EPUB 体检
│   ├── zhconv_file.py      # 文件级转换入口（EPUB / TXT）
│   ├── device.py           # Kindle USB 设备识别（ctypes 直连）
│   ├── clippings.py        # My Clippings.txt 解析
│   ├── vocab.py            # vocab.db（SQLite）解析
│   ├── library.py          # 设备书库扫描
│   ├── deliver.py          # 投递到设备（AZW3 转换、拷贝）
│   ├── calibre.py          # Calibre 检测 / 安装包下载 / 命令行调用
│   ├── freebooks.py        # Gutenberg / Standard Ebooks 检索取回
│   ├── classics.py         # 中文经典（chinese-poetry 语料）
│   ├── dictbuild.py        # 生成 KOReader 划词查词用的 StarDict 字典
│   └── data/               # 自带词表（OpenCC 装不上时的兜底）
├── web/                    # 前端（原生 HTML/CSS/JS，无框架无构建）
├── miniprogram/            # 微信小程序源码
├── _test/                  # 回归测试
├── _tools/                 # 抓取语料、打发布包
├── 收书/                    # ← 放电子书，工具会从这里取
└── 导出/                    # ← 所有产物都落在这里
```

**数据目录约定**：`收书/` 放待投递的书，`导出/` 放产物。都是普通文件夹，随时可以直接打开。

## 常见操作

### 把 EPUB 投进 Kindle

Kindle **原生不认 EPUB**，硬拷 `documents/` 是没用的（系统根本不索引它）。四条路线：

| 路线 | 做法 | 适合 |
|---|---|---|
| **A（推荐）** | 本地转 AZW3 → 拷进设备 | 离线、不碰账号、排版可控 |
| **B** | Send to Kindle 网页 / 邮件 | 零安装，但要联网、要用 `@kindle.com` 地址 |
| **C** | 越狱 + KOReader | 排版、词典、PDF 重排最好，代价是折腾 |
| **D** | MOBI 家族直接拷 | `.mobi/.azw/.azw3/.prc` 本来就能读，零转换 |

路线 A 需要本机装 [Calibre](https://calibre-ebook.com/)（免费），工具会引导你下载官方安装包，
**不静默安装**：不写注册表、不改 PATH，最后一步交给你自己点。

### 给 KOReader 做划词查词字典

```bash
python kindle/dictbuild.py
```

从公开词表 [CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cc-cedict) 打包出两部
**StarDict** 字典 —— 简体词头版（读简体书用）与繁體词头版（读繁体公版书用），
含拼音与释义。生成后把 `字典/` 下两个子文件夹整体拷进 KOReader 的 `dicts/` 目录即可。

> 词库需在**能联网**的机器上生成；本机若装不了 OpenCC，转换会退回内置小词表。

### 补齐中文经典语料

```bash
python _tools/fetch-chinese-poetry.py
```

下载 [chinese-poetry](https://github.com/chinese-poetry/chinese-poetry)（MIT）正文数据，
支持断点续传，中断后再跑一次即可。

## 开发与测试

```bash
python _test/test-hanzi.py     # 繁简转换 + EPUB 体检
python _test/test-zhconv.py    # 简繁转换全链路（含 HTTP 端到端）
```

两个脚本都是零依赖的，直接跑就行，失败会打印具体哪条断言不满足。

## 打包发布

```bash
python _tools/make_release.py            # 生成 _release/kindle-bridge-<版本>.zip
```

发布包只含源码、依赖清单、文档和启动器，**不含**任何用户数据
（`导出/`、`收书/`、`工具/`、`corpus/` 都被排除）。

打成单文件 exe（需先 `pip install pyinstaller`）：

```bash
pyinstaller Kindle桥.spec
```

产物在 `dist/`。冻结后只读资源（`web/`、`kindle/data/`）走解包目录，
用户数据（`收书/`、`导出/`、`工具/`）落在 **exe 旁边** —— 这条分界由 `kindle/paths.py` 统一管理。

## 设计取向

- **本地优先**：没有账号、没有云、没有遥测。数据不出机器。
- **零 Web 框架**：后端是标准库 `http.server`，前端是原生 HTML/CSS/JS。
  没有 `node_modules`，没有构建步骤，`git clone` 完就能跑。
- **不破解**：带 DRM 的 kfx/azw 一律只如实标注状态，不做任何解密。
- **不静默安装**：要装什么，先问用户。
- **唯一第三方依赖**：OpenCC（MIT）。其余全是标准库。

## 许可

本项目代码采用 [MIT 许可证](LICENSE)。

第三方组件与数据各自遵循其原有许可，详见 LICENSE 文件末尾的说明。
本项目不包含、也不分发任何受版权保护的书籍正文。

## 致谢

- [OpenCC](https://github.com/BYVoid/OpenCC) —— 简繁转换字典与算法（MIT）
- [CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cc-cedict) —— 中英词典数据（CC BY-SA 4.0）
- [chinese-poetry](https://github.com/chinese-poetry/chinese-poetry) —— 中文诗词与四书五经语料（MIT）
- [Project Gutenberg](https://www.gutenberg.org/) —— 公版电子书
- [Standard Ebooks](https://standardebooks.org/) —— 精校公版电子书
- [Calibre](https://calibre-ebook.com/) —— EPUB / AZW3 转换

## 已知限制

- **Windows 优先**：设备识别用 `ctypes` 直连 USB 大容量存储，macOS / Linux 下
  设备相关功能受限，但简繁转换、标注解析、生词解析等纯本地功能跨平台可用。
- **需要连着 Kindle**：书库、投递这些功能要求设备已连接并被系统挂载。
- 简繁转换的繁体输出采用**台湾正体**；需要港标或大陆正体请自行改 `kindle/hanzi.py`
  里的 `_CC_S2T` 配置（OpenCC 还提供 `s2t` / `s2hk` / `tw2sp` 等）。
