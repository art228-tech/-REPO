"""Шифрование session string.

Session string даёт полный доступ к аккаунту и не спрашивает 2FA, поэтому в БД
он лежит только в зашифрованном виде. Ключ хранится в окружении, не в базе.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SessionCipherError(RuntimeError):
    pass


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")


class SessionCipher:
    def __init__(self, key: str) -> None:
        if not key:
            raise SessionCipherError(
                "SESSION_ENCRYPTION_KEY не задан. Сгенерируйте ключ: "
                "python -m tgparser genkey"
            )
        try:
            self._fernet = Fernet(key.encode("ascii") if isinstance(key, str) else key)
        except (ValueError, TypeError) as exc:
            raise SessionCipherError(f"Некорректный SESSION_ENCRYPTION_KEY: {exc}") from exc

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as exc:
            raise SessionCipherError(
                "Не удалось расшифровать сессию: ключ не совпадает с тем, "
                "которым она была зашифрована."
            ) from exc
