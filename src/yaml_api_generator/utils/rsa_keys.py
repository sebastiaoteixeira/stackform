"""RSA key material for RS256-signed session tokens."""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_SIZE = 2048


def generate_private_key_pem() -> str:
    """A fresh unencrypted PKCS#8 PEM-encoded RSA private key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def public_key_pem(private_pem: str) -> str:
    """The SubjectPublicKeyInfo PEM of the public half of a private key."""
    private_key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
