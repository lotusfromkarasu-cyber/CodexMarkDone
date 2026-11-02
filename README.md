# Codex MarkDone

## v0.2.2 阅读排版修订 — 2026-11-03

前端修订 `20261103-reading`，标签 `v0.2.2-reading`；后端继续使用 `20261024-word-regular`。

- 针对中文标点紧邻双星号的写法，兼容加粗分隔符；仍使用 Markdown 原生配对算法，不改会话原文。代码、转义星号、公式和未闭合标记保持原义。
- 阅读器表格整体及默认单元格居中；Markdown 明确指定的列对齐仍保留。
- 单条阅读顶栏新增“页宽”滑块（480–1800 px），随窗口自动限制实际宽度，设置保存在阅读器配置中。
- 新排版回归、原复制界面及 80 轮消息导航回归通过。未改 Word/WPS 复制后端与公式序列化。

参考：[CommonMark 分隔符规则](https://spec.commonmark.org/spec/#emphasis-and-strong-emphasis)。

## v0.2.2 阅读排版修订 — 2026-11-03

前端修订 `20261103-reading`，标签 `v0.2.2-reading`；后端继续使用 `20261024-word-regular`。

- 针对中文标点紧邻双星号的写法，兼容加粗分隔符；仍使用 Markdown 原生配对算法，不改会话原文。代码、转义星号、公式和未闭合标记保持原义。
- 阅读器表格整体及默认单元格居中；Markdown 明确指定的列对齐仍保留。
- 单条阅读顶栏新增“页宽”滑块（480–1800 px），随窗口自动限制实际宽度，设置保存在阅读器配置中。
- 新排版回归、原复制界面及 80 轮消息导航回归通过。未改 Word/WPS 复制后端与公式序列化。

参考：[CommonMark 分隔符规则](https://spec.commonmark.org/spec/#emphasis-and-strong-emphasis)。

## v0.2.2 长对话导航修订 — 2026-10-25

前端修订 `20261025-navigation`，Git 标签 `v0.2.2-navigation`。仅更新网页资源，后端可执行程序构建仍为 `20261024-word-regular`。

- 节点与消息导航统一直接定位正文中的目标消息，不再长距离平滑滚动经过早期节点，避免同步刷新中断动画导致多次点击。
- 消息尚在分批渲染时保留跳转请求，渲染完成后自动定位；切换对话时清除旧请求。
- 重建节点列表时保留其滚动位置；窄窗口先完成侧栏收起，再计算正文目标位置。
- 已用 80 轮 / 160 条消息在隔离的无界面 Chrome 中验证：最新节点、消息向前/向后跳转、跳转期间同步刷新及渲染未完成时导航；旧代码在同步刷新场景可复现失败，新代码通过。已安装资源的同一导航回归与原复制界面回归均通过。
- 已核对运行中服务返回的新 app.js 与源码一致；无需重启服务，刷新阅读器即可加载。未操作用户的浏览器页面，实际对话体验由用户复核。

实现参考：[W3C CSSOM 滚动规范](https://www.w3.org/TR/cssom-view-1/#scrolling)。

## v0.2.2 Word 普通字重修订 — 2026-10-24

当前构建 **20261024-word-regular**。仅 Windows“复制到 Word”清除非公式文字粗体（正文、Markdown 加粗、标题、表头），保留其他排版及可编辑公式；WPS 输出不变，公式保持非加粗数学斜体。

11 项复制/公式测试通过，包括 WPS 输出逐字节相同与本机 Office RichEdit 原生解析。安装版实际复制接口交替调用 Word/WPS 12 次成功，前台切换 0 次、Office 进程不变，最慢 0.142 秒。未操作 Word/WPS 文档，粘贴外观由用户检查。

安装版和 v0.2.2 发布包已覆盖更新；重新打开阅读器并重新复制后生效。Git 标签 `v0.2.2-word-regular`。

Codex Desktop/CLI 会话阅读器与选择复制工具。它在本机运行本地网页阅读器，可浏览会话、查看 Markdown 内容和图片，并按需复制回复、段落、行或公式。

## Windows 下载与启动

从 [Windows Release](https://github.com/lotusfromkarasu-cyber/CodexMarkDone/releases/tag/v0.1.0-2026.09.24) 下载 Windows x64 便携包 `CodexMarkDone-2026-09-24-windows-x64.7z`，解压后运行 `CodexMarkDone.exe`。程序在本机启动服务并打开网页阅读器。

## macOS 下载与启动

从 [macOS Release](https://github.com/lotusfromkarasu-cyber/CodexMarkDone/releases/tag/v0.1.1) 下载与你的 Mac 芯片相符的 `CodexMarkDone-macOS-arm64.zip`（Apple Silicon）或 `CodexMarkDone-macOS-x86_64.zip`（Intel），解压后将 `CodexMarkDone.app` 移入“应用程序”并打开。第一次启动时，macOS 可能要求在“隐私与安全性”中确认打开。

macOS 版使用本机网页阅读器、菜单栏图标和系统剪贴板；数据保存在 `~/Library/Application Support/CodexMarkDone`。Word/WPS 复制通过 HTML 富文本剪贴板提供格式，Windows 版的原生 OMML 公式剪贴板仍由 Windows 构建提供。

也可以从源码运行：

```powershell
python scripts/codex_markdone.py
```

在 Codex 当前任务中启动并直接打开该会话：

```powershell
python scripts/codex_markdone.py --current
```

## 阅读与复制

- 阅读 Codex Desktop/CLI 会话，渲染标题、列表、代码、LaTeX/MathML 公式和 Markdown 图片。
- 支持选择整条回复、拖选文本、按行选择或单独选择公式。
- 复制到 Obsidian 时输出 `$...$` / `$$...$$` Markdown 公式。
- 复制到 Word/WPS 时保留可编辑的原生 OMML 公式，并保留正文格式；标题带有大纲级别，可供文档导航和目录使用。
- 平方根公式采用兼容 Word/WPS 的 OMML 结构，避免根号前出现空白占位框。
- 复制纯 LaTeX 时保留公式源码和数学定界符。

会话读取兼容 Codex Desktop/CLI 的本地 JSONL 会话目录。阅读器在本机提供服务，不需要上传会话内容。

## 从源码运行与构建

需要 Python 3 和项目依赖。运行入口为 `scripts/codex_markdone.py`。Windows 便携版由 `scripts/build_reader.ps1` 构建；macOS Intel 与 Apple Silicon 便携包由 `.github/workflows/build-macos.yml` 在 GitHub macOS runner 上分别构建并上传到 Release。无需在 Windows 本机安装 macOS 工具链。

Word/WPS 富文本粘贴需要在对应电脑安装应用。macOS 构建为未公证版本；面向大众分发时需要 Apple Developer ID 签名与公证。

## 项目结构

- `scripts/`：会话读取、网页服务、剪贴板和 Word/WPS 文档复制。
- `web/`：本地网页阅读器。
- `assets/`：图标与静态资源。
- `tests/`：项目测试与格式校验用例。
- `releases/`：Windows 便携程序归档。

## 许可

当前仓库未附带开源许可证；公开源码不代表授予再分发或修改许可。
