"""Autenticación simple por contraseña con cookie de sesión firmada.

Un solo usuario (el dueño): la contraseña vive en .env (APP_PASSWORD).
Al iniciar sesión se emite una cookie firmada con itsdangerous que expira
a los 30 días y se renueva en cada uso.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

COOKIE_NAME = "gestor_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 días

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="gestor-session")


def verificar_password(ingresada: str) -> bool:
    """Comparación en tiempo constante para evitar timing attacks."""
    return hmac.compare_digest(ingresada, settings.app_password)


def crear_token_sesion() -> str:
    expira = datetime.now(timezone.utc) + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
    return _serializer.dumps({"exp": expira.isoformat()})


def validar_token(token: str) -> bool:
    """True si el token es válido y no ha expirado."""
    try:
        payload = _serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
        return isinstance(payload, dict) and "exp" in payload
    except (BadSignature, SignatureExpired):
        return False


def token_requiere_renovacion(token: str) -> bool:
    """True si quedan menos de 3 días de vida (para renovar en cada petición)."""
    try:
        payload = _serializer.loads(token, max_age=None)
        exp = datetime.fromisoformat(payload["exp"])
        queda = exp - datetime.now(timezone.utc)
        return queda < timedelta(days=3)
    except (BadSignature, SignatureExpired, KeyError, ValueError):
        return False
