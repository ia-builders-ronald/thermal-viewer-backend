import time

import pytest

from middleware.auth import AuthConfig, TokenError, validate_access_token
from tests.conftest import _gen_key


def test_valid_access_token_returns_claims(make_token, auth_config):
    token = make_token(sub="abc-123")
    claims = validate_access_token(token, auth_config)
    assert claims["sub"] == "abc-123"


def test_rejects_id_token(make_token, auth_config):
    with pytest.raises(TokenError):
        validate_access_token(make_token(token_use="id"), auth_config)


def test_rejects_wrong_client_id(make_token, auth_config):
    with pytest.raises(TokenError):
        validate_access_token(make_token(client_id="other"), auth_config)


def test_rejects_wrong_issuer(make_token, auth_config):
    with pytest.raises(TokenError):
        validate_access_token(make_token(iss="https://evil.example.com/pool"), auth_config)


def test_rejects_expired(make_token, auth_config):
    with pytest.raises(TokenError):
        validate_access_token(make_token(exp=int(time.time()) - 10), auth_config)


def test_rejects_bad_signature(make_token, auth_config):
    with pytest.raises(TokenError):
        validate_access_token(make_token(signing_key=_gen_key()), auth_config)


def test_rejects_unknown_kid(make_token, auth_config):
    with pytest.raises(TokenError):
        validate_access_token(make_token(kid="nope"), auth_config)


def test_rejects_garbage(auth_config):
    with pytest.raises(TokenError):
        validate_access_token("not-a-jwt", auth_config)


def test_config_missing_vars_raises(monkeypatch):
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "pool")
    monkeypatch.setenv("COGNITO_DOMAIN", "d.example.com")
    monkeypatch.delenv("COGNITO_CLIENT_ID", raising=False)
    monkeypatch.delenv("USERS_TABLE", raising=False)
    with pytest.raises(RuntimeError) as exc:
        AuthConfig.from_env()
    assert "COGNITO_CLIENT_ID" in str(exc.value)
    assert "USERS_TABLE" in str(exc.value)


def test_config_derived_urls(auth_config):
    assert auth_config.issuer == "https://cognito-idp.ap-southeast-1.amazonaws.com/ap-southeast-1_TESTPOOL"
    assert auth_config.jwks_url == auth_config.issuer + "/.well-known/jwks.json"
    assert auth_config.userinfo_url == "https://test.auth.ap-southeast-1.amazoncognito.com/oauth2/userInfo"
