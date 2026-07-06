# Как работает TicketBot

Этот документ описывает, что происходит при запуске приложения, как взаимодействуют компоненты и по какому пути проходит каждый запрос.

---

## 1. Точка входа: main.py

**Команда запуска:** `python main.py` или `docker compose up -d`

### Последовательность запуска

```
1. main.py
   │
   ├─ Загрузка config из .env
   │
   ├─ init_db()
   │   └─ Создание таблиц (если ещё нет) через metadata.create_all
   │
   ├─ Telegram бот ── если есть TELEGRAM_TOKEN
   │   └─ Запуск polling через aiogram (start_polling)
   │
   ├─ VK бот ── если есть VK_TOKEN
   │   └─ Запуск polling через vkbottle (bot.run())
   │
   └─ MAX бот ── если есть MAX_TOKEN
       └─ Запуск polling через max-bot-api-client-py (run_polling)
```

**Что НЕ запускается, если токен не указан:**

| Платформа | Без токена |
|-----------|-----------|
| Telegram | Бот пропускается, пишется лог: «Telegram бот пропущен: токен не указан» |
| VK | Аналогично |
| MAX | Аналогично |

### Запуск в Docker

При `docker compose up -d`:

```
1. Запускается контейнер db (postgres:16-alpine)
   └─ Healthcheck каждые 5 сек: pg_isready

2. Когда db здоров → запускается app (наш бот)
   └─ wait-for-db: проверяет TCP-доступность PostgreSQL
   └─ main.py:
       ├─ init_db() → создаёт таблицы
       ├─ TelegramBot().run()      (если есть токен)
       ├─ VKPlatformBot().run()    (если есть токен)
       └─ MaxPlatformBot().run()   (если есть токен)

3. seed — запускается только вручную
   └─ docker compose run --rm seed
```

---

## 2. Анатомия запроса: пользователь → ответ

### Пример: пользователь пишет `/events`

```
Telegram                    VK                        MAX
   │                         │                         │
   ├─ aiogram ловит          ├─ vkbottle ловит         ├─ max-bot-api ловит
   │  Command("events")      │  /events или "events"   │  команду "events"
   │                         │                         │
   ▼                         ▼                         ▼
   
   Каждый адаптер делает ОДНО И ТО ЖЕ:
   
   1. Создаёт сессию БД: async_session_factory()
   2. Создаёт сервис: EventService(session)
   3. Вызывает: event_service.list_upcoming()
       └─ SQL: SELECT * FROM events WHERE is_active=true AND date >= NOW()
   4. Форматирует ответ (каждый по-своему)
   5. Отправляет пользователю
   
   Разница — ТОЛЬКО в форматировании:
   ┌─────────────────────┬────────────────────────────┐
   │ Telegram            │ HTML, inline-клавиатуры    │
   │ VK                  │ Простой текст              │
   │ MAX                 │ Простой текст              │
   └─────────────────────┴────────────────────────────┘
```

### Схема потока

```
┌───────┐     /events     ┌────────────────────┐     list_upcoming()    ┌───────────┐
│  TG   │ ──────────────► │  TelegramBot       │ ────────────────────► │           │
│  User │                 │  .cmd_events()      │                      │  Event    │
└───────┘                 └────────────────────┘                      │  Service  │
                                                                      │           │
┌───────┐     /events     ┌────────────────────┐     list_upcoming()   │  SELECT   │
│  VK   │ ──────────────► │  VKPlatformBot     │ ────────────────────► │  FROM     │
│  User │                 │  .cmd_events()      │                      │  events   │
└───────┘                 └────────────────────┘                      │  WHERE…   │
                                                                      │           │
┌───────┐     /events     ┌────────────────────┐     list_upcoming()  └─────┬─────┘
│  MAX  │ ──────────────► │  MaxPlatformBot    │ ────────────────────►      │
│  User │                 │  .cmd_events()      │                           │
└───────┘                 └────────────────────┘                           │
                                                                           ▼
                                                                   ┌───────────┐
                                                                   │PostgreSQL │
                                                                   │  ticketbot │
                                                                   └───────────┘
```

---

## 3. Все команды и что происходит под капотом

### `/start` — Приветствие

```
UserService.get_or_create(platform, platform_user_id, name)
  └─ SELECT FROM users WHERE platform=? AND platform_user_id=?
  └─ Если нет → INSERT нового пользователя
  └─ Вывод: список команд
```

**Проверки:** нет (пользователь создаётся, если новый)

---

### `/events` — Список мероприятий

```
EventService.list_upcoming()
  └─ SQL: SELECT * FROM events
           WHERE is_active = true
             AND date >= NOW()
           ORDER BY date ASC
```

**Проверки:**
- Если мероприятий нет → «Нет предстоящих мероприятий»

---

### `/event <id>` — Детали мероприятия

```
EventService.get_by_id(event_id)
  └─ SQL: SELECT * FROM events WHERE id = ?
```

**Проверки:**
- `id` — валидный UUID? → нет → «Неверный ID»
- Мероприятие найдено? → нет → «Мероприятие не найдено»
- В Telegram — показывается кнопка «🎟 Купить билет»

---

### `/buy <event_id>` — Купить билет

```
TicketService.buy_ticket(user_id, event_id)
  └─ 1. Проверка: мероприятие существует?
  └─ 2. Проверка: мероприятие активно? (is_active)
  └─ 3. Проверка: мероприятие ещё не прошло? (date >= NOW())
  └─ 4. Проверка: есть билеты? (available_tickets > 0)
  └─ 5. Проверка: нет уже активного билета у пользователя?
  └─ 6. Создание Ticket (status = active)
  └─ 7. available_tickets -= 1
  └─ 8. Создание Payment (status = completed — заглушка)
  └─ 9. Если любая проверка не прошла → ValueError
```

