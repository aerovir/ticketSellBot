"""Унифицированное форматирование текста мероприятия (общее для бота и web)."""


def format_event_text(event, mode: str = "full") -> str:
    """Форматировать мероприятие в текст (HTML-safe для parse_mode=HTML).

    Args:
        event: Event (SQLAlchemy модель или объект с теми же атрибутами)
        mode: "full" — анонс/детали пользователя,
              "short" — пункт списка,
              "admin" — админ-панель/список

    Returns:
        str: форматированный текст
    """
    date_str = event.date.strftime("%d.%m.%Y %H:%M")

    if mode == "short":
        return (
            f"📌 <b>{event.title}</b>\n"
            f"📅 {date_str}\n"
            f"📍 {event.location or 'Не указано'}\n"
            f"💰 {event.price:.0f}₽ | Осталось: {event.available_tickets}/{event.total_tickets}\n"
        )

    if mode == "admin":
        status_icon = "🟢" if event.is_active else "🔴"
        status_text = "Активно" if event.is_active else "Отключено"
        publish_icon = "📢" if event.is_published else "📝"
        publish_text = "Опубликовано" if event.is_published else "Черновик"
        media_icon = "🖼" if event.media_telegram_file_id else "—"
        media_type_label = " 🎬" if event.media_type == "video" else ""
        media_text = f"Афиша: {media_icon}{media_type_label}" if event.media_telegram_file_id else "Афиша: —"
        return (
            f"{publish_icon} <b>{event.title}</b>\n"
            f"{event.description or 'Описание отсутствует'}\n\n"
            f"📅 {date_str}\n"
            f"📍 {event.location or 'Не указано'}\n"
            f"💰 {event.price:.0f}₽\n"
            f"🎟 Осталось: {event.available_tickets}/{event.total_tickets}\n"
            f"{status_icon} {status_text} | {publish_icon} {publish_text}\n"
            f"{media_text}"
        )

    # mode == "full" (по умолчанию)
    return (
        f"🎫 <b>{event.title}</b>\n\n"
        f"{event.description or 'Описание отсутствует'}\n\n"
        f"📅 {date_str}\n"
        f"📍 {event.location or 'Не указано'}\n"
        f"💰 {event.price:.0f}₽\n"
        f"🎟 Осталось билетов: {event.available_tickets}/{event.total_tickets}"
    )
