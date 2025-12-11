import base64
import json
import os
from functools import lru_cache
from typing import Any, Dict, Optional

import jwt
import requests
from fastapi import Header, HTTPException, status
from jwt import InvalidTokenError
from jwt.algorithms import ECAlgorithm, HMACAlgorithm, RSAAlgorithm
from pydantic import BaseModel


class AuthSettings(BaseModel):
    """OIDC/OAuth configuration loaded from environment variables."""

    issuer: Optional[str] = None
    audience: Optional[str] = None
    realm: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    token_url: Optional[str] = None
    well_known_url: Optional[str] = None
    jwks_json: Optional[str] = None
    jwks_url: Optional[str] = None
    redirect_uri: Optional[str] = None
    scope: str = "openid profile email"


class AuthenticatedUser(BaseModel):
    username: str
    token: str
    claims: Dict[str, Any]


def _load_jwks(settings: AuthSettings) -> Dict[str, Any]:
    """Load JWKS either from env, direct URL or via OIDC discovery."""
    if settings.jwks_json:
        return json.loads(settings.jwks_json)

    if settings.well_known_url:
        discovery = requests.get(settings.well_known_url, timeout=5)
        discovery.raise_for_status()
        metadata = discovery.json()
        settings.issuer = settings.issuer or metadata.get("issuer")
        settings.token_url = settings.token_url or metadata.get("token_endpoint")
        jwks_uri = metadata.get("jwks_uri")
        if not jwks_uri:
            raise RuntimeError("jwks_uri is missing in well-known configuration")
        jwks_response = requests.get(jwks_uri, timeout=5)
        jwks_response.raise_for_status()
        return jwks_response.json()

    if settings.jwks_url:
        jwks_response = requests.get(settings.jwks_url, timeout=5)
        jwks_response.raise_for_status()
        return jwks_response.json()

    raise RuntimeError("JWKS configuration is missing (OIDC_JWKS / OIDC_JWKS_URL / OIDC_WELL_KNOWN_URL)")


def _key_from_jwk(jwk_dict: Dict[str, Any]):
    """Convert a single JWK dict to a usable key for PyJWT."""
    kty = jwk_dict.get("kty", "").upper()
    if kty == "RSA":
        return RSAAlgorithm.from_jwk(json.dumps(jwk_dict))
    if kty == "EC":
        return ECAlgorithm.from_jwk(json.dumps(jwk_dict))
    # Treat everything else as HMAC (oct)
    return HMACAlgorithm.from_jwk(json.dumps(jwk_dict))


class JwtValidator:
    """Caches JWKS keys and validates JWT tokens."""

    def __init__(self, settings: AuthSettings):
        self.settings = settings
        self.jwks: Optional[Dict[str, Any]] = None
        self.key_cache: Dict[str, Any] = {}

    def _get_key(self, kid: Optional[str]):
        if not self.jwks:
            self.jwks = _load_jwks(self.settings)

        if not self.jwks or "keys" not in self.jwks:
            raise RuntimeError("JWKS does not contain 'keys'")

        if kid in self.key_cache:
            return self.key_cache[kid]

        candidate = None
        for jwk_item in self.jwks.get("keys", []):
            jwk_kid = jwk_item.get("kid")
            if kid is None or jwk_kid == kid:
                candidate = jwk_item
                break

        if not candidate:
            # If the key is not found, allow one refresh attempt when JWKS is provided via URL
            if self.settings.jwks_url or self.settings.well_known_url:
                self.jwks = _load_jwks(self.settings)
                for jwk_item in self.jwks.get("keys", []):
                    if jwk_item.get("kid") == kid:
                        candidate = jwk_item
                        break
            if not candidate:
                raise RuntimeError("Signing key not found for token")

        key = _key_from_jwk(candidate)
        if kid:
            self.key_cache[kid] = key
        return key

    def validate(self, token: str) -> AuthenticatedUser:
        try:
            unverified_header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid JWT header") from exc

        kid = unverified_header.get("kid")
        alg = unverified_header.get("alg", "RS256")

        try:
            key = self._get_key(kid)
            options = {"verify_aud": bool(self.settings.audience)}
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[alg],
                audience=self.settings.audience,
                issuer=self.settings.issuer,
                options=options,
            )
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT validation failed") from exc

        username = (
            claims.get("preferred_username")
            or claims.get("email")
            or claims.get("name")
            or claims.get("sub")
        )
        if not username:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Username claim is missing in token")

        return AuthenticatedUser(username=username, token=token, claims=claims)


@lru_cache()
def get_settings() -> AuthSettings:
    return AuthSettings(
        issuer=os.getenv("OIDC_ISSUER"),
        audience=os.getenv("OIDC_AUDIENCE"),
        realm=os.getenv("OIDC_REALM"),
        client_id=os.getenv("OIDC_CLIENT_ID"),
        client_secret=os.getenv("OIDC_CLIENT_SECRET"),
        token_url=os.getenv("OIDC_TOKEN_URL"),
        well_known_url=os.getenv("OIDC_WELL_KNOWN_URL"),
        jwks_json=os.getenv("OIDC_JWKS"),
        jwks_url=os.getenv("OIDC_JWKS_URL"),
        redirect_uri=os.getenv("OIDC_REDIRECT_URI"),
        scope=os.getenv("OIDC_SCOPE", "openid profile email"),
    )


@lru_cache()
def get_validator() -> JwtValidator:
    return JwtValidator(get_settings())


def get_current_user(authorization: str = Header(None)) -> AuthenticatedUser:
    """FastAPI dependency that validates JWT and returns an authenticated user."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header with Bearer token is required",
        )

    token = authorization.split(" ", 1)[1].strip()
    return get_validator().validate(token)


def auth_header_for(token: str) -> Dict[str, str]:
    """Build Authorization header for downstream requests."""
    return {"Authorization": f"Bearer {token}"}


def reset_auth_cache():
    """Clear cached auth settings/validator (useful in tests when env changes)."""
    get_validator.cache_clear()
    get_settings.cache_clear()

