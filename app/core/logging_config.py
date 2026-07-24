"""
logging_config.py — Единая конфигурация структурированного JSON-логирования.

Выводит логи в stdout в JSON-формате.
Все entry points должны вызывать setup_logging() при старте.

Формат лога:
{
    "timestamp": "2026-07-24T12:00:00.000Z",
    "level": "INFO",
    "logger": "ticketbot.services",
    "message": "",
    "event_type": "ticket.purchased",
    "user_id": "tg_12345",
    "platform": "telegram",
    "status": "success",
    "duration_ms": 45
}
"""

import json
import logging
import sys
from datetime import datetime, timezone

# Подавляем шумные логгеры сторонних библиотек
SILENT_LOGGERS = [
    "aiogram",
    "aiogram.event",
    "aiogram.dispatcher",
    "sqlalchemy",
    "sqlalchemy.engine",
    "httpx",
    "httpx._client",
    "urllib3",
    "urllib3.connectionpool",
    "asyncio",
    "vkbottle",
    "aiohttp",
    "aiohttp.access",
]

# Стандартные поля LogRecord, которые мы НЕ включаем в JSON
# (все internal-поля Python logging)
_INTERNAL_FIELDS = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}


class CompactJsonFormatter(logging.Formatter):
    """Форматтер, который выводит только нужные поля в JSON.

    Включает: timestamp, level, logger, message + все extra-поля.
    Исключает все стандартные поля LogRecord.

    Использование:
        logger.info("", extra={"event_type": "ticket.purchased", "user_id": "..."})
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage() if record.args else (record.msg or ""),
        }

        # Добавляем только extra-поля, пропуская все внутренние
        for key, value in record.__dict__.items():
            if key not in _INTERNAL_FIELDS and not key.startswith("_"):
                log_entry[key] = value

        return json.dumps(log_entry, ensure_ascii=False, default=str)


def setup_logging(
    logger_name: str = "ticketbot",
    extra_fields: dict | None = None,
    debug: bool = False,
):
    """Настроить JSON-логирование для процесса.

    Args:
        logger_name: Имя корневого логгера (например 'ticketbot.telegram').
        extra_fields: Дополнительные поля, добавляемые во все логи
                      (например {'platform': 'telegram'}).
        debug: Включить DEBUG-уровень (при settings.debug=True).
    """
    level = logging.DEBUG if debug else logging.INFO

    formatter = CompactJsonFormatter()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Настраиваем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Подавляем шумные логгеры
    for name in SILENT_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
        logging.getLogger(name).propagate = False

    # Наш логгер
    app_logger = logging.getLogger(logger_name)
    app_logger.setLevel(level)

    return app_logger
