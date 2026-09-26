"""Authenticated credential identity, corruption handling and key rotation."""

import json
import uuid

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from backend.core.config import settings
from backend.models.game_account import GameAccount
from backend.services.account_credentials import (
    AccountCredentialUnavailable,
    read_account_password,
    set_account_password,
)


@pytest.fixture
def cipher_account(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "ACCOUNT_CREDENTIAL_KEYS", SecretStr(key))
    account = GameAccount(org_id=uuid.uuid4(), game="audit", login="audit-cipher")
    set_account_password(account, "audit-unicode-密码-🔐")
    return account, key


@pytest.mark.parametrize("changed", ["id", "org_id"])
def test_ciphertext_cannot_be_transplanted_to_another_identity(cipher_account, changed):
    account, _ = cipher_account
    setattr(account, changed, uuid.uuid4())
    with pytest.raises(AccountCredentialUnavailable):
        read_account_password(account)


@pytest.mark.parametrize("broken", ["tamper", "wrong-key", "empty", "invalid-key", "non-ascii"])
def test_invalid_credentials_fail_closed_with_generic_error(cipher_account, monkeypatch, broken):
    account, key = cipher_account
    if broken == "tamper":
        account.password_ciphertext = account.password_ciphertext[:-4] + "AAAA"
    elif broken == "non-ascii":
        account.password_ciphertext = "audit-🔐"
    else:
        replacement = {"wrong-key": Fernet.generate_key().decode(), "empty": "", "invalid-key": "audit-bad"}[broken]
        monkeypatch.setattr(settings, "ACCOUNT_CREDENTIAL_KEYS", SecretStr(replacement))
    with pytest.raises(AccountCredentialUnavailable) as caught:
        read_account_password(account)
    assert caught.value.status_code == 503
    assert caught.value.detail == "Account credentials unavailable"
    assert key not in str(caught.value)


@pytest.mark.parametrize("payload", [{"version": 2}, {"version": True}, [], "text", {"password": 1}])
def test_unknown_or_malformed_authenticated_envelope_is_not_accepted(cipher_account, payload):
    account, key = cipher_account
    account.password_ciphertext = Fernet(key).encrypt(json.dumps(payload).encode()).decode()
    with pytest.raises(AccountCredentialUnavailable):
        read_account_password(account)


def test_rotation_reads_previous_key_and_writes_only_primary(cipher_account, monkeypatch):
    account, old_key = cipher_account
    new_key = Fernet.generate_key().decode()
    before = account.password_ciphertext
    monkeypatch.setattr(settings, "ACCOUNT_CREDENTIAL_KEYS", SecretStr(new_key + "," + old_key))
    password = read_account_password(account)
    set_account_password(account, password)
    assert account.password_ciphertext != before
    monkeypatch.setattr(settings, "ACCOUNT_CREDENTIAL_KEYS", SecretStr(new_key))
    assert read_account_password(account) == "audit-unicode-密码-🔐"
    assert account.password_encrypted == ""
    assert old_key not in repr(settings) and new_key not in repr(settings)


def test_missing_key_does_not_mutate_a_previous_credential(cipher_account, monkeypatch):
    account, _ = cipher_account
    before = account.password_ciphertext
    monkeypatch.setattr(settings, "ACCOUNT_CREDENTIAL_KEYS", SecretStr(""))
    with pytest.raises(AccountCredentialUnavailable):
        set_account_password(account, "audit-new-value")
    assert account.password_ciphertext == before
