"""Configuración central de la aplicación.

Lee variables de entorno (archivo .env si existe) y expone un objeto
`settings` único para todo el proyecto.

Variables soportadas:
    APP_PASSWORD        contraseña de acceso (login simple)
    SECRET_KEY          clave para firmar la cookie de sesión (opcional)
    DB_MODE             "local" (sqlite) o "turso" (autodetecta si TURSO_URL existe)
    DB_PATH             ruta del archivo sqlite local
    TURSO_URL           URL libsql:// de la base de datos en Turso
    TURSO_AUTH_TOKEN    token de autenticación de Turso
    HORIZONTE_DIAS      días de planificación del motor (opcional, default 7)
"""

import os
import secrets
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv es opcional: sin él se usan variables del entorno
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def _leer_o_crear_secret_key() -> str:
    """Secret persistente en data/secret.key para que las sesiones
    sobrevivan a reinicios del servidor."""
    env_key = os.getenv("SECRET_KEY")
    if env_key:
        return env_key
    key_file = DATA_DIR / "secret.key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    return key


class Settings:
    def __init__(self) -> None:
        self.app_password: str = os.getenv("APP_PASSWORD", "cambiar-esta-contrasena")
        self.secret_key: str = _leer_o_crear_secret_key()
        self.db_path: str = os.getenv("DB_PATH", str(DATA_DIR / "app.db"))
        self.turso_url: str = os.getenv("TURSO_URL", "")
        self.turso_auth_token: str = os.getenv("TURSO_AUTH_TOKEN", "")
        self.horizonte_dias: int = int(os.getenv("HORIZONTE_DIAS", "7"))

        modo_env = os.getenv("DB_MODE", "").strip().lower()
        if modo_env in ("turso", "local"):
            self.db_mode: str = modo_env
        else:
            self.db_mode = "turso" if self.turso_url else "local"

    @property
    def usando_turso(self) -> bool:
        return self.db_mode == "turso"


settings = Settings()
