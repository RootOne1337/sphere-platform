"""Keep the application's fixed-key JWT boundary across dependency upgrades."""

import time
from unittest.mock import patch

import jwt
import pytest

from backend.core.config import settings
from backend.core.security import decode_access_token, decode_expired_access_token


@pytest.fixture
def claims(monkeypatch):
    monkeypatch.setattr(settings, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "audit-only-jwt-contract-" + "a" * 64)
    return {"sub": "audit-user", "jti": "audit-token", "type": "access", "exp": int(time.time()) + 60}


@pytest.mark.parametrize("decoder", [decode_access_token, decode_expired_access_token])
@pytest.mark.parametrize("forgery", ["unsigned", "disallowed_algorithm", "wrong_key"])
def test_verifier_rejects_forgery_including_the_logout_path(claims, decoder, forgery):
    if forgery == "unsigned":
        token = jwt.encode(claims, "", algorithm="none")
    elif forgery == "disallowed_algorithm":
        token = jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm="HS512")
    else:
        token = jwt.encode(claims, "not-the-audit-key-" + "b" * 64, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decoder(token)


@pytest.mark.parametrize("decoder", [decode_access_token, decode_expired_access_token])
def test_token_header_cannot_select_an_external_signing_key(claims, decoder):
    token = jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm="HS256",
                       headers={"jku": "http://127.0.0.1:9/audit-jwks", "kid": "untrusted-header"})
    with patch("urllib.request.urlopen", side_effect=AssertionError("JWT must not fetch header URLs")) as fetch:
        assert decoder(token)["sub"] == "audit-user"
    fetch.assert_not_called()


@pytest.mark.parametrize("required", ["sub", "jti", "type", "exp"])
def test_access_verifier_preserves_required_claims(claims, required):
    del claims[required]
    token = jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm="HS256")
    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_access_token(token)
