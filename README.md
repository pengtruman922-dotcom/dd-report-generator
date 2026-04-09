# 尽调报告生成器 (DD Report Generator)

基于 AI 的智能尽职调查报告生成系统。支持 Excel/手动录入 → 6步 AI 流水线 → Markdown 报告输出 → FastGPT 知识库推送。

---

## 功能概览

### v1.0（已上线）
- **Excel 批量导入**：26列标准模板，自动解析；一键下载模板
- **手动录入模式**：无需 Excel，直接在线填写
- **附件解析**：PDF（含 OCR）、Word、PPT、Markdown 自动提取
- **6步 AI 流水线**（实时 SSE 进度推送）：
  1. Extractor：信息提取 → CompanyProfile JSON
  2. Researcher：联网调研（最多18轮，自适应）
  3. Writer：生成完整尽调报告（~5000-10000字 Markdown）
  4. FieldExtractor：字段回填到数据库
  5. Chunker：规则分块 + AI 生成搜索标签
  6. FastGPT Push：推送到知识库
- **批量生成**：一次性生成多份报告，并发执行
- **报告管理**：列表搜索/筛选/分页、在线编辑、版本历史、FastGPT 批量推送
- **任务持久化**：服务重启后自动恢复进行中的任务
- **搜索容灾**：Bocha → Baidu → Bing → DuckDuckGo 自动 fallback
- **用户权限**：多用户登录，admin 角色管理

### v2.0（开发中）
- **智能录入 Agent**：直接投入聊天记录/截图/文档/链接，AI 自动解析为操作指令
- **轻量更新流程**：仅字段变化时跳过重调研，Step3' 直接重写报告（节省 5-15 分钟）
- **更新记录 Tab**：每次操作的完整数据处理日志

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端框架 | FastAPI + Uvicorn + SSE-Starlette |
| AI 模型 | 阿里云 DashScope（Qwen3-Max / qwen3.5-plus） |
| 数据库 | SQLite（bcrypt 密码哈希） |
| 文档解析 | PyMuPDF、pdfplumber、rapidocr、python-docx、python-pptx |
| 搜索工具 | Bocha、Baidu、Bing、DuckDuckGo（fallback 链） |
| 网页抓取 | Jina Reader、本地 Scraper |
| 数据源 | cninfo（巨潮）、akshare、tianyancha、gsxt |
| 前端框架 | React 19 + TypeScript + Vite |
| 路由 | React Router v7 |
| 样式 | Tailwind CSS |

---

## 快速开始

### 前置条件

- Python 3.11+
- Node.js 18+
- 阿里云 DashScope API Key（必须）
- Bocha 搜索 API Key（可选，有 fallback）

### 1. 配置

```bash
cp settings.example.json settings.json
# 编辑 settings.json，填入 API keys（最少填 ai_config 下的 api_key 和 base_url）
```

`settings.json` 最小配置示例：

```json
{
  "ai_config": {
    "extractor":       { "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key": "sk-xxx", "model": "qwen3-max" },
    "researcher":      { "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key": "sk-xxx", "model": "qwen3-max" },
    "writer":          { "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key": "sk-xxx", "model": "qwen3-max" },
    "field_extractor": { "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key": "sk-xxx", "model": "qwen3-max" },
    "chunker":         { "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key": "sk-xxx", "model": "qwen3-max" },
    "intake_agent":    { "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key": "sk-xxx", "model": "qwen3.5-plus" }
  },
  "tools_config": {
    "search":  { "active_provider": "duckduckgo", "fallback_chain": ["duckduckgo"] },
    "scraper": { "active_provider": "jina_reader" }
  },
  "fastgpt_config": { "enabled": false }
}
```

### 2. 安装依赖

```bash
# 后端
pip install -r backend/requirements.txt

# 前端
cd frontend && npm install
```

### 3. 启动（Windows）

```bat
start.bat
```

脚本自动启动后端（:8000）+ 前端（:5173）并打开浏览器。

