"""Хеширование паролей и кодовых слов на scrypt из стандартной библиотеки."""

import hashlib
import hmac
import secrets

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32


def hash_secret(value: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(value.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_secret(value: str, stored: str | None) -> bool:
    if not stored:
        # Считаем хеш и для несуществующего пользователя, чтобы время ответа не выдавало логины.
        hash_secret(value)
        return False
    try:
        _, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.scrypt(value.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=_N, r=_R, p=_P, dklen=_DKLEN)
    return hmac.compare_digest(digest.hex(), digest_hex)


def normalize_codeword(value: str) -> str:
    """Кодовое слово сверяем без учёта регистра и лишних пробелов."""
    return " ".join(value.split()).casefold()
