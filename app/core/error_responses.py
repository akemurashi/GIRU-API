"""Modelos de respuesta de error estándar para la API de GIRU."""

from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Formato estándar de respuesta de error."""
    error: str
    message: str
    details: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: str | None = None


class ValidationErrorResponse(ErrorResponse):
    """Respuesta de error de validación."""
    error: str = "validation_error"
    field: str | None = None


class DatabaseErrorResponse(ErrorResponse):
    """Respuesta de error de base de datos."""
    error: str = "database_error"


class NotFoundResponse(ErrorResponse):
    """Respuesta de recurso no encontrado."""
    error: str = "not_found"


class AuthenticationErrorResponse(ErrorResponse):
    """Respuesta de error de autenticación."""
    error: str = "authentication_error"


class AuthorizationErrorResponse(ErrorResponse):
    """Respuesta de error de autorización."""
    error: str = "authorization_error"


class SearchErrorResponse(ErrorResponse):
    """Respuesta de error de búsqueda."""
    error: str = "search_error"


class IngestErrorResponse(ErrorResponse):
    """Respuesta de error de ingestión."""
    error: str = "ingest_error"


class UniqueConstraintResponse(ErrorResponse):
    """Respuesta de conflicto por unicidad."""
    error: str = "unique_constraint_error"


class DAGCycleResponse(ErrorResponse):
    """Respuesta de violación de grafo acíclico."""
    error: str = "dag_cycle_error"


class CatalogNotFoundResponse(ErrorResponse):
    """Respuesta de catálogo no encontrado."""
    error: str = "catalog_not_found"

