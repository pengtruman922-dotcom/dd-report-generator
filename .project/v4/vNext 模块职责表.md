# vNext 模块职责表

> 目录：`.project/v4`
> 目的：把 vNext 双产物链路拆成可确认、可开发的模块职责边界，便于后续逐项评审。

---

## 一、vNext 总体原则

vNext 的写作链路只产出两类核心文档：

1. 标的信息 chunk
2. 跟进动态 chunk

其中：

- 跟进动态 chunk 负责保留时间线与动态变化
- 跟进动态处理过程额外产出 `seller_fact_snapshot`
- 标的信息 chunk 只接收静态事实、research 事实和 `seller_fact_snapshot`
- 当前系统不写推荐对象、匹配结论、shortlist 判断、下一步建议
- `tracking_chunk` 只在当前系统内查看和管理，不推送到 FastGPT
- FastGPT 只接收最终的 `info_chunk`

---

## 二、后端模块职责表

| 模块 | 当前实现 | vNext 职责 | 输入 | 输出 | 备注 |
|---|---|---|---|---|---|
| Intake / Parse | `backend/routers/intake.py`、解析器、`intake_agent_v3.py` | 解析文本/附件；拆分静态事实候选、动态候选、噪音候选 | 用户输入、附件、链接 | `static_fact_candidates`、`dynamic_candidates`、`noise_candidates` | 不直接生成最终 chunk |
| Research | `backend/agents/researcher.py` | 按需补公开事实，不写行业长文，不做推荐分析 | 主体名、静态事实缺口 | `public_fact_bundle` | 地位下降，变成补事实模块 |
| Tracking Processor | 新模块（建议新增） | 统一处理历史动态 + 新增动态；生成动态 chunk；提炼当前有效卖方事实 | 历史动态、新增动态、动态候选 | `tracking_chunk`、`seller_fact_snapshot`、`excluded_context` | vNext 核心新增模块；`tracking_chunk` 仅系统内使用 |
| Info Chunk Writer | 由 `chunk_writer.py` 重构或拆新模块 | 只生成单个高密度标的信息 chunk；吸收 snapshot 中的最新有效值 | 静态事实、research 事实、`seller_fact_snapshot` | `info_chunk` | 不直接读取全量动态原文 |
| Summary / Index Builder | 新模块或在写作后补一层 | 为最终 `info_chunk` 生成对外检索用摘要和索引；如有需要，为 `tracking_chunk` 生成系统内展示摘要 | `info_chunk`、`tracking_chunk` | `info_summary`、`info_index_tags`、`tracking_summary` | `tracking_chunk` 不参与 FastGPT 推送，也不作为外部检索对象 |
| 主流程编排 | `backend/services/pipeline_v3.py`、`writer_agent.py` | 协调 create/update 流程，决定是否 research、是否处理 tracking、是否重写 info chunk | 全部上游输入 | 两个 chunk + 元数据 | 这是职责，不预设必须新增独立 orchestrator 或 `pipeline_v4.py` |
| Attachment Update Pipeline | `backend/services/attachment_update_pipeline.py` | 对新增附件走同一条 vNext 更新链路 | 新附件、历史报告 | 更新后的动态 chunk / 信息 chunk | 不能再按旧的 affected chunk 逻辑做 |
| Store | `pipeline_v3.py`、`report.py` | 保存双 chunk、摘要、索引和结构化字段 | 最终产物 | DB 记录 | 存储层可沿用 `report_chunks` |
| Push | `fastgpt_uploader.py` | 仅推送 `info_chunk` 到向量库 / FastGPT | 最终 `info_chunk`、`info_summary`、`info_index_tags` | FastGPT payload | `tracking_chunk` 不推送 FastGPT |
| Rating | `rating_agent.py` | 小改动平移；输入改为 `info_chunk` 和 `tracking_chunk` | `info_chunk`、`tracking_chunk` | 评级结果 | 仍服务标的活跃度、交易意愿、可行性等内部评级，不作为 FastGPT 内容 |

---

## 三、建议新增的后端模块

## 1. Tracking Processor

建议文件：

- `backend/agents/tracking_processor.py`
- `backend/prompts/tracking_processor_prompt.py`

职责：

- 清洗和归并跟进记录
- 识别动态中的卖方有效事实
- 剔除买方态度 / 我方策略 / 建议性内容
- 输出完整时间线文档 + 当前有效事实快照

建议输出结构：

```json
{
  "tracking_chunk": {
    "summary": "...",
    "content": "..."
  },
  "seller_fact_snapshot": {
    "current_offer": null,
    "current_deal_path": null,
    "current_willingness": null,
    "current_blockers": [],
    "current_nonpublic_facts": []
  },
  "excluded_context": []
}
```

## 2. Info Chunk Writer（重构版）

建议文件：

- `backend/agents/info_chunk_writer.py`
- `backend/prompts/info_chunk_prompt.py`

职责：

- 合并静态事实 + 公开事实 + snapshot
- 生成单个高密度、通用、可检索的标的信息 chunk
- 输出正文和必要的结构化字段

