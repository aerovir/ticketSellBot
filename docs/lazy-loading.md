# Lazy-loading в SQLAlchemy: политика проекта

**Дата:** 2026-07-09
**Статус:** утверждено

---

## Политика

В проекте **запрещён lazy-loading** (ленивая загрузка связанных объектов).

Все relationship в моделях используют `lazy="raise"` — при случайной попытке обратиться к связанному объекту через атрибут модели будет выброшена ошибка:

```
sqlalchemy.exc.InvalidRequestError: 'User.tickets' is not available
  due to lazy='raise'
```

## Обоснование

### 1. Производительность

Lazy-loading генерирует **N+1 запросов**:

```python
# ❌ Lazy-loading (N+1)
events = await session.execute(select(Event))
for event in events.scalars():
    print(event.tickets)  # ← отдельный SELECT для каждого event

# ✅ Явный JOIN (1 запрос)
stmt = select(Event, Ticket).join(Ticket)
result = await session.execute(stmt)
```

### 2. Асинхронность

С асинхронным SQLAlchemy lazy-loading требует активной сессии. Попытка обратиться к `user.tickets` после закрытия сессии падает с `DetachedInstanceError`.

### 3. Явность

Все запросы к связанным данным пишутся **явно** через `select()` + `join()` в сервисах — код читается сверху вниз, не нужно гадать, где выполнится неявный SELECT.

## Исключения

Исключений нет. Если нужны связанные данные — пишется `select().join()` в сервисе.

## Где задано

**Файл:** `app/core/models.py`

| Модель | Relationship | lazy= |
|--------|------------|-------|
| `User` | `.tickets` → `Ticket.user` | `"raise"` |
| `Event` | `.tickets` → `Ticket.event` | `"raise"` |
| `Ticket` | `.event → Event.tickets` | `"raise"` |
| `Ticket` | `.user → User.tickets` | `"raise"` |
| `Ticket` | `.payment → Payment.ticket` | `"raise"` |
| `Payment` | `.ticket → Ticket.payment` | `"raise"` |

## Как получить связанные данные (правильный путь)

```python
# Вместо:
user = await session.get(User, user_id)
user.tickets  # ❌ lazy="raise" — ошибка

# Нужно:
from sqlalchemy import select
from app.core.models import Ticket

stmt = select(Ticket).where(Ticket.user_id == user_id)
result = await session.execute(stmt)
tickets = result.scalars().all()

# Или через сервис:
tickets = await TicketService(session).get_user_tickets(user_id)
```

## Зачем тогда relationship?

Relationship в моделях существуют **только** для:
1. **`back_populates`** — ORM-связь для корректной работы сессии и каскадов
2. **Типизации** — подсказки IDE о структуре модели
3. **Будущих явных eager load** — если когда-нибудь понадобится `selectinload()`, relationship должен быть объявлен

Реальное обращение к данным через атрибуты relationship — **всегда ошибка**.
