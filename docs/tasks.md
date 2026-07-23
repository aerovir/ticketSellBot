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
| 16 | Реальная оплата (YooKassa / ссылка на оплату) | 🔄 pending | 2026-07-07 | — |
| 17 | VK группа — настройка и подключение | 🔄 pending | 2026-07-07 | — |
| 18 | MAX — подключение после выхода SDK | 🔄 pending | 2026-07-07 | — |
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
