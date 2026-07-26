#!/usr/bin/env python3
"""
self-diagnose.py — Самодиагностика производительности TicketBot.

Анализирует систему, БД и логи приложения, проверяет пороги и
отправляет алерт в Telegram super-admin'у при превышении.

Использование:
  python scripts/self-diagnose.py
  python scripts/self-diagnose.py --verbose    # подробный вывод
  python scripts/self-diagnose.py --alert      # принудительная отправка алерта

Коды возврата:
  0 — всё в пределах нормы
  1 — есть WARNING
  2 — есть CRITICAL
"""

import os
import sys
import json
import asyncio
import argparse
import subprocess
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ─── Пороги ───────────────────────────────────────────────
THRESHOLDS = {
    "cpu_percent":       {"warn": 70,  "crit": 90},
    "memory_percent":    {"warn": 75,  "crit": 90},
    "disk_percent":      {"warn": 75,  "crit": 90},
    "db_connections_pct":{"warn": 70,  "crit": 90},
    "p95_duration_ms":   {"warn": 500, "crit": 1000},
    "error_rate_pct":    {"warn": 2,   "crit": 5},
    "load_per_cpu":      {"warn": 2.0, "crit": 4.0},
}

COMPOSE_FILES = os.getenv(
    "COMPOSE_FILES",
    "-f docker-compose.yml -f deploy/docker-compose.beget.yml -f deploy/docker-compose.monitoring.yml",
)


# ─── Утилиты ──────────────────────────────────────────────

def ok(msg: str):
    print(f"  ✅ {msg}")

def warn(msg: str):
    print(f"  ⚠️  {msg}")

def fail(msg: str):
    print(f"  ❌ {msg}")

def fmt(val, unit=""):
    if isinstance(val, float):
        return f"{val:.1f}{unit}"
    return f"{val}{unit}"


# ─── Шаг 1: System metrics ───────────────────────────────

