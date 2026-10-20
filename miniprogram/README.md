# Kindle 桥 · 微信小程序

手机上那一半的 Kindle 桥：**纯端内运行**，不连服务器、不上传任何数据。

## 能做什么

| 页面 | 功能 | 位置 |
|---|---|---|
| 首页 | 功能入口 | `pages/index/` |
| 繁 → 简 | 文本 / EPUB / TXT 转简体 | `pages/convert/` |
| 简 → 繁 | 文本 / EPUB / TXT 转台湾正体 | `pkg-trad/pages/t2t/` |
| 标注 | 解析 `My Clippings.txt`，导出 Markdown / CSV / 微信读书笔记 / JSON | `pages/clippings/` |
| 生词 | 解析桌面端导出的生词 CSV，转 Anki / Markdown / JSON | `pages/vocab/` |

## 装到手机上

1. 打开 [微信开发者工具](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)
2. 「导入项目」→ 选 **`miniprogram/` 这个目录**（不是仓库根目录）
3. AppID 选「测试号」即可；`project.config.json` 里已填 `touristappid`
4. 真机预览：点「预览」扫码

不需要后端、不需要域名、不需要备案。

## 架构要点

### 分包：为什么简→繁要单独放一个包

| 包 | 内容 | 体积 |
|---|---|---|
| 主包 | `vendor/t2cn.js`（繁→简字典）+ `vendor/fflate.js`（zip 库）+ 4 个页面 | 约 200 KB |
| 分包 `pkg-trad` | `vendor/cn2t.js`（简→繁词组表）+ 简转繁页 | 约 1.05 MB |

简→繁的词组表有 1MB（`STPhrases` 982KB），塞进主包会让首屏变慢，
所以等用户真的点进「简转繁」页面时才由微信下载分包。

### 转换口径与桌面端一致

桌面端用 OpenCC 的标准 `t2s`；小程序这边用 opencc-js 的 `hk→cn`。
实测在《紅樓夢》（90 万字）上逐字比对，**差异 16 个字符（0.0018%）**，
且全是港台异体归一，对大陆读者反而更正确：

```
桌面 拚 -> 小程序 拼   ×6      拚命 -> 拼命
桌面 袷 -> 小程序 夹   ×3      袷紗被 -> 夹纱被
桌面 坏 -> 小程序 坯   ×1
```

> 曾经试过 `tw→cn`（台湾口径），那会把「著」一律转成「着」（著名→着名）、
> 还把「么」转成「幺」，与桌面端差出 6000 多处，已弃用。

### 异体补丁与短语保护

`utils/zhtables.js` 与桌面端 `kindle/hanzi.py` 用同一套表：

- **异体补丁**：`擡→抬`、`舖→铺`、`薴→苧→苎`（补上 OpenCC 断掉的第二跳）等
- **短语保护**：`乾坤` 的「乾」不转成「干」（干坤是错的）、`變徵` 的「徵」不转成「征」（五声音阶用字）

### EPUB 处理

`utils/epub.js` 用 fflate 直接改容器：

- **只动文本节点** —— 标签、样式、脚本、图片、字体一律原样
- 产出仍是合法 EPUB：`mimetype` 排第一个且不压缩
- 转换 1.17 MB 的《紅樓夢》约 **0.4 秒**

## 自测

不用微信开发者工具也能跑：

```bash
node _test/test-miniprogram.js
```

覆盖：主包/分包字典可用、异体补丁与短语保护、EPUB 容器合法性、
标注解析（中英文时间格式）、生词 CSV（含带逗号的引号字段）、Anki 输出格式。
共 47 项断言。

## 功能边界（重要）

小程序跑在手机上，**碰不到插在电脑上的 Kindle**，所以这些仍然只能在桌面端做：

- 扫描 Kindle 书库
- 把书投递到设备（AZW3 转换 / 拷贝）
- 读取 `vocab.db`（设备上的 SQLite）—— 小程序侧改为解析桌面端导出的 CSV
- 读取 `My Clippings.txt` —— 需要先用数据线拷出来，再传到微信里

## 第三方组件

| 组件 | 用途 | 许可 | 位置 |
|---|---|---|---|
| [opencc-js](https://github.com/BYVoid/OpenCC) | 简繁转换字典 | Apache-2.0 | `vendor/`、`pkg-trad/vendor/` |
| [fflate](https://github.com/101arrowz/fflate) | zip 读写 | MIT | `vendor/` |

许可证原文在 `vendor/LICENSES/`。
