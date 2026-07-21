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

---

## 012 — Payment.ticket_id = null при покупке билета

- **Дата:** 2026-07-07
- **Статус:** ✅ Исправлено
- **Описание:** При покупке билета (`/buy`) бот падает с `NotNullViolationError: null value in column "ticket_id" of relation "payments" violates not-null constraint`. Лог показывает, что в INSERT в payments параметр `ticket_id` = None.
- **Анализ:** `core/services.py:180-192`
   1. `ticket = Ticket(...)` — в конструкторе не передан `id`. Поле `id` модели имеет `default=uuid.uuid4`, но это column-level default, который не выполняется при создании объекта в Python → `ticket.id == None`
   2. `payment = Payment(ticket_id=ticket.id)` — передаётся None
   3. `self.session.flush()` — Ticket получает UUID от БД, но Payment уже сформирован с `ticket_id = None`
- **Причина (подтверждено: core/models.py:79-80, core/services.py:180-192):** `default=uuid.uuid4` в SQLAlchemy ORM — это column default, не заполняющий атрибут объекта до flush()
- **Исправление:** `core/services.py:180` — явная генерация `id=uuid.uuid4()` при создании Ticket
- **Связанные ошибки:** нет

---

## 013 — GitHub Actions: Unrecognized named-value 'secrets' в if: выражениях

- **Дата:** 2026-07-10
- **Статус:** ✅ Исправлено
- **Описание:** Деплой падает на этапе парсинга workflow с ошибкой:
  ```
  (Line: 77, Col: 13): Unrecognized named-value: 'secrets'. Located at position 1
  within expression: secrets.VK_TOKEN != ''
  (Line: 88, Col: 13): Unrecognized named-value: 'secrets'. Located at position 1
  within expression: secrets.MAX_TOKEN != ''
  (Line: 189, Col: 13): Unrecognized named-value: 'secrets'. Located at position 1
  within expression: secrets.VK_TOKEN != ''
  ```
  Шаги создания `.env.vk`, `.env.max` и запуска VK бота не выполняются, workflow завершается ошибкой до запуска контейнеров.
- **Анализ:**
  - **Гипотеза:** `${{ secrets.X }}` в `if:` не поддерживается GitHub Actions, т.к. `${{ }}` вычисляется на этапе парсинга, а `secrets` доступен только в runtime контексте.
  - **Подтверждено (docs.github.com):** GitHub Actions документация явно указывает, что `secrets` нельзя использовать в `if:` условиях. Вместо этого секрет передаётся через `env:` блок, а в `if:` используется `env.VK_TOKEN != ''`.
- **Исправление (подтверждено: .github/workflows/deploy.yml:77-79, 90-92, 193-195):**
  Замена во всех трёх местах:
  ```yaml
  # Было:
  if: ${{ secrets.VK_TOKEN != '' }}

  # Стало:
  env:
    VK_TOKEN: ${{ secrets.VK_TOKEN }}
  if: env.VK_TOKEN != ''
  ```
  Принцип: `${{ secrets.X }}` в `env:` резолвится в пустую строку, если секрет не задан. `env.X != ''` — корректное runtime-выражение.
- **Коммит:** `3f9d205` — fix: secrets in GitHub Actions if: expressions
- **Связанные ошибки:** нет

---

## 014 — CI: RuntimeError — starlette.testclient requires httpx2 (тесты test_web_api не собираются)

- **Дата:** 2026-07-10
- **Статус:** ✅ Исправлено
- **Описание:** На CI (GitHub Actions) тесты падают при сборе с ошибкой:
  ```
  ERROR collecting tests/test_web_api.py
  RuntimeError: The starlette.testclient module requires the httpx2 package
  ```
  Локально тесты проходят, на CI — нет. При этом `test_web_api.py` импортирует `TestClient` из `fastapi.testclient`.
- **Анализ:**
  - **Гипотеза:** `httpx` не указан в зависимостях, на CI fresh install без него.
  - **Подтверждено (`pyproject.toml:19-24`):** В `[project.optional-dependencies] dev` отсутствует `httpx`. Локально он уже есть в окружении (`pip list`), на CI — нет.
  - Ошибка говорит "httpx2", но имеется в виду пакет `httpx` версии 2.x (современный). `fastapi.testclient` требует `httpx>=0.28`.
- **Исправление (подтверждено: pyproject.toml:24):**
  Добавлена строка `"httpx>=0.28"` в `dev`-зависимости.
- **Коммит:** `7bb4543` — fix: add httpx to dev dependencies for FastAPI TestClient
- **Связанные ошибки:** нет

---

## 015 — Deploy: service "app" has neither an image nor a build context (docker compose exec без COMPOSE_FILES)

- **Дата:** 2026-07-10
- **Статус:** ✅ Исправлено
- **Описание:** Деплой падает на шаге «Создать роли PostgreSQL» с ошибкой:
  ```
  service "app" has neither an image nor a build context specified: invalid compose project
  ```
  Лог показывает, что команда `docker compose exec -T db bash -c "..."` запущена без флагов `-f`.
