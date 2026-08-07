#!/usr/bin/env bash
# smoke-user-flow.sh — быстрая проверка реального пути пользователя на dev-копии.
#
# Проверяет: создание открыто, покупка подписки активирует pro-функции.
# Запускать на VDS, где поднята dev-копия (web на :8081).
#
# Использование:
#   bash scripts/smoke-user-flow.sh            # против http://localhost:8081
#   B=http://my-host:8081 bash scripts/smoke-user-flow.sh

set -euo pipefail

B="${B:-http://localhost:8081}"
H="X-Skip-Auth: 1"
CJSON="Content-Type: application/json"

echo "=== 1. GET /api/me → role ==="
ME=$(curl -sS -m 10 -H "$H" "$B/api/me")
echo "$ME" | python3 -c "import json,sys; print('  role:', json.load(sys.stdin)['role'])"

echo "=== 2. Создать бесплатное (должно быть 201) ==="
UID_ID=$(echo "$ME" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
RESP=$(curl -sS -m 10 -H "$H" -H "$CJSON" -X POST "$B/api/admin/events" \
  -d "{\"title\":\"Smoke Free\",\"date\":\"2026-12-01T19:00:00Z\",\"price\":0,\"total_tickets\":10,\"channel_id\":null,\"owner_user_id\":\"$UID_ID\"}")
echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'id' in d, 'создание бесплатного не удалось: '+str(d); print('  ✅ id:', d['id'])"

echo "=== 3. Платное без pro (должно быть 409) ==="
CODE=$(curl -sS -m 10 -o /dev/null -w "%{http_code}" -H "$H" -H "$CJSON" -X POST "$B/api/admin/events" \
  -d "{\"title\":\"Smoke Paid\",\"date\":\"2026-12-01T19:00:00Z\",\"price\":500,\"total_tickets\":10,\"channel_id\":null,\"owner_user_id\":\"$UID_ID\"}")
echo "  HTTP $CODE (ожидаем 409)"; [ "$CODE" = "409" ] || { echo "  ❌ платное без pro вернуло $CODE"; exit 1; }

echo "=== 4. Купить подписку pro (должно быть 200) ==="
RESP=$(curl -sS -m 10 -H "$H" -H "$CJSON" -X POST "$B/api/me/subscription" -d '{"tier":"pro"}')
echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('subscription_tier')=='pro', 'покупка не удалась: '+str(d); print('  ✅ tier:', d['subscription_tier'])"

echo "=== 5. GET /api/me → role ==="
ME2=$(curl -sS -m 10 -H "$H" "$B/api/me")
echo "$ME2" | python3 -c "import json,sys; r=json.load(sys.stdin)['role']; assert r=='organizer', 'role='+r; print('  ✅ role:', r)"

echo "=== 6. Платное после pro (должно быть 201) ==="
CODE=$(curl -sS -m 10 -o /dev/null -w "%{http_code}" -H "$H" -H "$CJSON" -X POST "$B/api/admin/events" \
  -d "{\"title\":\"Smoke Paid Pro\",\"date\":\"2026-12-01T19:00:00Z\",\"price\":500,\"total_tickets\":10,\"channel_id\":null,\"owner_user_id\":\"$UID_ID\"}")
echo "  HTTP $CODE (ожидаем 201)"; [ "$CODE" = "201" ] || { echo "  ❌ платное после pro вернуло $CODE"; exit 1; }

echo ""
echo "✅ Smoke-тест реального пути пользователя ПРОЙДЕН"
