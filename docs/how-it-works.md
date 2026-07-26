# Как работает TicketBot

Этот документ описывает архитектуру после перехода на раздельные процессы для каждой платформы.

---

## 1. Архитектура: независимые процессы

Каждая платформа запускается в **отдельном Python-процессе / Docker-контейнере**:

```
  ┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
  │  ticketbot-telegram  │    │   ticketbot-vk      │    │   ticketbot-max     │
  │  python -m bot.telegram │ │  python -m bot.vk   │    │  python -m bot.max  │
  │  aiogram 3.x         │    │  vkbottle 4.x       │    │  max-bot-api        │
  │  tg_user → PostgreSQL │   │  vk_user → PG       │    │  max_user → PG      │
  └──────────┬──────────┘    └──────────┬──────────┘    └──────────┬──────────┘
             │                          │                          │
             └──────────────────────────┼──────────────────────────┘
                                        ▼
                              ┌─────────────────────┐
                              │  PostgreSQL          │
                              │  ticketbot (общая)    │
                              │  tg_user / vk_user    │
                              │  / max_user          │
                              └─────────────────────┘
```

### Точка входа

| Платформа | Команда | Файл |
|-----------|---------|------|
| Telegram | `python -m bot.telegram` | `app/bot/telegram.py` |
| VK | `python -m bot.vk` | `app/bot/vk.py` |
| MAX | `python -m bot.max` | `app/bot/max.py` |

### Docker

| Команда | Что запускается |
|---------|----------------|
| `docker compose up -d` | PostgreSQL + Telegram бот |
| `docker compose --profile all up -d` | + VK + MAX |
| `docker compose run --rm seed` | Тестовые мероприятия |

---

## 2. База данных: одна БД, три роли

Единая база `ticketbot`, но каждая платформа подключается под своей ролью PostgreSQL:

| Роль | Платформа | Права |
|------|-----------|-------|
| `postgres` | Миграции / seed | Все права (CREATE TABLE, DROP и т.д.) |
| `tg_user` | Telegram | SELECT, INSERT, UPDATE |
| `vk_user` | VK | SELECT, INSERT, UPDATE |
| `max_user` | MAX | SELECT, INSERT, UPDATE |

Ограничения ролей:
- **Нет права DROP/ALTER** — платформы не меняют схему
- **Нет права DELETE** (опционально) — мягкое удаление через поля `is_active`/`status`
- Каждая платформа работает только со своими данными через `platform`-поле в таблице `users`

Скрипт создания ролей: `scripts/init-db-roles.sh`

---

## 3. Последовательность запуска

```
1. docker compose up -d telegram (или python -m bot.telegram)
   │
   ├─ Загрузка config из .env.telegram
   │  └─ DATABASE_URL = postgresql+asyncpg://tg_user:...@db:5432/ticketbot
   │
   ├─ init_db() — создание таблиц (если ещё нет)
   │  └─ Base.metadata.create_all
   │
   ├─ TelegramBot()
   │  ├─ Bot(token=TELEGRAM_TOKEN)
   │  ├─ Dispatcher(storage=MemoryStorage())
   │  └─ _register_handlers() — регистрация всех хендлеров
   │
   ├─ bot.run() — start_polling (с ретраями при ошибках)
   │
   └─ Ctrl+C → bot.stop() → close_db()

2. docker compose --profile all up -d vk — аналогично, но с .env.vk
3. docker compose --profile all up -d max — аналогично, но с .env.max
```

---

## 4. Анатомия запроса

```
Пользователь          Платформа                БД
   │                     │                     │
   ├─ /events ──────────►                       │
   │                     ├─ Создание сессии      │
   │                     ├─ EventService         │
   │                     │  .list_upcoming() ───►│
   │                     │◄─ events список ──────┤
   │                     ├─ Форматирование        │
   │◄─ ответ ────────────┤                     │
   │                     └─ Сессия закрыта      │
```

Разница между платформами — **только в форматировании ответа**:
- Telegram: HTML, inline-клавиатуры, канал
- VK: Простой текст
- MAX: Простой текст

---

