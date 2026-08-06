# Контур тестирования с имитацией пользователя в Telegram — исследование

**Дата:** 2026-08-06
**Статус:** ✅ Подход A реализован (харнесс имитации); Подход B (MTProto) — план

---

## Что реализовано (Подход A, 2026-08-06)

Полный контур имитации работает — **230 тестов**:

- **`tests/harness.py`** — `FakeTelegramSession(BaseSession)` перехватывает исходящие Telegram API; Update-билдеры: `make_message_update`, `make_callback_update`, `make_channel_post_update`, `make_chat_member_update`.
- **`tests/test_telegram_sim.py`** — 10 бот-сценариев через `Dispatcher.feed_update` (реальный конвейер: фильтры/FSM/хендлеры): `/start`, `/start buy_<id>`, inline `buy:`, `channel_buy` redirect, FSM create event, `ch_admin:publish`, `/check`, invite deep-link, `/my_tickets`+cancel, анонс с WebApp, `channel_post`.
- **`tests/test_web_api.py` `TestCabinetFlow`** — сквозной web-flow на реальной БД (`db_client` + httpx ASGITransport): browse→buy→tickets→admin→invite→checkin→stats.
- **`TestCoverageGaps`** — +14 тестов непокрытых эндпоинтов.
- Ошибки построения: `docs/errors.md` #045-#048.

**Ключевые решения:**
- `db_client` — `pytest_asyncio` + `httpx.AsyncClient(ASGITransport)` (тот же event loop, что и `db_session`; TestClient зависал — кросс-loop, #048).
- Роли в сквозном тесте — через реальные зависимости (channel-admin через `sync_admins`), не через `admin_auth` (мокает UserService, ломал buy, #048).

---

## Цель

Построить контур тестирования, который имитирует **поведение реального пользователя в Telegram** (шлёт `/start`, жмёт inline-кнопки, читает ответы бота) — а не только мокает aiogram.

---

## Текущее состояние (что уже есть)

- **203-204 теста**, но **Telegram-слой полностью замокан**:
  - Бот тестируется **прямыми вызовами хендлеров** (`await bot.cmd_start(mock_message)`) — минуя Dispatcher, фильтры, FSM-маршрутизацию и Telegram API
  - `mock_message`/`mock_callback` — `AsyncMock`, реального пользователя нет
  - Реальная БД (`ticketbot_test`) только в service-тестах; бот-хендлеры мокают `async_session_factory`
  - **Ни одного e2e** — ручной live-тест по `docs/test-plan-manual.md`
- **aiogram 3.29 не имеет** официальных тест-хелперов (нет `aiogram.testing`, `Dispatcher.test_mode`)

**Чистые «швы» в aiogram для построения харнесса:**
- `Dispatcher.feed_update(bot, update)` — гоняет весь конвейер: middleware → фильтры → FSM → хендлер
- `Bot(token, session=fake)` — инъектируемая сессия перехватывает все исходящие API-вызовы
- `MemoryStorage` — FSM работает out-of-the-box
- `Update.model_validate(raw_dict, context={"bot": bot})` — строит реальный Update

---

## Три способа имитации пользователя

| | **A. Свой харнесс на aiogram** | **B. MTProto-клиент (Telethon/Pyrogram)** | **C. Локальный Bot API server (tdlib)** |
|---|---|---|---|
| Что имитирует | Telegram **API** (пользователь виртуальный) | **Реального пользователя** через настоящий Telegram | Локальную копию Telegram |
| Как | `feed_update` + фейк-сессия | Клиент шлёт /start, жмёт кнопки, читает ответы | Свой Bot API server + userbot |
| Нужен аккаунт? | ❌ | ✅ api_id/api_hash + тестовый аккаунт | ✅ api_id/api_hash |
| Скорость | ⚡ мгновенно | 🐢 реальная сеть | средняя |
| CI-совместимость | ✅ полностью | ⚠️ нужен аккаунт/сессия | ⚠️ тяжёлый (C++/tdlib) |
| Трудоёмкость | 1-2 дня | 1 день + настройка аккаунта | избыточно |

### Ключевые инструменты для Подхода B

- **Pyrogram `test_mode=True`** → тестовые серверы Telegram: номера вида `99966XYYYY`, код подтверждения = повтор DC-цифры. **Не нужен реальный телефон** — отдельный тестовый датацентр, не мешает проду.
- **teletest-api** (dexoon/teletest-api) — готовый сервис (FastAPI + Telethon): `POST /send-message`, `POST /press-button`, `GET /get-messages` — имитация пользователя по HTTP.
- **Telethon** — нативно: `client.send_message('bot', '/start')`, чтение ответов, нажатие inline-кнопок.
- **Креды:** `api_id`/`api_hash` из [my.telegram.org](https://my.telegram.org) (привязаны к разработчику, не к пользователю).

---

## Рекомендуемая архитектура — двухуровневый контур

1. **Внутренний харнесс (Подход A) — основной.**
   Быстрый, детерминированный, в CI. Имитирует полный конвейер бота (Dispatcher → FSM → хендлеры) на реальной тестовой БД. Запускается на каждый коммит.
   - Фейк-сессия `BaseSession` отвечает на `get_me`/`get_chat_member`/`set_my_commands`/`send_message`/`edit_text` и записывает ответы
   - `async_session_factory` направляется на `TEST_DATABASE_URL`

2. **Дымовой e2e через MTProto (Подход B) — периодический.**
   Против реального прод-бота или отдельного dev-бота. Имитирует **настоящего пользователя**: /start → покупка → inline-кнопка → /check. Через teletest-api или нативный Telethon в `scripts/`.

**Подход C** — избыточен: тяжеловесный (сборка tdlib/C++), нужны те же креды, что у B, а выигрыша для проекта нет.

---

## Что нужно от пользователя

### Для Подхода A (внутренний харнесс) — почти ничего
- ✅ Существующая тестовая БД `ticketbot_test` (локально уже есть)
- ✅ Право запускать pytest локально
- Отдельных кредов не требуется

### Для Подхода B (e2e через MTProto)
- **`api_id` / `api_hash`** из [my.telegram.org](https://my.telegram.org) → API Development Tools
- **Тестовый аккаунт:** тестовый номер `99966XYYYY` (без реального телефона) **или** реальный тестовый аккаунт
- **Сессия** (session string) — генерируется при первом входе, хранится как секрет
- **Решение:** тестировать против прод-бота или **отдельного dev-бота** (рекомендуется: dev-бот с тем же кодом, чтобы не трогать прод)

---

## Связанные документы
- `docs/test-plan-manual.md` — ручной план тестирования
- `docs/test-log.md` — журнал ручных сессий
