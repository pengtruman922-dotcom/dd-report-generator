# WriterAgent 设计方案

## 概述

WriterAgent 是整个系统的核心智能体，替代了原来的 Orchestrator 角色。它不是"调度员派活给工人"，而是"领域专家自己规划并执行"。

WriterAgent 是一个 tool-calling agent，具备并购领域知识，能够：
- 分析用户输入材料，判断需要写/更新哪些 chunk
- 决定是否需要联网调研
- 决定是否需要读取附件
- 判断是否有跟进动态需要追加日志
- 并行调度 write_chunk 完成各 chunk 的撰写

## 在 Pipeline 中的位置

```
IntakeAgent → MatcherAgent → 用户确认 → 代码分发
  │
  每个标的独立 Pipeline:
  Step 1: 准备（代码）
  Step 2: WriterAgent（本文档）  ← 核心智能体
  Step 3: 字段回填（代码）
  Step 4: 评级（RatingAgent，固定执行）
  Step 5: 推送 FastGPT（代码，固定执行）
```

## WriterAgent 的输入

由代码层组装，传入 WriterAgent 的上下文：

```json
{
  "project_name": "某某科技有限公司",
  "action": "create 或 update",
  "update_summary": "输入标的基础信息（公司介绍、财务概况）",
  "report_id": "report_xxx（update时）",

  "materials": {
    "text": "IntakeAgent 整理后的去噪文本内容",
    "image_content": "IntakeAgent 从图片中提取的文字内容",
    "attachment_files": ["某某科技介绍.pdf", "财务报表.xlsx"]
  },

  "chunk_summaries": {
    "chunk0": {"label": "标的身份卡", "summary": "某某科技，半导体封测..."},
    "chunk1": {"label": "财务数据", "summary": "2023年营收1.83亿..."},
    ...
  }
  // chunk_summaries 仅 update 时提供，create 时为空
}
```

**注意：附件全文不在此输入中。** WriterAgent 通过 `read_attachment` 工具按需读取。

## WriterAgent 的工具

### run_researcher(company_info: dict)

触发联网调研。company_info 包含 {company_name, industry?(从材料中推断), is_listed?}。
返回 ResearchData（扁平 JSON，覆盖工商/财务/业务/行业/风险/估值/客户等维度）。

调研是一次全局调用，搜索策略按维度分 6 轮执行。结果传给后续的 write_chunk 调用。

### read_attachment(filename: str)

读取指定附件的完整解析文本。
- 文件名来自 materials.attachment_files
- 返回解析后的纯文本（PDF/DOCX/PPTX/Excel 已由代码层预解析）

### write_chunk(chunk_id: str, instruction: str, shared_context: dict)

调用独立 LLM 写入一个 chunk。这是一个**独立的、干净的 LLM 调用**，不与其他 chunk 共享上下文。

参数：
- chunk_id：chunk0~chunk7
- instruction：自然语言任务描述
- shared_context：该 chunk 写作所需的上下文，由 WriterAgent 组装：
  - text：用户输入的文本内容
  - image_content：图片提取的文字
  - attachment_content：相关附件的解析文本（WriterAgent 读取后传入）
  - research_data：调研数据（如果做了调研）
  - tracking_logs：全部跟进日志（仅 chunk7）
- 工具内部自动注入该 chunk 的旧内容（update 时）

返回：{summary, content, extracted_fields}

**每个 write_chunk 调用是独立的 LLM 调用**，拥有自己的系统提示词（该 chunk 的格式规范）和干净的上下文。多个 write_chunk 可并行调用。

### append_tracking_log(report_id: str, content: str)

追加一条跟进日志到 intake_logs 表。
- 返回 {log_id, all_logs: [...]}
- 追加后必须调用 write_chunk(chunk7) 重新生成跟进动态

## WriterAgent 系统提示词

```
你是一名资深并购顾问，负责规划和执行标的项目的尽职调查报告撰写工作。

## 你的任务

根据收到的标的信息和材料，制定写作计划并调用工具完成执行。

## 你收到的输入

- project_name：标的项目名称
- action：create（新建）或 update（更新）
- update_summary：本次输入内容的简要摘要
- materials：用户提供的材料（文本、图片文字、附件文件名列表）
- chunk_summaries：现有 chunk 的摘要（仅 update 时提供）

## 你的工作流程

### 新建标的（action=create）

1. 阅读 materials 中的文本和图片内容，了解标的概况
2. 如有附件，调 read_attachment 读取附件内容
3. 调 run_researcher 进行联网调研
4. 并行调 write_chunk 写入 chunk0~chunk6（共 7 个 chunk）
   - 每个 write_chunk 调用传入相同的 shared_context（materials + research_data + attachment_content）
   - chunk7（跟进动态）此时无日志，跳过

### 更新标的（action=update）

1. 阅读 materials 和 chunk_summaries，理解本次更新的内容
2. 如有附件，调 read_attachment 读取相关附件
3. 判断是否需要联网调研：
   - 材料中涉及重大变更（主营业务变化、重组、上市/退市等）→ 调 run_researcher
   - 普通字段更新或跟进动态 → 不需要调研
4. 如果更新内容包含跟进动态（推介反馈、报价、谈判进展等）：
   - 调 append_tracking_log 追加日志
   - 调 write_chunk(chunk7) 从全部日志重新生成跟进动态
5. 对比更新内容与现有 chunk 摘要，确定哪些 chunk 需要更新
   - 只更新受影响的 chunk，不重写无关的 chunk
   - 一条信息可能影响多个 chunk（如"报价3亿"同时影响 chunk7 和 chunk5）
6. 并行调 write_chunk 更新受影响的 chunk

## 重要原则

- 你是规划者和决策者。判断做什么、以什么顺序做，然后调用工具执行。
- 不同 chunk 之间互不依赖，可以并行写入。
- chunk7 必须从全量日志重新生成，不能在旧内容上追加。
- 如果某个 chunk 写入失败，继续处理其他 chunk，不要终止整个流程。
- 对于 update 场景，只更新受影响的 chunk，不要重写无关的 chunk。
- 调 write_chunk 时，instruction 要清晰说明任务（如"新建标的的财务数据chunk""营收数据从1.8亿更新为2.1亿"）。
- shared_context 传给 write_chunk 时，包含所有该 chunk 可能需要的上下文。write_chunk 会自行从中提取相关信息。
```

## write_chunk 返回后的处理（代码层）

每个 write_chunk 返回 `{summary, content, extracted_fields}` 后，代码��即：
1. 存入 `report_chunks` 表（report_id, chunk_id, label, summary, content, index_tags, updated_at）
2. 收集 extracted_fields

WriterAgent 所有 write_chunk 调用完成后，代码层：
1. 汇总所有 chunk 的 extracted_fields → `update_report_fields` 写入 reports 表
2. 调 RatingAgent（固定执行）
3. 推送 FastGPT（固定执行）
