# 部署指南

本文档说明如何将尽调报告生成器部署到阿里云服务器。

## 部署架构

```
本地开发环境 → GitHub 仓库 → 阿里云 ECS 服务器
```

## 前置准备

### 1. 阿里云服务器要求

- **操作系统**：Ubuntu 20.04/22.04 或 CentOS 7/8
- **配置建议**：
  - CPU: 2核及以上
  - 内存: 4GB 及以上
  - 硬盘: 40GB 及以上
- **网络**：开放端口 80 (HTTP) 和 443 (HTTPS)

### 2. 本地准备

- Git 已安装
- GitHub 账号
- SSH 密钥配置（用于连接服务器）

---

## 第一步：发布到 GitHub

### 1.1 提交当前更改

```bash
cd /c/Users/MP/search-toolkit/dd-report-generator

# 添加所有更改
git add backend/routers/upload.py
git add frontend/src/components/FileUpload.tsx
git add frontend/src/components/HomePage.tsx

# 提交
git commit -m "feat: 添加 Excel 模板下载和拖拽上传增强功能

- 新增 /api/upload/template 端点生成 Excel 模板
- FileUpload 组件增强：图标、文件名回显、格式提示
- HomePage 添加模板下载按钮"
```

### 1.2 创建 GitHub 仓库

1. 访问 https://github.com/new
2. 仓库名称：`dd-report-generator`（或自定义）
3. 选择 **Private**（如果不想公开）或 **Public**
4. 不要勾选 "Initialize with README"（因为本地已有代码）
5. 点击 "Create repository"

### 1.3 推送代码到 GitHub

```bash
# 如果是新仓库，添加远程地址
git remote add origin https://github.com/你的用户名/dd-report-generator.git

# 如果已有 origin，更新地址
# git remote set-url origin https://github.com/你的用户名/dd-report-generator.git

# 推送代码
git push -u origin main
```

---

## 第二步：服务器环境配置

### 2.1 连接到阿里云服务器

```bash
ssh root@你的服务器IP
# 或使用密钥
ssh -i ~/.ssh/your_key.pem root@你的服务器IP
```

### 2.2 安装基础依赖

#### Ubuntu/Debian:

```bash
# 更新包管理器
sudo apt update && sudo apt upgrade -y

# 安装 Python 3.10+
sudo apt install python3.10 python3.10-venv python3-pip -y

# 安装 Node.js 18+ (使用 NodeSource)
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install nodejs -y

# 安装 Git
sudo apt install git -y

# 安装 Nginx (用于反向代理)
sudo apt install nginx -y

# 安装 Supervisor (用于进程管理)
sudo apt install supervisor -y
```

#### CentOS/RHEL:

```bash
# 更新包管理器
sudo yum update -y

# 安装 Python 3.10+
sudo yum install python3.10 python3-pip -y

# 安装 Node.js 18+
curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash -
sudo yum install nodejs -y

# 安装 Git
sudo yum install git -y

# 安装 Nginx
sudo yum install nginx -y

# 安装 Supervisor
sudo yum install supervisor -y
```

### 2.3 创建应用用户（推荐）

```bash
# 创建专用用户（不使用 root 运行应用更安全）
sudo useradd -m -s /bin/bash ddreport
sudo su - ddreport
```

---

## 第三步：部署应用

### 3.1 克隆代码

```bash
cd ~
git clone https://github.com/你的用户名/dd-report-generator.git
cd dd-report-generator
```

如果是私有仓库，需要配置 GitHub 访问：

```bash
# 方法1: 使用 Personal Access Token
git clone https://你的token@github.com/你的用户名/dd-report-generator.git

# 方法2: 配置 SSH 密钥（推荐）
# 在服务器上生成 SSH 密钥
ssh-keygen -t ed25519 -C "your_email@example.com"
# 将 ~/.ssh/id_ed25519.pub 内容添加到 GitHub Settings > SSH Keys
```

### 3.2 配置后端

```bash
cd ~/dd-report-generator

# 创建 Python 虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -r backend/requirements.txt
```

### 3.3 配置 AI 和工具 API

创建 `settings.json` 文件：

```bash
nano settings.json
```

填入配置（替换为你的实际 API key）：

```json
{
  "ai_config": {
    "extractor": {
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "api_key": "你的阿里云DashScope API Key",
      "model": "qwen3-max"
    },
    "researcher": {
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "api_key": "你的阿里云DashScope API Key",
      "model": "qwen3-max"
    },
    "writer": {
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "api_key": "你的阿里云DashScope API Key",
      "model": "qwen3-max"
    }
  },
  "tools_config": {
    "search": {
      "active_provider": "bocha",
      "providers": {
        "bocha": {
          "api_key": "你的搜索API Key"
        }
      }
    }
  }
}
```

保存并退出（Ctrl+O, Enter, Ctrl+X）。

### 3.4 构建前端

```bash
cd frontend

# 安装依赖
npm install

# 构建生产版本
npm run build
```

构建完成后，静态文件会生成在 `frontend/dist/` 目录。

---

## 第四步：配置 Nginx 反向代理

### 4.1 创建 Nginx 配置

```bash
sudo nano /etc/nginx/sites-available/ddreport
```

填入以下配置：

