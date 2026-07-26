# Система логирования поведения пользователя

## Назначение

Отслеживать все бизнес-действия пользователей в приложении для анализа и отладки.

**Что логируется:**
- Покупка/отмена билетов (успех и ошибки с причиной)
- Создание/изменение/удаление мероприятий
- Регистрация пользователей
- Управление подписками каналов
- Нажатия inline-кнопок в Telegram
- Добавление/удаление бота из каналов

**Что НЕ логируется (в этой системе):**
- Технические события (запуск/стоп, ошибки отправки сообщений) — остаются как есть
- HTTP-запросы REST API (будут при необходимости)

---

## Архитектура

```
Пользователь → Telegram Bot / Web App → Service Layer
                                              ↓
                    logger.info("", extra={"event_type": "ticket.purchased", ...})
                                              ↓
                    CompactJsonFormatter → JSON-строка → stdout
                                              ↓
                    Docker (json-file driver) → docker compose logs
                                              ↓
                    Promtail → Loki → Grafana (на сервере)
                                              ↓
                    ты: !make -C deploy logs-app → мне на анализ
```

Все логи пишутся в **stdout** процесса. Docker подхватывает их через стандартный `json-file` driver. На сервере работает стек Promtail → Loki → Grafana.

---

## Формат лога

Каждая строка — валидный JSON с минимальным набором полей:

```json
{
  "timestamp": "2026-07-24T12:00:00.000000+00:00",
  "level": "INFO",
  "logger": "ticketbot.services",
  "message": "",
  "event_type": "ticket.purchased",
  "ticket_id": "uuid-xxx",
  "event_id": "uuid-yyy",
  "event_title": "Концерт",
  "user_id": "tg_12345",
  "amount": 1000.0,
  "status": "success",
  "duration_ms": 42
}
```

### Поля

| Поле | Всегда | Описание |
|------|--------|---------|
| `timestamp` | ✅ | ISO-8601 в UTC |
| `level` | ✅ | `INFO` / `WARNING` / `ERROR` |
| `logger` | ✅ | Имя логгера: `ticketbot.services` или `ticketbot.telegram` |
| `message` | ✅ | Текстовое сообщение (обычно пустое, данные в extra) |
| `event_type` | ✅ | Тип события (см. таблицу ниже) |
| `status` | ✅ | `"success"` или `"error"` |
| `platform` | — | `"telegram"` / `"vk"` / `"web"` |
| `duration_ms` | — | Время выполнения операции в миллисекундах |
| `user_id` | — | ID пользователя на платформе |
| `error` | — | Причина ошибки (только при `status: "error"`) |
| ... | — | Остальные поля зависят от типа события |

---

## Типы событий (event_type)

### Покупка билетов

| event_type | Уровень | Когда | Доп. поля |
|---|---|---|---|
| `ticket.purchased` | INFO | Успешная покупка через Telegram | `ticket_id`, `event_id`, `event_title`, `user_id`, `amount` |
| `ticket.purchased_webapp` | INFO | Успешная покупка через Mini App | `ticket_id`, `event_id`, `event_title`, `user_id`, `amount` |
| `ticket.purchase_failed` | WARNING | Ошибка покупки (любая причина) | `event_id`, `user_id`, `error` |
| `ticket.purchase_webapp_failed` | WARNING | Ошибка покупки через Mini App | `event_id`, `user_id`, `error` |
| `ticket.cancelled` | INFO | Отмена билета пользователем | `ticket_id`, `event_id`, `user_id` |
| `ticket.admin_cancelled` | INFO | Отмена билета администратором | `ticket_id`, `event_id` |
| `ticket.cancel_failed` | WARNING | Ошибка отмены | `ticket_id`, `user_id`, `error` |
| `ticket.admin_cancel_failed` | WARNING | Ошибка админской отмены | `ticket_id`, `error` |

### Мероприятия

| event_type | Уровень | Когда | Доп. поля |
|---|---|---|---|
| `event.created` | INFO | Создано мероприятие | `event_id`, `event_title`, `channel_id`, `price`, `total_tickets` |
| `event.updated` | INFO | Изменено мероприятие | `event_id`, `changed` (какие поля) |
| `event.toggled` | INFO | Включено/отключено | `event_id`, `is_active` |
| `event.deleted` | INFO | Удалено (soft delete) | `event_id`, `event_title` |
| `event.get_by_id` | INFO | Запрос деталей мероприятия | `event_id`, `found` |
| `event.list_upcoming` | INFO | Список предстоящих мероприятий | `channel_id`, `count` |
| `event.list_all` | INFO | Все мероприятия админа | `channel_id`, `count` |
| `event.get_stats` | INFO | Статистика продаж | `event_id`, `sold`, `refunded`, `revenue` |

### Пользователи

| event_type | Уровень | Когда | Доп. поля |
|---|---|---|---|
| `user.created` | INFO | Создан новый пользователь | `platform`, `user_id` |
| `user.found` | INFO | Найден существующий | `platform`, `user_id` |
| `user.started` | INFO | Команда /start | `user_id`, `payload` (deep link) |
| `user.deep_link_buy` | INFO | Переход по deep link buy_ | `user_id`, `event_id` |
| `user.buy_command` | INFO | Команда /buy | `user_id`, `event_id` |

