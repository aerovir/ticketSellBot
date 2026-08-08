# Учёт задач TicketBot

Формат записи:
- **Статус:** pending / in progress / done / cancelled
- **Описание:** что нужно сделать
- **Дата:** когда добавлена
- **Коммит / PR:** связанные изменения

---

## ✅ Выполненные

| # | Задача | Статус | Дата | Коммит |
|---|--------|--------|------|--------|
| 1 | Создать архитектуру проекта (core, platforms, config) | ✅ done | 2026-07-05 | — |
| 2 | Реализовать Telegram бота (aiogram, все команды) | ✅ done | 2026-07-05 | — |
| 3 | Реализовать VK бота (vkbottle, все команды) | ✅ done | 2026-07-05 | — |
| 4 | Реализовать MAX бота (заглушка) | ✅ done | 2026-07-05 | — |
| 5 | Настроить PostgreSQL (SQLAlchemy async + asyncpg) | ✅ done | 2026-07-05 | — |
| 6 | Создать seed-скрипт с тестовыми мероприятиями | ✅ done | 2026-07-05 | — |
| 7 | Обернуть проект в Docker (Dockerfile + docker-compose) | ✅ done | 2026-07-05 | — |
| 8 | Настроить GitHub Actions self-hosted runner | ✅ done | 2026-07-05 | `6d26730` |
| 9 | Настроить деплой на VPS (Beget/LightNode) | ✅ done | 2026-07-05 | — |
| 10 | Создать документацию проекта (CLAUDE.md, how-it-works.md) | ✅ done | 2026-07-05 | `e17488f` |
| 11 | Разделить entry point для всех платформ (run_*.py) | ✅ done | 2026-07-07 | `e17488f` |
| 12 | Починить init_db (таблицы не создавались при деплое) | ✅ done | 2026-07-07 | `29746ef` |
| 13 | Добавить retry при ошибках Telegram API | ✅ done | 2026-07-07 | `62752d3` |
| 14 | Создать реестр ошибок (docs/errors.md) | ✅ done | 2026-07-07 | — |
| 15 | Создать учёт задач (docs/tasks.md) | ✅ done | 2026-07-07 | — |

## 🔄 В работе

| # | Задача | Статус | Дата | Коммит |
|---|--------|--------|------|--------|
| 16 | Реальная оплата (YooKassa / ссылка на оплату) | 📌 pending | 2026-07-07 | — |
| 17 | VK группа — настройка и подключение | 📌 pending | 2026-07-07 | — |
| 18 | MAX — подключение после выхода SDK | 📌 pending | 2026-07-07 | — |
| 20 | Telegram канал: анонсы + channel_post хендлеры | ✅ done | 2026-07-07 | `99e177d` |
| 21 | Telegram канал: проверка /events и /event в работе | ✅ verified | 2026-07-07 | — |
| 22 | Добавить TELEGRAM_CHANNEL_ID в GitHub Secrets | ✅ done | 2026-07-07 | — |
| 23 | Админ-панель: управление мероприятиями через бота | ✅ done | 2026-07-07 | — |

## 📌 Запланировано

