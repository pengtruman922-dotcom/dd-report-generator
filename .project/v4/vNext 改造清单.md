# vNext 改造清单

> 目录：`.project/v4`
> 目的：把 vNext 从“方向性讨论”推进到“可拆分、可排期、可开发”的任务清单。

---

## 一、改造范围总览

vNext 改造范围覆盖：

- 主流程编排
- Agents / Prompts
- 数据存储
- 首页列表字段
- 详情页展示
- 设置页 / 工作台
- FastGPT 推送
- 更新流程
- 类型定义与测试

这不是一次“只改 prompt”的优化，而是一次跨后端、前端、存储、配置的系统性调整。

---

## 二、已确认前提

以下前提已确认，本清单后续不再反复摇摆：

1. 新版本直接切到 v4，不考虑 v3/v4 共存
2. 历史数据本轮不做兼容处理，先在 git 中保留 v3 可回退版本
3. v4 的核心产物只有两个：`info_chunk`、`tracking_chunk`
4. 只有 `info_chunk` 推送到 FastGPT / 向量库
5. `tracking_chunk` 只留在当前系统内，用于查看和动态更新
6. `tracking_processor` 单独 agent 化
7. `rating` 保留兼容，但不是本轮改造主目标
8. 首页继续显示 `feasibility_rating`，保持当前语义
9. `referral_status` 保持现有动态字段语义，不替换成 summary
10. 设置页和工作台只保留 v4 配置

---

## 三、开发主线与优先级

| 主线 | 目标 | 优先级 | 依赖 | 验收结果 |
|---|---|---|---|---|
| 主流程重排 | 跑通 v4 create/update 链路 | P0 | 无 | 能生成并保存 `info_chunk` / `tracking_chunk` |
| Tracking / Info 写作 | 完成双产物写作和 snapshot 提炼 | P0 | 主流程 | 动态先处理，再稳定反哺 `info_chunk` |
| 存储与字段回填 | 保住首页和详情页所需聚合字段 | P0 | 主流程、写作 | `industry`、`revenue`、`offer_yuan` 等能稳定回填 |
| FastGPT 适配 | 只推 `info_chunk` | P1 | 主流程、字段回填 | 新推送 payload 稳定可用 |
| 详情页 / 编辑器 | 用户能看懂、能改 v4 结构 | P1 | 存储结构 | 双视图可读可编辑 |
| 首页列表 | 首页字段与 v4 一致 | P1 | 字段回填 | 列表字段不再依赖旧 8 chunk |
| 设置页 / 工作台 | 去掉旧 chunk 配置心智 | P2 | 新模块命名稳定 | 页面只呈现 v4 模块 |
| 测试与清理 | 防止回归和旧逻辑残留 | P2 | 前面各主线 | 旧逻辑不再成为主路径 |

说明：

- P0 是必须先打通的链路
- P1 是让用户真正能用起来的界面与外推能力
- P2 是收口、清理和防回归

---

## 四、后端主流程改造清单

## 4.1 主流程编排

### 当前文件

- `backend/services/pipeline_v3.py`
- `backend/routers/intake.py`
- `backend/services/attachment_update_pipeline.py`

### 改造目标

- 从 `writer -> 8 chunks -> rating -> push`
- 改为 `parse -> research -> tracking processor -> info chunk writer -> summary/index -> store/push`

### 必做任务

- [ ] 在现有主流程中直接改造成 v4 主路径，不再保留旧 8 chunk 作为运行时主流程
- [ ] 统一 create / update 的主流程编排顺序
- [ ] 在 `intake.py` 中把入口收敛到 v4 链路
- [ ] 改造附件更新链路，不再依赖 `affected_chunks`
- [ ] 增加 `tracking_chunk -> seller_fact_snapshot -> info_chunk` 的顺序约束
- [ ] 明确 research 是按需节点，不再默认执行行业长文检索
- [ ] 明确 rating / push 的调用时机，避免在 `info_chunk` 未稳定前提前执行

### 建议拆分任务

#### Task A：主流程骨架重排

- 涉及文件：`backend/services/pipeline_v3.py`
- 输出：v4 顺序编排骨架
- 验收：create 能完整跑通主链路

