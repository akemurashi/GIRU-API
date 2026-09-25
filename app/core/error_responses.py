from pydantic import BaseModel
from typing import Optional, Any, Dict
from datetime import datetime


class ErrorResponse(BaseModel):
    """Formato estándar de respuesta de error."""
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = datetime.utcnow()
    request_id: Optional[str] = None


class ValidationErrorResponse(ErrorResponse):
    """Respuesta de error de validación."""
    error: str = "validation_error"
    field: Optional[str] = None


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
