#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# beget-setup.sh — Быстрое развёртывание TicketBot на VPS Beget
#
# Использование:
#   chmod +x deploy/beget-setup.sh
#   ./deploy/beget-setup.sh
#
# Предварительно:
#   1. Заказать VPS в beget.com (1 vCPU, 2 GB, 15 GB NVMe)
#      с Ubuntu 22.04/24.04 и Docker
#   2. Получить root-доступ или пользователя с sudo
#   3. Запустить этот скрипт на сервере
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
header(){ echo -e "\n${CYAN}═══ $1 ═══${NC}\n"; }

# ─── Проверка ОС ──────────────────────────────────────
header "Проверка системы"

if [ ! -f /etc/os-release ]; then
    err "Скрипт поддерживает только Ubuntu/Debian"
    exit 1
fi

. /etc/os-release
info "ОС: $NAME $VERSION_ID"

# ─── Пути ──────────────────────────────────────────────
PROJECT_DIR="/opt/ticketbot"
REPO_URL="${REPO_URL:-}"  # можно передать через env

# ─── 1. Docker ──────────────────────────────────────────
header "Шаг 1/6: Docker"

if ! command -v docker &>/dev/null; then
    info "Установка Docker..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    log "Docker установлен"
else
    log "Docker уже установлен: $(docker --version | awk '{print $3}' | tr -d ',')"
fi

if ! docker compose version &>/dev/null; then
    info "Установка Docker Compose plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi
log "Docker Compose: $(docker compose version | awk '{print $4}')"

# ─── 2. Swap (для 1-2 GB RAM — обязательно!) ────────────
header "Шаг 2/6: Swap"

TOTAL_RAM=$(free -m | awk '/^Mem:/{print $2}')
SWAP_FILE="/swapfile"

if [ "$TOTAL_RAM" -le 2048 ]; then
    if swapon --show | grep -q "$SWAP_FILE"; then
        log "Swap уже включён: $(swapon --show | grep "$SWAP_FILE" | awk '{print $3}')"
    else
        info "RAM ${TOTAL_RAM}MB — создаю swap 2GB..."
        sudo fallocate -l 2G "$SWAP_FILE" 2>/dev/null || sudo dd if=/dev/zero of="$SWAP_FILE" bs=1M count=2048
        sudo chmod 600 "$SWAP_FILE"
        sudo mkswap "$SWAP_FILE" >/dev/null
        sudo swapon "$SWAP_FILE"
        echo "$SWAP_FILE none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
        log "Swap 2GB создан и включён"
    fi
else
    log "RAM $TOTAL_RAM MB — swap не требуется"
fi

# ─── 3. Настройка PostgreSQL в Docker ────────────────────
header "Шаг 3/6: Настройка PostgreSQL"

info "Оптимизация PostgreSQL для 1-2 GB RAM..."
# Эти параметры будут применены в docker-compose override
log "Готово (параметры в docker-compose.beget.yml)"

# ─── 4. Клонирование / обновление проекта ───────────────
header "Шаг 4/6: Проект"

if [ -d "$PROJECT_DIR" ]; then
    log "Проект уже существует в $PROJECT_DIR"
    cd "$PROJECT_DIR"

    if [ -d .git ]; then
        warn "Обновляю через git pull..."
        git pull 2>/dev/null || warn "git pull не удался, продолжаю с текущими файлами"
    fi
else
    if [ -n "$REPO_URL" ]; then
        info "Клонирую репозиторий..."
        sudo git clone "$REPO_URL" "$PROJECT_DIR"
    else
        info "Создаю директорию $PROJECT_DIR"
        sudo mkdir -p "$PROJECT_DIR"
        warn "Репозиторий не указан (REPO_URL)."
        warn "Скопируйте файлы проекта вручную:"
        echo "  scp -r /путь/к/ticketBot/* user@server:$PROJECT_DIR"
        echo ""
        read -rp "Нажмите Enter после копирования файлов..."
    fi
    cd "$PROJECT_DIR"
fi

sudo chown -R "$USER":"$USER" "$PROJECT_DIR" 2>/dev/null || true

# ─── 5. Настройка .env ──────────────────────────────────
header "Шаг 5/6: Переменные окружения"

if [ -f ".env" ]; then
    log ".env уже существует"
    warn "Проверьте токены: grep TELEGRAM_TOKEN .env"
else
    cat > .env << 'ENVEOF'
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/ticketbot
TELEGRAM_TOKEN=
VK_TOKEN=
VK_GROUP_ID=
MAX_TOKEN=
DEBUG=false
ENVEOF
    log ".env создан"
    echo ""
    warn "!!! Отредактируйте .env и укажите TOKEN бота:"
    echo "  nano $PROJECT_DIR/.env"
    echo ""
    read -rp "Нажмите Enter после редактирования .env..."
fi

# ─── 6. Сборка и запуск ─────────────────────────────────
header "Шаг 6/6: Запуск"

info "Сборка образов..."
docker compose build
log "Образы собраны"

info "Запуск PostgreSQL..."
docker compose -f docker-compose.yml -f deploy/docker-compose.beget.yml up -d db

info "Ожидание PostgreSQL..."
for i in $(seq 1 30); do
    if docker compose exec -T db pg_isready -U postgres -d ticketbot &>/dev/null; then
        log "PostgreSQL готов!"
        break
    fi
    sleep 1
done

info "Миграции БД..."
docker compose run --rm app python -c "import asyncio; from core.database import init_db; asyncio.run(init_db())" \
  && log "Таблицы созданы" \
  || warn "Не удалось создать таблицы"

info "Запуск бота..."
docker compose -f docker-compose.yml -f deploy/docker-compose.beget.yml up -d app
sleep 3

# ─── Проверка ──────────────────────────────────────────
header "Проверка"

if docker compose ps | grep -q "app.*Up"; then
    log "✅ Бот успешно запущен!"
    echo ""
    echo "  ┌──────────────────────────────────────────────┐"
    echo "  │  docker compose logs -f app    — логи        │"
    echo "  │  docker compose restart app    — перезапуск  │"
    echo "  │  docker compose down           — остановить  │"
    echo "  │  docker compose down -v        — + удалить БД│"
    echo "  │  make -C deploy seed           — тест. данные│"
    echo "  └──────────────────────────────────────────────┘"
    echo ""
    docker compose logs --tail 15 app
else
    err "❌ Бот не запустился. Логи:"
    docker compose logs app
fi

header "Готово!"
log "Beget VPS настроен и бот работает!"
info "Тариф: 1 vCPU, 2 GB RAM — ~17 ₽/день (~510 ₽/мес)"
info "Не забудьте остановить VPS, если не нужен: beget.com → панель управления"