**Проверки (все обязательны):**

| № | Проверка | Ошибка |
|:-:|----------|--------|
| 1 | Мероприятие найдено | «Мероприятие не найдено» |
| 2 | is_active = true | «Мероприятие неактивно» |
| 3 | date >= now() | «Мероприятие уже прошло» |
| 4 | available_tickets > 0 | «Билеты закончились» |
| 5 | Нет активного билета у user + event | «У вас уже есть активный билет» |

---

### `/my_tickets` — Мои билеты

```
TicketService.get_user_tickets(user_id)
  └─ SQL: SELECT ticket.*, event.title
           FROM tickets
           JOIN events ON tickets.event_id = events.id
           WHERE tickets.user_id = ?
           ORDER BY purchase_date DESC
```

**Проверки:**
- Если билетов нет → «У вас нет билетов»

---

### `/cancel <ticket_id>` — Отменить билет

```
TicketService.cancel_ticket(ticket_id, user_id)
  └─ 1. Проверка: билет существует?
  └─ 2. Проверка: билет принадлежит пользователю?
  └─ 3. Проверка: билет ещё не возвращён?
  └─ 4. ticket.status → refunded
  └─ 5. event.available_tickets += 1
  └─ 6. payment.status → refunded
```

**Проверки:**

| № | Проверка | Ошибка |
|:-:|----------|--------|
| 1 | Билет найден | «Билет не найден» |
| 2 | user_id совпадает | «Это не ваш билет» |
| 3 | status != refunded | «Билет уже возвращён» |

---

## 4. Что живёт в памяти

### Постоянные процессы (после запуска)

```
System process tree:
  ├─ init (PID 1 — в Docker это процесс Python)
  │   ├─ main.py (Python)
  │   │   ├─ Telegram polling (aiogram)
  │   │   ├─ VK polling (vkbottle)
  │   │   └─ MAX polling (max-bot-api)
  │   └─ postgres (в отдельном контейнере)
```

- **Polling-цикл Telegram:** aiogram бесконечно опрашивает API Telegram (getUpdates) каждые ~1 сек
- **Polling-цикл VK:** vkbottle делает то же самое через LongPoll
- **Polling-цикл MAX:** max-bot-api-client-py аналогично
- **PostgreSQL:** висит, ждёт запросы на порту 5432

### Расход RAM

| Компонент | RAM |
|-----------|:---:|
| PostgreSQL (в Docker) | ~50–200 MB |
| Python bot (aiogram) | ~30–60 MB |
| Python bot (vkbottle) | ~30–60 MB |
| Python bot (max) | ~30–60 MB |
| **Итого** | **~150–400 MB** (без нагрузки) |

---

## 5. Что НЕ работает (заглушки)

| Функция | Статус | Почему |
|---------|:------:|--------|
| **Оплата** | 🟡 Заглушка | Payment создаётся со status=completed сразу |
| **Выбор места** | ❌ Не реализовано | Места не предусмотрены моделью |
| **Скидочные купоны** | ❌ Не реализовано | Нет кода для купонов |
| **Уведомления** | ❌ Не реализовано | Нет отправки email/push |
| **MAX Bot** | 🟡 Требуется токен | MAX может быть недоступен для создания ботов |

---

## 6. Жизненный цикл контейнеров (Docker)

```
docker compose up -d
   │
   ├── db → postgres:16-alpine
   │     └─ Состояние: running
   │     └─ Перезапуск: unless-stopped (восстанавливается при падении)
   │     └─ Данные: том pgdata (живут при перезапуске контейнера)
   │
   └── app → наш образ
         └─ Состояние: running (ждёт команды)
         └─ Перезапуск: always (восстанавливается при падении)
         └─ Код: вшит в образ (read-only)

docker compose down
   └─ Контейнеры останавливаются
   └─ Том pgdata сохраняется

docker compose down -v
   └─ Контейнеры + том pgdata удаляются (БД стёрта)
```

---

## 7. Важные файлы

| Файл | Роль |
|------|------|
| `main.py` | Точка входа, запуск всех ботов |
| `config.py` | Чтение .env через pydantic-settings |
| `core/database.py` | async engine, сессии, init_db |
| `core/models.py` | ORM-модели (5 таблиц) |
| `core/services.py` | Бизнес-логика (UserService, EventService, TicketService) |
| `core/schemas.py` | Pydantic-схемы для API |
| `platforms/telegram/bot.py` | Telegram адаптер (aiogram) |
| `platforms/vk/bot.py` | VK адаптер (vkbottle) |
| `platforms/max/bot.py` | MAX адаптер (max-bot-api) |
| `platforms/base.py` | Абстрактный класс PlatformBot |

---

## 8. Краткая памятка

```
┌────────────────────────────────────────────────────────────┐
│  Пользователь пишет /events                               │
│                                                           │
│  1. Платформа (TG/VK/MAX) получает сообщение              │
│  2. Хендлер парсит команду                                │
│  3. Создаётся сессия БД                                   │
│  4. Вызывается EventService.list_upcoming()                │
│  5. Сервис шлёт SELECT в PostgreSQL                        │
│  6. Результат возвращается в хендлер                       │
│  7. Хендлер форматирует ответ (HTML / текст)              │
│  8. Ответ отправляется пользователю                       │
│  9. Сессия БД закрывается                                 │
│                                                           │
│  ВСЁ. Весь путь занимает 10-50 мс.                        │
└────────────────────────────────────────────────────────────┘
```
