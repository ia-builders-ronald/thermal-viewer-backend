import time
import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from middleware import auth
from middleware.auth import AuthConfig

TEST_KID = "test-kid-1"


def _gen_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk_for(private_key, kid):
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return jwk


@pytest.fixture(scope="session")
def rsa_keys():
    key = _gen_key()
    return {"private_key": key, "kid": TEST_KID, "jwk": _jwk_for(key, TEST_KID)}


@pytest.fixture
def auth_config():
    return AuthConfig(
        region="ap-southeast-1",
        user_pool_id="ap-southeast-1_TESTPOOL",
        client_id="test-client-id",
        domain="test.auth.ap-southeast-1.amazoncognito.com",
        users_table="test-users",
    )


@pytest.fixture(autouse=True)
def patch_jwks(monkeypatch, rsa_keys):
    """No network: JWKS fetching returns the test JWK."""
    monkeypatch.setattr(
        auth, "fetch_jwks", lambda config, force=False: {rsa_keys["kid"]: rsa_keys["jwk"]}
    )


@pytest.fixture
def make_token(rsa_keys, auth_config):
    def _make(signing_key=None, kid=None, **overrides):
        claims = {
            "token_use": "access",
            "client_id": auth_config.client_id,
            "iss": auth_config.issuer,
            "sub": "user-sub-123",
            "username": "testuser",
            "exp": int(time.time()) + 3600,
        }
        claims.update(overrides)
        return jwt.encode(
            claims,
            signing_key or rsa_keys["private_key"],
            algorithm="RS256",
            headers={"kid": kid or rsa_keys["kid"]},
        )

    return _make
