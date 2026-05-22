# 首页慢刷新止血改造记录（2026-04-17）

## 背景

现象：

- 当后台同时运行 5 个 `WriterAgent` 任务时，从其他页面刷新首页（标的管理列表）明显变慢。

排查结论：

1. 首页列表接口 `GET /api/report/list` 在返回分页结果前，会对当前页每条报告调用 `_compute_push_status(...)`。
2. 旧实现中，`_compute_push_status(...)` 会进一步调用 `compute_chunks_hash(report_id)`。
3. 对 v3 报告来说，`compute_chunks_hash(...)` 需要重新查询 `report_chunks`、拼装 chunk 内容并计算哈希。
4. 当 `WriterAgent` 正在持续写入 `reports/report_chunks` 时，首页刷新会与这些写操作竞争 SQLite 读写资源，导致响应显著变慢。
5. 首页前端还会固定每 3 秒轮询一次 `listIntakeTasks()`，即使当前没有运行任务，也会持续发请求。

## 本次止血改造

### 1. 后端：列表页取消逐条 hash 重算

文件：

- `backend/routers/report.py`

改动：

- 删除列表页 `push_status` 计算中对 `compute_chunks_hash(...)` 的依赖。
- `_compute_push_status(...)` 现阶段仅做轻量判断：
  - 无 chunks：`no_chunks`
  - 有 chunks，但当前 dataset 无 push record：`not_pushed`
  - 有 chunks，且当前 dataset 有 push record：`pushed`

目的：

- 将首页列表请求从“读取报告 + 逐条重扫 chunk 内容”降级为“读取报告 + 轻量状态判断”。

### 2. 前端：首页任务轮询改为按需继续

文件：

- `frontend/src/components/ReportsPage.tsx`

改动：

- 原实现：`setInterval(poll, 3000)` 固定轮询 `listIntakeTasks()`。
- 新实现：
  - 页面加载先探测一次
  - 只有存在 `running/queued/cancelling` 任务时，才在 3 秒后继续下一轮轮询
  - 若没有运行中的任务，则停止继续轮询

目的：

- 避免首页在无任务时仍持续请求任务接口，减少不必要请求。

## 当前有意接受的降级

本次是“止血改造”，不是最终方案，因此有一个已知降级：

- 首页列表中的 `push_status` 暂时不会实时判断 `outdated`
- 也就是说，之前依赖“当前 chunks hash vs 上次推送 hash”得出的 `需更新` 状态，在首页列表页里暂时不再做强一致计算

影响范围：

- 仅影响首页列表页的 `push_status` 精细程度
- 不影响：
  - 报告生成
  - WriterAgent 执行
  - Push 记录写入
  - 报告详情

## 后续建议

若要做正式修复，不建议把实时 hash 计算再放回首页列表接口，而应改成：

1. 在 `reports` 表中增加持久化缓存字段，例如：
   - `chunks_hash`
   - `push_status_cached`
   - `push_status_updated_at`
2. 在写 chunks / push 成功时同步更新这些缓存字段
3. 首页列表直接读取缓存字段，不做逐条内容重算

## 验证

已做的本地验证：

- `python -m py_compile backend\\routers\\report.py`
- `npm.cmd run build`（frontend）

均通过。

