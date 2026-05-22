# DD Report Generator

并购 / 招商 / 项目推荐场景的信息沉淀系统。当前主线是 v4 写作链路：目标不再是生成一篇完整尽调报告，而是沉淀可检索、可维护的高密度事实。

## v4 核心产物

- `info_chunk`：通用、稳定、当前有效的标的信息事实块；用于检索和 FastGPT / 向量库推送。
- `tracking_chunk`：系统内部跟进动态时间线；保留历史推进、报价变化、买方反馈和沟通记录；不推送 FastGPT。

`info_chunk` 不写买家推荐、shortlist、next step、推进策略、主观投资判断或特定买方态度。

## 当前主链路

后端入口文件名仍保留 `pipeline_v3.py`，但实际流程是 v4：

1. `researcher`：补充公开事实。
2. `tracking_processor`：只处理输入框文字和聊天/沟通截图中的跟进动态，生成 `tracking_chunk` 与 `seller_fact_snapshot`。
3. `info_chunk_writer`：结合附件解析文本、公开调研结果和 snapshot 生成 `info_chunk`。
4. `index_builder`：生成摘要与检索标签。
5. `rating_agent`：生成内部活跃度 / 可行性评级。
6. FastGPT push：只推送 `info_chunk`。

## 本地开发

### 后端

```bash
python -m venv backend/venv
backend/venv/Scripts/pip install -r backend/requirements.txt
backend/venv/Scripts/python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`。默认管理员账号由后端初始化，首次登录后应修改密码。

## 配置

本地复制示例配置：

```bash
cp settings.example.json settings.json
```

关键配置项：

- `ai_config.researcher`
- `ai_config.intake_agent`
- `ai_config.matcher_agent`
- `ai_config.tracking_processor`
- `ai_config.info_chunk_writer`
- `ai_config.index_builder`
- `ai_config.rating_agent`
- `tools.search`
- `fastgpt`

不要提交真实 `settings.json`，该文件已被 `.gitignore` 忽略。

## Railway 部署

推荐单服务部署：FastAPI 同时提供 `/api/*` 和前端静态页面。

### Railway Volume

建议挂载 Volume 到：

```text
/app/.railway-data
```

### Railway Variables

```text
PORT=8000
APP_DATA_DIR=/app/.railway-data/data
APP_OUTPUT_DIR=/app/.railway-data/outputs
APP_UPLOAD_DIR=/app/.railway-data/uploads
APP_SETTINGS_FILE=/app/.railway-data/settings.json
CORS_ORIGINS=https://你的railway域名
```

`Dockerfile` 已内置前端构建、后端依赖安装和 Uvicorn 启动命令。部署成功后健康检查：

```text
https://你的railway域名/api/health
```

## 不应提交的文件

- `settings.json`
- `data/`
- `outputs/`
- `uploads/`
- `backend/venv/`
- `frontend/node_modules/`
- `frontend/dist/`
- `*.log`
- 本地草稿 `mock*.md`

## 主要目录

```text
backend/agents/      AI agents
backend/prompts/     prompt definitions
backend/services/    v4 pipeline, attachment cache, FastGPT push
backend/routers/     FastAPI routes
backend/parsers/     PDF/DOCX/PPTX/MD parsing and OCR helpers
backend/tools/       researcher tools
backend/utils/       attachment and FastGPT adapters
frontend/src/        React frontend
.project/v4/         v4 design notes
```