#### Task B：入口收口

- 涉及文件：`backend/routers/intake.py`
- 输出：统一走 v4 的执行入口
- 验收：新建报告请求不再落入旧 8 chunk 分支

#### Task C：更新链路收口

- 涉及文件：`backend/services/attachment_update_pipeline.py`
- 输出：更新流程按 snapshot 变化决定是否重写 `info_chunk`
- 验收：新增动态但不改当前有效事实时，只更新 `tracking_chunk`

### 风险点

- 动态链路与静态链路混在一起，容易污染 `info_chunk`
- 更新流程最容易遗漏“只更新 tracking，不重写 info”场景

---

## 4.2 Tracking / Info 写作模块

### 当前文件

- `backend/agents/writer_agent.py`
- `backend/agents/chunk_writer.py`
- `backend/prompts/writer_agent_prompt.py`
- `backend/prompts/chunk_prompts.py`

### 改造目标

- 删除“并发写 8 个固定 chunk”的假设
- 收缩为：
  - `tracking_processor`
  - `info_chunk_writer`

### 必做任务

- [ ] 新建 `backend/agents/tracking_processor.py`
- [ ] 新建 `backend/prompts/tracking_processor_prompt.py`
- [ ] 新建 `backend/agents/info_chunk_writer.py`
- [ ] 新建 `backend/prompts/info_chunk_prompt.py`
- [ ] 将 `writer_agent.py` 降级为轻量协调层，或把职责并回主流程
- [ ] 将 `chunk_writer.py` 从 `chunk0~chunk7` 写作器收缩为双产物写作能力
- [ ] 将旧 `chunk0~chunk7` prompt 归档，不再作为主路径配置

### 模块级职责拆分

#### `tracking_processor`

必须输出：

- `tracking_chunk`
- `seller_fact_snapshot`
- `excluded_context`

必须解决：

- 时间线保留
- 当前有效卖方事实提炼
- 买方态度 / 我方策略剔除
- 历史值保留在 `tracking_chunk`、当前值只进 `info_chunk`

#### `info_chunk_writer`

必须输入：

- 静态事实
- research 事实
- `seller_fact_snapshot`

必须解决：

- 只写当前有效事实
- 不写推荐对象 / shortlist / 买家视角结论
- 支持交易字段回填，如 `valuation_yuan`、`offer_yuan`

### 风险点

- `tracking_processor` 如果把买方态度混进 snapshot，会直接污染检索内容
- `info_chunk_writer` 如果直接读全量动态原文，会重新引入漂移风险

---

## 4.3 Research 改造

### 当前文件

- `backend/agents/researcher.py`
- `backend/prompts/researcher_prompt.py`

### 改造目标

- Research 只负责公开事实补充
- 不再围绕旧 8 chunk 的章节需求检索
- 不再默认查行业长文、可比公司、推荐分析素材

### 必做任务

- [ ] 调整 researcher prompt，明确“补事实，不写长文”
- [ ] 改写输入 schema，围绕事实缺口而非章节需求
- [ ] 收缩输出结构为主体、财务、风险、股权/融资等事实包
- [ ] 明确 research 可跳过的条件，避免无必要联网开销

### 需要明确的边界

- 行业信息只保留赛道归属，不扩展宏观分析
- 公开财务、处罚、融资、工商等交给 research
- 非公开交易信息、报价变化、意愿变化不交给 research

---

## 4.4 Rating 改造

### 当前文件

- `backend/agents/rating_agent.py`
- `backend/prompts/rating_agent_prompt.py`
- 主流程相关调用点

### 改造目标

- 以小改动方式平移到 v4
- 输入从旧的若干 chunk 改为：
  - `info_chunk`
  - `tracking_chunk`

### 必做任务

- [ ] 调整 rating 输入组装
- [ ] 同步修改 rating prompt
- [ ] 保持列表展示字段兼容
- [ ] 保持不推送 FastGPT

### 非本轮目标

- 不把 rating 改造成买家匹配评分
- 不围绕 rating 重构主流程

---

## 五、数据与存储改造清单

## 5.1 `report_chunks` 存储语义调整

### 当前状态

- `chunk_id` 默认是 `chunk0~chunk7`

