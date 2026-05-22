# v3.0 优化开发计划

> 基于 5 份设计文档（prompt_intake_agent / prompt_writer_agent / prompt_writer / prompt_researcher / prompt_rating_agent）整合的完整开发计划。
> Excel 录入流程保留原 v1.0 六步流水线不动，本计划仅覆盖智能录入（Intake）入口的全链路重构。

---

## 一、架构总览

### 现有架构（v1.0/v2.1，保留不动）

```
Excel 上传 → Extractor → Researcher → Writer(整篇MD) → FieldExtractor → Chunker(5chunk) → Push
```

### 新架构（v3.0，智能录入入口）

```
用户上传（文本+图片+文档+URL）
  │
  ▼
Step 0: 代码层 — 文件解析（PDF/DOCX/PPTX/Excel/图片/URL）
  │
  ▼
Step 1: IntakeAgent（LLM #1，多模态）— 识别标的 + 生成摘要 + 关联材料 + 图片提取
  │
  ▼
Step 2: MatcherAgent（LLM #2，纯文本）— 标的名称 vs 已有库模糊匹配
  │
  ▼
Step 3: 代码层 — 合并结果 → 前端确认弹窗
  │
  ▼
Step 4: 代码层 — 按标的分发，每个标的独立 Pipeline：
  │
  ├─ WriterAgent（LLM #3，tool-calling agent）
  │   ├─ read_attachment(filename)      — 按需读取附件
  │   ├─ run_researcher(company_info)   — 按需联网调研（LLM #4，tool-calling agent）
  │   ├─ write_chunk(chunk_id, ...)     — 写/更新 chunk（LLM #5，每 chunk 独立调用）
  │   └─ append_tracking_log(...)       — 追加跟进日志
  │
  ├─ 代码层 — 汇总 extracted_fields → 字段回填
  │
  ├─ RatingAgent（LLM #6，条件触发）— 可行性评级 A-E
  │
  └─ 代码层 — 推送 FastGPT
```

### 两套架构共存

| 入口 | 流程 | 报告格式 | chunk 格式 |
|------|------|---------|-----------|
| Excel 上传 | v1.0 六步流水线 | 整篇 MD（13 章） | Chunker 切分的 5 chunk |
| 智能录入 | v3.0 新架构 | 8 个独立 chunk | write_chunk 直接写 8 chunk |

两者共用同一个 `reports` 数据库表和 FastGPT 知识库，但报告存储格式不同。前端 ReportDetail 页面需兼容两种格式的展示。

---

## 二、模块拆解

### 模块 A：Intake 环节重构

**涉及文档**：`prompt_intake_agent.md`

**现有代码**：`agents/intake_agent.py`、`prompts/intake_agent_prompt.py`、`routers/intake.py`、`frontend/IntakeAgent.tsx`

**改动内容**：

| 序号 | 改动 | 说明 |
|------|------|------|
| A1 | 文件解析层（Step 0） | 新增 Excel 文本提取（`extract_excel_text`）、DOCX/PPTX 解析、图片保留 base64。输出 `parsed_inputs = {text, documents[], images[], urls[]}` |
| A2 | IntakeAgent 重写 | 从"全包"改为"只做三件事"：识别标的、生成摘要、关联材料。移除字段提取和新建/更新判断。新增多模态支持（图片 base64 → image_url 内容块） |
| A3 | 新增 MatcherAgent | 独立 Agent，接收 project_name 列表 + 已有标的库，做模糊匹配。输出 action + matched_report_id + confidence + reason |
| A4 | 代码层合并逻辑 | `merge_intake_and_matcher()` 合并两个 Agent 输出，生成完整的确认数据 |
| A5 | 前端确认弹窗优化 | 名称可编辑、action 可切换（新建↔更新）、match_confidence 为 medium/low 时高亮提醒 |
| A6 | 附件关联存储 | 代码层将关联附件复制到 `reports/{report_id}/attachments/`，写入 DB 的 `attachments` 列 |
| A7 | 分发逻辑 | `build_writer_agent_input()` 组装每个标的的材料，附件只传文件名 |

### 模块 B：WriterAgent

**涉及文档**：`prompt_writer_agent.md`

**新增代码**：全新模块

**改动内容**：

