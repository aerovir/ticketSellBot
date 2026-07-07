# TicketBot

Мультиплатформенный бот для продажи билетов на мероприятия.

**Платформы:** Telegram ✅ (работает), VK ⏸️ (код готов, отключён), MAX ⏸️ (заглушка).

---

## Быстрый старт

```bash
# 1. Настройка .env
cp .env.example .env
# заполнить TELEGRAM_TOKEN от @BotFather

# 2. Запуск через Docker (все сразу)
docker compose up -d

# 3. Или только Telegram:
docker compose --profile standalone up -d telegram

# 4. Накатить тестовые данные:
docker compose run --rm seed
```

---

## Telegram канал для анонсов

Бот работает по схеме **Вариант А**:
- **Канал** — только анонсы мероприятий + команды `/events` и `/event <id>` (просмотр)
- **Личные сообщения** — покупка `/buy`, просмотр `/my_tickets`, отмена `/cancel`

### Настройка канала

1. Создать Telegram канал (приватный или публичный)
2. Добавить бота в канал как **администратора** с правами:
   - ✅ Отправлять сообщения
   - ✅ Читать сообщения
3. Отключить Privacy Mode в BotFather:
   ```
   @BotFather → /mybots → Bot → Bot Settings → Group Privacy → Turn off
   ```
4. Указать `TELEGRAM_CHANNEL_ID` в секретах GitHub (например `@my_channel`)
5. При деплое бот будет постить анонсы в канал автоматически

### Что умеет бот в канале

| Команда | Описание |
|---------|----------|
| `/events` | Список предстоящих мероприятий |
| `/event <id>` | Детали мероприятия |

Покупка — только в личных сообщениях с ботом.

---

## Архитектура

```
├── run_telegram.py     # Entry point: только Telegram
├── run_vk.py           # Entry point: только VK
├── run_max.py          # Entry point: только MAX (заглушка)
├── main.py             # Лаунчер — запускает всех ботов по токенам
│
├── core/               # Бизнес-логика (общая для всех платформ)
│   ├── models.py       # SQLAlchemy: User, Event, Ticket, Payment
│   ├── database.py     # Асинхронный движок + фабрика сессий
│   ├── services.py     # UserService, EventService, TicketService
│   └── schemas.py      # Pydantic схемы
│
├── platforms/          # Адаптеры платформ
│   ├── base.py         # Abstract base class PlatformBot
│   ├── telegram/bot.py # aiogram 3.x — хендлеры + клавиатуры
│   ├── vk/bot.py       # vkbottle 4.x — хендлеры
│   └── max/bot.py      # max-bot-api-client-py (заглушка)
│
├── config.py           # pydantic-settings из .env
├── seed.py             # Тестовые мероприятия
│
├── deploy/             # Деплой и DevOps
│   ├── Makefile         # up-beget / logs-beget / down-beget
│   ├── docker-compose.beget.yml  # Override для Beget VPS
│   ├── docker-compose.prod.yml   # Override для прода
│   ├── setup-runner.sh           # Настройка GitHub Actions runner
│   ├── beget-setup.sh            # Разовый деплой на Beget
│   ├── deploy-vps.sh             # Универсальный деплой
│   ├── healthcheck.py            # Проверка здоровья
│   └── cron-healthcheck.py       # Healthcheck по крону
│
├── docs/               # Документация
├── .github/workflows/  # CI/CD
└── Dockerfile
```

### Принцип разделения

Каждая платформа — **независимый entry point**:
- `run_telegram.py` — `python run_telegram.py` запустит только Telegram
- `run_vk.py` — `python run_vk.py` запустит только VK
- `run_max.py` — `python run_max.py` запустит только MAX

Общий `main.py` пытается запустить все платформы, для которых есть токены.

Каждый entry point можно запустить в отдельном Docker контейнере (через profiles).

---

## Деплой через GitHub Actions

**Репозиторий:** `https://github.com/aerovir/ticketSellBot.git`

### Раннер

- Self-hosted runner на удалённом VPS
- Workflow: `.github/workflows/deploy.yml`
- Автоматический деплой при пуше в `main`

### Secrets (Settings → Secrets and variables → Actions)

| Secret | Описание |
|--------|---------|
| `TELEGRAM_TOKEN` | Токен Telegram бота от @BotFather |
| `TELEGRAM_CHANNEL_ID` | @username канала для анонсов (опционально) |
| `VK_TOKEN` | Токен VK сообщества |
| `VK_GROUP_ID` | ID VK группы |
| `MAX_TOKEN` | Токен MAX бота |

### Команды

```bash
make -C deploy up-beget      # запустить всех ботов
make -C deploy logs-beget    # смотреть логи
make -C deploy down-beget    # остановить
```

---

## Разработка

### 📋 Ведение документации — обязательно

Каждое изменение в проекте должно сопровождаться документацией:

#### 1. Ошибки и их исправления
Все найденные и исправленные ошибки фиксируются в `docs/errors.md`:
- **Описание ошибки** — что произошло, логи, traceback
- **Причина** — почему возникла
- **Исправление** — что конкретно изменили в коде
- **Дата** — когда исправили

#### 2. Учёт задач
Текущие и выполненные задачи ведутся в `docs/tasks.md`:
- **Статус** — pending / in progress / done / cancelled
- **Описание** — что нужно сделать
- **Дата** — когда добавлена задача
- **Связанные коммиты** — ссылки на изменения

#### 3. Принцип работы с проектом
- При обнаружении ошибки → сначала записать в `docs/errors.md`, потом чинить
- При постановке новой задачи → записать в `docs/tasks.md`
- После исправления → обновить `docs/errors.md` (статус), добавить ссылку на коммит
- При каждом новом сеансе → свериться с `docs/tasks.md`, обновить статусы

---

## Разработка

```bash
# Локально
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Запустить только Telegram
./run_telegram.py

# Накатить тестовые мероприятия
./seed.py
```

### Добавление новой платформы

1. Создать `platforms/new/bot.py` с классом, унаследованным от `PlatformBot`
2. Создать `run_new.py` по шаблону `run_telegram.py`
3. Добавить сервис в `docker-compose.yml`
4. Если нужно — добавить блок в `main.py`
