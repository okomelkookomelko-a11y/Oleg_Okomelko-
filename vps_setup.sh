#!/bin/bash
# =============================================
# VPS Setup Script — Telegram Bot + Git Relay
# Запусти цей скрипт на VPS від root
# =============================================

set -e

# === ЗМІННІ (передаються через env або заповни тут) ===
TG_TOKEN="${TG_TOKEN:?Set TG_TOKEN env variable}"
ANTHROPIC_KEY="${ANTHROPIC_KEY:?Set ANTHROPIC_KEY env variable}"
GH_TOKEN="${GH_TOKEN:?Set GH_TOKEN env variable}"
GH_USER="${GH_USER:-okomelkookomelko-a11y}"
REPO_NAME="${REPO_NAME:-my-bot}"
BOT_DIR="/home/bot/${REPO_NAME}"

echo "============================================"
echo " 1/7 — Оновлення системи"
echo "============================================"
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

echo "============================================"
echo " 2/7 — Встановлення пакетів"
echo "============================================"
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-pip python3-venv git curl

python3 --version
git --version

echo "============================================"
echo " 3/7 — Створення користувача bot"
echo "============================================"
id bot 2>/dev/null && echo "Користувач bot вже існує" || adduser --disabled-password --gecos '' bot

echo "============================================"
echo " 4/7 — Клонування репозиторію"
echo "============================================"
mkdir -p /home/bot
if [ -d "$BOT_DIR/.git" ]; then
    echo "Репо вже існує, оновлюємо..."
    cd "$BOT_DIR"
    git pull origin main
else
    git clone "https://${GH_TOKEN}@github.com/${GH_USER}/${REPO_NAME}.git" "$BOT_DIR"
fi
chown -R bot:bot /home/bot

echo "============================================"
echo " 5/7 — Налаштування Python venv та .env"
echo "============================================"
cd "$BOT_DIR"
sudo -u bot python3 -m venv venv
sudo -u bot venv/bin/pip install --upgrade pip
sudo -u bot venv/bin/pip install -r requirements.txt

# Створення .env файлу
cat > "$BOT_DIR/.env" << ENVEOF
TG_TOKEN=${TG_TOKEN}
ANTHROPIC_KEY=${ANTHROPIC_KEY}
GH_TOKEN=${GH_TOKEN}
GH_REPO=${GH_USER}/${REPO_NAME}
ENVEOF
chown bot:bot "$BOT_DIR/.env"
chmod 600 "$BOT_DIR/.env"
echo ".env файл створено"

echo "============================================"
echo " 6/7 — Systemd сервіс для бота"
echo "============================================"
cat > /etc/systemd/system/my-bot.service << SVCEOF
[Unit]
Description=Telegram Bot (Claude AI)
After=network.target

[Service]
Type=simple
User=bot
WorkingDirectory=${BOT_DIR}
EnvironmentFile=${BOT_DIR}/.env
ExecStart=${BOT_DIR}/venv/bin/python3 bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF

cat > /etc/systemd/system/bot-deploy.service << SVCEOF
[Unit]
Description=Bot Auto-Deploy (git pull)
After=network.target

[Service]
Type=oneshot
User=bot
WorkingDirectory=${BOT_DIR}
ExecStart=/bin/bash -c 'git pull origin main && ${BOT_DIR}/venv/bin/pip install -r requirements.txt -q && systemctl restart my-bot'
EnvironmentFile=${BOT_DIR}/.env
SVCEOF

cat > /etc/systemd/system/bot-deploy.timer << SVCEOF
[Unit]
Description=Bot Auto-Deploy Timer

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
Unit=bot-deploy.service

[Install]
WantedBy=timers.target
SVCEOF

cat > /etc/systemd/system/git-relay.service << SVCEOF
[Unit]
Description=Git Relay Command Runner
After=network.target

[Service]
Type=oneshot
User=bot
WorkingDirectory=${BOT_DIR}
ExecStart=${BOT_DIR}/venv/bin/python3 cmd_runner.py
EnvironmentFile=${BOT_DIR}/.env
SVCEOF

cat > /etc/systemd/system/git-relay.timer << SVCEOF
[Unit]
Description=Git Relay Timer (every 30s)

[Timer]
OnBootSec=30s
OnUnitActiveSec=30s
Unit=git-relay.service

[Install]
WantedBy=timers.target
SVCEOF

sudo -u bot git -C "$BOT_DIR" config pull.rebase false
sudo -u bot git -C "$BOT_DIR" config credential.helper store
echo "https://${GH_TOKEN}@github.com" | sudo -u bot tee /home/bot/.git-credentials > /dev/null
chmod 600 /home/bot/.git-credentials
chown bot:bot /home/bot/.git-credentials

systemctl daemon-reload
systemctl enable my-bot
systemctl enable bot-deploy.timer
systemctl enable git-relay.timer
systemctl start my-bot
systemctl start bot-deploy.timer
systemctl start git-relay.timer

echo "============================================"
echo " 7/7 — Перевірка статусу"
echo "============================================"
sleep 3
systemctl status my-bot --no-pager -l
echo ""
echo "============================================"
echo " ✅ ВСЕ ГОТОВО!"
echo "============================================"
echo "Репо: https://github.com/${GH_USER}/${REPO_NAME}"
echo ""
echo "Корисні команди:"
echo "  journalctl -u my-bot -f          # логи бота"
echo "  systemctl status my-bot          # статус бота"
echo "  systemctl status git-relay.timer # статус git relay"
echo "============================================"
