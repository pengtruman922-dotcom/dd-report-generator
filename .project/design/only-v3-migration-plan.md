# Only V3 录入收敛方案

> 状态：主体实施已完成，正在清理最后一批 legacy 运行时兼容层
> 创建日期：2026-04-16
> 最近更新：2026-04-23
> 对应 ROADMAP：[../ROADMAP.md](../ROADMAP.md)

---

## 1. 背景与目标

本方案立项时，项目同时维护三种录入入口：

- `上传 Excel`
- `手动输入`
- `智能录入`

其中，前两者走 legacy `upload -> session -> report/generate -> pipeline.py` 链路，第三者走 `intake -> execute-v3 -> pipeline_v3.py` 链路。两套链路长期并存带来三个问题：

1. 首页入口与交互模型重复，用户操作路径不一致
2. 后端同时维护 session 型 legacy 流程和 operation 型 v3 流程，维护成本高
3. v3 虽然已存在，但附件、任务持久化、详情页 chunks 展示等关键能力仍未完全闭环

**本方案目标**：

- 彻底移除 `上传 Excel` 和 `手动输入`
- 只保留 `智能录入（Only V3）`
- 采用渐进式迁移：`隐藏旧入口 -> 补全 v3 -> 删除旧服务和路由`
- 保证历史 legacy 报告继续可读、可查看、可下载、可更新

---

## 1.1 当前实施结果（2026-04-17）

已完成：

- 首页与列表入口已收敛到 Only V3，Excel / 手动输入入口已移除
- `frontend/src/components/IntakeAgent.tsx` 已改为 `parse-async -> parse-status -> 确认层 -> execute-v3`
- v3 parse 已切换为 `intake_agent_v3 + matcher_agent + intake_merger`
- v3 附件透传、任务持久化、报告 chunks 兼容读取已接通
- 前端 legacy API 已删除：Excel 上传、手动录入、旧 generate / batch-generate
- 后端 legacy 路由与服务已删除：`routers/upload.py`、`report.py:/generate`、`report.py:/batch-generate`
- legacy 执行链已删除：`services/pipeline.py`、`services/light_update_pipeline.py`、`routers/intake.py:/execute`
- 2026-04-23 已继续清理：
  - `settings.json` 旧 `ai_config` 键自动清洗
  - 设置页 workbench 移除 4 个 legacy 模型节点
  - `pipeline_v3.py` / `intake.py` 移除对 legacy 模型配置的 fallback
  - `report.py` chunks API 改为仅支持 `report_chunks`
  - `fastgpt_uploader.py` 改为仅从 v3 chunks 推送
  - `ChunkEditor.tsx` 移除旧分块重建交互
  - 删除旧文件：`agents/extractor.py`、`agents/field_extractor.py`、`agents/chunker.py`、`agents/writer.py`、`services/chunker.py` 及对应 prompt
- 2026-04-24 已继续收口运行时尾巴：
  - `task_manager.py` 的 `runner_type` 默认语义改为 `v3`，启动时会把历史 `legacy` 值归一化为 `v3`
  - 删除 `task_manager.py` 中未被运行时使用的旧恢复接口：`get_pending_tasks()`、`recover_tasks()`
  - `report.py` / `intake.py` 不再把 `*_chunks.json` 视为 v3 报告标准产物
  - `settings.example.json`、`DEPLOYMENT.md`、`README.md` 已同步为 only-v3 配置键：`tools`、`fastgpt`

当前仍需持续确认的事项：

- v3 解析确认层在复杂多标的输入下的可用性与可编辑性
- 前端任务墙、SSE 超时回退轮询、任务 message 展示在长任务下的稳定性

---

## 2. 现状梳理

### 2.1 当前前后端路径

#### 路径 A：Excel / 手动输入（legacy，已删除）