def collect_system_metrics() -> dict:
    """Собрать метрики системы через psutil или /proc."""
    print("🔍 Система...")
    metrics = {}

    # Пробуем psutil (нативно)
    try:
        import psutil  # type: ignore
        metrics["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        metrics["memory_percent"] = mem.percent
        metrics["memory_used_mb"] = round(mem.used / 1024 / 1024)
        metrics["memory_total_mb"] = round(mem.total / 1024 / 1024)
        disk = psutil.disk_usage("/")
        metrics["disk_percent"] = disk.percent
        metrics["disk_used_gb"] = round(disk.used / 1024 / 1024 / 1024, 1)
        metrics["disk_total_gb"] = round(disk.total / 1024 / 1024 / 1024, 1)
        load = psutil.getloadavg()
        metrics["load_1m"] = load[0]
        metrics["load_5m"] = load[1]
        metrics["load_15m"] = load[2]
        metrics["cpu_count"] = psutil.cpu_count()
    except ImportError:
        # Fallback: читаем /proc
        try:
            with open("/proc/stat") as f:
                fields = f.readline().split()
                total = sum(int(v) for v in fields[1:])
                idle = int(fields[4])
                metrics["cpu_percent"] = round(100 - (idle / total * 100), 1)
        except Exception:
            metrics["cpu_percent"] = 0

        try:
            with open("/proc/meminfo") as f:
                data = {}
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip().split()[0]
                        data[key] = int(val) * 1024  # kB → bytes
            total = data.get("MemTotal", 1)
            available = data.get("MemAvailable", 0)
            metrics["memory_percent"] = round(100 - (available / total * 100), 1)
            metrics["memory_used_mb"] = round((total - available) / 1024 / 1024)
            metrics["memory_total_mb"] = round(total / 1024 / 1024)
        except Exception:
            metrics["memory_percent"] = 0

        try:
            statvfs = os.statvfs("/")
            total = statvfs.f_frsize * statvfs.f_blocks
            free = statvfs.f_frsize * statvfs.f_bfree
            used = total - free
            metrics["disk_percent"] = round(used / total * 100, 1)
            metrics["disk_used_gb"] = round(used / 1024 / 1024 / 1024, 1)
            metrics["disk_total_gb"] = round(total / 1024 / 1024 / 1024, 1)
        except Exception:
            metrics["disk_percent"] = 0

        try:
            with open("/proc/loadavg") as f:
                parts = f.read().strip().split()
                metrics["load_1m"] = float(parts[0])
                metrics["load_5m"] = float(parts[1])
                metrics["load_15m"] = float(parts[2])
        except Exception:
            metrics["load_1m"] = metrics["load_5m"] = metrics["load_15m"] = 0

        metrics["cpu_count"] = os.cpu_count() or 1

    ok(f"CPU: {fmt(metrics['cpu_percent'], '%')} "
       f"| RAM: {fmt(metrics['memory_percent'], '%')} "
       f"({fmt(metrics['memory_used_mb'])}/{fmt(metrics['memory_total_mb'])} MB) "
       f"| Disk: {fmt(metrics['disk_percent'], '%')} "
       f"| Load: {fmt(metrics['load_1m'])}/{metrics['cpu_count']} CPUs")
    return metrics


# ─── Шаг 2: DB metrics ────────────────────────────────────

async def collect_db_metrics() -> dict:
    """Собрать метрики PostgreSQL: соединения, размер, блокировки."""
    print("🔍 База данных...")
    metrics = {}

    try:
        from app.core.database import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as session:
            # Активные соединения
            row = await session.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE state IS NOT NULL"
            ))
            metrics["db_total_connections"] = row.scalar() or 0

            row = await session.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
            ))
            metrics["db_active_connections"] = row.scalar() or 0

            row = await session.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'"
            ))
            metrics["db_locked_queries"] = row.scalar() or 0

            row = await session.execute(text("SHOW max_connections"))
            metrics["db_max_connections"] = int(row.scalar() or 100)

            row = await session.execute(text(
                "SELECT pg_database_size(current_database())"
            ))
            db_size_bytes = row.scalar() or 0
            metrics["db_size_mb"] = round(db_size_bytes / 1024 / 1024)

            # Долгие запросы (>5s)
            row = await session.execute(text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE state = 'active' AND now() - query_start > interval '5 seconds'"
            ))
            metrics["db_long_queries"] = row.scalar() or 0

        conn_pct = round(
            metrics["db_total_connections"] / metrics["db_max_connections"] * 100, 1
        ) if metrics["db_max_connections"] > 0 else 0
        metrics["db_connections_pct"] = conn_pct

        ok(f"Соединений: {metrics['db_total_connections']}/{metrics['db_max_connections']} "
           f"({fmt(conn_pct, '')}%) "
           f"| Активных: {metrics['db_active_connections']} "
           f"| Размер БД: {fmt(metrics['db_size_mb'])} MB")
        if metrics["db_locked_queries"] > 0:
            warn(f"Заблокированных запросов: {metrics['db_locked_queries']}")
        if metrics["db_long_queries"] > 0:
            warn(f"Долгих запросов (>5с): {metrics['db_long_queries']}")

    except Exception as e:
        fail(f"Не удалось подключиться к БД: {e}")
        metrics["db_error"] = str(e)
        metrics["db_connections_pct"] = 0

    return metrics


# ─── Шаг 3: Application metrics из логов ──────────────────

