"""Punto de entrada de la aplicación FastAPI.

Monta los routers de la API, sirve el frontend estático y gestiona:
- creación del esquema al arrancar (lifespan);
- renovación automática de la cookie de sesión (middleware);
- cierre de la conexión a la base por hilo tras cada petición.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import db
from .routers import auth, horario, tareas
from .security import COOKIE_NAME, SESSION_MAX_AGE_SECONDS, token_requiere_renovacion, validar_token

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_schema()
    yield
    db.close()


app = FastAPI(
    title="Gestor de Tareas",
    description="Planificador de tareas con horario inteligente (estilo Google Calendar).",
    version="2.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def sesion_middleware(request: Request, call_next):
    """Renueva la cookie si le quedan pocos días y cierra la conexión al salir."""
    try:
        response = await call_next(request)
        token = request.cookies.get(COOKIE_NAME)
        if token and validar_token(token) and token_requiere_renovacion(token):
            from .security import crear_token_sesion

            response.set_cookie(
                COOKIE_NAME,
                crear_token_sesion(),
                httponly=True,
                samesite="lax",
                max_age=SESSION_MAX_AGE_SECONDS,
            )
        return response
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
app.include_router(auth.router)
app.include_router(tareas.router)
app.include_router(horario.router)

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def pagina_login() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/app", include_in_schema=False)
def pagina_app() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {"ok": True, "modo": settings.db_mode}
