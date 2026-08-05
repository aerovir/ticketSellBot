"""Генерация QR-кодов для билетов и пригласительных.

Используется фича pro-подписки `qr_codes`. QR содержит короткий код
билета (XXXX-XXXX) — проверяющий сканирует/вводит его на входе.
"""
import io

import qrcode


def generate_qr_png(code: str) -> bytes:
    """Сгенерировать PNG-изображение QR-кода с кодом билета.

    Args:
        code: Короткий код (XXXX-XXXX).

    Returns:
        bytes: PNG-картинка.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(code)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()
