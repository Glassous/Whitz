---
name: deep-research
description: 多源深度研究与结构化报告输出指南
category: research
tags: [research, rag, synthesis]
---

# 深度研究技能

当用户需要系统性调研、对比分析或撰写研究报告时遵循以下流程：

1. **拆解问题**：使用 `todo_list` 列出 3-5 个清晰的研究子步骤。
2. **先内后外检索**：
   - 若工作区有上传资料，优先调用 `rag_search_workspace` 与 `read_workspace_file` 核实一手材料。
   - 需要最新外部信息时调用 `web_search` 与 `web_extract`，并保留来源链接。
3. **复杂课题委派**：必要时通过 `delegate_subtask(role="researcher", ...)` 并行汇总多维信息。
4. **交付产物**：长篇报告优先通过 `write_workspace_file` 保存为 Markdown 或 HTML 报告，并在正文中给出核心结论与引用依据。
