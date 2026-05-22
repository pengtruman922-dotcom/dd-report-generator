# vNext 写作链路任务流程图（文字版）

> 目标：将当前 v3 的“多 chunk 并发写报告”调整为“通用标的信息 chunk + 跟进动态 chunk”的双产物写作链路，使系统更贴合向量检索场景，而不是在当前系统内完成推荐分析。

---

## 一、vNext 的核心定位

vNext 不再把写作目标定义为“生成一份尽量完整的研究/尽调报告”，而是定义为：

1. 生成一份**通用、稳定、高密度的标的信息 chunk**
2. 生成一份**时间敏感、持续增长、可回溯的跟进动态 chunk**
3. 让跟进动态中的**最新卖方有效事实**反哺标的信息 chunk
4. 不在当前系统内写“推荐给谁”“为什么适配”“下一步怎么推”等推荐分析内容

一句话概括：

**vNext = 动态优先的事实沉淀链路，而不是章节化报告写作链路。**

---

## 二、vNext 的最终产物

### 产物 A：标的信息 chunk

作用：

- 作为向量检索的主入口
- 提供标的的通用基础事实
- 供后续推荐系统、匹配系统、人工检索统一调用

内容边界：

- 主体与基础身份
- 行业与细分赛道
- 产品、客户、收入结构
- 财务与经营数据
- 股权、融资、治理
- 风险与合规事实
- 当前有效的交易基础事实

不包含：

- 特定买家的态度
- 我方/中介方策略
- shortlist 判断
- 推荐对象分析
- 下一步推进建议

### 产物 B：跟进动态 chunk

作用：

- 保留全量时间线
- 承载非公开、动态变化的信息
- 作为后续更新标的信息 chunk 的上游信息源

内容边界：

- 日期
- 沟通事件
- 卖方态度变化
- 报价变化
- 交易路径变化
- 新出现的障碍或限制
- 关键非公开信息

允许保留：

- 动态变化轨迹
- 历史版本
- 时间线语义

不建议直接沉淀为基础事实的内容：

- 某个买家的兴趣或态度
- 我方项目组策略
- 对特定买方的推荐建议
- 会议中的猜测性判断

---

## 三、vNext 任务流程总图（文字版）

```text
用户输入 / 附件 / 新增纪要 / 历史数据
        │
        ▼
Step 0. Intake / Parse
        │
        ├─ 解析静态事实候选（公司、产品、财务、股权等）
        ├─ 解析动态事实候选（报价、卖方意愿、交易障碍、沟通节点等）
        └─ 解析无效内容 / 噪音 / 策略性语句候选
        │
        ▼
Step 1. Research（按需）
        │
        └─ 补充公开事实，不负责推荐分析
        │
        ▼
Step 2. Tracking Processor / Dynamic Writer
        │
        ├─ 输入：历史动态 + 本次新增动态 + 动态候选
        ├─ 输出 1：跟进动态 chunk
        ├─ 输出 2：seller fact snapshot（卖方当前有效事实快照）
        └─ 输出 3：excluded context（买方态度/我方策略/非通用内容）
        │
        ▼
Step 3. Info Chunk Writer
        │
        ├─ 输入：静态事实 + research 事实 + seller fact snapshot
        └─ 输出：标的信息 chunk
        │
        ▼
Step 4. Summary / Index Builder
        │
        ├─ 为标的信息 chunk 生成摘要与索引
        └─ 如有需要，为跟进动态 chunk 生成系统内摘要
        │
        ▼
Step 5. Store / Push
        │
        ├─ 保存标的信息 chunk
        ├─ 保存跟进动态 chunk
        ├─ 更新结构化字段
        └─ 仅推送标的信息 chunk 到向量库 / FastGPT
```

---

## 四、vNext 各步骤的职责定义

## Step 0：Intake / Parse

输入：

- 用户录入文本
- 附件解析结果
- 历史报告与历史 chunk
- 新增沟通纪要 / 跟进记录

职责：

- 提取静态事实候选
- 提取动态事实候选
- 标记明显属于“策略/建议/买方态度”的内容

输出建议结构：

```json
{
  "static_fact_candidates": {},
  "dynamic_fact_candidates": [],
  "non_generic_context_candidates": []
}
```

说明：

- 这一层不做最终写作
- 这一层只做“内容分流”
- 重点是把“静态事实”和“动态信息”分开

---

## Step 1：Research（按需）

输入：

- 主体名称
- 静态事实候选
- 基础附件

职责：

- 补工商、财务、股权、处罚、公开融资等公开事实
- 只补事实，不做推荐判断

输出建议结构：

```json
{
  "public_company_facts": {},
  "public_risk_facts": {},
  "public_financing_facts": {}
}
```

说明：

