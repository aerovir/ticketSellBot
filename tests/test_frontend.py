"""
Фронтенд VK Mini App (#165): структурные smoke-тесты.

Проверяем, что vk-app.html переиспользует app.js (VK-детект), подключён
vk-bridge, и что общие страницы (index.html / vk-app.html) синхронны
по ключевым id.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "web" / "static"

APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
VK_APP = (STATIC / "vk-app.html").read_text(encoding="utf-8")


def test_vk_app_includes_bridge_and_appjs():
    assert "vk-bridge" in VK_APP
    assert "app.js" in VK_APP


def test_vk_app_has_common_page_ids():
    for pid in ["page-home", "page-events", "page-tickets", "page-profile",
                "page-admin", "page-my-vk-groups", "tabBar"]:
        assert pid in VK_APP


def test_index_has_vk_groups_page():
    # VK-группы доступны и из TG (организатор публикует в VK) — страница в обоих.
    assert 'id="page-my-vk-groups"' in INDEX
    assert 'id="page-my-vk-groups"' in VK_APP


def test_appjs_has_vk_auth():
    assert "initVKAuth" in APP_JS
    assert "VKWebAppGetLaunchParams" in APP_JS
    assert "X-VK-Init-Data" in APP_JS
    assert 'state.platform = "vk"' in APP_JS


def test_appjs_has_vk_groups_ui():
    assert "showMyVKGroups" in APP_JS
    assert "addMyVKGroup" in APP_JS
    assert "removeMyVKGroup" in APP_JS


def test_appjs_has_linking_ui():
    assert "createVKLinkCode" in APP_JS
    assert "linkVKByCode" in APP_JS
    assert "/api/me/link-code" in APP_JS
    assert "/api/me/link" in APP_JS


def test_appjs_initvk_handles_direct_object():
    # vk-bridge 3.x возвращает VKWebAppGetLaunchParams как объект НАПРЯМУЮ
    # (без обёртки launch_params): { vk_user_id, vk_ts, sign, ... }.
    # Раньше код читал только res.launch_params — из-за этого initData
    # оставался пустым и VK Mini App показывал «Откройте кабинет в Telegram».
    # 1. Прямой объект vk-bridge (sign на верхнем уровне) обрабатывается:
    assert "!res.sign" in APP_JS or "res.sign &&" in APP_JS
    # 2. Fallback на launch params в URL (/vk-app?vk_user_id=...&sign=...):
    assert "window.location.search" in APP_JS
    # 3. Объект/строка нормализуются в единый dict, затем — в initData:
    assert "normalizeVKLaunchParams" in APP_JS
    assert "Object.entries(lp)" in APP_JS
    # 4. initData кладётся в state (то, что уходит в X-VK-Init-Data):
    assert "state.initData = btoa(query)" in APP_JS


def test_appjs_buyer_ticket_qr_and_code():
    """Покупатель видит код для входа + может показать QR своего билета."""
    # Код для входа (validation_code) показывается в списке билетов
    assert "Код для входа" in APP_JS
    assert "showBuyerTicketQr" in APP_JS
    assert "downloadBuyerQr" in APP_JS
    # QR-эндпоинт покупателя (без pro)
    assert "/api/tickets/${ticketId}/qr" in APP_JS
    # VK-авторизация через authHeaders (X-VK-Init-Data / X-Init-Data)
    assert "authHeaders" in APP_JS
    assert "X-VK-Init-Data" in APP_JS


def test_appjs_vk_ticket_dm_flow():
    """VK: мягкий запрос → VKWebAppAllowMessagesFromGroup → POST send-vk."""
    assert "offerVkTicketDm" in APP_JS
    assert "VKWebAppAllowMessagesFromGroup" in APP_JS
    assert "vk_group_id" in APP_JS
    assert "/send-vk" in APP_JS
    assert "Билет отправлен в личные сообщения ВКонтакте" in APP_JS


def test_appjs_invite_links_flow():
    """Пригласительные как ссылки: выдача ссылки + активация гостем по ?invite=."""
    # Выдача: организатор получает ссылку на пригласительное
    assert "inviteLink" in APP_JS
    assert "?invite=" in APP_JS
    # Гость: deep-link ?invite=<код> → страница активации
    assert "showInvitePage" in APP_JS
    assert "params.get(\"invite\")" in APP_JS
    # Активация
    assert "claimInvite" in APP_JS
    assert "/api/invites/${encodeURIComponent(code)}/claim" in APP_JS
    assert "Активировать" in APP_JS


def test_appjs_ticket_presentation_free_vs_paid():
    """A: бесплатный билет → код, платный → QR (ветвление по is_free)."""
    assert "t.is_free" in APP_JS
    assert "const isFree = !!t.is_free" in APP_JS
    # free-ветка: код для входа
    assert "Код для входа" in APP_JS
    # paid-ветка: кнопка QR и подпись «платный билет»
    assert "Показать QR" in APP_JS
    assert "Платный билет" in APP_JS
    # ветвление: тернарник по isFree
    assert "isFree" in APP_JS


def test_appjs_event_premium():
    """C: per-event премиум — canPaid учитывает is_premium события."""
    assert "canPaid" in APP_JS
    assert "is_premium" in APP_JS
    assert "isPro() || !!(event && event.is_premium)" in APP_JS
    # эндпоинт покупки премиума
    assert "/premium" in APP_JS


# ─── QR-сканер для админа (#94, Feature Future #5) ────────────────────


def test_html_includes_jsqr():
    """jsQR подключён в оба entry (TG и VK) перед app.js."""
    assert "jsqr@1.4.0" in INDEX
    assert "jsqr@1.4.0" in VK_APP


def test_appjs_has_qr_scanner():
    """Сканер: живой поток камеры (getUserMedia + jsQR)."""
    assert "openQrScanner" in APP_JS
    assert "getUserMedia" in APP_JS
    assert "facingMode: \"environment\"" in APP_JS
    assert "jsQR(" in APP_JS
    assert "closeQrScanner" in APP_JS
    # stop потока при закрытии — освобождение камеры
    assert "getTracks().forEach(t => t.stop())" in APP_JS


def test_appjs_has_photo_fallback():
    """Фото-фоллбек: нативный capture (работает в Android WebView)."""
    assert "qrScanPhotoFallback" in APP_JS
    assert "scanFromPhoto" in APP_JS
    assert "accept=\"image/*\"" in APP_JS
    assert "capture=\"environment\"" in APP_JS


def test_appjs_checkin_has_scan_button():
    """На странице check-in есть кнопка «Сканировать QR»."""
    assert "Сканировать QR" in APP_JS


def test_appjs_scanner_format_gate():
    """Формат-гейт: авто-check-in только для кода билета XXXX-XXXX."""
    assert "QR_CODE_RE" in APP_JS
    assert "^[0-9A-F]{4}-[0-9A-F]{4}$" in APP_JS


# ─── Промокоды (скидки на билеты, pro) ──────────────────────────


def test_appjs_promo_buy_flow():
    """Поле «Промокод» на странице покупки и передача promo_code в body."""
    assert "Промокод" in APP_JS
    assert "promoInput_" in APP_JS
    assert "promo_code" in APP_JS
    assert "body: JSON.stringify(promo ? { promo_code: promo } : {})" in APP_JS


def test_appjs_admin_promo_section():
    """Секция «Промокоды» в админ-панели события."""
    assert "Промокоды" in APP_JS
    assert "/promo-codes" in APP_JS
    assert "adminCreatePromo" in APP_JS
    assert "adminTogglePromo" in APP_JS


# ─── Динамические цены по дате (early bird, pro) ────────────────


def test_appjs_dynamic_pricing():
    """Секция «Цены по дате» в форме/админке + CRUD-функции."""
    assert "Цены по дате" in APP_JS
    assert "/price-ranges" in APP_JS
    assert "addPriceRangeRow" in APP_JS
    assert "adminCreatePriceRange" in APP_JS
    assert "adminDeletePriceRange" in APP_JS