| # | Задача | Статус | Дата | Коммит |
|---|--------|--------|------|--------|
| 19 | Добавить уведомления о скором мероприятии | 📌 pending | 2026-07-07 | — |
| 20 | Написать тесты (pytest для core/services.py) | ✅ done | 2026-07-09 | — |
| 24 | Разделить процессы платформ (убрать launcher.py) | ✅ done | 2026-07-09 | — |
| 25 | Раздельные PostgreSQL-роли для каждой платформы | ✅ done | 2026-07-09 | — |
| 26 | Раздельные .env файлы (.env.telegram, .env.vk, .env.max) | ✅ done | 2026-07-09 | — |
| 27 | Docker Compose: Telegram как дефолт, VK/MAX в profile: all | ✅ done | 2026-07-09 | — |
| 28 | Тесты: database, services, TG/VK/MAX bot handlers | ✅ done | 2026-07-09 | — |
| 29 | Документация: README для каждой платформы | ✅ done | 2026-07-09 | — |
| 30 | Multi-tenant: модель Channel, изоляция мероприятий по каналам | ✅ done | 2026-07-11 | `acc7953` |
| 31 | Multi-tenant: миграция 0002 (channels + channel_id в events) | ✅ done | 2026-07-11 | `acc7953` |
| 32 | Multi-tenant: ChannelService (подписки, каналы админа) | ✅ done | 2026-07-11 | `acc7953` |
| 33 | Подписка: /subscribe <channel_id> <days> для super-admin | ✅ done | 2026-07-11 | `913b104` |
| 34 | Подписка: /unsubscribe <channel_id> для super-admin | ✅ done | 2026-07-11 | `e937599` |
| 35 | Подписка: проверка `is_subscription_valid()` при каждом действии | ✅ done | 2026-07-11 | `acc7953` |
| 36 | Админ-меню: inline-кнопки вместо текстовых команд | ✅ done | 2026-07-11 | `3f6e66f` |
| 37 | Админ-меню: ролевое разделение (super-admin vs channel admin) | ✅ done | 2026-07-11 | `3f6e66f` |
| 38 | Super-admin команды: /stats_all, /list_channels, /channel_info, /user_info, /admin_cancel, /broadcast, /health | ✅ done | 2026-07-11 | `3f6e66f` |
| 39 | Super-admin: /check_expired, /change_admin | ✅ done | 2026-07-11 | `3f6e66f` |
| 40 | FSM: исправлен порядок callback.answer() в create_event (кнопка подтвердить) | ✅ done | 2026-07-11 | `a7f15ff` |
| 41 | Deploy: миграция через alembic stamp + ALTER TABLE ADD COLUMN IF NOT EXISTS | ✅ done | 2026-07-11 | `bed6e60`, `b5eb13a`, `1449908`, `a7d6e6a` |
| 42 | Deploy: очистка тестовых seed-данных при деплое | ✅ done | 2026-07-11 | `913b104` |
| 43 | Legacy канал: автопривязка к первому админу (_get_admin_channel fallback) | ✅ done | 2026-07-11 | `913b104` |
| 44 | Тесты: обновлены для multi-tenant (fixture sample_channel, channel_id) | ✅ done | 2026-07-11 | `f886a16`, `f8846be`, `18e56ed` |
| 45 | Удалён TELEGRAM_CHANNEL_ID из конфига и .env | ✅ done | 2026-07-11 | `acc7953` |
| 46 | Канал: my_chat_member хендлер (обнаружение добавления бота) | ✅ done | 2026-07-11 | `acc7953` |
| 47 | Fix: GRANT USAGE → GRANT USAGE, CREATE ON SCHEMA public для платформенных ролей БД | ✅ done | 2026-07-12 | `2a8c29b` |
| 48 | Fix: admin_menu кнопки выполняют действие вместо показа команды | ✅ done | 2026-07-12 | `e3b7167` |
| 49 | Fix: UnboundLocalError — select импортирован внутри блока, недоступен в других блоках | ✅ done | 2026-07-12 | `305691e` |
| 50 | Feat: FSM-ввод параметров для кнопок админ-меню группы Б (channel_info, subscribe, и др.) | ✅ done | 2026-07-12 | `e2fa6a8` |
| 51 | Fix: Missing imports — TicketStatus, PaymentStatus, User, Event, Ticket, Payment | ✅ done | 2026-07-12 | `e2fa6a8` |
| 52 | Feat: Кнопка «🎛 Управление» на анонсах в канале — гибридная админ-панель через ЛС | ✅ done | 2026-07-12 | `2560555` |
| 53 | Fix: Каналу при подписке назначается суперадмин вместо реального админа | ✅ done | 2026-07-13 | — |
| 54 | Fix: нейминг ролевой модели (_is_admin → _is_super_admin, _is_channel_admin → _has_admin_access) | ✅ done | 2026-07-16 | — |
| 55 | Fix: /my_channels проверял super-admin вместо channel admin (баг) | ✅ done | 2026-07-16 | — |
| 56 | Feat: верификация админа канала через Telegram API (get_chat_member) при каждом действии | ✅ done | 2026-07-16 | — |
| 57 | Fix: on_chat_member_update не обрабатывал статус "administrator" (каналы) | ✅ done | 2026-07-16 | — |
| 58 | Refactor: устранены двойные вызовы _get_admin_channel в хендлерах | ✅ done | 2026-07-16 | — |
| 59 | Fix: _verify_channel_admin теперь возвращает True/False/None (не деактивирует подписку при ошибке API) | ✅ done | 2026-07-16 | — |
| 60 | Fix: on_chat_member_update обновляет telegram_channel_id для голых чисел (без -100) | ✅ done | 2026-07-16 | — |
| 61 | Fix: _verify_channel_admin возвращает None → доверяем БД и возвращаем канал (вместо skip) | ✅ done | 2026-07-18 | — |
| 62 | Feat: multi-admin каналов — новая модель ChannelAdmin, getChatAdministrators, синхронизация всех админов | ✅ done | 2026-07-18 | — |
| 63 | Fix: /subscribe существующего канала не синхронизирует админов (прочерк в списке каналов) | ✅ done | 2026-07-18 | — |
| 64 | Feat: улучшение диалога создания мероприятия — _fsm_header, inline-кнопка Пропустить, новые формулировки | ✅ done | 2026-07-18 | — |
| 65 | Feat: _format_event_text — унифицированное форматирование мероприятий (Phase 2) | ✅ done | 2026-07-23 | `a0835d0` |
| 66 | Feat: структурированное JSON-логирование поведения пользователя (app/core/logging_config.py) | ✅ done | 2026-07-24 | — |
| 67 | Feat: логирование сервисного слоя — EventService, TicketService, ChannelService, UserService | ✅ done | 2026-07-24 | — |
| 68 | Feat: логирование ключевых хендлеров Telegram-бота (start, buy, callback, chat_member) | ✅ done | 2026-07-24 | — |
| 69 | Feat: управление публикацией мероприятия — поле is_published, черновики, кнопка Опубликовать | ✅ done | 2026-07-24 | — |
| 70 | Feat: афиша мероприятия (медиа-файлы через Telegram File Server) | ✅ done | 2026-07-24 | — |
| 71 | Feat: duration_ms на все read-методы сервисного слоя (14 методов) | ✅ done | 2026-07-26 | — |
| 72 | Feat: фоновый сбор метрик системы (app/core/system_metrics.py) | ✅ done | 2026-07-26 | — |
| 73 | Feat: скрипт самодиагностики с порогами + Telegram-алерт (scripts/self-diagnose.py) | ✅ done | 2026-07-26 | — |
| 74 | Feat: добавлены Makefile-цели diagnose, diagnose-alert, diagnose-verbose | ✅ done | 2026-07-26 | — |
| 75 | Feat: psutil как основная зависимость (перенесён из [monitoring] в core) | ✅ done | 2026-07-26 | — |
| 76 | Feat: автоматический алерт при превышении порогов (в metrics_loop бота) | ✅ done | 2026-07-26 | — |
| 77 | Feat: cron-диагностика раз в 5 мин (scripts/cron-diagnose.py) | ✅ done | 2026-07-26 | — |
| 78 | Feat: cron-задание устанавливается GitHub Actions при деплое (deploy.yml) | ✅ done | 2026-07-26 | — |
| 79 | Chore: удалён setup_cron_diagnose из setup-dev-env.sh (теперь в CI/CD) | ✅ done | 2026-07-26 | — |
| 80 | Chore: удалены install/remove-cron-diagnose из Makefile (теперь в CI/CD) | ✅ done | 2026-07-26 | — |
| 81 | Fix: self-diagnose.py — флаг --logs-from-stdin для пайпа логов в контейнер | ✅ done | 2026-07-26 | — |
| 82 | Fix: cron-diagnose.py — сбор логов на хосте, запуск diagnose внутри контейнера | ✅ done | 2026-07-26 | — |
| 83 | Fix: cron-diagnose.py — datetime.utcnow() → datetime.now(timezone.utc) | ✅ done | 2026-07-26 | — |
| 84 | Feat: SubscriptionTier (basic/pro) + Channel.subscription_tier | ✅ done | 2026-07-26 | — |
| 85 | Feat: TicketStatus.checked_in + validation_code, checked_in_at/by, is_free | ✅ done | 2026-07-26 | — |
| 86 | Feat: ChannelService.activate_subscription с tier, get_subscription_tier, require_feature | ✅ done | 2026-07-26 | — |
| 87 | Feat: EventService проверяет tier при создании (basic не может price>0) | ✅ done | 2026-07-26 | — |
| 88 | Feat: TicketService.generate_validation_code, validate_ticket, check_in, check_in_by_code | ✅ done | 2026-07-26 | — |
| 89 | Feat: /check <code> команда для админа на входе | ✅ done | 2026-07-26 | — |
| 90 | Feat: разные кнопки для бесплатных/платных мероприятий | ✅ done | 2026-07-26 | — |
| 91 | Feat: /subscribe с аргументом tier (basic/pro) | ✅ done | 2026-07-26 | — |
| 92 | Tests: 62 тестов сервисного слоя (все проходят) | ✅ done | 2026-07-26 | — |

