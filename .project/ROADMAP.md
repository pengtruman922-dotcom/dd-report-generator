# DD Report Generator · 项目路线图

> 本文件是项目管理的主索引。所有功能设计、开发任务、Bug 修复均在此追踪。
> 最后更新：2026-04-17

---

## 文件夹说明

```
.project/
├── ROADMAP.md              ← 你在这里：主索引，进度总览
└── design/
    ├── v2-smart-intake.md        ← v2.0 功能设计文档（详细需求、交互方案）
    ├── v3-development-plan.md    ← 既有 v3.0 智能录入开发计划
    ├── only-v3-migration-plan.md ← Only V3 收敛与迁移方案（2026-04-16）
    └── only-v3-acceptance-checklist.md ← Only V3 手工回归与验收清单
```

---

## 当前版本状态

| 版本 | 状态 | 说明 |
|------|------|------|
| v1.0 | ✅ 已上线 | 基础流水线：Excel录入 → 6步生成 → FastGPT推送 |
| v2.0 | 🟡 开发中 | 智能录入 Agent + 轻量更新流程（部分已实现，见下方）|
| v2.1 | 🟡 开发中 | 并行执行 + 任务终止 + prompt精简（本次迭代）|
| v3-only | ✅ 主体完成 | Only V3 已切主线，进入回归与验收阶段 |

---

## 当前优先事项（2026-04-17）

### Only V3 收敛

已完成：

- `design/only-v3-migration-plan.md`
- `design/only-v3-acceptance-checklist.md`

已按既定顺序完成：

1. 隐藏旧入口
2. 补全 v3 主链闭环
3. 统一详情页与报告消费层
4. 删除旧服务与旧路由

当前重点：

1. 手工回归 Only V3 主流程
2. 验证历史 legacy 报告消费兼容
3. 收口残余文档描述

### 本轮关注范围

| 方向 | 核心文件 | 结论 |
|------|---------|------|
| 首页录入 | `frontend/src/components/HomePage.tsx` | 已收敛为 Only V3 |
| 智能录入执行 | `backend/routers/intake.py` | 已切到 v3 parse + execute-v3 |
| v3 编排 | `backend/services/pipeline_v3.py` | 已成为唯一执行主链 |
| 报告消费层 | `frontend/src/components/ReportDetail.tsx` / `backend/routers/report.py` | 已完成 v3 / legacy 兼容适配 |
| 旧链下线 | `backend/services/intake_session_store.py` | legacy 路由已删，剩余仅保留 v3 所需 helper |

---

## v2.1 本次迭代（2026-04-08）

### 需求背景
三轮测试优化（详见 `docs/测试优化-第*.md`）后进入下一阶段功能迭代，核心目标：
1. 提升 existing_targets prompt 质量（精简字段，扩大数量）
2. 多标的并行执行（滑动窗口队列，最多5并行）
3. 全局任务状态可见（首页实时显示生成/更新进度）
4. 任务终止功能（含回滚）

### 模块变更清单

#### 后端变更

| 文件 | 变更内容 | 状态 |
|------|---------|------|
| `agents/intake_agent_v3.py` / `agents/matcher_agent.py` | v3 解析与匹配替代旧 intake agent | ✅ 完成 |
| `agents/intake_merger.py` | 解析结果与匹配结果合并为确认层数据 | ✅ 完成 |
| `routers/intake.py` | parse后根据company_name模糊匹配补填bd_code；更新操作执行前保存旧数据快照 | ✅ 完成 |
| `routers/intake.py` | 新增 `/cancel/{task_id}` 终止接口；终止时新建删数据，更新回滚快照 | ✅ 完成 |
| `services/task_manager.py` | 新增滑动窗口队列（最多5并行），任务状态增加 queued/cancelling | ✅ 完成 |

#### 前端变更

