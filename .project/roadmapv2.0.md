# DD Report Generator · 项目路线图 v2.0

> 本文件是项目管理的主索引。所有功能设计、开发任务、Bug 修复均在此追踪。
> 最后更新：2026-04-14

---

## 文件夹说明

```
.project/
├── ROADMAP.md                          ← 旧版路线图（v1.0~v2.1）
├── roadmapv2.0.md                      ← 你在这里：v3.0 路线图
└── design/
    ├── v2-smart-intake.md              ← v2.0 设计文档（已执行）
    ├── v3-development-plan.md          ← v3.0 开发计划（模块拆解+开发顺序+依赖关系）
    ├── prompt_intake_agent.md          ← Intake 环节设计（IntakeAgent + MatcherAgent）
    ├── prompt_writer_agent.md          ← WriterAgent 设计（核心智能体）
    ├── prompt_writer.md                ← write_chunk 工具设计（8 chunk 格式规范）
    ├── prompt_researcher.md            ← Researcher 设计（工具准入 + 搜索策略）
    └── prompt_rating_agent.md          ← RatingAgent 设计（可行性评级 A-E）
```

---

## 版本总览

| 版本 | 状态 | 说明 |
|------|------|------|
| v1.0 | ✅ 已上线 | 基础流水线：Excel 录入 → 6 步生成 → FastGPT 推送 |
| v2.0 | ✅ 已完成 | 智能录入 Agent + 轻量更新流程 |
| v2.1 | ✅ 已完成 | 并行执行 + 任务终止 + prompt 精简 + 报告质量门控 |
| **v3.0** | **🔵 待开发** | **全链路重构：Intake 拆分 + WriterAgent + 8 chunk + RatingAgent** |

---

## v3.0 架构概览

### 两套流程并存

```
入口一：Excel 上传（保留 v1.0，不动）
  Extractor → Researcher → Writer(整篇MD) → FieldExtractor → Chunker(5chunk) → Push

入口二���智能录入（v3.0 全新）
  文件解析 → IntakeAgent → MatcherAgent → 用户确认
    → WriterAgent(tool-calling)
        ├─ read_attachment
        ├─ run_researcher
        ├─ write_chunk × N（8 chunk 独立写入）
        └─ append_tracking_log
    → RatingAgent（条件触发）
    → Push FastGPT
```

### 核心变化

| 维度 | v2.1 | v3.0 |
|------|------|------|
| Intake | 一个 Agent 全包（识别+匹配+字段提取） | 拆分为 IntakeAgent（识别）+ MatcherAgent（匹配） |
| 报告生成 | 代码硬编排 6 步 | WriterAgent 自主规划，tool-calling 驱动 |
| 报告格式 | 整篇 MD（13 章）→ Chunker 切 5 chunk | 直接写 8 个独立 chunk，面向向量检索优化 |
| 字段回填 | 独立 FieldExtractor Agent | write_chunk 同时返回 extracted_fields |
| 调研 | 每次必做，全量搜索 | WriterAgent 按需决定，更新时可跳过 |
| 评级 | 无独立评级（Writer 内嵌投资评分） | 独立 RatingAgent，四维度可行性评级 A-E |
| 评级变更 | 无 | 更新时需用户确认 |
| 附件 | 不关联 | 按标的关联存储，可下载 |

---

## v3.0 模块开发进度

### 模块 A：Intake 环节重构

设计文档：`prompt_intake_agent.md`

| 编号 | 子功能 | 状态 | 说明 |
|------|--------|------|------|
| A1 | 文件解析层（Step 0） | ✅ 已完成 | 新增 Excel/DOCX/PPTX 文本提取，图片保留 base64 |
| A2 | IntakeAgent 重写 | ✅ 已完成 | 多模态，只做识别+摘要+关联，不做字段提取和匹配 |
| A3 | MatcherAgent 新建 | ✅ 已完成 | 独立 Agent，模糊匹配 + confidence + reason |
| A4 | 代码层合并逻辑 | ✅ 已完成 | merge_intake_and_matcher() |
| A5 | 前端确认弹窗优化 | 🟡 后端完成 | 名称可编辑、action 可切换、confidence 警示 |
| A6 | 附件关联存储 | ✅ 已完成 | 复制到 reports/{id}/attachments/，写入 DB |
| A7 | 分发逻辑 | ✅ 已完成 | build_writer_agent_input()，附件只传文件名 |

### 模块 B：WriterAgent

设计文档：`prompt_writer_agent.md`

| 编号 | 子功能 | 状态 | 说明 |
|------|--------|------|------|
| B1 | WriterAgent 主体 | ✅ 已完成 | agents/writer_agent.py，tool-calling agent |
| B2 | 工具：read_attachment | ✅ 已完成 | 按文件名读取附件解析文本 |
| B3 | 工具：run_researcher | ✅ 已完成 | 调用 Researcher（复用模块 C） |
| B4 | 工具：write_chunk | ⬜ 待开发 | 调用 chunk_writer（复用模块 D） |
| B5 | 工具：append_tracking_log | ✅ 已完成 | 追加跟进日志到 intake_logs |
| B6 | WriterAgent prompt | ✅ 已完成 | 规划者角色提示词 |
| B7 | 新建流程逻辑 | ✅ 已完成 | 读附件 → 调研 → 并行写 chunk0~6 |
| B8 | 更新流程逻辑 | ✅ 已完成 | 判断调研/日志/受影响 chunk → 定向更新 |

### 模块 C：Researcher 优化

设计文档：`prompt_researcher.md`