- **Анализ:**
  - **Гипотеза:** `docker compose exec` без `${{ env.COMPOSE_FILES }}` пытается перепарсить compose-файлы. На self-hosted runner находит неполный compose-проект (например, файл `compose.yaml` вне репозитория) и падает.
  - **Подтверждено (`deploy.yml:128, 171, 118, 203, 205, 208`):** Все `docker compose exec`, `ps`, `logs` команды используют только дефолтный `docker-compose.yml` без Beget-override. При этом проект создан с `-f docker-compose.yml -f deploy/docker-compose.beget.yml`.
- **Исправление (подтверждено: .github/workflows/deploy.yml):**
  Добавлен `${{ env.COMPOSE_FILES }}` (`-f docker-compose.yml -f deploy/docker-compose.beget.yml`) во все `docker compose` команды:
  - Ожидание PostgreSQL (pg_isready)
  - Создание ролей (psql heredoc)
  - Выдача прав на таблицы (psql -c)
  - Проверка работоспособности (ps, logs)
- **Коммит:** `96384b8` — fix: add COMPOSE_FILES to all docker compose commands in deploy
- **Связанные ошибки:** нет

---

## 016 — ModuleNotFoundError: No module named 'bot' (неверный Python-модуль в docker-compose)

- **Дата:** 2026-07-11
- **Статус:** ✅ Исправлено
- **Описание:** При деплое контейнер telegram падает с циклическим перезапуском:
  ```
  /usr/local/bin/python: Error while finding module specification for 'bot.telegram'
  (ModuleNotFoundError: No module named 'bot')
  ```
  Контейнер уходит в `Restarting (1)` и не поднимается.
- **Анализ:**
  - **Подтверждено (`Dockerfile:6`, `docker-compose.yml:30`, `docker-compose.yml:44`, `docker-compose.yml:58`, `docker-compose.yml:68`, `docker-compose.yml:78`):**
    - В Dockerfile: `WORKDIR=/app`, `PYTHONPATH=/app`
    - Код проекта копируется в `/app`, реальная структура: `/app/app/bot/telegram.py` — то есть пакет `app.bot.telegram`
    - Команды в docker-compose.yml: `python -m bot.telegram` — поиск идёт по пути `/app/bot/telegram.py` (не существует)
    - Ранее, когда `bot/` лежал в корне репозитория, команда `python -m bot.telegram` работала. После реструктуризации (перенос `bot/` под `app/`) docker-compose.yml не обновлён.
  - Причина: несоответствие между PYTHONPATH и фактическим расположением модулей после реструктуризации.
- **Исправление (подтверждено: `docker-compose.yml:30,44,58,68,78`):**
  Все команды `python -m bot.xxx` заменены на `python -m app.bot.xxx`:
  ```yaml
  # Было:
  command: ["python", "-m", "bot.telegram"]
  # Стало:
  command: ["python", "-m", "app.bot.telegram"]
  ```
  Изменены сервисы: `telegram`, `vk`, `max`, `seed`, `web`.
- **Коммит:** (будет в след. коммите)
- **Связанные ошибки:** нет

---

## 017 — ADMIN_TELEGRAM_IDS пустой в контейнере (переопределяется compose override)

- **Дата:** 2026-07-11
- **Статус:** ✅ Исправлено
- **Описание:** В контейнере `ticketbot-telegram` переменная `ADMIN_TELEGRAM_IDS` пустая, хотя в GitHub Secrets значение задано, и `.env.telegram` создаётся из секрета. Админ-команды (`/repost_events`, `/admin`) отвечают «У вас нет доступа к панели администратора».
- **Анализ:**
  - **Подтверждено (`deploy/docker-compose.beget.yml:38-39`):** В beget override для сервиса `telegram` указан блок:
    ```yaml
    environment:
      ADMIN_TELEGRAM_IDS: ${ADMIN_TELEGRAM_IDS:-}
    ```
  - Docker Compose при merge даёт приоритет `environment` над `env_file`. Значение из `.env.telegram` затирается.
  - Переменная `${ADMIN_TELEGRAM_IDS}` не задана в shell окружении раннера → раскрывается в пустую строку.
- **Исправление (подтверждено: `deploy/docker-compose.beget.yml:38-39`):**
  Удалён блок `environment` у сервиса `telegram` в beget override. Значение `ADMIN_TELEGRAM_IDS` теперь берётся из `.env.telegram`, который создаётся на шаге деплоя из GitHub Secret.
- **Коммит:** `03113f3`
- **Связанные ошибки:** нет

---

## 018 — Alembic миграция падает на CI: "table channels already exists" / "column channel_id does not exist"

- **Дата:** 2026-07-11
- **Статус:** ✅ Исправлено
- **Описание:** Деплой на CI проходит через несколько итераций ошибок:
  1. `init_db()` создаёт таблицы → alembic stamp head → миграция 0002 пытается создать таблицы повторно → `relation "channels" already exists`
  2. После замены `init_db()` на alembic — ошибка `column channel_id of relation "events" does not exist`, потому что init_db() не добавляет колонки в существующие таблицы (только DROP ALL → CREATE ALL, но данные уже есть)
