import pytest

from app import crypto


def test_round_trip():
    blob, version = crypto.encrypt("s3cret-wazuh-password")
    assert crypto.decrypt(blob, version) == "s3cret-wazuh-password"


def test_ciphertext_is_not_the_plaintext():
    blob, _ = crypto.encrypt("s3cret-wazuh-password")
    assert b"s3cret" not in blob


def test_nonce_is_fresh_per_encryption():
    a, _ = crypto.encrypt("same")
    b, _ = crypto.encrypt("same")
    assert a != b


def test_tampering_is_detected():
    from cryptography.exceptions import InvalidTag

    blob, version = crypto.encrypt("password")
    tampered = bytearray(blob)
    tampered[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        crypto.decrypt(bytes(tampered), version)


def test_unknown_key_version_refuses_rather_than_guessing():
    blob, version = crypto.encrypt("password")
    with pytest.raises(crypto.EncryptionError):
        crypto.decrypt(blob, version + 1)


def test_generated_key_is_32_bytes():
    import base64

    assert len(base64.b64decode(crypto.generate_key())) == 32
