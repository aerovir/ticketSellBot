# Как работает TicketBot

Этот документ описывает, что происходит при запуске приложения, как взаимодействуют компоненты и по какому пути проходит каждый запрос.

---

## 1. Точка входа: main.py (или run_telegram.py / run_vk.py / run_max.py)

**Команда запуска:**
- `python main.py` — запускает всех ботов, для которых есть токены
- `python run_telegram.py` — только Telegram
- `python run_vk.py` — только VK
- `python run_max.py` — только MAX (заглушка)

Или через Docker:
- `docker compose up -d` — запускает app + db
- `docker compose --profile standalone up -d telegram` — только Telegram бот
- `docker compose --profile standalone up -d vk` — только VK бот


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

## 1.1 Telegram канал для анонсов

Бот работает по схеме **Вариант А**:
- **Канал** — только анонсы и просмотр (команды `/events`, `/event <id>`)
- **Личные сообщения** — покупка билетов и управление

### Последовательность отправки анонса в канал

```
seed.py / админ-панель
    │
    ├─ EventService.create_event()
    │   └─ INSERT в events
    │
    └─ ChannelManager.post_event_announcement(event)
        │
        ├─ Формирует HTML: название, дата, место, цена
        ├─ bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, ...)
        └─ Результат:
            ┌──────────────────────────────────────┐
            │  🎫 Рок-концерт                       │
            │                                      │
            │  Грандиозный концерт с лучшими        │
            │  рок-хитами в исполнении оркестра.    │
            │                                      │
            │  📅 21.07.2026 19:00                  │
            │  📍 Москва, Крокус Сити Холл          │
            │  💰 2500₽                             │
            │                                      │
            │  👇 Купить в личных сообщениях:       │
            │  @bot /buy <id>                       │
            └──────────────────────────────────────┘
```

### Что происходит при команде в канале

```
Пользователь пишет /events в канале (не боту, а в чат канала)
    │
    ├─ aiogram получает channel_post (не message!)
    ├─ Хендлер channel_cmd_events()
    ├─ EventService.list_upcoming()
    └─ channel_post.answer() → ответ пишется прямо в канал
```

### Какие команды работают в канале, какие — только в личке

#### 📢 В канале (только просмотр)
| Команда | Описание |
|---------|----------|
| `/events` | Список предстоящих мероприятий |
| `/event <id>` | Детали мероприятия |

Покупка билетов в канале недоступна — только просмотр.

#### 💬 В личных сообщениях бота
| Команда | Описание |
|---------|----------|
| `/start` | Приветствие + список команд |
| `/events` | Список предстоящих мероприятий |
| `/event <id>` | Детали + кнопка «Купить билет» |
| `/buy <id>` | Купить билет на мероприятие |
| `/my_tickets` | Мои купленные билеты |
| `/cancel <id>` | Отменить билет (возврат) |

#### 🔐 В личных сообщениях (только администратор)
| Команда | Описание |
|---------|----------|
| `/admin` | Меню администратора |
| `/create_event` | Создать новое мероприятие |
| `/events_all` | Все мероприятия (вкл. неактивные) |
| `/stats <id>` | Статистика продаж |
| `/deactivate <id>` | Отключить мероприятие |
| `/activate <id>` | Включить мероприятие |

### ChannelManager

Класс `ChannelManager` (файл `platforms/telegram/channel.py`) отвечает за:

- `post_event_announcement(event)` — отправить анонс мероприятия в канал
- `post_events_list(events)` — отправить список всех мероприятий
- Ничего не делает, если `TELEGRAM_CHANNEL_ID` не настроен (безопасный пропуск)

### Требования для работы канала

1. Бот добавлен в канал как **администратор** (права: отправлять + читать)
2. В BotFather отключён **Privacy Mode**
3. В `config.py` или `.env` указан `TELEGRAM_CHANNEL_ID`

---

## 1.2 Админ-панель (управление мероприятиями)

Администраторы определяются через `ADMIN_TELEGRAM_IDS` в `.env` — список Telegram ID через запятую.

