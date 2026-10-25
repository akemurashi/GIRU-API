"""Punto de entrada principal y configuración de la aplicación FastAPI para GIRU Backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.api import auth, documents, external_ai, relaciones, search
from app.core.config import settings
from app.core.database import check_db_connection, ensure_schema_compatibility
from app.core.exceptions import BaseAppException
from app.core.middleware import (
    exception_handler,
    general_exception_handler,
    request_id_middleware,
    sqlalchemy_exception_handler,
    validation_exception_handler,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Ciclo de vida de la aplicación FastAPI para inicializar recursos."""
    # Asegura existencia de columnas requeridas como 'ultima_modificacion'
    await ensure_schema_compatibility()
    yield


app = FastAPI(
    title="Sistema de Búsqueda de Documentos",
    version="0.1.0",
    description="Búsqueda semántica y chatbot RAG sobre documentos institucionales",
    lifespan=lifespan,
    swagger_ui_init_oauth={
        "clientId": settings.COGNITO_CLIENT_ID,
        "appName": "Sistema de Búsqueda Swagger",
    },
)

# Store app state for middleware
app.state.APP_ENV = settings.APP_ENV

# Add request ID middleware
app.middleware("http")(request_id_middleware)

# Add exception handlers
app.add_exception_handler(BaseAppException, exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(search.router, prefix="/api/v1/search", tags=["search"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])
app.include_router(external_ai.router, prefix="/api/v1/ai", tags=["external-ai"])
app.include_router(relaciones.router, prefix="/api/v1/relaciones", tags=["relaciones"])


@app.get("/health")
def health_check() -> dict[str, str]:
    """Verifica el estado del servicio FastAPI."""
    return {"status": "ok"}


@app.get("/health/db")
async def database_health() -> dict[str, Any]:
    """Verifica el estado de conexión con la base de datos PostgreSQL."""
    conn_info = await check_db_connection()
    if conn_info.get("connected"):
        return conn_info

    return {"database": "disconnected", "error": conn_info.get("error")}
