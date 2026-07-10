# Telegram Bot

Адаптер для Telegram на базе **aiogram 3.x**.

## Статус

✅ **Работает** — используется в продакшене.

## Команды

### 📢 В канале (только просмотр)
| Команда | Описание |
|---------|----------|
| `/events` | Список предстоящих мероприятий |
| `/event <id>` | Детали мероприятия |

### 💬 В личных сообщениях
| Команда | Описание |
|---------|----------|
| `/start` | Приветствие + список команд |
| `/events` | Список предстоящих мероприятий |
| `/event <id>` | Детали + кнопка «Купить» |
| `/buy <id>` | Купить билет |
| `/my_tickets` | Мои билеты |
| `/cancel <id>` | Отменить билет |

### 🔐 Админ-команды (только для ADMIN_TELEGRAM_IDS)
| Команда | Описание |
|---------|----------|
| `/admin` | Меню администратора |
| `/create_event` | Пошаговое создание мероприятия (FSM) |
| `/events_all` | Все мероприятия |
| `/stats <id>` | Статистика продаж |
| `/deactivate <id>` | Отключить мероприятие |
| `/activate <id>` | Включить мероприятие |

## Настройка

1. Создать бота через [@BotFather](https://t.me/BotFather) → получить токен
2. Настроить `.env.telegram`:
   ```
   DATABASE_URL=postgresql+asyncpg://tg_user:password@localhost:5432/ticketbot
   TELEGRAM_TOKEN=ваш_токен
   TELEGRAM_CHANNEL_ID=@channel_username
   ADMIN_TELEGRAM_IDS=123456,789012
   ```

### Telegram канал для анонсов

1. Создать канал (приватный или публичный)
2. Добавить бота в канал как **администратора** с правами:
   - ✅ Отправлять сообщения
   - ✅ Читать сообщения
3. Отключить Privacy Mode в BotFather:
   ```
   @BotFather → /mybots → Bot → Bot Settings → Group Privacy → Turn off
   ```
4. Указать `TELEGRAM_CHANNEL_ID` в `.env.telegram`

### Классы

- **`TelegramBot`** (`bot.py`) — основной класс с хендлерами
- **`ChannelManager`** (`channel.py`) — отправка анонсов в канал
- **`CreateEvent`** — FSM для пошагового создания мероприятия