## 3. Summary / Index Builder

建议文件：

- `backend/agents/index_builder.py` 或 `backend/services/index_builder.py`

职责：

- 为最终 `info_chunk` 生成摘要与索引标签
- 如有需要，为 `tracking_chunk` 生成系统内展示摘要
- 控制 `info_chunk` 标签质量与重复度

说明：

- 对外检索对象只有 `info_chunk`
- `tracking_chunk` 的摘要仅用于首页/详情等系统内展示
- 不必为 `tracking_chunk` 构建 FastGPT 检索标签

---

## 四、现有后端模块如何调整

## 1. `backend/agents/writer_agent.py`

当前职责：

- 规划是否调研、读附件、并行写多个 chunk

vNext 职责：

- 保留为轻量流程协调层，或将职责下沉到现有主流程文件
- 主要决定：
  - 是否需要 research
  - 是否需要跑 tracking processor
  - 是否需要更新 info chunk

建议：

- 不再直接调度 8 个 `write_chunk`
- 不预设必须新建 `pipeline_v4.py`
- 重点是职责重排，不是额外增加一层抽象

## 2. `backend/agents/chunk_writer.py`

当前职责：

- 写 chunk0~chunk7

vNext 职责：

- 不再承担 8 个固定 chunk 的写作
- 收缩为两类写作能力：
  - `write_info_chunk`
  - `write_tracking_chunk`

建议：

- 去掉与 `chunk0~chunk7` 相关的全部设置和 prompt 假设
- 用 `info_chunk` / `tracking_chunk` 替换

## 3. `backend/prompts/chunk_prompts.py`

当前职责：

- 维护 8 套固定 prompt

vNext 职责：

- 缩成两套主 prompt：
  - `info_chunk_prompt`
  - `tracking_chunk_prompt`
- 可选第三套：
  - `tracking_snapshot_prompt`

建议：

- 新建文件，不建议在原 `chunk_prompts.py` 上继续膨胀改造
- 原 `chunk0~chunk7` prompt 进入归档态，不再作为 vNext 主路径

## 4. `backend/services/pipeline_v3.py`

当前职责：

- `writer -> save chunks -> rating -> push`

vNext 职责：

- 重新编排：
  - parse
  - research
  - tracking processor
  - info chunk writer
  - summary/index
  - save/push

建议：

- 设计阶段不预设必须新建 `backend/services/pipeline_v4.py`
- 可优先在现有主流程文件上演进
- 是否拆新文件留到实现阶段再决定

## 5. `backend/services/attachment_update_pipeline.py`

当前职责：

- 根据 affected chunks 做局部更新

vNext 职责：

- 改成：
  - 更新 tracking processor 输入
  - 按 snapshot 变化决定是否重写 info chunk

建议：

- 不能再以“受影响的 chunk0~chunk7”作为核心模型

## 6. `backend/agents/rating_agent.py`

当前职责：

- 基于 chunk7 + chunk0/1/4/5 做可行性评级

vNext 建议：

- 以较小改动平移
- 输入改为：
  - tracking chunk
  - info chunk

结论：

- 可以先保留接口和展示逻辑
- 主要修改输入组装和 prompt
- 不应成为 vNext 流程设计的中心

---

## 五、数据层职责表

| 数据对象 | 当前状态 | vNext 建议 |
|---|---|---|
| `reports` 表 | 承载大量 legacy/v3 字段，如 `industry`、`revenue`、`referral_status`、`feasibility_rating`、`valuation_yuan`、`offer_yuan` 等 | 保留，但需梳理哪些字段继续做列表聚合字段，哪些应降级或废弃 |
| `report_chunks` 表 | 存 chunk0~chunk7 | 可继续沿用，改为只存 `info_chunk`、`tracking_chunk` 两类记录 |
| `reports.referral_status` | 当前承载首页跟进动态相关内容 | 保留原语义，不直接替换成 summary；后续如需摘要可新增独立字段 |
| `feasibility_rating*` | 当前用于评级展示 | 保留；它表示标的活跃度、交易意愿、可行性等内部评级，不推送 FastGPT |
| `valuation_yuan` / `valuation_date` | 当前为交易相关字段 | 保留；可由 `info_chunk` 抽取当前有效估值信息 |
| `offer_yuan` / `offer_date` | 当前为交易相关字段 | 保留；可由 `info_chunk` 抽取当前有效报价信息 |
| `industry_tags` | 当前用于行业标签 | 可保留，作为 info chunk 的索引派生字段 |
| `push_records` | 当前记录 FastGPT 推送信息 | 可继续沿用 |

建议新增或显式化的元数据概念：

- `report_schema_version = v4`（固定当前结构标记，不用于双版本共存）
- `chunk_kind = info | tracking`
- `seller_fact_snapshot_json`
- `info_summary`
- `tracking_summary`（可选，仅系统内使用）
- `info_index_tags`

短期内可不立即改表，而是先放到 `metadata_json` 或 chunk 记录里过渡。

---

## 六、前端模块职责表