- 与当前 v3 相比，research 的地位下降
- 它不再支撑“行业长文”“推荐分析”
- 它只负责补全公开事实缺口

---

## Step 2：Tracking Processor / Dynamic Writer

这是 vNext 的核心变化。

输入：

- 历史动态 chunk
- 新增动态候选
- 新增沟通纪要
- 历史已提炼 snapshot

职责分成三部分：

### 2.1 生成跟进动态 chunk

要求：

- 保留时间线
- 支持持续追加
- 支持历史事实保留
- 不要求去掉历史值

### 2.2 提炼 seller fact snapshot

作用：

- 从动态中提炼“当前仍然有效的卖方事实”
- 供标的信息 chunk 使用

典型字段：

- 当前最新卖方报价
- 当前最新交易方式
- 当前最新出售意愿
- 当前最新可转让比例
- 当前最新交易障碍
- 当前最新非公开风险

### 2.3 剔除 non-generic context

剔除内容：

- 买方 A 的态度
- 我方策略
- “建议推给谁”
- “联系谁推进”
- “高层审批后再说”

输出建议结构：

```json
{
  "tracking_chunk": "...",
  "seller_fact_snapshot": {
    "current_offer": "...",
    "current_deal_path": "...",
    "current_willingness": "...",
    "current_blockers": []
  },
  "excluded_context": []
}
```

说明：

- 这里可以是单独 agent
- 也可以是现有 writer_agent 下拆出来的专门工具
- 关键不是模型数量，而是职责必须独立

---

## Step 3：Info Chunk Writer

输入：

- 静态事实候选
- research 事实
- seller fact snapshot

输出：

- 单个高密度标的信息 chunk

写作原则：

- 只写当前有效事实
- 不写推荐结论
- 不写某个买家的态度
- 不写我方策略
- 不保留过期值
- 允许把 seller fact snapshot 中的最新值覆盖旧值

说明：

- 这一层不直接读“全量动态原文”
- 只读 snapshot
- 这是避免污染基础信息的关键

---

## Step 4：Summary / Index Builder

输入：

- 标的信息 chunk
- 跟进动态 chunk

输出：

- 标的信息摘要
- 标的信息索引标签
- 跟进动态摘要（可选，仅系统内使用）

说明：

- 摘要服务列表预览与人工快速浏览
- 索引标签只围绕 `info_chunk`
- `tracking_chunk` 不作为外部检索对象
- 不承载推荐逻辑

---

## Step 5：Store / Push

保存对象：

- info_chunk
- tracking_chunk
- summaries
- index_tags
- 结构化字段

推送对象：

- 向量库 / FastGPT

说明：

- 逻辑上是双 chunk
- 存储层可以继续复用 `report_chunks`
- 只是 chunk 数不再默认固定 8 个
- 对外仅推送 `info_chunk` 及其摘要/索引

---

## 五、Create / Update 两种场景的流程差异

## 场景 A：Create（新建）

适用情况：

- 新标的首次入库
- 历史无报告或无 chunk

流程：

```text
parse -> research -> tracking processor（若有动态） -> info chunk writer -> summary/index -> store/push
```

特殊说明：

- 如果没有跟进动态，tracking processor 可以只输出空动态 chunk 或最小动态 chunk
- info chunk 仍可基于静态事实和 research 生成

## 场景 B：Update（更新）

适用情况：

- 有新增附件
- 有新增跟进记录
- 有新增公开信息

流程：

```text
parse -> research（按需） -> tracking processor -> info chunk writer（按需更新） -> summary/index -> store/push
```

更新判断逻辑建议：

- 若新增内容仅影响动态，不影响当前有效卖方事实：
  - 更新 tracking_chunk
  - 可不更新 info_chunk

- 若新增内容改变了当前有效卖方事实：
  - 更新 tracking_chunk
  - 同时更新 info_chunk

例如：

- 3 月卖方报价 10 亿
- 4 月卖方报价 15 亿

则：

- tracking_chunk 保留两条时间线
- info_chunk 只保留“当前最新报价 15 亿”

---

## 六、与当前 v3 相比，原有内容要怎么调整

当前 v3 的核心产物：

- chunk0：身份卡
- chunk1：财务数据
- chunk2：业务与竞争力
- chunk3：行业与市场
- chunk4：风险与合规
- chunk5：交易条件
- chunk6：客户与供应链
- chunk7：跟进动态

vNext 不是简单重命名，而是整体收缩和重组。

## 1. 保留的内容

这些内容保留，但不再分散到多个 chunk：

- 主体身份（原 chunk0）
- 财务事实（原 chunk1）
- 业务、产品、场景（原 chunk2）
- 风险与合规事实（原 chunk4）
- 股权、融资、交易基础（原 chunk5 的一部分）
- 客户与收入结构（原 chunk6）
- 跟进动态（原 chunk7）