```text
frontend/src/components/HomePage.tsx
  └─ 已删除 Excel / 手动输入入口

frontend/src/api/client.ts
  └─ legacy upload / generate API 已删除

backend/routers/upload.py
  └─ 已删除

backend/routers/report.py
  └─ `/generate` 与 `/batch-generate` 已删除

backend/services/pipeline.py
  └─ 已删除
```

#### 路径 B：智能录入（当前主路径）

```text
frontend/src/components/IntakeAgent.tsx
  ├─ startParseIntake()
  ├─ getParseIntakeStatus()
  ├─ 解析结果确认层
  └─ executeIntake()

frontend/src/api/client.ts
  ├─ /api/intake/parse
  ├─ /api/intake/execute-v3
  ├─ /api/intake/tasks
  └─ /api/intake/cancel/{task_id}

backend/routers/intake.py
  ├─ /parse -> intake_agent_v3 + matcher_agent + intake_merger
  ├─ /parse-async -> 后台解析任务
  ├─ /parse-status/{id} -> 解析状态轮询
  └─ /execute-v3 -> services/pipeline_v3.py

backend/services/pipeline_v3.py
  └─ WriterAgent -> save chunks -> RatingAgent
```

### 2.2 已完成下线的旧路径耦合点

#### 前端

- `frontend/src/components/HomePage.tsx`
  - 已移除三模式切换、Excel 专属项目选择、模板下载、手动输入表单
- `frontend/src/api/client.ts`
  - 已删除 `uploadExcel`、`submitManualInput`、`getFieldDefs`、`generateReport`、`batchGenerateReports`
- `frontend/src/types/index.ts`
  - legacy 类型已删除：`UploadResponse`、`ManualInputResponse`、`FieldDef`、`GenerateResponse`
- `frontend/src/components/ReportDetail.tsx`
  - 已兼容 v3 chunks 读取
- `frontend/src/components/ReportsPage.tsx`
  - 已改为“智能更新”，走 v3 入口

#### 后端

- `backend/routers/upload.py`
  - 已删除；剩余 helper 已下沉到 `backend/services/intake_session_store.py`
- `backend/routers/report.py`
  - `/generate` 和 `/batch-generate` 已删除
- `backend/services/pipeline.py`
  - 已删除
- `backend/services/light_update_pipeline.py`
  - 已删除
- `backend/services/task_manager.py`
  - 已补充 v3 任务持久化视图，但不承担 legacy 恢复

### 2.3 当前关注点

1. 历史 legacy 报告仍需继续验证读取、下载、分块编辑兼容性
2. v3 任务已经持久化到 `pipeline_tasks`，但当前不做“重启后继续执行”的自动恢复
3. 文档与项目说明需要持续跟进代码现状，避免残留 legacy 描述误导开发

---

## 3. 目标态定义（Only V3）

### 3.1 用户入口

首页只保留一个录入入口：

- `智能录入`

支持输入：

- 文本
- URL
- 附件（图片 / PDF / DOCX / PPTX / TXT / MD）

移除入口：

- `上传 Excel`
- `手动输入`
- `下载 Excel 模板`
- Excel 项目选择 / 批量生成 UI

### 3.2 统一任务流

```text
输入材料
  -> parse
  -> 匹配/确认
  -> execute
  -> v3 pipeline
  -> reports + report_chunks + attachments
```

推荐统一阶段：

1. `parse`：识别标的、生成摘要、初步关联附件
2. `match`：与现有标的匹配，判定 create/update
3. `confirm`：人工确认或自动确认
4. `execute`：进入 v3 pipeline
5. `consume`：列表 / 详情 / 下载 / 评级确认 / 更新记录

### 3.3 统一状态机

建议最终统一为以下状态模型：

- `draft`
- `queued`
- `running_writer`
- `saving`
- `rating_pending_confirm`
- `completed`
- `updated`
- `failed`
- `cancelled`

前端不再同时理解：

- legacy SSE `report/progress/{task_id}`
- intake 内存任务 `_intake_tasks`

### 3.4 统一数据模型

#### 保留为长期主模型

- `reports`
- `report_chunks`
- `report_versions`
- `intake_logs`
- 通用化后的 `pipeline_tasks`