| 前端模块 | 当前实现 | vNext 需要承担的职责 | 影响等级 |
|---|---|---|---|
| `ReportsPage.tsx` | 首页列表，展示编码、项目名、主体、行业、评级、跟进、营收等 | 调整列逻辑，适配“信息卡 + 动态卡”结构；决定首页显示哪些聚合字段 | 高 |
| `ReportDetail.tsx` | 详情页展示内容/chunks/更新记录/附件 | 从“8 chunk 浏览”改为“标的信息 + 跟进动态”双视图 | 高 |
| `ChunkEditor.tsx` | 编辑 chunk | 只需支持编辑 info/tracking 两类 chunk | 中 |
| `EditReportModal.tsx` | 编辑报告元字段 | 需要重新评估展示字段，尤其是 `referral_status`、`rating`、`industry_tags` | 中 |
| `PipelineProgress.tsx` | 显示 planning/research/writing/rating/push | 需改步骤语义为 tracking/info/index/push 等 | 中 |
| `SettingsPanel.tsx` | AI 设置与 FastGPT 设置 | 新增/替换 v4 模块配置项 | 高 |
| `types/index.ts` | 定义 ReportMeta、AISettings 等类型 | 需要同步新增 v4 元数据和移除旧 chunk 假设 | 高 |

---

## 七、首页列表字段的职责重构建议

当前首页字段强依赖旧结构，核心字段包括：

- `bd_code`
- `project_name`
- `company_name`
- `industry` / `industry_tags`
- `feasibility_rating`
- `referral_status`
- `revenue`
- `net_profit`

vNext 下建议把首页字段分成三类：

## A. 必留字段

这些字段仍然有高价值：

- `bd_code`
- `project_name`
- `company_name`
- `industry`
- `industry_tags`
- `updated_at`
- `owner`
- `push_status`

## B. 需重定义字段

### `referral_status`

当前：

- 承载跟进动态核心文本 / 原文压缩版

vNext：

- 保留原语义
- 不直接重定义为 `tracking_summary`
- 如首页确实需要更短摘要，可新增独立摘要字段

### `revenue` / `net_profit`

当前：

- 来源于多个 chunk 的字段回填

vNext：

- 仍可保留
- 但应明确来自 info chunk 的结构化抽取

## C. 保留字段

### `feasibility_rating`

当前：

- 首页重要字段

vNext：

- 继续保留
- 语义为标的活跃度、交易意愿、可行性等内部评级
- 不作为 FastGPT 内容推送

---

## 八、设置项的职责重构建议

当前设置主要围绕：

- `researcher`
- `matcher_agent`
- `writer_agent`
- `chunk_writer`
- `rating_agent`
- `fastgpt`

vNext 下建议改成：

## A. AI 模块配置

建议最终保留或新增：

- `intake_agent`
- `matcher_agent`（若仍保留）
- `researcher`
- `tracking_processor`
- `info_chunk_writer`
- `index_builder`
- `rating_agent`

## B. Prompt 配置

建议最终以模块而非 chunk0~7 管理：

- `tracking_processor_prompt`
- `tracking_chunk_prompt`
- `info_chunk_prompt`
- `index_builder_prompt`

## C. FastGPT 设置

保持不变，但要注意推送内容从“8 chunk”变成“仅 info chunk + 其摘要/索引”。

---

## 九、FastGPT / 向量库适配职责

当前：

- `fastgpt_uploader.py` 会按 `report_chunks` 推送多个 chunk

vNext：

- 仅推送最终 `info_chunk`
- `info_chunk` 已吸收 `seller_fact_snapshot` 中的最新有效值
- 附带：
  - `info_summary`
  - `info_index_tags`
  - `report meta`

建议：

- `build_fastgpt_chunks_v3` 需要新增 v4 适配器
- 更适合新建：
  - `build_fastgpt_chunks_v4`
- `tracking_chunk` 不进入 FastGPT

---

## 十、测试职责建议

vNext 需要新增的测试类型：

1. 动态信息提炼测试
   - 旧报价 -> 新报价覆盖
   - 买方态度不进入 snapshot
   - 我方策略被排除

2. 双 chunk 生成测试
   - 新建仅生成 info chunk
   - 有动态时生成 tracking chunk
   - 更新时仅动态变化不重写 info chunk

3. 首页字段回填测试
   - `industry`
   - `revenue`
   - `net_profit`
   - `referral_status`

4. FastGPT 推送测试
   - v4 仅推送 info chunk
   - 摘要和索引结构正确

---

## 十一、结论

vNext 不是“减少 chunk 数量”这么简单，而是整个系统职责的重新分层：

- 后端主流程：从章节编排改为事实编排
- 写作模块：从 8 个知识块写作改为 2 个事实文档写作
- 前端：首页、详情、设置都要同步弱化旧 8 chunk 假设
- 数据层：保留现有表结构但调整语义
- 向量库：只推送稳定的 info chunk，动态信息留在当前系统内管理

如果用一句话概括模块职责变化：

**vNext 的核心职责不是“把报告写全”，而是“把基础事实和动态事实稳定地沉淀出来，并只把通用基础事实推送到外部检索系统”。**