## 5. Жизненный цикл контейнеров

```
docker compose up -d
   │
   ├── db ─── postgres:16-alpine (running)
   ├── telegram ─── python -m bot.telegram (running)
   │                └─ profile: "" (default)
   ├── vk ─── python -m bot.vk (остановлен, profile: all)
   └── max ─── python -m bot.max (остановлен, profile: all)

docker compose --profile all up -d
   └── + vk, max запускаются

docker compose down
   └── Все контейнеры остановлены, pgdata сохранена
```

---

## 6. Изоляция сбоев

```
🔥 Telegram крашнулся (ошибка в хендлере):
   └─ Контейнер ticketbot-telegram перезапускается
   └─ VK и MAX продолжают работать

🔥 VK упал (потеря соединения):
   └─ ticketbot-vk делает retry (до 10 попыток)
   └─ Telegram и MAX не затронуты

🔥 PostgreSQL недоступен:
   └─ Все контейнеры ждут healthcheck
   └─ retry-цикл в каждом entry point
```

---

## 7. Важные файлы

| Файл | Роль |
|------|------|
| `app/bot/telegram.py` | Entry point Telegram |
| `app/bot/vk.py` | Entry point VK |
| `app/bot/max.py` | Entry point MAX |
| `app/platforms/telegram/bot.py` | Telegram адаптер (aiogram) |
| `app/platforms/vk/bot.py` | VK адаптер (vkbottle) |
| `app/platforms/max/bot.py` | MAX адаптер (max-bot-api) |
| `app/platforms/base.py` | Абстрактный класс PlatformBot |
| `app/config.py` | Чтение .env через pydantic-settings |
| `app/core/database.py` | async engine, сессии, init_db |
| `app/core/models.py` | ORM-модели (5 таблиц) |
| `app/core/services.py` | Бизнес-логика |
| `scripts/init-db-roles.sh` | Создание ролей PostgreSQL |
| `scripts/healthcheck.py` | Healthcheck всех платформ |

---

## 8. Расход RAM

| Компонент | RAM |
|-----------|:---:|
| PostgreSQL (Docker) | ~50–200 MB |
| Telegram бот (aiogram) | ~30–60 MB |
| VK бот (vkbottle) | ~30–60 MB |
| MAX бот (max-bot-api) | ~30–60 MB |
| **Итого (все платформы)** | **~140–380 MB** |
| **Только Telegram** | **~80–260 MB** |

---

## 9. Билеты и валидация на входе

### Уровни подписки

Подписка канала имеет уровень (tier):

| Tier | Фичи |
|------|------|
| `basic` | Бесплатные мероприятия, короткий код на вход |
| `pro` | Платные мероприятия, короткий код + QR, промокоды |

Активация: `/subscribe @channel 30 basic` или `/subscribe @channel 30 pro`.

Тариф проверяется при создании мероприятия — если канал basic, price не может быть > 0.

### Бесплатные мероприятия

1. Пользователь нажимает «🎟 Получить билет» на анонсе
2. Создаётся билет с уникальным кодом формата `AB3X-K7M9` (8 hex-символов)
3. Код показывается пользователю в алерте и в /my_tickets
4. На входе админ вводит: `/check AB3X-K7M9`
5. Бот отвечает:
   - ✅ Иван И., мероприятие «Лекция», 19:35 UTC — если билет действителен
   - 🟡 Уже использован, первый вход 19:30 — если уже чекинился
   - ❌ Билет с кодом XXXX-XXXX не найден — если код неверный

### Платные мероприятия (Pro)

Всё то же +:
- При покупке генерируется QR-код
- Планируется: Mini App сканер QR для админа (встроенный Telegram QR scanner)
- Планируется: более 2 типов билетов, промокоды, экспорт CSV

### Жизненный цикл билета

```
active → checked_in (на входе) → конец
active → refunded (возврат)
```

### Новые event_type в логах

| event_type | Когда |
|---|----|
| `ticket.validate` | Проверка билета по коду |
| `ticket.checked_in` | Успешный вход |
| `ticket.checkin_failed` | Ошибка входа |
