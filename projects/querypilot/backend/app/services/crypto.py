from cryptography.fernet import Fernet

from app.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        if not settings.secret_key:
            raise RuntimeError("SECRET_KEY is not set in backend/.env (see .env.example).")
        _fernet = Fernet(settings.secret_key.encode())
    return _fernet


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()