### 3. 启动（其他平台）

```bash
# 终端 1：后端
python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload

# 终端 2：前端
cd frontend && npm run dev
```

访问 http://localhost:5173，默认账号：`admin` / `admin123`（首次登录强制改密）

---

## 生产部署

参考 [DEPLOYMENT.md](./DEPLOYMENT.md)（Linux/阿里云，Nginx + Supervisor）。

---

## 项目结构

```
dd-report-generator/
├── backend/
│   ├── main.py              # FastAPI 入口，注册所有 router
│   ├── config.py            # 全局常量（路径、AI 默认配置、搜索配置）
│   ├── db.py                # SQLite schema（users/sessions/reports/tasks/intake_logs 等）
│   ├── auth.py              # JWT token 验证中间件
│   ├── agents/              # AI Agent（每个步骤一个文件）
│   │   ├── base_agent.py    # AsyncOpenAI 客户端封装
│   │   ├── extractor.py     # Step1：信息提取
│   │   ├── researcher.py    # Step2：联网调研（tool-loop，自适应迭代）
│   │   ├── writer.py        # Step3：报告撰写（流式输出）
│   │   ├── field_extractor.py # Step4：字段回填
│   │   ├── chunker.py       # Step5：AI 索引标签生成
│   │   └── intake_agent.py  # v2.0 录入 Agent（多模态 + 意图解析）
│   ├── prompts/             # 各 Agent 的系统提示词（与 agents/ 一一对应）
│   ├── parsers/             # 文档解析器（excel/pdf/docx/pptx/md + OCR）
│   ├── services/
│   │   ├── pipeline.py      # 6步流水线编排
│   │   ├── light_update_pipeline.py  # v2.0 轻量更新（Step3'+4+5+6）
│   │   ├── task_manager.py  # 任务生命周期管理（SQLite 持久化 + 崩溃恢复）
│   │   ├── sse_manager.py   # SSE 事件广播
│   │   ├── fastgpt_uploader.py  # FastGPT 知识库推送客户端
│   │   ├── chunker.py       # 规则分块（按中文数字章节标题）
│   │   ├── version_manager.py   # 报告版本快照管理
│   │   └── token_tracker.py     # Token 用量 & 费用统计
│   ├── tools/               # 搜索/抓取/数���源工具（含 fallback 包装器）
│   │   ├── fallback.py      # FallbackToolProvider：自动切换 provider
│   │   ├── registry.py      # 工具注册表
│   │   ├── bocha_search.py / baidu_search.py / bing_search.py / duckduckgo_search.py
│   │   ├── jina_reader.py / local_scraper.py
│   │   └── cninfo.py / akshare_data.py / tianyancha.py / gsxt_scraper.py
│   ├── routers/
│   │   ├── upload.py        # Excel 上传/解析、手动录入、附件、模板下载
│   │   ├── report.py        # 报告 CRUD、生成触发、SSE 流、版本、FastGPT 推送
│   │   ├── intake.py        # v2.0 录入 Agent（/parse、/execute、/logs）
│   │   ├── tasks.py         # 任务列表/取消/清理
│   │   ├── settings.py      # AI 配置读写（admin）
│   │   ├── tools.py         # 工具配置读写（admin）
│   │   └── auth_router.py   # 登录/登出/用户管理
│   ├── migrations/          # 一次性数据迁移脚本（历史用，已执行）
│   ├── tests/               # pytest 自动化测试（83条）
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx           # 路由根
│       ├── api/client.ts     # HTTP 请求封装
│       ├── contexts/AuthContext.tsx
│       ├── hooks/useSSE.ts   # SSE 订阅 hook
│       ├── types/index.ts    # TypeScript 类型定义
│       └── components/       # 所有页面与组件（见下）
├── docs/
│   ├── reliability.md        # 搜索容灾 & 自适应迭代设计说明
│   └── testing.md            # 测试套件说明
├── .project/
│   ├── ROADMAP.md            # 项目管理主索引（功能进度 + Bug 追踪）
│   └── design/
│       └── v2-smart-intake.md  # v2.0 详细设计文档
├── settings.example.json     # 配置模板
├── settings.json             # 运行时配置（gitignored，含 API keys）
├── start.bat                 # Windows 一键启动脚本
├── deploy.sh                 # Linux 自动部署脚本（阿里云）
├── DEPLOYMENT.md             # 生产部署详细指南
└── data/users.db             # SQLite 数据库（gitignored）
```

