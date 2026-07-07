# Реестр ошибок TicketBot

Формат записи:
- **Дата:** когда обнаружено
- **Описание:** что произошло + логи
- **Причина:** почему возникло
- **Исправление:** что изменено (файл + суть)
- **Коммит:** ссылка на git

---

## 001 — vkbottle>=5.0 не найден в PyPI

- **Дата:** 2026-07-05
- **Описание:** `pip install vkbottle>=5.0` падает с ошибкой — пакет не найден. PyPI содержит только версии до 4.10.0.
- **Причина:** Неверно указана версия библиотеки. vkbottle на PyPI не превышает 4.10.0.
- **Исправление:** `requirements.txt` — `vkbottle>=5.0` → `vkbottle>=4.10.0`
- **Коммит:** — (исправлено в процессе первой настройки)

---

## 002 — Docker wait-for-db выходит без запуска приложения

- **Дата:** 2026-07-05
- **Описание:** Контейнер ждёт PostgreSQL, пишет «PostgreSQL готов!» и завершается. Бот не запускается.
- **Причина:** В конце скрипта `wait-for-db` стоял `exit 0`, а не `exec "$@"`. Скрипт завершал контейнер вместо передачи управления приложению.
- **Исправление:** `Dockerfile` — `exit 0` → `exec "$@"`
- **Коммит:** — (исправлено в процессе)

---

## 003 — VK_GROUP_ID="" не парсится как Optional[int]

- **Дата:** 2026-07-05
- **Описание:** При пустом значении `VK_GROUP_ID` в .env pydantic выдаёт ошибку валидации, не может привести пустую строку к `Optional[int]`.
- **Причина:** Поле объявлено как `Optional[int]`, пустая строка не конвертируется в None.
- **Исправление:** `config.py` — `vk_group_id: Optional[str]` (храним как строку, конвертируем при использовании)
- **Коммит:** — (исправлено в процессе)

---

## 004 — Node.js 20 deprecated в GitHub Actions

- **Дата:** 2026-07-05
- **Описание:** Warning при запуске workflow — `Node.js 20 actions are deprecated. Please update to Node.js 20.`
- **Причина:** Используются старые версии actions: checkout@v4, setup-python@v5.
- **Исправление:** `.github/workflows/deploy.yml` — `checkout@v4→v6`, `setup-python@v5→v6`
- **Коммит:** — (исправлено в процессе)

---

## 005 — IndentationError в проверке импортов на CI

- **Дата:** 2026-07-05
- **Описание:** Деплой падает на шаге проверки импортов с `IndentationError: unexpected indent`.
- **Причина:** Многострочный YAML с preserve-whitespace привёл к сломанному отступу в Python коде.
- **Исправление:** `.github/workflows/deploy.yml` — проверка импортов одной строкой `python -c "..."`.
- **Коммит:** — (исправлено в процессе)

---

## 006 — "Repository path is not under workspace" (checkout в /opt/ticketbot)

- **Дата:** 2026-07-05
- **Описание:** `Error: Repository path '/opt/ticketbot' is not under '/home/user1/actions-runner/_work/ticketSellBot/ticketSellBot'`
- **Причина:** Использован `path:` в actions/checkout@v6, указывающий директорию вне рабочей области раннера.
- **Исправление:** Удалён `path:` из checkout, все `working-directory` ссылки удалены. Runner сам клонирует в `_work/`.
- **Коммит:** — (исправлено в процессе)

---

## 007 — Docker permission denied (self-hosted runner)

- **Дата:** 2026-07-05
- **Описание:** `permission denied while trying to connect to the Docker daemon socket` — раннер не может выполнять docker compose.
- **Причина:** В `deploy/setup-runner.sh` команда `usermod -aG docker` была внутри блока `else`, поэтому существующий пользователь runner не добавлялся в группу docker.
- **Исправление:** `deploy/setup-runner.sh` — `usermod -aG docker` вынесен из `if-else` и выполняется всегда.
- **Коммит:** `6d26730` — Fix setup-runner.sh: usermod -aG docker теперь выполняется всегда

---

## 008 — Telegram API timeout с российского хостинга

- **Дата:** 2026-07-07
- **Описание:** Бот падает при старте с `TelegramNetworkError: Request timeout error`. Запускается только на 3-й раз, когда Docker перезапустит контейнер через restart policy.
- **Причина:** С российского VPS (Beget/LightNode) соединение с Telegram API (api.telegram.org) идёт нестабильно, первые 2 попытки уходят в таймаут.
- **Исправление:** `platforms/telegram/bot.py` — добавлен retry-цикл в `run()`: до 10 попыток с экспоненциальной задержкой (5с → 60с). Аналогично поправлено в `platforms/vk/bot.py`.
- **Коммит:** `62752d3` — Telegram: retry при ошибках подключения к API

---

## 009 — VK бот: команды с параметрами не работали

- **Дата:** 2026-07-07
- **Описание:** Хендлеры вида `text=["/buy <event_id>"]` используют список, что предполагает точное совпадение текста. Пользователь не может передать параметр команде.
- **Причина:** vkbottle ожидает строку или паттерн, а не список с литералом.
- **Исправление:** `platforms/vk/bot.py` — `text=["/buy <event_id>"]` → `text="/buy <event_id>"` (строка вместо списка). Также добавлена безопасная проверка `message.sender` и retry-логика.
- **Коммит:** `e17488f` — Разделение кода соцсетей + правки VK бота

---

## 010 — Таблица `events` не создаётся при деплое

- **Дата:** 2026-07-07
- **Описание:** После деплоя команда `/events` в Telegram падает с `UndefinedTableError: relation "events" does not exist`. База запущена, init_db() вызвана, но таблиц нет.
- **Причина:** `init_db()` вызывает `Base.metadata.create_all`, но на момент вызова ни одна модель не импортирована. SQLAlchemy не знает о таблицах.
- **Исправление:** `core/database.py` — добавлен `from core.models import User, Event, Ticket, Payment` внутрь `init_db()`. Модели импортируются перед `create_all`.
- **Коммит:** `29746ef` — Fix: init_db теперь импортирует модели перед create_all + seed в деплой

---

## 011 — VK бот: message.sender может быть None

- **Дата:** 2026-07-07
- **Описание:** Код обращается к `message.sender.first_name` без проверки на None. Если VK API не вернул данные пользователя — AttributeError.
- **Причина:** vkbottle возвращает `sender = None` при ошибках получения профиля.
- **Исправление:** `platforms/vk/bot.py` — добавлен метод `_get_user_name()` с проверкой `if message.sender`.
- **Коммит:** `e17488f` — Разделение кода соцсетей + правки VK бота
