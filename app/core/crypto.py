"""Шифрование секретов (community token VK-групп) через Fernet.

Ключ — в settings.vk_token_encryption_key (base64url, 32 байта).
Генерация ключа:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger("ticketbot.crypto")


def _fernet() -> Fernet:
    key = settings.vk_token_encryption_key
    if not key:
        raise ValueError("VK_TOKEN_ENCRYPTION_KEY не настроен — невозможно зашифровать секрет")
    return Fernet(key.encode())


def encrypt_token(plain: str) -> str:
    """Зашифровать секрет. Возвращает str (token)."""
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_token(encrypted: str) -> str | None:
    """Расшифровать секрет. None при отсутствии или ошибке."""
    if not encrypted:
        return None
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except (InvalidToken, ValueError) as e:
        logger.warning("Не удалось расшифровать секрет: %s", e)
        return None
