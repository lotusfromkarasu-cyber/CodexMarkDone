# Codex MarkDone

Codex Desktop/CLI 会话阅读器与选择复制工具。它在本机运行本地网页阅读器，可浏览会话、查看 Markdown 内容和图片，并按需复制回复、段落、行或公式。

## 下载与启动

从 [最新 Release](https://github.com/lotusfromkarasu-cyber/CodexMarkDone/releases/latest) 下载 Windows x64 便携包 `CodexMarkDone-2026-09-24-windows-x64.7z`，解压后运行 `CodexMarkDone.exe`。程序在本机启动服务并打开网页阅读器。

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

## 从源码运行

需要 Windows、Python 3 和项目依赖。运行入口为 `scripts/codex_markdone.py`。Word/WPS 富文本复制需要本机安装对应应用。

## 项目结构

- `scripts/`：会话读取、网页服务、剪贴板和 Word/WPS 文档复制。
- `web/`：本地网页阅读器。
- `assets/`：图标与静态资源。
- `tests/`：项目测试与格式校验用例。
- `releases/`：Windows 便携程序归档。

## 许可

当前仓库未附带开源许可证；公开源码不代表授予再分发或修改许可。
