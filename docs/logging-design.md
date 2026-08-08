# Система логирования и мониторинга — проект

**Дата:** 2026-08-08  
**Контекст:** расследование CPU-проблемы на VDS заняло часы из-за отсутствия метрик на уровне БД и приложения. Системные метрики собираются раз в минуту, но нет данных о пуле соединений, нет трассировки запросов, нет экспорта метрик PostgreSQL.

---

## Что есть сейчас

| Компонент | Статус | Где |
|-----------|--------|-----|
| JSON-логи в stdout | ✅ | `logging_config.py` |
| Promtail → Loki → Grafana | ✅ | `deploy/docker-compose.monitoring.yml` |
| Системные метрики (CPU/RAM/Disk/Load) | ✅ раз в 60с | `system_metrics.py` — только в Telegram-боте |
| Алерты в Telegram | ✅ | `system_metrics.py:129` |
| event_type в логах | ✅ | `services.py` — user.created, ticket.purchased, ... |
| duration_ms в логах | ✅ | `services.py` — каждый вызов сервиса |

## Чего не хватает

| Данные | Зачем | Как влияет на расследование |
|--------|-------|---------------------------|
| **Метрики пула соединений** | Видеть сколько соединений занято/свободно/overflow | Без них мы не знали что пул растёт до 15 соединений на сервис |
| **correlation_id (trace)** | Связать все логи одного HTTP-запроса | Без него нельзя понять сколько сессий БД создал один запрос |
| **Метрики PostgreSQL изнутри** | pg_stat_activity, pg_stat_statements | Без них неизвестно что делает PostgreSQL когда CPU 866% |
| **session_count на запрос** | Сколько `async with async_session_factory()` вызвано | Без метрики не узнали бы что publish = 4 сессии |
| **Метрики Docker контейнеров** | CPU/RAM per container | psutil даёт только хост-уровень |

---

## Проект

### Уровень 1: correlation_id — трассировка запроса

**Идея:** каждый HTTP-запрос получает уникальный ID, который передаётся во все логи внутри этого запроса.

```python
# middleware.py — новый файл
from contextvars import ContextVar
import uuid

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

class CorrelationMiddleware:
    async def __call__(self, request, call_next):
        cid = request.headers.get("X-Correlation-Id", str(uuid.uuid4())[:8])
        correlation_id.set(cid)
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = cid
        return response
```

**В логах:** каждое событие получает поле `correlation_id: "a1b2c3d4"`.

**Результат:** один grep по correlation_id → вся цепочка запроса: сколько сессий, какие запросы, сколько времени.

### Уровень 2: метрики пула соединений

**Идея:** логировать состояние пула SQLAlchemy каждые 30 секунд и после каждого запроса.

```python
# database.py — дополнить
async def log_pool_metrics():
    pool = engine.pool
    metrics = {
        "event_type": "db.pool_metrics",
        "pool_size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "total": pool.checkedin() + pool.checkedout(),
    }
    logger.info("", extra=metrics)
```

**Middlewares:** после каждого запроса логировать `db.session_count` — сколько раз был вызван `async_session_factory()`.

```python
# database.py — обернуть async_session_factory
_request_session_count: ContextVar[int] = ContextVar("session_count", default=0)

class SessionFactoryWrapper:
    def __call__(self):
        _request_session_count.set(_request_session_count.get() + 1)
        return async_session_factory()

# В middleware после запроса:
logger.info("", extra={
    "event_type": "http.request_done",
    "correlation_id": correlation_id.get(),
    "db_sessions": _request_session_count.get(),
    ...
})
```

**Результат:** видно что на страницу мероприятия уходит 5 сессий, на publish — 4.

### Уровень 3: экспорт метрик PostgreSQL

**Идея:** фоновая asyncio-задача (как `metrics_loop`), которая собирает `pg_stat_activity` и `pg_stat_statements` и пишет в лог.

```python
# postgres_metrics.py — новый файл
async def collect_pg_metrics():
    # 1. Активные запросы дольше 1 секунды
    long_queries = await session.execute(
        select(PgStatActivity).where(
            PgStatActivity.state == "active",
            PgStatActivity.query_start < now - timedelta(seconds=1),
        )
    )
    
    # 2. Количество соединений по состоянию
    conns_by_state = await session.execute("""
        SELECT state, COUNT(*) FROM pg_stat_activity 
        WHERE backend_type = 'client backend' GROUP BY state
    """)
    
    # 3. Топ-5 медленных запросов из pg_stat_statements
    slow_queries = ...
    
    logger.info("", extra={
        "event_type": "db.postgres_metrics",
        "long_queries": len(long_queries),
        "conns_by_state": dict(conns_by_state),
        "slow_queries_top5": slow_queries,
    })
```