| 编号 | 子功能 | 状态 | 说明 |
|------|--------|------|------|
| C1 | 工具准入逻辑（两层校验） | ✅ 已完成 | 设置选中 + key 有效 |
| C2 | Researcher prompt 重写 | ✅ 已完成 | 主体确认策略 + 工具使用策略 + 输出整理规则 |
| C3 | 输出格式更新 | ✅ 已完成 | 按 8 chunk 维度对应的 JSON 结构 |
| C4 | cninfo 修复 | ✅ 已完成 | searchkey 查询 |
| C5 | akshare 简化 | ✅ 已完成 | 仅历史行情 + 超时保护 |
| C6 | gsxt 标记不可用 | ✅ 已完成 | description 标注 |

### 模块 D：write_chunk 工具

设计文档：`prompt_writer.md`

| 编号 | 子功能 | 状态 | 说明 |
|------|--------|------|------|
| D1 | chunk_writer 实现 | ✅ 已完成 | agents/chunk_writer.py，独立 LLM 调用 |
| D2 | 8 chunk 格式规范 | ✅ 已完成 | prompts/chunk_prompts.py，chunk0~chunk7 提示词 |
| D3 | 向量检索优化写法 | ✅ 已完成 | 禁表格、自包含、身份标签行、来源标注 |
| D4 | extracted_fields 回填 | ✅ 已完成 | 每个 chunk 返回对应结构化字段 |
| D5 | 增量更新模式 | ✅ 已完成 | update 时注入 existing_content |

### 模块 E：RatingAgent

设计文档：`prompt_rating_agent.md`

| 编号 | 子功能 | 状态 | 说明 |
|------|--------|------|------|
| E1 | 评级触发逻辑 | ✅ 已完成 | should_rate_on_create / should_rate_on_update |
| E2 | RatingAgent 实现 | ✅ 已完成 | agents/rating_agent.py，四维度 → A-E |
| E3 | 评级输入组装 | ✅ 已完成 | chunk7 原文 + chunk0/1/4/5 摘要 + 当前评级 |
| E4 | 更新稳定性规则 | ✅ 已完成 | prompt 层稳定性指令 + 代码层 E 级校验 |
| E5 | pending_rating_change | ✅ 已完成 | 评级变更写入待确认字段 |
| E6 | 数据库 schema | ✅ 已完成 | 新增 feasibility_rating 系列字段 |
| E7 | 确认/驳回 API | ✅ 已完成 | POST /api/reports/{id}/rating-confirm |
| E8 | 前端：首页评级列 | ✅ 已完成 | A-E 标识 + 待确认闪烁 |
| E9 | 前端：评级确认弹窗 | ✅ 已完成 | 原评级/新评级/依据/四维度对比 |

### 模块 F：存储与前端适配

| 编号 | 子功能 | 状态 | 说明 |
|------|--------|------|------|
| F1 | 数据库 schema 升级 | ✅ 已完成 | report_format、feasibility_rating 系列、attachments |
| F2 | report_chunks 表 | ✅ 已完成 | report_id, chunk_id, label, summary, content, index_tags |
| F3 | ReportDetail 适配 | ✅ 已完成 | 兼容 legacy(整篇MD) + v3(8 chunk) |
| F4 | FastGPT 推送适配 | ✅ 已完成 | v3 直接推 8 chunk + index_tags |
| F5 | 附件管理 UI | ⬜ ���开发 | 报告详情页"附件"Tab |

---

## 开发顺序

详见 `v3-development-plan.md` 第四节。总体分四阶段：

```
阶段一（底层先行）          阶段二（核心 Agent）
  F1/F2 数据库 schema         B1~B8 WriterAgent
  C2/C3 Researcher prompt     E1~E7 RatingAgent
  D1~D5 write_chunk
        │                           │
        └───────────┬───────────────┘
                    ▼
阶段三（入口重构）          阶段四（前端与集成）
  A1 文件解析                 F3 ReportDetail 适配
  A2~A4 IntakeAgent+Matcher   F4 FastGPT 推送
  A5~A7 前端确认+附件+分发    E8/E9 评级前端
                              F5 附件管理
```

---

## 已知 Bug（从 v2.1 继承）

| ID | 问题 | 优先级 | 状态 |
|----|------|--------|------|
| BUG-003 | FastGPT 重复推送旧 collection 未删除 | P2 | ⬜ 待修复 |
| BUG-004 | Session 无 TTL 清理 | P2 | ⬜ 待修复 |

---

## 设计文档索引

| 文档 | 内容 | 最后更新 |
|------|------|---------|
| `prompt_intake_agent.md` | Intake 环节：IntakeAgent + MatcherAgent + 确认弹窗 + 附件关联 + 分发 | 2026-04-10 |
| `prompt_writer_agent.md` | WriterAgent：tool-calling 核心智能体，4 工具，新建/更新流程 | 2026-04-10 |
| `prompt_writer.md` | write_chunk 工具：8 chunk 格式规范，向量检索优化写法 | 2026-04-10 |
| `prompt_researcher.md` | Researcher：工具准入两层校验，LLM 驱动搜索策略，输出整理 | 2026-04-13 |
| `prompt_rating_agent.md` | RatingAgent：四维度可行性评级 A-E，评级触发/稳定性/用户确认 | 2026-04-13 |
| `v3-development-plan.md` | 开发计划：模块拆解、依赖关系、开发顺序、风险 | 2026-04-14 |

---

## 状态图例

| 标记 | 含义 |
|------|------|
| ⬜ | 待开发 / 待修复 |
| 🔵 | 设计完成，待开发 |
| 🟡 | 开发中 |
| ✅ | 已完成 |
| ❌ | 已取消 |