### vNext 目标

- 只存：
  - `info_chunk`
  - `tracking_chunk`

### 必做任务

- [ ] 将 `chunk_id` 收敛为 `info` / `tracking`
- [ ] 调整 `report.py` 的 chunk 读取逻辑
- [ ] 调整保存逻辑，确保双 chunk 可独立更新
- [ ] 明确 `tracking_chunk` 缺省为空时的保存策略

### 建议补充元数据

- `report_schema_version = v4`
- `chunk_kind = info | tracking`
- `seller_fact_snapshot_json`
- `info_summary`
- `tracking_summary`（可选，仅系统内使用）
- `info_index_tags`

---

## 5.2 `reports` 表字段梳理

### 当前问题

`reports` 表存在大量旧结构字段，且来源分散。

### vNext 目标

- 保留真正服务首页和筛选的聚合字段
- 弱化旧 8 chunk 的字段来源假设
- 明确“哪些字段来自 `info_chunk`，哪些字段来自 `tracking_chunk` 或 rating”

### 建议保留字段

- `bd_code`
- `company_name`
- `project_name`
- `industry`
- `industry_tags`
- `revenue`
- `net_profit`
- `valuation_yuan`
- `valuation_date`
- `offer_yuan`
- `offer_date`
- `referral_status`
- `updated_at`
- `owner`
- `feasibility_rating*`

### 建议弱化或评估去留字段

- `company_intro`
- `description`

### 字段来源映射建议

| 字段 | v4 主要来源 | 用途 | 是否推送 FastGPT |
|---|---|---|---|
| `industry` | `info_chunk` 抽取 | 首页筛选 / 标签 | 否，作为 meta 可附带 |
| `industry_tags` | `info_chunk` / index builder | 首页筛选 / 检索辅助 | 可附带 |
| `revenue` | `info_chunk` 抽取 | 首页展示 | 否 |
| `net_profit` | `info_chunk` 抽取 | 首页展示 | 否 |
| `valuation_yuan` | `info_chunk` 抽取当前有效估值 | 首页展示 / 详情查看 | 否 |
| `valuation_date` | `info_chunk` 抽取 | 首页展示 / 详情查看 | 否 |
| `offer_yuan` | `info_chunk` 抽取当前有效报价 | 首页展示 / 详情查看 | 否 |
| `offer_date` | `info_chunk` 抽取 | 首页展示 / 详情查看 | 否 |
| `referral_status` | `tracking_chunk` / 跟进记录聚合 | 首页动态查看 | 否 |
| `feasibility_rating` | `rating_agent` | 首页排序 / 内部管理 | 否 |

### 必做任务

- [ ] 明确字段抽取责任，是由 writer 返回还是 post-process 抽取
- [ ] 明确 `valuation_yuan` / `offer_yuan` 取“当前有效值”而不是历史值
- [ ] 明确 `referral_status` 保持动态原语义，不被 summary 替代
- [ ] 明确 `feasibility_rating` 与内容推送边界分离

---

## 六、前端改造清单

## 6.1 首页列表 `ReportsPage.tsx`

### 当前问题

- 列定义严重依赖旧结构
- `industry`、`revenue`、`net_profit`、`referral_status`、`feasibility_rating` 都默认存在
- 默认有“评级”中心视角

### vNext 需要做的事

- [ ] 重新定义首页默认字段
- [ ] 保留 `referral_status` 作为跟进动态相关字段
- [ ] 明确 `industry`、`revenue`、`net_profit`、`valuation_yuan`、`offer_yuan` 的来源
- [ ] 保留 `feasibility_rating` 作为内部项目可行性/活跃度字段
- [ ] 检查搜索、筛选、排序逻辑是否仍依赖旧 chunk 结构

### 建议首页默认字段

- `bd_code`
- `project_name`
- `company_name`
- `industry`
- `industry_tags`
- `revenue`
- `net_profit`
- `valuation_yuan`
- `offer_yuan`
- `referral_status`
- `feasibility_rating`
- `updated_at`
- `push_status`

### 验收标准

- 首页不再隐式依赖 chunk0~chunk7
- 用户能在列表看到核心交易字段和动态字段