**Без миграций БД** — никаких изменений в схеме, только проверка `user_id ∈ admin_telegram_ids`.

### Команды админ-панели

| Команда | Описание | Доступ |
|---------|----------|:------:|
| `/admin` | Меню администратора | ❌ |
| `/create_event` | Пошаговое создание мероприятия (FSM) | ❌ |
| `/events_all` | Все мероприятия (вкл. неактивные/прошедшие) | ❌ |
| `/stats <id>` | Статистика продаж | ❌ |
| `/deactivate <id>` | Отключить мероприятие | ❌ |
| `/activate <id>` | Включить мероприятие | ❌ |

Обычным пользователям на все админ-команды отвечаем: «У вас нет доступа к панели администратора.»

### FSM: создание мероприятия (`/create_event`)

```
1. /create_event
   │
   ├─ 1. Название ──────────────────────────► admin_create_event()
   │   └─ строка
   │
   ├─ 2. Описание ──────────────────────────► fsm_title()
   │   └─ строка или "-" (пропустить)
   │
   ├─ 3. Дата ──────────────────────────────► fsm_description()
   │   └─ "ДД.ММ.ГГГГ ЧЧ:ММ" (парсится strptime)
   │
   ├─ 4. Место ─────────────────────────────► fsm_date()
   │   └─ строка или "-" (пропустить)
   │
   ├─ 5. Цена ──────────────────────────────► fsm_location()
   │   └─ число (float), 0 = бесплатно
   │
   ├─ 6. Количество билетов ────────────────► fsm_price()
   │   └─ целое > 0
   │
   ├─ 7. Сводка + кнопки ───────────────────► fsm_tickets()
   │   └─ ✅ Подтвердить / ❌ Отмена
   │
   ├─ ✅ Подтвердить ───────────────────────► callback: admin:confirm_create
   │   ├─ EventService.create()
   │   ├─ post_announcement() — анонс в канал
   │   └─ state.clear()
   │
   └─ ❌ Отмена ────────────────────────────► callback: admin:cancel_create
       └─ state.clear()
```

Отмена на любом шаге: `/cancel` срабатывает только в состоянии FSM (StateFilter).

### Статистика `/stats <id>`

```
EventService.get_event_stats(id)
  └─ SELECT count(*) FROM tickets WHERE event_id=? AND status='active'
  └─ SELECT count(*) FROM tickets WHERE event_id=? AND status='refunded'
  └─ Расчёт:
       ├─ sold_pct = sold / total_tickets * 100
       └─ revenue = sold * price
```

### Активация / деактивация

```
EventService.set_active(id, is_active)
  └─ UPDATE events SET is_active=? WHERE id=?
  └─ Без изменения билетов — мероприятие просто скрывается из /events
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
| **VK Bot** | ⏸️ Отключён | Код готов, ждёт настройки группы и токена |
| **MAX Bot** | ⏸️ Заглушка | Ждёт выхода/доступа к max-bot-api-client-py |
| **Выбор места** | ❌ Не реализовано | Места не предусмотрены моделью |
| **Скидочные купоны** | ❌ Не реализовано | Нет кода для купонов |
| **Уведомления** | ❌ Не реализовано | Нет отправки push/email до мероприятия |

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
| `main.py` | Запуск всех ботов по токенам |
| `run_telegram.py` | Запуск только Telegram бота |
| `run_vk.py` | Запуск только VK бота |
| `run_max.py` | Запуск только MAX бота (заглушка) |
| `config.py` | Чтение .env через pydantic-settings |
| `core/database.py` | async engine, сессии, init_db |
| `core/models.py` | ORM-модели (5 таблиц) |
| `core/services.py` | Бизнес-логика (UserService, EventService, TicketService) |
| `core/schemas.py` | Pydantic-схемы для API |
| `platforms/telegram/bot.py` | Telegram адаптер (aiogram) |
| `platforms/telegram/channel.py` | Менеджер анонсов в Telegram канал |
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