- **Анализ:**
  - **Подтверждено:** init_db() вызывает `Base.metadata.create_all`, она **создаёт только новые таблицы**, но **не добавляет колонки** в существующие.
  - Alembic migration 0002 корректно описывает изменения, но при наличии данных `drop_all → create_all` недопустим.
- **Исправление (подтверждено: `.github/workflows/deploy.yml:157-186`):**
  Три шага в деплое:
  1. `alembic stamp head` — проставляет версию в существующей БД (без миграции)
  2. `ALTER TABLE ADD COLUMN IF NOT EXISTS` — идемпотентное добавление колонок
  3. `INSERT INTO channels ... WHERE NOT EXISTS` — создание legacy канала
  4. `UPDATE events SET channel_id = ... WHERE channel_id IS NULL` — бэкфилл
  Итоговая версия — stamp head + идемпотентный SQL через psql.
- **Коммиты:** `bed6e60`, `1449908`, `b5eb13a`, `a7d6e6a`
- **Связанные ошибки:** нет

---

## 019 — "кнопка подтвердить не активна" в create_event FSM

- **Дата:** 2026-07-11
- **Статус:** ✅ Исправлено
- **Описание:** При создании мероприятия через FSM, на шаге подтверждения кнопка "✅ Подтвердить" не активна (disabled). Пользователь не может завершить создание мероприятия.
- **Анализ:**
  - **Подтверждено (`app/platforms/telegram/bot.py`, хендлер `admin:confirm_create`):**
    - `callback.answer()` вызывалась **после** всех DB-операций (создание Event + запись в БД)
    - Telegram требует `callback.answer()` в течение 30 секунд. Если не вызвана — кнопка "висит" в состоянии ожидания
    - При ошибке БД или долгом запросе Telegram не получает answer → деактивирует кнопку
  - Дополнительно: не было проверки state перед выполнением (если пользователь не в FSM)
- **Исправление (подтверждено: `app/platforms/telegram/bot.py`):**
  1. `callback.answer()` перенесён в самое начало хендлера
  2. Добавлен try-except с отправкой сообщения об ошибке
  3. Добавлена валидация state (если нет данных в FSM — отправить alert)
- **Коммит:** `a7f15ff`
- **Связанные ошибки:** нет

---

## 020 — Legacy канал: admin_telegram_user_id='0' приводит к пустому меню админа

- **Дата:** 2026-07-11
- **Статус:** ✅ Исправлено
- **Описание:** После деплоя multi-tenant в каналах пропали inline-кнопки. Команда `/admin` показывала «Панель управления» с кнопками, но все админ-команды возвращали ошибку. Пользователи в канале вообще не видели кнопок.
- **Анализ:**
  - **Подтверждено (`app/platforms/telegram/bot.py`, метод `_get_admin_channel()`):**
    - Метод ищет канал по `admin_telegram_user_id == str(user_id)`
    - Legacy канал создаётся с `admin_telegram_user_id = '0'`
    - Ни один реальный пользователь не имеет Telegram ID = 0
    - → `_get_admin_channel()` возвращает None → админ не может управлять каналом
  - Дополнительно: канальные кнопки (`channel_buy`, `channel_events`) требуют контекст канала, который определялся через `_get_admin_channel()` — не работал.
- **Исправление (подтверждено: `app/platforms/telegram/bot.py`):**
  Добавлен fallback в `_get_admin_channel()`:
  1. Если канал с `admin_telegram_user_id = '0'` существует — автоматически привязать к текущему админу
  2. Обновить `admin_telegram_user_id` на реальный ID пользователя
  3. Записать изменения в БД
  4. Вернуть канал админу
- **Коммит:** `913b104`
- **Связанные ошибки:** нет

---

## 021 — CI test_admin_menu_unauthorized падает: _get_admin_channel требует БД

- **Дата:** 2026-07-11
- **Статус:** ✅ Исправлено
- **Описание:** На CI тест `test_admin_menu_unauthorized` падает с ошибкой, потому что `admin_menu()` теперь вызывает `_get_admin_channel()`, который требует подключения к БД и сервисов.
- **Анализ:**
  - **Подтверждено (`tests/test_telegram_bot.py:164-171`):**
    - После перехода на button-based меню, `admin_menu()` вызывает `_get_admin_channel()` даже для неавторизованного пользователя (проверка на super-admin происходит раньше, но channel admin path тоже вызывает метод)
    - Тест использует mock-объекты без подключения к БД
    - `_get_admin_channel()` не замокан → падает
- **Исправление (подтверждено: `tests/test_telegram_bot.py:167`):**
  Добавлен `patch.object(telegram_bot, "_get_admin_channel", new_callable=AsyncMock, return_value=None)`:
  ```python
  with patch.object(telegram_bot, "_get_admin_channel", new_callable=AsyncMock, return_value=None):
      await telegram_bot.admin_menu(mock_message)
  ```
