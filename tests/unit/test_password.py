import pytest

from yaml_api_generator.server.common.auth.password import hash_password, verify_password


class TestHashPassword:
    def test_176_hash_verifiable_with_verify_password(self):
        # If hash_password produces output that verify_password can't verify, it's broken
        h = hash_password("secret123")
        assert verify_password("secret123", h) is True
        assert verify_password("wrong", h) is False

    def test_177_different_hashes_for_same_password(self):
        h1 = hash_password("secret123")
        h2 = hash_password("secret123")
        assert h1 != h2

    def test_178_verify_correct_password(self):
        h = hash_password("correcthorse")
        assert verify_password("correcthorse", h) is True

    def test_179_verify_wrong_password(self):
        h = hash_password("correcthorse")
        assert verify_password("wronghorse", h) is False

    def test_180_empty_password(self):
        h = hash_password("")
        assert verify_password("", h) is True
        assert verify_password("notempty", h) is False

    def test_181_unicode_password(self):
        pw = "pässwörd日本語🔐"
        h = hash_password(pw)
        assert verify_password(pw, h) is True
        assert verify_password("password", h) is False

    def test_182_malformed_hash_wrong_segment_count(self):
        assert verify_password("x", "pbkdf2$sha256$390000$salt") is False

    def test_183_wrong_algorithm_prefix(self):
        assert verify_password("x", "bcrypt$sha256$390000$c2FsdA==$aGFzaA==") is False

    def test_184_wrong_digest_name(self):
        assert verify_password("x", "pbkdf2$sha512$390000$c2FsdA==$aGFzaA==") is False

    def test_185_non_numeric_rounds(self):
        assert verify_password("x", "pbkdf2$sha256$abc$c2FsdA==$aGFzaA==") is False

    def test_186_invalid_base64_in_salt(self):
        assert (
            verify_password("x", "pbkdf2$sha256$390000$!!!invalid!!!$aGFzaA==") is False
        )

    def test_187_empty_hash_string(self):
        assert verify_password("x", "") is False

    def test_188_verify_password_works_as_expected(self):
        h = hash_password("test_password")
        assert verify_password("test_password", h) is True
        assert verify_password("other", h) is False