| 文件 | 变更内容 | 状态 |
|------|---------|------|
| `types/index.ts` | 新增 TaskStatus 类型，IntakeExecuteResult 增加 queue_position | ✅ 完成 |
| `api/client.ts` | 新增 cancelTask API | ✅ 完成 |
| `components/IntakeAgent.tsx` | 多任务卡片列表，每张独立进度+终止按钮，滑动窗口状态展示 | ✅ 完成 |
| `components/ReportsPage.tsx` | 报告生成状态列实时从任务队列读取，覆盖DB status显示 | ✅ 完成 |
| `hooks/useTaskQueue.ts` | 新增全局任务队列 hook，轮询后端任务状态 | ✅ 完成 |

### 终止行为规范
- 点击终止 → 二次确认弹窗："终止任务将丢失本次操作的数据，确认终止？"
- **新建任务终止**：删除已写入的 report 记录 + outputs 文件
- **更新任务终止**：从内存快照恢复旧 DB 字段值 + 旧 MD 文件内容
- task 从内存队列删除，重启后丢失（可接受）

### 状态流转
```
排队中(第N位) → 生成中 Step1/6 → ... → 完成
                              ↘ 终止中 → [删除/回滚] → 已终止(从队列移除)
```

---

## v2.0 功能模块进度

### 模块一：录入 Agent
| 子功能 | 状态 | 说明 |
|--------|------|------|
| 混合输入支持（文字/图片/文档/链接） | ✅ 已完成 | `IntakeAgent.tsx` UI + 后端 `intake_agent_v3.py` |
| 多模态图片理解（qwen3.5-plus） | ✅ 已完成 | prompt + 前端联调完成 |
| 网页智能下钻（最多3次） | ⬜ 待开发 | 设计完成，未实现 |
| 多标的识别与意图解析 | ✅ 已完成 | 含新建/更新混合识别 |
| existing_targets精简（名称+行业，1000条）| ✅ 已完成 | v2.1 |
| bd_code Python侧模糊补填 | ✅ 已完成 | v2.1 |

### 模块二：执行模式
| 子功能 | 状态 | 说明 |
|--------|------|------|
| 统一确认后执行 | ✅ 已完成 | `parse-async` + 确认层 + `/execute-v3` |
| 手动确认模式（预览卡） | ✅ 已完成 | `IntakeAgent.tsx` 确认层 |
| 并行执行（滑动窗口，最多5个）| ✅ 已完成 | v2.1 |
| 任务终止（含回滚）| ✅ 已完成 | v2.1 |

### 模块三：v3 更新流程
| 子功能 | 状态 | 说明 |
|--------|------|------|
| v3 更新执行 | ✅ 已实现 | `pipeline_v3.py` |
| 解析确认后更新 | ✅ 已实现 | `IntakeAgent.tsx` |
| 附件/材料摘要透传 | ✅ 已实现 | `routers/intake.py` → `pipeline_v3.py` |

### 模块四：更新记录
| 子功能 | 状态 | 说明 |
|--------|------|------|
| `intake_logs` 数据库表 | ✅ 已实现 | `db.py` 中已建表 |
| 报告详情页「更新记录」Tab | ✅ 已实现 | `IntakeLogs.tsx` |

### 模块五：全局任务状态
| 子功能 | 状态 | 说明 |
|--------|------|------|
| 首页报告生成状态实时显示 | ✅ 已完成 | v2.1，轮询任务队列覆盖DB状态 |
| 录入页多任务卡片 | ✅ 已完成 | v2.1 |

---

## 已知 Bug

| ID | 问题 | 优先级 | 状态 |
|----|------|--------|------|
| BUG-001 | Excel上传时bd_code不一致 | P0 | ✅ 已修复 |
| BUG-002 | Step4字段回填未同步DB | P0 | ✅ 已修复 |
| BUG-003 | FastGPT重复推送旧collection未删除 | P2 | ⬜ 待修复 |
| BUG-004 | Session无TTL清理 | P2 | ⬜ 待修复 |
| BUG-005 | IntakeAgent.tsx引用未声明的urlInput/urls变量导致页面空白 | P0 | ✅ 已修复（2026-04-08）|

---

## 状态图例

| 标记 | 含义 |
|------|------|
| ⬜ | 待开发 / 待修复 |
| 🔵 | 设计完成，待开发 |
| 🟡 | 开发中（有代码但未完成） |
| ✅ | 已完成 |
| ❌ | 已取消 |
