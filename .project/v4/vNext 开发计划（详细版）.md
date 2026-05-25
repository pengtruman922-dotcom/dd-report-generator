# vNext 开发计划（详细版）

> 目录：`.project/v4`
> 目标：在确认 vNext 双产物链路方向后，给出更细的实施排期和依赖关系，便于评审、拆任务和控制风险。

---

## 一、项目目标

vNext 的开发目标不是继续优化“多 chunk 章节报告”，而是完成以下转向：

- 从多 chunk 并发章节写作，转为双产物事实写作
- 从“章节完整性”转为“检索有效性”
- 从“当前系统内做推荐分析”转为“当前系统只沉淀事实”
- 从“动态只是附加内容”转为“动态驱动基础事实更新”

最终希望达到：

1. 每个标的至少有 1 份高密度标的信息 chunk
2. 有跟进记录的标的额外有 1 份跟进动态 chunk
3. 列表、详情、编辑、推送、设置全部适配双产物结构

---

## 二、范围界定

## 本次纳入范围

- 主流程编排
- tracking processor
- info chunk writer
- summary/index builder
- 存储与推送适配
- 前端首页字段调整
- 前端详情页结构调整
- 设置页与工作台适配
- 基础测试补齐

## 本次暂不深挖但先保留的内容

- rating 体系
- 高级匹配算法
- seller snapshot 的字段精调

---

## 三、阶段化开发计划

## Phase 0：设计确认阶段

### 目标

- 确认流程、职责、边界
- 形成可执行开发清单

### 交付物

- `vNext 写作链路任务流程图（文字版）.md`
- `vNext 模块职责表.md`
- `vNext 改造清单.md`
- 本文档

### 验收标准

- 流程、模块、首页、设置影响面已讲清
- 可以进入正式开发拆解

---

## Phase 1：后端 v4 主链路打通

### 目标

先不动前端，优先在后端跑通：

- parse
- research
- tracking processor
- info chunk writer
- save/push

### 核心任务

#### 1. 调整现有主流程编排

- 在现有主流程文件中增加 v4 分支或 schema 分支
- 统一 create / update 双场景编排
- 对接现有 intake 执行入口
- 输出双 chunk

说明：

- 这里的重点是“主流程职责重排”
- 不预设必须新增 `pipeline_v4.py`
- 是否拆新文件留到实现阶段再决定

#### 2. 新建 `tracking_processor`

- 输入历史动态 + 新增动态
- 输出 tracking chunk
- 输出 seller fact snapshot
- 输出 excluded context

#### 3. 新建 `info_chunk_writer`

- 只接收静态事实 + research + snapshot
- 生成 info chunk

#### 4. 初版保存逻辑

- 先复用 `report_chunks`
- 使用 `chunk_id = info / tracking`

### 依赖

- 当前 `intake.py` 可复用
- 当前附件解析器可复用
- 当前 research 可复用但 prompt 要收缩

### 风险

- tracking processor 的边界不清会污染 info chunk
- update 逻辑容易漏掉“只更新 tracking”的场景

### 验收标准

- 新建标的可以生成 info chunk
- 有动态时可以生成 tracking chunk
- 更新时能根据动态变化决定是否更新 info chunk

---

## Phase 2：摘要、索引与推送适配

### 目标

把双产物真正变成可推到向量库的稳定内容。

### 核心任务

#### 1. 新建 summary/index builder

- 为 info chunk 生成 summary / index tags
- 如有需要，为 tracking chunk 生成系统内展示摘要

#### 2. FastGPT v4 适配

- 新建 `build_fastgpt_chunks_v4`
- 调整 `fastgpt_uploader.py`
- 直接切换到 v4 推送路径

#### 3. hash / push 逻辑调整

- 支持 info/tracking 分别 hash
- 仅 `info_chunk` 变化触发 FastGPT 重推
- 判断内容变化时不要误判

### 风险

- index tags 可能过多或过于噪音
- 若 `seller_fact_snapshot` 融合策略不清，可能导致 info chunk 与 tracking chunk 脱节

### 验收标准

- v4 报告可以稳定推送 FastGPT
- FastGPT 仅接收 `info_chunk + info_summary + info_index_tags`
- tracking chunk 只保留在当前系统内

---

## Phase 3：前端详情页与编辑器适配

### 目标

先让用户能正确查看和编辑 v4 结构。

### 核心任务

#### 1. `ReportDetail.tsx` 改成双视图

- 基础信息
- 跟进动态

#### 2. `ChunkEditor.tsx` 适配双 chunk

- 只显示 info/tracking 两类 chunk
- 支持直接编辑与保存

#### 3. `report.py` 统一读取接口调整

- 按 v4 新结构返回双 chunk 结果

### 风险

- 前端仍有多处假设固定 chunks

### 验收标准

- v4 报告在详情页可正常查看
- info/tracking 可编辑
- 页面不再依赖旧 8 chunk 假设

---

## Phase 4：首页列表字段重构

### 目标

让首页字段和新结构一致，不再继续依赖旧 8 chunk 语义。

### 核心任务

#### 1. 重新定义首页默认字段

建议默认保留：

- 编码
- 项目名
- 主体
- 行业
- `referral_status`
- 营收
- 净利润
- 可行性评级
- 更新时间
- 推送状态

#### 2. `referral_status` 语义调整