#### 兼容保留，逐步降级

- `reports.md_path`
- `reports.chunks_path`
- `reports.debug_dir`
- `reports.attachments_dir`

#### 待下线

- `upload_sessions`

### 3.5 保留能力 vs 下线能力

#### 保留能力

- 智能录入新建标的
- 智能录入更新已有标的
- 报告详情查看、下载、版本回滚
- 报告附件管理
- 更新记录查看
- A-E 可行性评级与人工确认

#### 下线能力

- Excel 模板下载
- Excel 解析录入
- 手动字段表单录入
- session 型附件上传
- 基于 `upload_sessions` 的单个/批量生成
- legacy 6-step 新任务创建

---

## 4. 分阶段实施方案

以下分阶段内容保留为实施记录；截至 2026-04-17，这四个阶段均已完成。

### 阶段 1：隐藏旧入口，保留后端旧链用于兜底（已完成）

**目标**：先把产品入口收敛，但不立刻删除旧路由，降低切换风险。

#### 前端改造

- `frontend/src/components/HomePage.tsx`
  - 移除模式切换 UI，只显示 `IntakeAgent`
  - 删除 Excel / 手动输入相关步骤区块
  - 删除模板下载入口
  - 删除批量生成按钮和项目选择器
- `frontend/src/components/ReportsPage.tsx`
  - 将“重新生成”改为“智能更新”
  - 智能更新入口不再依赖 legacy `manualData`
- `frontend/src/api/client.ts`
  - legacy API 标记为 deprecated，前端不再调用

#### 后端改造

- 实施当时暂未删除 `backend/routers/upload.py`
- 实施当时暂未删除 `backend/routers/report.py:/generate`
- 最终阶段已全部移除，不再使用 feature flag 控制 legacy 入口

#### 风险

- 低
- 主要是首页交互和跳转路径变化

### 阶段 2：补全 v3 主链闭环（已完成）

**目标**：让 v3 真正替代 legacy，成为唯一可执行链路。

#### 后端改造

- `backend/routers/intake.py`
  - `/parse` 改为真正接入：
    - `backend/agents/intake_agent_v3.py`
    - `backend/agents/matcher_agent.py`
    - `backend/agents/intake_merger.py`
    - `backend/utils/writer_input_builder.py`
  - 统一 parse 输出模型
- `backend/services/pipeline_v3.py`
  - 接入附件文件名与附件元数据
  - 写入 `reports.attachments`
  - 对更新流程补齐与 `report_chunks` 的一致写入
- `backend/agents/writer_agent.py`
  - 修正附件读取路径与实际存储结构不一致的问题
  - 明确共享上下文中附件摘要、调研结果、existing chunks 的使用方式
- `backend/services/task_manager.py`
  - 扩展为 v3 通用任务持久化
  - intake 执行不再只依赖 `_intake_tasks`

#### 前端改造

- `frontend/src/components/IntakeAgent.tsx`
  - 增加“解析结果确认”层
  - 支持人工确认项目名称、create/update、匹配结果
  - 统一显示任务状态
- `frontend/src/types/index.ts`
  - 增加 v3 parse / confirm / execute 专用类型

#### 风险

- 高
- 这是主替换阶段，附件、匹配、任务状态最容易出问题

### 阶段 3：统一报告消费层（已完成）

**目标**：详情页、列表页、chunks、附件、日志全部优先围绕 v3 模型工作，同时兼容 legacy 历史数据。

#### 前端改造

- `frontend/src/components/ReportDetail.tsx`
  - 根据报告格式自动选择 chunks 数据源
- `frontend/src/components/ChunkEditor.tsx`
  - 支持 `report_chunks` 表，不再只依赖 `_chunks.json`
- `frontend/src/components/ReportsPage.tsx`
  - 状态列统一读取通用任务状态
  - 更新入口统一跳转到智能录入更新

#### 后端改造

