# 更新记录

## 0.2.1 — 2026-10-20

- Word/WPS 复制彻底移除 GetActiveObject、DispatchEx、Documents.Open 和 Content.Copy 等应用自动化调用。
- 由 MarkDone 直接生成和写入包含原生数学结构的 RTF 剪贴板，不启动或连接 Word/WPS，不修改应用设置，不留下 Office 剪贴板延迟提供者。
- 复用原有 MathML → OMML 转换及论文排版，保留公式、表格、中文和标题层级。
- 新增无 COM 调用约束、RTF 结构及本机 Office RichEdit 隐藏解析器往返测试；测试不打开 Word/WPS 文档。

## 0.2.0 — 2026-10-19

- 兼容 Codex 自动压缩的 `.jsonl.zst`，无须解压或改写原始会话。
- 按 `history_base` 的物理 rollout ID 递归连接分段历史，支持同一个对话的多次继续、分叉及压缩前序记录。
- 严格使用排他性 ordinal 边界，避免读入已被分叉或继续操作舍弃的后续记录。
- 支持运行中 JSONL 与压缩记录相互切换；压缩内容采用流式读取。
- 健康检查返回软件版本，Windows/macOS 构建声明 zstandard 依赖。

验证：会话读取回归测试 10 项通过；实际两条故障会话恢复读取。
