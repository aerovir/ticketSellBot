#!/usr/bin/env python3
"""
cron-healthcheck.py — Скрипт для cron: запускает healthcheck и логирует результат.

Установка в cron (каждые 10 минут):
  crontab -e
  */10 * * * * /usr/bin/python3 /path/to/deploy/cron-healthcheck.py >> /var/log/ticketbot-health.log 2>&1
"""

import os
import sys
import json
import subprocess
from datetime import datetime

LOG_FILE = "/var/log/ticketbot-health.json"

# Берём токен и chat_id для уведомлений из .env
os.environ.setdefault("TELEGRAM_TOKEN", "")

HEALTHCHECK_PATH = os.path.join(os.path.dirname(__file__), "healthcheck.py")


def run_healthcheck() -> dict:
    """Запустить healthcheck и вернуть результат."""
    result = subprocess.run(
        [sys.executable, HEALTHCHECK_PATH],
        capture_output=True, text=True, timeout=30,
    )

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "success": result.returncode == 0,
        "exit_code": result.returncode,
        "output": result.stdout + result.stderr,
    }


def log_result(result: dict):
    """Дописать результат в JSON-лог."""
    records = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                records = json.load(f)
        except (json.JSONDecodeError, OSError):
            records = []

    records.append(result)

    # Храним только последние 1000 записей
    records = records[-1000:]

    with open(LOG_FILE, "w") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    result = run_healthcheck()
    log_result(result)

    status = "OK" if result["success"] else "FAIL"
    print(f"[{result['timestamp']}] {status}")

    if not result["success"]:
        print(result["output"])
        sys.exit(1)
