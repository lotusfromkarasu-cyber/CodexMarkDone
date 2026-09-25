---
name: codex-markdone
description: Open the standalone local Codex MarkDone reader for browsing Codex projects and copying messages or equations into Obsidian and Word.
---

# Codex MarkDone

The user normally opens **Codex MarkDone** from the desktop or Start menu. No conversation command is required. The executable includes Python, the browser assets, KaTeX and fonts; do not start the legacy web server.

When explicitly asked to open the reader from Codex, launch:

```powershell
$reader = $env:CODEX_MARKDONE_HOME
if (-not $reader) { $reader = Join-Path $env:LOCALAPPDATA 'Programs\CodexMarkDone\CodexMarkDone.exe' }
if (-not (Test-Path $reader)) { $reader = Join-Path $PSScriptRoot '..\..in\CodexMarkDone\CodexMarkDone.exe' }
if (-not (Test-Path $reader)) { $reader = Join-Path $env:LOCALAPPDATA 'Programs\CodexMarkDone\CodexMarkDone.exe' }
Start-Process $reader -WindowStyle Hidden
```

Add `-ArgumentList '--current'` when the user asks for the current task. The process reads `CODEX_THREAD_ID` or `CODEX_SESSION_ID`; otherwise the reader restores the last conversation. Repeated launches reuse the existing service.

If the executable is absent, the source plugin includes `scripts/build_reader.ps1` to build and install it, including shortcuts. Explain that this is a one-time installation, not the normal user workflow. The old `scripts/codex_markdone.py --current` remains a compatibility launcher.

The reader reads local Codex SQLite and JSONL files without modifying them. It does not import conversations only present on chatgpt.com. Projects and conversations are on the left; message navigation and full-conversation search remain on the right. Updates are checked every few seconds; the left sidebar has a pause/start toggle (自动同步) and a manual refresh button (⟳). Pausing stops background polling entirely. Settings are stored separately under LocalAppData/CodexMarkDone.

Click a reply's selection button, a text line, or a formula; dragging text also opens the floating three-button menu. Clicking blank space in a message card selects the whole reply. The three copy actions (Obsidian, Word, Formula) are also pinned to the top toolbar. Ctrl+click or the 多选 toolbar button adds arbitrary messages to one multi-selection; 全选内容 picks all messages, and a turn node's 选回答 picks every answer of that question turn. The right sidebar shows a numbered turn rail (each user question is a node) that jumps to that turn and tracks scroll progress. Obsidian copies Markdown with dollar delimiters. Word copies HTML with Presentation MathML. Copy Formula copies the first equation as editable MathML. A failed rich copy must be reported as failed, not as successful plain-text fallback. Keep inner LaTeX backslashes intact.

Use the tray menu to open the reader or exit the service. No startup-at-login setting is installed.