---

## 6.2 详情页 `ReportDetail.tsx`

### 当前问题

- 默认假设 v3 为多 chunk 展示

### vNext 需要做的事

- [ ] 改成“标的信息 / 跟进动态”双视图
- [ ] 去掉旧 8 chunk 标题与排序假设
- [ ] 明确 `tracking_chunk` 只在系统内展示，不出现外部推送心智
- [ ] 预留查看结构化字段的区域，如报价、估值、评级

### 建议展示结构

- 基础信息
- 跟进动态
- 附件 / 来源
- 评级与元数据

### 验收标准

- 用户能直观看到“基础信息”和“动态记录”是两块不同内容

---

## 6.3 `ChunkEditor.tsx`

### 当前问题

- 假设存在多个 chunk 可编辑

### vNext 需要做的事

- [ ] 编辑器只支持 `info_chunk` / `tracking_chunk`
- [ ] 编辑保存逻辑改成双 chunk 模式
- [ ] 明确编辑 `tracking_chunk` 后是否触发 snapshot 重算

---

## 6.4 `EditReportModal.tsx`

### 当前问题

- 编辑字段集来自旧结构

### vNext 需要做的事

- [ ] 重新审查字段表单
- [ ] 明确哪些字段允许人工编辑
- [ ] `referral_status` 继续作为动态字段对待
- [ ] 评估 `valuation_yuan` / `offer_yuan` 是否允许人工修正

---

## 6.5 `PipelineProgress.tsx`

### 当前问题

- 默认步骤为 planning / research / writing / rating / push

### vNext 需要做的事

- [ ] 改成更贴近 v4 的步骤名，例如：`parse -> research -> tracking -> info -> index -> rating -> push`
- [ ] 确保进度展示不再暗示“多 chunk 并发写作”

---

## 6.6 类型定义 `frontend/src/types/index.ts`

### 当前问题

- `ReportMeta`、`AISettings`、`Chunk` 结构都偏旧模型

### vNext 需要做的事

- [ ] 增加 chunk kind 定义
- [ ] 增加 summary / index 元数据定义
- [ ] 移除旧 8 chunk 枚举依赖
- [ ] 为 settings 增加 `tracking_processor`、`info_chunk_writer`、`index_builder`

---

## 七、设置与工作台改造清单

## 7.1 后端设置接口

### 当前文件

- `backend/routers/settings.py`
- `backend/config.py`
- `backend/services/model_workbench.py`

### 当前问题

- 设置和工作台围绕 `writer_agent/chunk_writer/rating_agent/chunk0~7 prompt` 展开

### vNext 需要做的事

- [ ] 新增模块配置：`tracking_processor`、`info_chunk_writer`、`index_builder`
- [ ] 调整 workbench 节点目录，只保留 v4 可调节点
- [ ] 移除 `chunk0~chunk7` prompt 的工作台入口
- [ ] 保留 `researcher`、`rating_agent`、`fastgpt` 等仍然有效的模块配置

---

## 7.2 前端设置页 `SettingsPanel.tsx`

### 当前问题

- 页面逻辑默认存在 `writer_agent`、`rating_agent`、旧 chunk prompt

### vNext 需要做的事

- [ ] 增加 v4 模块配置区
- [ ] prompt 分类改成模块级，而不是 chunk 级
- [ ] 移除 v3/v4 切换心智
- [ ] 明确 FastGPT 只消费 `info_chunk`

### 已确认方向

- 设置页不保留 v3/v4 双模式切换
- 工作台只保留 v4 prompt 与模块配置入口

### 验收标准

- 用户在设置页只会看到 v4 相关模块
- 不再看到 `chunk0~chunk7` 这类旧术语

---

## 八、FastGPT / 向量库改造清单

### 当前文件

- `backend/services/fastgpt_uploader.py`
- `backend/utils/fastgpt_adapter.py`

### 当前问题

- v3 适配器按多个 chunk 推送
- collection 内容默认围绕旧 chunk 结构组织

### vNext 需要做的事