- **Коммит:** `18e56ed`
- **Связанные ошибки:** нет

---

## 022 — CI test_admin_menu_authorized: текст меню изменился на кнопочный

- **Дата:** 2026-07-11
- **Статус:** ✅ Исправлено
- **Описание:** На CI тест `test_admin_menu_authorized` падает, потому что проверяет текст "Панель администратора", но после перехода на button-based меню текст изменился на "Панель управления".
- **Анализ:**
  - **Подтверждено (`tests/test_telegram_bot.py:174-188`):**
    - Тест проверяет `assert "Панель администратора" in text`
    - В новой реализации `admin_menu()` отправляет "Панель управления" с inline-кнопками
- **Исправление (подтверждено: `tests/test_telegram_bot.py:185`):**
  Изменена проверка текста:
  ```python
  assert "Панель управления" in text
  ```
  Добавлена проверка наличия `reply_markup` в kwargs.
- **Коммит:** `f8846be`
- **Связанные ошибки:** нет

---

## 023 — Permission denied for schema public при CREATE TYPE platformtype

- **Дата:** 2026-07-12
- **Статус:** ✅ Исправлено
- **Описание:** После деплоя контейнер telegram циклически перезапускается с ошибкой:
  ```
  asyncpg.exceptions.InsufficientPrivilegeError: permission denied for schema public
  [SQL: CREATE TYPE platformtype AS ENUM ('telegram', 'vk', 'max')]
  ```
  `init_db()` не может создать ENUM-тип `platformtype`, бот не стартует.
- **Анализ:**
  - **Подтверждено (`.github/workflows/deploy.yml:135,143,151`):**
    - На шаге «Создать роли PostgreSQL» платформенным ролям выдаётся только `GRANT USAGE ON SCHEMA public`
    - `USAGE` позволяет обращаться к существующим объектам, но `CREATE TYPE/platformtype` требует права `CREATE` на схему
    - `init_db()` → `Base.metadata.create_all` → создание ENUM → `InsufficientPrivilegeError`
    - Аналогичная проблема с последовательностями (sequences) — не выданы права на `ALL SEQUENCES`
- **Исправление (подтверждено: `.github/workflows/deploy.yml`):**
  1. `GRANT USAGE` → `GRANT USAGE, CREATE ON SCHEMA public` для всех трёх ролей (`tg_user`, `vk_user`, `max_user`)
  2. Добавлены `GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public` для всех трёх ролей в шаг «Права на таблицы»
- **Коммит:** `2a8c29b`
- **Связанные ошибки:** нет

---

## 024 — UnboundLocalError: cannot access local variable 'select' where it is not associated with a value

- **Дата:** 2026-07-12
- **Статус:** ✅ Исправлено
- **Описание:** При нажатии на кнопки админ-меню (кроме stats_all) бот падает с `UnboundLocalError: cannot access local variable 'select' where it is not associated with a value`. Traceback указывает на строку `select(Channel).where(...)` в `cmd_callback`.
- **Анализ:**
  - **Подтверждено (`app/platforms/telegram/bot.py`, callback handler):**
    - `from sqlalchemy import select, func` стоял внутри `if action == "stats_all":` — это сделало `select` локальной переменной для всей функции `cmd_callback`
    - Python при компиляции функции видит `select` в любом блоке как локальную переменную (из-за присваивания через import в одном из блоков)
    - Все остальные `if action == ...` блоки (check_expired, list_channels, health и др.) используют `select` без собственного импорта → `UnboundLocalError`
- **Исправление (подтверждено: `app/platforms/telegram/bot.py`):**
  1. Перенесён `from sqlalchemy import select, func` на верхний уровень файла (после стандартных импортов)
  2. Убран дублирующийся локальный импорт внутри `if action == "stats_all"`
- **Коммит:** `305691e`
- **Связанные ошибки:** нет

---

## 025 — NameError: TicketStatus / PaymentStatus / User / Event / Ticket / Payment не импортированы

- **Дата:** 2026-07-12
- **Статус:** ✅ Исправлено
- **Описание:** В `bot.py` отсутствовали импорты `TicketStatus`, `PaymentStatus`, `User`, `Event`, `Ticket`, `Payment` из `app.core.models`. При попытке выполнить действия, использующие эти имена (статистика, отмена билета, инфо о канале и т.д.), бот падал бы с `NameError`.
- **Анализ:**
  - **Подтверждено (`app/platforms/telegram/bot.py:15`):**
    - Импорт был только `from app.core.models import PlatformType, Channel`
    - `User`, `Event`, `Ticket`, `Payment` использовались в запросах SQLAlchemy (`select(func.count()).select_from(User)` и т.д.)
    - `TicketStatus`, `PaymentStatus` использовались как значения enum (`TicketStatus.active`, `PaymentStatus.completed`)
    - Баг не проявлялся раньше, т.к. код до недавних правок не использовал эти имена напрямую
- **Исправление (подтверждено: `app/platforms/telegram/bot.py:15-18`):**
  Расширен импорт:
  ```python
  from app.core.models import (
      PlatformType, Channel, User, Event, Ticket, Payment,
      TicketStatus, PaymentStatus,
  )
  ```
