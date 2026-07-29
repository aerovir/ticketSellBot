#!/usr/bin/env bash
# init-ssl.sh — получение SSL-сертификата Let's Encrypt для pochtibot.online
#
# Запускается один раз при первом деплое.
# Последующие разы certbot сам обновляет сертификаты (раз в 90 дней).
#
# Использование:
#   bash deploy/scripts/init-ssl.sh
#   (запускается внутри GitHub Actions или вручную на сервере)

set -euo pipefail

DOMAIN="pochtibot.online"
EMAIL="admin@${DOMAIN}"

echo "🔐 Получение SSL-сертификата для ${DOMAIN}..."

# Проверяем, нет ли уже сертификата
if [ -d "/etc/letsencrypt/live/${DOMAIN}" ]; then
    echo "✅ Сертификат уже существует: /etc/letsencrypt/live/${DOMAIN}"
    certbot renew --dry-run 2>/dev/null && echo "✅ Автообновление настроено" || echo "⚠️  Проверь автообновление"
    exit 0
fi

# Получаем сертификат через certbot в Docker
docker run --rm \
    -v /etc/letsencrypt:/etc/letsencrypt \
    -v /var/www/certbot:/var/www/certbot \
    -p 80:80 \
    certbot/certbot:latest \
    certonly --standalone \
    -d "${DOMAIN}" \
    --non-interactive \
    --agree-tos \
    -m "${EMAIL}" \
    --preferred-challenges http \
    --http-01-port 80

echo "✅ SSL-сертификат получен для ${DOMAIN}"
echo "📁 /etc/letsencrypt/live/${DOMAIN}/"
echo "   ├── fullchain.pem"
echo "   └── privkey.pem"