| 序号 | 改动 | 说明 |
|------|------|------|
| B1 | WriterAgent 主体 | 新建 `agents/writer_agent.py`，tool-calling agent，4 个工具 |
| B2 | 工具：read_attachment | 按文件名读取附件解析文本（PDF/DOCX/PPTX/Excel 已由代码层预解析） |
| B3 | 工具：run_researcher | 调用 Researcher 进行联网调研（见模块 C） |
| B4 | 工具：write_chunk | 调用独立 LLM 写一个 chunk（见模块 D） |
| B5 | 工具：append_tracking_log | 追加跟进日志到 intake_logs 表，返回全量日志 |
| B6 | WriterAgent prompt | 系统提示词：规划者+决策者，根据 action 和材料决定工作计划 |
| B7 | 新建流程 | 读附件 → 调研 → 并行写 chunk0~chunk6（chunk7 无日志时跳过） |
| B8 | 更新流程 | 读附件 → 判断是否调研 → 判断跟进日志 → 只更新受影响的 chunk |

### 模块 C：Researcher 优化

**涉及文档**：`prompt_researcher.md`

**现有代码**：`agents/researcher.py`、`prompts/researcher_prompt.py`

**改动内容**：

| 序号 | 改动 | 说明 |
|------|------|------|
| C1 | 工具准入逻辑 | `_build_active_tools` 增加两层校验：设置选中 + key 有效。过滤 fallback chain 中无效 provider |
| C2 | Researcher prompt 重写 | 新增主体确认策略、按工具类型的使用策略、输出整理规则（过滤无关内容） |
| C3 | 输出格式更新 | 从旧结构（business_info/financial_info/...）改为按 8 chunk 维度对应（identity/financial/business/industry/...） |
| C4 | cninfo 修复 | 已完成：改用 searchkey 查询 |
| C5 | akshare 简化 | 已完成：仅保留历史行情查询，加超时保护 |
| C6 | gsxt 标记不可用 | 已完成：description 标注不可用 |

### 模块 D：write_chunk 工具

**涉及文档**：`prompt_writer.md`

**新增代码**：全新模块

**改动内容**：

| 序号 | 改动 | 说明 |
|------|------|------|
| D1 | write_chunk 实现 | 新建 `agents/chunk_writer.py`，独立 LLM 调用，每次只写一个 chunk |
| D2 | 8 chunk 格式规范 | chunk0~chunk7 各自的系统提示词，定义格式和写作规则 |
| D3 | 向量检索优化写法 | 禁止表格、每条信息自包含、身份标签行、来源标注 |
| D4 | extracted_fields | 每个 write_chunk 返回 `{summary, content, extracted_fields}`，字段回填与写作合一 |
| D5 | 增量更新 | update 时注入 existing_content，LLM 在此基础上增量修改 |

### 模块 E：RatingAgent

**涉及文档**：`prompt_rating_agent.md`

**新增代码**：全新模块

**改动内容**：

| 序号 | 改动 | 说明 |
|------|------|------|
| E1 | 评级触发逻辑 | `should_rate_on_create` / `should_rate_on_update`：用户输入无评级 + chunk7/chunk0/chunk5 有更新时才触发 |
| E2 | RatingAgent 实现 | 新建 `agents/rating_agent.py`，四维度评级（出售意愿/配合度/客观条件/当前状态）→ A-E |
| E3 | 评级输入组装 | chunk7 完整原文 + chunk0/1 摘要 + chunk4/5 摘要 + 当前评级（更新时） |
| E4 | 更新稳定性规则 | prompt 层：稳定性优先指令。代码层：`validate_rating_change` 校验 E 级变更 |
| E5 | pending_rating_change 机制 | 评级变更不直接生效，写入 pending 字段等待用户确认 |
| E6 | 数据库 schema | 新增 `feasibility_rating`、`feasibility_rating_detail`、`feasibility_rating_at`、`pending_rating_change` 字段 |
| E7 | 确认/驳回 API | `POST /api/reports/{report_id}/rating-confirm`，accept 或 reject |
| E8 | 前端：首页评级列 | 显示 A-E 评级 + 待确认标识（[B] →C 闪烁） |
| E9 | 前端：评级确认弹窗 | 展示原评级、新评级、变更依据、四维度对比 |

### 模块 F：存储与前端适配

**涉及文档**：跨多个文档

**改动内容**：

| 序号 | 改动 | 说明 |
|------|------|------|
| F1 | 数据库 schema 升级 | reports 表新增字段：`report_format`（"legacy"/"v3"）、`feasibility_rating` 系列、`attachments`、`pending_rating_change` |
| F2 | report_chunks 表 | 新建表：`report_id, chunk_id, label, summary, content, index_tags, updated_at` |
| F3 | ReportDetail 页面适配 | 检测 `report_format`：legacy 显示整篇 MD，v3 按 chunk 组织展示 |
| F4 | FastGPT 推送适配 | v3 格式直接推送 8 chunk + index_tags，不再经过 Chunker 切分 |
| F5 | 附件管理 UI | 报告详情页增加"附件"Tab，展示关联附件列表，支持下载 |

