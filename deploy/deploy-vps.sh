#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
# deploy-vps.sh — Быстрый деплой TicketBot на свежий VPS
#
# Использование:
#   chmod +x deploy/deploy-vps.sh
#   ./deploy/deploy-vps.sh          # интерактивный режим
#   ./deploy/deploy-vps.sh --auto   # авто-режим (с .env)
#
# Поддерживаемые хостинги: Timeweb, Beget, любой Ubuntu/Debian VPS
# ═══════════════════════════════════════════════════════════

set -euo pipefail

# ─── Цвета ────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }
info() { echo -e "${BLUE}[i]${NC} $1"; }

# ─── Проверка прав ─────────────────────────────────────
if [ "$EUID" -eq 0 ]; then
    err "Не запускайте скрипт от root. Он сам использует sudo где нужно."
    exit 1
fi

# ─── 1. Системные зависимости ──────────────────────────
info "→ Шаг 1/6: Установка системных зависимостей..."

if ! command -v docker &>/dev/null; then
    log "Устанавливаю Docker..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    log "Docker установлен. Перелогиньтесь после деплоя (newgrp docker)"
fi

if ! command -v docker compose &>/dev/null; then
    log "Устанавливаю Docker Compose..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

log "Docker готов: $(docker --version)"
log "Compose готов: $(docker compose version)"

# ─── 2. Клонирование репозитория ───────────────────────
info "→ Шаг 2/6: Клонирование репозитория..."

if [ -d "ticketBot" ]; then
    warn "Папка ticketBot уже существует. Обновляю..."
    cd ticketBot && git pull
else
    git clone https://github.com/your-org/ticketBot.git
    cd ticketBot
    log "Репозиторий склонирован"
fi

# ─── 3. Настройка окружения ────────────────────────────
info "→ Шаг 3/6: Настройка переменных окружения..."

if [ ! -f ".env" ]; then
    if [ -f "deploy/.env.prod.example" ]; then
        cp deploy/.env.prod.example .env
        warn "Файл .env создан из шаблона. Отредактируйте его: nano .env"
    else
        cat > .env << 'ENVEOF'
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/ticketbot
TELEGRAM_TOKEN=
VK_TOKEN=
VK_GROUP_ID=
MAX_TOKEN=
DEBUG=false
ENVEOF
        warn "Файл .env создан. Отредактируйте его: nano .env"
    fi

    if [ "$*" != "--auto" ]; then
        echo ""
        info "Откройте .env в редакторе и укажите TOKEN бота:"
        echo "  nano $(pwd)/.env"
        echo ""
        read -rp "Нажмите Enter после редактирования .env..."
    fi
else
    log ".env уже существует"
fi

# ─── 4. Сборка образов ────────────────────────────────
info "→ Шаг 4/6: Сборка Docker-образов..."
docker compose build
log "Образы собраны"

# ─── 5. Запуск ─────────────────────────────────────────
info "→ Шаг 5/6: Запуск сервисов..."

# Поднимаем БД
docker compose up -d db
log "PostgreSQL запущен"

# Ожидаем готовности БД
info "Ожидание PostgreSQL..."
for i in $(seq 1 30); do
    if docker compose exec -T db pg_isready -U postgres -d ticketbot &>/dev/null; then
        log "PostgreSQL готов!"
        break
    fi
    sleep 1
done

# Применяем миграции
docker compose run --rm app alembic upgrade head 2>/dev/null || {
    warn "Alembic не сработал, создаю таблицы через init_db..."
    docker compose run --rm app python -c "import asyncio; from core.database import init_db; asyncio.run(init_db())"
}

# Поднимаем бота
docker compose up -d app
log "Бот запущен!"

# ─── 6. Проверка ──────────────────────────────────────
info "→ Шаг 6/6: Проверка работоспособности..."

sleep 3
if docker compose ps --status running | grep -q "app"; then
    log "✅ Бот работает!"

    # Показываем логи
    echo ""
    docker compose logs --tail 10 app
    echo ""

    log "Команды для управления:"
    echo "  docker compose logs -f app    — смотреть логи"
    echo "  docker compose restart app    — перезапустить бота"
    echo "  docker compose down           — остановить всё"
    echo "  make -C deploy seed           — залить тестовые данные"
else
    err "❌ Бот не запустился. Проверьте логи:"
    echo "  docker compose logs app"
fi