```nginx
server {
    listen 80;
    server_name 你的域名或IP;  # 例如: ddreport.example.com 或 123.45.67.89

    # 前端静态文件
    location / {
        root /home/ddreport/dd-report-generator/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 支持（用于实时进度推送）
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }

    # 上传文件大小限制
    client_max_body_size 100M;
}
```

### 4.2 启用配置

```bash
# 创建软链接
sudo ln -s /etc/nginx/sites-available/ddreport /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重启 Nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

---

## 第五步：配置 Supervisor 进程管理

### 5.1 创建 Supervisor 配置

```bash
sudo nano /etc/supervisor/conf.d/ddreport.conf
```

填入以下内容：

```ini
[program:ddreport-backend]
command=/home/ddreport/dd-report-generator/venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
directory=/home/ddreport/dd-report-generator
user=ddreport
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/ddreport-backend.log
environment=PYTHONUNBUFFERED=1
```

### 5.2 启动服务

```bash
# 重新加载 Supervisor 配置
sudo supervisorctl reread
sudo supervisorctl update

# 启动应用
sudo supervisorctl start ddreport-backend

# 查看状态
sudo supervisorctl status

# 查看日志
sudo tail -f /var/log/ddreport-backend.log
```

---

## 第六步：配置 HTTPS（可选但推荐）

### 6.1 安装 Certbot

```bash
# Ubuntu/Debian
sudo apt install certbot python3-certbot-nginx -y

# CentOS
sudo yum install certbot python3-certbot-nginx -y
```

### 6.2 获取 SSL 证书

```bash
sudo certbot --nginx -d 你的域名
# 例如: sudo certbot --nginx -d ddreport.example.com
```

按提示操作，Certbot 会自动配置 Nginx 并获取证书。

### 6.3 自动续期

```bash
# 测试自动续期
sudo certbot renew --dry-run

# Certbot 会自动添加 cron 任务，无需手动配置
```

---

## 第七步：验证部署

### 7.1 检查服务状态

```bash
# 检查后端服务
sudo supervisorctl status ddreport-backend

# 检查 Nginx
sudo systemctl status nginx

# 检查端口监听
sudo netstat -tlnp | grep -E '80|8000'
```

### 7.2 访问应用

在浏览器中访问：
- HTTP: `http://你的服务器IP` 或 `http://你的域名`
- HTTPS: `https://你的域名`（如果配置了 SSL）

### 7.3 测试功能

1. 点击"下载Excel模板"按钮，确认模板下载成功
2. 上传 Excel 文件，确认解析正常
3. 生成报告，确认 AI 调用和进度推送正常

---

## 日常维护

### 更新代码

```bash
cd ~/dd-report-generator
git pull origin main

# 如果后端有更新
source venv/bin/activate
pip install -r backend/requirements.txt
sudo supervisorctl restart ddreport-backend

# 如果前端有更新
cd frontend
npm install
npm run build
```

### 查看日志

```bash
# 后端日志
sudo tail -f /var/log/ddreport-backend.log

# Nginx 访问日志
sudo tail -f /var/log/nginx/access.log

# Nginx 错误日志
sudo tail -f /var/log/nginx/error.log
```

### 重启服务

```bash
# 重启后端
sudo supervisorctl restart ddreport-backend

# 重启 Nginx
sudo systemctl restart nginx
```

---

## 故障排查

### 问题1: 502 Bad Gateway

**原因**：后端服务未启动或端口不通

**解决**：
```bash
sudo supervisorctl status ddreport-backend
sudo supervisorctl restart ddreport-backend
sudo tail -f /var/log/ddreport-backend.log
```

### 问题2: 前端页面空白

**原因**：前端构建失败或路径配置错误

**解决**：
```bash
cd ~/dd-report-generator/frontend
npm run build
ls -la dist/  # 确认文件存在
```

### 问题3: API 调用失败

**原因**：settings.json 配置错误或 API key 无效

**解决**：
```bash
cat ~/dd-report-generator/settings.json
# 检查 API key 是否正确
```

### 问题4: 上传文件失败

**原因**：Nginx 文件大小限制

**解决**：
```bash
sudo nano /etc/nginx/sites-available/ddreport
# 增加 client_max_body_size 100M;
sudo nginx -t
sudo systemctl restart nginx
```

---

## 安全建议

1. **防火墙配置**：只开放必要端口（80, 443, 22）
2. **定期更新**：保持系统和依赖包最新
3. **备份数据**：定期备份 `uploads/`、`outputs/`、`settings.json`
4. **监控日志**：使用日志分析工具监控异常访问
5. **限流保护**：配置 Nginx 限流防止滥用

---

## 性能优化

### 1. 启用 Gzip 压缩

在 Nginx 配置中添加：

```nginx
gzip on;
gzip_types text/plain text/css application/json application/javascript text/xml application/xml;
gzip_min_length 1000;
```

### 2. 配置缓存

```nginx
location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}
```

### 3. 增加 Worker 进程

修改 Supervisor 配置，使用多个 Uvicorn worker：

```ini
command=/home/ddreport/dd-report-generator/venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 4
```

---

## 联系支持

如遇到部署问题，请检查：
1. 服务器日志：`/var/log/ddreport-backend.log`
2. Nginx 日志：`/var/log/nginx/error.log`
3. 系统资源：`htop` 或 `top` 查看 CPU/内存使用情况
