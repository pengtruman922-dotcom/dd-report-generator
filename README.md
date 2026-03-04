# 尽调报告生成器 (DD Report Generator)

基于 AI 的智能尽职调查报告生成系统，支持 Excel 批量导入、附件解析、多步骤 AI 分析和 Markdown 报告输出。

## 功能特性

### 核心功能
- ✅ **Excel 批量导入**：支持 26 列标的信息表，自动解析公司数据
- ✅ **Excel 模板下载**：一键下载标准格式模板，降低新用户上手门槛
- ✅ **手动输入模式**：无需 Excel，直接在线填写标的信息
- ✅ **附件解析**：支持 PDF、Word、PPT、Markdown 文档自动提取
- ✅ **OCR 识别**：图片型 PDF 自动 OCR 文字识别
- ✅ **多步骤 AI 分析**：
  - 信息提取（Extractor）
  - 网络研究（Researcher）
  - 报告撰写（Writer）
- ✅ **实时进度推送**：SSE 实时显示生成进度和日志
- ✅ **批量生成**：支持一次性生成多份报告
- ✅ **报告管理**：查看历史报告、编辑、删除、导出 Word

### 增强体验
- 🎨 拖拽上传：支持文件拖拽，带视觉反馈和动画效果
- 📄 文件预览：上传后显示文件名、大小，可清除重选
- 💡 格式提示：明确显示支持的文件格式
- 🔄 报告重生成：可基于历史报告重新生成

## 技术栈

### 后端
- **框架**：FastAPI + Uvicorn
- **AI 模型**：阿里云 DashScope (Qwen3-Max)
- **文档解析**：
  - Excel: `openpyxl`, `pandas`
  - PDF: `PyMuPDF`, `pdfplumber`
  - OCR: `rapidocr-onnxruntime`
  - Word: `python-docx`
  - PPT: `python-pptx`
- **搜索工具**：Bocha、Baidu、Bing、DuckDuckGo（支持 fallback）
- **网页抓取**：Jina Reader、本地 Scraper
- **数据库**：SQLite（会话和报告持久化）

### 前端
- **框架**：React 18 + TypeScript
- **路由**：React Router v6
- **样式**：Tailwind CSS
- **构建**：Vite
- **实时通信**：Server-Sent Events (SSE)

## 快速开始

### 本地开发

#### 1. 克隆仓库

```bash
git clone https://github.com/你的用户名/dd-report-generator.git
cd dd-report-generator
```

#### 2. 配置后端

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r backend/requirements.txt

# 配置 API keys
cp settings.example.json settings.json
# 编辑 settings.json，填入你的 API keys
```

#### 3. 配置前端

```bash
cd frontend
npm install
```

#### 4. 启动服务

```bash
# 终端 1: 启动后端
cd dd-report-generator
source venv/bin/activate
python -m uvicorn backend.main:app --reload --port 8000

# 终端 2: 启动前端
cd dd-report-generator/frontend
npm run dev
```

访问 http://localhost:5173

### 生产部署

详细部署指南请参考 [DEPLOYMENT.md](./DEPLOYMENT.md)

#### 快速部署到阿里云（推荐）

1. **推送代码到 GitHub**

```bash
git add .
git commit -m "准备部署"
git push origin main
```

2. **在服务器上运行自动部署脚本**

```bash
# 下载部署脚本
wget https://raw.githubusercontent.com/你的用户名/dd-report-generator/main/deploy.sh

# 修改脚本中的配置变量
nano deploy.sh
# 修改: GITHUB_REPO, DOMAIN_OR_IP

# 运行部署
sudo bash deploy.sh
```

3. **配置 API keys**

```bash
sudo nano /home/ddreport/dd-report-generator/settings.json
# 填入你的 API keys

# 重启服务
sudo supervisorctl restart ddreport-backend
```

4. **访问应用**

浏览器打开 `http://你的服务器IP`

