# GitHub 发布和部署操作指南

## 第一步：提交当前更改到 Git

### 1. 查看当前状态

```bash
cd /c/Users/MP/search-toolkit/dd-report-generator
git status
```

### 2. 添加新功能的文件

```bash
# 添加模板下载和上传增强功能
git add backend/routers/upload.py
git add frontend/src/components/FileUpload.tsx
git add frontend/src/components/HomePage.tsx

# 添加部署相关文件
git add README.md
git add DEPLOYMENT.md
git add deploy.sh
git add settings.example.json
git add .gitignore
```

### 3. 提交更改

```bash
git commit -m "feat: 添加 Excel 模板下载和部署文档

新功能：
- Excel 模板下载端点 (/api/upload/template)
- FileUpload 组件增强（图标、文件名回显、格式提示）
- HomePage 添加模板下载按钮

部署支持：
- 添加详细部署指南 (DEPLOYMENT.md)
- 添加自动部署脚本 (deploy.sh)
- 添加 README 和配置模板
- 更新 .gitignore"
```

### 4. 查看提交历史

```bash
git log --oneline -5
```

---

## 第二步：创建 GitHub 仓库

### 方式 1：通过 GitHub 网页创建

1. 访问 https://github.com/new
2. 填写仓库信息：
   - **Repository name**: `dd-report-generator`
   - **Description**: `基于 AI 的智能尽职调查报告生成系统`
   - **Visibility**:
     - 选择 **Private**（私有，只有你能看到）
     - 或 **Public**（公开，所有人可见）
   - **不要勾选** "Initialize this repository with:"（因为本地已有代码）
3. 点击 "Create repository"

### 方式 2：通过 GitHub CLI 创建（如果已安装）

```bash
# 安装 GitHub CLI (如果未安装)
# Windows: winget install GitHub.cli
# 或访问 https://cli.github.com/

# 登录
gh auth login

# 创建私有仓库
gh repo create dd-report-generator --private --source=. --remote=origin

# 或创建公开仓库
gh repo create dd-report-generator --public --source=. --remote=origin
```

---

## 第三步：推送代码到 GitHub

### 1. 添加远程仓库地址

如果通过网页创建，需要手动添加 remote：

```bash
# 替换为你的 GitHub 用户名
git remote add origin https://github.com/你的用户名/dd-report-generator.git

# 查看远程仓库
git remote -v
```

### 2. 推送代码

```bash
# 推送到 main 分支
git push -u origin main

# 如果遇到错误 "failed to push some refs"，可能需要先拉取
git pull origin main --rebase
git push -u origin main
```

### 3. 验证推送成功

访问你的 GitHub 仓库页面：
```
https://github.com/你的用户名/dd-report-generator
```

确认文件已上传。

---

## 第四步：准备阿里云服务器

### 1. 购买阿里云 ECS 服务器

访问：https://ecs.console.aliyun.com/

**推荐配置：**
- 实例规格：2核4GB（ecs.t6-c1m2.large 或更高）
- 操作系统：Ubuntu 22.04 64位
- 带宽：按使用流量计费，峰值 5Mbps
- 存储：40GB 系统盘

### 2. 配置安全组

在 ECS 控制台 → 安全组 → 配置规则，添加：

| 规则方向 | 端口范围 | 授权对象 | 说明 |
|---------|---------|---------|------|
| 入方向 | 22/22 | 0.0.0.0/0 | SSH 登录 |
| 入方向 | 80/80 | 0.0.0.0/0 | HTTP 访问 |
| 入方向 | 443/443 | 0.0.0.0/0 | HTTPS 访问 |

### 3. 获取服务器 IP

在 ECS 实例列表中找到你的服务器，记录**公网 IP**。

### 4. 配置 SSH 密钥（推荐）

**方式 1：使用密码登录**
```bash
ssh root@你的服务器IP
# 输入密码
```

**方式 2：使用密钥登录（更安全）**

在本地生成密钥：
```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
# 一路回车，使用默认路径
```

将公钥复制到服务器：
```bash
ssh-copy-id root@你的服务器IP
# 输入密码

# 之后可以免密登录
ssh root@你的服务器IP
```

---

## 第五步：在服务器上部署

### 方式 1：使用自动部署脚本（推荐）

1. **连接到服务器**

```bash
ssh root@你的服务器IP
```

2. **下载部署脚本**

```bash
# 如果是公开仓库
wget https://raw.githubusercontent.com/你的用户名/dd-report-generator/main/deploy.sh

# 如果是私有仓库，需要先克隆整个仓库
git clone https://github.com/你的用户名/dd-report-generator.git
cd dd-report-generator
```

3. **修改部署脚本配置**

```bash
nano deploy.sh
```