### Каналы и подписки

| event_type | Уровень | Когда | Доп. поля |
|---|---|---|---|
| `channel.created` | INFO | Создан канал в БД | `channel_id`, `telegram_channel_id` |
| `channel.admin_changed` | INFO | Смена администратора | `channel_id`, `old_admin_ids`, `new_admin_id` |
| `channel.get_by_telegram_id` | INFO | Поиск канала по ID | `telegram_channel_id`, `found` |
| `channel.get_by_id` | INFO | Поиск канала по UUID | `channel_id`, `found` |
| `channel.subscription_check` | INFO | Проверка подписки | `channel_id`, `valid`, `reason` |
| `channel.get_active_unassigned` | INFO | Поиск канала без админа | `found` |
| `channel.get_ids_by_admin` | INFO | ID каналов админа | `admin_id`, `count` |
| `channel.get_channels_by_admin` | INFO | Каналы админа | `admin_id`, `count` |
| `subscription.activated` | INFO | Активирована подписка | `channel_id`, `duration_days`, `subscription_until` |
| `subscription.deactivated` | INFO | Деактивирована подписка | `channel_id` |
| `subscription.auto_expired` | INFO | Авто-деактивация просрочки | `channel_id` |

### Администраторы

| event_type | Уровень | Когда | Доп. поля |
|---|---|---|---|
| `channel_admins.synced` | INFO | Синхронизация админов | `channel_id`, `added`, `removed` |
| `channel_admin.removed` | INFO | Удалён администратор | `channel_id`, `user_id` |
| `channel_admin.get_ids` | INFO | Список админов канала | `channel_id`, `count` |
| `channel_admin.user_is_admin` | INFO | Проверка прав админа | `channel_id`, `user_id`, `is_admin` |

### Билеты (чтение)

| event_type | Уровень | Когда | Доп. поля |
|---|---|---|---|
| `ticket.get_user_tickets` | INFO | Билеты пользователя | `user_id`, `count` |
| `ticket.get_event_tickets` | INFO | Билеты на мероприятие (админ) | `event_id`, `count` |

### Системные метрики (фоновый сбор)

| event_type | Уровень | Когда | Доп. поля |
|---|---|---|---|
| `system.metrics` | INFO | Каждые 60с фоновым сборщиком | `cpu_percent`, `memory_percent`, `disk_percent`, `load_1m`, `load_5m`, `load_15m` |
| `system.metrics_error` | WARNING | Ошибка сбора метрик | `error` |

### Системные события Telegram

| event_type | Уровень | Когда | Доп. поля |
|---|---|---|---|
| `callback.received` | INFO | Нажата inline-кнопка | `callback_data`, `user_id` |
| `bot.added_to_channel` | INFO | Бот добавлен в канал | `channel_id`, `adder_id` |
| `bot.removed_from_channel` | INFO | Бот удалён из канала | `channel_id` |

---

## Самодиагностика производительности

Проект содержит систему самодиагностики, которая проверяет пороги производительности
и отправляет алерт в Telegram super-admin'у при превышении.

### Скрипт: `scripts/self-diagnose.py`

```bash
# Полная диагностика (через SSH на сервере)
make -C deploy diagnose

# С принудительным алертом в Telegram
make -C deploy diagnose-alert
```

**4 шага диагностики:**
1. **System** — CPU, RAM, disk, load average (psutil или /proc)
2. **DB** — активные соединения, блокировки, долгие запросы, размер БД
3. **App logs** — парсинг Docker-логов: p50/p95 duration_ms, error rate, RPS, типы событий
4. **Threshold check** — сравнение метрик с порогами, алерт в Telegram при превышении

### Пороги

| Метрика | Warning | Critical |
|---------|---------|----------|
| CPU usage | >70% | >90% |
| RAM usage | >75% | >90% |
| Disk usage | >75% | >90% |
| DB connections | >70% от max_connections | >90% от max_connections |
| p95 latency | >500ms | >1000ms |
| Error rate | >2% | >5% |
| Load per CPU | >2.0 | >4.0 |

### Фоновый сбор метрик: `app/core/system_metrics.py`

Запускается как asyncio-задача внутри Telegram бота.
Каждые 60 секунд логирует `event_type: system.metrics` с CPU/RAM/disk/load.

Не требует новых зависимостей — использует `psutil` (optional dep `[monitoring]`)
или читает `/proc` как fallback.

### Makefile-цели

```bash
make -C deploy diagnose           # 🩺 Полная диагностика
make -C deploy diagnose-alert     # + алерт в Telegram
make -C deploy diagnose-verbose   # подробный вывод
```

### Автоматический режим

Система самодиагностики работает в двух режимах одновременно:

1. **Внутри бота** — `metrics_loop` раз в 60с проверяет CPU/RAM/disk/load. При превышении порогов отправляет алерт super-admin'у в Telegram (с cooldown 5 мин, чтобы не спамить)
2. **Cron на сервере** — `scripts/cron-diagnose.py` запускает полную диагностику (включая БД и RPS) раз в 5 минут через crontab