- [ ] 新增 v4 payload builder
- [ ] 只推 `info_chunk`
- [ ] 为 `info_chunk` 配套 `info_summary`、`info_index_tags`
- [ ] 明确 `seller_fact_snapshot` 不单独外推，而是先融合进最终 `info_chunk`
- [ ] 调整 push 去重 / hash 逻辑，避免 `tracking_chunk` 变化触发无意义重推

### 验收标准

- FastGPT 侧只看到一份稳定的通用标的信息内容
- `tracking_chunk` 完全留在当前系统内

---

## 九、更新链路改造清单

### 当前问题

- 附件更新走 `affected_chunks`
- 基于旧 8 chunk 模型更新

### vNext 需要做的事

- [ ] 附件更新统一走 `tracking_processor + info_chunk_writer`
- [ ] 通过 `seller_fact_snapshot` 比较决定 `info_chunk` 是否需要重写
- [ ] 支持“只更新 tracking，不更新 info”的路径
- [ ] 支持“snapshot 变化后同步回填交易字段”的路径

### 需要新增的判断

- 动态更新是否影响当前有效卖方事实
- 仅动态变化是否可以跳过 `info_chunk` 重写
- 交易字段变化是否需要触发首页字段刷新

### 验收标准

- 3 月报价 10 亿、4 月报价 15 亿时：
  - `tracking_chunk` 保留两段时间线
  - `info_chunk` 只保留最新有效报价 15 亿
  - 首页 `offer_yuan` 同步更新到当前有效值

---

## 十、测试改造清单

### 新增测试方向

- [ ] 动态提炼正确性测试
- [ ] snapshot 覆盖逻辑测试
- [ ] `info_chunk` 仅保留当前有效值测试
- [ ] `tracking_chunk` 保留历史值测试
- [ ] 首页字段回填测试
- [ ] 设置项读写测试
- [ ] FastGPT v4 payload 测试（仅 `info_chunk`）
- [ ] rating 输入切换测试

### 旧测试需要调整或删除

- [ ] 与 `chunk0~chunk7` 强耦合的测试
- [ ] 与 `affected_chunks` 强耦合的附件更新测试
- [ ] 旧工作台 / 旧 prompt 节点相关测试

---

## 十一、建议开发顺序

## Phase 1：后端主链路打通（P0）

- 调整现有主流程编排
- 新建 `tracking_processor`
- 新建 `info_chunk_writer`
- 输出双 chunk
- 保存到 `report_chunks`
- 跑通字段回填

## Phase 2：更新链路与交易字段稳定（P0）

- 改造 `attachment_update_pipeline.py`
- 跑通 snapshot 覆盖逻辑
- 确保 `valuation_yuan` / `offer_yuan` 取当前有效值

## Phase 3：FastGPT 与详情页（P1）

- 新建 summary/index builder
- 调整 FastGPT 适配器
- 详情页双视图可用
- ChunkEditor 适配双 chunk

## Phase 4：首页列表与设置页（P1 / P2）

- 首页字段改造
- 设置页模块重构
- workbench 节点重构

## Phase 5：测试与旧逻辑清理（P2）

- 下线旧 chunk prompt
- 平移 rating 输入
- 清理旧 8 chunk 术语与界面残留
- 补齐核心回归测试

---

## 十二、最值得优先盯住的风险

1. `tracking_processor` 把买方态度或我方策略误写入 snapshot
2. `info_chunk` 仍然混入推荐结论、next step、特定买家视角
3. `valuation_yuan` / `offer_yuan` 被错误取成历史值而不是当前有效值
4. 首页字段虽然保留了，但来源仍旧偷偷依赖旧 chunk 逻辑
5. FastGPT 仍然收到动态内容，污染检索结果
6. 设置页和工作台仍残留旧 `chunk0~chunk7` 心智

---

## 十三、结论

vNext 改造不是“把 8 个 chunk 改成 2 个 chunk”这么简单，而是以下几件事同时发生：

- 主流程重排
- 写作职责重构
- 字段来源重定义
- 更新逻辑重写
- 首页字段重构
- 设置页和工作台重构
- 向量库推送适配

如果用一句话概括这份改造清单：

**v4 的开发主任务，不是继续把报告写全，而是把“动态先处理、事实再沉淀、字段可回填、外部只推通用信息”这条链路真正做实。**