- **Коммит:** `e2fa6a8`
- **Связанные ошибки:** нет

---

## 026 — Каналу при подписке назначается суперадмин вместо реального админа

- **Дата:** 2026-07-13
- **Статус:** ✅ Исправлено
- **Описание:** Super-admin подписывает канал через `/subscribe @channel 30` (или через FSM-кнопку «Подписать»). Канал регистрируется в БД с `admin_telegram_user_id = super_admin_id`. Реальный админ канала добавляет бота, но не может управлять каналом — запись уже занята суперадмином. Дополнительно: при добавлении бота в канал создаётся дубликат записи, т.к. поиск по числовому ID не находит запись, созданную с @username.
- **Причина (подтверждено: `app/platforms/telegram/bot.py`):**
  - Две несогласованные точки создания/обновления записей канала:
    1. `/subscribe` при создании нового канала записывает `admin_telegram_user_id = str(message.from_user.id)` (суперадмин)
    2. `on_chat_member_update` ищет канал по `str(chat.id)` — не находит запись с @username → создаёт дубликат
  - Формат ключа не совпадает: `/subscribe` сохраняет @username, `on_chat_member_update` ищет по числовому ID
- **Исправление (подтверждено: `app/platforms/telegram/bot.py`):**
  1. `/subscribe` (text command, ~line 1379 и FSM handler, ~line 857): `admin_telegram_user_id=str(message.from_user.id)` → `admin_telegram_user_id=""` (пустая строка). Реальный админ определится, когда добавит бота.
  2. `on_chat_member_update` (~line 1486): после неудачного поиска по `str(chat.id)` добавлен fallback — поиск по `chat.username` (если есть @username у канала). Если запись найдена — обновляется: числовой ID, admin_telegram_user_id, title.
  3. Условие замены `telegram_channel_id` расширено: теперь также срабатывает при `channel.telegram_channel_id.startswith("@")`.
- **Коммит:** —

---

## 027 — UnboundLocalError: cannot access local variable 'datetime' where it is not associated with a value

- **Дата:** 2026-07-16 (обновлено 2026-07-16)
- **Статус:** ✅ Исправлено
- **Описание:** В runtime при нажатии inline-кнопки «Общая статистика» бот падает с ошибкой:
  ```
  UnboundLocalError: cannot access local variable 'datetime' where it is not associated with a value
  Traceback (most recent call last):
    File "/app/app/platforms/telegram/bot.py", line 1684, in cmd_callback
      select(func.count()).select_from(Event).where(Event.date >= datetime.now(timezone.utc))
                                                                  ^^^^^^^^
  UnboundLocalError: cannot access local variable 'datetime' where it is not associated with a value
  ```
  Ошибка повторяется дважды (на двух разных сессиях).
- **Анализ:**
  - **Подтверждено (`app/platforms/telegram/bot.py:1596`):**
    - Внутри функции `cmd_callback` (строка 1596) есть локальный импорт `from datetime import datetime` в ветке `if action == "admin:confirm_create":`
    - Python при компиляции видит присваивание `datetime` через импорт в одном из блоков функции — `datetime` становится локальной переменной для всей функции
    - Когда срабатывает ветка `if action == "stats_all":` (строка 1685), код использует `datetime.now(timezone.utc)` — но локальная `datetime` ещё не присвоена (ветка `admin:confirm_create` не выполнялась), возникает `UnboundLocalError`
  - **Корень проблемы:** Предыдущее «исправление» (добавление `from datetime import datetime, timezone` на верхний уровень) было недостаточным. Локальный импорт на строке 1596 остался и продолжал затенять глобальный `datetime`, потому что Python видит `import` внутри функции как присваивание локальной переменной, что делает `datetime` локальным для всей функции `cmd_callback` независимо от того, выполнилась ли эта ветка.
- **Исправление (подтверждено: `app/platforms/telegram/bot.py:1596,593`):**
  1. Удалена строка 1596 `from datetime import datetime` внутри `cmd_callback`. Глобальный импорт `from datetime import datetime, timezone` (строка 2) уже предоставляет оба имени. `datetime.fromisoformat()` — классовый метод, доступный через глобальный `datetime`.
  2. Дополнительно удалена строка 593 `from sqlalchemy import select, func` внутри `sa_channel_info()` — избыточный импорт, т.к. `select` и `func` уже импортированы глобально на строке 12. Этот импорт не вызывал ошибки (использовался сразу после объявления), но являлся техническим долгом.
  Аналогичная проблема (локальный импорт, затеняющий глобальный) была ранее с #024 (`select`), исправлена тем же способом.
- **Коммит:** —

---

## 028 — CI test_admin_create_event_unauthorized падает: _get_admin_channel требует БД (InvalidCatalogNameError)

