.PHONY: help up up-beget down logs seed ps clean deploy deploy-beget

help: ## Показать эту справку
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Базовые команды ──────────────────────────────────

up: ## Запустить бота + БД (универсальный)
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml up -d

down: ## Остановить все сервисы
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml down

restart: ## Перезапустить бота
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml restart app

logs: ## Посмотреть логи бота
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml logs -f app

ps: ## Статус контейнеров
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml ps

# ─── Beget ────────────────────────────────────────────

up-beget: ## Запустить на Beget (с оптимизацией под 1-2 GB RAM)
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml up -d

down-beget: ## Остановить всё на Beget
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml down

logs-beget: ## Логи на Beget
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml logs -f app

restart-beget: ## Перезапустить бота на Beget
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml restart app

seed: ## Залить тестовые мероприятия
	docker compose -f ../docker-compose.yml run --rm seed

clean-beget: ## Остановить и удалить всё (включая БД) на Beget
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml down -v

# ─── Деплой ──────────────────────────────────────────

deploy: ## Полный деплой: БД → миграции → seed → запуск
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml up -d db
	@echo "Ожидание БД..."
	@sleep 5
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml run --rm app python -c \
		"import asyncio; from app.core.database import init_db; asyncio.run(init_db())"
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml run --rm seed
	docker compose -f ../docker-compose.yml -f docker-compose.prod.yml up -d app
	@echo "✅ Деплой завершён"

deploy-beget: ## Полный деплой на Beget
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml up -d db
	@echo "Ожидание БД..."
	@sleep 5
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml run --rm app python -c \
		"import asyncio; from app.core.database import init_db; asyncio.run(init_db())"
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml run --rm seed
	docker compose -f ../docker-compose.yml -f docker-compose.beget.yml up -d app
	@echo "✅ Деплой на Beget завершён"
