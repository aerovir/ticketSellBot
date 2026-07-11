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
- **Коммит:** (текущий)
- **Связанные ошибки:** нет