- **Дата:** 2026-07-16
- **Статус:** ✅ Исправлено
- **Описание:** На CI тест `test_admin_create_event_unauthorized` падает с ошибкой:
  ```
  asyncpg.exceptions.InvalidCatalogNameError: database "ticketbot" does not exist
  ```
  Остальные 83 теста проходят. Ошибка возникает, потому что `admin_create_event()` вызывает `_is_channel_admin()`, который при незаадминенном пользователе вызывает `_get_admin_channel()`, который открывает реальную сессию БД через `async_session_factory()`, использующую `settings.database_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/ticketbot"`. В CI есть только `ticketbot_test`.
- **Причина (подтверждено: `tests/test_telegram_bot.py:190-199`):**
  - После замены `_is_admin` на `_is_channel_admin` в `admin_create_event()` (строка 1048), метод вызывает `_get_admin_channel()` (транзитивно через `_is_channel_admin` на строке 426), который требует реальную БД
  - Тест не мокает `_get_admin_channel`, в отличие от `test_admin_menu_unauthorized` (строка 167), который мокает этот же метод
  - `async_session_factory` на строке 8 `database.py` использует дефолтный URL `ticketbot`, а в CI существует только `ticketbot_test`
- **Исправление (подтверждено: `tests/test_telegram_bot.py:194`):**
  Добавлен `patch.object(telegram_bot, "_get_admin_channel", new_callable=AsyncMock, return_value=None)`:
  ```python
  with patch.object(telegram_bot, "_get_admin_channel", new_callable=AsyncMock, return_value=None):
      await telegram_bot.admin_create_event(mock_message, mock_state)
  ```
  По аналогии с `test_admin_menu_unauthorized` (строка 167). Теперь `_is_channel_admin` вызывает замоканный `_get_admin_channel`, получает None, возвращает False, и хендлер корректно отвечает «У вас нет доступа», без обращения к БД.
- **Связанные ошибки:** #021 (аналогичная проблема для `test_admin_menu_unauthorized`)

---

## 029 — on_chat_member_update не обрабатывает статус "administrator" (каналы)

- **Дата:** 2026-07-16
- **Статус:** ✅ Исправлено
- **Описание:** Admin канала добавляет бота в канал, но `on_chat_member_update()` не срабатывает. `admin_telegram_user_id` остаётся пустым, админ не может создавать мероприятия — «У вас нет доступа к панели администратора». При этом `/create_event` в канале просто игнорируется (нет channel_post хендлера).
- **Анализ:**
  - **Подтверждено (`app/platforms/telegram/bot.py:1513`):** Проверка `new_chat_member.status == "member"`. В Telegram каналах бот всегда добавляется как администратор (`status = "administrator"`), а не как участник (`"member"`). Проверка никогда не совпадает.
  - Дополнительно: при вводе команд не было проверки через Telegram API, что пользователь действительно является админом канала сейчас. Система полностью доверяла БД.
- **Исправление (подтверждено: `app/platforms/telegram/bot.py`):**
  1. `on_chat_member_update`: `== "member"` → `in ("member", "administrator")` (строка 1513)
  2. Добавлен метод `_verify_channel_admin()` (строка 390) — вызывает `bot.get_chat_member()` через Telegram API
  3. В `_get_admin_channel()` после проверки подписки добавляется Telegram-верификация (строка 412)
  4. При провале верификации — подписка деактивируется, пользователь видит «Нет канала с активной подпиской»
  5. Fallback-каналы (unassigned, legacy) также проверяются перед привязкой (строки 430, 450)
  6. Устранены двойные вызовы `_get_admin_channel()` в 5 хендлерах
  7. В тесты добавлен мок `get_chat_member` в fixture `telegram_bot`
- **Связанные ошибки:** #021, #028

---

## 030 — _verify_channel_admin деактивирует подписку при временной ошибке Telegram API

- **Дата:** 2026-07-16
- **Статус:** ✅ Исправлено
- **Описание:** Админ канала вводит `/create_event` — бот отвечает «У вас нет канала с активной подпиской», хотя канал есть в БД и подписка активна. Причина: `_verify_channel_admin()` вызывает `bot.get_chat_member()`, который падает с ошибкой (неверный формат ID, сетевой сбой, rate limit), и подписка необратимо деактивируется.
- **Анализ:**
  - **Подтверждено (`app/platforms/telegram/bot.py:390-403`, `412-421`):**
    1. `_verify_channel_admin()` возвращал `False` на любую ошибку API (exception)
    2. `_get_admin_channel()` трактовал `False` как «пользователь не админ» → вызывал `deactivate_subscription()`
    3. Следующий вызов уже не находил канал (подписка удалена)
  - **Дополнительно:** `on_chat_member_update()` не обновлял `telegram_channel_id`, если super-admin ввёл голое число (`1234567890`) без `-100` префикса. `get_chat_member(chat_id="1234567890")` падал с ошибкой.
- **Исправление (подтверждено: `app/platforms/telegram/bot.py`):**
  1. `_verify_channel_admin()` возвращает `True` (админ), `False` (не админ, подтверждено API), `None` (ошибка API)
  2. `_get_admin_channel()`: 
     - `True` → возвращает канал
     - `False` → деактивирует подписку (подтверждено API)
     - `None` → не трогает подписку, логирует, пробует следующий канал
  3. `on_chat_member_update()`: добавлена проверка `channel.telegram_channel_id.lstrip("-").isdigit()` — исправляет голые числа