- 保留现有动态字段语义
- 不直接改成 `tracking_summary`
- 如首页确实需要更短摘要，可后续新增独立字段

#### 3. 评级字段处理

- 保留 `feasibility_rating`
- 语义仍是标的活跃度、交易意愿、可行性等内部评级
- 不作为 FastGPT 内容推送

#### 4. 搜索/筛选/排序兼容

- 行业筛选
- 列表文本搜索
- 营收利润排序
- owner / push status 保持不变

### 风险

- 首页字段太多会导致旧逻辑残留
- 评级和动态摘要的关系需要重新梳理

### 验收标准

- 首页展示与双产物结构一致
- 核心字段来自 v4 新链路而不是旧 chunk 假设

---

## Phase 5：设置页与工作台重构

### 目标

让 AI 配置与 prompt 配置都能操作 v4 模块，而不是继续围绕旧 8 chunk。

### 核心任务

#### 1. 后端 settings / workbench 节点重构

新增：

- tracking_processor
- info_chunk_writer
- index_builder

弱化：

- chunk0~chunk7 prompt

#### 2. 前端 `SettingsPanel.tsx` 调整

- 新增 v4 模块配置
- 调整 prompt 分类显示
- 保留 FastGPT 和 researcher 设置

#### 3. 类型定义更新

- `AISettings`
- `Workbench` payload
- prompt override 结构

### 风险

- 设置页和工作台历史配置清理不彻底
- 老 prompt override 数据迁移边界不清

### 验收标准

- 设置页可查看、编辑、保存 v4 模块配置
- workbench 能测试 v4 节点

---

## Phase 6：更新链路与附件链路收口

### 目标

让新增附件、新增纪要、动态更新都统一走 v4 思路。

### 核心任务

- 改造 `attachment_update_pipeline.py`
- 取消旧 `affected_chunks` 逻辑中心地位
- 改成 snapshot 变化驱动 info chunk 是否重写

### 验收标准

- 更新流程与新建流程一致
- 纯动态更新不强制重写 info chunk
- snapshot 变化时 info chunk 可被正确覆盖更新

---

## 四、跨模块影响说明

## 1. 主流程影响

高影响：

- `backend/services/pipeline_v3.py`
- `backend/routers/intake.py`
- `backend/services/attachment_update_pipeline.py`

## 2. Prompt / Agent 影响

高影响：

- `backend/agents/writer_agent.py`
- `backend/agents/chunk_writer.py`
- `backend/prompts/chunk_prompts.py`
- `backend/agents/researcher.py`
- `backend/prompts/researcher_prompt.py`

## 3. 存储影响

中高影响：

- `backend/db.py`
- `backend/routers/report.py`
- `backend/utils/fastgpt_adapter.py`
- `backend/services/fastgpt_uploader.py`

## 4. 前端影响

高影响：

- `frontend/src/components/ReportsPage.tsx`
- `frontend/src/components/ReportDetail.tsx`
- `frontend/src/components/ChunkEditor.tsx`
- `frontend/src/components/SettingsPanel.tsx`
- `frontend/src/types/index.ts`

---

## 五、建议的实施方式

## 建议采用“先备份 v3，再直接切换 v4”的替换策略

### 原因

- 改动面太大
- 首页、详情、设置、推送都受影响
- 继续维护两套链路只会放大复杂度
- 历史数据本轮不作为兼容目标处理

### 做法

- 先在 git 中保存当前 v3 状态，作为可回退版本
- 在现有主流程中直接切到 v4 结构，必要时再拆文件
- 前端详情、列表、设置统一按 v4 重构
- 不再维护 v3/v4 双套设置、双套展示、双套推送逻辑

### 不建议的做法

- 一边保留 v3 运行时逻辑，一边再叠加一套 v4 逻辑
- 继续让设置页、工作台、前端界面承担双版本兼容成本
- 为历史数据补一整套旧结构兼容逻辑

---

## 六、里程碑建议

### Milestone 1

- 后端 v4 主流程跑通
- 可生成双 chunk
- 可保存数据库

### Milestone 2

- FastGPT v4 推送打通
- 详情页双视图可用

### Milestone 3

- 首页字段调整完成
- `referral_status` 保持原语义
- `feasibility_rating` 与 v4 列表字段兼容

### Milestone 4

- 设置页和工作台重构完成
- 更新链路统一收口

### Milestone 5

- 评估是否逐步淘汰旧 8 chunk 逻辑

---

## 七、当前最需要你确认的关键决策

1. 保留 rating 兼容，但不把它作为本轮主目标
2. 首页继续保留 `feasibility_rating`，并保持当前语义
3. `referral_status` 继续沿用现有字段名和语义
4. 不做 v3/v4 共存；先备份 v3，再直接切换到 v4
5. tracking processor 明确单独成模块 / agent
6. 设置页与工作台只支持 v4 配置

---

## 八、结论

从开发计划角度看，vNext 不适合被当作“prompt 优化项目”，而应当被当作一个新小版本架构改造项目处理。

最稳妥的推进方式是：

- 先打通后端双产物主链路
- 再适配推送与详情
- 再调整首页字段和设置页
- 最后收口更新链路和旧结构清理

如果用一句话总结本计划：

**vNext 应按“新版本链路”来实施，而不是在 v3 上做局部修补。**