## 2. 下沉或删除的内容

### 原 chunk3：行业与市场

建议处理：

- 删除宏观行业长文
- 删除大段政策趋势
- 删除机械化可比公司列表

保留内容：

- 仅保留与标的直接相关的赛道归属
- 仅保留“产品/客户/应用场景”能落下来的事实

### 原 chunk5：交易条件

建议处理：

- 保留卖方当前有效报价、交易路径、最新障碍
- 删除 deal strategy、推荐打法、我方判断

### 原 chunk6：客户与供应链

建议处理：

- 不再独立成块
- 并入 info chunk 的“客户/收入结构/区域分布”部分

## 3. 新的内容合并方式

### info chunk 由以下旧内容重组而成

- chunk0 的主体身份
- chunk1 的财务数据
- chunk2 的业务与产品
- chunk4 的风险与合规事实
- chunk5 中“卖方当前有效交易事实”
- chunk6 的客户结构与收入结构
- chunk7 提炼出的 seller fact snapshot

### tracking chunk 延续旧 chunk7，但职责升级

旧职责：

- 记录时间线

新职责：

- 记录时间线
- 作为 seller fact snapshot 的上游来源

---

## 七、原有模块如何迁移

## 1. `writer_agent.py`

当前职责：

- 规划并发写多个 chunk

vNext 后建议职责：

- 从“并发写 8 chunk 的 orchestrator”改为“流程协调器”
- 主要负责决定：
  - 是否需要 research
  - 是否需要跑 tracking processor
  - 是否需要更新 info chunk

结论：

- 保留
- 但角色从“章节调度”改为“事实链路调度”

## 2. `chunk_writer.py`

当前职责：

- 按 chunk0~chunk7 的不同 prompt 写多个 chunk

vNext 后建议职责：

- 简化为两个写作单元：
  - info chunk writer
  - tracking chunk writer

结论：

- 保留底层能力
- 但不再需要 8 套固定 chunk prompt

## 3. `chunk_prompts.py`

当前职责：

- 维护 chunk0~chunk7 的独立写作提示词

vNext 后建议职责：

- 改成两套主 prompt：
  - `info_chunk_prompt`
  - `tracking_chunk_prompt`

可选第三套：

- `tracking_snapshot_prompt`

结论：

- 需要重构
- 从 8 套 prompt 收缩为 2-3 套 prompt

## 4. `rating_agent.py`

当前职责：

- 基于 chunk7 + chunk0/1/4/5 做可行性评级

vNext 后建议：

- 不是当前首要模块
- 如果保留，应只读取：
  - tracking chunk
  - info chunk

结论：

- 可以先保留接口
- 但不应成为 vNext 流程设计的中心

## 5. `pipeline_v3.py`

当前职责：

- writer -> save chunks -> rating -> push

vNext 后建议：

- 重写为：
  - parse
  - research
  - tracking processor
  - info chunk writer
  - summary/index builder
  - save/push

结论：

- 这是最核心要改的编排文件

---

## 八、vNext 最小可行版本（MVP）建议

如果希望先小步试，不建议一步到位重构所有东西，建议先做 MVP：

### MVP 版本只改四件事

1. 产物从 8 chunk 收缩为 2 chunk
2. 新增 tracking processor 概念
3. info chunk 不再直接读取全量动态
4. summary/index 改为围绕 2 chunk 生成

### MVP 下暂时不做的事情

- 不先精调 seller snapshot 字段全集
- 不先改 rating 体系
- 不先改前端复杂展示逻辑
- 不先改所有旧数据迁移

这样做的原因是：

- 先验证“动态驱动基础事实”这条主逻辑
- 再补字段精调和规则细化

---

## 九、建议的文件级调整清单

### 优先调整

- `backend/services/pipeline_v3.py`
- `backend/agents/writer_agent.py`
- `backend/agents/chunk_writer.py`
- `backend/prompts/chunk_prompts.py`

### 次优先调整

- `backend/services/attachment_update_pipeline.py`
- `backend/prompts/rating_agent_prompt.py`
- `backend/agents/rating_agent.py`

### 数据层可暂不大改

- `report_chunks` 表可以先继续用
- 只是 chunk 数不再固定为 8

---

## 十、最终建议

如果用一句话概括 vNext 写作链路：

**vNext 不再并发生成多章节报告，而是先处理跟进动态，提炼当前有效卖方事实，再生成通用标的信息 chunk，最终形成“基础事实 + 时间线动态”的双文档结构。**

这套结构更适合：

- 信息量有限的项目
- 动态持续更新的项目
- 非公开信息占比高的项目
- 向量检索与后续外部推荐分析的分层架构
