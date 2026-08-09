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
