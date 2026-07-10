#!/usr/bin/env python3
"""
healthcheck.py — Проверка работоспособности TicketBot.

Проверяет контейнеры платформ (telegram, vk, max) и доступность БД.

Использование:
  python scripts/healthcheck.py
  python scripts/healthcheck.py --verbose
  python scripts/healthcheck.py --platform telegram

Коды возврата:
  0 — всё хорошо
  1 — ошибка
"""

import os
import sys
import asyncio
import argparse
import subprocess
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SERVICES = ["telegram", "vk", "max"]


def ok(msg: str):
    print(f"  ✅ {msg}")


def fail(msg: str):
    print(f"  ❌ {msg}")


# ─── 1. Docker-контейнеры ──────────────────────────────

def check_containers(platform: str | None = None) -> bool:
    """Проверить, что контейнеры работают."""
    services = [platform] if platform else SERVICES
    print(f"🔍 Проверка контейнеров: {', '.join(services)}...")

    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "{{.Name}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            fail("Не удалось выполнить docker compose ps")
            return False

        lines = [l.strip() for l in result.stdout.split("\n") if l.strip()]
        all_ok = True
        found = set()

        for line in lines:
            for svc in services:
                if svc in line:
                    found.add(svc)
                    if "Up" in line:
                        ok(line)
                    else:
                        fail(line)
                        all_ok = False

        for svc in services:
            if svc not in found:
                fail(f"Контейнер ticketbot-{svc} не найден")
                all_ok = False

        return all_ok
    except FileNotFoundError:
        fail("Docker не найден. Проверьте установку.")
        return False
    except subprocess.TimeoutExpired:
        fail("Таймаут при проверке контейнеров")
        return False


# ─── 2. Подключение к БД ────────────────────────────────

async def check_database() -> bool:
    """Проверить подключение к PostgreSQL."""
    print("🔍 Проверка базы данных...")

    try:
        from sqlalchemy import select, func, text
        from app.core.database import async_session_factory
        from app.core.models import Event

        async with async_session_factory() as session:
            result = await session.execute(select(func.count(Event.id)))
            count = result.scalar() or 0
            ok(f"PostgreSQL доступен, мероприятий в БД: {count}")

            result = await session.execute(text("SELECT NOW()"))
            now = result.scalar()
            ok(f"Серверное время: {now}")

        return True
    except Exception as e:
        fail(f"Ошибка подключения к БД: {e}")
        return False


# ─── 3. Логи на ошибки ──────────────────────────────────

def check_logs_for_errors(platform: str | None = None) -> bool:
    """Проверить последние логи на наличие ошибок."""
    services = [platform] if platform else SERVICES
    print(f"🔍 Проверка логов: {', '.join(services)}...")

    try:
        all_ok = True
        for svc in services:
            result = subprocess.run(
                ["docker", "compose", "logs", "--tail", "50", svc],
                capture_output=True, text=True, timeout=10,
            )
            logs = result.stdout + result.stderr

            error_lines = []
            for line in logs.split("\n"):
                if "ERROR" in line or "Traceback" in line or "Error" in line:
                    if "Operation not permitted" not in line:
                        error_lines.append(line.strip())

            if error_lines:
                for err_line in error_lines[:3]:
                    fail(f"[{svc}] {err_line}")
                if len(error_lines) > 3:
                    fail(f"[{svc}] ...и ещё {len(error_lines) - 3} ошибок")
                all_ok = False
            else:
                ok(f"[{svc}] Критических ошибок нет")

        return all_ok
    except Exception as e:
        fail(f"Не удалось проверить логи: {e}")
        return True


# ─── 4. Отправка уведомления ────────────────────────────

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


# ─── Main ───────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Healthcheck для TicketBot")
    parser.add_argument("--verbose", "-v", action="store_true", help="Подробный вывод")
    parser.add_argument("--platform", choices=SERVICES, help="Проверить только одну платформу")
    parser.add_argument("--notify-tg", metavar="CHAT_ID", help="Уведомление в Telegram при проблемах")
    args = parser.parse_args()

    print(f"\n{'═' * 40}")
    print(f"  Healthcheck TicketBot")
    print(f"  {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M:%S UTC')}")
    print(f"{'═' * 40}\n")

    checks = []

    containers_ok = check_containers(args.platform)
    checks.append(containers_ok)
    print()

    db_ok = await check_database()
    checks.append(db_ok)
    print()

    logs_ok = check_logs_for_errors(args.platform)
    checks.append(logs_ok)
    print()

    print(f"{'─' * 40}")
    if all(checks):
        print(f"  🟢 ВСЁ ХОРОШО")
        sys.exit(0)
    else:
        failed = sum(1 for c in checks if not c)
        print(f"  🔴 {failed} проверок провалено")

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

        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
