"""
system_metrics.py — Фоновый сбор метрик системы в структурированные логи.

Использует psutil для сбора CPU, RAM, disk, load average.
Запускается как asyncio-задача внутри Telegram бота.

При превышении порогов автоматически отправляет алерт super-admin'у в Telegram.

Пример лога:
{
    "event_type": "system.metrics",
    "cpu_percent": 45.2,
    "memory_percent": 62.1,
    "disk_percent": 24.0,
    "load_1m": 0.5,
    "load_5m": 0.3,
    "load_15m": 0.2
}
"""

import asyncio
import json
import logging
import time
import urllib.request
from datetime import datetime, timezone

from app.config import settings

logger = logging.getLogger("ticketbot.system_metrics")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logger.warning("psutil not installed — system metrics disabled. Install: pip install psutil")

# ─── Пороги ───────────────────────────────────────────────
_THRESHOLDS = {
    "cpu_percent":    {"warn": 70, "crit": 90},
    "memory_percent": {"warn": 75, "crit": 90},
    "disk_percent":   {"warn": 75, "crit": 90},
    "load_per_cpu":   {"warn": 2.0, "crit": 4.0},
}

# Cooldown: не слать алерт по одной метрике чаще чем раз в N секунд
_ALERT_COOLDOWN = 300  # 5 минут
_last_alert: dict[str, float] = {}  # metric_name -> last_alert_time

# Grace period после старта: не проверять пороги первые N секунд
# (чтобы избежать ложных срабатываний во время деплоя, когда CPU в пике)
_STARTUP_GRACE_PERIOD = 180  # 3 минуты
_bot_start_time: float = time.monotonic()


def _fmt(val, unit=""):
    if isinstance(val, float):
        return f"{val:.1f}{unit}"
    return f"{val}{unit}"


async def _send_alert(criticals: list[str], warnings: list[str], metrics: dict):
    """Отправить алерт super-admin'у через Telegram HTTP API."""
    token = settings.telegram_token
    admin_ids = settings.admin_telegram_ids

    if not token or not admin_ids:
        return

    lines = ["🚨 <b>TicketBot: превышены пороги</b>\n"]

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

    lines.append(
        f"📊 <b>CPU:</b> {_fmt(metrics.get('cpu_percent', '?'))}% / "
        f"<b>RAM:</b> {_fmt(metrics.get('memory_percent', '?'))}% / "
        f"<b>Disk:</b> {_fmt(metrics.get('disk_percent', '?'))}% / "
        f"<b>Load:</b> {_fmt(metrics.get('load_1m', '?'))}"
    )
    lines.append(f"\n🕐 {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M:%S')} UTC")

    message = "\n".join(lines)
    payload = json.dumps({
        "chat_id": None,  # будет подставлен для каждого админа
        "text": message,
        "parse_mode": "HTML",
    })

    for admin_id in admin_ids.split(","):
        admin_id = admin_id.strip()
        if not admin_id:
            continue
        try:
            data = json.loads(payload)
            data["chat_id"] = admin_id
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
            logger.info("", extra={
                "event_type": "system.alert_sent",
                "admin_id": admin_id,
                "criticals": len(criticals),
                "warnings": len(warnings),
                "status": "success",
            })
        except Exception as e:
            logger.warning("", extra={
                "event_type": "system.alert_failed",
                "admin_id": admin_id,
                "error": str(e),
                "status": "error",
            })


