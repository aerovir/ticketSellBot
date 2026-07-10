.PHONY: help up up-all down logs ps seed deploy deploy-beget

help: ## Показать эту справку
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Базовые команды ──────────────────────────────────

up: ## Запустить Telegram бота + БД (дефолтный профиль)
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml up -d telegram

up-all: ## Запустить всех ботов + БД
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml --profile all up -d

down: ## Остановить все сервисы
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml --profile all down

restart: ## Перезапустить Telegram бота
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml restart telegram

logs: ## Посмотреть логи Telegram бота
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml logs -f telegram

ps: ## Статус контейнеров
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml ps

# ─── Beget ────────────────────────────────────────────

up-beget: ## Запустить на Beget Telegram + БД
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml up -d telegram

up-beget-all: ## Запустить всех ботов на Beget
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml --profile all up -d

down-beget: ## Остановить всё на Beget
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml --profile all down

logs-beget: ## Логи Telegram на Beget
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml logs -f telegram

restart-beget: ## Перезапустить Telegram на Beget
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml restart telegram

seed: ## Залить тестовые мероприятия
	docker compose -f ../docker-compose.yml run --rm seed

clean-beget: ## Остановить и удалить всё (включая БД) на Beget
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml down -v

# ─── Деплой ──────────────────────────────────────────

deploy: ## Полный деплой: БД → init-db → seed → Telegram
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml up -d db
	@echo "Ожидание БД..."
	@sleep 5
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml run --rm \
		-e DB_PASSWORD_TG="${DB_PASSWORD_TG}" \
		-e DB_PASSWORD_VK="${DB_PASSWORD_VK}" \
		-e DB_PASSWORD_MAX="${DB_PASSWORD_MAX}" \
		db bash /app/scripts/init-db-roles.sh 2>/dev/null || true
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml run --rm \
		app python -m bot.seed 2>/dev/null || true
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml up -d telegram
	@echo "✅ Деплой Telegram завершён"

deploy-beget: ## Полный деплой на Beget
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml up -d db
	@echo "Ожидание БД..."
	@sleep 5
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml run --rm \
		-e DB_PASSWORD_TG="${DB_PASSWORD_TG}" \
		-e DB_PASSWORD_VK="${DB_PASSWORD_VK}" \
		-e DB_PASSWORD_MAX="${DB_PASSWORD_MAX}" \
		db bash /app/scripts/init-db-roles.sh 2>/dev/null || true
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml run --rm \
		app python -m bot.seed 2>/dev/null || true
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml up -d telegram
	@echo "✅ Деплой Telegram на Beget завершён"
