# 🎫 TicketBot

Кроссплатформенный бот для продажи билетов на мероприятия.

Работает одновременно в **трёх мессенджерах/соцсетях**:

| Платформа | Библиотека | Статус |
|-----------|-----------|--------|
| **Telegram** | aiogram 3.x | ✅ Работает |
| **ВКонтакте** | vkbottle | ✅ Работает |
| **MAX** (max.ru) | max-bot-api-client-py | 🟡 Требуется токен |

---

## 📦 Функционал (MVP)

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и список доступных команд |
| `/events` | Список предстоящих мероприятий |
| `/event <id>` | Детальная информация о мероприятии |
| `/buy <id>` | Купить билет на мероприятие |
| `/my_tickets` | Мои купленные билеты |
| `/cancel <id>` | Отменить билет (возврат) |

**Что умеет бот:**
- ✅ Просматривать список предстоящих мероприятий
- ✅ Смотреть детали мероприятия (дата, место, цена, остаток билетов)
- ✅ Покупать билет (автоматически проверяет наличие, не даёт купить второй на то же событие)
- ✅ Просматривать свои билеты
- ✅ Отменять билет с восстановлением места
- ✅ Запоминать пользователей (авторегистрация при первом обращении)
- 🟡 Заглушка оплаты (билет сразу считается оплаченным)

---

## 🏗 Архитектура

```
┌───────────────────────────────────────────────┐
│                   main.py                      │  — точка входа
│         asyncio.gather — запуск всех ботов       │
├───────────────────────────────────────────────┤
│  platforms/telegram/  vk/  max/               │  — адаптеры платформ
│  «тонкие» — только форматирование и вызов сервисов│
├───────────────────────────────────────────────┤
│               core/services.py                 │  — бизнес-логика
│     UserService · EventService · TicketService   │
├───────────────────────────────────────────────┤
│          core/models.py · database.py          │  — ORM + БД
│    SQLAlchemy async + PostgreSQL (asyncpg)     │
└───────────────────────────────────────────────┘
```

**Ключевой принцип:** вся бизнес-логика находится **только** в `core/services.py`. Адаптеры платформ не содержат логики — они только форматируют ответы и вызывают сервисы. Это позволяет:

- Добавлять новые платформы, не меняя логику
- Менять правила покупки/возврата в одном месте
- Легко тестировать бизнес-логику без ботов

---

## 🗄 База данных

**PostgreSQL** с асинхронным драйвером asyncpg. ORM — SQLAlchemy 2.0 (asyncio).

### Схема данных

```mermaid
erDiagram
    User ||--o{ Ticket : has
    Event ||--o{ Ticket : contains
    Ticket ||--|| Payment : pays

    User {
        uuid id PK
        enum platform "telegram | vk | max"
        string platform_user_id
        string name
        datetime created_at
    }
    Event {
        uuid id PK
        string title
        text description
        datetime date
        string location
        float price
        int total_tickets
        int available_tickets
        bool is_active
        datetime created_at
    }
    Ticket {
        uuid id PK
        uuid event_id FK
        uuid user_id FK
        datetime purchase_date
        enum status "active | refunded"
    }
    Payment {
        uuid id PK
        uuid ticket_id FK
        float amount
        enum status "pending | completed | failed | refunded"
        datetime created_at
    }
```

### Статусы билетов

| Статус | Значение |
|--------|---------|
| `active` | Билет активен |
| `refunded` | Билет возвращён |

### Статусы платежей

| Статус | Значение |
|--------|---------|
| `pending` | Ожидает оплаты |
| `completed` | Оплачен |
| `failed` | Ошибка оплаты |
| `refunded` | Возвращён |

---

---

## 🐳 Быстрый старт с Docker

### Требования

- **Docker** ≥ 24.0
- **Docker Compose** ≥ 2.20

### 1. Настроить токены

```bash
cp .env.example .env
# Отредактируйте .env — вставьте токены ботов
```

### 2. Запустить