- **Связанные ошибки:** #029

---

## 031 — При ошибке Telegram API _get_admin_channel пропускает канал, а не возвращает его

- **Дата:** 2026-07-18
- **Статус:** ✅ Исправлено
- **Описание:** Пользователь имеет канал в БД с активной подпиской, бот добавлен в канал. Но при `/create_event` получает «❌ У вас нет канала с активной подпиской.».
  - `/create_event` не появляется в Menu Button (админские команды не видны)
  - При ручном вводе `/create_event` — отказ
  - При этом канал в `/my_channels` отображается, подписка активна
- **Анализ:**
  - **Подтверждено (`app/platforms/telegram/bot.py:471-476`):** После фикса #059 `_verify_channel_admin()` возвращает `None` при ошибке API. Код в `_get_admin_channel()` при `None` **пропускает канал** (логирует и идёт к следующему), но не возвращает его. Если канал один — цикл завершается без результата, fallback'ов для обычного админа нет.
  - При этом подписка в БД **остаётся активной** — проблема не в подписке, а в том, что `_get_admin_channel()` не доверяет БД при ошибке API.
  - Причины ошибки API: может быть сетевой сбой, rate limit, временная недоступность Telegram API — любая причина, не связанная с правами пользователя.
- **Исправление (подтверждено: `app/platforms/telegram/bot.py:478-484`):**
  ```python
  # verified is None — ошибка API (сеть, таймаут, формат ID).
  # Доверяем БД: подписка активна, пользователь админ.
  logger.warning(...)
  return channel
  ```
  При `None` (ошибка API) — возвращаем канал. Подписку не деактивируем, действие не блокируем.
  Логируем предупреждение, чтобы админ знал о проблеме.
- **Связанные ошибки:** #030 (это доработка фикса #030)

---

## 032 — Кнопка "Сменить админа" показывает usage вместо FSM-диалога

- **Дата:** 2026-07-21
- **Статус:** ✅ Исправлено
- **Описание:** Super-admin нажимает кнопку «🔄 Сменить админа» в админ-меню. Вместо FSM-диалога (ввод @channel и new_user_id) получает сообщение: «Использование: /change_admin <channel_id> <new_user_id>».
- **Анализ:**
  - **Был вызов:**

    Пользователь кликает кнопку с `callback_data="admin_menu:change_admin"`. Callback-хендлер `cmd_callback` (строка 1889) обрабатывает её и попадает в блок `input_actions` (строка 2215-2227): устанавливает `AwaitingAdminInput.text` state и отправляет приглашение ввести параметры.

    Однако если пользователь после этого (или вместо этого) вводит текстовую команду `/change_admin`, срабатывает **не** FSM-хендлер `_handle_admin_input`, а **текстовый** команда-хендлер `sa_change_admin`, потому что:

    1. `sa_change_admin` зарегистрирован на строке 125: `self.dp.message.register(self.sa_change_admin, Command("change_admin"))` — **без StateFilter**
    2. `_handle_admin_input` зарегистрирован на строке 131: `self.dp.message.register(self._handle_admin_input, StateFilter(AwaitingAdminInput.text))`
    3. aiogram 3 проверяет хендлеры в порядке регистрации. Первый подошедший — `sa_change_admin` (строка 125), так как у него нет StateFilter, и он подходит для любого сообщения `/change_admin`, включая те, что пришли во время FSM.
    4. В `sa_change_admin` (строка 1197-1224): `args = message.text.split(maxsplit=2)` → если аргументов меньше 3, выводится usage-сообщение (строка 1204-1205).

  - **Корень проблемы (подтверждено: `app/platforms/telegram/bot.py:125`):**

    `Command("change_admin")` не имеет `StateFilter`, поэтому перехватывает сообщения `/change_admin` даже когда пользователь находится в состоянии `AwaitingAdminInput.text`. FSM-хендлер `_handle_admin_input` (строка 131) не успевает сработать.

  - **Аналогичная проблема** у других команд, имеющих FSM-альтернативу:
    - `sa_channel_info` (строка 119) — `Command("channel_info")`, без StateFilter
    - `sa_user_info` (строка 120) — `Command("user_info")`, без StateFilter
    - `sa_admin_cancel` (строка 121) — `Command("admin_cancel")`, без StateFilter
    - `admin_subscribe` (строка 112) — `Command("subscribe")`, без StateFilter
    - `admin_unsubscribe` (строка 113) — `Command("unsubscribe")`, без StateFilter

