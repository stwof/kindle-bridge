# Kindle 桥

> 把 Kindle 里的书、标注、生词，搬到你自己的电脑和常用阅读器里。
> 纯本地运行，数据不出机器，MIT 开源。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![OpenCC](https://img.shields.io/badge/OpenCC-BYVoid-green.svg)](https://github.com/BYVoid/OpenCC)
[![微信小程序](https://img.shields.io/badge/微信小程序-端内运行-07C160.svg)](miniprogram/README.md)

仓库：<https://github.com/stwof/kindle-bridge>

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
| **阅读器** | 在本机直接读 EPUB / TXT / MOBI / AZW3，带目录、划线标注、进度记忆、**边读边听**、**划词查词**；支持鼠标点击/滚轮/触摸滑动翻页 | `书架/` |
| **朗读** | 文字转语音（TTS），本地用 Coqui TTS 合成，不联网 | 浏览器内播放 / 下载 WAV |
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

### 本地阅读器（epub.js + Calibre）

「阅读器」页是一个**跑在本机的网页阅读器**：书架自动收拢 `收书/`、`导出/` 下的书，
以及连着的 Kindle 里的书，点开就能读。

- **EPUB**：用 [epub.js](https://github.com/futurepress/epub.js)（BSD 类许可）直接在浏览器里渲染，
  不转格式、不落地副本。
- **TXT**：现场打包成 EPUB（就是「简繁转换」那套 `build_epub`），零外部依赖。
- **MOBI / AZW3 / AZW / PRC**：Kindle 原生读不了网页格式，交给本机
  [Calibre](https://calibre-ebook.com/) 的 `ebook-convert` 转成 EPUB —— **转一次就缓存**
  （`工具/缓存/阅读器/`），之后再开同一本书是秒开。没装 Calibre 会明确提示。

阅读体验：目录、字体/行距/页宽/主题（浅色/护眼/深色）、**键盘 ←→ / 空格翻页**，
以及更顺手的**鼠标点击翻页**（左 1/3 上一页、右 1/3 下一页、中间点一下隐藏/显示顶底栏）、
**鼠标滚轮翻页**、**触摸滑动翻页**（手机/平板）；`Esc` 返回书架、`R` 朗读；
按进度条跳章、**记忆上次读到哪**；选中文字可划线保存或直接朗读。
翻页做了多源去重与就绪守卫，键盘/滚轮/点击/触摸不会重复翻页、也不会在内容没就绪时崩。

**朗读**：点工具栏 🔊（或按 `R`）读出当前页，勾上「自动续读」则读完自动翻到下一页接着读；
选中一段文字后点「🔊 朗读」只读那一句。优先用本机 Coqui TTS（音质好、完全离线），
**没装 TTS 时自动回落到浏览器自带的语音**，界面上会写明当前用的是哪一种。

**划词查词**：选中正文里的词，浮动工具条点「查词」，弹出释义卡片（中文带拼音、
英文给释义），还能直接 🔊 朗读该词。查询全程**离线、不联网**：

- 先查内置的 `kindle/data/quickdict.json` 精选小词典（中英常用词，开箱即用）；
- 再用 `kindle/dictbuild.py` 生成的 StarDict 字典（`字典/` 下的 `.idx` / `.dict`），
  词库更大；装了 Calibre 词库或自行生成的字典放进 `字典/` 即自动纳入；
- 查不到时给出「未收录」提示，英文短语自动回落到末词重查。

词条按词缓存，重复查询不重复请求，不阻塞翻页渲染 —— 阅读流畅不受影响。

**翻页健壮性**：点击翻页按**可见舞台区域**计算热区（左 1/3 上一页、右 1/3 下一页、
中间隐藏/显示顶底栏），内容容器做宽度钳制与溢出裁剪。遇到 Calibre 转出来的
「超宽排版」书籍（内容宽到十万像素级）也不会出现「点右边却翻回上一页」的错乱，
手势与渲染都不卡顿。

> 阅读进度记在 `书架/进度.json`，划线标注记在 `书架/标注.json` —— 都是普通 JSON，
> 随时能打开看、能自己改、能备份。数据全程不联网。

### 本地语音合成（朗读 · Coqui TTS）

「朗读」页把文字在本机合成成语音，**完全离线、不上传任何内容**。引擎用
[Coqui TTS](https://github.com/coqui-ai/TTS)（Mozilla Public License 2.0，PyTorch 实现）：

- **中文**：Baker / Tacotron2 模型（普通话女声），约 50 MB；另有 Baker-DCA 变体。
- **多语**：YourTTS，支持中文（zh-cn）且可换说话人，约 120 MB。
- **英文**：LJSpeech 女声，约 40 MB。

用法：在「朗读」页把文字贴进文本框（或到「标注」页点任意一条里的 🔊 按钮，
把那段划线直接读出来），选好声音，点「生成并播放」；也能「下载 WAV」。

声音模型**不在仓库里**，首次用某个声音时由 Coqui 自动下载并缓存到本机
`~/.local/share/tts`，之后不用再下。

> 这是**可选功能**：核心程序不依赖它。要用「朗读」，先装：
> ```bash
> pip install -r requirements-tts.txt      # 需 Python 3.9~3.11
> ```
> 重启 Kindle 桥即可。「朗读」页在没装 TTS 时会明确提示怎么装，不影响其它功能。

## 快速开始

### 下载现成的（推荐）

去 [Releases](https://github.com/stwof/kindle-bridge/releases) 拿打包好的版本：

| 产物 | 说明 |
|---|---|
| `Kindle-Bridge-1.0.0.exe` | **Windows 单文件版**，双击即用，不需要装 Python（9.8 MB） |
| `kindle-bridge-1.0.0.zip` | 源码包，解压后用启动器运行 |

> 单文件版里只读资源（网页、词表）打进了 exe，**用户数据（`收书/`、`导出/`、`工具/`）
> 落在 exe 旁边** —— 把 exe 放哪儿，你就在那儿放书、拿结果。

### 从源码跑

```bash
git clone https://github.com/stwof/kindle-bridge.git
cd kindle-bridge
pip install -r requirements.txt
python app.py            # 浏览器会自动打开 http://127.0.0.1:8765/
```

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

### 命令行参数

```
python app.py --port 8765 --host 127.0.0.1 --no-browser
```

`--port` 端口（默认 8765）、`--host` 绑定地址（默认仅本机）、`--no-browser` 不自动开浏览器。

### 微信小程序

`miniprogram/` 下有一个**纯端内运行**的微信小程序：`miniprogram/README.md`。

- **简繁转换 / 标注 / 生词**：与网页版对应，全部在手机本地算，不上传数据。
- **读 EPUB（原生离线阅读器）**：从微信会话里选一个 `.epub` 文件，手机本地解析、本地读，
  **完全离线、不联网**。支持横向滑动翻章、上一章/下一章按钮、目录跳转、进度记忆、
  主题（浅/护眼/深）与字号调节；封面与章节内图片自动内联显示。解析内核见
  `miniprogram/utils/reader.js`（fflate 解包 + 轻量正则抽正文，不依赖 DOM）。

> 小程序跑在手机上，**碰不到插在电脑上的 Kindle**，所以「投递到设备」这类操作仍然只能在桌面端做。
> 小程序的价值是：手机上一键转简繁、随手解析标注和生词，现在还能离线读 EPUB。

## 目录结构

```
kindle-bridge/
├── app.py                  # 主服务（标准库 http.server，无 Web 框架）
├── requirements.txt        # 核心依赖（仅 OpenCC）
├── requirements-tts.txt    # 可选：本地语音合成（Coqui TTS，需 Python 3.9~3.11）
├── Kindle桥.spec           # 打包成单文件 exe（核心）
├── Kindle桥-tts.spec       # 可选：把 TTS 也打进 exe 的全内置变体
├── kindle/                 # 各功能模块
│   ├── paths.py            # 资源目录 / 数据目录分离（为单文件 exe 准备）
│   ├── hanzi.py            # 简繁转换内核（OpenCC + 异体补丁 + 短语保护）
│   ├── epub.py             # EPUB 容器读写、简繁转换、EPUB 体检
│   ├── tts.py              # 本地语音合成封装（Coqui TTS，可选功能）
│   ├── reader.py           # 本地阅读器后端（书架/元信息/封面/TXT 打包/进度标注）
│   ├── dictdata.py         # 阅读器划词查词后端（内置小词典 + StarDict 查询）
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
├── web/                    # 前端（原生 HTML/CSS/JS）+ vendor/（epub.js、JSZip）
├── miniprogram/            # 微信小程序源码
├── _test/                  # 回归测试
├── _tools/                 # 抓取语料、打发布包
├── 收书/                    # ← 放电子书，工具会从这里取
├── 书架/                    # ← 阅读器的进度与标注（两个 JSON）
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

> 生成的字典放进 `字典/` 后，**网页阅读器的「划词查词」也会自动用它**（没放也能查，
> 会先回落到内置小词典），一份数据两处用。

> 词库需在**能联网**的机器上生成；本机若装不了 OpenCC，转换会退回内置小词表。

### 补齐中文经典语料

```bash
python _tools/fetch-chinese-poetry.py
```

下载 [chinese-poetry](https://github.com/chinese-poetry/chinese-poetry)（MIT）正文数据，
支持断点续传，中断后再跑一次即可。

## 开发与测试

**跑完整回归（推荐）**：

```bash
python _test/run-regression.py            # 全跑，含真实浏览器端到端
python _test/run-regression.py --quick    # 跳过浏览器环节，快很多
python _test/run-regression.py --only reader tts
```

它会把 Python 单测、小程序、前端 DOM 桩、**真实浏览器端到端**依次跑完并给一张汇总表，
服务由脚本自己起停，不用手动开。公版书库那组要联网，在带 SSL 中间人代理的环境里
会以 `CERTIFICATE_VERIFY_FAILED` 失败 —— 脚本会标成「环境受限」而不是算代码有问题。

**单独跑某一项**：

```bash
python _test/test-hanzi.py     # 繁简转换 + EPUB 体检
python _test/test-zhconv.py    # 简繁转换全链路（含 HTTP 端到端）
python _test/test-reader.py    # 阅读器：书架/封面/TXT 打包/Calibre 转换/进度标注
python _test/test-dict.py      # 划词查词：内置词典命中/大小写/标点/未收录 + HTTP 端到端
python _test/test-tts.py       # 朗读：分句、声音目录、未安装时降级
```

这些脚本都是零依赖的，直接跑就行，失败会打印具体哪条断言不满足。

前端回归（需要先启动服务）：

```bash
python app.py &                                  # 或用启动器
BASE=http://127.0.0.1:8765 node _test/frontend-smoke.js
```

它在 Node 里用最小 DOM 桩**真实执行 app.js**，喂真实接口数据，抓运行时报错，
并逐项检查书库、投递、公版书库、阅读器、朗读各页的渲染结果。

`_test/reader-e2e.js` 更进一步：用 CDP 驱动一个**真实浏览器**，走完整用户流程
（进阅读器页 → 点开一本书 → 翻页 → 目录 → 朗读），并断言 iframe 真的渲染出正文、
控制台没有报错。它不需要额外装浏览器驱动，用系统自带的 Edge/Chrome 即可：

```bash
python app.py --port 8765 &
node _test/reader-e2e.js 8765 --shot ./截图    # --shot 会把每步截图存下来
```

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

想要一个**连 TTS 都不用装**的朗读版，用另一个 spec（体积几百 MB 起，需 Python 3.9~3.11）：

```bash
pyinstaller "Kindle桥-tts.spec"
```

## 设计取向

- **本地优先**：没有账号、没有云、没有遥测。数据不出机器。
- **零 Web 框架**：后端是标准库 `http.server`，前端是原生 HTML/CSS/JS。
  没有 `node_modules`，没有构建步骤，`git clone` 完就能跑。
- **不破解**：带 DRM 的 kfx/azw 一律只如实标注状态，不做任何解密。
- **不静默安装**：要装什么，先问用户。
- **依赖极少**：Python 端唯一的第三方运行时依赖是 OpenCC（MIT），其余全是标准库。
  「朗读」的 Coqui TTS、「阅读器」的 Calibre 都是**可选、按需安装**，不装也能跑其它功能。
  前端另随包两份宽松许可的静态资源（epub.js: BSD-2-Clause、JSZip: MIT），
  不参与安装、不需要 `node_modules`、没有构建步骤，`git clone` 完就能跑。

## 许可

本项目代码采用 [MIT 许可证](LICENSE)。

第三方组件与数据各自遵循其原有许可，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
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
- **「朗读」TTS 需 Python 3.9~3.11**：Coqui TTS 依赖的 PyTorch 目前不支持 3.12+。
  本机是更高版本时，请单独建一个 3.11 虚拟环境装 `requirements-tts.txt`。
- **「朗读」不进微信小程序**：小程序跑在手机上，装不了 PyTorch；小程序里要语音
  合成得走微信自己的同声传译插件。桌面端的 TTS 是给电脑上读标注、读段落用的。

