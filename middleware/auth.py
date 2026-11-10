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

from flask import request, jsonify, g, current_app
import jwt
import requests

from middleware.userinfo import fetch_userinfo
from middleware.users import DEFAULT_ROLE, UserStore, permissions_for

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


def _unauthenticated(message: str):
    return jsonify({'error': message, 'code': 'unauthenticated'}), 401


def require_auth(f):
    """Require a valid Cognito access token; load the user row and block check."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # CORS preflight: Flask-CORS adds the headers
        if request.method == 'OPTIONS':
            return '', 200

        ext = current_app.extensions.get('auth')
        if ext is None:
            logger.error("require_auth used before init_auth")
            return jsonify({'error': 'Authentication unavailable'}), 500
        config, store = ext['config'], ext['store']

        auth_header = request.headers.get('Authorization', '')
        if not auth_header:
            return _unauthenticated('Authorization header required')

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return _unauthenticated('Invalid Authorization header format. Use: Bearer <token>')

        try:
            claims = validate_access_token(parts[1], config)
        except TokenError as e:
            logger.warning(f"Authentication failed: {e}")
            return _unauthenticated(str(e))

        sub = claims.get('sub')
        username = claims.get('username')
        user = store.get(sub)
        if user is None:
            info = ext['userinfo_fetcher'](config, parts[1])
            user = store.get_or_create(
                sub, username, email=info.get('email'), name=info.get('name')
            )
        if user.get('blocked'):
            return jsonify({
                'error': 'Your access has been blocked. Contact your administrator.',
                'code': 'blocked',
            }), 403

        role = user.get('role') or DEFAULT_ROLE
        g.user = {
            'sub': sub,
            'username': username,
            'email': user.get('email'),
            'name': user.get('name'),
            'role': role,
            'permissions': permissions_for(role),
            'access_token': parts[1],
        }
        return f(*args, **kwargs)

    return decorated


def require_permission(name: str):
    """Require a permission on g.user. Use after @require_auth."""
    def wrap(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if request.method == 'OPTIONS':
                return '', 200
            if name not in g.user.get('permissions', []):
                return jsonify({
                    'error': 'You do not have permission to do this.',
                    'code': 'forbidden',
                }), 403
            return f(*args, **kwargs)
        return decorated
    return wrap


def init_auth(app, config: Optional[AuthConfig] = None, store: Optional[UserStore] = None,
              userinfo_fetcher=None):
    """
    Initialise auth and store it on app.extensions["auth"]. Raises RuntimeError
    (app refuses to start) when required configuration is missing. No network
    calls when a config is injected; the production JWKS prefetch is best-effort.
    """
    prefetch = config is None
    config = config or AuthConfig.from_env()
    if store is None:
        import boto3
        store = UserStore(boto3.resource('dynamodb', region_name=config.region).Table(config.users_table))
    app.extensions['auth'] = {
        'config': config,
        'store': store,
        'userinfo_fetcher': userinfo_fetcher or fetch_userinfo,
    }
    logger.info(f"Cognito authentication enabled for pool: {config.user_pool_id}")
    if prefetch:
        try:
            fetch_jwks(config)
        except Exception as e:
            logger.error(f"JWKS prefetch failed (will retry on demand): {e}")
