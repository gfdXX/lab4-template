import base64
import json
import os
from typing import Dict, Optional
import time

import jwt
from services.auth import reset_auth_cache

TEST_SECRET = "test-secret-key"
TEST_KID = "test-key"
TEST_ISSUER = "http://test-issuer"
TEST_AUDIENCE = "test-client"


def ensure_test_jwks() -> None:
    """Populate environment variables with a static JWKS for unit tests."""
    jwk = {
        "kty": "oct",
        "kid": TEST_KID,
        "k": base64.urlsafe_b64encode(TEST_SECRET.encode()).decode().rstrip("="),
    }
    os.environ.setdefault("OIDC_JWKS", json.dumps({"keys": [jwk]}))
    os.environ.setdefault("OIDC_ISSUER", TEST_ISSUER)
    os.environ.setdefault("OIDC_AUDIENCE", TEST_AUDIENCE)
    os.environ.setdefault("OIDC_SCOPE", "openid profile email")
    reset_auth_cache()


def generate_token(extra_claims: Optional[Dict] = None) -> str:
    """Generate a short-lived JWT signed with the static test key."""
    ensure_test_jwks()
    now = int(time.time())
    payload = {
        "sub": "test-user",
        "preferred_username": "test-user",
        "aud": TEST_AUDIENCE,
        "iss": TEST_ISSUER,
        "iat": now,
        "exp": now + 3600,
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(
        payload,
        TEST_SECRET,
        algorithm="HS256",
        headers={"kid": TEST_KID},
    )


def auth_headers(token: Optional[str] = None) -> Dict[str, str]:
    """Return Authorization header with a valid bearer token."""
    return {"Authorization": f"Bearer {token or generate_token()}"}

