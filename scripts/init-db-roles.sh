#!/bin/bash
# init-db-roles.sh — Создание PostgreSQL-ролей для каждой платформы.
#
# Каждый бот подключается к общей БД под своей ролью:
#   tg_user  — Telegram
#   vk_user  — VK
#   max_user — MAX
#
# Роль admin (postgres) используется только для миграций и seed.
#
# Использование:
#   export DB_PASSWORD_TG="..." DB_PASSWORD_VK="..." DB_PASSWORD_MAX="..."
#   bash scripts/init-db-roles.sh
#
# Или через docker:
#   docker compose exec -T db bash < scripts/init-db-roles.sh

set -euo pipefail

DB_NAME="${POSTGRES_DB:-ticketbot}"
DB_USER="${POSTGRES_USER:-postgres}"

echo "=== Инициализация ролей платформ ==="
echo "БД: $DB_NAME"

# Определяем пароли (из переменных окружения или значения по умолчанию)
TG_PASS="${DB_PASSWORD_TG:-}"
VK_PASS="${DB_PASSWORD_VK:-}"
MAX_PASS="${DB_PASSWORD_MAX:-}"

if [ -z "$TG_PASS" ] || [ -z "$VK_PASS" ] || [ -z "$MAX_PASS" ]; then
    echo "❌ Ошибка: Укажите пароли через переменные:"
    echo "   DB_PASSWORD_TG DB_PASSWORD_VK DB_PASSWORD_MAX"
    exit 1
fi

psql -v ON_ERROR_STOP=1 --username "$DB_USER" --dbname "$DB_NAME" <<-EOSQL
    -- Telegram
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'tg_user') THEN
            CREATE ROLE tg_user WITH LOGIN PASSWORD '${TG_PASS}';
        END IF;
    END
    \$\$;
    GRANT CONNECT ON DATABASE ${DB_NAME} TO tg_user;
    GRANT USAGE ON SCHEMA public TO tg_user;
    GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO tg_user;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO tg_user;

    -- VK
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'vk_user') THEN
            CREATE ROLE vk_user WITH LOGIN PASSWORD '${VK_PASS}';
        END IF;
    END
    \$\$;
    GRANT CONNECT ON DATABASE ${DB_NAME} TO vk_user;
    GRANT USAGE ON SCHEMA public TO vk_user;
    GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO vk_user;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO vk_user;

    -- MAX
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'max_user') THEN
            CREATE ROLE max_user WITH LOGIN PASSWORD '${MAX_PASS}';
        END IF;
    END
    \$\$;
    GRANT CONNECT ON DATABASE ${DB_NAME} TO max_user;
    GRANT USAGE ON SCHEMA public TO max_user;
    GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO max_user;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO max_user;

    -- Проверка
    SELECT rolname FROM pg_catalog.pg_roles WHERE rolname IN ('tg_user', 'vk_user', 'max_user');
EOSQL

echo "✅ Роли созданы: tg_user, vk_user, max_user"
echo "⚠️  Запишите пароли в .env.telegram, .env.vk, .env.max"