**Cron-задание устанавливается автоматически** при деплое через GitHub Actions (шаг `⏰ Установить cron-задание самодиагностики` в `deploy.yml`). При каждом деплое проверяется актуальность — если команда совпадает, ничего не меняется.

Лог cron: `/var/log/ticketbot-diagnose.log`

Проверить вручную на сервере:
```bash
ssh vps 'crontab -l | grep cron-diagnose'
tail -f /var/log/ticketbot-diagnose.log'
```

---

## Анализ логов (через Claude)

### Быстрый просмотр

После действия в боте — запросить последние логи:

```
!make -C deploy logs-app LINES=30
```

Я получу структурированные JSON-логи и смогу:
- Определить, какая операция выполнялась
- Найти причину ошибки (поле `error`)
- Увидеть время выполнения (поле `duration_ms`)
- Понять последовательность действий пользователя

### Фильтрация

```bash
# Только покупки
docker compose logs telegram | grep ticket.purchased

# Только ошибки
docker compose logs telegram | grep purchase_failed

# Действия конкретного пользователя
docker compose logs telegram | grep tg_12345

# Все события сервисного слоя
docker compose logs telegram | grep ticketbot.services
```

---

## Как это устроено в коде

### Модуль: `app/core/logging_config.py`

- `setup_logging(name, extra_fields, debug)` — вызывается в каждом entry point при старте
- `CompactJsonFormatter` — кастомный форматтер, выводит только `timestamp`, `level`, `logger`, `message` + все `extra`-поля
- Подавляет шумные логгеры (`aiogram`, `sqlalchemy`, `httpx`, `urllib3` и др.)

### Слой: `app/core/services.py`

Каждый метод всех сервисов логирует результат работы:
```python
logger.info("", extra={
    "event_type": "ticket.purchased",
    "ticket_id": str(ticket.id),
    "event_title": event.title,
    "user_id": str(user_id),
    "amount": float(event.price),
    "status": "success",
    "duration_ms": _ms(start),
})
```

При ошибке — `logger.warning()` с `"status": "error"` + `"error": "причина"`.

### Хендлеры: `app/platforms/telegram/bot.py`

- `cmd_start()` → `user.started`, `user.deep_link_buy`
- `cmd_buy()` → `user.buy_command`
- `_do_buy_ticket()` → `ticket.purchase_failed_ui`
- `cmd_callback()` → `callback.received`
- `on_chat_member_update()` → `bot.added_to_channel`, `bot.removed_from_channel`

### Entry points

Все `bot/*.py` используют `setup_logging()` вместо inline `basicConfig`:

```python
from app.core.logging_config import setup_logging
logger = setup_logging("ticketbot.telegram", {"platform": "telegram"}, debug=settings.debug)
```

### Зависимости

- **`CompactJsonFormatter`** — написан на стандартном `logging` + `json` (нет внешних зависимостей)
- **`psutil`** — основная зависимость (не опциональная), для фонового сбора метрик системы. Устанавливается в каждый контейнер через `pip install .`

---

## SSH-подключение для просмотра логов

### Настройка (один раз)

Создать `~/.ssh/config`:

```
Host vps
    HostName <IP-адрес-сервера>
    User root
    Port 22
    IdentityFile ~/.ssh/id_ed25519
```

Публичный ключ добавить на сервер:
```bash
ssh-copy-id vps
# или вручную: echo "ssh-ed25519 AAAA..." >> ~/.ssh/authorized_keys
```

### Смена IP-адреса сервера

При смене хостинга или IP достаточно изменить **одну строку** в `~/.ssh/config`:

```
Host vps
    HostName <НОВЫЙ-IP>    # ← только это
    User root
    Port 22
    IdentityFile ~/.ssh/id_ed25519
```

Все Makefile-команды (`logs-app`, `logs-raw` и т.д.) работают через алиас `vps` — код проекта менять не нужно.

### Команды Makefile

```bash
# Бизнес-логи (только event_type), последние 50 строк
make -C deploy logs-app

# С указанием количества строк
make -C deploy logs-app LINES=30

# Все логи бота (сырые)
make -C deploy logs-raw

# Статус контейнеров
make -C deploy logs-health

# Статус мониторинга (Loki, Promtail, Grafana)
make -C deploy logs-monitor

# 🩺 Самодиагностика
make -C deploy diagnose           # полная диагностика
make -C deploy diagnose-alert     # + алерт в Telegram
make -C deploy diagnose-verbose   # подробный вывод

# ⏰ Авто-диагностика (cron) устанавливается GitHub Actions при деплое
```

### Логи через Grafana

На сервере работает Grafana на порту 3000 (если настроен reverse proxy):
1. Открыть `http://<IP>:3000` (или поддомен)
2. Data Source: Loki
3. Explore → `{container="ticketbot-telegram"} |= "event_type"`

Либо через SSH-туннель:
```bash
ssh -L 3000:localhost:3000 vps
# открыть http://localhost:3000
```
