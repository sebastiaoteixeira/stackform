import base64
import hashlib
import hmac
import os
import secrets


DEFAULT_PASSWORD_HASH_ROUNDS = int(os.environ.get("PASSWORD_HASH_ROUNDS", "390000"))


def hash_password(password: str, rounds: int = DEFAULT_PASSWORD_HASH_ROUNDS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        rounds,
    )
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    hash_b64 = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"pbkdf2$sha256${rounds}${salt_b64}${hash_b64}"


def verify_password(password: str, encoded_hash: str) -> bool:
    parts = encoded_hash.split("$")
    if len(parts) != 5:
        return False

    algorithm, digest_name, rounds_text, salt_b64, hash_b64 = parts
    if algorithm != "pbkdf2" or digest_name != "sha256":
        return False

    try:
        rounds = int(rounds_text)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(hash_b64.encode("ascii"))
    except (ValueError, base64.binascii.Error):
        return False

    computed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        rounds,
    )
    return hmac.compare_digest(computed, expected)
