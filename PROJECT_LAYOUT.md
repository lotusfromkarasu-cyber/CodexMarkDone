# Codex MarkDone

当前版本：**v0.2.1（2026-10-20）**。

## v0.2.1 后台复制

“复制到 Word/WPS”现在由 MarkDone 自行生成并写入 RTF，公式使用 Office 原生数学结构，表格和正文样式保留。复制不再连接或启动 Word/WPS，不打开临时文档、不触发应用的 Content.Copy、不修改应用设置。剪贴板使用不可显示的消息所有者窗口，并短暂重试其他程序的剪贴板占用。

6 项复制测试通过，包括本机 Office RichEdit 引擎的无界面 RTF 往返验证；安装版连续复制及焦点检查见 `releases/v0.2.1/RELEASE.md`。Word/WPS 实际粘贴外观由用户检查，本次不控制其文档窗口。

## 文件位置

- `source/codex-markdone/`：主源码和原有 Git 历史。后续修改和提交在此进行。
- `releases/v0.2.0/`：本版完整便携程序、源码快照、安装压缩包、校验清单。
- `releases/v0.2.1/`：最新后台复制修复版的程序、源码快照、压缩包和校验清单。
- `archives/`：原 general 根目录中的 09-22、09-24 备份目录和压缩包，原样保留，不覆盖。

已安装程序仍在 `C:\Users\lotus\AppData\Local\Programs\CodexMarkDone\CodexMarkDone.exe`，桌面快捷方式无需更改。

个人插件市场仍引用 `C:\Users\lotus\plugins\codex-markdone`，因此该路径保留运行镜像；同时同步已安装插件缓存中的修改。当前机器不允许移除迁移后隐藏的空 Git 目录，未创建目录联接。后续更新请以本目录下的 Git 源码为准，再同步运行镜像。

## 本版修复及实测

Codex 已将大量历史会话改为 Zstandard 压缩存储，同时使用 `history_base` 串联分段记录。旧版只打开 SQLite 中的 JSONL 路径、只识别旧分叉字段，导致找不到文件或仅显示最新一轮。

新版直接流式读取压缩文件，递归解析物理 rollout ID，按排他 ordinal 边界连接历史；不修改 Codex 数据库和会话文件。

- 109 条本地对话的记录路径均可定位，其中 89 条为压缩文件。
- 实际安装版接口验证：截图报错的对话恢复 55 条消息、16 个提问。
- “论文撰写-5组图及result-6.1-sol”恢复 176 条消息、52 个提问，跨度 2026-09-23 至 2026-10-19。
- 另外两条相关分叉会话分别读取 129/142 条消息，重复轮询返回 unchanged。
- 10 项针对性读取回归测试通过；Windows 安装版健康检查返回 0.2.0。

以上是读取和接口验证，未使用 computer use，也未执行 Word/WPS 粘贴验证。若原有阅读器页面仍显示旧错误，刷新该页面即可。

## 使用与版本管理

直接通过原快捷方式启动，或运行 `releases/v0.2.0/CodexMarkDone/CodexMarkDone.exe`。便携程序必须连同 `_internal` 文件夹一起保留。

Git 仓库位于 `source/codex-markdone/.git`，本次提交和标签记录为 v0.2.0。历史备份不纳入 Git 大文件历史；新版本发布目录独立存放。压缩包不包含账号凭据、会话数据库或阅读器个人设置。

参考实现：https://github.com/openai/codex/blob/main/codex-rs/rollout/src/compression.rs
