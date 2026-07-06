#!/usr/bin/env python3
"""
healthcheck.py — Проверка работоспособности TicketBot.

Использование:
  python deploy/healthcheck.py                  # базовая проверка
  python deploy/healthcheck.py --verbose        # подробно
  python deploy/healthcheck.py --notify-tg      # уведомление в Telegram при проблемах

Коды возврата:
  0 — всё хорошо
  1 — ошибка (бот не отвечает, БД недоступна)
"""

import os
import sys
import asyncio
import argparse
import subprocess
from datetime import datetime, timezone

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def ok(msg: str):
    print(f"  ✅ {msg}")


def fail(msg: str):
    print(f"  ❌ {msg}")


# ─── 1. Docker-контейнеры ──────────────────────────────────────

def check_containers() -> bool:
    """Проверить, что все контейнеры работают."""
    print("🔍 Проверка контейнеров...")

    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "{{.Name}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            fail("Не удалось выполнить docker compose ps")
            return False

        lines = [l.strip() for l in result.stdout.split("\n") if l.strip()]
        if not lines:
            fail("Нет запущенных контейнеров ticketbot")
            return False

        all_ok = True
        for line in lines:
            if "Up" in line:
                ok(line)
            else:
                fail(line)
                all_ok = False

        return all_ok
    except FileNotFoundError:
        fail("Docker не найден. Проверьте установку.")
        return False
    except subprocess.TimeoutExpired:
        fail("Таймаут при проверке контейнеров")
        return False


# ─── 2. Подключение к БД ────────────────────────────────────────

async def check_database() -> bool:
    """Проверить подключение к PostgreSQL."""
    print("🔍 Проверка базы данных...")

    try:
        from sqlalchemy import select, func, text
        from core.database import async_session_factory
        from core.models import Event

        async with async_session_factory() as session:
            result = await session.execute(select(func.count(Event.id)))
            count = result.scalar() or 0
            ok(f"PostgreSQL доступен, мероприятий в БД: {count}")

            # Проверка времени
            result = await session.execute(text("SELECT NOW()"))
            now = result.scalar()
            ok(f"Серверное время: {now}")

        return True
    except Exception as e:
        fail(f"Ошибка подключения к БД: {e}")
        return False


# ─── 3. Логи на ошибки ──────────────────────────────────────────

def check_logs_for_errors() -> bool:
    """Проверить последние логи на наличие ошибок."""
    print("🔍 Проверка логов...")

    try:
        result = subprocess.run(
            ["docker", "compose", "logs", "--tail", "50", "app"],
            capture_output=True, text=True, timeout=10,
        )
        logs = result.stdout + result.stderr

        # Ищем критические ошибки (не INFO/WARNING)
        error_lines = []
        for line in logs.split("\n"):
            if "ERROR" in line or "Traceback" in line or "Error" in line:
                if "Operation not permitted" not in line:  # игнорируем безобидные
                    error_lines.append(line.strip())

        if error_lines:
            for err_line in error_lines[:5]:
                fail(err_line)
            if len(error_lines) > 5:
                fail(f"...и ещё {len(error_lines) - 5} ошибок")
            return False
        else:
            ok("Критических ошибок в логах нет")
            return True

    except Exception as e:
        warn(f"Не удалось проверить логи: {e}")
        return True  # не фатально


# ─── 4. Отправка уведомления ────────────────────────────────────

async def notify_tg(token: str, chat_id: str, message: str):
    """Отправить уведомление в Telegram."""
    try:
        from aiogram import Bot
        bot = Bot(token=token)
        await bot.send_message(chat_id=chat_id, text=message)
        await bot.session.close()
        ok("Уведомление отправлено в Telegram")
    except Exception as e:
        fail(f"Не удалось отправить уведомление: {e}")


# ─── Main ───────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Healthcheck для TicketBot")
    parser.add_argument("--verbose", "-v", action="store_true", help="Подробный вывод")
    parser.add_argument("--notify-tg", metavar="CHAT_ID", help="Отправить уведомление в Telegram при проблемах")
    args = parser.parse_args()

    print(f"\n{'═' * 40}")
    print(f"  Healthcheck TicketBot")
    print(f"  {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M:%S UTC')}")
    print(f"{'═' * 40}\n")

    checks = []

    # Проверка контейнеров
    containers_ok = check_containers()
    checks.append(containers_ok)
    print()

    # Проверка БД
    db_ok = await check_database()
    checks.append(db_ok)
    print()

    # Проверка логов (только если verbose или проблемы)
    logs_ok = check_logs_for_errors()
    checks.append(logs_ok)
    print()

    # Итог
    print(f"{'─' * 40}")
    if all(checks):
        print(f"  🟢 ВСЁ ХОРОШО")
        sys.exit(0)
    else:
        failed = sum(1 for c in checks if not c)
        print(f"  🔴 {failed} проверок провалено")

        # Уведомление в Telegram при проблемах
        if args.notify_tg:
            tg_token = os.getenv("TELEGRAM_TOKEN", "")
            if tg_token:
                msg = (
                    f"🚨 TicketBot Healthcheck\n"
                    f"Время: {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M:%S UTC')}\n"
                    f"Провалено проверок: {failed}\n"
                    f"Контейнеры: {'✅' if containers_ok else '❌'}\n"
                    f"База данных: {'✅' if db_ok else '❌'}"
                )
                await notify_tg(tg_token, args.notify_tg, msg)
            else:
                fail("TELEGRAM_TOKEN не указан для уведомлений")

        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
