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
