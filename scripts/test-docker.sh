#!/usr/bin/env bash
# Запуск тестов в docker-контуре (аналог CI, но против локальной БД ticketbot_test).
#
# Использует образ ticketbot-dev (основные + dev зависимости), монтирует текущий
# код и бежит в сети host (интернет + 127.0.0.1:5432 = локальный postgres).
#
# Собрать образ (один раз, или после изменения deps):
#   docker build -t ticketbot-dev -f - . <<'EOF'
#   FROM ticketbot-telegram
#   WORKDIR /app
#   ENV PYTHONPATH=/app
#   COPY pyproject.toml .
#   COPY . .
#   RUN pip install --no-cache-dir -e '.[dev]'
#   EOF
#
# Usage:
#   scripts/test-docker.sh                    # весь набор
#   scripts/test-docker.sh tests/test_identity.py -v
set -e
cd "$(dirname "$0")/.."

IMAGE="${TICKETBOT_TEST_IMAGE:-ticketbot-dev}"
DB_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ticketbot_test"

docker run --rm --network host --entrypoint sh \
  -v "$PWD:/app" -w /app \
  -e PYTHONPATH=/app \
  -e DATABASE_URL="$DB_URL" \
  -e TEST_DATABASE_URL="$DB_URL" \
  "$IMAGE" -c "pytest $* --timeout=60"
