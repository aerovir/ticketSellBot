#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# setup-runner.sh — Настройка self-hosted GitHub Actions runner
#
# Что делает:
#   1. Устанавливает Docker + Docker Compose (если нет)
#   2. Создаёт пользователя runner (если нет)
#   3. Устанавливает и запускает GitHub Actions runner
#   4. Настраивает автозапуск runner при перезагрузке
#
# Использование:
#   chmod +x deploy/setup-runner.sh
#
#   # Интерактивный режим (запросит TOKEN):
#   sudo ./deploy/setup-runner.sh
#
#   # Авто-режим (с токеном):
#   sudo GITHUB_TOKEN=ABC123 ./deploy/setup-runner.sh
#
# Требуется:
#   - root-доступ (sudo)
#   - Токен раннера из GitHub → Settings → Actions → Runners → New runner
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

# ─── Цвета ────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
err()   { echo -e "${RED}[✗]${NC} $1"; }
info()  { echo -e "${BLUE}[i]${NC} $1"; }
header(){ echo -e "\n${CYAN}═════ $1 ═════${NC}\n"; }

if [ "$EUID" -ne 0 ]; then
    err "Запустите скрипт от root: sudo $0"
    exit 1
fi

# ─── Параметры ────────────────────────────────────────
GITHUB_ORG="${GITHUB_ORG:-aerovir}"
GITHUB_REPO="${GITHUB_REPO:-ticketSellBot}"
RUNNER_VERSION="${RUNNER_VERSION:-2.322.0}"
RUNNER_USER="${RUNNER_USER:-runner}"
PROJECT_DIR="${PROJECT_DIR:-/opt/ticketbot}"

# ─── 1. Зависимости ──────────────────────────────────
header "Шаг 1/5: Системные зависимости"

apt-get update -qq
apt-get install -y -qq curl wget git jq ca-certificates >/dev/null
log "Базовые пакеты установлены"

# ─── 2. Docker ────────────────────────────────────────
header "Шаг 2/5: Docker"

if ! command -v docker &>/dev/null; then
    info "Установка Docker..."
    curl -fsSL https://get.docker.com | sh
    log "Docker установлен: $(docker --version)"
else
    log "Docker уже установлен: $(docker --version | awk '{print $3}')"
fi

if ! docker compose version &>/dev/null; then
    info "Установка Docker Compose plugin..."
    apt-get install -y -qq docker-compose-plugin >/dev/null
fi
log "Docker Compose: $(docker compose version | awk '{print $4}')"

# ─── 3. Пользователь runner ───────────────────────────
header "Шаг 3/5: Пользователь runner"

if id "$RUNNER_USER" &>/dev/null; then
    log "Пользователь $RUNNER_USER уже существует"
else
    useradd -m -s /bin/bash -d "/home/$RUNNER_USER" "$RUNNER_USER"
    usermod -aG docker "$RUNNER_USER"
    log "Пользователь $RUNNER_USER создан и добавлен в группу docker"
fi

# ─── 4. GitHub Actions Runner ─────────────────────────
header "Шаг 4/5: GitHub Actions Runner"

RUNNER_DIR="/home/$RUNNER_USER/actions-runner"
mkdir -p "$RUNNER_DIR"

if [ -f "$RUNNER_DIR/.runner" ]; then
    log "Раннер уже настроен в $RUNNER_DIR"
else
    cd "$RUNNER_DIR"

    if [ ! -f "run.sh" ]; then
        info "Скачивание runner v$RUNNER_VERSION..."
        curl -sL "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
            -o runner.tar.gz
        tar xzf runner.tar.gz
        rm runner.tar.gz
        log "Runner v$RUNNER_VERSION загружен"
    fi

    # Запрашиваем токен если не передан
    if [ -z "${GITHUB_TOKEN:-}" ]; then
        echo ""
        warn "Требуется токен регистрации раннера."
        warn "Получите его в GitHub → Settings → Actions → Runners → New runner"
        warn "Или введите URL для получения токена:"
        echo "  https://github.com/$GITHUB_ORG/$GITHUB_REPO/settings/actions/runners/new"
        echo ""
        read -rp "Введите токен регистрации: " GITHUB_TOKEN
    fi

    # Регистрация раннера
    info "Регистрация раннера..."
    ./config.sh \
        --url "https://github.com/$GITHUB_ORG/$GITHUB_REPO" \
        --token "$GITHUB_TOKEN" \
        --name "ticketbot-runner" \
        --labels "self-hosted,linux,${GITHUB_REPO}" \
        --work "_work" \
        --unattended

    log "Раннер зарегистрирован"
fi

# Права
chown -R "$RUNNER_USER":"$RUNNER_USER" "$RUNNER_DIR"

# ─── 5. Сервис автозапуска ────────────────────────────
header "Шаг 5/5: Сервис автозапуска (systemd)"

SERVICE_FILE="/etc/systemd/system/actions.runner.$RUNNER_USER-ticketbot.service"

if [ ! -f "$SERVICE_FILE" ]; then
    cat > "$SERVICE_FILE" << SERVICE
[Unit]
Description=GitHub Actions Runner (ticketSellBot)
After=network.target docker.service

[Service]
User=$RUNNER_USER
WorkingDirectory=$RUNNER_DIR
ExecStart=$RUNNER_DIR/run.sh
ExecStop=$RUNNER_DIR/config.sh remove --token $(echo "$GITHUB_TOKEN")
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

    systemctl daemon-reload
    systemctl enable "actions.runner.$RUNNER_USER-ticketbot.service"
    systemctl start "actions.runner.$RUNNER_USER-ticketbot.service"
    log "Сервис actions.runner запущен и добавлен в автозагрузку"
else
    log "Сервис уже существует"
    systemctl restart "actions.runner.$RUNNER_USER-ticketbot.service"
fi

# ─── Проверка ─────────────────────────────────────────
header "Проверка"

sleep 2
if systemctl is-active "actions.runner.$RUNNER_USER-ticketbot.service" &>/dev/null; then
    log "✅ GitHub Actions Runner работает!"
else
    err "❌ Раннер не запустился. Проверьте:"
    echo "  sudo journalctl -u actions.runner.$RUNNER_USER-ticketbot.service -f"
fi

# Информация
echo ""
info "Директория проекта: $PROJECT_DIR"
info "Создайте .env в $PROJECT_DIR с токенами ботов"
info "Убедитесь что раннер виден:"
echo "  https://github.com/$GITHUB_ORG/$GITHUB_REPO/settings/actions/runners"
echo ""
info "При пуше в main → раннер сам развернёт бота"
echo ""
