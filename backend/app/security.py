import base64
import hashlib
import hmac
import re
import secrets

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_MAXMEM = 64 * 1024 * 1024  # N=2**15, r=8 требует 32 МиБ плюс накладные расходы; лимит по умолчанию — ровно 32 МиБ

USERNAME_PATTERN = re.compile(r"[A-Za-z0-9._@-]{3,64}")
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128
CODEWORD_MIN_LENGTH = 6
CODEWORD_MAX_LENGTH = 64
WEAK_CODEWORDS = {"password", "qwerty", "codeword", "letmein", "aeza"}
RESET_TOKEN_MINUTES = 10


def normalize_username(value: str) -> str:
    return value.strip().lower()


def normalize_codeword(value: str) -> str:
    return " ".join(value.split()).casefold()


def username_error(username: str) -> str | None:
    if not USERNAME_PATTERN.fullmatch(username):
        return "Логин должен быть от 3 до 64 символов: латинские буквы, цифры, точка, дефис, подчёркивание или @."
    return None


def password_error(password: str, username: str | None = None) -> str | None:
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        return "Пароль должен быть от 10 до 128 символов."
    if not (re.search(r"[^\W\d_]", password) and re.search(r"\d", password)):
        return "Пароль должен содержать буквы и цифры."
    if username and password.casefold() == username.casefold():
        return "Пароль не должен совпадать с логином."
    return None


def codeword_error(codeword: str, password: str | None = None) -> str | None:
    normalized = normalize_codeword(codeword)
    if not CODEWORD_MIN_LENGTH <= len(normalized) <= CODEWORD_MAX_LENGTH:
        return "Кодовое слово должно быть от 6 до 64 символов."
    if normalized.isdigit() or normalized in WEAK_CODEWORDS:
        return "Кодовое слово слишком простое: не только цифры и не типовое слово."
    if password is not None and normalized == normalize_codeword(password):
        return "Кодовое слово не должно совпадать с паролем."
    return None


def hash_secret(secret: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        secret.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM,
    )
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N,
        SCRYPT_R,
        SCRYPT_P,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_secret(secret: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_b64, digest_b64 = stored.split("$")
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.scrypt(
            secret.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


DUMMY_HASH = hash_secret("unused-dummy-secret")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
