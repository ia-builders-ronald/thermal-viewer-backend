"""
Cognito access-token authentication.

Accepts Cognito *access* tokens only (token_use == "access", client_id matching
the configured app client). Configuration is read from the environment and the
app fails closed when it is incomplete: there is no auth-off switch.
"""

import os
import json
import time
import logging
from dataclasses import dataclass
from functools import wraps
from typing import Optional

from flask import request, jsonify, g
import jwt
import requests

logger = logging.getLogger(__name__)

JWKS_CACHE_TTL = 3600  # 1 hour

_REQUIRED_ENV = ("COGNITO_USER_POOL_ID", "COGNITO_CLIENT_ID", "COGNITO_DOMAIN", "USERS_TABLE")


class TokenError(Exception):
    """Raised when a token fails validation."""


@dataclass(frozen=True)
class AuthConfig:
    region: str
    user_pool_id: str
    client_id: str
    domain: str  # bare hostname, no scheme
    users_table: str

    @classmethod
    def from_env(cls) -> "AuthConfig":
        missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
        if missing:
            raise RuntimeError(
                "Missing required auth configuration: " + ", ".join(missing)
            )
        return cls(
            region=os.environ.get("COGNITO_REGION") or "ap-southeast-1",
            user_pool_id=os.environ["COGNITO_USER_POOL_ID"],
            client_id=os.environ["COGNITO_CLIENT_ID"],
            domain=os.environ["COGNITO_DOMAIN"],
            users_table=os.environ["USERS_TABLE"],
        )

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/.well-known/jwks.json"

    @property
    def userinfo_url(self) -> str:
        return f"https://{self.domain}/oauth2/userInfo"


# Cache for JWKS (JSON Web Key Set), keyed by kid
_jwks_cache = {'keys': None, 'last_updated': 0}


def fetch_jwks(config: AuthConfig, force: bool = False):
    """Fetch JWKS from Cognito (kid -> JWK), cached for JWKS_CACHE_TTL."""
    now = time.time()
    if (
        not force
        and _jwks_cache['keys']
        and (now - _jwks_cache['last_updated']) < JWKS_CACHE_TTL
    ):
        return _jwks_cache['keys']

    try:
        logger.info(f"Fetching JWKS from {config.jwks_url}")
        response = requests.get(config.jwks_url, timeout=10)
        response.raise_for_status()
        keys = {key['kid']: key for key in response.json()['keys']}
        _jwks_cache['keys'] = keys
        _jwks_cache['last_updated'] = now
        return keys
    except Exception as e:
        logger.error(f"Error fetching JWKS: {e}")
        if _jwks_cache['keys']:
            logger.warning("Using expired JWKS cache")
            return _jwks_cache['keys']
        raise


def _get_public_key(token: str, config: AuthConfig):
    kid = jwt.get_unverified_header(token).get('kid')
    if not kid:
        raise TokenError("Token header missing 'kid'")

    jwks = fetch_jwks(config)
    if kid not in jwks:
        # Keys may have rotated: refetch once
        jwks = fetch_jwks(config, force=True)
        if kid not in jwks:
            raise TokenError("Unknown signing key")

    from jwt.algorithms import RSAAlgorithm
    return RSAAlgorithm.from_jwk(json.dumps(jwks[kid]))


def validate_access_token(token: str, config: AuthConfig) -> dict:
    """Validate a Cognito access token and return its claims, or raise TokenError."""
    try:
        public_key = _get_public_key(token, config)
        claims = jwt.decode(
            token,
            public_key,
            algorithms=['RS256'],
            issuer=config.issuer,
            options={'verify_exp': True, 'verify_iss': True, 'verify_aud': False},
        )
    except TokenError:
        raise
    except jwt.ExpiredSignatureError:
        raise TokenError("Token has expired")
    except jwt.InvalidIssuerError:
        raise TokenError("Invalid token issuer")
    except jwt.InvalidTokenError as e:
        raise TokenError(f"Invalid token: {e}")
    except Exception as e:
        logger.error(f"Error validating token: {e}")
        raise TokenError("Token validation failed")

    if claims.get('token_use') != 'access':
        raise TokenError("Invalid token_use: access token required")
    if claims.get('client_id') != config.client_id:
        raise TokenError("Token was not issued for this client")
    return claims


_config: Optional[AuthConfig] = None


def require_auth(f):
    """Require a valid Cognito access token in the Authorization header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # CORS preflight: Flask-CORS adds the headers
        if request.method == 'OPTIONS':
            return '', 200

        if _config is None:
            logger.error("require_auth used before init_auth")
            return jsonify({'error': 'Authentication unavailable'}), 500

        auth_header = request.headers.get('Authorization', '')
        if not auth_header:
            return jsonify({'error': 'Authorization header required'}), 401

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return jsonify({'error': 'Invalid Authorization header format. Use: Bearer <token>'}), 401

        try:
            claims = validate_access_token(parts[1], _config)
        except TokenError as e:
            logger.warning(f"Authentication failed: {e}")
            return jsonify({'error': str(e)}), 401

        g.user = {
            'sub': claims.get('sub'),
            'username': claims.get('username'),
            'token_use': claims.get('token_use'),
        }
        return f(*args, **kwargs)

    return decorated


def init_auth(app, config: Optional[AuthConfig] = None):
    """
    Initialise auth. Raises RuntimeError (app refuses to start) when required
    configuration is missing. JWKS prefetch is best-effort.
    """
    global _config
    prefetch = config is None
    _config = config or AuthConfig.from_env()
    logger.info(f"Cognito authentication enabled for pool: {_config.user_pool_id}")
    if prefetch:
        try:
            fetch_jwks(_config)
        except Exception as e:
            logger.error(f"JWKS prefetch failed (will retry on demand): {e}")
