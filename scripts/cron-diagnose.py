#!/usr/bin/env python3
"""
cron-diagnose.py — Скрипт для cron: запускает самодиагностику раз в 5 минут.

Запускает self-diagnose.py внутри Docker-контейнера telegram (чтобы были
доступны sqlalchemy, asyncpg) и передаёт логи через stdin (чтобы был
доступен Docker CLI для анализа логов).

При превышении порогов self-diagnose.py сам отправляет алерт в Telegram.

Установка в cron выполняется автоматически через GitHub Actions:
  .github/workflows/deploy.yml → шаг «⏰ Установить cron-задание самодиагностики»
"""

import os
import subprocess
import sys
from datetime import datetime, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COMPOSE_FILES = "-f docker-compose.yml -f deploy/docker-compose.beget.yml -f deploy/docker-compose.monitoring.yml"


def main():
    # Собираем последние 500 строк логов telegram (на хосте, где есть Docker)
    logs_cmd = ["docker", "compose"] + COMPOSE_FILES.split() + ["logs", "--tail", "500", "telegram"]

    # Запускаем пайп: docker compose logs | docker compose exec -T telegram python self-diagnose.py --logs-from-stdin
    ps1 = subprocess.Popen(
        logs_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=PROJECT_DIR,
    )

    diagnose_cmd = (
        ["docker", "compose"] + COMPOSE_FILES.split() +
        ["exec", "-T", "telegram", "python", "scripts/self-diagnose.py", "--logs-from-stdin"]
    )

    result = subprocess.run(
        diagnose_cmd,
        stdin=ps1.stdout,
        capture_output=True, text=True, timeout=60,
        cwd=PROJECT_DIR,
    )
    ps1.stdout.close()
    ps1.wait()

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    success = result.returncode == 0

    # В stdout пишем краткий статус (попадает в cron-лог)
    status = "OK" if success else "CRIT" if result.returncode == 2 else "WARN"
    print(f"[{timestamp}] {status} (exit={result.returncode})")

    if result.stdout.strip():
        for line in result.stdout.split("\n")[-8:]:
            if line.strip():
                print(f"  {line.strip()}")

    if not success and result.stderr.strip():
        for line in result.stderr.split("\n")[-5:]:
            if line.strip():
                print(f"  ERR: {line.strip()}")

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