- `backend/routers/report.py`
  - `/report/{id}/chunks` 改成统一适配层
  - `/report/{id}` 继续兼容 legacy markdown 和 v3 chunk 反组装
  - 附件、下载、版本、评级确认接口全部验证 v3/legacy 两侧兼容性

#### 风险

- 中高
- 影响范围覆盖详情页、列表页、下载与编辑链路

### 阶段 4：删除旧服务与旧路由（已完成）

**目标**：Only V3 正式收口。

#### 删除项

- `backend/routers/upload.py`
  - `/template`
  - `/excel`
  - `/manual`
  - `/fields`
  - session 型 `/attachments`
- `backend/routers/report.py`
  - `/generate`
  - `/batch-generate`
- `backend/services/pipeline.py`
- `backend/services/light_update_pipeline.py`
- `frontend/src/api/client.ts`
  - `uploadExcel`
  - `submitManualInput`
  - `getFieldDefs`
  - `generateReport`
  - `batchGenerateReports`
- `frontend/src/types/index.ts`
  - legacy 上传与手动录入类型

#### 配置收敛

- `backend/config.py`
- `settings.json`
- `frontend/src/components/SettingsPanel.tsx`

将配置收敛为：

- `intake_agent`
- `researcher`（如果 WriterAgent 继续依赖）
- `writer_agent`
- `rating_agent`
- `fastgpt`
- `tools`

#### 风险

- 中
- 删除阶段的核心风险是遗漏少量引用和文档失真

---

## 5. 详细改造清单

### 5.1 前端

#### `frontend/src/components/HomePage.tsx`

- 删除 `InputMode = "excel" | "manual"`
- 删除 Excel 上传、手动录入、模板下载、项目选择、批量生成 UI
- 保留并加强 `IntakeAgent` 容器
- 再生成改为“带上下文的智能更新入口”

#### `frontend/src/components/IntakeAgent.tsx`

- 增加 parse -> confirm -> execute 三段式 UI
- 支持低置信度匹配提醒
- 任务状态改为统一任务模型
- 保留终止功能，但后端状态源改为持久化任务表

#### `frontend/src/api/client.ts`

- 新增或重构：
  - `parseIntakeV3`
  - `confirmIntakeTargets`
  - `executeIntakeV3`
  - `listPipelineTasks`
- 删除 legacy 调用点

#### `frontend/src/types/index.ts`

- 清理 legacy 类型
- 新增：
  - `IntakeTarget`
  - `MatcherResult`
  - `IntakeConfirmationItem`
  - 通用 `PipelineTask`

#### `frontend/src/components/ReportDetail.tsx`

- 详情页 chunks tab 根据 `report_format` 或统一 API 适配
- 不再把 legacy `_chunks.json` 当作唯一来源

#### `frontend/src/components/ChunkEditor.tsx`

- 接入 v3 chunk 保存逻辑
- 确认 legacy 报告仍可查看或只读编辑

### 5.2 后端

#### `backend/routers/intake.py`

- `/parse` 切到 v3 parse + match + merge
- `/execute-v3` 入参与 parse 结果统一
- 统一任务创建与状态更新

#### `backend/services/pipeline_v3.py`

- 接通附件
- 接通通用任务状态持久化
- create/update 都写入统一元数据

#### `backend/agents/writer_agent.py`

- 修复附件读取路径
- 校验 `read_attachment` 与实际附件存储目录一致
- 规范工具调用的容错和日志

#### `backend/routers/report.py`

- 统一 report/chunks 读取
- 保留 legacy 历史读取兼容
- 下线 session 型生成接口

#### `backend/services/task_manager.py`

- 从 legacy pipeline manager 升级为通用 pipeline manager
- 覆盖 v3 任务恢复、取消、状态查询

### 5.3 DB

#### 建议长期保留

- `reports`
- `report_chunks`
- `report_versions`
- `intake_logs`
- `pipeline_tasks`

#### 建议降级为兼容字段

- `reports.md_path`
- `reports.chunks_path`
- `reports.debug_dir`
- `reports.attachments_dir`

