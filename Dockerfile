FROM python:3.12-slim

WORKDIR /app

# PYTHONPATH для src-layout: app/ — корневой пакет
ENV PYTHONPATH=/app

# Устанавливаем зависимости PostgreSQL (libpq для asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем зависимости Python
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Копируем код проекта
COPY . .

# Скрипт ожидания БД (используется в entrypoint)
RUN printf '#!/bin/bash\n\
set -e\n\
\n\
host="$(echo "$DATABASE_URL" | sed -E "s|.*@([^:/]+).*|\\1|")"\n\
port="$(echo "$DATABASE_URL" | sed -E "s|.*:([0-9]+)/.*|\\1|")"\n\
\n\
: "${host:=localhost}"\n\
: "${port:=5432}"\n\
\n\
echo "Ожидание PostgreSQL на $host:$port..."\n\
\n\
for i in $(seq 1 30); do\n\
    if python3 -c "import socket; s=socket.socket(); s.settimeout(2); s.connect((\"$host\", $port)); s.close()" 2>/dev/null; then\n\
        echo "PostgreSQL готов!"\n\
        exec "$@"\n\
    fi\n\
    echo "  попытка $i/30..."\n\
    sleep 1\n\
done\n\
\n\
echo "PostgreSQL не запустился за 30 секунд."\n\
exit 1\n' > /usr/local/bin/wait-for-db \
    && chmod +x /usr/local/bin/wait-for-db

ENTRYPOINT ["wait-for-db"]
CMD ["python", "-m", "bot.telegram"]
