# TicketBot

## Деплой через self-hosted GitHub Actions runner

**Репозиторий:** `https://github.com/aerovir/ticketSellBot.git`

### Раннер

- Настроен на удалённом VPS как self-hosted runner
- Воркфлоу: `.github/workflows/deploy.yml`
- При пуше в `main` раннер автоматически разворачивает бота

### Secrets в GitHub (Settings → Secrets and variables → Actions)

| Secret | Описание |
|--------|---------|
| `TELEGRAM_TOKEN` | Токен Telegram бота от @BotFather |
| `VK_TOKEN` | Токен VK сообщества |
| `VK_GROUP_ID` | ID VK группы |
| `MAX_TOKEN` | Токен MAX бота |

### Структура

- `core/` — бизнес-логика (models, services, database)
- `platforms/` — адаптеры: telegram, vk, max
- `deploy/` — скрипты деплоя, Docker override, healthcheck
- `docs/` — документация

### Команды

```bash
make -C deploy up-beget      # запустить бота
make -C deploy logs-beget    # смотреть логи
make -C deploy down-beget    # остановить
```