---

## 三、依赖关系

```
模块 A (Intake重构)
  │
  └──→ 模块 B (WriterAgent) ──→ 模块 F (存储与前端适配)
         │                           │
         ├──→ 模块 C (Researcher)     │
         ├──→ 模块 D (write_chunk)    │
         └──→ 模块 E (RatingAgent) ──┘
```

- A 是入口，B 依赖 A 的输出格式
- B 依赖 C（调研工具）和 D（写 chunk 工具）
- E 在 B 之后执行，依赖 D 的 chunk 输出
- F 是底层存储，B/D/E 都向 F 写数据

---

## 四、开发顺序

由于按一个大版本整体交付，但开发时仍需有序推进，建议按以下顺序：

### 第一阶段：底层先行

| 顺序 | 模块 | 内容 | 依赖 |
|------|------|------|------|
| 1 | F1/F2 | 数据库 schema 升级（新增字段+新表） | 无 |
| 2 | C1/C2/C3 | Researcher 优化（工具准入 + prompt 重写 + 输出格式） | 无 |
| 3 | D1~D5 | write_chunk 实现（8 chunk 格式规范 + 独立 LLM 调用） | F2 |

### 第二阶段：核心 Agent

| 顺序 | 模块 | 内容 | 依赖 |
|------|------|------|------|
| 4 | B1~B8 | WriterAgent 主体（4 工具 + 新建/更新流程） | C + D |
| 5 | E1~E7 | RatingAgent（评级逻辑 + pending 机制 + API） | D（需要 chunk 输出） |

### 第三阶段：入口重构

| 顺序 | 模块 | 内容 | 依赖 |
|------|------|------|------|
| 6 | A1 | 文件解析层 | 无 |
| 7 | A2/A3/A4 | IntakeAgent + MatcherAgent + 合并逻辑 | 无 |
| 8 | A5~A7 | 前端确认弹窗 + 附件关联 + 分发逻辑 | A2/A3 + B |

### 第四阶段：前端与集成

| 顺序 | 模块 | 内容 | 依赖 |
|------|------|------|------|
| 9 | F3 | ReportDetail 页面适配（兼容 legacy + v3） | F1/F2 + D |
| 10 | F4 | FastGPT 推送适配 | D |
| 11 | E8/E9 | 前端评级列 + 确认弹窗 | E |
| 12 | F5 | 附件管理 UI | A6 |

---

## 五、风险与注意事项

| 风险 | 影响 | 应对 |
|------|------|------|
| WriterAgent 的 tool-calling 稳定性 | LLM 可能不按预期调用工具或调用顺序混乱 | 充分测试 qwen3-max 的 tool-calling 能力，准备降级方案（代码编排替代 LLM 自主） |
| write_chunk 并行调用的 token 消耗 | 7 个 chunk 并行写，每个都带完整 shared_context | 测算 token 量，必要时分批而非全并行 |
| 两套报告格式共存 | 前端、API、FastGPT 都需要兼容 | `report_format` 字段区分，所有读取路径加判断 |
| Researcher 搜索效果依赖 LLM 自律 | 无代码层硬控，搜索次数/质量不可控 | 通过 prompt 优化引导，后续根据实际效果决定是否加代码约束 |
| 非上市公司信息不足 | 搜索命中率低，chunk 内容稀疏 | write_chunk prompt 中已有"整块缺失简化"规则 |
| 评级确认弹窗的用户体验 | 用户可能忽略或不理解评级变更 | 首页醒目标识 + 弹窗内容简明 |

---

## 六、现有已完成的改动（可复用）

以下改动在之前的会话中已完成，可直接复用：

| 改动 | 文件 | 状态 |
|------|------|------|
| cninfo 修复（searchkey 查询） | `backend/tools/cninfo.py` | ✅ 已完成 |
| akshare 简化（仅历史行情+超时） | `backend/tools/akshare_data.py` | ✅ 已完成 |
| gsxt 标记不可用 | `backend/tools/gsxt_scraper.py` | ✅ 已完成 |
| 工具准入：validate_config 过滤 | `backend/agents/researcher.py` _build_active_tools | ✅ 已完成 |
| 研究质量门控（core_empty 检测） | `backend/services/pipeline.py` | ✅ 已完成（v1.0 流程用） |
| Writer 禁止编造规则 | `backend/agents/writer.py` | ✅ 已完成（v1.0 流程用） |
| Researcher search_failed 信号 | `backend/prompts/researcher_prompt.py` | ✅ 已完成（v1.0 流程用） |