def collect_app_metrics(tail_lines: int = 500) -> dict:
    """Проанализировать Docker-логи Telegram бота.

    Парсит JSON-строки с event_type, duration_ms и status.
    Вычисляет: RPS, p95 latency, error rate, распределение по типам.
    """
    print(f"🔍 Логи приложения (последние {tail_lines} строк)...")
    metrics = {}

    try:
        docker_cmd = [
            "docker", "compose"] + COMPOSE_FILES.split() + [
            "logs", "--tail", str(tail_lines), "telegram"
        ]
        result = subprocess.run(
            docker_cmd, capture_output=True, text=True, timeout=15,
        )
        raw_logs = result.stdout + result.stderr
    except FileNotFoundError:
        fail("Docker не найден")
        return {"app_error": "docker not found"}
    except subprocess.TimeoutExpired:
        fail("Таймаут при чтении логов Docker")
        return {"app_error": "timeout"}
    except Exception as e:
        fail(f"Ошибка чтения логов: {e}")
        return {"app_error": str(e)}

    durations = defaultdict(list)
    error_count = 0
    total_count = 0
    event_type_counts = defaultdict(int)
    recent_events = []
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)

    for line in raw_logs.split("\n"):
        line = line.strip()
        # Ищем JSON в строке лога (после префикса контейнера)
        try:
            json_start = line.index("{")
            obj = json.loads(line[json_start:])
        except (ValueError, json.JSONDecodeError):
            continue

        event_type = obj.get("event_type", "")
        if not event_type or event_type == "system.metrics":
            continue

        total_count += 1
        event_type_counts[event_type] += 1

        if obj.get("status") == "error":
            error_count += 1

        duration = obj.get("duration_ms")
        if duration is not None:
            durations[event_type].append(duration)
            # Для p95 всех запросов
            durations["_all"].append(duration)

        # Для подсчёта RPS: считаем только за последние 5 минут
        ts = obj.get("timestamp", "")
        if ts:
            try:
                t = datetime.fromisoformat(ts)
                if t >= cutoff:
                    recent_events.append(t)
            except Exception:
                pass

    if total_count == 0:
        ok("Нет бизнес-логов за последнее время (возможно, нет активности)")
        return {"app_empty": True}

    # Error rate
    error_rate = round(error_count / total_count * 100, 2)
    metrics["total_events"] = total_count
    metrics["error_count"] = error_count
    metrics["error_rate_pct"] = error_rate

    # RPS за последние 5 минут
    time_span = min(300, (datetime.now(timezone.utc) - cutoff).total_seconds())
    if time_span > 0:
        rps = round(len(recent_events) / time_span, 2)
    else:
        rps = 0
    metrics["rps_5min"] = rps

    # p95 latency (все запросы)
    all_durations = sorted(durations.get("_all", []))
    if all_durations:
        p95_idx = int(len(all_durations) * 0.95)
        metrics["p95_duration_ms"] = all_durations[p95_idx]
        metrics["p50_duration_ms"] = all_durations[len(all_durations) // 2]
        metrics["avg_duration_ms"] = round(sum(all_durations) / len(all_durations), 1)
        metrics["max_duration_ms"] = all_durations[-1]
    else:
        metrics["p95_duration_ms"] = 0

    # Топ-5 типов событий
    top_events = sorted(event_type_counts.items(), key=lambda x: -x[1])[:5]

    ok(f"{total_count} событий | "
       f"Ошибок: {error_count} ({fmt(error_rate, '')}%) | "
       f"RPS: {fmt(rps)} | "
       f"p50: {fmt(metrics.get('p50_duration_ms', 0))}ms | "
       f"p95: {fmt(metrics.get('p95_duration_ms', 0))}ms")

    for evt, cnt in top_events:
        evt_durations = durations.get(evt, [])
        if evt_durations:
            avg_d = round(sum(evt_durations) / len(evt_durations), 1)
            print(f"     {evt}: {cnt} раз, среднее {fmt(avg_d)}ms")
        else:
            print(f"     {evt}: {cnt} раз")

    return metrics


# ─── Шаг 4: Threshold check ──────────────────────────────

def check_thresholds(
    system: dict,
    db: dict,
    app: dict,
) -> tuple[list[str], list[str]]:
    """Проверить все метрики против порогов.

    Returns:
        tuple[list[str], list[str]]: (warnings, criticals)
    """
    print("\n🔍 Проверка порогов...")
    warnings = []
    criticals = []

    # CPU
    cpu = system.get("cpu_percent", 0)
    if cpu >= THRESHOLDS["cpu_percent"]["crit"]:
        criticals.append(f"CPU: {fmt(cpu, '%')} ≥ {fmt(THRESHOLDS['cpu_percent']['crit'], '%')}")
    elif cpu >= THRESHOLDS["cpu_percent"]["warn"]:
        warnings.append(f"CPU: {fmt(cpu, '%')} ≥ {fmt(THRESHOLDS['cpu_percent']['warn'], '%')}")

    # RAM
    mem = system.get("memory_percent", 0)
    if mem >= THRESHOLDS["memory_percent"]["crit"]:
        criticals.append(f"RAM: {fmt(mem, '%')} ≥ {fmt(THRESHOLDS['memory_percent']['crit'], '%')}")
    elif mem >= THRESHOLDS["memory_percent"]["warn"]:
        warnings.append(f"RAM: {fmt(mem, '%')} ≥ {fmt(THRESHOLDS['memory_percent']['warn'], '%')}")

    # Disk
    disk = system.get("disk_percent", 0)
    if disk >= THRESHOLDS["disk_percent"]["crit"]:
        criticals.append(f"Disk: {fmt(disk, '%')} ≥ {fmt(THRESHOLDS['disk_percent']['crit'], '%')}")
    elif disk >= THRESHOLDS["disk_percent"]["warn"]:
        warnings.append(f"Disk: {fmt(disk, '%')} ≥ {fmt(THRESHOLDS['disk_percent']['warn'], '%')}")

    # Load per CPU
    load = system.get("load_1m", 0)
    cpus = system.get("cpu_count", 1)
    load_per_cpu = load / cpus if cpus > 0 else load
    if load_per_cpu >= THRESHOLDS["load_per_cpu"]["crit"]:
        criticals.append(f"Load: {fmt(load)} (per CPU: {fmt(load_per_cpu)})")
    elif load_per_cpu >= THRESHOLDS["load_per_cpu"]["warn"]:
        warnings.append(f"Load: {fmt(load)} (per CPU: {fmt(load_per_cpu)})")

    # DB connections
    db_conn = db.get("db_connections_pct", 0)
    if db_conn >= THRESHOLDS["db_connections_pct"]["crit"]:
        criticals.append(f"DB connections: {fmt(db_conn, '')}% ≥ {fmt(THRESHOLDS['db_connections_pct']['crit'], '')}%")
    elif db_conn >= THRESHOLDS["db_connections_pct"]["warn"]:
        warnings.append(f"DB connections: {fmt(db_conn, '')}% ≥ {fmt(THRESHOLDS['db_connections_pct']['warn'], '')}%")

    # DB locks
    if db.get("db_locked_queries", 0) > 0:
        warnings.append(f"DB locked queries: {db['db_locked_queries']}")

    # DB long queries
    if db.get("db_long_queries", 0) > 0:
        warnings.append(f"DB long queries (>5s): {db['db_long_queries']}")

    # p95 latency
    p95 = app.get("p95_duration_ms", 0)
    if p95 >= THRESHOLDS["p95_duration_ms"]["crit"]:
        criticals.append(f"p95 latency: {fmt(p95)}ms ≥ {fmt(THRESHOLDS['p95_duration_ms']['crit'])}ms")
    elif p95 >= THRESHOLDS["p95_duration_ms"]["warn"]:
        warnings.append(f"p95 latency: {fmt(p95)}ms ≥ {fmt(THRESHOLDS['p95_duration_ms']['warn'])}ms")

    # Error rate
    err = app.get("error_rate_pct", 0)
    if err >= THRESHOLDS["error_rate_pct"]["crit"]:
        criticals.append(f"Error rate: {fmt(err, '')}% ≥ {fmt(THRESHOLDS['error_rate_pct']['crit'], '')}%")
    elif err >= THRESHOLDS["error_rate_pct"]["warn"]:
        warnings.append(f"Error rate: {fmt(err, '')}% ≥ {fmt(THRESHOLDS['error_rate_pct']['warn'], '')}%")

    # Вывод
    if not warnings and not criticals:
        ok("Все метрики в пределах нормы")
    else:
        for w in warnings:
            warn(w)
        for c in criticals:
            fail(c)

    return warnings, criticals


# ─── Telegram alert ───────────────────────────────────────

def send_telegram_alert(
    system: dict, db: dict, app: dict,
    warnings: list[str], criticals: list[str],
):
    """Отправить алерт super-admin'у через Telegram HTTP API."""
    token = os.getenv("TELEGRAM_TOKEN", "")
    admin_ids = os.getenv("ADMIN_TELEGRAM_IDS", "")

    if not token or not admin_ids:
        print("\n  ℹ️  TELEGRAM_TOKEN или ADMIN_TELEGRAM_IDS не заданы — алерт не отправлен")
        return

    # Формируем сообщение
    lines = ["🚨 <b>TicketBot: диагностика</b>\n"]

    if criticals:
        lines.append("🔴 <b>CRITICAL:</b>")
        for c in criticals:
            lines.append(f"  ▸ {c}")
        lines.append("")

    if warnings:
        lines.append("🟡 <b>WARNING:</b>")
        for w in warnings:
            lines.append(f"  ▸ {w}")
        lines.append("")

    lines.append(f"📊 <b>CPU:</b> {fmt(system.get('cpu_percent', '?'))}% / "
                 f"<b>RAM:</b> {fmt(system.get('memory_percent', '?'))}% / "
                 f"<b>Disk:</b> {fmt(system.get('disk_percent', '?'))}%")
    lines.append(f"📊 <b>DB:</b> {db.get('db_total_connections', '?')}/{db.get('db_max_connections', '?')} conn / "
                 f"{fmt(db.get('db_size_mb', '?'))} MB")
    lines.append(f"📊 <b>App:</b> {app.get('total_events', '?')} events / "
                 f"p95 {fmt(app.get('p95_duration_ms', '?'))}ms / "
                 f"err {fmt(app.get('error_rate_pct', '?'))}% / "
                 f"RPS {fmt(app.get('rps_5min', '?'))}")
    lines.append(f"\n🕐 {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M:%S')} UTC")

    message = "\n".join(lines)

    # Отправляем каждому super-admin'у через HTTP API
    import urllib.request
    for admin_id in admin_ids.split(","):
        admin_id = admin_id.strip()
        if not admin_id:
            continue
        try:
            payload = json.dumps({
                "chat_id": admin_id,
                "text": message,
                "parse_mode": "HTML",
            }).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
            ok(f"Алерт отправлен super-admin'у {admin_id}")
        except Exception as e:
            fail(f"Не удалось отправить алерт {admin_id}: {e}")


# ─── Main ────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Самодиагностика TicketBot")
    parser.add_argument("--verbose", "-v", action="store_true", help="Подробный вывод")
    parser.add_argument("--alert", action="store_true", help="Принудительно отправить алерт (даже если всё ОК)")
    parser.add_argument("--tail", type=int, default=500, help="Сколько строк логов анализировать")
    args = parser.parse_args()

    print(f"\n{'═' * 45}")
    print(f"  🩺 Самодиагностика TicketBot")
    print(f"  {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M:%S')} UTC")
    print(f"{'═' * 45}\n")

    # Шаг 1: Система
    system = collect_system_metrics()
    print()

    # Шаг 2: БД
    db = await collect_db_metrics()
    print()

    # Шаг 3: Логи приложения
    app = collect_app_metrics(tail_lines=args.tail)
    print()

    # Шаг 4: Пороги
    warnings, criticals = check_thresholds(system, db, app)
    print(f"\n{'─' * 45}")

    # Итог
    if criticals:
        print(f"\n  🔴 CRITICAL: {len(criticals)} проблем")
        print(f"     ⚠️  WARNING: {len(warnings)} проблем\n")
        exit_code = 2
        # Всегда отправляем алерт при critical
        send_telegram_alert(system, db, app, warnings, criticals)
    elif warnings:
        print(f"\n  🟡 WARNING: {len(warnings)} проблем\n")
        exit_code = 1
        send_telegram_alert(system, db, app, warnings, criticals)
    else:
        print(f"\n  🟢 Всё хорошо\n")
        exit_code = 0
        if args.alert:
            send_telegram_alert(system, db, app, warnings, criticals)

    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