#### 建议废弃

- `upload_sessions`

### 5.4 配置

#### `backend/config.py`

- 移除 legacy-only 默认项：
  - `extractor`
  - `field_extractor`
  - `chunker`

#### `frontend/src/components/SettingsPanel.tsx`

- 从“步骤型配置”改为“能力型配置”
- 避免用户继续配置已经不生效的 legacy 模型

#### `settings.json`

- 缩减为 Only V3 需要的配置项
- 保留 feature flag 用于过渡期回滚

---

## 6. 兼容与迁移策略

### 6.1 历史数据兼容

历史 legacy 报告继续：

- 可列表展示
- 可打开详情页
- 可下载 markdown / pdf
- 可查看附件、版本、更新记录

### 6.2 历史报告升级策略

不做一次性全量迁移。

推荐策略：

1. 历史 legacy 报告保留 `report_format='legacy'`
2. 新建报告默认 `report_format='v3'`
3. 当 legacy 报告首次通过智能录入更新时：
   - 写入 `report_chunks`
   - 补齐附件元数据
   - 保留旧 md/json/chunks 文件作为兼容层
   - 将 `report_format` 切为 `v3`

### 6.3 灰度开关

建议保留阶段性开关：

- `features.only_v3_intake`
- `features.disable_legacy_generate`

用途：

- 先隐藏旧入口
- 再关闭旧后端生成接口
- 最后删除物理代码

### 6.4 回滚策略

回滚不依赖恢复代码，而依赖过渡期保留 legacy 路由：

1. 首页隐藏旧入口阶段，后端 legacy 路由继续保留
2. Only V3 内测阶段，如发现主链问题，可暂时重新打开旧入口
3. 等 v3 闭环稳定一段周期后，再删除 legacy 路由与服务

---

## 7. 测试与验收

### 7.1 主流程测试

- 纯文本创建新标的
- 文本 + URL 创建新标的
- 文本 + 附件创建新标的
- 单次输入识别多个标的
- 智能更新已有标的
- 更新触发评级确认
- 报告详情、附件、更新记录、版本历史可正常访问

### 7.2 异常测试

- parse 无结果
- match 置信度低
- 附件解析失败
- WriterAgent 失败
- RatingAgent JSON 解析失败
- 任务中断 / 服务重启恢复

### 7.3 回归重点

- `frontend/src/components/ReportsPage.tsx`
- `frontend/src/components/ReportDetail.tsx`
- `frontend/src/components/ChunkEditor.tsx`
- `backend/routers/report.py`
- `backend/routers/intake.py`
- `backend/services/pipeline_v3.py`
- `backend/services/task_manager.py`

### 7.4 手工验收清单

- 首页只剩“智能录入”
- 再也看不到 Excel 模板下载和手动输入表单
- 能用智能录入创建新报告
- 能用智能录入更新已有报告
- 报告详情的 chunks、附件、更新记录可正常使用
- 历史 legacy 报告仍可读、可下载

---

## 8. PR 拆分建议

### PR1：入口收敛

- 隐藏 legacy 入口
- 保留旧后端路由
- 改造首页和列表页跳转

### PR2：v3 主链补全

- parse 切换到真正 v3 方案
- 补齐附件链路
- 统一 v3 任务持久化

### PR3：报告消费层统一

- 统一 report/chunks/attachments/detail
- 报告详情兼容 legacy 与 v3

### PR4：删除 legacy

- 删除 upload 路由
- 删除 generate/batch-generate
- 删除 `pipeline.py` / `light_update_pipeline.py`
- 收敛 settings 与文档

---

## 9. 当前建议

执行顺序固定为：

1. **隐藏旧入口**
2. **补全 v3**
3. **统一详情与消费层**
4. **删除旧服务和路由**

不建议跳过第二步直接删除 legacy。当前 v3 还存在 parse、附件、chunks、任务持久化四个未闭环点，直接删旧链会放大故障半径。
