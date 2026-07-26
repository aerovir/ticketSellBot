#!/usr/bin/env python3
"""
cron-diagnose.py — Скрипт для cron: запускает самодиагностику раз в 5 минут.

При превышении порогов self-diagnose.py сам отправляет алерт в Telegram.
Этот скрипт-обёртка логирует результат и перехватывает ошибки.

Установка в cron:
  crontab -e
  */5 * * * * /usr/bin/python3 /path/to/scripts/cron-diagnose.py >> /var/log/ticketbot-diagnose.log 2>&1

Или через Makefile:
  make -C deploy install-cron-diagnose
"""

import os
import sys
import subprocess
from datetime import datetime

# Путь к проекту — двумя уровнями выше scripts/
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DIAGNOSE_PATH = os.path.join(os.path.dirname(__file__), "self-diagnose.py")

# Берём .env из проекта
DOTENV_PATH = os.path.join(PROJECT_DIR, ".env")


def load_dotenv(path: str):
    """Загрузить .env файл в os.environ (минимальная реализация)."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("\"'")
            if key and not os.environ.get(key):
                os.environ[key] = val


def main():
    load_dotenv(DOTENV_PATH)

    result = subprocess.run(
        [sys.executable, DIAGNOSE_PATH],
        capture_output=True, text=True, timeout=60,
        cwd=PROJECT_DIR,
    )

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    success = result.returncode == 0

    # В stdout пишем краткий статус (попадает в cron-лог)
    status = "OK" if success else "CRIT" if result.returncode == 2 else "WARN"
    print(f"[{timestamp}] {status} (exit={result.returncode})")

    if not success:
        # Печатаем последние строки вывода для cron-лога
        for line in result.stdout.split("\n")[-5:]:
            if line.strip():
                print(f"  {line.strip()}")
        if result.stderr:
            for line in result.stderr.split("\n")[-5:]:
                if line.strip():
                    print(f"  ERR: {line.strip()}")

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
