# Codex MarkDone

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