修改以下变量：
```bash
GITHUB_REPO="https://github.com/你的用户名/dd-report-generator.git"
DOMAIN_OR_IP="你的服务器IP"  # 例如: 123.45.67.89
```

保存并退出（Ctrl+O, Enter, Ctrl+X）。

4. **运行部署脚本**

```bash
chmod +x deploy.sh
sudo bash deploy.sh
```

脚本会自动完成：
- 安装系统依赖
- 创建应用用户
- 克隆代码
- 安装 Python 和 Node.js 依赖
- 构建前端
- 配置 Nginx 和 Supervisor

5. **配置 API keys**

```bash
sudo nano /home/ddreport/dd-report-generator/settings.json
```

填入你的 API keys（参考 settings.example.json）。

6. **重启服务**

```bash
sudo supervisorctl restart ddreport-backend
```

7. **访问应用**

浏览器打开：`http://你的服务器IP`

### 方式 2：手动部署

参考 [DEPLOYMENT.md](./DEPLOYMENT.md) 中的详细步骤。

---

## 第六步：配置域名（可选）

### 1. 购买域名

在阿里云或其他域名注册商购买域名，例如：`ddreport.example.com`

### 2. 配置 DNS 解析

在域名控制台添加 A 记录：

| 记录类型 | 主机记录 | 记录值 | TTL |
|---------|---------|--------|-----|
| A | @ 或 www | 你的服务器IP | 600 |

### 3. 更新 Nginx 配置

```bash
sudo nano /etc/nginx/sites-available/ddreport
```

修改 `server_name`：
```nginx
server_name ddreport.example.com;  # 改为你的域名
```

重启 Nginx：
```bash
sudo nginx -t
sudo systemctl restart nginx
```

### 4. 配置 HTTPS（强烈推荐）

```bash
# 安装 Certbot
sudo apt install certbot python3-certbot-nginx -y

# 获取 SSL 证书
sudo certbot --nginx -d ddreport.example.com

# 按提示操作，选择自动重定向 HTTP 到 HTTPS
```

现在可以通过 `https://ddreport.example.com` 访问应用。

---

## 第七步：验证部署

### 1. 检查服务状态

```bash
# 检查后端服务
sudo supervisorctl status ddreport-backend

# 检查 Nginx
sudo systemctl status nginx

# 查看后端日志
sudo tail -f /var/log/ddreport-backend.log
```

### 2. 测试功能

1. 访问首页，确认页面加载正常
2. 点击"下载Excel模板"，确认模板下载成功
3. 上传 Excel 文件，确认解析正常
4. 生成报告，确认 AI 调用和进度推送正常

---

## 日常维护

### 更新代码

当你在本地修改代码并推送到 GitHub 后，在服务器上更新：

```bash
ssh root@你的服务器IP

cd /home/ddreport/dd-report-generator
sudo -u ddreport git pull origin main

# 如果后端有更新
sudo -u ddreport bash -c "source venv/bin/activate && pip install -r backend/requirements.txt"
sudo supervisorctl restart ddreport-backend

# 如果前端有更新
cd frontend
sudo -u ddreport npm install
sudo -u ddreport npm run build
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

### 备份数据

```bash
# 备份上传文件和生成的报告
cd /home/ddreport/dd-report-generator
tar -czf backup-$(date +%Y%m%d).tar.gz uploads/ outputs/ settings.json

# 下载到本地
scp root@你的服务器IP:/home/ddreport/dd-report-generator/backup-*.tar.gz ./
```

---

## 故障排查

### 问题：无法访问网站

**检查步骤：**
1. 确认安全组已开放 80 端口
2. 检查 Nginx 是否运行：`sudo systemctl status nginx`
3. 检查防火墙：`sudo ufw status`（如果启用了 ufw）

### 问题：502 Bad Gateway

**原因：** 后端服务未启动

**解决：**
```bash
sudo supervisorctl status ddreport-backend
sudo supervisorctl restart ddreport-backend
sudo tail -f /var/log/ddreport-backend.log
```

### 问题：报告生成失败

**检查步骤：**
1. 确认 settings.json 中的 API keys 正确
2. 查看后端日志：`sudo tail -f /var/log/ddreport-backend.log`
3. 测试 API 连接：`curl https://dashscope.aliyuncs.com`

---

## 安全建议

1. **修改 SSH 端口**（可选）
2. **禁用 root 登录**，使用普通用户 + sudo
3. **配置防火墙**：只开放必要端口
4. **定期更新系统**：`sudo apt update && sudo apt upgrade`
5. **使用 HTTPS**：保护数据传输安全
6. **定期备份**：防止数据丢失

---

## 需要帮助？

- 查看详细部署文档：[DEPLOYMENT.md](./DEPLOYMENT.md)
- 提交 Issue：https://github.com/你的用户名/dd-report-generator/issues
- 查看日志排查问题

祝部署顺利！🚀