```bash
# Запустить PostgreSQL + бота
docker compose up -d

# Залить тестовые мероприятия (однократно)
docker compose run --rm --profile seed seed
```

Всё! Бот работает, слушает команды на всех платформах, для которых указаны токены.

### Другие команды

```bash
# Посмотреть логи
docker compose logs -f app

# Остановить
docker compose down

# Остановить и удалить БД (все данные пропадут)
docker compose down -v
```

### Переменные окружения

Все переменные из `.env` автоматически подхватываются `docker compose`. Можно также передавать их явно:

```bash
TELEGRAM_TOKEN=123:abc docker compose up -d
```

---

## 🟢 Развёртывание на Beget

Beget — российский хостинг с посуточной оплатой. **Идеально для тестирования бота.**

### Тариф

| Параметр | Значение |
|----------|---------|
| **vCPU** | 1 ядро |
| **RAM** | 2 GB |
| **Диск** | 15 GB NVMe |
| **Цена** | **~17 ₽/день** (≈510 ₽/мес) |
| **Docker** | ✅ Поддерживается |

### Заказ VPS

1. Зайдите в [beget.com → VPS](https://beget.com/ru/vps)
2. Выберите тариф: **1 vCPU, 2 GB RAM, 15 GB NVMe** (Ubuntu 24.04, с Docker)
3. Оплатите посуточно (первый день — 17 ₽)
4. После создания — скопируйте **IP-адрес**, **логин** и **пароль** из панели

### Быстрый деплой (автоматический скрипт)

```bash
# Подключиться к серверу по SSH
ssh root@<IP-адрес-сервера>

# Скопировать и запустить скрипт настройки
# (предварительно — скопируйте файлы проекта на сервер)
```

На сервере выполните:

```bash
# Установить docker если нет
curl -fsSL https://get.docker.com | sh

# Скопировать проект на сервер (с локальной машины)
# scp -r /путь/к/ticketBot user@server:/opt/ticketbot

# Зайти в проект и запустить
cd /opt/ticketbot

# Настроить .env
cp .env.example .env
nano .env   # ← вставить TELEGRAM_TOKEN

# Запустить с оптимизацией под Beget
docker compose -f docker-compose.yml -f deploy/docker-compose.beget.yml up -d

# Создать таблицы
docker compose run --rm app python -c \
  "import asyncio; from app.core.database import init_db; asyncio.run(init_db())"

# Залить тестовые данные
docker compose run --rm seed

# Проверить логи
docker compose logs -f app
```

### Управление

```bash
# Через Makefile (запуск из корня проекта)
make -C deploy up-beget       # запустить
make -C deploy logs-beget     # логи
make -C deploy down-beget     # остановить
make -C deploy seed           # тестовые данные

# Остановить VPS чтобы не тратить деньги
# beget.com → панель управления → выключить сервер
```

### Важно для Beget

| Совет | Почему |
|-------|--------|
| ⚡ **Останавливайте VPS**, когда не тестируете | Иначе 17 ₽/день × 30 = 510 ₽/мес |
| 💾 PostgreSQL оптимизирован под 2 GB RAM | `docker-compose.beget.yml` — уже настроен |
| 🔄 При перезапуске VPS — контейнеры стартуют автоматически | `restart: always` в конфиге |
| 📦 NVMe 15 GB — достаточно для БД, логов и Docker-образов | Но следите за `docker system df` |

---

### Запуск только Telegram (без VK и MAX)

```bash
docker compose run --rm -e TELEGRAM_TOKEN=123:abc app python -c "
import asyncio
from platforms.telegram.bot import TelegramBot
asyncio.run(TelegramBot().run())
"
```

---

## ⚙️ Установка и запуск (без Docker)

### 1. Клонировать репозиторий

```bash
git clone <url-репозитория>
cd ticketBot
```

### 2. Установить зависимости

```bash
pip install -e .
```

Состав зависимостей:

| Пакет | Версия | Назначение |
|-------|--------|-----------|
| `sqlalchemy[asyncio]` | >=2.0 | ORM |
| `asyncpg` | >=0.29 | Асинхронный драйвер PostgreSQL |
| `pydantic` | >=2.0 | Валидация данных |
| `pydantic-settings` | >=2.0 | Настройки из .env |
| `python-dotenv` | >=1.0 | Загрузка .env |
| `aiogram` | >=3.0 | Telegram Bot API |
| `vkbottle` | >=5.0 | VK Bot API |
| `alembic` | >=1.13 | Миграции БД |

Для MAX дополнительно:
```bash
pip install max-bot-api-client-py
```

### 3. Настроить окружение

```bash
cp .env.example .env
```

Отредактируйте `.env`:

```ini
# База данных
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/ticketbot

# Telegram (получить у BotFather)
TELEGRAM_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11

# ВКонтакте (токен сообщества)
VK_TOKEN=vk1.a.xxxxx
VK_GROUP_ID=123456789

# MAX (получить у @MasterBot)
MAX_TOKEN=your_max_bot_token

# Режим отладки
DEBUG=false
```

### 4. Развернуть базу данных

Убедитесь, что PostgreSQL запущен:

```bash
# Создать базу данных
createdb ticketbot

# Применить миграции
alembic upgrade head

# Либо быстрый старт (создание таблиц через metadata.create_all)
python -c "import asyncio; from app.core.database import init_db; asyncio.run(init_db())"
```

### 5. Залить тестовые мероприятия

```bash
python -m bot.seed
```

Будут созданы 6 мероприятий:

| Название | Дата | Город | Цена | Билетов |
|----------|------|-------|------|---------|
| Концерт «Рок-хиты» | +14 дней | Москва | 2500₽ | 500 |
| Stand-up вечер | +7 дней | Санкт-Петербург | 1500₽ | 200 |
| Театральная премьера: «Гамлет» | +21 день | Казань | 1800₽ | 300 |
| Фестиваль электронной музыки | +30 дней | Екатеринбург | 3500₽ | 1000 |
| Мастер-класс по фотографии | +5 дней | Москва | 2000₽ | 50 |
| Спектакль «Три сестры» | +45 дней | Новосибирск | 1200₽ | 400 |

### 6. Запустить бота

```bash
python -m bot.launcher
```

Бот запустится на всех платформах, для которых указаны токены. Если токен для платформы не указан — она пропускается.

---

## 📁 Структура проекта

```
ticketBot/
├── app/                             # Весь Python-код (пакет, PYTHONPATH=/app)
│   ├── config.py                    # Настройки из .env (pydantic-settings)
│   ├── core/                        # Ядро
│   │   ├── database.py              # Асинхронный SQLAlchemy engine и сессии
│   │   ├── models.py                # ORM-модели (User, Event, Ticket, Payment)
│   │   ├── schemas.py               # Pydantic-схемы
│   │   └── services.py              # Бизнес-логика
│   ├── platforms/                   # Адаптеры платформ
│   │   ├── base.py                  # Базовый класс PlatformBot
│   │   ├── telegram/
│   │   │   ├── bot.py               # Telegram бот (aiogram)
│   │   │   └── channel.py           # Анонсы в Telegram канал
│   │   ├── vk/
│   │   │   └── bot.py               # VK бот (vkbottle)
│   │   └── max/
│   │       └── bot.py               # MAX бот (max-bot-api-client-py, заглушка)
│   └── bot/                         # Entry points (python -m bot.xxx)
│       ├── launcher.py              # Запуск всех ботов
│       ├── telegram.py              # Только Telegram
│       ├── vk.py                    # Только VK
│       ├── max.py                   # Только MAX
│       └── seed.py                  # Тестовые мероприятия
├── scripts/                         # Вспомогательные скрипты
│   ├── healthcheck.py
│   └── cron-healthcheck.py
├── tests/                           # Тесты (pytest)
├── deploy/                          # DevOps
├── docs/                            # Документация
├── migrations/                      # Alembic
├── pyproject.toml                   # Зависимости и метаданные
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── .env.example
└── README.md
```

---

## 🧠 Как это работает

### Поток покупки билета

```
Пользователь → /buy 1

  1. Парсинг аргументов → ID мероприятия
  2. _get_user_id → регистрация пользователя, если новый
  3. TicketService.buy_ticket(user_id, event_id)
       └─ Проверки:
            ├── Мероприятие существует?       → ValueError
            ├── Мероприятие активно?          → ValueError
            ├── Мероприятие ещё не прошло?    → ValueError
            ├── Есть свободные билеты?        → ValueError
            └── Нет уже активного билета?     → ValueError
       └─ Создание Ticket (status=active)
       └─ Уменьшение available_tickets--
       └─ Создание Payment (status=completed — заглушка)
  4. Ответ пользователю → "✅ Билет куплен!"
```

### Поток отмены билета

```
Пользователь → /cancel <ticket_id>

  1. TicketService.cancel_ticket(ticket_id, user_id)
       └─ Проверки:
            ├── Билет существует?             → ValueError
            ├── Это билет пользователя?       → ValueError
            └── Билет ещё не возвращён?       → ValueError
       └─ Статус билета → refunded
       └─ available_tickets++
       └─ Статус платежа → refunded
  2. Ответ пользователю → "✅ Билет возвращён"
```

---

## 🐘 Платформы

### Telegram

- Использует **aiogram 3.x**
- Inline-клавиатура: на деталях мероприятия есть кнопка «🎟 Купить билет»
- HTML-форматирование сообщений
- Токен получить: [@BotFather](https://t.me/BotFather)

### ВКонтакте

- Использует **vkbottle**
- Все команды доступны как через `/команда`, так и текстом
- Токен получить: в настройках сообщества → Работа с API → Создать токен

### MAX (max.ru)

- Использует **max-bot-api-client-py** (официальный Python SDK)
- MAX — российский защищённый мессенджер от VK Group
- Токен получить: через бота **@MasterBot** в MAX
- Документация API: [dev.max.ru/docs-api](https://dev.max.ru/docs-api)
- ⚠️ На момент разработки создание ботов может быть недоступно

---

## 🧪 Разработка

### Добавление новой платформы

1. Создать `app/platforms/new_platform/bot.py`
2. Реализовать класс, унаследованный от `PlatformBot`:
   - `__init__` — создать клиента платформы и зарегистрировать хендлеры
   - `run()` — запустить polling
   - `stop()` — остановить бота
3. В хендлерах вызывать сервисы из `app.core.services`
4. Создать `app/bot/new_platform.py` по шаблону `app/bot/telegram.py`
5. Добавить в `app/bot/launcher.py` импорт и проверку токена

Пример скелета адаптера:

```python
from app.platforms.base import PlatformBot

class MyPlatformBot(PlatformBot):
    async def run(self):
        # Запустить polling / webhook
        ...

    async def stop(self):
        # Остановить клиент
        ...
```

### Добавление новой команды

1. В `core/services.py` — добавить метод в соответствующий сервис
2. В каждом `platforms/*/bot.py` — добавить хендлер и зарегистрировать его

### Миграции БД

```bash
# Создать новую миграцию (авто)
alembic revision --autogenerate -m "описание"

# Применить миграции
alembic upgrade head

# Откатить на шаг
alembic downgrade -1
```

---

## 🔄 Дорожная карта

- [x] MVP: базовая архитектура core + 3 платформы
- [x] Покупка и отмена билетов
- [x] Управление пользователями
- [ ] Настоящая платёжная интеграция (ЮKassa, Stripe)
- [ ] Выбор места на мероприятии
- [ ] Скидочные купоны
- [ ] Роли (админ, организатор)
- [ ] Админ-панель для создания мероприятий
- [ ] Email-уведомления
- [ ] Статистика продаж

---

## 📄 Лицензия

MIT