### 前端组件一览

| 组件 | 功能 |
|------|------|
| `HomePage.tsx` | 主录入页（Excel / 手动 两种模式） |
| `ReportsPage.tsx` | 报告列表（搜索、筛选、分页） |
| `ReportDetail.tsx` | 报告详情（内容 / 分块 / 版本历史 / 更新记录 四个 Tab） |
| `PipelineProgress.tsx` | 6步（或3步轻量）进度面板（SSE 实时） |
| `IntakeAgent.tsx` | v2.0 录入 Agent 输入区 + 手动模式预览卡 |
| `IntakeLogs.tsx` | v2.0 更新记录历史列表 |
| `BatchProgress.tsx` | 批量生成进度 |
| `SettingsPanel.tsx` | AI 配置（6个 Agent + FastGPT） |
| `ToolSettingsPanel.tsx` | 搜索/抓取/数据源配置 |
| `ChunkEditor.tsx` | 分块内容编辑 |
| `VersionHistory.tsx` | 版本列表 + 回滚 |
| `AccountManager.tsx` | 用户管理（admin） |

---

## 关键配置说明

### 搜索 Provider（settings.json）

```json
"search": {
  "active_provider": "bocha",
  "fallback_chain": ["bocha", "baidu", "bing_china", "duckduckgo"],
  "providers": {
    "bocha":     { "api_key": "xxx" },
    "baidu":     { "api_key": "xxx", "secret_key": "xxx" },
    "duckduckgo": { "proxy": "http://127.0.0.1:7890" }
  }
}
```

无 API key 时 `duckduckgo` 可作为免费 fallback，需代理访问。

### 研究迭代次数（config.py）

```python
RESEARCH_ITERATIONS = {"listed": 10, "unlisted": 18, "default": 15}
SEARCH_QUALITY_THRESHOLD = 0.3   # 低于此分数自动切换 provider
MAX_TOOL_ITERATIONS = 15
```

### FastGPT（settings.json）

```json
"fastgpt_config": {
  "enabled": true,
  "base_url": "http://your-fastgpt:3100",
  "api_key": "fastgpt-xxx",
  "dataset_id": "xxx"
}
```

---

## 运行测试

```bash
cd backend
pip install pytest pytest-asyncio
pytest tests/ -v
```

共 83 条自动化测试，覆盖：搜索 fallback、质量评估、自适应迭代、任务持久化、SSE 流。

---

## API 文档

启动后端后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## 常见问题

**Q: 报告生成失败？**
1. 检查 `settings.json` API key 是否正确
2. 查看后端终端日志（Step 编号 + 错误信息）
3. 确认 API 余额充足，网络可访问 DashScope

**Q: 搜索结果为空？**
- 检查搜索 provider 配置；可临时切换为 `duckduckgo`（需代理）
- 查看 `fallback_chain` 是否配置了多个 provider

**Q: FastGPT 推送失败？**
- 检查 `fastgpt_config.enabled` 是否为 `true`
- 确认 FastGPT 服务地址和 API key 可用
- BUG-003：公司名修改后重推可能产生重复 collection，暂需手动在 FastGPT 清理旧条目

**Q: uploads/ 目录越来越大？**
- BUG-004：session 无自动清理，可手动删除 `uploads/` 下过期目录
- 临时方案：定期运行 `find uploads/ -mtime +7 -type d | xargs rm -rf`

---

## 许可证

MIT License
