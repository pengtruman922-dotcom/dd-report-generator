# 设置页「模型与提示词」改造记录（2026-04-23）

## 本次目标

- 统一不同节点在设置页中的配置来源表达
- 去掉页面上直接展示默认 API Key 的风险
- 将模型配置、行为配置、提示词配置拆成稳定结构
- 给设置页补齐加载失败、保存状态和兼容节点折叠

## 后端改动

### `backend/services/model_workbench.py`

- 重新定义 workbench 节点输出结构
- provider 字段改为按字段返回：
  - `fields`
  - `summary`
  - `source`
  - `configured`
  - `default_value`
- behavior 字段改为按字段返回：
  - `fields`
  - `input_type`
  - `description`
  - `options`
  - `default_value`
- 新增统一来源语义：
  - `custom`
  - `inherited`
  - `system_default`
- fallback 节点不再简单按空对象/非空对象判断，而是按“是否存在有效覆盖值”判断
- chunk prompt 在设置页中改为业务化命名：
  - `Chunk 0 - 身份卡`
  - `Chunk 1 - 财务数据`
  - ...

## 前端改动

### `frontend/src/components/SettingsPanel.tsx`

- 重构为四段式详情结构：
  - 节点概览
  - 模型配置
  - 行为配置
  - 提示词配置
- 左侧导航支持：
  - 主链路优先
  - 兼容节点默认折叠
  - 提示词覆盖数量徽标
- 模型配置区改为展示“当前生效值 + 来源标签”
- API Key 改为状态展示：
  - `已配置`
  - `未配置`
  - 不再显示默认 key 文案
- 继承节点支持：
  - `启用独立模型配置`
  - `恢复继承`
- 顶层独立节点支持：
  - `恢复默认`
- FastGPT 与模型设置拆分独立加载/保存状态
- 增加：
  - 加载中状态
  - 加载失败重试
  - 未保存提示
  - 底部固定保存条
  - 每个节点模型配置区的 `连接测试` 按钮

### 本轮补充：模型连接测试

- 后端新增接口：
  - `POST /api/settings/model-workbench/test-node`
- 用法：
  - 前端提交当前 `node_id + ai_config`
  - 后端基于当前页面配置解析该节点的最终生效 `base_url / api_key / model`
  - 使用 OpenAI 兼容接口发起一次最小 chat completion 请求做连通性验证
- 目标：
  - 快速判断该节点当前模型参数是否有效
  - 支持继承节点和仅提示词节点，不要求前端展示真实 API Key
- 前端交互：
  - 测试中显示 `测试中...`
  - 成功/失败结果在模型配置区内联展示
  - 修改模型参数后会自动清空上一次测试结果

### `frontend/src/types/index.ts`

- 新增 workbench 视图类型：
  - `ModelConfigSourceView`
  - `ModelProviderFieldView`
  - `ModelBehaviorFieldView`
- 扩展 `ModelNodeView`
  - `node_kind`
  - `source_badge`
  - `can_customize`
  - `can_reset`
  - `prompt_override_count`

## 验证

- 后端语法检查：
  - `python -m py_compile backend/config.py backend/routers/settings.py backend/services/model_workbench.py`
- 前端构建：
  - `npm.cmd run build`

## 协同开发注意点

- 前端现在依赖新的 workbench 契约，不要再按旧结构读取：
  - `provider.current`
  - `provider.default`
  - `behavior.current`
  - `behavior.default`
- 如果后续继续扩展节点，优先在 `backend/services/model_workbench.py` 里补：
  - 节点定义
  - 字段 label
  - 输入类型
  - 来源语义
- 如果新增行为字段，优先补：
  - `_FIELD_LABELS`
  - `_FIELD_INPUT_TYPES`
  - `_FIELD_DESCRIPTIONS`
  - `_FIELD_OPTIONS`

---

## 本轮补充：Only V3 清理（2026-04-23）

- workbench 已删除 4 个 legacy 节点：
  - `extractor`
  - `writer`
  - `field_extractor`
  - `chunker`
- 后端 `load_settings()` 现在会主动清洗旧 `settings.json`：
  - 自动删除退役 `ai_config` 键
  - 自动补齐当前 v3 默认配置
  - 清洗后会回写磁盘，避免旧键持续污染设置页
- 设置页左侧导航不再展示“兼容节点折叠”交互，当前只展示仍在运行的 v3 节点
- `ChunkEditor` 只保留 v3 chunk 编辑，不再支持旧 `regenerate-chunks` 入口