## 配置说明

### settings.json 示例

```json
{
  "ai_config": {
    "extractor": {
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "api_key": "sk-xxx",
      "model": "qwen3-max"
    },
    "researcher": {
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "api_key": "sk-xxx",
      "model": "qwen3-max"
    },
    "writer": {
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "api_key": "sk-xxx",
      "model": "qwen3-max"
    }
  },
  "tools_config": {
    "search": {
      "active_provider": "bocha",
      "fallback_chain": ["bocha", "baidu", "bing_china"],
      "providers": {
        "bocha": {
          "api_key": "your-bocha-key"
        },
        "baidu": {
          "api_key": "your-baidu-key",
          "secret_key": "your-baidu-secret"
        }
      }
    },
    "scraper": {
      "active_provider": "jina_reader"
    }
  }
}
```

## 使用指南

### 1. Excel 模式（批量）

1. 点击"下载Excel模板"获取标准格式模板
2. 填写标的信息（至少填写：标的编码、标的主体、标的项目）
3. 上传填好的 Excel 文件
4. 选择目标项目（单个或批量）
5. 上传附件（可选）
6. 点击"生成报告"

### 2. 手动输入模式（单个）

1. 切换到"手动输入"标签
2. 填写必填字段（标的主体、标的项目）
3. 填写其他可选字段
4. 点击"确认提交"
5. 上传附件（可选）
6. 点击"生成报告"

### 3. 查看和管理报告

- 点击顶部"报告列表"查看所有历史报告
- 支持搜索、筛选、排序
- 可编辑报告内容
- 可导出为 Word 文档
- 可重新生成报告

## API 文档

启动后端后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 项目结构

```
dd-report-generator/
├── backend/
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # 全局配置
│   ├── db.py                # SQLite 数据库
│   ├── routers/
│   │   ├── upload.py        # 上传和模板下载
│   │   ├── generate.py      # 报告生成
│   │   └── reports.py       # 报告管理
│   ├── parsers/             # 文档解析器
│   ├── agents/              # AI Agent
│   └── tools/               # 搜索和抓取工具
├── frontend/
│   ├── src/
│   │   ├── components/      # React 组件
│   │   ├── api/             # API 客户端
│   │   └── hooks/           # 自定义 Hooks
│   └── dist/                # 构建输出
├── uploads/                 # 上传文件存储
├── outputs/                 # 生成报告存储
├── settings.json            # 配置文件（需手动创建）
├── DEPLOYMENT.md            # 详细部署指南
└── deploy.sh                # 自动部署脚本
```

## 常见问题

### Q: 如何获取 API keys？

- **阿里云 DashScope**: https://dashscope.console.aliyun.com/
- **Bocha 搜索**: 联系 Bocha 服务商
- **百度搜索**: https://ai.baidu.com/

### Q: 报告生成失败怎么办？

1. 检查 API key 是否正确配置
2. 查看后端日志：`tail -f /var/log/ddreport-backend.log`
3. 确认网络连接正常
4. 检查 API 余额是否充足

### Q: 如何更新部署的代码？

```bash
cd /home/ddreport/dd-report-generator
git pull origin main
source venv/bin/activate
pip install -r backend/requirements.txt
cd frontend && npm install && npm run build
sudo supervisorctl restart ddreport-backend
```

### Q: 支持哪些文件格式？

- **Excel**: .xlsx, .xls
- **附件**: .pdf, .docx, .pptx, .md, .txt

## 性能优化

- 使用 Nginx 反向代理和静态文件缓存
- 多 worker 进程提升并发能力
- 搜索工具 fallback 机制提高成功率
- OCR 自适应 DPI 平衡速度和质量

## 安全建议

- 不要将 `settings.json` 提交到 Git
- 使用 HTTPS 加密传输
- 定期更新依赖包
- 配置防火墙限制访问
- 定期备份数据

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

如有问题，请提交 GitHub Issue。
