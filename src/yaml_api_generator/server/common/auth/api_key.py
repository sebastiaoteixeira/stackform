import hashlib


def hash_api_key(api_key: str) -> str:
    """API keys are high-entropy, so an unsalted digest keeps them both secret and indexable."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()