- **Исправление (подтверждено: `app/platforms/telegram/bot.py:125`):**

  Добавить `StateFilter(None)` в регистрацию `sa_change_admin`, чтобы хендлер срабатывал **только** когда пользователь не находится ни в одном FSM-состоянии. Когда пользователь в `AwaitingAdminInput.text`, сообщение `/change_admin` будет обработано FSM-хендлером `_handle_admin_input`.

  ```python
  # Было (строка 125):
  self.dp.message.register(self.sa_change_admin, Command("change_admin"))

  # Стало:
  self.dp.message.register(self.sa_change_admin, Command("change_admin"), StateFilter(None))
  ```

  **Дополнительно:** Аналогично стоит поправить регистрацию других команда-хендлеров, конфликтующих с FSM:
  - `sa_channel_info` (строка 119)
  - `sa_user_info` (строка 120)
  - `sa_admin_cancel` (строка 121)
  - `admin_subscribe` (строка 112)
  - `admin_unsubscribe` (строка 113)

- **Связанные ошибки:** нет
---

## 038 — Инлайн-кнопка "Список каналов" не реагирует на нажатие

- **Дата:** 2026-07-21
- **Статус:** ✅ Исправлено
- **Описание:** Super-admin нажимает кнопку "📋 Список каналов" в админ-меню. Спиннер на кнопке гаснет, но сообщение не меняется — создаётся ощущение, что кнопка "не реагирует".
- **Анализ:**
  - **Корень проблемы (подтверждено: `app/platforms/telegram/bot.py:2036`):**
    
    `callback.answer()` вызывался ДО выполнения работы (на строке 2036, сразу при входе в `admin_menu:`). Если последующий код (`edit()` на строке 2140) выбрасывал исключение (ошибка БД, таймаут, превышение лимита символов), Telegram уже убирал спиннер, а сообщение не менялось.

    Для `stats_all` (простые `SELECT COUNT`) исключений не было — поэтому она работала. Для `list_channels` (запрос всех каналов + N запросов админов) вероятность ошибки выше.

  - **Дополнительно:** Во всём блоке `admin_menu:` не было вызовов `callback.answer()` в return-путях — только один вызов в начале. Если исключение происходило после `callback.answer()`, пользователь видел только исчезновение спиннера.

- **Исправление:**
  1. Убран ранний `await callback.answer()` на строке 2036
  2. `callback.answer()` теперь вызывается ПОСЛЕ успешного `edit()` в каждом action-хендлере
  3. `list_channels` обёрнут в `try/except` с логированием ошибки и показом сообщения пользователю
  4. `callback.answer()` добавлен во все return-пути (включая ошибки доступа, отсутствие данных и FSM-старт)
  5. Затронутые хендлеры: `back`, `stats_all`, `check_expired`, `list_channels`, `health`, `events_all`, `my_channels`, `create_event`, `broadcast`, `input_actions`

---

## 039 — Lazy `from sqlalchemy import select` вызывает UnboundLocalError в кнопках админ-меню

- **Дата:** 2026-07-21
- **Статус:** ✅ Исправлено
- **Описание:** Кнопки «📋 Список каналов», «📊 Общая статистика» и «🔍 Проверить подписки» в админ-меню показывают «❌ Ошибка». В логах `UnboundLocalError: cannot access local variable 'select' where it is not associated with a value`.

- **Анализ:**
  - **Корень проблемы (подтверждено: `app/platforms/telegram/bot.py:2293`, семантика Python):**

    Внутри `cmd_callback` на строке 2293 был `from sqlalchemy import select` внутри блока `if event_ids:`:
    ```python
    if event_ids:
        async with async_session_factory() as session:
            from sqlalchemy import select  # ← lazy import
            stmt = select(Event).where(...)
    ```

    **Правило Python:** если в теле функции есть `import name` (или другое присваивание `name =`) хотя бы в одной ветке, **Python считает `name` локальной переменной во всей функции** — даже в тех ветках, которые идут ДО этого импорта.

    Хендлеры, выполняющиеся РАНЬШЕ (строки 2070-2140), используют `select()`. Python видит `select` как локальную переменную, но она ещё не инициализирована → `UnboundLocalError`.

  - **Почему другие кнопки работали:** не используют `select()` напрямую, либо уходят в отдельные методы (FSM).

  - **Почему глобальный импорт (строка 12) не спасал:** Python внутри `cmd_callback` игнорирует его из-за локального импорта на строке 2293.

- **Исправление (подтверждено: `app/platforms/telegram/bot.py:2293`):**

    Удалена строка `from sqlalchemy import select`. `select` уже импортирован глобально на строке 12. После удаления Python использует глобальный `select` во всей `cmd_callback`.

    ```python
    # Было:
    if event_ids:
        async with async_session_factory() as session:
            from sqlalchemy import select
            stmt = select(Event).where(...)
    # Стало:
    if event_ids:
        async with async_session_factory() as session:
            stmt = select(Event).where(...)
    ```

- **Добавлены тесты** (`TestAdminMenuSelectScope`):
  - `test_list_channels_success` / `test_list_channels_empty`
  - `test_stats_all_success`
  - `test_check_expired_success` / `test_check_expired_deactivates`
  - `test_admin_ev_page_pagination`

- **Связанные ошибки:** #038 (логировал ошибку `list_channels`, но не устранил корень)
