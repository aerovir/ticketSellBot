# MAX Bot

Адаптер для **MAX (max.ru)** — российского мессенджера от VK Group.

## Статус

⏸️ **Заглушка** — код написан по документации API, но не протестирован.  
Ждёт доступа к [max-bot-api-client-py](https://pypi.org/project/max-bot-api-client-py/).

- Документация API: https://dev.max.ru/docs-api
- Python SDK: `pip install max-bot-api-client-py`

## Команды

| Команда | Описание |
|---------|----------|
| `start` | Приветствие + список команд |
| `events` | Список предстоящих мероприятий |
| `event <id>` | Детали мероприятия |
| `buy <id>` | Купить билет |
| `my_tickets` | Мои билеты |
| `cancel <id>` | Отменить билет |

> MAX использует команды **без слэша** (в отличие от Telegram и VK).

## Настройка

1. Получить токен у @MasterBot
2. Установить SDK: `pip install max-bot-api-client-py`
3. Настроить `.env.max`:
   ```
   DATABASE_URL=postgresql+asyncpg://max_user:password@localhost:5432/ticketbot
   MAX_TOKEN=ваш_токен
   ```

## Запуск

```bash
docker compose --profile all up -d max
```

## Классы

- **`MaxPlatformBot`** (`bot.py`) — основной класс с хендлерами
- Использует `max_bot_api.MaxBot`