def _check_thresholds_and_alert(metrics: dict):
    """Проверить метрики против порогов, отправить алерт если превышен.

    Использует cooldown — не шлёт повторный алерт по той же метрике
    чаще чем раз в _ALERT_COOLDOWN секунд.

    Grace period: первые _STARTUP_GRACE_PERIOD секунд после старта бота
    алерты не отправляются (чтобы избежать ложных срабатываний при деплое).
    """
    now = time.monotonic()

    # Grace period: не алертим сразу после старта
    if now - _bot_start_time < _STARTUP_GRACE_PERIOD:
        return

    warnings = []
    criticals = []

    # CPU
    cpu = metrics.get("cpu_percent", 0)
    if cpu >= _THRESHOLDS["cpu_percent"]["crit"]:
        key = "cpu_percent"
        if now - _last_alert.get(key, 0) > _ALERT_COOLDOWN:
            criticals.append(f"CPU: {_fmt(cpu, '%')} ≥ {_fmt(_THRESHOLDS['cpu_percent']['crit'], '%')}")
            _last_alert[key] = now
    elif cpu >= _THRESHOLDS["cpu_percent"]["warn"]:
        key = "cpu_percent"
        if now - _last_alert.get(key, 0) > _ALERT_COOLDOWN:
            warnings.append(f"CPU: {_fmt(cpu, '%')} ≥ {_fmt(_THRESHOLDS['cpu_percent']['warn'], '%')}")
            _last_alert[key] = now

    # RAM
    mem = metrics.get("memory_percent", 0)
    if mem >= _THRESHOLDS["memory_percent"]["crit"]:
        key = "memory_percent"
        if now - _last_alert.get(key, 0) > _ALERT_COOLDOWN:
            criticals.append(f"RAM: {_fmt(mem, '%')} ≥ {_fmt(_THRESHOLDS['memory_percent']['crit'], '%')}")
            _last_alert[key] = now
    elif mem >= _THRESHOLDS["memory_percent"]["warn"]:
        key = "memory_percent"
        if now - _last_alert.get(key, 0) > _ALERT_COOLDOWN:
            warnings.append(f"RAM: {_fmt(mem, '%')} ≥ {_fmt(_THRESHOLDS['memory_percent']['warn'], '%')}")
            _last_alert[key] = now

    # Disk
    disk = metrics.get("disk_percent", 0)
    if disk >= _THRESHOLDS["disk_percent"]["crit"]:
        key = "disk_percent"
        if now - _last_alert.get(key, 0) > _ALERT_COOLDOWN:
            criticals.append(f"Disk: {_fmt(disk, '%')} ≥ {_fmt(_THRESHOLDS['disk_percent']['crit'], '%')}")
            _last_alert[key] = now
    elif disk >= _THRESHOLDS["disk_percent"]["warn"]:
        key = "disk_percent"
        if now - _last_alert.get(key, 0) > _ALERT_COOLDOWN:
            warnings.append(f"Disk: {_fmt(disk, '%')} ≥ {_fmt(_THRESHOLDS['disk_percent']['warn'], '%')}")
            _last_alert[key] = now

    # Load per CPU
    load = metrics.get("load_1m", 0)
    cpus = metrics.get("cpu_count", 1)
    load_per_cpu = load / cpus if cpus > 0 else load
    if load_per_cpu >= _THRESHOLDS["load_per_cpu"]["crit"]:
        key = "load_per_cpu"
        if now - _last_alert.get(key, 0) > _ALERT_COOLDOWN:
            criticals.append(f"Load: {_fmt(load)} (per CPU: {_fmt(load_per_cpu)})")
            _last_alert[key] = now
    elif load_per_cpu >= _THRESHOLDS["load_per_cpu"]["warn"]:
        key = "load_per_cpu"
        if now - _last_alert.get(key, 0) > _ALERT_COOLDOWN:
            warnings.append(f"Load: {_fmt(load)} (per CPU: {_fmt(load_per_cpu)})")
            _last_alert[key] = now

    if criticals or warnings:
        # Запускаем отправку алерта (не ждём завершения)
        asyncio.ensure_future(_send_alert(criticals, warnings, metrics))


async def collect_and_log():
    """Собрать метрики системы, записать в лог, проверить пороги."""
    if not HAS_PSUTIL:
        return

    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        load = psutil.getloadavg()
        cpus = psutil.cpu_count()

        metrics = {
            "cpu_percent": cpu,
            "memory_percent": mem.percent,
            "memory_used_mb": round(mem.used / 1024 / 1024),
            "memory_total_mb": round(mem.total / 1024 / 1024),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
            "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
            "load_1m": round(load[0], 2),
            "load_5m": round(load[1], 2),
            "load_15m": round(load[2], 2),
            "cpu_count": cpus,
        }

        logger.info("", extra={
            "event_type": "system.metrics",
            **metrics,
            "status": "success",
        })

        # Проверка порогов + алерт
        _check_thresholds_and_alert(metrics)

    except Exception as e:
        logger.warning("", extra={
            "event_type": "system.metrics_error",
            "error": str(e),
            "status": "error",
        })


async def metrics_loop(interval: int = 60):
    """Бесконечный цикл сбора метрик.

    Args:
        interval: Интервал между сборами в секундах (по умолчанию 60).
    """
    if not HAS_PSUTIL:
        logger.warning("system_metrics: psutil not available, metrics loop disabled")
        return

    while True:
        await collect_and_log()
        await asyncio.sleep(interval)
