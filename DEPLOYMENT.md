# Railway Deployment

当前推荐把项目部署成 Railway 单服务：一个 FastAPI 服务同时托管后端 API 和 React 静态页面。

## 1. 推送到 GitHub

目标仓库：

```text
https://github.com/pengtruman922-dotcom/dd-report-generator
```

提交前确认不要包含：

- `settings.json`
- `data/`
- `outputs/`
- `uploads/`
- `backend/venv/`
- `frontend/node_modules/`
- `frontend/dist/`
- `*.log`

## 2. Railway 新建项目

1. 打开 Railway。
2. `New Project`。
3. 选择 `Deploy from GitHub repo`。
4. 选择 `pengtruman922-dotcom/dd-report-generator`。
5. Railway 会检测根目录 `Dockerfile` 并按 Docker 构建。

## 3. 配置 Volume

在 Railway Service 的 `Volumes` 中新建 Volume：

```text
Mount Path: /app/.railway-data
```

该目录用于持久化：

- SQLite 数据库
- 上传附件
- 输出文件
- 线上 `settings.json`

## 4. 配置 Variables

```text
PORT=8000
APP_DATA_DIR=/app/.railway-data/data
APP_OUTPUT_DIR=/app/.railway-data/outputs
APP_UPLOAD_DIR=/app/.railway-data/uploads
APP_SETTINGS_FILE=/app/.railway-data/settings.json
CORS_ORIGINS=https://你的railway域名
```

首次生成 Railway 域名后，把 `CORS_ORIGINS` 改成真实域名。

## 5. 验证

健康检查：

```text
https://你的railway域名/api/health
```

前端页面：

```text
https://你的railway域名/
```

首次登录后，在系统设置页配置：

- 模型 API Key
- 搜索工具 Key
- FastGPT API URL / API Key / Dataset ID

## 6. 当前部署说明

- `Dockerfile` 会先构建 `frontend/dist`，再启动 FastAPI。
- `backend/main.py` 会托管前端静态资源。
- FastGPT 推送边界为 v4 `info_chunk`，不会推送 `tracking_chunk`。
- SQLite + Railway Volume 适合当前测试阶段；后续多人并发或生产化建议迁移 PostgreSQL。
