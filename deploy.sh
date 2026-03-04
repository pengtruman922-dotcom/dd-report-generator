#!/bin/bash
# 快速部署脚本 - 在阿里云服务器上运行

set -e  # 遇到错误立即退出

echo "=========================================="
echo "尽调报告生成器 - 自动部署脚本"
echo "=========================================="

# 配置变量（请根据实际情况修改）
APP_USER="ddreport"
APP_DIR="/home/$APP_USER/dd-report-generator"
GITHUB_REPO="https://github.com/pengtruman922-dotcom/dd-report-generator.git"
DOMAIN_OR_IP="8.134.115.126"

# 检查是否为 root 用户
if [ "$EUID" -ne 0 ]; then
    echo "请使用 root 用户运行此脚本: sudo bash deploy.sh"
    exit 1
fi

echo ""
echo "步骤 1/7: 安装系统依赖..."
if command -v apt &> /dev/null; then
    # Ubuntu/Debian
    apt update
    apt install -y python3 python3-venv python3-pip git nginx supervisor curl

    # 安装 Node.js 18 (通过 NodeSource)
    if ! command -v node &> /dev/null; then
        echo "正在安装 Node.js 18..."
        curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
        apt install -y nodejs
    else
        echo "Node.js 已安装: $(node --version)"
    fi
elif command -v yum &> /dev/null; then
    # CentOS/RHEL
    yum update -y
    yum install -y python3 python3-pip git nginx supervisor curl
    if ! command -v node &> /dev/null; then
        curl -fsSL https://rpm.nodesource.com/setup_18.x | bash -
        yum install -y nodejs
    fi
else
    echo "不支持的操作系统"
    exit 1
fi

echo ""
echo "步骤 2/7: 创建应用用户..."
if ! id "$APP_USER" &>/dev/null; then
    useradd -m -s /bin/bash $APP_USER
    echo "用户 $APP_USER 已创建"
else
    echo "用户 $APP_USER 已存在"
fi

echo ""
echo "步骤 3/7: 克隆代码..."
if [ ! -d "$APP_DIR" ]; then
    sudo -u $APP_USER git clone $GITHUB_REPO $APP_DIR
else
    echo "代码目录已存在，执行 git pull..."
    cd $APP_DIR
    sudo -u $APP_USER git pull
fi

echo ""
echo "步骤 4/7: 配置后端..."
cd $APP_DIR
sudo -u $APP_USER python3 -m venv venv
sudo -u $APP_USER bash -c "source venv/bin/activate && pip install --upgrade pip && pip install -r backend/requirements.txt"

echo ""
echo "步骤 5/7: 构建前端..."
cd $APP_DIR/frontend
sudo -u $APP_USER npm install
sudo -u $APP_USER npm run build

echo ""
echo "步骤 6/7: 配置 Nginx..."
cat > /etc/nginx/sites-available/ddreport <<EOF
server {
    listen 80;
    server_name $DOMAIN_OR_IP;

    location / {
        root $APP_DIR/frontend/dist;
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }

    client_max_body_size 100M;
}
EOF

ln -sf /etc/nginx/sites-available/ddreport /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx
systemctl enable nginx

echo ""
echo "步骤 7/7: 配置 Supervisor..."
cat > /etc/supervisor/conf.d/ddreport.conf <<EOF
[program:ddreport-backend]
command=$APP_DIR/venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
directory=$APP_DIR
user=$APP_USER
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/ddreport-backend.log
environment=PYTHONUNBUFFERED=1
EOF

supervisorctl reread
supervisorctl update
supervisorctl restart ddreport-backend

echo ""
echo "=========================================="
echo "部署完成！"
echo "=========================================="
echo ""
echo "访问地址: http://$DOMAIN_OR_IP"
echo ""
echo "重要提示："
echo "1. 请编辑 $APP_DIR/settings.json 配置 API keys"
echo "2. 配置完成后重启服务: supervisorctl restart ddreport-backend"
echo "3. 查看日志: tail -f /var/log/ddreport-backend.log"
echo ""
echo "如需配置 HTTPS，请运行："
echo "  certbot --nginx -d $DOMAIN_OR_IP"
echo ""