**Запуск:** `metrics_loop` в `bot/web.py` (веб-сервер тоже должен собирать).

### Уровень 4: метрики Docker контейнеров

**Идея:** вместо psutil на хосте — собирать `docker stats` изнутри контейнера или через Docker API.

```python
# docker_metrics.py
async def collect_docker_metrics():
    # Через Docker socket (если проброшен) или docker-py
    import docker
    client = docker.from_env()
    for container in client.containers.list():
        stats = container.stats(stream=False)
        cpu = stats["cpu_stats"]["cpu_usage"]["total_usage"]
        mem = stats["memory_stats"]["usage"]
        mem_limit = stats["memory_stats"]["limit"]
        logger.info("", extra={
            "event_type": "system.docker_metrics",
            "container": container.name,
            "cpu_usage": cpu,
            "memory_bytes": mem,
            "memory_limit": mem_limit,
            "memory_percent": round(mem / mem_limit * 100, 1) if mem_limit else None,
        })
```

### Уровень 5: алерты с контекстом

**Идея:** при превышении порога — логировать не только системные метрики, но и снапшот БД (пул, активные запросы).

```python
async def alert_with_context(alert_type, metrics):
    # Снять снапшот пула и PostgreSQL
    pool_snapshot = await get_pool_snapshot()
    pg_snapshot = await get_pg_snapshot()
    
    logger.error("", extra={
        "event_type": "system.alert",
        "alert_type": alert_type,
        "metrics": metrics,
        "pool": pool_snapshot,
        "postgres": pg_snapshot,
    })
```

### Уровень 6: health endpoint с метриками

**Идея:** `GET /api/health` уже есть (SELECT 1). Добавить метрики в ответ:

```json
{
    "status": "ok",
    "db_pool": {"size": 5, "checked_in": 5, "checked_out": 0, "overflow": 0},
    "db_connections": {"active": 1, "idle": 4},
    "uptime_seconds": 3600
}
```

---

## Приоритеты

| Приоритет | Компонент | Сложность | Влияние |
|-----------|-----------|-----------|---------|
| **P0** | correlation_id (middleware) | низкая | Высокое — один grep вместо ручного сопоставления |
| **P0** | Метрики пула (log_pool_metrics) | низкая | Критичное — узнали бы о росте соединений за минуты |
| **P1** | session_count на запрос | низкая | Высокое — видно N+1 проблему сразу |
| **P1** | PostgreSQL метрики | средняя | Высокое — видно ЧТО именно делает PostgreSQL |
| **P2** | Health endpoint с метриками | низкая | Среднее — Grafana может скрейпить |
| **P2** | Алерты с контекстом | низкая | Среднее — меньше ручного анализа при инциденте |
| **P3** | Docker метрики | средняя | Низкое — Grafana и так показывает docker stats |

---

## Как выглядит расследование ДО и ПОСЛЕ

### До (сейчас)
```
1. Видим load 12.77 на Grafana → идём на сервер
2. top → видим postgres 866% CPU
3. pg_stat_activity → пусто (зомби)
4. Логи web → grep "event_type" → ручной подсчёт сессий
5. Часы на анализ
```

### После
```
1. Alert в Telegram: "CPU critical 866%, pool overflow 10/5, 23 active conns"
2. Loki: {event_type="db.pool_metrics"} → видим рост checked_out
3. Loki: {correlation_id="X"} → видим 5 сессий на один page view
4. pg_metrics: 0 active queries + 23 idle connections → зомби
5. 5 минут на анализ
```

---

## Файлы для реализации

| Файл | Назначение |
|------|-----------|
| `app/core/middleware.py` | CorrelationMiddleware, логирование session_count |
| `app/core/database.py` | pool_metrics(), обёртка session_count |
| `app/core/postgres_metrics.py` | сбор pg_stat_activity + pg_stat_statements |
| `app/web/routes.py` | health endpoint с метриками |
| `app/core/system_metrics.py` | alert_with_context() |
| `tests/test_logging.py` | тесты новых middleware и метрик |
