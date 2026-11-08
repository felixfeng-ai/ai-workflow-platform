from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings


class SecretDecryptionError(ValueError):
    pass


def _fernet() -> Fernet:
    """从任意长度的应用密钥派生固定长度 Fernet 密钥。

    数据库只保存密文；密钥轮换属于后续运维能力，不在 V1 范围内。
    """
    digest = hashlib.sha256(settings.app_encryption_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SecretDecryptionError("凭据无法解密，请重新配置") from exc
