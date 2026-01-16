"""
Cognito JWT Authentication Middleware

Validates JWT tokens from AWS Cognito User Pool.
"""

import os
import json
import time
import logging
from functools import wraps
from flask import request, jsonify, g
import jwt
import requests

logger = logging.getLogger(__name__)

# Configuration from environment variables
COGNITO_REGION = os.environ.get('COGNITO_REGION', 'ap-southeast-1')
COGNITO_USER_POOL_ID = os.environ.get('COGNITO_USER_POOL_ID', '')

# Cache for JWKS (JSON Web Key Set)
_jwks_cache = {
    'keys': None,
    'last_updated': 0
}
JWKS_CACHE_TTL = 3600  # 1 hour


def get_jwks_url():
    """Get the JWKS URL for the Cognito User Pool"""
    return f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}/.well-known/jwks.json"


def get_issuer():
    """Get the expected issuer for the Cognito User Pool"""
    return f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"


def fetch_jwks():
    """Fetch JWKS from Cognito, with caching"""
    global _jwks_cache

    current_time = time.time()

    # Return cached keys if still valid
    if _jwks_cache['keys'] and (current_time - _jwks_cache['last_updated']) < JWKS_CACHE_TTL:
        return _jwks_cache['keys']

    try:
        url = get_jwks_url()
        logger.info(f"Fetching JWKS from {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        jwks = response.json()

        # Cache the keys
        _jwks_cache['keys'] = {key['kid']: key for key in jwks['keys']}
        _jwks_cache['last_updated'] = current_time

        logger.info(f"JWKS cached with {len(_jwks_cache['keys'])} keys")
        return _jwks_cache['keys']

    except Exception as e:
        logger.error(f"Error fetching JWKS: {e}")
        # Return cached keys if available, even if expired
        if _jwks_cache['keys']:
            logger.warning("Using expired JWKS cache")
            return _jwks_cache['keys']
        raise


def get_public_key(token):
    """Get the public key for a token from JWKS"""
    try:
        # Decode header without verification to get kid
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get('kid')

        if not kid:
            raise ValueError("Token header missing 'kid'")

        jwks = fetch_jwks()

        if kid not in jwks:
            # Refresh cache and try again
            _jwks_cache['last_updated'] = 0
            jwks = fetch_jwks()

            if kid not in jwks:
                raise ValueError(f"Public key not found for kid: {kid}")

        key_data = jwks[kid]

        # Convert JWK to PEM format
        from jwt.algorithms import RSAAlgorithm
        public_key = RSAAlgorithm.from_jwk(json.dumps(key_data))

        return public_key

    except Exception as e:
        logger.error(f"Error getting public key: {e}")
        raise


def validate_token(token):
    """
    Validate a Cognito JWT token.

    Returns:
        dict: Decoded token claims if valid

    Raises:
        Exception: If token is invalid
    """
    if not COGNITO_USER_POOL_ID:
        raise ValueError("COGNITO_USER_POOL_ID not configured")

    try:
        public_key = get_public_key(token)

        # Decode and validate the token
        claims = jwt.decode(
            token,
            public_key,
            algorithms=['RS256'],
            issuer=get_issuer(),
            options={
                'verify_exp': True,
                'verify_iss': True,
                'verify_aud': False,  # Cognito access tokens don't have aud claim
            }
        )

        # Verify token_use claim (should be 'access' or 'id')
        token_use = claims.get('token_use')
        if token_use not in ['access', 'id']:
            raise ValueError(f"Invalid token_use: {token_use}")

        return claims

    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidIssuerError:
        raise ValueError("Invalid token issuer")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token: {e}")


def require_auth(f):
    """
    Decorator to require authentication for a route.

    Usage:
        @app.route('/api/protected')
        @require_auth
        def protected_route():
            user = g.user  # Access user info
            return jsonify({'message': 'Hello, authenticated user!'})
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Skip auth for OPTIONS preflight requests (CORS)
        if request.method == 'OPTIONS':
            return f(*args, **kwargs)

        # Skip auth if Cognito is not configured (development mode)
        if not COGNITO_USER_POOL_ID:
            logger.warning("COGNITO_USER_POOL_ID not set - authentication disabled")
            g.user = None
            return f(*args, **kwargs)

        # Get token from Authorization header
        auth_header = request.headers.get('Authorization', '')

        if not auth_header:
            return jsonify({'error': 'Authorization header required'}), 401

        # Parse Bearer token
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return jsonify({'error': 'Invalid Authorization header format. Use: Bearer <token>'}), 401

        token = parts[1]

        try:
            # Validate token and get claims
            claims = validate_token(token)

            # Store user info in Flask's g object for access in route
            g.user = {
                'sub': claims.get('sub'),  # User ID
                'email': claims.get('email'),
                'username': claims.get('username') or claims.get('cognito:username'),
                'token_use': claims.get('token_use'),
            }

            return f(*args, **kwargs)

        except ValueError as e:
            logger.warning(f"Authentication failed: {e}")
            return jsonify({'error': str(e)}), 401
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return jsonify({'error': 'Authentication failed'}), 401

    return decorated


def init_auth(app):
    """
    Initialize authentication middleware.

    Call this during app startup to validate configuration.
    """
    if COGNITO_USER_POOL_ID:
        logger.info(f"Cognito authentication enabled for pool: {COGNITO_USER_POOL_ID}")
        try:
            # Pre-fetch JWKS to validate configuration
            fetch_jwks()
            logger.info("JWKS pre-fetched successfully")
        except Exception as e:
            logger.error(f"Failed to fetch JWKS during init: {e}")
    else:
        logger.warning("COGNITO_USER_POOL_ID not set - authentication disabled")
