# 附件驱动更新链路（2026-04-19）

## 目标

首页附件弹窗上传新材料后，允许用户选择：

- 仅保存附件
- 保存并更新报告

更新流程为独立链路，不复用智能录入主流程，不进行联网调研，仅执行：

- 附件解析
- 更新规划（AttachmentUpdatePlanner）
- 定向 chunk 写作
- 评级
- FastGPT 推送


## 主要代码落点

### 后端

- `backend/routers/report.py`
  - 新增 `POST /api/report/{report_id}/attachments/update-report`
  - 负责创建附件更新任务、写入 `pipeline_tasks`、异步启动更新流程
- `backend/services/attachment_update_pipeline.py`
  - 新增附件更新专用 pipeline
  - 负责：
    - 读取并解析选中的附件
    - 调用 `AttachmentUpdatePlanner`
    - 定向调用 `chunk_writer`
    - 保存 chunk / metadata
    - 调用 `RatingAgent`
    - 自动推送 FastGPT
- `backend/prompts/attachment_update_planner_prompt.py`
  - 新增附件更新 planner 默认提示词
- `backend/services/intake_log_service.py`
  - 抽出通用的更新记录写入函数
- `backend/routers/intake.py`
  - `/intake/tasks` 适配 `task_kind="attachment_update"`，首页统一显示为“更新中”
- `backend/services/model_workbench.py`
  - 新增模型节点 `attachment_update_planner`
- `backend/config.py`
  - 新增 `DEFAULT_AI_CONFIG["attachment_update_planner"]`
- `backend/routers/settings.py`
  - 设置模型配置时支持 `attachment_update_planner`


### 前端

- `frontend/src/components/AttachmentPopover.tsx`
  - 上传附件成功后弹出二次确认弹窗
  - 支持选择“仅保存附件”或“保存并更新报告”
  - 支持勾选参与本次更新的附件、填写备注
  - 当首页当前项目无附件时，按钮不再显示 `--`，而是显示 `上传`，仍走同一个附件弹层
- `frontend/src/api/client.ts`
  - 新增 `startAttachmentUpdate(reportId, attachmentFilenames, note)`
- `frontend/src/components/ReportsPage.tsx`
  - 增加 `window.__refreshIntakeTasks`
  - 附件更新任务创建后可立即重启首页状态轮询
  - 附件列始终渲染 `AttachmentPopover`，0 附件项目也有入口
- `frontend/src/components/IntakeLogs.tsx`
  - 新增 `attachment_update` 记录类型展示
- `frontend/src/types/index.ts`
  - 增加 `attachment_update_planner` 模型配置
  - 扩展 `IntakeExecuteResult` / `IntakeLog` 类型


## 任务与状态设计

- `pipeline_tasks.task_kind = "attachment_update"`
- 首页列表仍通过 `/api/intake/tasks` 读取活跃 v3 任务
- `attachment_update` 任务在首页状态列统一展示为“更新中”

附件更新推荐阶段：

1. 附件更新规划
2. 更新 chunk
3. 保存数据
4. 评级
5. 推送（FastGPT 开启时）


## 更新记录设计

附件更新成功后，在 `intake_logs` 写入一条：

- `log_type = "attachment_update"`
- `trigger_reason = "首页附件上传后触发更新（不联网调研）"`
- `input_sources = 本次参与更新的附件文件名`
- `changed_fields = 受影响 chunk 的中文标签`
- `steps_executed = ["AttachmentUpdatePlanner", "ChunkWriter", "RatingAgent", "FastGPTPush"]`

说明：

- 当前未处理“新建记录未展示”的历史问题
- 本次仅保证附件更新完成后会新增一条更新记录


## 配置说明

在「设置 -> 模型与提示词」新增节点：

- `AttachmentUpdatePlanner`

该节点仅负责：

- 读取新附件解析内容
- 结合现有 chunk 摘要判断受影响章节
- 为每个受影响 chunk 生成增量更新指令

该节点不负责：

- 联网调研
- 正文写作
- 评级
- 推送


## 风险与后续建议

- 当前附件更新日志写入发生在任务成功完成后；失败任务暂不写详情页更新记录
- `changed_fields` 目前用来表达“哪些 chunk 被更新”，后续如需更细粒度可新增 `extra_json`
- 如果后续要支持“从详情页附件 Tab 直接触发更新”，可复用同一接口与同一 pipeline
- 首页附件弹层空状态目前已增加“上传附件”引导，避免 0 附件项目无操作入口
- `execute-v3` 已增加后端附件兜底：若前端 draft merge 后丢失 `related_attachment_paths`，但仍保留 `available_attachment_paths`，create/update 执行时会自动回退使用全部可用附件，避免新建项目附件未入报告目录