## 📌 Запланировано

| # | Задача | Статус | Дата | Коммит |
|---|--------|--------|------|--------|
| 93 | QR-генерация для Pro-мероприятий | 📌 pending | 2026-07-26 | — |
| 94 | Telegram Mini App сканер QR для админа | 📌 pending | 2026-07-26 | — |
| 95 | Экспорт списка участников (CSV) | 📌 pending | 2026-07-26 | — |
| 96 | Fix: синхронизация админов при активации подписки на новый канал | ✅ done | 2026-07-26 | — |
| 97 | Docs: описание бага #040 в errors.md + тесты | ✅ done | 2026-07-26 | — |
| 98 | Feat: кнопка «🔍 Проверить билет» в админ-меню (для всех админов) | ✅ done | 2026-07-26 | — |
| 99 | Feat: /check в Menu Button бота | ✅ done | 2026-07-26 | — |
| 100 | Feat: отправка кода билета в ЛС после покупки | ✅ done | 2026-07-26 | — |
| 101 | Fix: try/except в cmd_check и FSM check_ticket (обработка ошибок) | ✅ done | 2026-07-26 | — |
| 102 | Chore: убран /check из Menu Button (оставлен в админ-меню) | ✅ done | 2026-07-26 | — |
| 103 | Feat: личный кабинет + админка в Telegram Mini App (роли user/channel-admin/super-admin) | ✅ done (код) | 2026-08-05 | — |
| 104 | Feat: веб-API админки — мероприятия CRUD, publish/repost/toggle/delete, статистика, билеты+check-in, CSV, каналы+подписки, общая статистика | ✅ done (код) | 2026-08-05 | — |
| 105 | Feat: перенос покупок/админки из inline-кнопок в web (MenuButtonWebApp, WebApp-кнопка в анонсах, /start и /menu → кабинет) | ✅ done (код) | 2026-08-05 | — |
| 106 | Feat: WEBAPP_URL в CI (.env.telegram) для работы WebApp-кнопок на проде | ✅ done | 2026-08-05 | — |
| 107 | Тесты: 28 новых (admin API 16, сервисы 9, бот 1) — всего 168 | ✅ done | 2026-08-05 | — |
| 108 | Деплой веб-кабинета на прод (pochtibot.online) и живой тест | 📌 pending | 2026-08-05 | — |
| 109 | Feat: закрытие пробелов супер-админа в web — создать канал + подписка (POST /api/admin/channels), инфо о пользователе, рассылка, здоровье | ✅ done (код) | 2026-08-05 | — |
| 110 | Тесты: +13 (админ-эндпоинты 9, сервисы 2, бот 2) — всего 181 | ✅ done (код) | 2026-08-05 | — |
| 111 | Feat: система пригласительных для pro (invite tickets) — квота на мероприятии, выдача 1/2/3 чел., отмена, статистика (выдано/использовано/свободно) | ✅ done (код) | 2026-08-05 | — |
| 112 | Feat: QR-коды для всех билетов и пригласительных (фича qr_codes: pro), показ/скачивание в кабинете, deep-link invite_<code> в боте | ✅ done (код) | 2026-08-05 | — |
| 113 | TDD: сначала тесты, потом код (правило в CLAUDE.md + memory) | ✅ done | 2026-08-05 | — |
| 114 | Тесты: +23 (пригласительные 15, web-api 8) — всего 204 | ✅ done (код) | 2026-08-05 | — |
| 115 | Деплой пригласительных + QR на прод и живой тест | 📌 pending | 2026-08-05 | — |
| 116 | Feat: полный контур тестирования — харнесс имитации пользователя (Подход A) покрывает весь user-flow | ✅ done (код) | 2026-08-06 | — |
| 117 | Харнесс: Update-билдеры (callback/channel_post/my_chat_member), FakeSession GetChatAdministrators/DeleteMessage | ✅ done | 2026-08-06 | — |
| 118 | Бот-сценарии: inline buy legacy, channel_buy redirect, FSM create, publish, /check, invite deep-link, my_tickets+cancel, анонс с WebApp | ✅ done | 2026-08-06 | — |
| 119 | Web-сквозной flow на реальной БД (db_client + httpx ASGITransport): browse→buy→tickets→admin→invite→checkin→stats | ✅ done | 2026-08-06 | — |
| 120 | Покрытие непокрытых эндпоинтов (toggle/delete/repost/update/… +14 тестов) | ✅ done | 2026-08-06 | — |
| 121 | Тесты: всего 230 (206 → +24) | ✅ done | 2026-08-06 | — |
| 122 | Deploy: полный контур тестирования на CI | 📌 pending | 2026-08-06 | — |
| 123 | Feat: управление подпиской канала для super-admin — смена типа + срока (дни/месяцы/годы), POST /admin/channels/{id}/subscription и /tier | ✅ done | 2026-08-06 | — |
| 124 | Тесты: +9 (сервисы 5, web-api 4) — всего 239 | ✅ done | 2026-08-06 | — |
| 125 | QA-верификация фичи через агента (8 сквозных сценариев, 403/404/400, срок от now) | ✅ done | 2026-08-06 | — |
| 126 | Feat: роль «Организатор» + подписка на пользователя (без канала, Mini App) — User.subscription_*, Event.owner_user_id, role organizer | ✅ done (код) | 2026-08-07 | — |
| 127 | Fix: #050 owner-мероприятия недоступны организатору на админ-действиях (403) — хелпер _can_manage_event | ✅ done | 2026-08-07 | — |
| 128 | Тесты: +6 (organizer e2e) +4 (owner access) — всего 258 | ✅ done | 2026-08-07 | — |
| 129 | Deploy: роль организатора на прод + миграция (users.subscription_*, events.owner_user_id) | 📌 pending | 2026-08-07 | — |
| 130 | QA: полное сквозное тестирование организатора (11 функций, реальная БД) — 266 тестов | ✅ done | 2026-08-07 | — |
| 131 | Fix: #052 организатор без канала выдаёт пригласительные (про-гейт по подписке пользователя) | ✅ done | 2026-08-07 | — |
| 132 | Fix: #053 checkin проверяет доступ организатора (403 для чужого) + SAWarning на owner-событиях | ✅ done | 2026-08-07 | — |
| 133 | Dev-копия на VDS для «живого» теста — изолированный compose-проект (db/web/telegram), БД ticketbot_dev, порт 8081 | ✅ done | 2026-08-07 | — |
| 134 | Живой тест организатора против dev-копии — 12 функций PASS | ✅ done | 2026-08-07 | — |
| 135 | QA-агент дополнен разделом «Живой тест против dev-копии» (чек-лист организатора) | ✅ done | 2026-08-07 | — |
| 136 | UI: добавлено редактирование имени (PATCH /api/me) в профиле + инфо о канале (GET /api/admin/channels/{id}) | ✅ done | 2026-08-07 | — |
| 137 | Feat: сопоставление UI с подписками — QR-гейт (pro) + UI-адаптация (isPro, скрытие pro-функций для basic) | ✅ done | 2026-08-07 | — |
| 138 | Feat: режим «только web» — убраны все команды бота кроме входа (start/menu/admin), сохранены my_chat_member + deep-links | ✅ done | 2026-08-07 | — |
| 139 | Feat: открытое создание мероприятий (любой пользователь) + эндпоинт покупки подписки POST /api/me/subscription | ✅ done | 2026-08-07 | — |
| 140 | Feat: тестирование от лица пользователя — E2E реального пути, контрактные тесты ролей, QA-агент, smoke-скрипт | ✅ done | 2026-08-07 | — |
| 141 | Fix: расхождение frontend/backend — открыто создание мероприятий для обычных пользователей (UI + API), +7 контрактных тестов, QA-верификация | ✅ done | 2026-08-07 | `fc3a115` |
| 142 | Feat: самообслуживание каналов — POST/GET /api/me/channels, UI «Мои каналы» (список + форма добавления), DM-fallback при публикации (бот не в канале → анонс в личку), форма мероприятия — все каналы без фильтра подписки | ✅ done | 2026-08-07 | `1523514` |
| 143 | Fix: убрать гейт is_admin из POST /api/me/channels — любой пользователь может добавить СВОЙ канал. Защита: уникальность telegram_channel_id + анти-захват (409) + DM-fallback | ✅ done | 2026-08-07 | `da58353` |
| 144 | Refactor: убрать статусы подписок из /api/me/channels — только id, telegram_channel_id, title. Подписка только у пользователя | ✅ done | 2026-08-07 | `30a2275` |
| 145 | Feat: публикация с выбором канала на странице мероприятия. POST /admin/events/{id}/publish принимает channel_id. Публикация многократная в разные каналы | ✅ done | 2026-08-07 | `fc5f43b` |
| 146 | Fix: `_can_manage_event` сначала owner_user_id, потом channel_id — владелец не теряет доступ при наличии канала | ✅ done | 2026-08-07 | `b0ba541` |
| 147 | Perf: pool конфигурация — pool_recycle=1800, pool_pre_ping=True, pool_size=5, max_overflow=5. Предотвращает мёртвые соединения после OOM-kill | ✅ done | 2026-08-08 | `48e18ef` |
| 148 | Arch: единая сессия на запрос — `Depends(get_session)` (отложено: требует переработки тестовой инфраструктуры) | 📋 planned | 2026-08-08 | — |
| 149 | Feat: Prometheus + postgres_exporter + FastAPI instrumentator — /metrics, метрики БД, Grafana datasource | ✅ done | 2026-08-08 | `44c68c4` |
